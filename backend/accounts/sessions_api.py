"""
Sign-in and sessions: who is signed in now, on what and from where, and what an
administrator can do about it — end a session, lift a lockout. Who may sign in
at all stays on the account itself (Users screen), so there is one answer.

A session is never named by its key: while it lasts the key is as good as the
person's password. The screen gets a fingerprint of it instead.
"""
import hashlib
import re
import time
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from audit.models import AuditEvent
from audit.services import record
from .authz import RequiresPermission
from .models import User
from .passwords import is_locked
from .serializers import photo_url_for

CanManageUsers = RequiresPermission.of("user.manage")

# Did something within this many minutes: "active now". Otherwise idle, until the
# idle limit signs them out on their next request.
ACTIVE_MINUTES = 5
RECENT = 40
# What the screen lists of the trail, and how each reads.
SIGN_IN_EVENTS = {
    "LOGIN": ("Signed in", "pass"),
    "LOGOUT": ("Signed out", "muted"),
    "SESSION_TIMED_OUT": ("Signed out after inactivity", "muted"),
    "SESSION_ENDED": ("Signed out by an administrator", "warn"),
    "LOGIN_FAILED": ("Wrong username or password", "fail"),
    "ACCOUNT_LOCKED": ("Locked out after wrong passwords", "fail"),
    "ACCOUNT_UNLOCKED": ("Lockout lifted", "info"),
}


def fingerprint(session_key: str) -> str:
    return hashlib.sha256(session_key.encode()).hexdigest()[:16]


def device_of(agent: str) -> str:
    """A browser and a system, from the user agent: enough to tell one computer from another."""
    if not agent:
        return ""
    browser = next((name for pattern, name in (
        (r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Firefox/", "Firefox"), (r"Chrome/", "Chrome"),
        (r"Safari/", "Safari"),
    ) if re.search(pattern, agent)), "A browser")
    system = next((name for pattern, name in (
        (r"Android", "Android"), (r"iPhone|iPad", "iPhone or iPad"), (r"Windows", "Windows"),
        (r"Mac OS X|Macintosh", "Mac"), (r"Linux", "Linux"),
    ) if re.search(pattern, agent)), "")
    return f"{browser} on {system}" if system else browser


def _moment(seconds):
    return datetime.fromtimestamp(seconds, tz=dt_timezone.utc) if seconds else None


def live_sessions():
    """(session, its data, user id) for every session still in force: not expired, not idle past the limit."""
    now, idle = time.time(), settings.QCLAB_IDLE_MINUTES * 60
    found = []
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        data = session.get_decoded()
        uid = data.get(SESSION_KEY)
        last = data.get("last_activity")
        if uid is None or (last is not None and now - last > idle):
            continue  # nobody signed in, or signed out on its next request
        found.append((session, data, int(uid)))
    return found


def _person(user) -> dict:
    return {
        "id": user.pk, "name": user.display_name(), "username": user.username,
        "role": user.role.name if user.role_id else "", "photo_url": photo_url_for(user),
    }


@api_view(["GET"])
@permission_classes([CanManageUsers])
def sessions(request):
    now, idle = time.time(), settings.QCLAB_IDLE_MINUTES * 60
    live = live_sessions()
    people = {u.pk: u for u in User.objects.select_related("role")}
    rows = []
    for session, data, uid in live:
        user = people.get(uid)
        if user is None or not user.may_sign_in():
            continue
        last = data.get("last_activity")
        rows.append({
            "id": fingerprint(session.session_key),
            "user": _person(user),
            "signed_in_at": _moment(data.get("signed_in_at")),
            "last_activity": _moment(last),
            "state": "active" if last is not None and now - last < ACTIVE_MINUTES * 60 else "idle",
            "signs_out_at": _moment(last + idle) if last is not None else None,
            "ip": data.get("ip", ""),
            "device": device_of(data.get("agent", "")),
            "current": session.session_key == request.session.session_key,
        })
    rows.sort(key=lambda r: (r["state"] != "active", -(r["last_activity"].timestamp() if r["last_activity"] else 0)))

    allowed = [u for u in people.values() if u.may_sign_in()]
    names = {u.username: u.display_name() for u in people.values()}
    recent = AuditEvent.objects.filter(action__in=SIGN_IN_EVENTS).order_by("-at", "-id")[:RECENT]
    return Response({
        "idle_minutes": settings.QCLAB_IDLE_MINUTES,
        "active_minutes": ACTIVE_MINUTES,
        "summary": {
            "online": len({r["user"]["id"] for r in rows if r["state"] == "active"}),
            "signed_in": len({r["user"]["id"] for r in rows}),
            "allowed": len(allowed),
            "blocked": len(people) - len(allowed),
            "locked": sum(1 for u in people.values() if is_locked(u)),
        },
        "sessions": rows,
        "recent": [
            {
                "id": e.id, "at": e.at, "action": e.action,
                "label": SIGN_IN_EVENTS[e.action][0], "tone": SIGN_IN_EVENTS[e.action][1],
                # Whose sign-in it was; an administrator's own action names them as well.
                "person": names.get(who := (e.details or {}).get("username") or e.entity_id or e.actor_username, who),
                "by": names.get(e.actor_username, e.actor_username)
                if e.action in ("SESSION_ENDED", "ACCOUNT_UNLOCKED") else "",
                "ip": e.ip_address,
            }
            for e in recent
        ],
    })


@api_view(["POST"])
@permission_classes([CanManageUsers])
def end_session(request, sid):
    """Sign someone out on one computer. Their account and their records are untouched."""
    for session, data, uid in live_sessions():
        if fingerprint(session.session_key) != sid:
            continue
        if session.session_key == request.session.session_key:
            return Response({"detail": "This is your own session here. Use Sign out at the top of the screen."},
                            status=status.HTTP_400_BAD_REQUEST)
        user = User.objects.filter(pk=uid).first()
        name = user.display_name() if user else "Someone"
        session.delete()
        record(request.user, "SESSION_ENDED", "user", user.username if user else str(uid),
               device=device_of(data.get("agent", "")) or "unknown", where=data.get("ip", "") or "unknown")
        return Response({"detail": f"{name} is signed out on that computer."})
    return Response({"detail": "That session has already ended."}, status=status.HTTP_404_NOT_FOUND)


@api_view(["POST"])
@permission_classes([CanManageUsers])
def unlock(request, pk):
    """Lift a lockout before it ends by itself, once you know it is really them."""
    user = get_object_or_404(User, pk=pk)
    if not is_locked(user):
        return Response({"detail": f"{user.display_name()} is not locked out."}, status=status.HTTP_400_BAD_REQUEST)
    User.objects.filter(pk=pk).update(failed_logins=0, locked_until=None)
    record(request.user, "ACCOUNT_UNLOCKED", "user", user.username)
    return Response({"detail": f"{user.display_name()} can sign in again."})
