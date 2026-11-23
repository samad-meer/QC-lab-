"""
Administration API: roles, their permissions, and users.

Every change here is written to the audit trail, and permission grants are
append-only — a revoke is a new state on the old row, never a delete. That
is what lets you answer "who could approve a certificate on 3 March?".
"""
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from audit.analytics import build
from audit.describe import RETURN_ACTIONS, describe, sample_reference
from audit.reviews import ReviewError, latest_review, record_review, unreviewed_events
from audit.models import AuditEvent
from audit.services import record
from lims.models import Section
from qclab.listing import paginated, window_from
from reports.list_export import Col, ListExport
from .authz import RequiresPermission, has_perm
from .lab_zone import is_zone
from .models import LabConfig, Role, RolePermissionGrant, User
from .permissions_registry import FEATURES, HIDEABLE
from .passwords import remember_first_password, set_temporary_password
from .photos import PhotoError, clean_logo
from .serializers import (
    GrantHistorySerializer,
    RoleSerializer,
    UserAdminSerializer,
    known_permission,
    permission_catalogue,
)

CanManageRoles = RequiresPermission.of("role.manage")
CanManageUsers = RequiresPermission.of("user.manage")
CanViewAudit = RequiresPermission.of("audit.view")


def _bad(msg):
    return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)


# ----------------------------------------------------------------- catalogue


@api_view(["GET"])
def permissions_catalogue(request):
    """
    The permission vocabulary, plus what the caller holds. Readable by any
    signed-in user: everyone is entitled to see the rules they work under.
    """
    from .permissions_registry import SEGREGATION_CONFLICTS

    return Response(
        {
            "modules": permission_catalogue(),
            "mine": sorted(request.user.permissions()),
            # Switched off for everyone in Settings: the role editor says so beside each.
            "hidden": sorted(LabConfig.hidden()),
            # Sent so the role editor can warn live, without duplicating the
            # list in the frontend and letting the two drift apart.
            "conflict_pairs": [
                {"a": a, "b": b, "message": msg} for a, b, msg in SEGREGATION_CONFLICTS
            ],
        }
    )


# --------------------------------------------------------------------- roles


@api_view(["GET", "POST"])
@permission_classes([CanManageRoles])
def roles(request):
    if request.method == "GET":
        return Response(RoleSerializer(Role.objects.all(), many=True).data)

    code = (request.data.get("code") or "").strip().upper().replace(" ", "_")
    name = (request.data.get("name") or "").strip()
    if not code or not name:
        return _bad("A role needs a code and a name.")
    if Role.objects.filter(code=code).exists():
        return _bad(f"A role with the code {code} already exists.")

    role = Role.objects.create(
        code=code, name=name, description=(request.data.get("description") or "").strip()
    )
    record(request.user, "ROLE_CREATED", "role", role.code, name=name)
    return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([CanManageRoles])
def role_detail(request, pk):
    role = get_object_or_404(Role, pk=pk)

    if request.method == "GET":
        return Response(RoleSerializer(role).data)

    if request.method == "DELETE":
        try:
            code = role.code
            role.delete()
        except PermissionError as e:
            return _bad(str(e))
        except ProtectedError:
            return _bad(f"{role.name} signs a stage in a review workflow, so it stays on record.")
        record(request.user, "ROLE_DELETED", "role", code)
        return Response(status=status.HTTP_204_NO_CONTENT)

    was = {"name": role.name, "description": role.description, "is_active": role.is_active}
    changed = {}
    for field in ("name", "description"):
        if field in request.data:
            value = (request.data.get(field) or "").strip()
            if field == "name" and not value:
                return _bad("A role needs a name.")
            if getattr(role, field) != value:
                changed[field] = value
                setattr(role, field, value)
    if "is_active" in request.data:
        active = bool(request.data["is_active"])
        if not active and role.users.filter(is_active=True).exists():
            return _bad(
                f"{role.name} is still held by {role.users.filter(is_active=True).count()} active "
                "user(s). Move them first."
            )
        if role.is_active != active:
            changed["is_active"] = active
            role.is_active = active
    if changed:
        role.save()
        record(request.user, "ROLE_UPDATED", "role", role.code, was={k: was[k] for k in changed}, **changed)
    return Response(RoleSerializer(role).data)


@api_view(["PUT"])
@permission_classes([CanManageRoles])
def role_permissions(request, pk):
    """
    Set the whole permission set for a role. Differences become grants and
    revokes; nothing is edited in place, so the history stays complete.
    """
    role = get_object_or_404(Role, pk=pk)
    wanted = set(request.data.get("permissions") or [])
    reason = (request.data.get("reason") or "").strip()

    unknown = sorted(k for k in wanted if not known_permission(k))
    if unknown:
        return _bad(f"Unknown permission(s): {', '.join(unknown)}")

    current = role.permissions()
    to_grant = wanted - current
    to_revoke = current - wanted
    if not to_grant and not to_revoke:
        return Response(RoleSerializer(role).data)
    if not reason:
        return _bad("Say why this role's access is changing.")

    # An administrator must not be able to widen their own access.
    if role.users.filter(pk=request.user.pk).exists() and to_grant:
        return _bad(
            "You cannot add permissions to a role you hold yourself. "
            "Ask another administrator to make this change."
        )
    # What their role gives them, hidden or not: hiding a report must not stop anyone granting it.
    beyond = sorted(to_grant - request.user.granted_permissions())
    if beyond:
        return _bad(f"You cannot give a role access you do not hold yourself: {', '.join(beyond)}.")

    with transaction.atomic():
        for key in sorted(to_revoke):
            grant = role.grants.filter(permission=key, revoked_at__isnull=True).first()
            if grant:
                grant.revoke(request.user, reason)
        for key in sorted(to_grant):
            RolePermissionGrant.objects.create(
                role=role, permission=key, granted_by=request.user, reason=reason
            )
        record(
            request.user, "ROLE_PERMISSIONS_CHANGED", "role", role.code,
            granted=sorted(to_grant), revoked=sorted(to_revoke), reason=reason,
        )
    role.refresh_from_db()
    data = RoleSerializer(role).data
    data["warnings"] = role.conflicts()
    return Response(data)


@api_view(["GET"])
@permission_classes([CanManageRoles])
def role_history(request, pk):
    """Every grant and revoke this role has ever had — nothing is removed."""
    role = get_object_or_404(Role, pk=pk)
    return Response(GrantHistorySerializer(role.grants.all(), many=True).data)


# --------------------------------------------------------------------- users


@api_view(["GET"])
@permission_classes([CanManageUsers])
def role_options(request):
    """The roles to choose from when setting up a user. Changing what they hold is another permission."""
    return Response(RoleSerializer(Role.objects.all(), many=True).data)


def _beyond_you(actor, role) -> bool:
    """Handing out a role, or taking over an account, must not widen what the actor can reach."""
    return bool(role.permissions() - actor.granted_permissions())


def _end_sessions(user):
    """Otherwise a blocked person's session wakes up, with no password, the moment they are allowed back."""
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if session.get_decoded().get(SESSION_KEY) == str(user.pk):
            session.delete()


def _account_state(u) -> str:
    if not u.is_active:
        return "Deactivated"
    return "Active" if u.may_sign_in() else "Active, but cannot sign in"


USER_EXPORT = ListExport(
    key="users",
    title="Users",
    columns=[
        Col("Name", lambda u: u.display_name(), 1.4),
        Col("Employee ID", lambda u: u.employee_id or "", 0.9),
        Col("Username", lambda u: u.username, 1),
        Col("Designation", lambda u: u.designation, 1.1),
        Col("Role", lambda u: u.role.name if u.role_id else "", 1),
        Col("Sections", lambda u: ", ".join(s.code for s in u.sections.all()), 1),
        Col("Email", lambda u: u.email, 1.5),
        Col("Phone", lambda u: u.phone, 0.9),
        Col("Joined", lambda u: u.joining_date, 0.8),
        Col("Last sign-in", lambda u: u.last_login, 1.1),
        Col("Account", lambda u: _account_state(u), 0.9),
    ],
)


@api_view(["GET", "POST"])
@permission_classes([CanManageUsers])
def users(request):
    if request.method == "GET":
        qs = User.objects.select_related("role").prefetch_related("sections").order_by(
            "-is_active", "first_name", "username"
        )
        return paginated(
            request, qs, lambda rows: UserAdminSerializer(rows, many=True).data,
            export=USER_EXPORT,
            active=User.objects.filter(is_active=True).count(),
        )

    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    if not username:
        return _bad("A username is required.")
    if User.objects.filter(username__iexact=username).exists():
        return _bad(f"The username {username} is already taken.")
    role = get_object_or_404(Role, pk=request.data.get("role_id"))
    if _beyond_you(request.user, role):
        return _bad(f"You cannot give someone the {role.name} role: it has access you do not hold.")

    employee_id = (request.data.get("employee_id") or "").strip() or None
    if employee_id and User.objects.filter(employee_id__iexact=employee_id).exists():
        return _bad(f"Employee ID {employee_id} is already used by another person.")

    user = User(
        username=username,
        first_name=(request.data.get("first_name") or "").strip(),
        last_name=(request.data.get("last_name") or "").strip(),
        email=(request.data.get("email") or "").strip(),
        employee_id=employee_id,
        designation=(request.data.get("designation") or "").strip(),
        joining_date=request.data.get("joining_date") or None,
        phone=(request.data.get("phone") or "").strip(),
        role=role,
    )
    try:
        validate_password(password, user)
        user.full_clean(exclude=["password"])
    except ValidationError as e:
        return _bad(" ".join(m for msgs in getattr(e, "message_dict", {"": e.messages}).values() for m in msgs))
    set_temporary_password(user, password)
    user.save()
    remember_first_password(user)
    user.sections.set(Section.objects.filter(pk__in=request.data.get("section_ids") or []))
    record(
        request.user, "USER_CREATED", "user", user.username,
        name=user.display_name(), role=role.code,
        employee_id=user.employee_id or "—", designation=user.designation or "—",
        joining_date=str(user.joining_date) if user.joining_date else "—",
        sections=list(user.sections.values_list("code", flat=True)),
    )
    return Response(UserAdminSerializer(user).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([CanManageUsers])
def user_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    was = {
        **{f: str(getattr(user, f) or "—") for f in (
            "first_name", "last_name", "email", "designation", "phone", "employee_id", "joining_date",
        )},
        "is_active": str(user.is_active),
        "role": user.role.code if user.role else "—",
        "sections": sorted(user.sections.values_list("code", flat=True)),
    }
    changed = {}

    for field in ("first_name", "last_name", "email", "designation", "phone"):
        if field in request.data:
            value = (request.data.get(field) or "").strip()
            if getattr(user, field) != value:
                changed[field] = value
                setattr(user, field, value)

    if "employee_id" in request.data:
        value = (request.data.get("employee_id") or "").strip() or None
        if value and User.objects.filter(employee_id__iexact=value).exclude(pk=user.pk).exists():
            return _bad(f"Employee ID {value} is already used by another person.")
        if user.employee_id != value:
            changed["employee_id"] = value or "—"
            user.employee_id = value

    if "joining_date" in request.data:
        value = request.data.get("joining_date") or None
        if str(user.joining_date or "") != str(value or ""):
            changed["joining_date"] = str(value or "—")
            user.joining_date = value

    if "role_id" in request.data:
        role = get_object_or_404(Role, pk=request.data["role_id"])
        if user.pk == request.user.pk and role.pk != user.role_id:
            return _bad("You cannot change your own role. Ask another administrator.")
        if role.pk != user.role_id and _beyond_you(request.user, role):
            return _bad(f"You cannot give someone the {role.name} role: it has access you do not hold.")
        if user.role_id != role.pk:
            changed["role"] = f"{user.role.code if user.role else '—'} → {role.code}"
            user.role = role

    if "is_active" in request.data:
        active = bool(request.data["is_active"])
        if user.pk == request.user.pk and not active:
            return _bad("You cannot deactivate your own account.")
        if active and not user.has_working_role():
            return _bad(f"{user.display_name()} has no active role, so they still could not sign in. "
                        "Give them a role on the Users screen first.")
        if user.is_active != active:
            changed["is_active"] = active
            user.is_active = active

    if changed:
        try:
            user.full_clean(exclude=["password"])
        except ValidationError as e:
            return _bad(" ".join(m for msgs in getattr(e, "message_dict", {"": e.messages}).values() for m in msgs))
        user.save()
        if changed.get("is_active") is False:
            _end_sessions(user)

    if "section_ids" in request.data:
        sections = Section.objects.filter(pk__in=request.data["section_ids"] or [])
        before = set(user.sections.values_list("code", flat=True))
        user.sections.set(sections)
        after = set(user.sections.values_list("code", flat=True))
        if before != after:
            changed["sections"] = sorted(after)

    if changed:
        record(request.user, "USER_UPDATED", "user", user.username, was={k: was[k] for k in changed}, **changed)
    return Response(UserAdminSerializer(user).data)


@api_view(["POST"])
@permission_classes([CanManageUsers])
def reset_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.role_id and _beyond_you(request.user, user.role):
        return _bad(f"{user.display_name()} has access you do not hold, so someone with that access must do this.")
    password = request.data.get("password") or ""
    try:
        validate_password(password, user)
    except ValidationError as e:
        return _bad(" ".join(e.messages))
    set_temporary_password(user, password)
    # The password itself is never recorded — only that it was reset.
    record(request.user, "PASSWORD_RESET", "user", user.username)
    return Response({"detail": f"Password reset for {user.display_name()}."})


# ----------------------------------------------------------------- lab details

CanManageConfig = RequiresPermission.of("config.manage")

CONFIG_TEXT_FIELDS = (
    "lab_name", "app_tagline", "company_name", "address", "licence_no",
    "phone", "email", "website", "footer_note", "time_zone", "time_format",
)


def _config_payload(cfg) -> dict:
    return {
        **{f: getattr(cfg, f) for f in CONFIG_TEXT_FIELDS},
        "logo_url": f"/api/auth/lab/logo/?v={cfg.logo.name.rsplit('/', 1)[-1]}" if cfg.logo else None,
    }


@api_view(["GET", "PATCH"])
@permission_classes([CanManageConfig])
def lab_config(request):
    """
    The lab's letterhead. This is presentation only — it never changes what
    a certificate contains, which is fixed by design.
    """
    cfg = LabConfig.get()
    if request.method == "GET":
        return Response(_config_payload(cfg))

    was = {f: getattr(cfg, f) for f in CONFIG_TEXT_FIELDS}
    changed = {}
    for field in CONFIG_TEXT_FIELDS:
        if field in request.data:
            value = (request.data.get(field) or "").strip()
            if field == "lab_name" and not value:
                return _bad(f"{field.replace('_', ' ').capitalize()} cannot be empty.")
            if field == "time_zone" and not is_zone(value):
                return _bad("Choose a time zone from the list.")
            if field == "time_format" and value not in ("12h", "24h"):
                return _bad("Choose a 12-hour or a 24-hour clock.")
            if getattr(cfg, field) != value:
                changed[field] = value
                setattr(cfg, field, value)
    if changed:
        try:
            cfg.full_clean()
        except ValidationError as e:
            return _bad(" ".join(m for msgs in e.message_dict.values() for m in msgs))
        cfg.save()
        record(request.user, "LAB_CONFIG_UPDATED", "config", "lab", was={k: was[k] for k in changed}, **changed)
    return Response(_config_payload(cfg))


def _features_payload(cfg) -> dict:
    hidden = set(cfg.hidden_features or [])
    return {
        "modules": [
            {
                "key": key, "name": name, "help": help_, "whole": whole,
                "parts": [{"key": k, "label": label, "group": group} for k, label, group in parts],
            }
            for key, name, help_, whole, parts in FEATURES
        ],
        "hidden": sorted(hidden & set(HIDEABLE)),
    }


@api_view(["GET", "PUT"])
@permission_classes([CanManageConfig])
def lab_features(request):
    """
    What the lab shows. A hidden feature is gone for everyone, administrators too,
    until it is shown again; its records and the rules about them stay as they were.
    """
    cfg = LabConfig.get()
    if request.method == "GET":
        return Response(_features_payload(cfg))
    wanted = request.data.get("hidden") if isinstance(request.data, dict) else None
    if not isinstance(wanted, list) or not all(isinstance(k, str) for k in wanted):
        return _bad("Send the list of features to hide.")
    unknown = sorted(set(wanted) - set(HIDEABLE))
    if unknown:
        return _bad(f"These cannot be hidden: {', '.join(unknown)}.")
    was = set(cfg.hidden_features or [])
    now = set(wanted)
    if now != was:
        cfg.hidden_features = sorted(now)
        cfg.save(update_fields=["hidden_features"])
        record(
            request.user, "FEATURES_CHANGED", "config", "lab",
            hidden=", ".join(HIDEABLE[k] for k in sorted(now - was)) or "nothing",
            shown=", ".join(HIDEABLE[k] for k in sorted(was - now)) or "nothing",
        )
    return Response(_features_payload(cfg))


@api_view(["POST", "DELETE"])
@parser_classes([MultiPartParser])
@permission_classes([CanManageConfig])
def lab_logo(request):
    cfg = LabConfig.get()
    if request.method == "DELETE":
        if not cfg.logo:
            return _bad("There is no logo to remove.")
        cfg.clear_logo()
        record(request.user, "LAB_LOGO_REMOVED", "config", "lab")
        return Response(_config_payload(cfg))
    try:
        cleaned = clean_logo(request.FILES.get("logo"))
    except PhotoError as e:
        return _bad(str(e))
    cfg.replace_logo(cleaned)
    record(request.user, "LAB_LOGO_CHANGED", "config", "lab")
    return Response(_config_payload(cfg))


@api_view(["GET"])
@permission_classes([AllowAny])
def lab_logo_file(request):
    """Public: the sign-in page shows it before anyone signs in, and it prints on every certificate."""
    cfg = LabConfig.get()
    if not cfg.logo:
        raise Http404("No logo.")
    try:
        handle = cfg.logo.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("No logo.")
    response = FileResponse(handle, content_type="image/png")
    response["Cache-Control"] = "private, max-age=300"
    return response


# --------------------------------------------------------------- audit trail


def _needs_review() -> Q:
    """The rows a periodic review goes looking for."""
    return (
        Q(action__contains="REFUSED") | Q(action__contains="FAILED")
        | Q(action__startswith="ADMIN_SITE_") | Q(details__has_key="override")
        | Q(action__in=["RESULT_SUPERSEDED", *RETURN_ACTIONS])
    )


def _audit_row(e) -> dict:
    told = describe(e)
    return {
        "id": e.id,
        "at": e.at,
        "actor": e.actor_username or "system",
        "actor_name": e.actor.display_name() if e.actor_id else "System",
        "action": e.action,
        "entity": e.entity,
        "entity_id": e.entity_id,
        "details": e.details,
        "ip_address": e.ip_address or "",
        "sentence": told["sentence"],
        "severity": told["severity"],
        "notable": told["notable"],
        "sample_no": sample_reference(e),
    }


@api_view(["GET", "POST"])
@permission_classes([CanViewAudit])
def audit_reviews(request):
    """Who has reviewed the trail, how far, and how much has happened since."""
    if request.method == "POST":
        try:
            record_review(request.user, request.data.get("findings"), request.data.get("password", ""))
        except ReviewError as e:
            return _bad(str(e))
    latest = latest_review()
    return Response({
        "latest": latest and {
            "name": latest.name_snapshot, "reviewed_at": latest.reviewed_at, "findings": latest.findings,
            "events": latest.events, "covered_from": latest.covered_from, "covered_to": latest.covered_to,
        },
        "unreviewed": unreviewed_events().count(),
    })


AUDIT_EXPORT = ListExport(
    key="activity-log",
    title="Activity log",
    columns=[
        Col("When", lambda r: r["at"], 1.1),
        Col("Who", lambda r: f"{r['actor_name']} ({r['actor']})", 1.3),
        Col("What happened", lambda r: r["sentence"], 3.4),
        Col("Action", lambda r: r["action"], 1.2),
        Col("Record", lambda r: r["sample_no"] or r["entity_id"], 1),
        Col("Record type", lambda r: r["entity"], 0.8),
        Col("From", lambda r: r["ip_address"], 0.8),
    ],
    filters={
        "action": "Action", "actor": "Who", "entity_id": "Record",
        "notable": ("Showing", lambda _: "Only what needs review"),
        "override": ("Showing", lambda _: "Only administrator overrides"),
    },
    dates={"at": "When"},
    default_period="week",
    rows=lambda records, request: [_audit_row(e) for e in records],
)


@api_view(["GET"])
@permission_classes([CanViewAudit])
def audit_trail(request):
    """
    Read-only view of who did what, when, and from where. Periodic review of
    this is a regulatory expectation, so it needs to be reachable in the app.
    """
    qs = window_from(request, default="week").apply(AuditEvent.objects.select_related("actor"), "at")

    action = request.query_params.get("action")
    if action:
        qs = qs.filter(action=action)
    entity_id = request.query_params.get("entity_id")
    if entity_id:
        qs = qs.filter(entity_id__icontains=entity_id)
    actor = request.query_params.get("actor")
    if actor:
        qs = qs.filter(actor_username__icontains=actor)
    if request.query_params.get("notable") == "1":
        qs = qs.filter(_needs_review())
    if request.query_params.get("override") == "1":
        qs = qs.filter(details__has_key="override")

    return paginated(
        request, qs,
        lambda rows: [_audit_row(e) for e in rows],
        export=AUDIT_EXPORT,
        # Ordered here on purpose: the model's default order by time would defeat distinct().
        actions=list(AuditEvent.objects.order_by("action").values_list("action", flat=True).distinct()),
    )


@api_view(["GET"])
@permission_classes([CanViewAudit])
def analytics(request):
    """Derived lab statistics for a time window. Nothing here is stored."""
    window = window_from(request, default="week")
    data = build(window)

    # A short "needs attention" feed alongside the numbers.
    recent = window.apply(AuditEvent.objects.select_related("actor"), "at").filter(_needs_review())
    data["attention"] = [
        {
            "id": e.id, "at": e.at,
            "actor_name": e.actor.display_name() if e.actor_id else "System",
            "sentence": describe(e)["sentence"],
            "severity": describe(e)["severity"],
            "sample_no": sample_reference(e),
        }
        for e in recent[:12]
    ]
    return Response(data)
