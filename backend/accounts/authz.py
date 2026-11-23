"""
Capability checks. One place, used by every view and service.

Replaces the old hardcoded role classes: nothing in the codebase should ask
"is this user a CHECKER?" any more — it asks "may this user sign as checked?"
so that a lab can invent its own roles without a code change.
"""
from rest_framework.permissions import BasePermission

from audit.middleware import note_override

# Passes the rules about WHO may act: the assigned analyst, the role that signs
# a stage, a different person for every signature, independent retests and
# waivers. It never passes the rules about the RECORD — a hold, the order of
# the steps, a failed result, a signed certificate, the audit trail.
OVERRIDE = "admin.override"


def permissions_of(user) -> set[str]:
    """Cached per request — a role's grants are hit many times per view."""
    if not getattr(user, "is_authenticated", False):
        return set()
    cached = getattr(user, "_perm_cache", None)
    if cached is None:
        cached = user.permissions()
        user._perm_cache = cached
    return cached


def has_perm(user, key: str) -> bool:
    return key in permissions_of(user)


def overrides(user, rule: str) -> bool:
    """
    May this user pass a rule that stops everyone else? If so, the rule is
    noted and the audit rows of this action name it. Only for the path of an
    action — a screen deciding what to show asks has_perm(user, OVERRIDE).
    """
    if not has_perm(user, OVERRIDE):
        return False
    note_override(rule)
    return True


def require(user, key: str, message: str | None = None):
    """Raise PermissionDenied-style ValueError for the service layer."""
    if not has_perm(user, key):
        raise PermissionError(message or "You do not have permission to do this.")


class RequiresPermission(BasePermission):
    """Usage: @permission_classes([RequiresPermission.of('sample.register')])"""

    key = ""

    @classmethod
    def of(cls, key: str):
        return type(f"Requires_{key.replace('.', '_')}", (cls,), {"key": key})

    def has_permission(self, request, view):
        return has_perm(request.user, self.key)

    message = "You do not have permission to do this."
