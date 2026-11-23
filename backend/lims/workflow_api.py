"""
Administration API for review workflows: which signatures a certificate
needs after the analyst's, who signs each, and which products use them.

Every change is written to the audit trail. Stages are never edited in
place — saving a change makes a new version, and samples already
registered keep the version they were bound to.
"""
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.authz import RequiresPermission
from accounts.models import Role
from audit.services import record
from execution.config import clean_checklist, config_payload, create_items, item_config, items_of, signature
from execution.files import ALLOWED, MAX_UPLOAD_MB
from .models import Product, Sample, SampleStatus, Workflow, WorkflowStage, WorkflowVersion
from .serializers import stage_payload
from .workflow import MAX_STAGES, stage_code, stage_warnings

CanManageWorkflows = RequiresPermission.of("workflow.manage")

FIELD_MAX = 60


def _bad(msg):
    return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)


def _chain_text(cleaned, testing=None, receipt=None, certificate=None) -> str:
    """“Checked (Checker, 3 checks) → Approved (Lab head)” — for the audit trail."""
    def extras(d):
        out = [f"{len(d['checklist'])} check{'s' if len(d['checklist']) != 1 else ''}"] if d["checklist"] else []
        return out + (["must be accepted"] if d.get("requires_acceptance") else [])

    chain = " → ".join(
        f"{s['name']} ({', '.join([s['role'].name] + extras(s))})" for s in cleaned
    )
    if testing and extras(testing):
        chain = f"Testing ({', '.join(extras(testing))}) → " + chain
    if receipt and extras(receipt):
        chain = f"Receipt ({', '.join(extras(receipt))}) → " + chain
    if certificate and certificate["show_retests"]:
        chain += " · the certificate shows retests"
    return chain


def _stage_admin_payload(stage) -> dict:
    return {**stage_payload(stage), "checklist": [config_payload(i) for i in items_of(stage.version, stage)]}


def _testing_payload(version) -> dict:
    return {
        "requires_acceptance": bool(version and version.testing_requires_acceptance),
        "checklist": [config_payload(i) for i in items_of(version, None)],
    }


def _receipt_payload(version) -> dict:
    return {"checklist": [config_payload(i) for i in items_of(version, None, receipt=True)]}


def _certificate_payload(version) -> dict:
    return {"show_retests": bool(version and version.coa_show_retests)}


def _workflow_payload(wf: Workflow) -> dict:
    current = wf.current_version()
    stages = list(current.stages.select_related("role")) if current else []
    bound = Sample.objects.filter(workflow_version__workflow=wf)
    return {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description,
        "is_default": wf.is_default,
        "version": current.version if current else None,
        "changed_at": current.created_at if current else wf.created_at,
        "receipt": _receipt_payload(current),
        "testing": _testing_payload(current),
        "certificate": _certificate_payload(current),
        "stages": [_stage_admin_payload(s) for s in stages],
        "warnings": stage_warnings(stages),
        "sample_count": bound.count(),
        "in_review_count": bound.filter(status=SampleStatus.IN_REVIEW).count(),
    }


def _products_payload() -> list[dict]:
    return [
        {"id": p.id, "code": p.code, "name": p.name, "section": p.section.code, "workflow_id": p.workflow_id}
        for p in Product.objects.select_related("section").order_by("section__code", "name")
    ]


def _roles_payload() -> list[dict]:
    rows = Role.objects.filter(is_active=True).annotate(
        active_users=Count("users", filter=Q(users__is_active=True))
    )
    return [{"id": r.id, "name": r.name, "code": r.code, "user_count": r.active_users} for r in rows]


def _clean_stages(raw, actor) -> list[dict]:
    """Validate the stage list from the editor. Raises ValueError with a readable message."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("A workflow needs at least one review stage after the analyst.")
    if len(raw) > MAX_STAGES:
        raise ValueError(f"A workflow can have at most {MAX_STAGES} review stages.")

    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    roles = {r.id: r for r in Role.objects.filter(pk__in=[_int(s.get("role_id")) for s in raw if isinstance(s, dict)])}
    cleaned, taken = [], set()
    for i, s in enumerate(raw, start=1):
        if not isinstance(s, dict):
            raise ValueError(f"Stage {i} is not valid.")
        name = (s.get("name") or "").strip()
        title = (s.get("signature_title") or "").strip()
        holder = (s.get("holder_title") or "").strip()
        if not name:
            raise ValueError(f"Stage {i} needs a name, e.g. “Checked”.")
        if not title:
            raise ValueError(f"Stage {i} ({name}) needs a signature title, e.g. “Checked by”.")
        if max(len(name), len(title), len(holder)) > FIELD_MAX:
            raise ValueError(f"Stage {i} ({name}): keep each text under {FIELD_MAX} characters.")
        role = roles.get(_int(s.get("role_id")))
        if role is None:
            raise ValueError(f"Choose who signs stage {i} ({name}).")
        if not role.is_active:
            raise ValueError(f"The {role.name} role is inactive and cannot sign stage {i}.")
        # Mirrors "you cannot add permissions to a role you hold": an
        # administrator must not be able to make themselves a signer.
        if actor.role_id == role.id:
            raise ValueError(
                f"You cannot make your own role ({role.name}) a signer. Ask another administrator."
            )
        code = stage_code(name, taken)
        taken.add(code)
        cleaned.append({"order": i, "code": code, "name": name, "signature_title": title,
                        "holder_title": holder, "role": role,
                        "requires_acceptance": bool(s.get("requires_acceptance", False)),
                        "checklist": clean_checklist(s.get("checklist"), f"Stage {i} ({name})")})
    return cleaned


def _clean_testing(raw, current) -> dict:
    """The analyst's step. Not sent at all (an older screen) means: keep what it has now."""
    if raw is None:
        return {
            "requires_acceptance": bool(current and current.testing_requires_acceptance),
            "checklist": [item_config(i) for i in items_of(current, None)],
        }
    if not isinstance(raw, dict):
        raise ValueError("The testing step's settings are not valid.")
    return {
        "requires_acceptance": bool(raw.get("requires_acceptance", False)),
        "checklist": clean_checklist(raw.get("checklist"), "Testing"),
    }


def _clean_receipt(raw, current) -> dict:
    """The front desk's checks on arrival. Not sent at all means: keep what it has now."""
    if raw is None:
        return {"checklist": [item_config(i) for i in items_of(current, None, receipt=True)]}
    if not isinstance(raw, dict):
        raise ValueError("The receipt checks are not valid.")
    return {"checklist": clean_checklist(raw.get("checklist"), "Receipt checks")}


def _clean_certificate(raw, current) -> dict:
    """What the certificate carries besides the results. Not sent means: keep it."""
    if raw is None:
        return {"show_retests": bool(current and current.coa_show_retests)}
    if not isinstance(raw, dict):
        raise ValueError("The certificate settings are not valid.")
    return {"show_retests": bool(raw.get("show_retests", False))}


def _same_stages(version, cleaned, testing, receipt, certificate) -> bool:
    if version is None:
        return False
    if version.testing_requires_acceptance != testing["requires_acceptance"] or signature(
        [item_config(i) for i in items_of(version, None)]
    ) != signature(testing["checklist"]):
        return False
    if signature([item_config(i) for i in items_of(version, None, receipt=True)]) != signature(receipt["checklist"]):
        return False
    if version.coa_show_retests != certificate["show_retests"]:
        return False
    current = [
        (s.name, s.signature_title, s.holder_title, s.role_id, s.requires_acceptance,
         signature([item_config(i) for i in items_of(version, s)]))
        for s in version.stages.all()
    ]
    wanted = [
        (s["name"], s["signature_title"], s["holder_title"], s["role"].id, s["requires_acceptance"],
         signature(s["checklist"]))
        for s in cleaned
    ]
    return current == wanted


def _new_version(wf: Workflow, cleaned, testing, receipt, certificate, actor, reason: str) -> WorkflowVersion:
    number = (wf.versions.aggregate(m=Max("version"))["m"] or 0) + 1
    version = WorkflowVersion.objects.create(
        workflow=wf, version=number, created_by=actor, reason=reason,
        testing_requires_acceptance=testing["requires_acceptance"],
        coa_show_retests=certificate["show_retests"],
    )
    create_items(version, None, receipt["checklist"], for_receipt=True)
    create_items(version, None, testing["checklist"])
    for s in cleaned:
        stage = WorkflowStage.objects.create(version=version, **{k: v for k, v in s.items() if k != "checklist"})
        create_items(version, stage, s["checklist"])
    return version


@api_view(["GET", "POST"])
@permission_classes([CanManageWorkflows])
def workflows(request):
    if request.method == "GET":
        return Response({
            "workflows": [_workflow_payload(wf) for wf in Workflow.objects.all()],
            "products": _products_payload(),
            "roles": _roles_payload(),
            "max_stages": MAX_STAGES,
            # What a document item may ask for — the server checks every upload against these.
            "file_types": sorted(ALLOWED),
            "max_upload_mb": MAX_UPLOAD_MB,
        })

    name = (request.data.get("name") or "").strip()
    reason = (request.data.get("reason") or "").strip()
    if not name:
        return _bad("Give the workflow a name.")
    if Workflow.objects.filter(name__iexact=name).exists():
        return _bad(f"A workflow called “{name}” already exists.")
    try:
        cleaned = _clean_stages(request.data.get("stages"), request.user)
        testing = _clean_testing(request.data.get("testing") or {}, None)
        receipt = _clean_receipt(request.data.get("receipt") or {}, None)
        certificate = _clean_certificate(request.data.get("certificate") or {}, None)
    except ValueError as e:
        return _bad(str(e))

    with transaction.atomic():
        wf = Workflow.objects.create(name=name, description=(request.data.get("description") or "").strip())
        _new_version(wf, cleaned, testing, receipt, certificate, request.user, reason)
        record(request.user, "WORKFLOW_CREATED", "workflow", wf.id,
               name=wf.name, stages=_chain_text(cleaned, testing, receipt, certificate), reason=reason)
    return Response(_workflow_payload(wf), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([CanManageWorkflows])
def workflow_detail(request, pk):
    wf = get_object_or_404(Workflow, pk=pk)

    if request.method == "DELETE":
        name = wf.name
        try:
            wf.delete()
        except PermissionError as e:
            return _bad(str(e))
        record(request.user, "WORKFLOW_DELETED", "workflow", pk, name=name)
        return Response(status=status.HTTP_204_NO_CONTENT)

    changed = {}
    if "name" in request.data:
        name = (request.data.get("name") or "").strip()
        if not name:
            return _bad("A workflow needs a name.")
        if Workflow.objects.filter(name__iexact=name).exclude(pk=wf.pk).exists():
            return _bad(f"A workflow called “{name}” already exists.")
        if name != wf.name:
            changed["name"] = name
    if "description" in request.data:
        description = (request.data.get("description") or "").strip()
        if description != wf.description:
            changed["description"] = description

    with transaction.atomic():
        if changed:
            for field, value in changed.items():
                setattr(wf, field, value)
            wf.save(update_fields=list(changed))
            record(request.user, "WORKFLOW_UPDATED", "workflow", wf.id, name=wf.name, **changed)
        if request.data.get("is_default") is True and not wf.is_default:
            previous = Workflow.default()
            # One default at a time (a DB constraint) — clear the old one first.
            Workflow.objects.filter(is_default=True).update(is_default=False)
            wf.is_default = True
            wf.save(update_fields=["is_default"])
            record(request.user, "WORKFLOW_DEFAULT_CHANGED", "workflow", wf.id,
                   name=wf.name, previous=previous.name if previous else "—")
    return Response(_workflow_payload(wf))


@api_view(["PUT"])
@permission_classes([CanManageWorkflows])
def workflow_stages(request, pk):
    """
    Replace the stage list. The change becomes a new version; samples
    already registered stay on the version they were bound to.
    """
    wf = get_object_or_404(Workflow, pk=pk)
    reason = (request.data.get("reason") or "").strip()
    current = wf.current_version()
    try:
        cleaned = _clean_stages(request.data.get("stages"), request.user)
        testing = _clean_testing(request.data.get("testing"), current)
        receipt = _clean_receipt(request.data.get("receipt"), current)
        certificate = _clean_certificate(request.data.get("certificate"), current)
    except ValueError as e:
        return _bad(str(e))

    if _same_stages(current, cleaned, testing, receipt, certificate):
        return Response(_workflow_payload(wf))
    if not reason:
        return _bad("Say why the workflow is changing.")

    with transaction.atomic():
        version = _new_version(wf, cleaned, testing, receipt, certificate, request.user, reason)
        record(request.user, "WORKFLOW_CHANGED", "workflow", wf.id, name=wf.name, version=version.version,
               stages=_chain_text(cleaned, testing, receipt, certificate), reason=reason)
    return Response(_workflow_payload(wf))


@api_view(["GET"])
@permission_classes([CanManageWorkflows])
def workflow_history(request, pk):
    """Every version this workflow has had — none is ever removed."""
    wf = get_object_or_404(Workflow, pk=pk)
    versions = wf.versions.select_related("created_by").annotate(samples_bound=Count("samples")).order_by("-version")
    return Response([
        {
            "version": v.version,
            "created_at": v.created_at,
            "created_by_name": v.created_by.display_name() if v.created_by else "System",
            "reason": v.reason,
            "sample_count": v.samples_bound,
            "receipt": _receipt_payload(v),
            "testing": _testing_payload(v),
            "certificate": _certificate_payload(v),
            "stages": [_stage_admin_payload(s) for s in v.stages.select_related("role")],
        }
        for v in versions
    ])


@api_view(["PUT"])
@permission_classes([CanManageWorkflows])
def product_workflow(request, pk):
    """Choose the workflow a product's future samples go through (null = the default)."""
    product = get_object_or_404(Product, pk=pk)
    raw = request.data.get("workflow_id")
    workflow = None
    if raw not in (None, ""):
        workflow = Workflow.objects.filter(pk=raw).first()
        if workflow is None:
            return _bad("That workflow does not exist.")
    if product.workflow_id != (workflow.id if workflow else None):
        before = product.workflow.name if product.workflow else "the default"
        product.workflow = workflow
        product.save(update_fields=["workflow"])
        record(request.user, "PRODUCT_WORKFLOW_CHANGED", "product", product.code,
               workflow=workflow.name if workflow else "the default", previous=before)
    return Response({"id": product.id, "workflow_id": product.workflow_id})
