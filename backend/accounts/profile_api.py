"""
Self-service: what a person may change about themselves.

An administrator owns identity and access — name, employee number,
designation, joining date, role, sections, the password, and whether the
account is active. A user owns only their photograph and contact details.
"""
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from audit.services import record
from .models import User
from .photos import PhotoError, clean_photo
from .serializers import ProfileSerializer


def _bad(msg):
    return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PATCH"])
def profile(request):
    """The signed-in user's own record."""
    user = request.user

    if request.method == "GET":
        return Response(ProfileSerializer(user).data)

    # Refuse admin-owned fields outright rather than ignoring them: a caller
    # that thinks it set its own joining date should be told it did not.
    forbidden = sorted(
        set(request.data) & set(User.ADMIN_ONLY_FIELDS + ("role_id", "role", "is_active", "username"))
    )
    if forbidden:
        return _bad(
            f"{', '.join(forbidden)} can only be changed by an administrator."
        )

    changed = {}
    for field in User.SELF_EDITABLE_FIELDS:
        if field in request.data:
            value = (request.data.get(field) or "").strip()
            if getattr(user, field) != value:
                changed[field] = value
                setattr(user, field, value)
    if "email" in request.data:
        value = (request.data.get("email") or "").strip()
        if user.email != value:
            changed["email"] = value
            user.email = value

    if changed:
        user.save(update_fields=list(changed))
        record(user, "PROFILE_UPDATED", "user", user.username, **changed)
    return Response(ProfileSerializer(user).data)


@api_view(["POST", "DELETE"])
@parser_classes([MultiPartParser])
def profile_photo(request):
    user = request.user

    if request.method == "DELETE":
        if not user.photo:
            return _bad("You have no photo to remove.")
        user.clear_photo()
        record(user, "PROFILE_PHOTO_REMOVED", "user", user.username)
        return Response(ProfileSerializer(user).data)

    try:
        cleaned = clean_photo(request.FILES.get("photo"))
    except PhotoError as e:
        return _bad(str(e))
    user.replace_photo(cleaned)
    record(user, "PROFILE_PHOTO_CHANGED", "user", user.username)
    return Response(ProfileSerializer(user).data)


@api_view(["GET"])
def user_photo(request, pk):
    """
    Serve a photo to signed-in users only. Personal data does not belong on
    an open /media/ path, and routing it through here keeps it same-origin
    with the API the frontend already talks to.
    """
    user = get_object_or_404(User, pk=pk)
    if not user.photo:
        raise Http404("No photo.")
    try:
        handle = user.photo.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("No photo.")
    response = FileResponse(handle, content_type="image/jpeg")
    # Photos change rarely but must not be stale after an upload; the URL
    # carries a cache-buster, so this can be cached hard but privately.
    response["Cache-Control"] = "private, max-age=300"
    return response


# An administrator sets a temporary password (accounts/admin_api.py ::
# reset_password), and the person chooses their own (accounts/views.py ::
# change_password) before they can do anything else.
