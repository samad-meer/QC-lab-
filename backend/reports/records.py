"""
What the reports read from the lab's records, in one place, so that "awaiting
review", "failed" and "turnaround" mean the same thing on every report, on the
dashboard and in every export.

Three different things can fail, and they are never run together:

- a failed test: one result outside its specification;
- a sample with a failed test: at least one of its results failed;
- a batch disposition: a release decision about a batch. It is recorded on the
  batch by the quality unit, and a released certificate is not one.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.utils import timezone

from accounts.models import User
from certificates.models import ANALYSED, CertStatus, Certificate, Signature
from execution.models import RetestRequest, RetestStatus
from lims.evaluation import reported_value
from lims.models import (
    FINISHED,
    Outcome,
    Product,
    SampleStatus,
    SampleType,
    Section,
    Specification,
    TestDefinition,
    TestResult,
    WorkflowEvent,
    WorkflowStage,
)
from lims.workflow import samples_visible_to
from quality.models import Investigation, InvestigationKind, InvestigationStatus

# Where a sample is, as the lab says it.
POSITIONS = {
    "AWAITING_TESTING": ("Awaiting testing", Q(status=SampleStatus.RECEIVED)),
    "UNDER_TESTING": ("Under testing", Q(status=SampleStatus.IN_TESTING)),
    "AWAITING_REVIEW": ("Awaiting review", Q(status=SampleStatus.IN_REVIEW, stages_after=True)),
    "AWAITING_APPROVAL": ("Awaiting approval", Q(status=SampleStatus.IN_REVIEW, stages_after=False)),
    "COMPLETED": ("Completed", Q(status=SampleStatus.APPROVED)),
    "REJECTED": ("Rejected", Q(status=SampleStatus.REJECTED)),
    "CANCELLED": ("Cancelled", Q(status=SampleStatus.CANCELLED)),
}

OUTCOME_TONES = {Outcome.PASS: "pass", Outcome.FAIL: "fail", Outcome.REPORTED: "muted"}
INVESTIGATION_TONES = {
    InvestigationStatus.OPEN: "warn",
    InvestigationStatus.PENDING_CLOSURE: "hot",
    InvestigationStatus.CLOSED: "pass",
}


def with_position(qs):
    """
    Samples, with what the reports ask of each: whether review stages remain
    after the one it waits at (the last one is the approval), when it was
    released, and whether a failure of it still needs an investigation.

    A failure needs one until an OOS investigation of that test has closed
    after it. A passing retest does not settle it: that is for the investigation
    to say, and a failure that comes after a closure needs looking at afresh.
    """
    closed = Investigation.objects.filter(
        kind=InvestigationKind.OOS, status=InvestigationStatus.CLOSED,
        sample=OuterRef("sample"), test_definition=OuterRef("test_definition"),
        closed_at__gte=OuterRef("entered_at"),
    )
    unresolved = TestResult.objects.filter(sample=OuterRef("pk"), outcome=Outcome.FAIL).filter(~Exists(closed))
    return qs.annotate(
        stages_after=Exists(WorkflowStage.objects.filter(
            version=OuterRef("workflow_version"), order__gt=OuterRef("review_stage__order"),
        )),
        released_at=Subquery(
            WorkflowEvent.objects.filter(sample=OuterRef("pk"), to_status=SampleStatus.APPROVED)
            .order_by("-at").values("at")[:1]
        ),
        open_failure=Exists(unresolved),
    )


def visible_samples(user):
    return with_position(samples_visible_to(user)).select_related("workflow_version")


def overdue(qs):
    return qs.exclude(status__in=FINISHED).filter(due_date__lt=timezone.localdate())


# How near a sample still in the lab is to its due date. The dashboard's chart of them and the
# Sample Register's filter read the same definition, so a slice opens exactly the samples it counts.
DUE_SOON_DAYS = 3
DUE_BANDS = {
    "overdue": "Overdue",
    "soon": f"Due in the next {DUE_SOON_DAYS} days",
    "later": "Due later",
}


def open_due(qs, band: str):
    """Samples still in the lab that are past their due date, due within a few days, or due later."""
    today = timezone.localdate()
    live = qs.exclude(status__in=FINISHED)
    if band == "overdue":
        return live.filter(due_date__lt=today)
    edge = today + timedelta(days=DUE_SOON_DAYS)
    if band == "soon":
        return live.filter(due_date__gte=today, due_date__lte=edge)
    return live.filter(due_date__gt=edge)


def batch_text(sample) -> str:
    """What a line calls it: its batch, or what it is if it has none (a swab, purified water)."""
    return f"Batch {sample.batch_no}" if sample.batch_no else sample.reference


def days_between(start, end) -> float:
    return round((end - start).total_seconds() / 86400, 1)


def turnaround_of(sample) -> tuple[float, bool]:
    """Days from receipt to release; for a sample still in the lab, the days so far."""
    finished = sample.released_at is not None
    return days_between(sample.received_at, sample.released_at or timezone.now()), finished


def median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def mean(values):
    return sum(values) / len(values) if values else None


def measure(value: float, places: int) -> Decimal:
    """A worked-out figure, to the precision of its test. A float would be written to one place."""
    return Decimal(str(round(value, places)))


def result_value(result) -> str:
    """As it prints on a certificate: the rounding the pass/fail decision used."""
    return reported_value(result)


def with_unit(result) -> str:
    return f"{result_value(result)} {result.test_definition.unit}".strip()


def results_visible_to(user):
    return TestResult.objects.filter(sample__in=samples_visible_to(user).values("pk")).select_related(
        "sample__product", "sample__specification", "test_definition", "entered_by", "superseded_by_user",
    )


def result_progress(sample_ids) -> dict[int, dict]:
    """For each sample: results entered and failing now, and failures replaced since."""
    rows = TestResult.objects.filter(sample_id__in=sample_ids).order_by().values("sample_id").annotate(
        entered=Count("id", filter=Q(is_superseded=False)),
        failing=Count("id", filter=Q(is_superseded=False, outcome=Outcome.FAIL)),
        failed_before=Count("id", filter=Q(is_superseded=True, outcome=Outcome.FAIL)),
    )
    return {r["sample_id"]: r for r in rows}


def tests_required(spec_ids) -> dict[int, int]:
    return {
        row["pk"]: row["n"]
        for row in Specification.objects.filter(pk__in=set(spec_ids)).values("pk").annotate(n=Count("tests"))
    }


def review_signatures(sample_ids) -> dict[int, list]:
    """Each sample's review signatures on its live certificate, earliest first."""
    found = defaultdict(list)
    rows = Signature.objects.filter(certificate__sample_id__in=sample_ids).exclude(meaning=ANALYSED).exclude(
        certificate__status=CertStatus.SUPERSEDED
    ).select_related("certificate").order_by("signed_at")
    for signature in rows:
        found[signature.certificate.sample_id].append(signature)
    return found


def returned_samples(sample_ids) -> set[int]:
    """Samples back with the analyst: the newest certificate version was sent back."""
    latest = {}
    for cert in Certificate.objects.filter(sample_id__in=sample_ids).order_by("version"):
        latest[cert.sample_id] = cert
    return {pk for pk, cert in latest.items() if cert.status == CertStatus.SUPERSEDED and cert.returned_at}


def investigations_by_test(pairs) -> dict[tuple, list]:
    """OOS investigations of (sample, test) pairs, newest first."""
    sample_ids = {s for s, _ in pairs}
    found = defaultdict(list)
    rows = Investigation.objects.filter(kind=InvestigationKind.OOS, sample_id__in=sample_ids).select_related(
        "closed_by"
    ).prefetch_related("actions")
    for inv in rows:
        found[(inv.sample_id, inv.test_definition_id)].append(inv)
    return found


def covering_investigation(found: dict, sample_id, test_id, failed_at):
    """
    The investigation of a failure: the newest that was still open at that moment,
    or closed after it. One that closed before a later failure says nothing about it.
    """
    for inv in found.get((sample_id, test_id), []):
        if inv.closed_at is None or inv.closed_at >= failed_at:
            return inv
    return None


def retests_of(result_ids) -> dict[int, list]:
    found = defaultdict(list)
    rows = RetestRequest.objects.filter(failed_result_id__in=result_ids).select_related(
        "retest_result__test_definition", "decided_by",
    )
    for retest in rows:
        found[retest.failed_result_id].append(retest)
    return found


def retest_results(result_ids) -> set[int]:
    """Which of these results are themselves the retest of an earlier failure."""
    return set(
        RetestRequest.objects.filter(retest_result_id__in=result_ids, status=RetestStatus.USED)
        .values_list("retest_result_id", flat=True)
    )


def time_buckets(start, stop) -> tuple[str, list]:
    """Days for a fortnight, weeks for a few months, months beyond that."""
    span = (stop - start).days
    if span <= 14:
        return "day", [start + timedelta(days=n) for n in range(span + 1)]
    if span <= 120:
        first = start - timedelta(days=start.weekday())
        return "week", [first + timedelta(weeks=n) for n in range((stop - first).days // 7 + 1)]
    months, current = [], start.replace(day=1)
    while current <= stop:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return "month", months


def bucket_of(day, unit: str):
    if unit == "week":
        return day - timedelta(days=day.weekday())
    if unit == "month":
        return day.replace(day=1)
    return day


# --- what filters offer -----------------------------------------------------

def product_options(request) -> list[tuple]:
    return [(p.id, f"{p.code} — {p.name}") for p in Product.objects.order_by("code")]


def section_options(request) -> list[tuple]:
    return [(s.id, s.name) for s in Section.objects.order_by("name")]


def analyst_options(request) -> list[tuple]:
    ids = samples_visible_to(request.user).order_by().values("assigned_analyst")
    return [(u.id, u.display_name()) for u in User.objects.filter(pk__in=ids).order_by("first_name", "username")]


def test_name_options(request) -> list[tuple]:
    names = TestDefinition.objects.order_by().values_list("name", flat=True).distinct()
    return [(n, n) for n in sorted(set(names))]


def spec_options(request) -> list[tuple]:
    specs = Specification.objects.select_related("product").order_by("product__code", "stage_key", "version")
    return [(s.id, f"{s.product.code} {s.stage_name + ' tests ' if s.stage_key else ''}v{s.version}") for s in specs]


SAMPLE_TYPES = [(t.value, t.label) for t in SampleType]
