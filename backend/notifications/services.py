"""
Sending notifications. Called by the services that change who holds work,
inside their own transaction — a refused action notifies nobody.
"""
from accounts.models import User
from .email import queue_email
from .models import Notification
from .rules import is_enabled, wants_email


def users_with(permission: str):
    """Active people whose role currently holds this permission."""
    return User.objects.filter(
        is_active=True, role__is_active=True,
        role__grants__permission=permission, role__grants__revoked_at__isnull=True,
    ).distinct()


def notify(recipient, kind: str, title: str, body: str = "", link: str = "", sample=None, actor=None):
    """One notification to one person. Nobody is notified of their own action."""
    if recipient is None or not recipient.is_active:
        return None
    if actor is not None and recipient.pk == actor.pk:
        return None
    if not is_enabled(kind):
        return None
    notification = Notification.objects.create(
        recipient=recipient, kind=kind, title=title[:200], body=(body or "")[:1000],
        link=link or (f"/samples/{sample.id}" if sample is not None else ""),
        sample=sample, actor=actor if getattr(actor, "pk", None) else None,
    )
    if wants_email(kind):
        queue_email(notification)
    return notification


def notify_all(recipients, kind: str, title: str, **kwargs):
    seen = set()
    for user in recipients:
        if user is not None and user.pk not in seen:
            seen.add(user.pk)
            notify(user, kind, title, **kwargs)
