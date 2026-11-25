"""Test results and failures: what was found, and what was done about it."""
from collections import defaultdict
from statistics import stdev

from django.db.models import Exists, OuterRef, Q

from accounts.authz import has_perm
from execution.models import RetestKind, RetestRequest, RetestStatus
from lims.models import Outcome
from lims.workflow import samples_visible_to
from quality.models import Investigation, InvestigationKind, InvestigationStatus
from .engine import Cell, Column, Dates, Filter, Report, register, text_of, window_of
from .records import (
    INVESTIGATION_TONES,
    OUTCOME_TONES,
    analyst_options,
    batch_text,
    covering_investigation,
    investigations_by_test,
    mean,
    measure,
    product_options,
    result_value,
    results_visible_to,
    retest_results,
    retests_of,
    review_signatures,
    section_options,
    spec_options,
    test_name_options,
    with_unit,
)


def _sample_cell(sample) -> Cell:
    return Cell(sample.sample_no, to=f"/reports/sample-history/{sample.pk}")


# Passed and failed together: what a pass rate is a share of. A result reported only as "<LOQ" or "ND" is neither.
JUDGED = "JUDGED"


def _by_outcome(qs, value):
    return qs.exclude(outcome=Outcome.REPORTED) if value == JUDGED else qs.filter(outcome=value)


@register
class ResultsRegister(Report):
    key = "test-results"
    title = "Test Results Register"
    category = "tests"
    description = "Every recorded result with the method, specification version and limit it was judged against."
    note = (
        "Methods appear as written in the specification version. "
        "Limits and pass/fail are the ones bound when the sample was registered."
    )
    columns = [
        Column("sample", "Sample ID", "sample__sample_no", width=1.1),
        Column("product", "Product", "sample__product__name", width=1.3),
        Column("batch", "Batch / Lot", "sample__batch_no", width=0.8),
        Column("test", "Test", "test_definition__name", width=1.2),
        Column("method", "Method", "test_definition__method"),
        Column("spec", "Spec version", "sample__specification__version", width=0.6),
        Column("result", "Result", width=0.8),
        Column("limit", "Acceptance criteria", width=1.1),
        Column("outcome", "Pass/fail", "outcome", width=0.8),
        Column("analyst", "Analyst", "entered_by__first_name"),
        Column("reviewer", "Reviewer"),
        Column("tested", "Test date", "entered_at", width=1.15),
        Column("reviewed", "Review date", width=1.15),
    ]
    dates = {"tested": Dates("Test date", "entered_at")}
    default_sort = "-tested"
    filters = [
        Filter("product", "Product", lambda qs, v: qs.filter(sample__product_id=v), options=product_options),
        Filter("test", "Test", lambda qs, v: qs.filter(test_definition__name__icontains=v), kind="text"),
        Filter("test_name", "Test, exact name", lambda qs, v: qs.filter(test_definition__name=v),
               options=test_name_options),
        Filter("batch", "Batch / Lot", lambda qs, v: qs.filter(
            Q(sample__batch_no__icontains=v) | Q(sample__reference__icontains=v)
        ), kind="text"),
        Filter("analyst", "Analyst", lambda qs, v: qs.filter(entered_by_id=v), options=analyst_options),
        Filter("outcome", "Result status", lambda qs, v: _by_outcome(qs, v),
               options=[(o.value, o.label) for o in Outcome] + [(JUDGED, "Passed or failed")]),
        Filter("spec", "Specification", lambda qs, v: qs.filter(sample__specification_id=v), options=spec_options),
        Filter("current", "Current results only", lambda qs, v: qs, kind="toggle"),
    ]

    def records(self, request):
        qs = results_visible_to(request.user)
        if request.query_params.get("current"):
            qs = qs.filter(is_superseded=False)
        return qs

    def rows(self, results, request):
        signatures = review_signatures({r.sample_id for r in results})
        rows = []
        for r in results:
            first = next(iter(signatures.get(r.sample_id, [])), None) if not r.is_superseded else None
            outcome_sub = "Superseded" if r.is_superseded else ""
            rows.append({
                "sample": _sample_cell(r.sample),
                "product": Cell(r.sample.product.name, sub=r.sample.product.code),
                "batch": r.sample.batch_label,
                "test": r.test_definition.name,
                "method": Cell(r.test_definition.method, sub=r.test_definition.source),
                "spec": f"v{r.sample.specification.version}",
                "result": with_unit(r),
                "limit": r.test_definition.limit_text,
                "outcome": Cell(r.get_outcome_display(), tone=OUTCOME_TONES.get(r.outcome, ""), sub=outcome_sub),
                "analyst": r.entered_by.display_name(),
                "reviewer": first.name_snapshot if first else "",
                "tested": r.entered_at,
                "reviewed": first.signed_at if first else None,
            })
        return rows


def _capa_text(inv) -> str:
    return "; ".join(a.description for a in inv.actions.all())


@register
class OutOfSpecification(Report):
    key = "oos"
    title = "OOS Investigations"
    category = "tests"
    description = "Every result outside its specification, with what followed it. Nothing here is ever overwritten."
    note = (
        "The failed result stays listed whatever came next. A passing retest does not invalidate it: "
        "only a closed investigation records why it stands or falls."
    )
    columns = [
        Column("sample", "Sample ID", "sample__sample_no", width=1.1),
        Column("product", "Product / batch", "sample__product__name", width=1.2),
        Column("test", "Test", "test_definition__name"),
        Column("original", "Failed result", width=0.8),
        Column("limit", "Acceptance limits", width=1),
        Column("entered", "Date", "entered_at", width=1.1),
        Column("analyst", "Analyst", "entered_by__first_name", width=0.9),
        Column("retest", "Followed by", width=1),
        Column("investigation", "Investigation", width=1),
        Column("status", "Investigation status", width=1),
        Column("root_cause", "Root cause", width=1.3, wrap=True),
        Column("actions", "Corrective actions", width=1.3, wrap=True),
        Column("closure", "Closure approval", width=1),
        Column("outcome", "Final outcome", width=1.3, wrap=True),
    ]
    dates = {"entered": Dates("Result date", "entered_at")}
    default_sort = "-entered"
    filters = [
        Filter("product", "Product", lambda qs, v: qs.filter(sample__product_id=v), options=product_options),
        Filter("test", "Test", lambda qs, v: qs.filter(test_definition__name__icontains=v), kind="text"),
        Filter("analyst", "Analyst", lambda qs, v: qs.filter(entered_by_id=v), options=analyst_options),
        Filter("state", "Investigation", lambda qs, v: _by_investigation(qs, v), options=[
            ("NONE", "None opened"), *[(s.value, s.label) for s in InvestigationStatus],
        ]),
    ]

    def records(self, request):
        return results_visible_to(request.user).filter(outcome=Outcome.FAIL)

    def rows(self, results, request):
        ids = [r.pk for r in results]
        found = investigations_by_test({(r.sample_id, r.test_definition_id) for r in results})
        followed = retests_of(ids)
        were_retests = retest_results(ids)
        may_open = has_perm(request.user, "investigation.manage")
        rows = []
        for r in results:
            inv = covering_investigation(found, r.sample_id, r.test_definition_id, r.entered_at)
            rows.append({
                "sample": _sample_cell(r.sample),
                "product": Cell(r.sample.product.name, sub=batch_text(r.sample)),
                "test": r.test_definition.name,
                "original": Cell(with_unit(r), sub="A retest that also failed" if r.pk in were_retests else ""),
                "limit": r.test_definition.limit_text,
                "entered": r.entered_at,
                "analyst": r.entered_by.display_name(),
                "retest": _followed_by(followed.get(r.pk, [])),
                "investigation": (
                    Cell(inv.reference, to=f"/investigations/{inv.id}") if inv
                    else Cell("None opened", tone="warn", to=f"/investigations/new?result={r.pk}" if may_open else "")
                ),
                "status": Cell(inv.get_status_display(), tone=INVESTIGATION_TONES[inv.status]) if inv else "",
                "root_cause": inv.root_cause if inv else "",
                "actions": _capa_text(inv) if inv else "",
                "closure": (
                    Cell(inv.closed_by.display_name(), sub=text_of(inv.closed_at)) if inv and inv.closed_by_id else ""
                ),
                "outcome": inv.outcome if inv else "",
            })
        return rows

    def summary(self, results, request):
        listed = list(results.order_by().values_list(
            "sample_id", "test_definition_id", "entered_at", "sample__batch_id",
        ))
        latest = {}
        for sample_id, test_id, entered_at, _ in listed:
            latest[(sample_id, test_id)] = max(entered_at, latest.get((sample_id, test_id), entered_at))
        found = investigations_by_test(set(latest))
        states = [covering_investigation(found, s, t, at) for (s, t), at in latest.items()]
        return [
            {"label": "Failed results", "value": len(listed)},
            {"label": "Samples", "value": len({row[0] for row in listed})},
            {"label": "Batches", "value": len({row[3] for row in listed if row[3]})},
            {"label": "No investigation", "value": sum(1 for i in states if i is None),
             "alert": any(i is None for i in states)},
            {"label": "Being investigated", "value": sum(1 for i in states if i and i.status != "CLOSED")},
            {"label": "Closed", "value": sum(1 for i in states if i and i.status == "CLOSED")},
        ]


def _followed_by(retests: list) -> Cell | str:
    if not retests:
        return ""
    r = retests[0]  # newest first
    label = r.get_kind_display()
    if r.status != RetestStatus.USED:
        return Cell(label, sub=r.get_status_display())
    tone = OUTCOME_TONES.get(r.retest_result.outcome, "")
    return Cell(f"{label}: {with_unit(r.retest_result)}", tone=tone, sub=r.retest_result.get_outcome_display())


def _by_investigation(qs, state: str):
    covered = Investigation.objects.filter(
        Q(closed_at__isnull=True) | Q(closed_at__gte=OuterRef("entered_at")),
        kind=InvestigationKind.OOS, sample=OuterRef("sample"), test_definition=OuterRef("test_definition"),
    )
    if state == "NONE":
        return qs.filter(~Exists(covered))
    return qs.filter(Exists(covered.filter(status=state)))


COMPARABLE = "Results are compared only where the test, method, unit and limits are all the same."


def comparable_key(result) -> tuple:
    t = result.test_definition
    return (t.name, t.method, t.unit, t.limit_type, t.min_value, t.max_value)


def trend_signal(values: list) -> tuple[str, str]:
    """
    A prompt to look, in plain words: the latest value beyond everything before
    it, or a run in one direction. Not an out-of-trend decision. That needs a
    statistical rule from an approved procedure, which the lab has yet to set.
    """
    if len(values) < 5:
        return "", ""
    latest, earlier = values[-1], values[:-1]
    if latest > max(earlier) or latest < min(earlier):
        return "Latest is outside the earlier range", "warn"
    run = 1
    direction = 0
    for before, after in zip(reversed(values[:-1]), reversed(values[1:])):
        step = (after > before) - (after < before)
        if step == 0 or (direction and step != direction):
            break
        direction = step
        run += 1
    if run >= 4:
        return f"{'Rising' if direction > 0 else 'Falling'} over {run} results", "info"
    return "", ""


@register
class OutOfTrend(Report):
    key = "oot"
    title = "OOT Trends"
    category = "tests"
    description = "Numeric results over time, per product and test, with anything unusual against their own history."
    note = (
        f"Basic trend reporting. {COMPARABLE} A signal is a prompt to look, not a finding: there is no "
        "statistical out-of-trend rule until the lab has an approved procedure and enough data. "
        "A result replaced by a retest is not plotted: every failure is on the OOS report."
    )
    columns = [
        Column("product", "Product", "product", width=1.5),
        Column("test", "Test", "test", width=1.2),
        Column("method", "Method", "method"),
        Column("results", "Results", "results", numeric=True, width=0.6),
        Column("mean", "Mean", "mean", numeric=True, width=0.7),
        Column("sd", "SD", "sd", numeric=True, width=0.6),
        Column("low", "Lowest", numeric=True, width=0.7),
        Column("high", "Highest", numeric=True, width=0.7),
        Column("latest", "Latest", numeric=True, width=0.7),
        Column("latest_at", "Latest date", "latest_at", width=1.1),
        Column("limit", "Limit", width=1),
        Column("signal", "Signal", "signal", width=1.3),
    ]
    dates = {"tested": Dates("Test date", "entered_at")}
    default_period = "quarter"
    default_sort = "product"
    filters = [
        Filter("product", "Product", lambda rows, v: [r for r in rows if str(r["product_id"]) == v],
               options=product_options),
        Filter("section", "Laboratory section", lambda rows, v: [r for r in rows if str(r["section_id"]) == v],
               options=section_options),
        Filter("signal_only", "Only with a signal", lambda rows, v: [r for r in rows if r["signal"]], kind="toggle"),
    ]

    def records(self, request):
        window = window_of(self, request)
        visible = results_visible_to(request.user).filter(is_superseded=False, value_numeric__isnull=False)
        if request.query_params.get("product", "").isdigit():
            visible = visible.filter(sample__product_id=request.query_params["product"])
        results = window.apply(
            visible, "entered_at"
        ).order_by("entered_at", "id")
        groups = defaultdict(list)
        for r in results:
            groups[(r.sample.product_id, *comparable_key(r))].append(r)
        may_open = has_perm(request.user, "investigation.manage")
        return [self._row(found, may_open) for found in groups.values()]

    def _row(self, results: list, may_open: bool) -> dict:
        first, last = results[0], results[-1]
        values = [float(result_value(r)) for r in results]
        signal, tone = trend_signal(values)
        t = first.test_definition
        return {
            "product_id": first.sample.product_id,
            "section_id": first.sample.section_id,
            "product": Cell(first.sample.product.name, to=f"/reports/product/{first.sample.product_id}"),
            "test": t.name,
            "method": t.method,
            "results": len(values),
            "mean": measure(mean(values), t.decimals + 1),
            "sd": measure(stdev(values), t.decimals + 1) if len(values) > 1 else None,
            "low": measure(min(values), t.decimals),
            "high": measure(max(values), t.decimals),
            "latest": Cell(with_unit(last)),
            "latest_at": last.entered_at,
            "limit": t.limit_text,
            "signal": (
                Cell(signal, tone=tone, to=f"/investigations/new?kind=OOT&result={last.pk}" if may_open else "")
                if signal else ""
            ),
        }


@register
class Retests(Report):
    key = "retests"
    title = "Retest History"
    category = "tests"
    description = "Each repeat, retest and resample: why, who authorized it, what it found and how it ended."
    note = (
        "Repeats, retests and resamples are kept apart, as the analyst requested them. "
        "A passing later result does not by itself settle the original failure."
    )
    columns = [
        Column("sample", "Sample ID", "sample__sample_no", width=1.1),
        Column("test", "Test", "test_definition__name"),
        Column("kind", "Type", "kind", width=0.7),
        Column("original", "Original result", width=0.8),
        Column("reason", "Reason", width=1.5, wrap=True),
        Column("requested", "Requested", "requested_at", width=1.2),
        Column("authorization", "Authorization", "status", width=1.2),
        Column("subsequent", "Subsequent result", width=1),
        Column("analyst", "Analyst", width=0.9),
        Column("reviewer", "Reviewer", width=0.9),
        Column("outcome", "Final documented outcome", width=1.4, wrap=True),
    ]
    dates = {"requested": Dates("Requested date", "requested_at")}
    default_sort = "-requested"
    filters = [
        Filter("kind", "Type", lambda qs, v: qs.filter(kind=v), options=[(k.value, k.label) for k in RetestKind]),
        Filter("status", "Authorization", lambda qs, v: qs.filter(status=v),
               options=[(s.value, s.label) for s in RetestStatus]),
        Filter("product", "Product", lambda qs, v: qs.filter(sample__product_id=v), options=product_options),
        Filter("test", "Test", lambda qs, v: qs.filter(test_definition__name__icontains=v), kind="text"),
    ]

    def records(self, request):
        return RetestRequest.objects.filter(sample__in=samples_visible_to(request.user).values("pk")).select_related(
            "sample", "test_definition", "failed_result__test_definition", "failed_result__entered_by",
            "retest_result__test_definition", "retest_result__entered_by", "requested_by", "decided_by",
        )

    def rows(self, requests, request):
        found = investigations_by_test({(r.sample_id, r.test_definition_id) for r in requests})
        signatures = review_signatures({r.sample_id for r in requests})
        rows = []
        for r in requests:
            inv = next(iter(found.get((r.sample_id, r.test_definition_id), [])), None)
            first = next(iter(signatures.get(r.sample_id, [])), None)
            later = r.retest_result
            rows.append({
                "sample": _sample_cell(r.sample),
                "test": r.test_definition.name,
                "kind": r.get_kind_display(),
                "original": Cell(with_unit(r.failed_result), tone="fail"),
                "reason": r.reason,
                "requested": Cell(r.requested_at, sub=r.requested_by.display_name()),
                "authorization": Cell(
                    r.get_status_display(),
                    tone={"PENDING": "hot", "DECLINED": "fail", "AUTHORIZED": "info", "USED": "pass"}[r.status],
                    sub=f"{r.decided_by.display_name()}, {text_of(r.decided_at)}" if r.decided_by_id else "",
                ),
                "subsequent": (
                    Cell(with_unit(later), tone=OUTCOME_TONES.get(later.outcome, "")) if later else ""
                ),
                "analyst": later.entered_by.display_name() if later else r.failed_result.entered_by.display_name(),
                "reviewer": first.name_snapshot if first else "",
                "outcome": (
                    Cell(inv.outcome or inv.get_status_display(), to=f"/investigations/{inv.id}", sub=inv.reference)
                    if inv else "No investigation on record"
                ),
            })
        return rows

    def summary(self, requests, request):
        tiles = [{"label": k.label, "value": requests.filter(kind=k).count()} for k in RetestKind]
        waiting = requests.filter(Q(status=RetestStatus.PENDING) | Q(status=RetestStatus.AUTHORIZED)).count()
        return [*tiles, {"label": "Still open", "value": waiting}]

