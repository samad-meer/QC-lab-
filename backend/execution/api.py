"""
Lab-execution endpoints. Every one checks that the caller can see the
sample, then hands the decision to the service layer, which enforces the
rules and writes the audit trail. Responses always return the sample's
full execution state, so the screen redraws from what the server holds.
"""
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.authz import has_perm
from accounts.models import User
from lims.models import Sample, SampleStatus
from lims.workflow import samples_visible_to
from . import services
from .files import private_file_response
from .models import TESTING, Assignment, Attachment, RetestKind, RetestRequest
from .payloads import execution_payload, person
from .rules import ExecutionError, step_of
from .tasks import tasks_for


def _bad(message: str):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _visible_sample(request, pk) -> Sample:
    sample = get_object_or_404(Sample, pk=pk)
    if not samples_visible_to(request.user).filter(pk=sample.pk).exists():
        raise Http404("Not your sample.")
    return sample


def _state(request, sample, code=status.HTTP_200_OK):
    sample.refresh_from_db()
    return Response(execution_payload(sample, request.user), status=code)


def _act(request, sample, action, *args, **kwargs):
    try:
        action(*args, **kwargs)
    except ExecutionError as e:
        return _bad(str(e))
    return _state(request, sample)


def _user(raw) -> User | None:
    return User.objects.filter(pk=raw, is_active=True).first() if str(raw or "").isdigit() else None


@api_view(["GET"])
def execution(request, pk):
    return _state(request, _visible_sample(request, pk))


@api_view(["POST"])
def checklist_answer(request, pk):
    sample = _visible_sample(request, pk)
    if request.data.get("clear"):
        return _act(request, sample, services.clear_answer, sample, request.data.get("item_id"),
                    request.user, request.data.get("reason", ""))
    return _act(request, sample, services.answer, sample, request.data.get("item_id"), request.user,
                request.data.get("value"), request.data.get("attachment_id"), request.data.get("reason", ""))


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def upload(request, pk):
    sample = _visible_sample(request, pk)
    return _act(request, sample, services.upload, sample, request.data.get("step", ""), request.user,
                request.FILES.get("file"), request.data.get("item_id"), request.data.get("replaces_id"),
                request.data.get("note", ""))


@api_view(["GET"])
def attachment_file(request, pk):
    """Files are served only here, to people who can see the sample — never from a public path."""
    a = get_object_or_404(Attachment, pk=pk)
    if not samples_visible_to(request.user).filter(pk=a.sample_id).exists():
        raise Http404("No such file.")
    return private_file_response(a.file, a.extension, a.content_type, a.original_name,
                                 download=request.query_params.get("download") == "1")


@api_view(["POST"])
def attachment_withdraw(request, pk):
    a = get_object_or_404(Attachment.objects.select_related("sample"), pk=pk)
    sample = _visible_sample(request, a.sample_id)
    return _act(request, sample, services.withdraw, a, request.user, request.data.get("reason", ""))


@api_view(["POST"])
def comment(request, pk):
    sample = _visible_sample(request, pk)
    return _act(request, sample, services.add_comment, sample, request.user, request.data.get("step", ""),
                request.data.get("body", ""), request.data.get("kind", "NOTE"),
                request.data.get("parent_id"), request.data.get("amends_id"))


@api_view(["GET"])
def candidates(request, pk):
    """Who a step can be assigned or handed to."""
    sample = _visible_sample(request, pk)
    try:
        step = step_of(sample, request.query_params.get("step", ""))
    except ExecutionError as e:
        return _bad(str(e))
    users = services.candidates(sample, step).select_related("role")
    return Response([
        {**person(u), "role": u.role.name if u.role else "", "is_me": u.id == request.user.id}
        for u in users
    ])


@api_view(["POST"])
def assignment(request, pk):
    """Assign (sample.assign), hand over (the holder), or take (someone in the stage's role)."""
    sample = _visible_sample(request, pk)
    mode = request.data.get("mode")
    step = request.data.get("step", "")
    if mode == "take":
        return _act(request, sample, services.claim, sample, step, request.user)
    to_user = _user(request.data.get("user_id"))
    if to_user is None:
        return _bad("Choose who the work goes to.")
    if mode == "assign":
        return _act(request, sample, services.assign, sample, step, to_user, request.user, request.data.get("note", ""))
    if mode == "handover":
        return _act(request, sample, services.hand_over, sample, step, to_user, request.user,
                    request.data.get("note", ""))
    return _bad("Unknown kind of assignment.")


MAX_AT_ONCE = 200


def _open_for_testing(request, raw_ids):
    """The samples asked for that this person sees and whose testing can still change hands."""
    ids = [int(i) for i in (raw_ids or []) if str(i).isdigit()][:MAX_AT_ONCE]
    return (samples_visible_to(request.user).filter(pk__in=ids)
            .select_related("section", "assigned_analyst").order_by("sample_no"))


@api_view(["GET"])
def testing_candidates(request):
    """
    Who the testing of several samples can go to at once: each active analyst, with how
    many of the chosen samples they are trained for and how many they already hold.
    """
    if not has_perm(request.user, "sample.assign"):
        return Response({"detail": "You do not have permission to assign work."}, status=status.HTTP_403_FORBIDDEN)
    samples = [s for s in _open_for_testing(request, request.query_params.get("ids", "").split(","))
               if s.status in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING)]
    analysts = (User.objects.filter(is_active=True, role__is_active=True, role__grants__permission="result.enter",
                                    role__grants__revoked_at__isnull=True)
                .select_related("role").prefetch_related("sections").distinct().order_by("first_name", "username"))
    people = []
    for u in analysts:
        sections = {s.id for s in u.sections.all()}
        can_take = sum(1 for s in samples if s.section_id in sections)
        if can_take:
            people.append({
                **person(u), "role": u.role.name if u.role else "", "is_me": u.id == request.user.id,
                "can_take": can_take, "holds": sum(1 for s in samples if s.assigned_analyst_id == u.id),
                "sections": sorted(s.code for s in u.sections.all()),
            })
    people.sort(key=lambda p: -p["can_take"])
    return Response({"open": len(samples), "people": people})


@api_view(["GET"])
def assign_overview(request):
    """
    Who holds how much testing right now, for whoever gives it out: each analyst with the
    samples they hold that can still change hands, and how many of those are late.
    """
    if not has_perm(request.user, "sample.assign"):
        return Response({"detail": "You do not have permission to assign work."}, status=status.HTTP_403_FORBIDDEN)
    today = timezone.localdate()
    open_samples = samples_visible_to(request.user).filter(status__in=(SampleStatus.RECEIVED, SampleStatus.IN_TESTING))
    held = {
        row["assigned_analyst_id"]: row
        for row in open_samples.order_by().values("assigned_analyst_id")
        .annotate(open=Count("id"), late=Count("id", filter=Q(due_date__lt=today)))
    }
    people = (
        User.objects.filter(is_active=True)
        .filter(Q(pk__in=held) | Q(role__is_active=True, role__grants__permission="result.enter",
                                   role__grants__revoked_at__isnull=True))
        .select_related("role").prefetch_related("sections").distinct().order_by("first_name", "username")
    )
    return Response({
        "open": sum(r["open"] for r in held.values()),
        "late": sum(r["late"] for r in held.values()),
        "people": [
            {**person(u), "role": u.role.name if u.role else "", "is_me": u.id == request.user.id,
             "sections": sorted(s.code for s in u.sections.all()),
             "open": held.get(u.id, {}).get("open", 0), "late": held.get(u.id, {}).get("late", 0)}
            for u in people
        ],
    })


@api_view(["POST"])
def assign_testing(request):
    """
    Give the testing of several samples to one analyst at once. Each sample is assigned
    as it would be on its own page, with the same checks, record and notice; one that
    cannot go to them is left as it was, with the reason.
    """
    if not has_perm(request.user, "sample.assign"):
        return Response({"detail": "You do not have permission to assign work."}, status=status.HTTP_403_FORBIDDEN)
    to_user = _user(request.data.get("user_id"))
    if to_user is None:
        return _bad("Choose who the testing goes to.")
    asked = request.data.get("sample_ids") or []
    if not isinstance(asked, list) or not asked:
        return _bad("Choose the samples to assign.")
    if len(asked) > MAX_AT_ONCE:
        return _bad(f"Assign at most {MAX_AT_ONCE} samples at once.")
    note = str(request.data.get("note") or "")
    assigned, skipped = [], []
    for sample in _open_for_testing(request, asked):
        try:
            services.assign(sample, TESTING, to_user, request.user, note)
        except ExecutionError as e:
            skipped.append({"id": sample.id, "sample_no": sample.sample_no, "reason": str(e)})
        else:
            assigned.append({"id": sample.id, "sample_no": sample.sample_no})
    found = {r["id"] for r in assigned + skipped}
    for raw in asked:
        if str(raw).isdigit() and int(raw) not in found:
            skipped.append({"id": int(raw), "sample_no": "", "reason": "Not found, or not one you can see."})
    return Response({"assigned": assigned, "skipped": skipped, "to": person(to_user)})


@api_view(["POST"])
def assignment_respond(request, pk):
    a = get_object_or_404(Assignment.objects.select_related("sample", "to_user"), pk=pk)
    sample = _visible_sample(request, a.sample_id)
    action = request.data.get("action")
    if action == "cancel":
        return _act(request, sample, services.cancel, a, request.user, request.data.get("reason", ""))
    if action not in ("accept", "reject"):
        return _bad("Accept or decline.")
    return _act(request, sample, services.respond, a, request.user, action == "accept", request.data.get("reason", ""))


@api_view(["POST"])
def hold(request, pk):
    sample = _visible_sample(request, pk)
    if request.data.get("release"):
        return _act(request, sample, services.release_hold, sample, request.user, request.data.get("comment", ""))
    return _act(request, sample, services.place_hold, sample, request.user, request.data.get("reason", ""))


@api_view(["POST"])
def retest_request(request, pk):
    sample = _visible_sample(request, pk)
    return _act(request, sample, services.request_retest, sample, request.data.get("test_definition_id"),
                request.user, request.data.get("reason", ""), request.data.get("kind", RetestKind.RETEST))


@api_view(["POST"])
def retest_decide(request, pk):
    req = get_object_or_404(
        RetestRequest.objects.select_related("sample", "failed_result", "test_definition", "requested_by"), pk=pk
    )
    sample = _visible_sample(request, req.sample_id)
    action = request.data.get("action")
    if action not in ("authorize", "decline"):
        return _bad("Authorize or decline.")
    return _act(request, sample, services.decide_retest, req, request.user, action == "authorize",
                request.data.get("comment", ""))


@api_view(["POST"])
def receipt_complete(request, pk):
    sample = _visible_sample(request, pk)
    return _act(request, sample, services.complete_receipt, sample, request.user, request.data.get("note", ""))


@api_view(["POST"])
def waive(request, pk):
    sample = _visible_sample(request, pk)
    return _act(request, sample, services.waive, sample, request.data.get("item_id"), request.user,
                request.data.get("reason", ""))


@api_view(["GET"])
def tasks(request):
    return Response(tasks_for(request.user))
