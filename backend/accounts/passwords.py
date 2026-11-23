"""
A password here is a signature, so guessing one has to stop quickly, nobody else
may know it, and a person's own choice is the one that counts.

- Five wrong passwords in a row lock the account for fifteen minutes, wherever
  they were typed: the sign-in page, the admin site or a signature prompt.
- A password an administrator sets is temporary: the person chooses their own
  before they can do anything else.
- The last five passwords cannot be used again, and a password expires.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record
from .models import PasswordHistory, User

MAX_FAILURES = 5
LOCKED_FOR = timedelta(minutes=15)
REMEMBERED = 5


def is_locked(user) -> bool:
    return user.locked_until is not None and user.locked_until > timezone.now()


def note_failure(user):
    if is_locked(user):
        return
    with transaction.atomic():
        fresh = User.objects.select_for_update().get(pk=user.pk)
        fresh.failed_logins += 1
        locked = fresh.failed_logins >= MAX_FAILURES
        if locked:
            fresh.failed_logins = 0
            fresh.locked_until = timezone.now() + LOCKED_FOR
        fresh.save(update_fields=["failed_logins", "locked_until"])
    user.failed_logins, user.locked_until = fresh.failed_logins, fresh.locked_until
    if locked:
        record(None, "ACCOUNT_LOCKED", "user", user.username)


def note_success(user):
    if user.failed_logins or user.locked_until:
        User.objects.filter(pk=user.pk).update(failed_logins=0, locked_until=None)
        user.failed_logins, user.locked_until = 0, None


def confirm_password(user, password) -> bool:
    """Every signature comes through here, so a signature prompt is no way round the lockout."""
    if is_locked(user):
        return False
    if password and user.check_password(password):
        note_success(user)
        return True
    note_failure(user)
    return False


def needs_new_password(user) -> bool:
    if user.must_change_password:
        return True
    changed = user.password_changed_at or user.date_joined
    return timezone.now() - changed > timedelta(days=settings.QCLAB_PASSWORD_MAX_AGE_DAYS)


def _store(user, password: str, temporary: bool):
    user.set_password(password)
    user.must_change_password = temporary
    user.password_changed_at = timezone.now()
    user.failed_logins = 0
    user.locked_until = None


def _remember(user):
    PasswordHistory.objects.create(user=user, password=user.password)


def set_temporary_password(user, password: str):
    """What an administrator does. They may know this one, so it does not last."""
    _store(user, password, temporary=True)
    if user.pk:
        user.save(update_fields=[
            "password", "must_change_password", "password_changed_at", "failed_logins", "locked_until",
        ])
        _remember(user)


def remember_first_password(user):
    _remember(user)


def _recently_used(user, password: str) -> bool:
    earlier = user.password_history.order_by("-changed_at", "-id")[:REMEMBERED]
    return user.check_password(password) or any(check_password(password, e.password) for e in earlier)


def set_own_password(user, password: str):
    """Raises ValidationError with messages for the person choosing it."""
    validate_password(password, user)
    if _recently_used(user, password):
        raise ValidationError("You have used that password recently. Choose a different one.")
    _store(user, password, temporary=False)
    user.save(update_fields=[
        "password", "must_change_password", "password_changed_at", "failed_logins", "locked_until",
    ])
    _remember(user)
