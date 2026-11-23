"""
The registers, generically, and what the sample page needs of them. A refusal
is a 400 with the reason, and the screen gets the fresh record back. A register
this person may not see is a 403, and is left out of the list of registers; the
pick-lists a result or a specification needs stay open to whoever fills them.
"""
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounts.authz import has_perm
from execution.payloads import person
from lims.workflow import samples_visible_to
from qclab.listing import filter_by_text, paginated
from reports.list_export import Col, ListExport, cell_text
from . import services
from .models import CustodyAction, InstrumentStatus, Material, MaterialStatus, Method, MethodStatus
from .registers import REGISTERS, choices, people
from .services import LabRecordError


def _refused(message: str):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _body(request) -> dict:
    """A body that is not an object has nothing in it any rule can read."""
    return request.data if isinstance(request.data, dict) else {}


def _register(key: str, request):
    entry = REGISTERS.get(key)
    if entry is None:
        raise Http404
    if not entry.visible_to(request.user):
        raise PermissionDenied(f"You do not have permission to see {entry.title.lower()}.")
    return entry


def _attempt(work):
    """Run a service. Two people adding the same thing at once is a refusal, not a crash."""
    try:
        return work(), None
    except LabRecordError as e:
        return None, _refused(str(e))
    except IntegrityError:
        return None, _refused("Someone else saved this first. Reload and try again.")


@api_view(["GET"])
def registers(request):
    """Which registers there are, and what each one holds. The screens are drawn from this."""
    return Response({"registers": [
        entry.definition(request) for entry in REGISTERS.values() if entry.visible_to(request.user)
    ]})


def _selected(entry, request):
    records = entry.records(request)
    for flt in entry.filters:
        value = (request.query_params.get(flt.key) or "").strip()
        if not value:
            continue
        if value not in {str(v) for v, _ in flt.options}:
            return None, _refused(f"“{value}” is not a choice for {flt.label}.")
        records = flt.apply(records, value)
    return entry.order(filter_by_text(request, records, entry.search)), None


def _export(entry) -> ListExport:
    """A register as a file: its own columns, read from the rows the screen draws."""
    def choice(flt):
        names = {str(v): label for v, label in flt.options}
        return flt.label, lambda value: names.get(value, value)

    return ListExport(
        key=entry.key,
        title=entry.title,
        columns=[Col(c.label, lambda row, k=c.key: cell_text(row.get(k))) for c in entry.columns],
        filters={**{f.key: choice(f) for f in entry.filters}, "q": "Search"},
        rows=lambda records, request: entry.rows(list(records), request),
    )


@api_view(["GET", "POST"])
def register(request, key):
    entry = _register(key, request)
    if request.method == "GET":
        records, refusal = _selected(entry, request)
        if refusal:
            return refusal
        return paginated(request, records, lambda page: entry.rows(list(page), request), export=_export(entry))
    created, refusal = _attempt(lambda: entry.add(request.user, _body(request)))
    if refusal:
        return refusal
    return Response(entry.detail(entry.find(request, created.pk), request), status=status.HTTP_201_CREATED)


@api_view(["GET"])
def record_detail(request, key, pk):
    entry = _register(key, request)
    return Response(entry.detail(entry.find(request, pk), request))


@api_view(["POST"])
def act(request, key, pk, action):
    entry = _register(key, request)
    chosen = entry.action(action)
    found = entry.find(request, pk)
    done, refusal = _attempt(lambda: chosen.run(found, request.user, _body(request)))
    if refusal:
        return refusal
    # Drafting a new version makes a new record, and that is the one to look at next.
    landed = done if isinstance(done, type(found)) else found
    return Response(entry.detail(entry.find(request, landed.pk), request))


@api_view(["GET"])
def result_options(request):
    """What can be named on a result right now. The server checks again when it is saved."""
    instruments = REGISTERS["instruments"].records(request).filter(status=InstrumentStatus.IN_SERVICE)
    materials = Material.objects.filter(status=MaterialStatus.AVAILABLE)
    return Response({
        "instruments": [
            {"id": i.id, "code": i.code, "name": i.name, "due": i.next_due}
            for i in instruments if services.calibration_problem(i, i.next_due) is None
        ],
        "materials": [
            {"id": m.id, "code": m.code, "name": m.name, "lot": m.lot, "kind": m.get_kind_display(),
             "expiry_date": m.expiry_date}
            for m in materials if services.material_problem(m) is None
        ],
    })


@api_view(["GET"])
def method_choices(request):
    """What a test in a draft specification can name. The approval decides whether that holds."""
    methods = Method.objects.exclude(status=MethodStatus.RETIRED)
    return Response({
        "methods": [
            {"id": m.id, "label": f"{m} — {m.title}", "status": m.status, "status_label": m.get_status_display(),
             "validation_status": m.validation_status}
            for m in methods.order_by("code", "-version")
        ],
    })


def _custody_entry(e) -> dict:
    return {
        "id": e.id, "action": e.action, "action_label": e.get_action_display(), "location": e.location,
        "from_person": person(e.from_person), "to_person": person(e.to_person), "quantity": e.quantity,
        "note": e.note, "retain_until": e.retain_until, "witness": person(e.witness), "at": e.at, "by": person(e.by),
    }


def _custody_payload(sample, user) -> dict:
    entries = sample.custody_events.select_related("from_person", "to_person", "witness", "by")
    ended = services.is_destroyed(sample)
    may_add, may_destroy = has_perm(user, services.CUSTODY), has_perm(user, services.DESTROY)
    return {
        "entries": [_custody_entry(e) for e in entries],
        "retain_until": services.retain_until(sample),
        "destroyed": ended,
        "can_add": not ended and may_add,
        "can_destroy": not ended and may_destroy,
        "actions": [
            {"value": v, "label": label} for v, label in choices(CustodyAction)
            if (may_destroy if v == CustodyAction.DESTROYED else may_add)
        ],
        "people": [{"id": pk, "name": name} for pk, name in people()] if may_add or may_destroy else [],
    }


@api_view(["GET", "POST"])
def custody(request, pk):
    """A sample's chain of custody. Whoever can see the sample can read it."""
    sample = get_object_or_404(samples_visible_to(request.user), pk=pk)
    if request.method == "POST":
        _, refusal = _attempt(lambda: services.add_custody(sample, request.user, _body(request)))
        if refusal:
            return refusal
        sample.refresh_from_db()
    return Response(_custody_payload(sample, request.user))
