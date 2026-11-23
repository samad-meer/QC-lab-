"""
Workflow and performance: what is waiting, what is late, and where the time
goes. These help a supervisor plan the lab's work. Test complexity and
investigation work vary too much for them to rank anyone, so nothing here sorts
people by volume unless someone asks it to.
"""
from collections import defaultdict

from django.db.models import Count, Max
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from certificates.models import ANALYSED, Certificate
from execution.models import (
    TESTING,
    Assignment,
    AssignmentStatus,
    ChecklistItem,
    ReceiptCompletion,
    SampleHold,
)
from lims.models import FINISHED, SampleStatus, TestResult, WorkflowEvent, WorkflowStage
from lims.workflow import samples_visible_to
from quality.models import CapaAction, InvestigationStatus
from quality.services import visible_investigations
from .engine import Cell, Column, Dates, Filter, Report, register, window_of
from .records import (
    analyst_options,
    batch_text,
    days_between,
    mean,
    median,
    overdue,
    product_options,
    result_progress,
    section_options,
    tests_required,
    visible_samples,
)
from .samples import stage_of

QUEUES = {
    "RECEIPT": "Awaiting receipt checks",
    "ASSIGNMENT": "Awaiting assignment",
    "TESTING": "Tests awaiting execution",
    "RETURNED": "Returned for correction",
    "REVIEW": "Work awaiting review",
    "APPROVAL": "Work awaiting approval",
}
QUEUE_TONES = {"RETURNED": "fail", "ASSIGNMENT": "warn", "REVIEW": "hot", "APPROVAL": "hot"}

RECEIPT_STEP = "Receipt checks"
TESTING_STEP = "Testing"


def _testing_holder(sample, rows: list):
    """Who holds testing, and who it waits on if nobody does — as rules.holder reads it."""
    if not rows:
        return sample.assigned_analyst, None  # registered before assignments were recorded
    accepted = [a for a in rows if a.status == AssignmentStatus.ACCEPTED]
    holder = accepted[-1].to_user if accepted else None
    waiting = next((a for a in rows if a.status == AssignmentStatus.PENDING), None)
    return holder, waiting


def waiting_work(user) -> list[dict]:
    """One row per sample in the lab: which queue it is in, and who it waits on."""
    samples = list(visible_samples(user).exclude(status__in=FINISHED))
    ids = [s.pk for s in samples]
    now, today = timezone.now(), timezone.localdate()

    moved = dict(WorkflowEvent.objects.filter(sample_id__in=ids).order_by().values_list("sample_id").annotate(Max("at")))
    holds = {h.sample_id: h for h in SampleHold.objects.filter(sample_id__in=ids, released_at__isnull=True)}
    assignments = defaultdict(list)
    for a in Assignment.objects.filter(sample_id__in=ids, step=TESTING).select_related("to_user") \
            .order_by("responded_at", "created_at", "id"):
        assignments[a.sample_id].append(a)
    with_checks = set(ChecklistItem.objects.filter(
        version_id__in={s.workflow_version_id for s in samples}, stage__isnull=True, for_receipt=True,
    ).values_list("version_id", flat=True))
    receipted = set(ReceiptCompletion.objects.filter(sample_id__in=ids).values_list("sample_id", flat=True))
    latest_cert = {}
    for cert in Certificate.objects.filter(sample_id__in=ids).order_by("version"):
        latest_cert[cert.sample_id] = cert
    progress = result_progress(ids)
    required = tests_required(s.specification_id for s in samples)

    rows = []
    for s in samples:
        since = moved.get(s.pk) or s.received_at
        testing = s.status in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING)
        cert = latest_cert.get(s.pk)
        done, needed = progress.get(s.pk, {}).get("entered", 0), required.get(s.specification_id, 0)
        step, detail = TESTING_STEP, f"{done} of {needed} tests entered"
        if s.status == SampleStatus.IN_REVIEW:
            key = "REVIEW" if s.stages_after else "APPROVAL"
            step, detail = s.review_stage.name, ""
            who = s.review_stage.holder
        elif s.status == SampleStatus.RECEIVED and s.workflow_version_id in with_checks and s.pk not in receipted:
            key, step, detail, who = "RECEIPT", RECEIPT_STEP, "", "The front desk"
        else:
            holder, handing = _testing_holder(s, assignments.get(s.pk, []))
            if holder is None:
                key = "ASSIGNMENT"
                who = handing.to_user.display_name() if handing else "Whoever assigns work"
                detail = "Waiting for them to accept" if handing else "Declined — needs reassigning"
            elif testing and cert is not None and cert.status == "SUPERSEDED" and cert.returned_at:
                key, who, since = "RETURNED", holder.display_name(), cert.returned_at
                detail = cert.superseded_reason
            else:
                key, who = "TESTING", holder.display_name()
        hold = holds.get(s.pk)
        rows.append({
            "queue_key": key,
            "product_id": s.product_id,
            "section_id": s.section_id,
            "analyst_id": s.assigned_analyst_id,
            "analyst_name": s.assigned_analyst.display_name(),
            "step_name": step,
            "task": Cell(s.sample_no, to=f"/samples/{s.pk}"),
            "type": "Sample",
            "product": Cell(s.product.name, sub=batch_text(s)),
            "queue": Cell(QUEUES[key], tone=QUEUE_TONES.get(key, "info")),
            "stage": Cell(stage_of(s), sub=detail),
            "who": who,
            "since": since,
            "days": days_between(since, now),
            "due": s.due_date,
            "overdue_days": (today - s.due_date).days,
            "hold": Cell(hold.reason, tone="warn") if hold else "",
        })
    return rows


def _quality_product(inv) -> Cell | str:
    if not inv.product_id:
        return ""
    return Cell(inv.product.name, sub=f"Batch {inv.batch_no}" if inv.batch_no else "")


def _overdue_quality(user) -> list[dict]:
    """Investigations and actions past their date: tasks, not samples."""
    today = timezone.localdate()
    live = visible_investigations(user).exclude(status=InvestigationStatus.CLOSED)
    rows = [
        {
            "queue_key": "", "product_id": i.product_id, "section_id": None, "analyst_id": None,
            "task": Cell(i.reference, to=f"/investigations/{i.pk}"),
            "type": "Investigation",
            "product": _quality_product(i),
            "stage": i.get_status_display(),
            "who": i.responsible.display_name(),
            "due": i.due_date,
            "overdue_days": (today - i.due_date).days,
            "hold": "",
        }
        for i in live.filter(due_date__lt=today)
    ]
    actions = CapaAction.objects.filter(
        investigation__in=live.order_by().values("pk"), completed_at__isnull=True, due_date__lt=today,
    ).select_related("investigation__product", "owner")
    for a in actions:
        inv = a.investigation
        rows.append({
            "queue_key": "", "product_id": inv.product_id, "section_id": None, "analyst_id": None,
            "task": Cell(inv.reference, to=f"/investigations/{inv.pk}", sub=a.description[:80]),
            "type": f"{a.get_kind_display()} action",
            "product": _quality_product(inv),
            "stage": inv.get_status_display(),
            "who": a.owner.display_name(),
            "due": a.due_date,
            "overdue_days": (today - a.due_date).days,
            "hold": "",
        })
    return rows


def _matching(key: str):
    return lambda rows, value: [r for r in rows if str(r[key]) == value]


@register
class PendingWork(Report):
    key = "pending-work"
    title = "Pending Work"
    category = "workflow"
    description = "Everything in the lab that is waiting, the queue it is in, and who it waits on."
    note = "A to-do list, so it has no date filter: a filter here could hide work that is waiting."
    columns = [
        Column("task", "Sample ID", "task", width=1.1),
        Column("product", "Product", "product", width=1.5),
        Column("queue", "Queue", "queue", width=1.3),
        Column("stage", "Current stage", width=1.3, wrap=True),
        Column("who", "Waiting on", "who", width=1.1),
        Column("since", "Waiting since", "since", width=1.2),
        Column("days", "Days waiting", "days", numeric=True, width=0.7),
        Column("due", "Due", "due", width=0.9),
        Column("hold", "Hold reason", width=1.2, wrap=True),
    ]
    default_sort = "-days"
    filters = [
        Filter("queue", "Queue", _matching("queue_key"), options=list(QUEUES.items())),
        Filter("analyst", "Analyst", _matching("analyst_id"), options=analyst_options),
        Filter("section", "Laboratory section", _matching("section_id"), options=section_options),
        Filter("product", "Product", _matching("product_id"), options=product_options),
    ]

    def records(self, request):
        return waiting_work(request.user)

    def summary(self, rows, request):
        counts = defaultdict(int)
        for row in rows:
            counts[row["queue_key"]] += 1
        return [{"label": label, "value": counts[key]} for key, label in QUEUES.items()]


@register
class OverdueWork(Report):
    key = "overdue"
    title = "Overdue Work"
    category = "workflow"
    description = "Samples, investigations and actions past their due date."
    columns = [
        Column("task", "Sample or task ID", "task", width=1.2),
        Column("type", "Type", "type", width=0.9),
        Column("product", "Product", "product", width=1.5),
        Column("who", "Assigned analyst or reviewer", "who", width=1.2),
        Column("due", "Due date", "due", width=0.9),
        Column("overdue_days", "Days overdue", "overdue_days", numeric=True, width=0.7),
        Column("stage", "Current stage", width=1.3, wrap=True),
        Column("hold", "Hold reason", width=1.2, wrap=True),
    ]
    default_sort = "-overdue_days"
    filters = [
        Filter("analyst", "Analyst", _matching("analyst_id"), options=analyst_options),
        Filter("product", "Product", _matching("product_id"), options=product_options),
    ]

    def records(self, request):
        late = [r for r in waiting_work(request.user) if r["overdue_days"] > 0]
        return late + _overdue_quality(request.user)


@register
class AnalystWorkload(Report):
    key = "analyst-workload"
    title = "Analyst Workload"
    category = "workflow"
    description = "What each analyst holds now, and what they finished in the period."
    note = (
        "For planning the lab's work, not for ranking people: test complexity and investigation work vary too much "
        "for volume to measure anyone. Listed by name for that reason."
    )
    columns = [
        Column("analyst", "Analyst", "analyst", width=1.4),
        Column("active", "Active assignments", "active", numeric=True, width=0.8),
        Column("pending", "Tests pending", "pending", numeric=True, width=0.8),
        Column("completed", "Tests completed", "completed", numeric=True, width=0.8),
        Column("overdue", "Overdue tasks", "overdue", numeric=True, width=0.8),
        Column("turnaround", "Average turnaround (days)", "turnaround", numeric=True, width=0.9),
        Column("investigations", "Open investigations", "investigations", numeric=True, width=0.8),
    ]
    dates = {"period": Dates("Completed in", "")}
    default_period = "month"
    default_sort = "analyst"
    filters = [
        Filter("section", "Laboratory section", lambda rows, v: [r for r in rows if v in r["section_ids"]],
               options=section_options),
    ]

    def records(self, request):
        window = window_of(self, request)
        user = request.user
        samples = samples_visible_to(user).order_by()
        live = samples.exclude(status__in=FINISHED)
        active = dict(live.values_list("assigned_analyst").annotate(n=Count("id")))
        late = dict(overdue(samples).values_list("assigned_analyst").annotate(n=Count("id")))

        live_rows = list(live.values_list("pk", "assigned_analyst", "specification"))
        required = tests_required(spec for _, _, spec in live_rows)
        progress = result_progress([pk for pk, _, _ in live_rows])
        pending = defaultdict(int)
        for pk, analyst, spec in live_rows:
            pending[analyst] += required.get(spec, 0) - progress.get(pk, {}).get("entered", 0)

        done = dict(
            window.apply(TestResult.objects.filter(sample__in=samples.values("pk"), is_superseded=False), "entered_at")
            .order_by().values_list("entered_by").annotate(n=Count("id"))
        )
        turnarounds = defaultdict(list)
        for analyst, received, released in window.apply(
            visible_samples(user).filter(released_at__isnull=False), "released_at"
        ).values_list("assigned_analyst", "received_at", "released_at"):
            turnarounds[analyst].append(days_between(received, released))

        cases = visible_investigations(user).exclude(status=InvestigationStatus.CLOSED).order_by()
        investigating = dict(cases.values_list("responsible").annotate(n=Count("id")))

        people = set(active) | set(done) | set(turnarounds)
        rows = []
        for person in User.objects.filter(pk__in=people).prefetch_related("sections"):
            average = mean(turnarounds[person.pk])
            rows.append({
                "section_ids": {str(s.pk) for s in person.sections.all()},
                "analyst": person.display_name(),
                "active": active.get(person.pk, 0),
                "pending": pending[person.pk],
                "completed": done.get(person.pk, 0),
                "overdue": Cell(late[person.pk], tone="warn") if late.get(person.pk) else 0,
                "turnaround": round(average, 1) if average is not None else None,
                "investigations": investigating.get(person.pk, 0),
            })
        return rows


def _durations(certs: list, stage_names: dict, receipts: dict) -> tuple[dict, dict]:
    """How long each step took, and how often work came back from it, across these attempts."""
    times, returned = defaultdict(list), defaultdict(int)
    previous = {}
    for cert in certs:
        sample = cert.sample
        signatures = sorted(cert.signatures.all(), key=lambda s: s.signed_at)
        started = previous.get(sample.pk) or receipts.get(sample.pk) or sample.received_at
        moment = started
        for signature in signatures:
            step = (
                TESTING_STEP if signature.meaning == ANALYSED
                else stage_names.get((sample.workflow_version_id, signature.meaning), (signature.meaning, 0))[0]
            )
            times[step].append(days_between(moment, signature.signed_at))
            moment = signature.signed_at
        if cert.returned_at:
            step = stage_names.get((sample.workflow_version_id, cert.returned_stage), (cert.returned_stage, 0))[0]
            times[step].append(days_between(moment, cert.returned_at))
            returned[step] += 1
            previous[sample.pk] = cert.returned_at
    return times, returned


@register
class WorkflowBottlenecks(Report):
    key = "bottlenecks"
    title = "Workflow Bottlenecks"
    category = "workflow"
    description = "How long work spends at each step, where it piles up, and what sends it back."
    note = (
        "Steps of the same name are read together across workflows. Blocked signatures count the attempts stopped "
        "by a missing checklist answer, document, result or acceptance."
    )
    columns = [
        Column("stage", "Workflow step", "order", width=1.4),
        Column("completed", "Times completed", "completed", numeric=True, width=0.8),
        Column("average", "Average days", "average", numeric=True, width=0.7),
        Column("median", "Median days", "median", numeric=True, width=0.7),
        Column("longest", "Longest days", "longest", numeric=True, width=0.7),
        Column("backlog", "Waiting now", "backlog", numeric=True, width=0.7),
        Column("returned", "Sent back from here", "returned", numeric=True, width=0.8),
        Column("blocked", "Blocked signatures", "blocked", numeric=True, width=0.8),
    ]
    dates = {"period": Dates("Started in", "")}
    default_period = "quarter"
    default_sort = "stage"

    def records(self, request):
        window = window_of(self, request)
        user = request.user
        visible = samples_visible_to(user).order_by()
        certs = list(
            window.apply(Certificate.objects.filter(sample__in=visible.values("pk")), "created_at")
            .select_related("sample").prefetch_related("signatures").order_by("sample_id", "version")
        )
        versions = {c.sample.workflow_version_id for c in certs}
        stage_names = {
            (s.version_id, s.code): (s.name, s.order) for s in WorkflowStage.objects.filter(version_id__in=versions)
        }
        receipts = dict(
            ReceiptCompletion.objects.filter(sample__in=[c.sample_id for c in certs])
            .values_list("sample_id", "completed_at")
        )
        times, returned = _durations(certs, stage_names, receipts)
        for received, completed in window.apply(
            ReceiptCompletion.objects.filter(sample__in=visible.values("pk")), "completed_at"
        ).values_list("sample__received_at", "completed_at"):
            times[RECEIPT_STEP].append(days_between(received, completed))

        backlog = defaultdict(int)
        order = {RECEIPT_STEP: -1, TESTING_STEP: 0}
        for name, position in stage_names.values():
            # A shorter workflow has the same step earlier: Approved is last wherever it comes.
            order[name] = max(order.get(name, 0), position)
        for row in waiting_work(user):
            backlog[row["step_name"]] += 1
            order.setdefault(row["step_name"], 99)

        blocked = defaultdict(int)
        for step in window.apply(
            AuditEvent.objects.filter(
                action__in=["SIGN_REFUSED_BLOCKED", "RECEIPT_REFUSED_BLOCKED"],
                entity="sample", entity_id__in=visible.values("sample_no"),
            ), "at",
        ).values_list("details__step", flat=True):
            blocked[TESTING_STEP if step == "Tested" else step] += 1

        rows = []
        for name in sorted(set(times) | set(backlog) | set(blocked), key=lambda n: order.get(n, 99)):
            spent = times.get(name, [])
            rows.append({
                "order": order.get(name, 99),
                "stage": name,
                "completed": len(spent),
                "average": round(mean(spent), 1) if spent else None,
                "median": round(median(spent), 1) if spent else None,
                "longest": max(spent) if spent else None,
                "backlog": backlog.get(name, 0),
                "returned": Cell(returned[name], tone="warn") if returned.get(name) else 0,
                "blocked": Cell(blocked[name], tone="warn") if blocked.get(name) else 0,
            })
        return rows
