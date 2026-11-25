"""
The QC dashboard: what is happening in the lab right now, and what happened in
the period. Every figure leads to the records behind it, and reads through the
same definitions as the reports it opens, so a tile saying 12 opens a list of 12.

Nothing is stored. Everything is limited to the samples this person can see.
"""
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone

from accounts.authz import has_perm
from batches.api import batches_visible_to
from batches.models import BatchDisposition, DispositionDecision
from lims.models import Outcome, Section, TestResult
from lims.workflow import samples_visible_to
from qclab.listing import window_from
from quality.models import InvestigationStatus
from quality.services import visible_investigations
from .engine import stamp
from .records import (
    DUE_BANDS,
    POSITIONS,
    bucket_of,
    days_between,
    mean,
    open_due,
    overdue,
    time_buckets,
    visible_samples,
)
from .workflow import waiting_work
from . import insights

DEFAULT_PERIOD = "month"


def _register(**query) -> str:
    return "/reports/sample-register?" + urlencode(query)


def _window_query(request) -> dict:
    """The period as the dashboard was asked for it, for the links it offers."""
    params = request.query_params
    chosen = {k: params[k] for k in ("period", "from", "to") if params.get(k)}
    return chosen or {"period": DEFAULT_PERIOD}


def _local_day(moment):
    return timezone.localtime(moment).date()


def _span(window, moments: list):
    """The days, weeks or months a period is drawn in: every one shows, empty or not."""
    today = timezone.localdate()
    days = [_local_day(m) for m in moments]
    start = _local_day(window.start) if window.start else min(days, default=today)
    stop = min(_local_day(window.stop - timedelta(microseconds=1)), today) if window.stop else today
    if stop < start:
        stop = start
    return time_buckets(start, stop)


def _timeline(window, moments_a: list, moments_b: list, names: tuple[str, str]) -> dict:
    """Two counts over the same stretch of time. Every day, week or month shows, empty or not."""
    unit, buckets = _span(window, [*moments_a, *moments_b])

    def tally(moments):
        counts = defaultdict(int)
        for moment in moments:
            counts[bucket_of(_local_day(moment), unit)] += 1
        return counts

    a, b = tally(moments_a), tally(moments_b)
    return {
        "unit": unit,
        "series": list(names),
        "points": [{"date": day.isoformat(), "values": [a[day], b[day]]} for day in buckets],
    }


def _investigations(user, window, period: dict) -> list[dict]:
    """Where the quality events stand now, and how many closed in the period. Only those this person may see."""
    seen = visible_investigations(user).order_by()
    closed = window.apply(seen.filter(status=InvestigationStatus.CLOSED), "closed_at").count()
    base = "/reports/deviations?"
    return [
        {"key": "OPEN", "label": "Under investigation", "value": seen.filter(status=InvestigationStatus.OPEN).count(),
         "to": base + urlencode({"status": "OPEN"})},
        {"key": "PENDING_CLOSURE", "label": "Awaiting closure approval",
         "value": seen.filter(status=InvestigationStatus.PENDING_CLOSURE).count(),
         "to": base + urlencode({"status": "PENDING_CLOSURE"})},
        {"key": "CLOSED", "label": "Closed in the period", "value": closed,
         "to": base + urlencode({"status": "CLOSED", "date_field": "closed", **period})},
    ]


def _batch_decisions(user, window) -> list[dict]:
    """Batches registered in the period, by the quality unit's latest decision, or none yet."""
    latest = BatchDisposition.objects.filter(batch=OuterRef("pk")).order_by("-id").values("decision")[:1]
    counts = dict(
        window.apply(batches_visible_to(user).order_by(), "created_at")
        .annotate(decision=Subquery(latest)).values_list("decision").annotate(n=Count("id"))
    )
    waiting = counts.get(None, 0)
    return [
        {"key": "RELEASED", "label": "Released", "value": counts.get(DispositionDecision.RELEASED, 0)},
        {"key": "QUARANTINED", "label": "Quarantined", "value": counts.get(DispositionDecision.QUARANTINED, 0)},
        {"key": "REJECTED", "label": "Rejected", "value": counts.get(DispositionDecision.REJECTED, 0)},
        {"key": "WAITING", "label": "Waiting for a decision", "value": waiting},
    ]


def build(request) -> dict:
    user = request.user
    window = window_from(request, DEFAULT_PERIOD)
    period = _window_query(request)
    samples = visible_samples(user)
    today_scope = samples_visible_to(user).order_by()

    positions = {key: samples.filter(q).count() for key, (_, q) in POSITIONS.items()}
    needing = samples.filter(open_failure=True).count()
    late = overdue(samples).count()

    received = window.apply(samples, "received_at")
    released = window.apply(samples.filter(released_at__isnull=False), "released_at")
    times = list(released.values_list("received_at", "released_at"))
    average = mean([days_between(a, b) for a, b in times])

    def now_tile(key: str, label: str) -> dict:
        return {"key": key, "label": label, "value": positions[key], "to": _register(stage=key)}

    now = [
        now_tile("AWAITING_TESTING", "Awaiting testing"),
        now_tile("UNDER_TESTING", "Under testing"),
        now_tile("AWAITING_REVIEW", "Awaiting review"),
        now_tile("AWAITING_APPROVAL", "Awaiting approval"),
        {"key": "INVESTIGATE", "label": "Failed samples requiring investigation", "value": needing,
         "to": _register(investigate=1), "alert": needing > 0},
        {"key": "OVERDUE", "label": "Overdue samples", "value": late, "to": _register(overdue=1), "alert": late > 0},
    ]
    in_period = [
        {"key": "RECEIVED", "label": "Samples received", "value": received.count(),
         "to": _register(date_field="received", **period)},
        {"key": "COMPLETED", "label": "Completed samples", "value": released.count(),
         "to": _register(date_field="completed", stage="COMPLETED", **period)},
        {"key": "TURNAROUND", "label": "Average turnaround", "value": f"{average:.1f}d" if times else "—",
         "sub": f"{len(times)} released" if times else "Nothing released in this period",
         "to": "/reports/turnaround?" + urlencode({"date_field": "released", **period})},
    ]

    scope_results = TestResult.objects.filter(sample__in=today_scope.values("pk"))
    entered = window.apply(scope_results, "entered_at").select_related("sample")
    outcomes = list(entered.exclude(outcome=Outcome.REPORTED).values_list("outcome", "entered_at"))
    failed = entered.filter(outcome=Outcome.FAIL)
    failures = {
        "tests": failed.count(),
        "samples": failed.order_by().values("sample").distinct().count(),
        "batches": failed.exclude(sample__batch=None).order_by().values("sample__batch").distinct().count(),
        "rejected_batches": window.apply(
            BatchDisposition.objects.filter(
                decision=DispositionDecision.REJECTED, batch__in=today_scope.exclude(batch=None).values("batch"),
            ), "decided_at",
        ).order_by().values("batch").distinct().count(),
        "to": "/reports/oos?" + urlencode(period),
    }

    by_section = dict(received.order_by().values_list("section").annotate(n=Count("id")))
    sections = [
        {"label": s.name, "value": by_section[s.pk],
         "to": _register(section=s.pk, date_field="received", **period)}
        for s in Section.objects.filter(pk__in=by_section).order_by("name")
    ]

    charts = {
        "flow": _timeline(
            window, list(received.values_list("received_at", flat=True)), [b for _, b in times],
            ("Received", "Completed"),
        ),
        "outcomes": _timeline(
            window, [at for o, at in outcomes if o == Outcome.PASS], [at for o, at in outcomes if o == Outcome.FAIL],
            ("Passed", "Failed"),
        ),
        "status": [
            {"label": label, "value": positions[key], "to": _register(stage=key)}
            for key, (label, _) in POSITIONS.items()
        ],
        "sections": sections,
        # Passed against failed, over the results entered in the period. A result reported only as
        # "<LOQ" or "ND" is neither, so it is left out of both, as it is on the outcomes chart.
        "results": {
            "passed": sum(1 for o, _ in outcomes if o == Outcome.PASS),
            "failed": failures["tests"],
            "to_passed": "/reports/test-results?" + urlencode({"outcome": Outcome.PASS, **period}),
            "to_failed": "/reports/test-results?" + urlencode({"outcome": Outcome.FAIL, **period}),
        },
        # Samples still in the lab by how near their due date is: each slice opens the register filtered to it.
        "due": [
            {"key": band, "label": label, "value": open_due(samples, band).count(), "to": _register(due=band)}
            for band, label in DUE_BANDS.items()
        ],
        "investigations": _investigations(user, window, period),
    }
    if has_perm(user, "sample.view.all") or has_perm(user, "batch.view.all"):
        charts["batches"] = _batch_decisions(user, window)
    if has_perm(user, "report.performance"):
        work = defaultdict(lambda: {"pending": 0, "overdue": 0})
        for row in waiting_work(user):
            person = work[(row["analyst_name"], row["analyst_id"])]
            person["pending"] += 1
            person["overdue"] += 1 if row["overdue_days"] > 0 else 0
        charts["analysts"] = [
            {"label": name, "to": f"/reports/pending-work?analyst={pk}", **counts}
            for (name, pk), counts in sorted(work.items())
        ]

    # The richer views: how the period compares with the one before, what is coming, what is waiting, where
    # failures come from, and whether the equipment is in date.
    unit, buckets = _span(window, [*received.values_list("received_at", flat=True), *[b for _, b in times],
                                   *[at for _, at in outcomes]])
    headline = insights.kpis(window, period, samples, scope_results, unit, buckets, late)
    deeper = {
        **headline,
        "outlook": insights.due_outlook(samples),
        "ageing": insights.ageing(samples),
        "failures": insights.failures(scope_results, period, window),
    }
    kit = insights.equipment(user)
    if kit:
        deeper["equipment"] = kit

    return {
        **stamp(request),
        "label": window.label,
        "scope": "Across the lab" if has_perm(user, "sample.view.all") else "The samples you can see",
        "now": now,
        "period": in_period,
        "failures": failures,
        "charts": charts,
        "insights": deeper,
    }
