"""
The QC dashboard: what is happening in the lab right now, and what happened in
the period. Every figure leads to the records behind it, and reads through the
same definitions as the reports it opens, so a tile saying 12 opens a list of 12.

Nothing is stored. Everything is limited to the samples this person can see.
"""
from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Count
from django.utils import timezone

from accounts.authz import has_perm
from batches.models import BatchDisposition, DispositionDecision
from lims.models import Outcome, Section, TestResult
from lims.workflow import samples_visible_to
from qclab.listing import window_from
from .engine import stamp
from .records import (
    POSITIONS,
    bucket_of,
    days_between,
    mean,
    overdue,
    time_buckets,
    visible_samples,
)
from .workflow import waiting_work

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


def _timeline(window, moments_a: list, moments_b: list, names: tuple[str, str]) -> dict:
    """Two counts over the same stretch of time. Every day, week or month shows, empty or not."""
    today = timezone.localdate()
    days = [_local_day(m) for m in [*moments_a, *moments_b]]
    start = _local_day(window.start) if window.start else min(days, default=today)
    stop = min(_local_day(window.stop - timedelta(microseconds=1)), today) if window.stop else today
    if stop < start:
        stop = start
    unit, buckets = time_buckets(start, stop)

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

    entered = window.apply(
        TestResult.objects.filter(sample__in=today_scope.values("pk")), "entered_at"
    ).select_related("sample")
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
    }
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

    return {
        **stamp(request),
        "label": window.label,
        "scope": "Across the lab" if has_perm(user, "sample.view.all") else "The samples you can see",
        "now": now,
        "period": in_period,
        "failures": failures,
        "charts": charts,
    }
