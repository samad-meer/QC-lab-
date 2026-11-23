"""
Any list as an Excel or PDF file. The file holds the records the screen lists,
under the same filters and in the same order, every page of them, headed by who
exported it, when, and under which filters. Every export is recorded, as a
report's is, and needs the same permission.

A list opts in by passing `export=` to qclab.listing.paginated, which answers
with the file when the request asks for one with ?file=xlsx or ?file=pdf.
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from rest_framework.exceptions import ParseError, PermissionDenied

from accounts.authz import has_perm
from audit.services import record
from qclab.listing import window_from
from . import export
from .engine import Column, stamp

EXPORT = "report.export"
FORMATS = ("xlsx", "pdf")


@dataclass(frozen=True)
class Col:
    label: str
    value: Callable[[Any], Any]  # (row) -> a value; dates and numbers stay dates and numbers in Excel
    width: float = 1.0  # its share of the page in a PDF


@dataclass(frozen=True)
class ListExport:
    key: str  # the file name
    title: str
    columns: list
    # The query parameters a person filters by: a label, or (label, how its value reads).
    filters: dict = field(default_factory=dict)
    # The dates the list can be filtered on: the date_field key and its label. Empty when it has none.
    dates: dict = field(default_factory=dict)
    default_period: str = "all"
    # Loaded with the records, so a long list is not one query per row.
    related: tuple = ()
    prefetch: tuple = ()
    # Turns the records into the rows the columns read; the records themselves when not given.
    rows: Callable | None = None
    # Built on samples_visible_to: a person without sample.view.all sees part of the lab.
    scoped: bool = False


def cell_text(value):
    """A register's cell is a value, or a dict with its text and where it links to."""
    if isinstance(value, dict):
        return " — ".join(str(part) for part in (value.get("text"), value.get("sub")) if part not in (None, ""))
    return value


def applied(spec: ListExport, request) -> list[dict]:
    """The filters in force, as a person reads them."""
    out = []
    if spec.dates:
        key = request.query_params.get("date_field") or next(iter(spec.dates))
        out.append({"label": spec.dates.get(key, "Date"), "value": window_from(request, spec.default_period).label})
    for param, how in spec.filters.items():
        raw = (request.query_params.get(param) or "").strip()
        if not raw:
            continue
        label, read = how if isinstance(how, tuple) else (how, None)
        out.append({"label": label, "value": read(raw) if read else raw})
    if spec.scoped and not has_perm(request.user, "sample.view.all"):
        out.append({"label": "Scope", "value": "Only the samples you can see, so this may not be the whole lab"})
    return out


def respond(request, records, spec: ListExport):
    if not has_perm(request.user, EXPORT):
        raise PermissionDenied("You do not have permission to export.")
    chosen = request.query_params.get("file", "")
    if chosen not in FORMATS:
        raise ParseError("Choose Excel or PDF.")
    if hasattr(records, "select_related"):
        if spec.related:
            records = records.select_related(*spec.related)
        if spec.prefetch:
            records = records.prefetch_related(*spec.prefetch)
    limit = export.ROW_LIMITS[chosen]
    # A cut-off list would look complete, so one over the limit is refused with the reason.
    picked = list(records[:limit + 1])
    if len(picked) > limit:
        also = " or export it to Excel" if chosen == "pdf" else ""
        raise ParseError(
            f"This list has more than {limit:,} rows, the most a {export.FORMAT_NAMES[chosen]} file holds. "
            f"Narrow the dates or filters{also}."
        )
    rows = spec.rows(picked, request) if spec.rows else picked
    columns = [Column(f"c{i}", c.label, width=c.width) for i, c in enumerate(spec.columns)]
    data = [{f"c{i}": c.value(row) for i, c in enumerate(spec.columns)} for row in rows]
    filters = applied(spec, request)
    meta = {"key": spec.key, "title": spec.title, "note": "", "applied": filters, **stamp(request)}
    response = (export.to_xlsx if chosen == "xlsx" else export.to_pdf)(meta, columns, data)
    record(request.user, "LIST_EXPORTED", "list", spec.key, title=spec.title,
           format=export.FORMAT_NAMES[chosen], rows=len(data),
           filters="; ".join(f"{f['label']}: {f['value']}" for f in filters))
    return response
