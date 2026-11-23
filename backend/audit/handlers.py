from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework.views import exception_handler

from .services import record


def record_refusals(exc, context):
    """
    A permission check turned away an attempt to change something. Reading
    is not recorded: a 403 on a GET is usually just a screen probing a menu.
    """
    request = context["request"]
    if (
        isinstance(exc, PermissionDenied)
        and request.method not in SAFE_METHODS
        and request.user.is_authenticated
    ):
        record(request.user, "ACCESS_REFUSED", "api", request.path[:60], reason=str(exc.detail))
    return exception_handler(exc, context)
