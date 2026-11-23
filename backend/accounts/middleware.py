import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse

from audit.services import record
from .lab_zone import activate_lab_zone, deactivate_lab_zone
from .passwords import needs_new_password

GUARDED = ("/api/", "/site-admin/")
# What someone can still do while they must choose a new password.
OPEN_WHILE_PASSWORD_DUE = {
    "/api/auth/me/", "/api/auth/logout/", "/api/auth/csrf/", "/api/auth/config/", "/api/auth/change-password/",
}
# Do not write to the session on every request for the sake of a few seconds.
ACTIVITY_GRANULARITY = 30


class LabTimeZoneMiddleware:
    """Each request works in the lab's time zone, as set on the Settings screen."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        activate_lab_zone()
        try:
            return self.get_response(request)
        finally:
            deactivate_lab_zone()


class SessionGuardMiddleware:
    """
    An unattended bench PC does not stay signed in, and a session never outlives
    the working day (SESSION_COOKIE_AGE). A request the screen makes by itself says
    so with X-Background, so polling for notifications is not activity.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(GUARDED) and request.user.is_authenticated:
            refused = self._timed_out(request) or self._password_due(request)
            if refused is not None:
                return refused
        return self.get_response(request)

    def _timed_out(self, request):
        now = time.time()
        last = request.session.get("last_activity")
        idle_minutes = settings.QCLAB_IDLE_MINUTES
        if last is not None and now - last > idle_minutes * 60:
            record(request.user, "SESSION_TIMED_OUT", "auth", request.user.username)
            logout(request)
            return JsonResponse(
                {"detail": f"You were signed out after {idle_minutes} minutes without activity."}, status=401
            )
        working = request.headers.get("X-Background") != "1"
        if last is None or (working and now - last > ACTIVITY_GRANULARITY):
            request.session["last_activity"] = now
        return None

    def _password_due(self, request):
        if request.path in OPEN_WHILE_PASSWORD_DUE or not needs_new_password(request.user):
            return None
        return JsonResponse(
            {"detail": "Choose a new password before you continue.", "code": "password_change_required"},
            status=403,
        )
