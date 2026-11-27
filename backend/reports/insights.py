"""
What the dashboard's charts read beyond the headline figures: how the period compares with the one
before it, where failures come from, how long work has been waiting, how long release takes, and
whether the instruments and materials the lab relies on are in date.

Every figure here is a count of records the reports can list, read through the same definitions and
the same visibility rules as the reports, and each carries a link that opens exactly those records.
Nothing is stored.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.db.models import Count
from django.utils import timezone

from accounts.authz import has_perm
from accounts.models import User
from labrecords import services as lab
from labrecords.models import InstrumentStatus, Material, MaterialStatus
from labrecords.registers import REGISTERS
from lims.models import FINISHED, Outcome, Product, Section
from quality.models import InvestigationStatus
from quality.services import visible_investigations
from qclab.listing import Window
from .records import POSITIONS, bucket_of, days_between, mean
from .results import JUDGED

# Where a sample in the lab is. Finished ones are not waiting for anything.
WAITING_STAGES = ("AWAITING_TESTING", "UNDER_TESTING", "AWAITING_REVIEW", "AWAITING_APPROVAL")

# How long a sample has been in the lab, in whole calendar days. The Sample Register's "age" filter
# reads the same bands, so a segment opens exactly the samples it counts.
AGE_BANDS = {
    "0-2": ("0–2 days", 0, 2),
    "3-5": ("3–5 days", 3, 5),
    "6-10": ("6–10 days", 6, 10),
    "11+": ("11 days or more", 11, None),
}

# Days from receipt to release. Each band runs from its lower figure up to, not including, the next.
TURNAROUND_BANDS = [("<1", 0, 1), ("1–2", 1, 2), ("2–3", 2, 3), ("3–5", 3, 5), ("5–7", 5, 7),
                    ("7–10", 7, 10), ("10+", 10, None)]

# Where the dials and the traffic lights change colour: good from the first figure, a warning from the second.
# A reading guide for the screen, not a commitment the lab has made: what the lab promises is its own due
# dates, which the limits panel counts.
REFERENCE = {"pass_rate": (95, 85), "on_time": (90, 75)}

OUTLOOK_DAYS = 14
TABLE_ROWS = 10
EXPIRY_WARNING_DAYS = 30
TOP = 8


def _register(**query) -> str:
    return "/reports/sample-register?" + urlencode(query)


def _results(**query) -> str:
    return "/reports/test-results?" + urlencode(query)


def in_age_band(qs, band: str):
    """Samples still in the lab that have been there for the days the band names."""
    _, low, high = AGE_BANDS[band]
    today = timezone.localdate()

    def midnight(day):
        return timezone.make_aware(datetime.combine(day, time.min))

    # Received on or before the day `low` days ago, and no earlier than the day `high` days ago.
    found = qs.exclude(status__in=FINISHED).filter(received_at__lt=midnight(today - timedelta(days=low - 1)))
    if high is not None:
        found = found.filter(received_at__gte=midnight(today - timedelta(days=high)))
    return found


# --- the period before ------------------------------------------------------

def previous_window(window: Window) -> tuple[Window | None, str]:
    """
    The stretch to compare this one with, over as much of it as has passed: this month so far is put
    beside the same number of days of last month, never beside a whole month it has not yet had.
    """
    if window.start is None or window.stop is None:
        return None, ""
    elapsed = min(timezone.now(), window.stop) - window.start
    if elapsed <= timedelta(0):
        return None, ""
    if window.key in ("month", "lastmonth"):
        start = (timezone.localtime(window.start) - timedelta(days=1)).replace(day=1)
        label = "last month" if window.key == "month" else "the month before"
    elif window.key in ("week", "lastweek"):
        start = window.start - timedelta(days=7)
        label = "last week" if window.key == "week" else "the week before"
    else:
        start = window.start - (window.stop - window.start)
        label = "the period before"
    stop = min(start + elapsed, window.start)
    return Window("previous", label, start, stop), label


# --- headline figures -------------------------------------------------------

class Figures:
    """What a stretch of time amounted to: the numbers, and the moments they come from."""

    def __init__(self, window: Window, samples, results):
        self.received = list(window.apply(samples, "received_at").values_list("received_at", flat=True))
        self.released = list(
            window.apply(samples.filter(released_at__isnull=False), "released_at")
            .values_list("received_at", "released_at", "due_date")
        )
        self.days = [days_between(a, b) for a, b, _ in self.released]
        self.on_time = [timezone.localtime(b).date() <= due for _, b, due in self.released]
        entered = window.apply(results, "entered_at").exclude(outcome=Outcome.REPORTED)
        self.outcomes = list(entered.values_list("outcome", "entered_at"))
        self.passed = sum(1 for o, _ in self.outcomes if o == Outcome.PASS)
        self.failed = len(self.outcomes) - self.passed

    @property
    def pass_rate(self):
        return 100 * self.passed / len(self.outcomes) if self.outcomes else None

    @property
    def turnaround(self):
        return mean(self.days)

    @property
    def on_time_rate(self):
        return 100 * sum(self.on_time) / len(self.on_time) if self.on_time else None


def _delta(now, before, good, count: bool):
    """How a figure moved. A count carries its percentage change; a rate or an average, only the difference."""
    if now is None or before is None:
        return None
    change = now - before
    if count:
        return {"change": change, "percent": round(100 * change / before) if before else None, "good": good}
    return {"change": round(change, 1), "percent": None, "good": good}


def _spark(points: list) -> list:
    return [None if p is None else round(p, 1) for p in points]


def _rounded(value):
    return None if value is None else round(value, 1)


def kpis(window, period, samples, results, unit, buckets, late: int) -> dict:
    """The headline figures, each beside the same stretch of the period before, with its own small trend."""
    now = Figures(window, samples, results)
    before_window, compare = previous_window(window)
    before = Figures(before_window, samples, results) if before_window else None

    def trend(pairs, reduce, empty=None):
        """One value for each day, week or month: the pairs are (moment, value)."""
        grouped = defaultdict(list)
        for moment, value in pairs:
            grouped[bucket_of(timezone.localtime(moment).date(), unit)].append(value)
        return [reduce(grouped[b]) if b in grouped else empty for b in buckets]

    def average(values):
        return sum(values) / len(values)

    def tile(key, label, value, display, *, spark, to, prior, good=None, sub="", count=False):
        return {
            "key": key, "label": label, "value": value, "display": display, "sub": sub, "to": to,
            "spark": _spark(spark),
            "delta": _delta(value, prior, good, count) if before else None,
        }

    released_link = "/reports/turnaround?" + urlencode({"date_field": "released", **period})
    return {
        "compare": compare or None,
        "tiles": [
            tile("received", "Samples received", len(now.received), str(len(now.received)),
                 spark=trend(((m, 1) for m in now.received), sum, 0),
                 to=_register(date_field="received", **period), count=True,
                 prior=len(before.received) if before else None),
            tile("completed", "Samples completed", len(now.released), str(len(now.released)),
                 spark=trend(((b, 1) for _, b, _ in now.released), sum, 0), good="up",
                 to=_register(date_field="completed", stage="COMPLETED", **period), count=True,
                 prior=len(before.released) if before else None),
            tile("pass_rate", "Test pass rate", _rounded(now.pass_rate),
                 "–" if now.pass_rate is None else f"{now.pass_rate:.0f}%",
                 spark=trend(((at, 100 if o == Outcome.PASS else 0) for o, at in now.outcomes), average),
                 good="up", to=_results(outcome=JUDGED, **period), prior=_rounded(before.pass_rate) if before else None,
                 sub=f"{now.passed} passed, {now.failed} failed" if now.outcomes else "No results in this period"),
            tile("turnaround", "Average turnaround", _rounded(now.turnaround),
                 "–" if now.turnaround is None else f"{now.turnaround:.1f}d",
                 spark=trend(((b, days_between(a, b)) for a, b, _ in now.released), average),
                 good="down", to=released_link, prior=_rounded(before.turnaround) if before else None,
                 sub=f"{len(now.released)} released" if now.released else "Nothing released in this period"),
            tile("on_time", "Released on time", _rounded(now.on_time_rate),
                 "–" if now.on_time_rate is None else f"{now.on_time_rate:.0f}%",
                 spark=trend(((b, 100 if timezone.localtime(b).date() <= due else 0)
                              for _, b, due in now.released), average),
                 good="up", to=released_link, prior=_rounded(before.on_time_rate) if before else None,
                 sub=(f"{sum(now.on_time)} of {len(now.on_time)} by their due date" if now.on_time
                      else "Nothing released in this period")),
            {"key": "overdue", "label": "Overdue now", "value": late, "display": str(late), "spark": None,
             "delta": None, "sub": "Open samples past their due date", "to": _register(overdue=1),
             "alert": late > 0},
        ],
        "turnaround": _turnaround(now, released_link),
    }


def _turnaround(now: Figures, link: str) -> dict:
    """How long release took, in bands, with the share that made its due date."""
    bands = [
        {"label": label, "value": sum(1 for d in now.days if d >= low and (high is None or d < high))}
        for label, low, high in TURNAROUND_BANDS
    ]
    return {
        "bands": bands,
        "mean": _rounded(now.turnaround),
        "on_time": sum(now.on_time),
        "late": len(now.on_time) - sum(now.on_time),
        "to": link,
    }


# --- looking ahead ----------------------------------------------------------

def due_outlook(samples) -> dict:
    """Open samples by the day they fall due, for the next two weeks, with what is already late beside them."""
    today = timezone.localdate()
    last = today + timedelta(days=OUTLOOK_DAYS - 1)
    live = samples.exclude(status__in=FINISHED).order_by()
    counts = dict(live.filter(due_date__gte=today, due_date__lte=last).values_list("due_date").annotate(n=Count("id")))
    days = []
    for n in range(OUTLOOK_DAYS):
        day = (today + timedelta(days=n)).isoformat()
        days.append({
            "date": day, "value": counts.get(today + timedelta(days=n), 0),
            "to": _register(date_field="due", open=1, **{"from": day, "to": day}),
        })
    return {
        "overdue": {"value": live.filter(due_date__lt=today).count(), "to": _register(due="overdue")},
        "days": days,
        "later": {
            "value": live.filter(due_date__gt=last).count(),
            "to": _register(date_field="due", open=1, **{"from": (last + timedelta(days=1)).isoformat()}),
        },
    }


def ageing(samples) -> dict:
    """Samples in the lab, by where they are and how long they have been there."""
    live = samples.exclude(status__in=FINISHED).order_by()
    today = timezone.localdate()
    keys = list(AGE_BANDS)
    stages = []
    for stage in WAITING_STAGES:
        values = [0] * len(keys)
        for received in live.filter(POSITIONS[stage][1]).values_list("received_at", flat=True):
            age = max((today - timezone.localtime(received).date()).days, 0)
            for i, band in enumerate(keys):
                _, low, high = AGE_BANDS[band]
                if age >= low and (high is None or age <= high):
                    values[i] += 1
                    break
        stages.append({
            "key": stage, "label": POSITIONS[stage][0], "values": values,
            "links": [_register(stage=stage, age=band) for band in keys],
        })
    return {"bands": [{"key": k, "label": AGE_BANDS[k][0]} for k in keys], "stages": stages}


# --- where failures come from ----------------------------------------------

def failures(results, period: dict, window: Window) -> dict:
    """Failed results in the period, by test and by product, each against everything entered for it."""
    entered = window.apply(results, "entered_at").exclude(outcome=Outcome.REPORTED).order_by()

    def ranked(field: str, labels, link):
        totals = dict(entered.values_list(field).annotate(n=Count("id")))
        failed = dict(entered.filter(outcome=Outcome.FAIL).values_list(field).annotate(n=Count("id")))
        names = labels(list(failed))
        rows = [
            {"label": names[key], "failed": n, "total": totals[key], "rate": round(100 * n / totals[key]),
             "to": link(key)}
            for key, n in failed.items() if key in names
        ]
        return sorted(rows, key=lambda r: (-r["failed"], r["label"]))[:TOP]

    return {
        "tests": ranked(
            "test_definition__name", lambda keys: {k: k for k in keys},
            lambda name: _results(outcome=Outcome.FAIL, test_name=name, **period),
        ),
        "products": ranked(
            "sample__product_id", lambda keys: dict(Product.objects.filter(pk__in=keys).values_list("pk", "name")),
            lambda pk: _results(outcome=Outcome.FAIL, product=pk, **period),
        ),
    }


# --- equipment --------------------------------------------------------------

def equipment(user) -> dict | None:
    """Whether the instruments and materials the lab relies on are in date. None for someone who may see neither."""
    today = timezone.localdate()
    soon = today + timedelta(days=EXPIRY_WARNING_DAYS)
    shown = {}
    if REGISTERS["instruments"].visible_to(user):
        counts = {"ok": 0, "soon": 0, "late": 0, "out": 0}
        for i in lab.instruments_with_next_due().exclude(status=InstrumentStatus.RETIRED).order_by():
            if i.status != InstrumentStatus.IN_SERVICE:
                counts["out"] += 1
            elif i.next_due is None or i.next_due < today:
                counts["late"] += 1
            elif i.next_due < soon:
                counts["soon"] += 1
            else:
                counts["ok"] += 1
        shown["instruments"] = {
            "title": "Instruments", "to": "/lab/instruments",
            "rows": [
                {"key": "ok", "label": "Calibrated, in date", "value": counts["ok"]},
                {"key": "soon", "label": f"Calibration due within {EXPIRY_WARNING_DAYS} days", "value": counts["soon"]},
                {"key": "late", "label": "Calibration overdue or never done", "value": counts["late"]},
                {"key": "out", "label": "Out of service", "value": counts["out"]},
            ],
        }
    if REGISTERS["materials"].visible_to(user):
        counts = {"ok": 0, "soon": 0, "late": 0, "held": 0}
        for status, expiry in Material.objects.exclude(status=MaterialStatus.RETIRED).values_list(
            "status", "expiry_date"
        ):
            if status == MaterialStatus.QUARANTINED:
                counts["held"] += 1
            elif expiry < today:
                counts["late"] += 1
            elif expiry < soon:
                counts["soon"] += 1
            else:
                counts["ok"] += 1
        shown["materials"] = {
            "title": "Standards and reagents", "to": "/lab/materials",
            "rows": [
                {"key": "ok", "label": "Available, in date", "value": counts["ok"]},
                {"key": "soon", "label": f"Expiring within {EXPIRY_WARNING_DAYS} days", "value": counts["soon"]},
                {"key": "late", "label": "Past their expiry date", "value": counts["late"]},
                {"key": "held", "label": "Quarantined", "value": counts["held"]},
            ],
        }
    return shown or None


# --- the scorecard ----------------------------------------------------------

def _status(value, reference):
    """good, warn or bad against a reading guide; none when there is nothing to judge."""
    if value is None:
        return "none"
    good, warn = reference
    return "good" if value >= good else "warn" if value >= warn else "bad"


def _share(part, whole):
    return None if not whole else round(100 * part / whole, 1)


def _trend(pairs, unit, buckets, reduce, empty=None):
    """One value for each day, week or month: the pairs are (moment, value)."""
    grouped = defaultdict(list)
    for moment, value in pairs:
        grouped[bucket_of(timezone.localtime(moment).date(), unit)].append(value)
    return [round(reduce(grouped[b]), 1) if b in grouped else empty for b in buckets]


def _average(values):
    return sum(values) / len(values)


def scorecard(user, window, period, samples, results, unit, buckets, equipment_now, waiting=None) -> dict:
    """
    The lab at a glance as a scorecard: dials for how results and release went, a table by product (and by
    analyst, for whoever may plan work), the failure rate by section, and the limits the lab has to stay within.
    """
    judged = list(
        window.apply(results, "entered_at").exclude(outcome=Outcome.REPORTED).order_by()
        .values_list("sample__product_id", "sample__section_id", "outcome", "entered_at")
    )
    received = list(window.apply(samples, "received_at").order_by().values_list("product_id", flat=True))
    released = list(
        window.apply(samples.filter(released_at__isnull=False), "released_at").order_by()
        .values_list("product_id", "received_at", "released_at", "due_date", "assigned_analyst_id")
    )

    passed = sum(1 for _, _, o, _ in judged if o == Outcome.PASS)
    on_time = [timezone.localtime(b).date() <= due for _, _, b, due, _ in released]
    pass_rate = _share(passed, len(judged))
    on_time_rate = _share(sum(on_time), len(on_time))
    released_link = "/reports/turnaround?" + urlencode({"date_field": "released", **period})

    gauges = [
        {"key": "pass_rate", "label": "Test pass rate", "value": pass_rate, "reference": REFERENCE["pass_rate"],
         "status": _status(pass_rate, REFERENCE["pass_rate"]),
         "sub": f"{passed} passed, {len(judged) - passed} failed" if judged else "No results in this period",
         "to": _results(outcome=JUDGED, **period)},
        {"key": "on_time", "label": "Released on time", "value": on_time_rate, "reference": REFERENCE["on_time"],
         "status": _status(on_time_rate, REFERENCE["on_time"]),
         "sub": f"{sum(on_time)} of {len(on_time)} by their due date" if on_time else "Nothing released in this period",
         "to": released_link},
    ]

    # By product: what came in, how its results went, how long release took, and the trend of its pass rate.
    codes = dict(Product.objects.values_list("pk", "code"))
    titles = dict(Product.objects.values_list("pk", "name"))
    by_product = defaultdict(lambda: {"received": 0, "results": [], "released": []})
    for pid in received:
        by_product[pid]["received"] += 1
    for pid, _, outcome, at in judged:
        by_product[pid]["results"].append((at, outcome))
    for pid, got, done, due, _ in released:
        by_product[pid]["released"].append((got, done, due))
    rows = []
    for pid, got in by_product.items():
        good = sum(1 for _, o in got["results"] if o == Outcome.PASS)
        rate = _share(good, len(got["results"]))
        days = [days_between(a, b) for a, b, _ in got["released"]]
        timely = [timezone.localtime(b).date() <= due for _, b, due in got["released"]]
        rows.append({
            "id": pid, "label": titles.get(pid, ""), "code": codes.get(pid, ""),
            "received": got["received"], "results": len(got["results"]), "completed": len(got["released"]),
            "passed": good, "failed": len(got["results"]) - good,
            "pass_rate": rate, "on_time": _share(sum(timely), len(timely)), "turnaround": _rounded(mean(days)),
            "spark": _trend(((at, 100 if o == Outcome.PASS else 0) for at, o in got["results"]), unit, buckets, _average),
            "status": _status(rate, REFERENCE["pass_rate"]),
            "to": f"/reports/product/{pid}",
            "to_received": _register(product=pid, date_field="received", **period),
            "to_results": _results(product=pid, outcome=JUDGED, **period),
            "to_released": "/reports/turnaround?" + urlencode({"product": pid, "date_field": "released", **period}),
        })
    rows.sort(key=lambda r: (-r["results"], -r["received"], r["label"]))

    # By section: the share of results that failed, each against everything entered there.
    totals, failed = defaultdict(int), defaultdict(int)
    for _, sid, outcome, _ in judged:
        totals[sid] += 1
        failed[sid] += outcome == Outcome.FAIL
    sections = [
        {"label": s.name, "code": s.code, "failed": failed[s.pk], "total": totals[s.pk],
         "rate": round(100 * failed[s.pk] / totals[s.pk], 1),
         "to": _results(outcome=Outcome.FAIL, section=s.pk, **period)}
        for s in Section.objects.filter(pk__in=totals).order_by("name")
    ]

    card = {
        "reference": {k: {"good": g, "warn": w} for k, (g, w) in REFERENCE.items()},
        "gauges": gauges,
        "products": rows[:TABLE_ROWS],
        "sections": sections,
        "limits": _limits(user, samples, equipment_now),
    }
    if has_perm(user, "report.performance"):
        card["analysts"] = _analysts(user, unit, buckets, released, waiting)
    return card


def _analysts(user, unit, buckets, released, waiting=None) -> list[dict]:
    """What each analyst holds and how long release took for them: for planning the work, not for ranking people."""
    from .workflow import waiting_work  # the workflow reports read this module's filters

    open_work = defaultdict(lambda: {"open": 0, "overdue": 0, "name": ""})
    for row in waiting if waiting is not None else waiting_work(user):
        mine = open_work[row["analyst_id"]]
        mine["name"] = row["analyst_name"]
        mine["open"] += 1
        mine["overdue"] += 1 if row["overdue_days"] > 0 else 0
    done = defaultdict(list)
    for _, got, finished, due, analyst in released:
        done[analyst].append((got, finished, due))
    ids = {a for a in {*open_work, *done} if a}
    people = {u.pk: u.display_name() for u in User.objects.filter(pk__in=ids)}
    rows = []
    for pk in ids:
        mine = open_work.get(pk, {"open": 0, "overdue": 0, "name": ""})
        finished = done.get(pk, [])
        days = [days_between(a, b) for a, b, _ in finished]
        timely = [timezone.localtime(b).date() <= due for _, b, due in finished]
        # Someone with something overdue is flagged, in proportion to what they hold.
        share = mine["overdue"] / mine["open"] if mine["open"] else None
        rows.append({
            "id": pk, "label": people.get(pk) or mine["name"], "open": mine["open"], "overdue": mine["overdue"],
            "completed": len(finished), "turnaround": _rounded(mean(days)), "on_time": _share(sum(timely), len(timely)),
            "spark": _trend(((b, 1) for _, b, _ in finished), unit, buckets, sum, 0),
            "status": "none" if share is None else "good" if share == 0 else "warn" if share <= 0.25 else "bad",
            "to": f"/reports/pending-work?analyst={pk}",
        })
    rows.sort(key=lambda r: (-r["open"], r["label"]))
    return rows[:TABLE_ROWS]


def _limits(user, samples, equipment_now) -> list[dict]:
    """
    What the lab has to stay within: a due date is the promise a sample was registered with, a calibration
    or an expiry date is a rule. Each is a share inside its limit, with the ones outside it a click away.
    """
    today = timezone.localdate()
    live = samples.exclude(status__in=FINISHED).order_by()
    open_n, late_n = live.count(), live.filter(due_date__lt=today).count()
    limits = [{
        "key": "samples", "label": "Open samples within their due date", "total": open_n, "outside": late_n,
        "to": _register(due="overdue") if late_n else None,
    }]
    cases = visible_investigations(user).order_by().exclude(status=InvestigationStatus.CLOSED)
    case_n, case_late = cases.count(), cases.filter(due_date__lt=today).count()
    limits.append({
        "key": "investigations", "label": "Open investigations within their due date", "total": case_n,
        "outside": case_late, "to": "/reports/deviations?late=1" if case_late else None,
    })
    for group, label in (("instruments", "Instruments in calibration"), ("materials", "Standards and reagents in date")):
        rows = {r["key"]: r["value"] for r in (equipment_now or {}).get(group, {}).get("rows", [])}
        if not rows:
            continue
        limits.append({
            "key": group, "label": label, "total": rows["ok"] + rows["soon"] + rows["late"], "outside": rows["late"],
            "to": equipment_now[group]["to"] if rows["late"] else None,
        })
    return limits
