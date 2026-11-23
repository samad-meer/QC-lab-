"""The investigation record. Its register is the Deviations & CAPA report."""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.authz import RequiresPermission
from accounts.models import LabConfig, User
from lims.models import Product
from lims.workflow import samples_visible_to
from . import services
from .models import CapaAction, CapaKind, Classification, Conclusion, InvestigationKind, LabFinding
from .payloads import investigation_payload
from .services import MANAGE, QualityError


def _visible(request, pk):
    return get_object_or_404(services.visible_investigations(request.user), pk=pk)


def _refused(e: QualityError):
    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


def _fresh(request, pk):
    return Response(investigation_payload(_visible(request, pk), request.user))


def _act(request, pk, action, *args):
    """Run a service; a refusal is a 400 with the reason, and the screen gets the fresh record."""
    try:
        action(_visible(request, pk), request.user, *args)
    except QualityError as e:
        return _refused(e)
    return _fresh(request, pk)


@api_view(["GET"])
@permission_classes([RequiresPermission.of(MANAGE)])
def options(request):
    """What the forms offer: the kinds, classifications, and who can be made responsible."""
    return Response({
        "kinds": [{"value": k.value, "label": k.label} for k in InvestigationKind],
        "classifications": [{"value": c.value, "label": c.label} for c in Classification],
        "action_kinds": [{"value": k.value, "label": k.label} for k in CapaKind],
        "lab_findings": [{"value": f.value, "label": f.label} for f in LabFinding],
        "conclusions": [{"value": c.value, "label": c.label} for c in Conclusion],
        "products": [{"id": p.id, "name": f"{p.code} — {p.name}"} for p in Product.objects.order_by("code")],
        "people": [
            {"id": u.id, "name": u.display_name()}
            for u in User.objects.filter(is_active=True, role__isnull=False).order_by("first_name", "username")
        ],
    })


@api_view(["POST"])
def investigations(request):
    try:
        inv = services.open_investigation(request.user, request.data)
    except QualityError as e:
        return _refused(e)
    return Response(investigation_payload(inv, request.user), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def investigation_detail(request, pk):
    if request.method == "PATCH":
        fields = {k: v for k, v in request.data.items() if k in services.EDITABLE}
        return _act(request, pk, services.update_investigation, fields, request.data.get("reason", ""))
    return _fresh(request, pk)


@api_view(["POST"])
def add_action(request, pk):
    return _act(request, pk, services.add_action, request.data)


@api_view(["POST"])
def complete_action(request, pk, action_id):
    action = get_object_or_404(CapaAction, pk=action_id, investigation=_visible(request, pk))
    try:
        services.complete_action(action, request.user, request.data.get("note", ""))
    except QualityError as e:
        return _refused(e)
    return _fresh(request, pk)


@api_view(["POST"])
def verify_action(request, pk, action_id):
    action = get_object_or_404(CapaAction, pk=action_id, investigation=_visible(request, pk))
    try:
        services.verify_action(action, request.user, request.data.get("note", ""), request.data.get("password", ""))
    except QualityError as e:
        return _refused(e)
    return _fresh(request, pk)


@api_view(["POST"])
def submit(request, pk):
    return _act(request, pk, services.submit_for_closure)


@api_view(["POST"])
def send_back(request, pk):
    return _act(request, pk, services.return_investigation, request.data.get("comment", ""))


@api_view(["POST"])
def close(request, pk):
    return _act(request, pk, services.close_investigation, request.data.get("password", ""))


@api_view(["POST"])
def lab_finding(request, pk):
    return _act(request, pk, services.record_lab_finding, request.data.get("finding", ""),
                request.data.get("notes", ""), request.data.get("reason", ""))


@api_view(["POST"])
def close_sample(request, pk):
    """Reject a sample whose failure is confirmed, or cancel one that cannot be tested."""
    sample = get_object_or_404(samples_visible_to(request.user), pk=pk)
    try:
        services.close_sample(sample, request.user, request.data.get("action") == "reject",
                              request.data.get("reason", ""), request.data.get("password", ""))
    except QualityError as e:
        return _refused(e)
    return Response({"status": "closed"})


@api_view(["GET", "PATCH"])
def quality_rules(request):
    """What the lab requires after a failed result. Everyone may read them; they govern everyone."""
    if request.method == "GET":
        return Response(services.rules_payload(LabConfig.get()))
    try:
        cfg = services.change_rules(request.user, request.data, request.data.get("reason", ""))
    except QualityError as e:
        return _refused(e)
    return Response(services.rules_payload(cfg))
