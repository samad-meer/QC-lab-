"""Sample reports: where each sample is, and how long it took."""
from django.db.models import Q
from django.utils import timezone

from execution.models import SampleHold
from lims.models import SampleStatus
from .engine import Cell, Column, Dates, Filter, Report, register
from .records import (
    POSITIONS,
    SAMPLE_TYPES,
    analyst_options,
    days_between,
    mean,
    median,
    overdue,
    visible_samples,
    product_options,
    result_progress,
    returned_samples,
    section_options,
    tests_required,
    turnaround_of,
    visible_samples,
)


def stage_of(sample) -> str:
    if sample.status == SampleStatus.RECEIVED:
        return "Received"
    if sample.status == SampleStatus.IN_TESTING:
        return "Testing"
    if sample.status == SampleStatus.IN_REVIEW and sample.review_stage_id:
        return sample.review_stage.name
    if sample.status in (SampleStatus.REJECTED, SampleStatus.CANCELLED):
        return sample.get_status_display()
    return "Released"


def review_status(sample, returned: set[int]) -> Cell:
    if sample.status == SampleStatus.APPROVED:
        return Cell("Approved", tone="pass")
    if sample.status == SampleStatus.REJECTED:
        return Cell("Rejected", tone="fail")
    if sample.status == SampleStatus.CANCELLED:
        return Cell("Cancelled", tone="muted")
    if sample.status == SampleStatus.IN_REVIEW:
        return Cell("Pending", tone="hot", sub=sample.review_stage.name if sample.review_stage_id else "")
    if sample.pk in returned:
        return Cell("Returned", tone="fail")
    return Cell("Not started", tone="muted")


def results_cell(progress: dict, required: int) -> Cell:
    entered, failing = progress.get("entered", 0), progress.get("failing", 0)
    if failing:
        return Cell(f"{failing} failed test(s)", tone="fail", sub=f"{entered} of {required} entered")
    if entered == 0:
        return Cell("No results yet", tone="muted")
    failed_before = progress.get("failed_before", 0)
    earlier = f"{failed_before} failed result(s) stay on record" if failed_before else ""
    if entered < required:
        return Cell(f"{entered} of {required} entered", tone="warn" if failed_before else "info", sub=earlier)
    if failed_before:
        return Cell("Within limits after a failure", tone="warn", sub=earlier)
    return Cell("All tests within limits", tone="pass")


@register
class SampleRegister(Report):
    key = "sample-register"
    title = "Sample Register"
    category = "samples"
    description = "Every registered sample: where it is, who holds it and how long it has taken."
    note = (
        "Results shows the sample's tests now. A failed test is not a failed batch: "
        "a batch's disposition is its own decision, recorded on the batch."
    )
    columns = [
        Column("sample", "Sample ID", "sample_no", width=1.15),
        Column("product", "Product / Material", "product__name", width=1.6),
        Column("batch", "Batch / Lot", "batch_no"),
        Column("type", "Sample type", "product__sample_type"),
        Column("section", "Section", "section__code", width=0.7),
        Column("received", "Received", "received_at", width=1.25),
        Column("due", "Due", "due_date"),
        Column("analyst", "Assigned analyst", "assigned_analyst__first_name"),
        Column("stage", "Current stage", width=0.9),
        Column("status", "Status", "status", width=1.1),
        Column("review", "Review status", width=0.9),
        Column("results", "Results", width=1.1),
        Column("turnaround", "Turnaround (days)", numeric=True, width=0.85),
    ]
    dates = {
        "received": Dates("Received date", "received_at"),
        "due": Dates("Due date", "due_date", date_only=True),
        "completed": Dates("Completed date", "released_at"),
    }
    default_sort = "-received"
    filters = [
        Filter("q", "Sample ID", lambda qs, v: qs.filter(sample_no__icontains=v), kind="text"),
        Filter("batch", "Batch / Lot", lambda qs, v: qs.filter(Q(batch_no__icontains=v) | Q(reference__icontains=v)),
               kind="text"),
        Filter("product", "Product", lambda qs, v: qs.filter(product_id=v), options=product_options),
        Filter("sample_type", "Sample type", lambda qs, v: qs.filter(product__sample_type=v), options=SAMPLE_TYPES),
        Filter("analyst", "Analyst", lambda qs, v: qs.filter(assigned_analyst_id=v), options=analyst_options),
        Filter("section", "Laboratory section", lambda qs, v: qs.filter(section_id=v), options=section_options),
        Filter("stage", "Workflow stage", lambda qs, v: qs.filter(POSITIONS[v][1]),
               options=[(k, label) for k, (label, _) in POSITIONS.items()]),
        Filter("status", "Status", lambda qs, v: qs.filter(status=v),
               options=[(s.value, s.label) for s in SampleStatus]),
        Filter("overdue", "Only overdue", lambda qs, v: overdue(qs), kind="toggle"),
        Filter("investigate", "Only requiring investigation", lambda qs, v: qs.filter(open_failure=True), kind="toggle"),
    ]

    def records(self, request):
        return visible_samples(request.user)

    def rows(self, samples, request):
        ids = [s.pk for s in samples]
        progress = result_progress(ids)
        required = tests_required(s.specification_id for s in samples)
        returned = returned_samples(ids)
        held = set(SampleHold.objects.filter(sample_id__in=ids, released_at__isnull=True)
                   .values_list("sample_id", flat=True))
        rows = []
        for s in samples:
            days, finished = turnaround_of(s)
            rows.append({
                "sample": Cell(s.sample_no, to=f"/reports/sample-history/{s.pk}"),
                "product": Cell(s.product.name, sub=s.product.code),
                "batch": Cell(s.batch_no, to=f"/reports/batch/{s.batch_id}") if s.batch_id else s.reference,
                "type": s.product.get_sample_type_display() or "Not set",
                "section": s.section.code,
                "received": s.received_at,
                "due": s.due_date,
                "analyst": s.assigned_analyst.display_name(),
                "stage": stage_of(s),
                "status": Cell("On hold", tone="warn", sub=s.status_label()) if s.pk in held else s.status_label(),
                "review": review_status(s, returned),
                "results": results_cell(progress.get(s.pk, {}), required.get(s.specification_id, 0)),
                "turnaround": Cell(days, sub="" if finished else "so far", screen_only=True),
            })
        return rows


@register
class Turnaround(Report):
    key = "turnaround"
    title = "Turnaround Time"
    category = "samples"
    description = "Released samples: from receipt to release, step by step, against the due date."
    note = (
        "Turnaround runs from the recorded receipt to the final signature. "
        "Tests differ in length, so compare like with like."
    )
    columns = [
        Column("sample", "Sample ID", "sample_no", width=1.15),
        Column("product", "Product", "product__name", width=1.6),
        Column("batch", "Batch / Lot", "batch_no"),
        Column("section", "Section", "section__code", width=0.7),
        Column("analyst", "Analyst", "assigned_analyst__first_name"),
        Column("received", "Received", "received_at", width=1.25),
        Column("released", "Released", "released_at", width=1.25),
        Column("due", "Due", "due_date"),
        Column("days", "Turnaround (days)", numeric=True, width=0.85),
        Column("timing", "Against due date", width=0.9),
    ]
    dates = {"released": Dates("Released date", "released_at"), "received": Dates("Received date", "received_at")}
    default_period = "quarter"
    default_sort = "-released"
    filters = [
        Filter("product", "Product", lambda qs, v: qs.filter(product_id=v), options=product_options),
        Filter("section", "Laboratory section", lambda qs, v: qs.filter(section_id=v), options=section_options),
        Filter("analyst", "Analyst", lambda qs, v: qs.filter(assigned_analyst_id=v), options=analyst_options),
        Filter("sample_type", "Sample type", lambda qs, v: qs.filter(product__sample_type=v), options=SAMPLE_TYPES),
    ]

    def records(self, request):
        return visible_samples(request.user).filter(released_at__isnull=False)

    def rows(self, samples, request):
        rows = []
        for s in samples:
            late = (timezone.localtime(s.released_at).date() - s.due_date).days
            rows.append({
                "sample": Cell(s.sample_no, to=f"/reports/sample-history/{s.pk}"),
                "product": Cell(s.product.name, sub=s.product.code),
                "batch": s.batch_label,
                "section": s.section.code,
                "analyst": s.assigned_analyst.display_name(),
                "received": s.received_at,
                "released": s.released_at,
                "due": s.due_date,
                "days": days_between(s.received_at, s.released_at),
                "timing": Cell(f"{late}d late", tone="warn") if late > 0 else Cell("On time", tone="pass"),
            })
        return rows

    def summary(self, samples, request):
        finished = list(samples.values_list("received_at", "released_at", "due_date"))
        days = [days_between(a, b) for a, b, _ in finished]
        on_time = sum(1 for _, b, due in finished if timezone.localtime(b).date() <= due)
        return [
            {"label": "Released", "value": len(finished)},
            {"label": "Overdue, not released", "value": overdue(visible_samples(request.user)).count(),
             "sub": "Not in the figures here"},
            {"label": "Median", "value": f"{median(days):.1f}d" if days else "—"},
            {"label": "Average", "value": f"{mean(days):.1f}d" if days else "—"},
            {"label": "On time", "value": f"{100 * on_time / len(finished):.0f}%" if finished else "—",
             "sub": f"{on_time} of {len(finished)}"},
        ]

