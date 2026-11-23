"""
Who samples are received from. The front desk picks a name from this list
instead of typing one, so "ali", "Ali" and "ALI Raza" never become three
sources. Entries are never deleted: one no longer used is deactivated, and a
sample keeps the name it was received under.
"""
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.authz import RequiresPermission
from audit.services import record
from .models import SampleSource

CanManageSources = RequiresPermission.of("config.manage")


def _bad(message: str):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _payload(s: SampleSource) -> dict:
    return {"id": s.id, "name": s.name, "is_active": s.is_active}


def clean_name(value) -> str:
    """Spacing never makes a different name."""
    return " ".join(value.replace("\x00", "").split()) if isinstance(value, str) else ""


def _name_problem(name: str, pk=None) -> str:
    if not name:
        return "Give the name, e.g. a department or the person who brings samples."
    if len(name) > 200:
        return "Keep the name under 200 characters."
    taken = SampleSource.objects.filter(name__iexact=name).exclude(pk=pk).first()
    if taken:
        return f"“{taken.name}” is already on the list." + ("" if taken.is_active else " It is inactive: reactivate it instead.")
    return ""


@api_view(["GET"])
@permission_classes([RequiresPermission.of("sample.register")])
def sample_sources(request):
    """What the front desk may choose from."""
    qs = SampleSource.objects.filter(is_active=True).order_by(Lower("name"))
    return Response([_payload(s) for s in qs])


@api_view(["GET", "POST"])
@permission_classes([CanManageSources])
def source_master(request):
    if request.method == "GET":
        return Response([_payload(s) for s in SampleSource.objects.order_by("-is_active", Lower("name"))])

    name = clean_name(request.data.get("name") if isinstance(request.data, dict) else None)
    problem = _name_problem(name)
    if problem:
        return _bad(problem)
    source = SampleSource.objects.create(name=name)
    record(request.user, "SAMPLE_SOURCE_ADDED", "sample_source", source.id, name=name)
    return Response(_payload(source), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([CanManageSources])
def source_detail(request, pk):
    source = get_object_or_404(SampleSource, pk=pk)
    data = request.data if isinstance(request.data, dict) else {}

    if "name" in data:
        name = clean_name(data.get("name"))
        problem = _name_problem(name, pk=source.pk)
        if problem:
            return _bad(problem)
        if name != source.name:
            was = source.name
            source.name = name
            source.save(update_fields=["name"])
            record(request.user, "SAMPLE_SOURCE_RENAMED", "sample_source", source.id, was=was, name=name)

    if "is_active" in data:
        active = data.get("is_active")
        if not isinstance(active, bool):
            return _bad("Say whether the name is offered at the front desk.")
        if active != source.is_active:
            source.is_active = active
            source.save(update_fields=["is_active"])
            action = "SAMPLE_SOURCE_REACTIVATED" if active else "SAMPLE_SOURCE_DEACTIVATED"
            record(request.user, action, "sample_source", source.id, name=source.name)
    return Response(_payload(source))
