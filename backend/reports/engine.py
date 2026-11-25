"""
One way to report anything.

A report states what is particular to it: which records, which columns, which
filters and dates, and how one record becomes a row. Everything else lives
here, once, so every report behaves the same: date ranges and paging (through
qclab/listing.py), column filters, sorting, the generation stamp, who may open
it and what they may see. The screens (frontend/src/pages/reports) and the
exports (reports/export.py) both read a report through this module, so a
downloaded report can never say something different from the one on screen.

Every date is written here, once, in the lab's time zone, so a report reads
the same whoever opens it, wherever they are.

Records come from two places. Most reports list a queryset, and the database
sorts and pages it. A few have to work their figures out first (workload,
bottlenecks, what is waiting): those return a list of finished rows instead,
and the same filters and sorting apply to the list.
"""
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Callable

from django.db.models import F, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ParseError

from accounts.authz import has_perm
from accounts.lab_zone import clock
from accounts.permissions_registry import report_permission
from qclab.listing import PERIODS, Window, window_from

DATE_FORMAT = "%d-%b-%Y"


def text_of(value) -> str:
    """The one way a value is written, on screen and in every export."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime(f"{DATE_FORMAT} {clock()}")
    if isinstance(value, date):
        return value.strftime(DATE_FORMAT)
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


@dataclass(frozen=True)
class Cell:
    """A value and what a screen adds to it. Exports carry the value and its second line."""

    value: object
    to: str = ""  # where clicking it leads: the source record
    tone: str = ""  # shown as a badge: pass, fail, warn, info, hot, muted
    sub: str = ""  # a second, smaller line: often who did it, so it is part of the record
    screen_only: bool = False  # the second line is a reading aid, and the value must stay a plain number


def plain(cell):
    return cell.value if isinstance(cell, Cell) else cell


def exported(cell):
    """What a file carries: a real number or date where it can, the words beside it where there are any."""
    if not isinstance(cell, Cell):
        return cell
    if not cell.sub or cell.screen_only:
        return cell.value
    return f"{text_of(cell.value)} — {cell.sub}" if text_of(cell.value) else cell.sub


def cell_json(cell):
    if not isinstance(cell, Cell):
        return text_of(cell)
    out = {"text": text_of(cell.value)}
    if cell.to:
        out["to"] = cell.to
    if cell.tone:
        out["tone"] = cell.tone
    if cell.sub:
        out["sub"] = cell.sub
    return out


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    sort: str = ""  # the model field to order by, or the row key of a computed report
    numeric: bool = False
    width: float = 1.0  # its share of the page in a PDF
    wrap: bool = False  # free text: it wraps on screen, where everything else keeps to one line


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    apply: Callable  # (records, value) -> records
    kind: str = "select"  # select, text or toggle
    options: Callable | list | None = None  # (request) -> [(value, label)], for a select
    blank: str = ""  # what choosing nothing means, if not "All": a report about one person says "Me"


@dataclass(frozen=True)
class Dates:
    """A date a report can be filtered on."""

    label: str
    field: str
    date_only: bool = False


class Report:
    key = ""
    title = ""
    category = ""
    description = ""
    # Shown under the title: what the figures mean and what they do not.
    note = ""
    # (button label, where it leads, the permission it needs), if the report offers one.
    action: tuple[str, str, str] | None = None
    columns: list[Column] = []
    filters: list[Filter] = []
    dates: dict[str, Dates] = {}
    default_period = "all"
    default_sort = ""
    # False for a report about a person's own work, which is not limited by the samples they can see.
    sample_scope = True
    # True when the figures above the list belong on a print too, as a report of someone's week does.
    print_summary = False

    def records(self, request):
        """Everything this person may see in this report: a queryset, or a list of rows."""
        raise NotImplementedError

    def grouped(self, records):
        """Runs after the filters: a report of batches filters samples, then groups them."""
        return records

    def subject(self, request) -> str:
        """Whom or what the report is about, if it is about one: said on screen and at the head of a print."""
        return ""

    def may_export(self, request) -> bool:
        """Who may download it. A report of someone's own work may be printed by them without more."""
        return has_perm(request.user, "report.export")

    def rows(self, records: list, request) -> list[dict]:
        """One page of records as rows, keyed by column. Work on the page together, not row by row."""
        return records

    def summary(self, records, request) -> list[dict]:
        """Tiles above the table, over everything the filters selected."""
        return []

    @property
    def permission(self) -> str:
        """Each report is a permission of its own, so a role can be given one report and no other."""
        return report_permission(self.key)


REPORTS: dict[str, Report] = {}

# The history page of one record goes with the report it opens from.
DOCUMENTS = {"sample-history": "sample-register", "batch": "batches", "product": "product-history"}


def may_open(user, report_key: str) -> bool:
    """The Reports module, and this report in it."""
    return has_perm(user, "report.view") and has_perm(user, report_permission(report_key))


def opens(user, to: str) -> bool:
    """May this person follow a link? Only a link into a report they cannot open is shut."""
    if not to.startswith("/reports/"):
        return True
    first = to.removeprefix("/reports/").split("?")[0].split("/")[0]
    return may_open(user, DOCUMENTS.get(first, first))


def reachable(value, user):
    """A screen's payload with every link this person cannot follow taken out, the text kept."""
    if isinstance(value, list):
        return [reachable(v, user) for v in value]
    if isinstance(value, Cell):
        return value if not value.to or opens(user, value.to) else replace(value, to="")
    if isinstance(value, dict):
        out = {k: reachable(v, user) for k, v in value.items()}
        if isinstance(out.get("to"), str) and out["to"] and not opens(user, out["to"]):
            del out["to"]
        return out
    return value

CATEGORIES = [
    ("samples", "Sample Reports", "Where is each sample in the testing process?"),
    ("tests", "Test Results & Failures", "Which tests passed, failed, or require investigation?"),
    ("batches", "Batch & Product Reports", "What is the QC history of a product or batch?"),
    ("workflow", "Workflow & Performance", "What is pending, overdue, or taking too long?"),
    ("compliance", "Quality & Compliance", "Who changed or approved records, and which documents were used?"),
]


def register(cls):
    report = cls()
    REPORTS[report.key] = report
    return cls


def window_of(report: Report, request) -> Window:
    return window_from(request, report.default_period)


def _dated(report: Report, request, records):
    if not report.dates or not isinstance(records, QuerySet):
        return records
    key = request.query_params.get("date_field") or next(iter(report.dates))
    if key not in report.dates:
        raise ParseError("This report cannot be filtered by that date.")
    chosen, window = report.dates[key], window_of(report, request)
    if chosen.date_only:
        return window.apply_to_dates(records, chosen.field)
    return window.apply(records, chosen.field)


def options_of(flt: Filter, request) -> list[tuple]:
    if flt.options is None:
        return []
    return flt.options(request) if callable(flt.options) else flt.options


def _filtered(report: Report, request, records):
    for flt in report.filters:
        value = (request.query_params.get(flt.key) or "").strip()
        if not value:
            continue
        if flt.kind == "select" and value not in {str(v) for v, _ in options_of(flt, request)}:
            raise ParseError(f"“{value}” is not a choice for {flt.label}.")
        records = flt.apply(records, value)
    return records


def _sorted(report: Report, request, records):
    asked = request.query_params.get("sort") or report.default_sort
    if not asked:
        return records
    descending = asked.startswith("-")
    column = next((c for c in report.columns if c.key == asked.lstrip("-") and c.sort), None)
    if column is None:
        raise ParseError("This report cannot be sorted by that column.")
    if isinstance(records, QuerySet):
        order = F(column.sort)
        # A blank goes last either way, and the id keeps paging stable between equal rows.
        order = order.desc(nulls_last=True) if descending else order.asc(nulls_last=True)
        return records.order_by(order, *(records.query.values_select or ("-pk",)))

    def key(row):
        value = plain(row.get(column.sort))
        return value.lower() if isinstance(value, str) else value

    blank = [r for r in records if key(r) in (None, "")]
    filled = [r for r in records if key(r) not in (None, "")]
    return sorted(filled, key=key, reverse=descending) + blank


def select(report: Report, request):
    """The records a request asks for, in order, before paging."""
    records = _filtered(report, request, _dated(report, request, report.records(request)))
    return _sorted(report, request, report.grouped(records))


def stamp(request, scoped: bool = True) -> dict:
    """Who produced this, when, and in which time zone — on every report."""
    return {
        "generated_at": text_of(timezone.now()),
        "generated_by": request.user.display_name(),
        "timezone": timezone.get_current_timezone_name(),
        "partial": scoped and not has_perm(request.user, "sample.view.all"),
    }


def period_label(report: Report, request) -> str:
    return window_of(report, request).label if report.dates else ""


def filters_applied(report: Report, request) -> list[dict]:
    """The filters in force, as a person reads them, for the top of an export."""
    applied = []
    if report.subject(request):
        applied.append({"label": "Report for", "value": report.subject(request)})
    if report.dates:
        window = window_of(report, request)
        key = request.query_params.get("date_field") or next(iter(report.dates))
        applied.append({"label": report.dates[key].label, "value": window.label})
    for flt in report.filters:
        value = (request.query_params.get(flt.key) or "").strip()
        if not value:
            continue
        labels = {str(v): label for v, label in options_of(flt, request)}
        applied.append({"label": flt.label, "value": "Yes" if flt.kind == "toggle" else labels.get(value, value)})
    if report.sample_scope and not has_perm(request.user, "sample.view.all"):
        applied.append({"label": "Scope", "value": "Only the samples you can see, so this may not be the whole picture"})
    return applied


def definition(report: Report, request, can_export: bool, can_act: bool) -> dict:
    return {
        "key": report.key,
        "title": report.title,
        "category": report.category,
        "description": report.description,
        "note": report.note,
        "columns": [
            {"key": c.key, "label": c.label, "sortable": bool(c.sort), "numeric": c.numeric, "wrap": c.wrap}
            for c in report.columns
        ],
        "filters": [
            {
                "key": f.key, "label": f.label, "kind": f.kind, "blank": f.blank,
                "options": [{"value": str(v), "label": label} for v, label in options_of(f, request)],
            }
            for f in report.filters
        ],
        "dates": [{"key": k, "label": d.label} for k, d in report.dates.items()],
        "has_dates": bool(report.dates),
        "default_period": report.default_period if report.default_period in PERIODS else "all",
        "default_sort": report.default_sort,
        "can_export": can_export,
        "action": {"label": report.action[0], "to": report.action[1]} if report.action and can_act else None,
    }
