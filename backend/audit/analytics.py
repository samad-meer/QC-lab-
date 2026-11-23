"""
Lab analytics over a time window.

Everything here is derived — no figure is stored, so nothing can drift out of
step with the records it describes.
"""
from django.db.models import Avg, Count, F, Q
from django.utils import timezone

from certificates.models import CertStatus, Certificate, PrintEvent
from lims.models import FINISHED, Outcome, Sample, SampleStatus, TestResult
from .describe import RETURN_ACTIONS
from .models import AuditEvent

def _median(values):
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def build(window) -> dict:

    # --- the pipeline right now (a snapshot, never windowed) -------------
    live = Sample.objects.exclude(status__in=FINISHED)
    by_status = {
        row["status"]: row["n"]
        for row in Sample.objects.values("status").annotate(n=Count("id"))
    }
    overdue = live.filter(due_date__lt=timezone.localdate()).count()

    # --- what happened in the window ------------------------------------
    received = window.apply(Sample.objects.all(), "received_at")
    approved = window.apply(Certificate.objects.filter(status=CertStatus.APPROVED), "created_at")
    results = window.apply(TestResult.objects.filter(is_superseded=False), "entered_at")
    failures = results.filter(outcome=Outcome.FAIL).count()
    graded = results.exclude(outcome=Outcome.REPORTED).count()

    # Turnaround: received → approved, for samples finished in the window.
    finished = window.apply(Sample.objects.filter(status=SampleStatus.APPROVED, certificates__status=CertStatus.APPROVED), "certificates__created_at").annotate(released=F("certificates__created_at")).values("received_at", "released")
    turnarounds = [
        (row["released"] - row["received_at"]).total_seconds() / 86400
        for row in finished
        if row["released"] and row["received_at"]
    ]

    # --- who did the work -------------------------------------------------
    workload = list(
        window.apply(Sample.objects.all(), "received_at")
        .values("assigned_analyst__first_name", "assigned_analyst__last_name",
                "assigned_analyst__username")
        .annotate(
            total=Count("id"),
            done=Count("id", filter=Q(status=SampleStatus.APPROVED)),
        )
        .order_by("-total")[:10]
    )
    by_section = list(
        window.apply(Sample.objects.all(), "received_at")
        .values("section__code", "section__name")
        .annotate(n=Count("id"))
        .order_by("-n")
    )

    # --- activity, day by day --------------------------------------------
    events = window.apply(AuditEvent.objects.all(), "at")
    daily = {}
    for stamp in events.values_list("at", flat=True):
        key = timezone.localtime(stamp).date().isoformat()
        daily[key] = daily.get(key, 0) + 1

    # Refusals are the rows an inspector goes looking for.
    refusals = events.filter(
        Q(action__contains="REFUSED") | Q(action__contains="FAILED")
    ).count()

    signatures = events.filter(action__startswith="SIGNED_").count()

    return {
        "period": window.key,
        "label": window.label,
        "from": window.start,
        "to": window.stop,
        "pipeline": {
            "by_status": {s.value: by_status.get(s.value, 0) for s in SampleStatus},
            "live": live.count(),
            "overdue": overdue,
        },
        "throughput": {
            "received": received.count(),
            "released": approved.count(),
            "results_entered": results.count(),
            "prints": window.apply(PrintEvent.objects.all(), "printed_at").count(),
        },
        "quality": {
            "failures": failures,
            "graded_results": graded,
            "oos_rate": round(100 * failures / graded, 1) if graded else 0.0,
            "corrections": events.filter(action="RESULT_SUPERSEDED").count(),
            "sent_back": events.filter(action__in=RETURN_ACTIONS).count(),
        },
        "turnaround": {
            "samples": len(turnarounds),
            "median_days": round(_median(turnarounds), 1) if turnarounds else None,
            "slowest_days": round(max(turnarounds), 1) if turnarounds else None,
        },
        "activity": {
            "events": events.count(),
            "signatures": signatures,
            "refusals": refusals,
            "daily": [{"date": d, "count": n} for d, n in sorted(daily.items())],
        },
        "workload": [
            {
                "analyst": (f"{w['assigned_analyst__first_name']} {w['assigned_analyst__last_name']}".strip()
                            or w["assigned_analyst__username"]),
                "total": w["total"],
                "done": w["done"],
            }
            for w in workload
        ],
        "by_section": [
            {"code": s["section__code"], "name": s["section__name"], "count": s["n"]}
            for s in by_section
        ],
    }
