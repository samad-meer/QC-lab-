"""A person's own notifications: list, mark one read, mark all read."""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Notification

LIMIT = 50


def _payload(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "sample_id": n.sample_id,
        "actor": {"id": n.actor_id, "name": n.actor.display_name()} if n.actor_id else None,
        "created_at": n.created_at,
        "read_at": n.read_at,
    }


def _state(user) -> dict:
    mine = Notification.objects.filter(recipient=user)
    return {
        "unread": mine.filter(read_at__isnull=True).count(),
        "items": [_payload(n) for n in mine.select_related("actor")[:LIMIT]],
        "server_time": timezone.now(),
    }


@api_view(["GET"])
def notifications(request):
    # Only reads. Every open page asks this every 30 seconds, so nothing slow may happen here: the
    # due-date sweep and the queued email are done by the background worker (worker.py).
    return Response(_state(request.user))


@api_view(["POST"])
def mark_read(request, pk):
    # Only your own — anyone else's is simply not found.
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save()
    return Response(_state(request.user))


@api_view(["POST"])
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return Response(_state(request.user))
