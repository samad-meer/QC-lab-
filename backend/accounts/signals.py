"""Every sign-in, wherever it happens, so the admin site is not a way round the trail."""
import time

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from audit.middleware import client_ip
from audit.services import record
from .models import User
from .passwords import note_failure, note_success


@receiver(user_logged_in)
def signed_in(sender, request, user, **kwargs):
    note_success(user)
    record(user, "LOGIN", "auth", user.username)
    # What the Sign-in and sessions screen shows of this session: when it began, from
    # where, on what. The session is new here (login() cycled its key), so it is theirs.
    if request is not None and hasattr(request, "session"):
        now = time.time()
        request.session["signed_in_at"] = now
        request.session["last_activity"] = now
        request.session["ip"] = client_ip(request)
        request.session["agent"] = (request.META.get("HTTP_USER_AGENT") or "")[:300]


@receiver(user_login_failed)
def failed_to_sign_in(sender, credentials, **kwargs):
    """What was typed is kept only if it is a real username: it may be someone's password."""
    user = User.objects.filter(username__iexact=credentials.get("username") or "").first()
    name = user.username if user else "an unknown user"
    record(None, "LOGIN_FAILED", "auth", name, username=name)
    if user is not None:
        note_failure(user)
