"""
Makes the current request available to the audit writer.

Every audit row should carry where the action came from, but threading a
`request` through ~30 service-layer call sites would clutter the domain code
for a cross-cutting concern. A context variable keeps `record()` a one-liner
at the call site and is safe under Django's synchronous request handling
(each request gets its own context).

The rules an action passed on the administrator override travel the same way:
they are noted where the rule is passed, so no action can pass one and leave
rows that do not say so.
"""
from contextvars import ContextVar

from django.conf import settings

_current_request: ContextVar = ContextVar("qclab_current_request", default=None)
_overrides: ContextVar = ContextVar("qclab_overrides", default=())


def client_ip(request) -> str:
    """
    The caller's address. A caller can write anything into X-Forwarded-For, so
    it counts only behind our own proxy, and only the last entry: that is the
    one the proxy added itself.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded and settings.QCLAB_BEHIND_PROXY:
        return forwarded.split(",")[-1].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


def current_request():
    return _current_request.get()


def note_override(rule: str):
    # Signing checks its rules twice, before the row lock and under it.
    if rule not in _overrides.get():
        _overrides.set((*_overrides.get(), rule))


def noted_overrides() -> tuple:
    return _overrides.get()


def clear_overrides():
    _overrides.set(())


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)
            clear_overrides()
