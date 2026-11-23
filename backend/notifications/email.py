"""
Email for notifications. Nothing here runs until a mail server is named in the
settings; the bell in the app works either way. See models.EmailOutbox for why
emails are queued rather than sent where the notification is written.
"""
from datetime import timedelta
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from audit.services import record
from .models import EmailOutbox

BATCH = 20
MAX_ATTEMPTS = 6
WAIT_MINUTES = 5  # after a failure, times the number of attempts so far


def email_ready() -> bool:
    return bool(settings.EMAIL_HOST)


def queue_email(notification):
    if email_ready() and notification.recipient.email:
        EmailOutbox.objects.create(notification=notification, to=notification.recipient.email)


def _message(notification, to: str) -> EmailMessage:
    link = f"{settings.QCLAB_BASE_URL}{notification.link}" if settings.QCLAB_BASE_URL and notification.link else ""
    return EmailMessage(
        subject=notification.title,
        body="\n\n".join(part for part in (notification.title, notification.body, link) if part),
        to=[to],
    )


def _note_failure(row, error: Exception):
    row.attempts += 1
    row.last_error = str(error)[:300]
    row.next_try = timezone.now() + timedelta(minutes=WAIT_MINUTES * row.attempts)
    row.save(update_fields=["attempts", "last_error", "next_try"])
    if row.attempts >= MAX_ATTEMPTS:
        record(None, "EMAIL_FAILED", "notification", row.notification_id, title=row.notification.title,
               to=row.to, error=row.last_error)


def send_queued() -> int:
    """Send what is waiting and due a try. Stops at the first failure: the server is probably down."""
    if not email_ready():
        return 0
    waiting = EmailOutbox.objects.filter(
        sent_at__isnull=True, attempts__lt=MAX_ATTEMPTS, next_try__lte=timezone.now()
    ).order_by("id").values_list("pk", flat=True)[:BATCH]
    sent = 0
    for pk in list(waiting):
        with transaction.atomic():
            # Two people's bells can check at once: each email goes to whichever got the row.
            row = EmailOutbox.objects.select_for_update(skip_locked=True).filter(pk=pk, sent_at__isnull=True).first()
            if row is None:
                continue
            try:
                _message(row.notification, row.to).send()
            except (SMTPException, OSError) as e:
                _note_failure(row, e)
                break
            row.sent_at = timezone.now()
            row.save(update_fields=["sent_at"])
            sent += 1
    return sent
