"""Batch and product reports: the QC history of a batch, a product or a certificate."""
from collections import defaultdict

from django.db.models import Case, Count, DateTimeField, Max, OuterRef, Q, Subquery, When

from batches.models import BatchDisposition, DispositionDecision
from certificates.models import CertStatus, Certificate, Signature
from lims.models import Outcome, Product, TestResult
from lims.workflow import samples_visible_to
from quality.models import InvestigationStatus
from quality.services import visible_investigations
from .engine import Cell, Column, Dates, Filter, Report, register
from .records import product_options, section_options, tests_required

CERT_TONES = {CertStatus.IN_REVIEW: "hot", CertStatus.APPROVED: "pass", CertStatus.WITHDRAWN: "fail", CertStatus.SUPERSEDED: "muted"}
DISPOSITION_TONES = {
    DispositionDecision.RELEASED: "pass", DispositionDecision.REJECTED: "fail", DispositionDecision.QUARANTINED: "warn",
}


def batch_link(batch_id) -> str:
    return f"/reports/batch/{batch_id}"


def disposition_cell(decision) -> Cell:
    if decision is None:
        return Cell("Not decided", tone="muted")
    return Cell(decision.get_decision_display(), tone=DISPOSITION_TONES[decision.decision])


@register
class Batches(Report):
    key = "batches"
    title = "Batch QC Summary"
    category = "batches"
    description = "Each batch of each product: samples, tests, failures and certificates. Open one for its summary."
    note = (
        "A batch is one official number of one product; samples with no batch are not listed. Neither a pass nor a "
        "fail here is a batch disposition: that is the decision shown in its own column, made by the quality unit."
    )
    columns = [
        Column("batch", "Batch / Lot", "batch__official_batch_no", width=1.1),
        Column("internal", "Internal ID", "batch__internal_id", width=1),
        Column("product", "Product", "product__name", width=1.6),
        Column("site", "Manufacturing site", "batch__manufacturing_site", width=1),
        Column("samples", "Samples", "samples", numeric=True, width=0.6),
        Column("tests", "Tests completed", numeric=True, width=0.8),
        Column("failed", "Failed tests", numeric=True, width=0.6),
        Column("investigations", "Open investigations", numeric=True, width=0.8),
        Column("certificates", "Released certificates", numeric=True, width=0.8),
        Column("disposition", "Disposition", width=0.9),
        Column("latest", "Latest receipt", "latest", width=1.2),
    ]
    dates = {"received": Dates("Received date", "received_at")}
    default_sort = "-latest"
    filters = [
        Filter("batch", "Batch / Lot", lambda qs, v: qs.filter(
            Q(batch__official_batch_no__icontains=v) | Q(batch__internal_id__icontains=v)
        ), kind="text"),
        Filter("product", "Product", lambda qs, v: qs.filter(product_id=v), options=product_options),
        Filter("section", "Laboratory section", lambda qs, v: qs.filter(section_id=v), options=section_options),
    ]

    def records(self, request):
        return samples_visible_to(request.user).filter(batch__isnull=False)

    def grouped(self, samples):
        return samples.order_by().values(
            "batch_id", "batch__official_batch_no", "batch__internal_id", "batch__manufacturing_site",
            "product_id", "product__name", "product__code",
        ).annotate(samples=Count("id"), latest=Max("received_at"))

    def rows(self, groups, request):
        samples = list(
            samples_visible_to(request.user).filter(batch_id__in={g["batch_id"] for g in groups}).order_by()
        )
        by_batch = defaultdict(list)
        for s in samples:
            by_batch[s.batch_id].append(s)
        required = tests_required(s.specification_id for s in samples)
        results = TestResult.objects.filter(sample__in=[s.pk for s in samples])
        entered = dict(results.filter(is_superseded=False).values_list("sample_id").annotate(n=Count("id")))
        failed = dict(results.filter(outcome=Outcome.FAIL).values_list("sample_id").annotate(n=Count("id")))
        released = dict(
            Certificate.objects.filter(sample__in=[s.pk for s in samples], status=CertStatus.APPROVED)
            .values_list("sample_id").annotate(n=Count("id"))
        )
        # A deviation names its batch in words, so the case it was typed in does not matter.
        # A case on a sample follows the sample's batch, whatever the number says now.
        open_cases = defaultdict(int)
        for batch_id, product_id, batch_no in visible_investigations(request.user).exclude(
            status=InvestigationStatus.CLOSED,
        ).filter(
            Q(sample__batch_id__in={g["batch_id"] for g in groups})
            | (Q(product_id__in={g["product_id"] for g in groups}) & ~Q(batch_no=""))
        ).values_list("sample__batch_id", "product_id", "batch_no"):
            open_cases[batch_id or (product_id, batch_no.upper())] += 1
        decisions = {}
        for d in BatchDisposition.objects.filter(batch_id__in={g["batch_id"] for g in groups}).order_by("id"):
            decisions[d.batch_id] = d  # oldest first, so the latest stays

        rows = []
        for g in groups:
            members = by_batch.get(g["batch_id"], [])
            needed = sum(required.get(s.specification_id, 0) for s in members)
            done = sum(entered.get(s.pk, 0) for s in members)
            failures = sum(failed.get(s.pk, 0) for s in members)
            cases = (open_cases.get(g["batch_id"], 0)
                     + open_cases.get((g["product_id"], g["batch__official_batch_no"].upper()), 0))
            rows.append({
                "batch": Cell(g["batch__official_batch_no"], to=batch_link(g["batch_id"])),
                "internal": g["batch__internal_id"],
                "product": Cell(g["product__name"], sub=g["product__code"]),
                "site": g["batch__manufacturing_site"],
                "samples": len(members),
                "tests": f"{done} of {needed}",
                "failed": Cell(failures, tone="fail") if failures else 0,
                "investigations": Cell(cases, tone="warn") if cases else 0,
                "certificates": sum(released.get(s.pk, 0) for s in members),
                "disposition": disposition_cell(decisions.get(g["batch_id"])),
                # The whole batch: the dates only choose which batches are listed.
                "latest": max((s.received_at for s in members), default=g["latest"]),
            })
        return rows


@register
class ProductHistory(Report):
    key = "product-history"
    title = "Product Quality History"
    category = "batches"
    description = "Each product across its batches. Open one for pass rates, trends and recurring investigations."
    columns = [
        Column("product", "Product", "name", width=1.8),
        Column("code", "Code", "code", width=0.8),
        Column("type", "Sample type", "sample_type"),
        Column("section", "Section", "section__code", width=0.7),
        Column("samples", "Samples", "sample_count", numeric=True, width=0.6),
        Column("batches", "Batches", "batch_count", numeric=True, width=0.6),
        Column("graded", "Graded results", "graded_count", numeric=True, width=0.7),
        Column("failed", "Failed results", "failed_count", numeric=True, width=0.7),
        Column("rate", "Failed, all tests pooled", numeric=True, width=0.8),
    ]
    default_sort = "code"
    filters = [
        Filter("section", "Laboratory section", lambda qs, v: qs.filter(section_id=v), options=section_options),
    ]

    def records(self, request):
        visible = samples_visible_to(request.user).order_by().values("pk")
        return Product.objects.select_related("section").annotate(
            sample_count=Count("samples", filter=Q(samples__in=visible), distinct=True),
            batch_count=Count(
                "samples__batch_no", filter=Q(samples__in=visible) & ~Q(samples__batch_no=""), distinct=True,
            ),
            graded_count=Count("samples__results", distinct=True, filter=Q(
                samples__in=visible, samples__results__outcome__in=[Outcome.PASS, Outcome.FAIL])),
            failed_count=Count("samples__results", distinct=True, filter=Q(
                samples__in=visible, samples__results__outcome=Outcome.FAIL)),
        ).filter(sample_count__gt=0)

    def rows(self, products, request):
        return [
            {
                "product": Cell(p.name, to=f"/reports/product/{p.pk}"),
                "code": p.code,
                "type": p.get_sample_type_display() or "Not set",
                "section": p.section.code,
                "samples": p.sample_count,
                "batches": p.batch_count,
                "graded": p.graded_count,
                "failed": Cell(p.failed_count, tone="fail") if p.failed_count else 0,
                "rate": f"{100 * p.failed_count / p.graded_count:.1f}%" if p.graded_count else "",
            }
            for p in products
        ]


@register
class Certificates(Report):
    key = "certificates"
    title = "Certificates of Analysis"
    category = "batches"
    description = "Every certificate version, issued or superseded. The original always stays on record."
    note = (
        "A certificate is identified by its sample number and version. A correction is a new version: the earlier "
        "one is kept, with who sent it back and why."
    )
    columns = [
        Column("number", "Certificate no.", width=1.2),
        Column("sample", "Sample ID", "sample__sample_no", width=1.1),
        Column("product", "Product", "sample__product__name", width=1.6),
        Column("batch", "Batch / Lot", "sample__batch_no"),
        Column("status", "Approval status", "status", width=1),
        Column("issued", "Issue date", "issued_at", width=1.2),
        Column("signed", "Signatures", numeric=True, width=0.7),
        Column("copies", "Copies printed", numeric=True, width=0.7),
        Column("history", "Revision history", width=1.5, wrap=True),
    ]
    dates = {"issued": Dates("Issue date", "issued_at"), "created": Dates("Signed by analyst", "created_at")}
    default_sort = "-issued"
    filters = [
        Filter("number", "Certificate no.", lambda qs, v: _by_number(qs, v), kind="text"),
        Filter("q", "Sample ID", lambda qs, v: qs.filter(sample__sample_no__icontains=v), kind="text"),
        Filter("batch", "Batch / Lot", lambda qs, v: qs.filter(
            Q(sample__batch_no__icontains=v) | Q(sample__reference__icontains=v)
        ), kind="text"),
        Filter("product", "Product", lambda qs, v: qs.filter(sample__product_id=v), options=product_options),
        Filter("status", "Approval status", lambda qs, v: qs.filter(status=v),
               options=[(s.value, s.label) for s in CertStatus]),
    ]

    def records(self, request):
        last_signature = Signature.objects.filter(certificate=OuterRef("pk")).order_by("-signed_at").values("signed_at")
        return Certificate.objects.filter(
            sample__in=samples_visible_to(request.user).values("pk")
        ).select_related("sample__product", "returned_by").annotate(
            # Only an approved certificate has been issued; its last signature issued it.
            issued_at=Case(
                When(status=CertStatus.APPROVED, then=Subquery(last_signature[:1])), output_field=DateTimeField(),
            ),
            signature_count=Count("signatures", distinct=True),
            copy_count=Count("prints", distinct=True),
        )

    def rows(self, certs, request):
        rows = []
        for c in certs:
            history = ""
            if c.status == CertStatus.SUPERSEDED:
                by = c.returned_by.display_name() if c.returned_by_id else "A reviewer"
                history = f"Sent back by {by}: {c.superseded_reason}"
            elif c.version > 1:
                history = f"Replaces version {c.version - 1}"
            rows.append({
                "number": Cell(f"{c.sample.sample_no}/v{c.version}", to=f"/certificates/{c.pk}"),
                "sample": Cell(c.sample.sample_no, to=f"/reports/sample-history/{c.sample_id}"),
                "product": Cell(c.sample.product.name, sub=c.sample.product.code),
                "batch": c.sample.batch_label,
                "status": Cell(c.get_status_display(), tone=CERT_TONES[c.status]),
                "issued": c.issued_at,
                "signed": c.signature_count,
                "copies": c.copy_count,
                "history": history,
            })
        return rows


def _by_number(qs, value: str):
    """“GF-2026-0004/v2”, or any part of the sample number."""
    sample, _, version = value.partition("/v")
    qs = qs.filter(sample__sample_no__icontains=sample)
    return qs.filter(version=version) if version.isdigit() else qs

