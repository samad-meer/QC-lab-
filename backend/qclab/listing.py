"""
One way to list anything.

Every list in the app is filtered by date and paged here, so an endpoint
states only what is particular to it: which records, and which of their
dates can be filtered on. The screens have the one matching control
(frontend/src/useList.ts and frontend/src/components/list/).

A list reads these query parameters:

- period=today|week|month|quarter|all, or from= and to= (either may be left
  open) — a date, or a date and time. Naive values are in the lab's time zone.
- date_field= — which date to filter on, where a list has more than one.
- q= — text to look for, where a list can be searched.
- page= and page_size=.

and always answers in the same shape: results, count, page, page_size, pages.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.paginator import Paginator
from django.db.models import DateTimeField, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ParseError
from rest_framework.response import Response

from accounts.lab_zone import clock

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200

PERIODS = {
    "today": "Today",
    "week": "This week",
    "month": "This month",
    "quarter": "Last 90 days",
    "all": "All time",
}


@dataclass(frozen=True)
class Window:
    """A stretch of time, from start up to but not including stop. None leaves that end open."""

    key: str  # a key of PERIODS, or "custom"
    label: str
    start: datetime | None = None
    stop: datetime | None = None

    def apply(self, qs, field: str):
        # One filter() call: across a relation, two would match different rows.
        limits = {}
        if self.start is not None:
            limits[f"{field}__gte"] = self.start
        if self.stop is not None:
            limits[f"{field}__lt"] = self.stop
        return qs.filter(**limits)

    def apply_to_dates(self, qs, field: str):
        """The same window over a date with no time of day, such as a due date."""
        limits = {}
        if self.start is not None:
            limits[f"{field}__gte"] = timezone.localtime(self.start).date()
        if self.stop is not None:
            limits[f"{field}__lte"] = timezone.localtime(self.stop - timedelta(microseconds=1)).date()
        return qs.filter(**limits)


def period_window(period: str) -> Window:
    """
    Weeks start Monday and months on the 1st — the lab's own calendar, not a
    rolling 7/30 days, because "this week" means the week you are in. Each
    runs to the end of the period, so a sample due later this week counts.
    """
    today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    if period == "today":
        start, stop = today, tomorrow
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        stop = start + timedelta(days=7)
    elif period == "month":
        start = today.replace(day=1)
        stop = (start + timedelta(days=32)).replace(day=1)
    elif period == "quarter":
        start, stop = today - timedelta(days=89), tomorrow
    else:
        return Window("all", PERIODS["all"])
    return Window(period, PERIODS[period], start, stop)


def _moment(raw: str, is_end: bool) -> datetime:
    try:
        # The date first: parse_datetime reads a bare date as that midnight.
        day = parse_date(raw)
        value = None if day else parse_datetime(raw)
    except ValueError:  # the right shape, but no such date: 31 February
        value = day = None
    if value is None and day is None:
        raise ParseError(f"“{raw}” is not a valid date and time.")
    if day is not None:
        value = timezone.make_aware(datetime.combine(day, time.min))
        return value + timedelta(days=1) if is_end else value
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    # The screens pick a time to the minute, so an end includes that whole minute.
    return value.replace(second=0, microsecond=0) + timedelta(minutes=1) if is_end else value


def _custom_label(start, stop) -> str:
    def shown(moment):
        return timezone.localtime(moment).strftime(f"%d %b %Y, {clock(seconds=False)}")

    last = stop - timedelta(minutes=1) if stop else None
    if start and stop:
        return f"{shown(start)} to {shown(last)}"
    return f"From {shown(start)}" if start else f"Up to {shown(last)}"


def window_from(request, default: str = "all") -> Window:
    """The time window a request asks for. Dates that make no sense are refused, not ignored."""
    params = request.query_params
    raw_from, raw_to = params.get("from"), params.get("to")
    if not raw_from and not raw_to:
        period = params.get("period")
        return period_window(period if period in PERIODS else default)
    start = _moment(raw_from, is_end=False) if raw_from else None
    stop = _moment(raw_to, is_end=True) if raw_to else None
    if start is not None and stop is not None and start >= stop:
        raise ParseError("The start of the date range is after its end.")
    return Window("custom", _custom_label(start, stop), start, stop)


def filter_by_date(request, qs, fields: dict[str, str], default: str = "all"):
    """
    Narrow a list to the requested window. `fields` maps the name a screen
    uses to the model field; the first is the one used unless it asks otherwise.
    """
    key = request.query_params.get("date_field") or next(iter(fields))
    if key not in fields:
        raise ParseError("This list cannot be filtered by that date.")
    window = window_from(request, default)
    field = fields[key]
    if isinstance(qs.model._meta.get_field(field), DateTimeField):
        return window.apply(qs, field)
    return window.apply_to_dates(qs, field)


def filter_by_text(request, qs, fields: list[str]):
    """Keep the rows with ?q= somewhere in these fields, ignoring case."""
    text = request.query_params.get("q", "").strip()
    if not text:
        return qs
    match = Q()
    for field in fields:
        match |= Q(**{f"{field}__icontains": text})
    return qs.filter(match)


def _page_size(request) -> int:
    try:
        size = int(request.query_params.get("page_size", DEFAULT_PAGE_SIZE))
    except ValueError:
        return DEFAULT_PAGE_SIZE
    return min(max(size, 1), MAX_PAGE_SIZE)


def paginated(request, qs, serialize, *, export=None, **extra) -> Response:
    """
    One page of a list. `serialize` turns that page's rows into JSON, so only
    those rows are worked on. A page past the end gives the last page: a filter
    can shrink a list under someone already on page 9. `extra` adds whatever
    else that list reports, such as totals across all its pages.

    A list given `export` (a reports.list_export.ListExport) also answers
    ?file=xlsx or ?file=pdf with the whole list as that file.
    """
    if export is not None and "file" in request.query_params:
        from reports.list_export import respond  # reports builds on this module

        return respond(request, qs, export)
    size = _page_size(request)
    paginator = Paginator(qs, size)
    page = paginator.get_page(request.query_params.get("page"))
    return Response({
        "results": serialize(page.object_list),
        "count": paginator.count,
        "page": page.number,
        "page_size": size,
        "pages": paginator.num_pages,
        **extra,
    })
