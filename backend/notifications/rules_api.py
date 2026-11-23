"""Administration of the notification rules: which alerts go out, and who else hears."""
from smtplib import SMTPException

from django.core.mail import EmailMessage
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.authz import RequiresPermission
from accounts.models import Role
from audit.services import record
from .email import email_ready
from .rules import EVENTS, rule_for

CanManageRules = RequiresPermission.of("notification.manage")
MAX_DAYS = 60


def _rule_payload(event: str) -> dict:
    spec = EVENTS[event]
    rule = rule_for(event)
    return {
        "event": event,
        "label": spec["label"],
        "hint": spec["hint"],
        "enabled": rule.enabled,
        "takes_roles": spec.get("roles", False),
        "role_ids": sorted(rule.roles.values_list("id", flat=True)),
        "takes_days_before": spec.get("days_before", False),
        "days_before": rule.days_before,
        "takes_repeat": spec.get("repeat", False),
        "repeat_days": rule.repeat_days,
        "email": rule.email,
        "updated_at": rule.updated_at,
    }


def _days(raw, what: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number of days.")
    if not 0 <= value <= MAX_DAYS:
        raise ValueError(f"{what} must be between 0 and {MAX_DAYS} days.")
    return value


@api_view(["GET"])
@permission_classes([CanManageRules])
def notification_rules(request):
    return Response({
        "rules": [_rule_payload(event) for event in EVENTS],
        "roles": [{"id": r.id, "name": r.name} for r in Role.objects.filter(is_active=True).order_by("name")],
        "email_ready": email_ready(),
    })


@api_view(["POST"])
@permission_classes([CanManageRules])
def test_email(request):
    """Sends straight away, to the person asking, so a wrong setting shows here and not in a silent queue."""
    if not email_ready():
        return Response({"detail": "No mail server is set up yet."}, status=status.HTTP_400_BAD_REQUEST)
    if not request.user.email:
        return Response({"detail": "Your account has no email address. Add one on the Users screen first."},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        EmailMessage(subject="QC Lab test email", body="Email from QC Lab is working.", to=[request.user.email]).send()
    except (SMTPException, OSError) as e:
        return Response({"detail": f"The mail server did not take it: {e}"}, status=status.HTTP_400_BAD_REQUEST)
    record(request.user, "EMAIL_TEST_SENT", "notification rule", "email", to=request.user.email)
    return Response({"to": request.user.email})


@api_view(["PUT"])
@permission_classes([CanManageRules])
def notification_rule(request, event):
    if event not in EVENTS:
        return Response({"detail": "No such notification."}, status=status.HTTP_404_NOT_FOUND)
    spec = EVENTS[event]
    rule = rule_for(event)
    try:
        days_before = _days(request.data.get("days_before", rule.days_before), "The warning") \
            if spec.get("days_before") else rule.days_before
        repeat_days = _days(request.data.get("repeat_days", rule.repeat_days), "The reminder") \
            if spec.get("repeat") else rule.repeat_days
    except ValueError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    rule.enabled = bool(request.data.get("enabled", rule.enabled))
    rule.days_before = days_before
    rule.repeat_days = repeat_days
    rule.email = bool(request.data.get("email", rule.email))
    rule.updated_by = request.user
    rule.save()
    if spec.get("roles") and isinstance(request.data.get("role_ids"), list):
        rule.roles.set(Role.objects.filter(pk__in=[r for r in request.data["role_ids"] if str(r).isdigit()]))
    record(request.user, "NOTIFICATION_RULE_CHANGED", "notification rule", event, label=spec["label"],
           enabled=rule.enabled, days_before=days_before, repeat_days=repeat_days, email=rule.email,
           roles=sorted(rule.roles.values_list("name", flat=True)))
    return Response(_rule_payload(event))
