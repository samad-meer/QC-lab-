"""
Reviewing the trail is a task in itself, and a record of it. Each review picks up
where the last one stopped, so no period goes unread and none is read twice.

Nobody signs off a period that holds their own administrator overrides: those are
what the review exists to look at.
"""
from django.db import transaction
from django.utils import timezone

from accounts.passwords import confirm_password
from .models import AuditEvent, AuditReview
from .services import record


class ReviewError(Exception):
    """A refused review. The message is written for the person who tried."""


def latest_review():
    return AuditReview.objects.order_by("-covered_to", "-id").first()


def unreviewed_events():
    latest = latest_review()
    return AuditEvent.objects.filter(at__gt=latest.covered_to) if latest else AuditEvent.objects.all()


def record_review(by, findings: str, password: str) -> AuditReview:
    findings = (findings or "").strip()[:2000]
    if not findings:
        raise ReviewError("Say what you reviewed and what you found, even if that is nothing.")
    if not confirm_password(by, password):
        record(by, "SIGN_PASSWORD_FAILED", "audit trail", "review", meaning="audit review")
        raise ReviewError("Password incorrect. The review was not recorded.")
    with transaction.atomic():
        latest = AuditReview.objects.select_for_update().order_by("-covered_to", "-id").first()
        now = timezone.now()
        events = unreviewed_events().filter(at__lte=now)
        own = events.filter(actor=by, details__has_key="override").count()
        if own:
            raise ReviewError(
                f"This period holds {own} administrator override(s) of your own, so someone else must review it."
            )
        first = events.order_by("at").values_list("at", flat=True).first()
        review = AuditReview.objects.create(
            reviewed_by=by, name_snapshot=by.display_name(), covered_from=latest.covered_to if latest else first or now,
            covered_to=now, events=events.count(), findings=findings,
        )
        record(by, "AUDIT_REVIEWED", "audit trail", "review", events=review.events, findings=findings[:300])
    return review
