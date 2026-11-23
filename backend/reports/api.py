"""
The Reports module. Permission to open a report is checked here; what a person
sees inside one comes from the same visibility rules as every other screen.
"""
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.response import Response

from accounts.authz import RequiresPermission, has_perm
from audit.services import record
from batches.models import Batch
from lims.models import Product
from lims.workflow import samples_visible_to
from qclab.listing import paginated, window_from
from . import batches, compliance, dashboard, documents, export, results, samples, workflow  # noqa: F401
from .engine import (
    CATEGORIES,
    REPORTS,
    cell_json,
    definition,
    filters_applied,
    may_open,
    period_label,
    reachable,
    select,
    stamp,
)

CanView = RequiresPermission.of("report.view")
EXPORT = "report.export"

# Reached from a row of another report, rather than opened on its own: (the
# report it is reached from, how the catalogue lists it).
PLACES = {
    "samples": [("sample-register", {
        "key": "sample-history", "title": "Sample History",
        "description": "The complete history of one sample. Open any sample in the register.",
        "to": "/reports/sample-register",
    })],
}


def _report(request, key: str):
    report = REPORTS.get(key)
    if report is None:
        raise Http404
    if not may_open(request.user, key):
        raise PermissionDenied("You do not have permission to open this report.")
    return report


def _may_open(request, key: str):
    """The history page of one record, which goes with the report it opens from."""
    if not may_open(request.user, key):
        raise PermissionDenied(
            f"You do not have permission to open this. It is part of the {REPORTS[key].title} report."
        )


@api_view(["GET"])
@permission_classes([CanView])
def catalogue(request):
    """The reports this person may open, by category. The rest are not mentioned."""
    groups = []
    for key, title, question in CATEGORIES:
        entries = [
            {"key": r.key, "title": r.title, "description": r.description, "to": f"/reports/{r.key}"}
            for r in REPORTS.values() if r.category == key and may_open(request.user, r.key)
        ]
        places = [place for via, place in PLACES.get(key, []) if may_open(request.user, via)]
        entries = [*entries[:1], *places, *entries[1:]]
        if entries:
            groups.append({"key": key, "title": title, "question": question, "reports": entries})
    return Response({"categories": groups})


@api_view(["GET"])
@permission_classes([CanView])
def dashboard_view(request):
    """The overview: figures from the Sample Register, each opening the records behind it."""
    _may_open(request, "sample-register")
    return Response(reachable(dashboard.build(request), request.user))


@api_view(["GET"])
@permission_classes([CanView])
def report_definition(request, key):
    report = _report(request, key)
    can_act = bool(report.action) and has_perm(request.user, report.action[2])
    return Response(definition(report, request, has_perm(request.user, EXPORT), can_act))


@api_view(["GET"])
@permission_classes([CanView])
def report_page(request, key):
    report = _report(request, key)
    records = select(report, request)

    def serialize(page):
        return [
            {c.key: cell_json(reachable(row.get(c.key), request.user)) for c in report.columns}
            for row in report.rows(list(page), request)
        ]

    return paginated(
        request, records, serialize,
        summary=reachable(report.summary(records, request), request.user), period=period_label(report, request), **stamp(request),
    )


def _chosen_format(request) -> str:
    """Named `file`, because DRF keeps `format` for itself."""
    chosen = request.query_params.get("file", "")
    if chosen not in export.CONTENT_TYPES:
        raise ParseError("Choose CSV, Excel or PDF.")
    return chosen


def _may_export(request):
    if not has_perm(request.user, EXPORT):
        raise PermissionDenied("You do not have permission to export reports.")


@api_view(["GET"])
@permission_classes([CanView])
def report_export(request, key):
    report = _report(request, key)
    _may_export(request)
    file_format = _chosen_format(request)
    records = select(report, request)
    limit = export.ROW_LIMITS[file_format]
    rows = list(records[:limit + 1]) if not isinstance(records, list) else records
    if len(rows) > limit:
        raise ParseError(
            f"This selection is over the {limit:,}-row limit for {export.FORMAT_NAMES[file_format]}. "
            "Narrow the dates or filters, or use a spreadsheet format."
        )
    rows = report.rows(rows, request)
    applied = filters_applied(report, request)
    meta = {"key": report.key, "title": report.title, "note": report.note, "applied": applied, **stamp(request)}
    writer = {"csv": export.to_csv, "xlsx": export.to_xlsx, "pdf": export.to_pdf}[file_format]
    response = writer(meta, report.columns, rows)
    record(request.user, "REPORT_EXPORTED", "report", report.key, title=report.title,
           format=export.FORMAT_NAMES[file_format], rows=len(rows),
           filters="; ".join(f"{f['label']}: {f['value']}" for f in applied))
    return response


def _document(request, doc: dict, key: str):
    """A document as JSON for the screen, or, asked for as a file, a recorded PDF."""
    if "file" not in request.query_params:
        shown = reachable(doc, request.user)
        # A link to another page that this person cannot open is left out, not shown dead.
        shown["links"] = [link for link in shown.get("links", []) if link.get("to")]
        return Response({**shown, **stamp(request), "can_export": has_perm(request.user, EXPORT)})
    _may_export(request)
    if request.query_params["file"] != "pdf":
        raise ParseError("This report is exported as a PDF.")
    response = export.document_pdf(doc, {"key": key, **stamp(request)}, key)
    record(request.user, "DOCUMENT_EXPORTED", "report", doc["reference"], title=doc["title"], format="PDF")
    return response


@api_view(["GET"])
@permission_classes([CanView])
def sample_history(request, pk):
    _may_open(request, "sample-register")
    sample = samples_visible_to(request.user).filter(pk=pk).first()
    if sample is None:
        return Response({"detail": "This sample is not one you can see."}, status=status.HTTP_404_NOT_FOUND)
    return _document(request, documents.sample_history(sample), f"sample-history_{sample.sample_no}")


@api_view(["GET"])
@permission_classes([CanView])
def batch_summary(request, pk):
    _may_open(request, "batches")
    batch = get_object_or_404(Batch.objects.select_related("product__section"), pk=pk)
    doc = documents.batch_summary(request.user, batch)
    if doc is None:
        return Response({"detail": "No sample of this batch is one you can see."}, status=status.HTTP_404_NOT_FOUND)
    return _document(request, doc, f"batch-summary_{batch.product.code}_{batch.official_batch_no}")


@api_view(["GET"])
@permission_classes([CanView])
def product_history(request, pk):
    _may_open(request, "product-history")
    product = get_object_or_404(Product.objects.select_related("section"), pk=pk)
    doc = documents.product_history(request.user, product, window_from(request, "all"))
    if doc is None:
        return Response({"detail": "No sample of this product is one you can see."}, status=status.HTTP_404_NOT_FOUND)
    return _document(request, doc, f"product-history_{product.code}")
