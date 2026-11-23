"""
Alerts nobody asked for by acting: a result that fails, a certificate released,
and samples, calibrations and qualifications coming due.

Due dates pass on their own, with no action to hang a notification on, so they
are swept for. A scheduled `manage.py send_due_alerts` does it; and so that a
lab with no scheduler still gets them, so does the first notification check of
each hour.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from execution.rules import current_step_key, holder, step_of
from execution.services import candidates
from labrecords.models import InstrumentStatus, Qualification
from labrecords.services import instruments_with_next_due
from lims.models import FINISHED, Sample
from .email import send_queued
from .models import AlertSweep, Notification
from .rules import extra_people, rule_for
from .services import notify, notify_all, users_with

logger = logging.getLogger(__name__)
SWEEP_EVERY = timedelta(hours=1)


def failed_result(sample, test, value: str, actor):
    """Those who can decide what happens next hear at once — never the analyst deciding for themselves."""
    conflicted = {actor.id, sample.assigned_analyst_id}
    people = [u for u in users_with("result.retest.authorize") if u.id not in conflicted]
    people += extra_people(rule_for("FAILED_RESULT"))
    notify_all(people, "RESULT_FAILED", f"{test.name} failed on {sample.sample_no}",
               body=f"{value} against the limit {test.limit_text}. Entered by {actor.display_name()}.",
               sample=sample, actor=actor)


def certificate_released(certificate, sample, actor):
    """The work is finished: whoever started it, did it, or prints it hears."""
    people = [sample.assigned_analyst, sample.registered_by, *users_with("cert.print")]
    people += extra_people(rule_for("CERT_RELEASED"))
    notify_all(people, "CERT_RELEASED", f"The certificate for {sample.sample_no} is released",
               body=f"{sample.product.name} · {sample.batch_label}. Signed by {actor.display_name()}. It can now be printed.",
               link=f"/certificates/{certificate.id}", sample=sample, actor=actor)


def waiting_on(sample) -> list:
    """Who a sample is waiting for right now."""
    key = current_step_key(sample)
    if key is None:
        return []
    step = step_of(sample, key)
    if step.is_receipt:
        return list(users_with("sample.register"))
    who = holder(sample, step)
    if who is not None:
        return [who]
    return [sample.assigned_analyst] if step.is_testing else list(candidates(sample, step))


def _already_told(person, kind: str, sample, repeat_days: int, now) -> bool:
    last = Notification.objects.filter(recipient=person, kind=kind, sample=sample).order_by("-created_at").first()
    if last is None:
        return False
    return not repeat_days or (now - last.created_at).days < repeat_days


def _in_days(days: int) -> str:
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


def _days_ago(days: int) -> str:
    return f"{days} day{'' if days == 1 else 's'} ago"


def _record_due(people, rule, kinds: tuple, link: str, due, today, now, soon: str, late: str, body: str) -> int:
    """
    Warn about one dated record that has no sample behind it. The date, not the
    record, decides what has been said: a renewal moves the date, so the next
    cycle warns again.
    """
    days = (due - today).days
    if days > rule.days_before:
        return 0
    if days < 0:
        kind, title, since, repeat = kinds[1], late.format(when=_days_ago(-days)), due, rule.repeat_days
    else:
        kind, title, since, repeat = kinds[0], soon.format(when=_in_days(days)), due - timedelta(days=rule.days_before), 0
    sent = 0
    for person in {p.pk: p for p in people}.values():
        last = Notification.objects.filter(
            recipient=person, kind=kind, link=link, created_at__date__gte=since
        ).order_by("-created_at").first()
        if last is None or (repeat and (now - last.created_at).days >= repeat):
            sent += 1 if notify(person, kind, title, body=body, link=link) else 0
    return sent


def _calibration_alerts(today, now) -> int:
    rule = rule_for("CALIBRATION_DUE")
    if not rule.enabled:
        return 0
    people = [*users_with("instrument.manage"), *extra_people(rule)]
    sent = 0
    for instrument in instruments_with_next_due().filter(status=InstrumentStatus.IN_SERVICE).exclude(next_due=None):
        sent += _record_due(
            people, rule, ("CALIBRATION_DUE", "CALIBRATION_OVERDUE"), f"/lab/instruments/{instrument.pk}",
            instrument.next_due, today, now,
            f"{instrument.code} is due for calibration {{when}}",
            f"{instrument.code} ran out of calibration {{when}}",
            f"{instrument.name}, {instrument.location}. It cannot be used once its calibration has run out.",
        )
    return sent


def _qualification_alerts(today, now) -> int:
    rule = rule_for("QUALIFICATION_DUE")
    if not rule.enabled:
        return 0
    granters = [*users_with("qualification.manage"), *extra_people(rule)]
    # A renewal is a new row, so only the one running longest for each person and method counts.
    current = {}
    active = Qualification.objects.filter(revoked_at__isnull=True, user__is_active=True).select_related("user")
    for qualification in active.order_by("expires_on", "id"):
        current[(qualification.user_id, qualification.method)] = qualification
    sent = 0
    for q in current.values():
        name = q.user.display_name()
        sent += _record_due(
            [q.user, *granters], rule, ("QUALIFICATION_DUE", "QUALIFICATION_EXPIRED"), f"/lab/qualifications/{q.pk}",
            q.expires_on, today, now,
            f"{name}'s qualification on {q.method} expires {{when}}",
            f"{name}'s qualification on {q.method} expired {{when}}",
            f"Qualified until {q.expires_on:%d %b %Y}.",
        )
    return sent


def send_due_alerts(today=None) -> int:
    """Tell each person once about each due date (or again, if the rule repeats). Returns how many were sent."""
    now = timezone.now()
    today = today or timezone.localdate()
    soon, late = rule_for("DUE_SOON"), rule_for("OVERDUE")
    sent = 0
    for sample in Sample.objects.exclude(status__in=FINISHED).select_related("product", "assigned_analyst"):
        days = (sample.due_date - today).days
        if days < 0 and late.enabled:
            kind, rule, repeat = "OVERDUE", late, late.repeat_days
            title = f"{sample.sample_no} is {-days} day{'' if days == -1 else 's'} overdue"
        elif 0 <= days <= soon.days_before and soon.enabled:
            kind, rule, repeat = "DUE_SOON", soon, 0
            title = f"{sample.sample_no} is due {_in_days(days)}"
        else:
            continue
        for person in {p.pk: p for p in waiting_on(sample) + extra_people(rule)}.values():
            if not _already_told(person, kind, sample, repeat, now):
                notify(person, kind, title, body=f"{sample.product.name} · {sample.batch_label}. {sample.status_label()}.",
                       sample=sample)
                sent += 1
    return sent + _calibration_alerts(today, now) + _qualification_alerts(today, now)


def flush_email():
    """Called on every notification check, so email goes out without a scheduler."""
    try:
        send_queued()
    except Exception:  # a mail problem must never take the bell down with it
        logger.exception("Sending queued email failed")


def sweep_if_due():
    """Called on every notification check; does its work at most once an hour, across all users."""
    now = timezone.now()
    AlertSweep.objects.get_or_create(pk=1, defaults={"last_run": now - 2 * SWEEP_EVERY})
    if not AlertSweep.objects.filter(pk=1, last_run__lte=now - SWEEP_EVERY).update(last_run=now):
        return
    try:
        send_due_alerts()
    except Exception:  # a failed sweep must never take the bell down with it
        logger.exception("The due-date sweep failed")
