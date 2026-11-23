from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from audit.services import record
from .lab_zone import lab_zone_name
from .models import LabConfig, User
from .passwords import confirm_password, set_own_password
from .serializers import UserSerializer


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf(request):
    """Prime the CSRF cookie for the SPA and return the token."""
    return Response({"csrfToken": get_token(request)})


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    # An anonymous request skips DRF's own check, and a page elsewhere could
    # otherwise sign a colleague in to the wrong account.
    SessionAuthentication().enforce_csrf(request)
    data = request.data if isinstance(request.data, dict) else {}
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))
    # The signals in accounts/signals.py record both outcomes and count failures.
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response(
            {"detail": "Invalid username or password. After five failed attempts an account is locked "
                       "for 15 minutes."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    login(request, user)
    return Response(UserSerializer(user).data)


@api_view(["POST"])
def logout_view(request):
    record(request.user, "LOGOUT", "auth", request.user.username)
    logout(request)
    return Response({"detail": "Logged out."})


@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


@api_view(["POST"])
def change_password(request):
    """A person's own password: the one nobody else knows."""
    user = request.user
    if not confirm_password(user, str(request.data.get("current_password") or "")):
        record(user, "SIGN_PASSWORD_FAILED", "user", user.username, meaning="password change")
        return Response({"detail": "Your current password is not correct."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        set_own_password(user, str(request.data.get("new_password") or ""))
    except ValidationError as e:
        return Response({"detail": " ".join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
    update_session_auth_hash(request, user)
    record(user, "PASSWORD_CHANGED", "user", user.username)
    return Response(UserSerializer(user).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def config(request):
    """
    Public branding so the login screen can render it. Demo logins are
    listed only when DEBUG is on — never on a validated installation.
    """
    cfg = LabConfig.get()
    demo_logins = []
    if settings.DEBUG:
        demo_logins = [
            {"username": u.username, "name": u.display_name(), "role": u.role.name}
            for u in User.objects.select_related("role")
            .filter(username__in=["frontdesk", "analyst.gf", "analyst.gf2", "analyst.api", "checker",
                                  "qa.officer", "labhead", "prod.operator", "prod.officer", "sysadmin"],
                    is_active=True, role__is_active=True)
            .order_by("role__name")
        ]
    return Response(
        {
            "lab_name": cfg.lab_name,
            "app_tagline": cfg.app_tagline,
            "time_zone": lab_zone_name(),
            # How a time of day is written: "12h" (02:05 PM) or "24h" (14:05).
            "time_format": cfg.time_format,
            # The lab's logo, beside its name in the top bar and on the sign-in page.
            "logo_url": f"/api/auth/lab/logo/?v={cfg.logo.name.rsplit('/', 1)[-1]}" if cfg.logo else None,
            "demo_logins": demo_logins,
            "demo_password": "qclab1234" if settings.DEBUG and demo_logins else "",
        }
    )
