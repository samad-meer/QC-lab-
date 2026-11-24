"""
Who holds what, and what each person has done: three reports from one list of open work.

Tasks by Person counts what each person holds. Team Tasks lists every item: what it is, where,
who gave it, when and when it falls due. Person Activity is one person's week or month, for
that person to print, or for QA and the administrator to read about anyone.

The open work is worked out on the server from the same places My tasks reads, so a report
can never disagree with a person's own task list. A review waits on a role rather than a
person, so it is counted under the role until someone takes it.

Nothing here ranks people. How much a person holds or does depends on what the work was, and
the reports say so.
"""
from collections import Counter, defaultdict

from django.utils import timezone
from rest_framework.exceptions import ParseError, PermissionDenied

from accounts.authz import has_perm
from accounts.models import User
from audit.describe import TEMPLATES, describe, sample_reference
from audit.models import AuditEvent
from batches.api import batches_visible_to
from batches.models import BatchStageAssignment
from batches.stages import open_stage_work
from execution.models import TESTING, Assignment
from qclab.listing import Window
from quality.models import CapaAction, Investigation, InvestigationStatus
from quality.services import visible_investigations
from .engine import Cell, Column, Dates, Filter, Report, register, window_of
from .records import days_between, product_options
from .workflow import _quality_product, waiting_work

TYPES = [
    ("sample", "Sample testing"),
    ("review", "Sample review or approval"),
    ("batch", "Batch record stage"),
    ("investigation", "Investigation"),
    ("capa", "CAPA action"),
]
TYPE_NAMES = dict(TYPES)
# The same kinds as short headings, for the count columns.
COUNT_LABELS = {
    "sample": "Samples to test", "review": "Reviews", "batch": "Batch records", "investigation": "Investigations",
    "capa": "CAPA actions",
}
REVIEW_QUEUES = {"REVIEW", "APPROVAL"}


def people_options(request, inactive: bool = True) -> list[tuple]:
    """
    Everyone who can be given work: a person, never a role. Someone who has left is still
    listed, marked, because what they hold or did stays on the record and QA may need it.
    """
    people = User.objects.filter(role__isnull=False).order_by("first_name", "username")
    if not inactive:
        people = people.filter(is_active=True)
    return [(u.id, u.display_name() if u.is_active else f"{u.display_name()} (inactive)") for u in people]


def _status(late: int | None, hold) -> Cell:
    if hold:
        return Cell("On hold", tone="warn", sub=hold.value if isinstance(hold, Cell) else str(hold))
    if late:
        return Cell(f"Overdue {late} d", tone="fail")
    return Cell("Open", tone="info") if late is None else Cell("On time", tone="pass")


def _item(kind: str, **fields) -> dict:
    late = fields.pop("late", None)
    row = {
        "type_key": kind,
        "type": TYPE_NAMES[kind],
        "person_id": None,
        "product_id": None,
        "by": "",
        "due": None,
        "hold": "",
        **fields,
    }
    row["overdue"] = bool(late)
    row["late"] = late or 0
    row["status"] = _status(late, row["hold"])
    return row


def _samples(user) -> list[dict]:
    items = []
    for r in waiting_work(user):
        kind = "review" if r["queue_key"] in REVIEW_QUEUES else "sample"
        items.append(_item(
            kind,
            person_id=r["holder_id"], person=r["who"],
            by=r["given_by"] or ("The workflow" if kind == "review" else ""),
            task=r["task"], product=r["product"], product_id=r["product_id"],
            stage=Cell(r["stage"].value, sub=r["stage"].sub or r["queue"].value) if isinstance(r["stage"], Cell) else r["stage"],
            since=r["since"], days=r["days"], due=r["due"],
            late=max(r["overdue_days"], 0), hold=r["hold"],
        ))
    return items


def _batch_stages(user, now) -> list[dict]:
    items = []
    for w in open_stage_work(batches=batches_visible_to(user)):
        batch, given = w["batch"], w["assignment"]
        if w["state"] == "fill":
            what = f"Fill {w['missing']} value{'' if w['missing'] == 1 else 's'}, then sign “{w['column']}”"
        elif w["state"] == "sign":
            what = f"Sign “{w['column']}”"
        else:
            what = "Waiting for " + ", ".join(w["waiting_for"])
        items.append(_item(
            "batch",
            person_id=given.assignee_id, person=given.assignee.display_name(),
            by=given.assigned_by.display_name(),
            task=Cell(batch.internal_id, to=f"/batches/{batch.pk}"),
            product=Cell(batch.product.name, sub=f"Batch {batch.official_batch_no}"), product_id=batch.product_id,
            stage=Cell(w["stage"].name, sub=what),
            since=given.assigned_at, days=days_between(given.assigned_at, now),
        ))
    return items


def _quality(user, now) -> list[dict]:
    today = timezone.localdate()
    live = visible_investigations(user).exclude(status=InvestigationStatus.CLOSED)
    items = []
    for i in live:
        items.append(_item(
            "investigation",
            person_id=i.responsible_id, person=i.responsible.display_name(), by=i.opened_by.display_name(),
            task=Cell(i.reference, to=f"/investigations/{i.pk}"),
            product=_quality_product(i), product_id=i.product_id,
            stage=Cell(i.get_status_display(), sub=i.get_kind_display()),
            since=i.opened_at, days=days_between(i.opened_at, now), due=i.due_date,
            late=max((today - i.due_date).days, 0),
        ))
    actions = CapaAction.objects.filter(
        investigation__in=live.order_by().values("pk"), completed_at__isnull=True,
    ).select_related("investigation__product", "owner", "created_by")
    for a in actions:
        inv = a.investigation
        items.append(_item(
            "capa",
            person_id=a.owner_id, person=a.owner.display_name(), by=a.created_by.display_name(),
            task=Cell(inv.reference, to=f"/investigations/{inv.pk}", sub=a.description[:80]),
            product=_quality_product(inv), product_id=inv.product_id,
            stage=Cell(f"{a.get_kind_display()} action", sub=inv.get_status_display()),
            since=a.created_at, days=days_between(a.created_at, now), due=a.due_date,
            late=max((today - a.due_date).days, 0),
        ))
    return items


def open_work(user) -> list[dict]:
    """Everything waiting on someone that this person may see, one item to a row."""
    now = timezone.now()
    return _samples(user) + _batch_stages(user, now) + _quality(user, now)


def _in(window: Window, moment) -> bool:
    return (window.start is None or moment >= window.start) and (window.stop is None or moment < window.stop)


def _matching(key: str):
    return lambda rows, value: [r for r in rows if str(r[key]) == value]


def _holder_key(row: dict):
    """A person, or the role a review waits on."""
    return row["person_id"] if row["person_id"] is not None else ("role", row["person"])


@register
class TasksByPerson(Report):
    key = "tasks-by-person"
    title = "Tasks by Person"
    category = "workflow"
    description = "How many tasks each person holds now, of each kind, and how many of them are late."
    note = (
        "Today's picture, so it has no date filter: a filter here could hide work that is waiting. "
        "A review waits on a role until someone takes it, so it is counted under the role. "
        "This is for planning the lab's work, not for ranking people: one investigation and one sample are not the same amount of work."
    )
    columns = [
        Column("person", "Assigned to", "person", width=1.5),
        *[Column(k, label, k, numeric=True, width=0.8) for k, label in COUNT_LABELS.items()],
        Column("total", "All open", "total", numeric=True, width=0.7),
        Column("overdue", "Overdue", "overdue", numeric=True, width=0.7),
        Column("oldest", "Oldest (days)", "oldest", numeric=True, width=0.8),
    ]
    default_sort = "-total"
    filters = [
        Filter("person", "Person", _matching("person_id"), options=people_options),
        Filter("everyone", "Include people with no tasks", lambda rows, v: rows, kind="toggle"),
    ]

    def records(self, request):
        held = defaultdict(lambda: {"counts": Counter(), "late": 0, "oldest": 0.0})
        names, ids = {}, {}
        for item in open_work(request.user):
            key = _holder_key(item)
            names[key], ids[key] = item["person"], item["person_id"]
            g = held[key]
            g["counts"][item["type_key"]] += 1
            g["late"] += item["overdue"]
            g["oldest"] = max(g["oldest"], item["days"])
        if request.query_params.get("everyone"):
            for pk, name in people_options(request, inactive=False):
                held[pk]
                names.setdefault(pk, name)
                ids.setdefault(pk, pk)
        rows = []
        for key, g in held.items():
            person_id = ids.get(key)
            late = g["late"]
            rows.append({
                "person_id": person_id,
                "person": Cell(names[key], to=f"/reports/team-tasks?person={person_id}" if person_id else "",
                               sub="" if person_id else "A role: waiting for whoever takes it"),
                **{k: g["counts"][k] for k, _ in TYPES},
                "total": sum(g["counts"].values()),
                "overdue": Cell(late, tone="warn") if late else 0,
                "oldest": round(g["oldest"], 1) if g["counts"] else None,
            })
        return rows

    def summary(self, rows, request):
        people = [r for r in rows if r["person_id"] is not None and r["total"]]
        late = sum(r["overdue"].value if isinstance(r["overdue"], Cell) else r["overdue"] for r in rows)
        return [
            {"label": "People holding tasks", "value": len(people)},
            {"label": "Open tasks", "value": sum(r["total"] for r in rows)},
            {"label": "Overdue", "value": late, "alert": late > 0},
        ]


@register
class TeamTasks(Report):
    key = "team-tasks"
    title = "Team Tasks"
    category = "workflow"
    description = "Every open task: who holds it, what it is and where, who gave it to them, when, and when it falls due."
    note = (
        "Assigned on is when the task reached that person, so a week or a month shows what was handed out in it. "
        "A review waits on a role until someone takes it, so it names the role."
    )
    # The ones a supervisor reads first come first: who, what, how late, when it was given.
    columns = [
        Column("person", "Assigned to", "person", width=1.2),
        Column("task", "Task", "task", width=1.1),
        Column("type", "Kind", "type", width=1.0),
        Column("product", "Product and batch", "product", width=1.4),
        Column("status", "Status", "late", width=0.9),
        Column("due", "Due", "due", width=0.8),
        Column("since", "Assigned on", "since", width=1.1),
        Column("days", "Days open", "days", numeric=True, width=0.6),
        Column("by", "Assigned by", "by", width=1.0),
        Column("stage", "What it needs", width=1.6, wrap=True),
    ]
    dates = {"assigned": Dates("Assigned in", "")}
    default_period = "all"
    default_sort = "-days"
    filters = [
        Filter("person", "Person", _matching("person_id"), options=people_options),
        Filter("kind", "Kind of task", _matching("type_key"), options=TYPES),
        Filter("product", "Product", _matching("product_id"), options=product_options),
        Filter("overdue", "Only overdue", lambda rows, v: [r for r in rows if r["overdue"]], kind="toggle"),
    ]

    def records(self, request):
        window = window_of(self, request)
        return [r for r in open_work(request.user) if _in(window, r["since"])]

    def summary(self, rows, request):
        late = sum(1 for r in rows if r["overdue"])
        return [
            {"label": "Open tasks", "value": len(rows)},
            {"label": "People holding them", "value": len({r["person_id"] for r in rows if r["person_id"] is not None})},
            {"label": "Overdue", "value": late, "alert": late > 0},
            {"label": "Longest open (days)", "value": max((r["days"] for r in rows), default=0)},
        ]


# What the activity list shows: the work a person did, not their sign-ins, passwords or downloads.
LEFT_OUT = {
    "PASSWORD_CHANGED", "PASSWORD_RESET", "EMAIL_FAILED", "REPORT_EXPORTED", "DOCUMENT_EXPORTED", "LIST_EXPORTED",
    "CERT_COPY_OPENED", "QUALITY_RULES_CHANGED",
}
WORK_ACTIONS = sorted(
    action for action, (severity, _) in TEMPLATES.items()
    if severity in ("normal", "signature", "attention") and action not in LEFT_OUT and not action.startswith("ADMIN_SITE")
)
SIGNED = {
    "BATCH_STAGE_RECORDED", "BATCH_DISPOSITION", "SPEC_APPROVED", "METHOD_APPROVED", "CHANGE_APPROVED",
    "CAPA_VERIFIED", "INVESTIGATION_CLOSED", "SAMPLE_RELEASED",
}
KINDS = {
    "results": ("Results and retests", lambda a: a.startswith(("RESULT_", "RETEST_"))),
    "signatures": ("Signatures and approvals", lambda a: a.startswith("SIGNED_") or a in SIGNED or a == "BATCH_STAGE_SIGNED"),
    "returns": ("Sent back or rejected",
                lambda a: a in {"RETURNED_TO_ANALYST", "SENT_BACK_BY_CHECKER", "REJECTED_BY_APPROVER", "INVESTIGATION_RETURNED"}),
    "batch": ("Batch records", lambda a: a.startswith("BATCH_")),
    "quality": ("Investigations, CAPA and changes", lambda a: a.startswith(("INVESTIGATION_", "CAPA_", "CHANGE_"))),
    "handover": ("Registering, assigning and handing over",
                 lambda a: a in {"SAMPLE_REGISTERED", "ASSIGNED", "STEP_CLAIMED", "BATCH_STAGE_ASSIGNED", "BATCH_STAGE_UNASSIGNED"}
                 or a.startswith("HANDOVER_")),
}
KIND_ACTIONS = {key: [a for a in WORK_ACTIONS if test(a)] for key, (_, test) in KINDS.items()}


@register
class PersonActivity(Report):
    key = "person-activity"
    title = "Person Activity"
    category = "workflow"
    description = (
        "One person's work for a week, a month or any dates: what was given to them, what they did and signed, "
        "and what they still hold. Print it from the PDF button."
    )
    note = (
        "Everyone can open and print their own. Choosing someone else needs “See workload on the overview”. "
        "It counts actions, which say nothing about how hard the work was, so it is not a ranking."
    )
    columns = [
        Column("when", "Date and time", "at", width=1.1),
        Column("what", "What was done", width=3.0, wrap=True),
        Column("record", "Record", "entity_id", width=1.0),
        Column("reason", "Reason or note", width=1.6, wrap=True),
    ]
    dates = {"at": Dates("Date", "at")}
    default_period = "week"
    default_sort = "-when"
    sample_scope = False  # it is about the person's own work, whatever samples the reader may see
    print_summary = True  # a printed week carries its totals
    filters = [
        Filter("person", "Person", lambda rows, v: rows, blank="Me",
               options=lambda request: _people_for(request)),
        Filter("kind", "Kind of work", lambda qs, v: qs.filter(action__in=KIND_ACTIONS[v]),
               options=[(k, label) for k, (label, _) in KINDS.items()]),
    ]

    def _person(self, request) -> User:
        asked = (request.query_params.get("person") or "").strip()
        if not asked or asked == str(request.user.pk):
            return request.user
        if not has_perm(request.user, "report.performance"):
            raise PermissionDenied(
                "You can open your own activity. Another person's needs “See workload on the overview”."
            )
        person = User.objects.filter(pk=asked).select_related("role").first() if asked.isdigit() else None
        if person is None:
            raise ParseError("That person does not exist.")
        return person

    def subject(self, request) -> str:
        person = self._person(request)
        role = person.role.name if person.role_id else ""
        return f"{person.display_name()} ({role})" if role else person.display_name()

    def may_export(self, request) -> bool:
        """Anyone may print their own week. Printing someone else's takes the right to export reports."""
        return has_perm(request.user, "report.export") or self._person(request).pk == request.user.pk

    def records(self, request):
        person = self._person(request)
        return AuditEvent.objects.filter(actor=person, action__in=WORK_ACTIONS).select_related("actor")

    def rows(self, events, request):
        rows = []
        for e in events:
            told, sample_no = describe(e), sample_reference(e)
            details = e.details or {}
            rows.append({
                "when": e.at,
                "what": Cell(told["sentence"][:1].upper() + told["sentence"][1:]),
                "record": Cell(sample_no, to=f"/reports/sample-register?q={sample_no}") if sample_no else e.entity_id,
                "reason": details.get("reason") or details.get("comment") or "",
            })
        return rows

    def summary(self, events, request):
        person = self._person(request)
        window = window_of(self, request)
        held = [r for r in open_work(person) if r["person_id"] == person.pk]
        late = sum(1 for r in held if r["overdue"])
        count = lambda keys: events.filter(action__in=keys).count()  # noqa: E731
        return [
            {"label": "Things done", "value": events.count(), "sub": window.label},
            {"label": "Results entered", "value": count(["RESULT_ENTERED", "RETEST_ENTERED"]), "sub": window.label},
            {"label": "Signatures", "value": count(KIND_ACTIONS["signatures"]), "sub": window.label},
            {"label": "Given to them", "value": _given_to(person, window), "sub": window.label},
            {"label": "Holding now", "value": len(held), "sub": "today, whatever the dates"},
            {"label": "Overdue now", "value": late, "alert": late > 0, "sub": "today, whatever the dates"},
        ]


def _people_for(request) -> list[tuple]:
    if has_perm(request.user, "report.performance"):
        return people_options(request)
    return [(request.user.id, request.user.display_name())]


def _given_to(person: User, window: Window) -> int:
    """What reached them in the period: samples, batch stages, investigations and actions."""
    counts = [
        window.apply(Assignment.objects.filter(to_user=person, step=TESTING), "created_at").count(),
        window.apply(BatchStageAssignment.objects.filter(assignee=person), "assigned_at").count(),
        window.apply(Investigation.objects.filter(responsible=person), "opened_at").count(),
        window.apply(CapaAction.objects.filter(owner=person), "created_at").count(),
    ]
    return sum(counts)
