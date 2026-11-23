"""
The lab's sections. Every sample number starts with its section's code, so a
code is fixed once chosen; the name can change. A section that anything uses
stays, because its samples and counters would otherwise point at nothing.
"""
import re

from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.authz import RequiresPermission
from audit.services import record
from .models import Section

CanManageSections = RequiresPermission.of("config.manage")


def _bad(message: str):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _payload(s: Section) -> dict:
    return {
        "id": s.id, "code": s.code, "name": s.name, "product_count": s.products.count(),
        "sample_count": s.samples.count(), "user_count": s.users.count(),
    }


def _text(request, field: str) -> str:
    value = request.data.get(field) if isinstance(request.data, dict) else None
    return value.replace("\x00", "").strip() if isinstance(value, str) else ""


@api_view(["GET", "POST"])
@permission_classes([CanManageSections])
def section_master(request):
    if request.method == "GET":
        return Response([_payload(s) for s in Section.objects.order_by("code")])

    code, name = _text(request, "code").upper(), _text(request, "name")
    if not re.fullmatch(r"[A-Z0-9]{1,10}", code):
        return _bad("The code must be 1 to 10 letters or digits. It starts every sample number in the section.")
    if not name:
        return _bad("Give the section a name.")
    if len(name) > 100:
        return _bad("Keep the name under 100 characters.")
    if Section.objects.filter(code=code).exists():
        return _bad(f"A section with the code {code} already exists.")
    section = Section.objects.create(code=code, name=name)
    record(request.user, "SECTION_CREATED", "section", section.code, name=name)
    return Response(_payload(section), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([CanManageSections])
def section_detail(request, pk):
    section = get_object_or_404(Section, pk=pk)

    if request.method == "DELETE":
        code = section.code
        kept = f"{section.name} has products or samples, so it stays on record."
        if section.products.exists() or section.samples.exists():
            return _bad(kept)
        if section.users.exists():
            return _bad(f"{section.users.count()} user(s) are trained for {section.name}. Move them first.")
        try:
            section.delete()
        except ProtectedError:  # its sample counter, once a number has been issued
            return _bad(kept)
        record(request.user, "SECTION_DELETED", "section", code)
        return Response(status=status.HTTP_204_NO_CONTENT)

    name = _text(request, "name")
    if not name:
        return _bad("Give the section a name.")
    if len(name) > 100:
        return _bad("Keep the name under 100 characters.")
    if name != section.name:
        was = section.name
        section.name = name
        section.save(update_fields=["name"])
        record(request.user, "SECTION_RENAMED", "section", section.code, was=was, name=name)
    return Response(_payload(section))
