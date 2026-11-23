"""
Quality and compliance: who did what, which documents were in force, and the
register of deviations and CAPA.

A report is not the audit trail. The Audit Trail report reads the protected
record (audit.AuditEvent), which nobody can edit or delete, and an export of it
is a copy of what the record said at that moment.
"""
from django.db.models import Count, Q
from django.utils import timezone

from accounts.admin_api import _needs_review
from audit.describe import describe, sample_reference
from audit.models import AuditEvent
from lims.models import SpecStatus, Specification, WorkflowVersion
from lims.workflow import samples_visible_to
from quality.models import CapaAction, Classification, InvestigationKind, InvestigationStatus
from quality.services import MANAGE, visible_investigations
from standards.models import TestTemplate
from .engine import Cell, Column, Dates, Filter, Report, register, text_of
from .records import INVESTIGATION_TONES, product_options

NOT_CHANGES = {"reason", "comment", "override", "sample", "changes", "fields"}


def change_text(details: dict) -> str:
    """Previous and new values where the record holds them, then what else it says."""
    details = details or {}
    if details.get("changes"):
        return "; ".join(f"{c['field']}: “{c['old']}” to “{c['new']}”" for c in details["changes"])
    if "previous" in details and "answer" in details:
        return f"“{details['previous']}” to “{details['answer']}”"
    return "; ".join(f"{k}: {v}" for k, v in details.items() if k not in NOT_CHANGES and v not in ("", None, []))


def action_options(request) -> list[tuple]:
    # Ordered here on purpose: the model's default order by time would defeat distinct().
    actions = AuditEvent.objects.order_by("action").values_list("action", flat=True).distinct()
    return [(a, a.replace("_", " ").capitalize()) for a in actions]


@register
class AuditTrail(Report):
    key = "audit-trail"
    title = "Audit Trail"
    category = "compliance"
    description = "Who did what, when and from where, including every refused attempt."
    note = (
        "This reads the protected record, which nobody can edit or delete. "
        "An export is a copy of it, not a replacement for it, and is itself recorded here."
    )
    columns = [
        Column("when", "Date and time", "at", width=1.1),
        Column("who", "User", "actor_username", width=1),
        Column("what", "What happened", width=2.4, wrap=True),
        Column("record", "Related record", "entity_id", width=1),
        Column("change", "Previous and new values", width=1.8, wrap=True),
        Column("reason", "Reason", width=1.3, wrap=True),
        Column("address", "From", width=0.7),
    ]
    dates = {"at": Dates("Date", "at")}
    default_period = "week"
    default_sort = "-when"
    filters = [
        Filter("action", "Action", lambda qs, v: qs.filter(action=v), options=action_options),
        Filter("actor", "User", lambda qs, v: qs.filter(actor_username__icontains=v), kind="text"),
        Filter("entity_id", "Record", lambda qs, v: qs.filter(entity_id__icontains=v), kind="text"),
        Filter("notable", "Only refusals and corrections", lambda qs, v: qs.filter(_needs_review()), kind="toggle"),
        Filter("override", "Only administrator overrides", lambda qs, v: qs.filter(details__has_key="override"),
               kind="toggle"),
    ]

    def records(self, request):
        return AuditEvent.objects.select_related("actor")

    def rows(self, events, request):
        rows = []
        for e in events:
            told, sample_no = describe(e), sample_reference(e)
            details = e.details or {}
            rows.append({
                "when": e.at,
                "who": Cell(e.actor.display_name() if e.actor_id else "System", sub=e.actor_username),
                "what": Cell(told["sentence"], sub=e.action),
                "record": Cell(sample_no, to=f"/reports/sample-register?q={sample_no}") if sample_no else e.entity_id,
                "change": change_text(details),
                "reason": details.get("reason") or details.get("comment") or "",
                "address": e.ip_address,
            })
        return rows


def _review_state(review, today) -> Cell | str:
    if review is None:
        return ""
    days = (review - today).days
    if days < 0:
        return Cell(review, tone="fail", sub=f"Overdue by {-days}d")
    if days <= 90:
        return Cell(review, tone="warn", sub=f"Due in {days}d")
    return review


@register
class DocumentControl(Report):
    key = "document-control"
    title = "Document Control"
    category = "compliance"
    description = "Specifications and workflows: what is in force, what is superseded, what used each."
    note = (
        "These are the versioned documents this system holds. Test methods appear as text inside a specification, "
        "and SOPs are not held here. A specification in Draft is awaiting approval."
    )
    columns = [
        Column("document", "Document", "document", width=1.8),
        Column("type", "Type", "type", width=0.9),
        Column("version", "Version", "version_no", numeric=True, width=0.5),
        Column("status", "Status", "status_rank", width=1),
        Column("effective", "Effective", "effective", width=0.9),
        Column("approved", "Approved by", width=1.1),
        Column("review", "Review date", "review", width=1),
        Column("linked", "Samples using it", "samples", numeric=True, width=0.7),
    ]
    default_sort = "document"
    filters = [
        Filter("type", "Type", lambda rows, v: [r for r in rows if r["type"] == v],
               options=[(t, t) for t in ("Specification", "Review workflow", "Test template")]),
        Filter("state", "Status", lambda rows, v: [r for r in rows if r["state"] == v], options=[
            ("CURRENT", "Current approved"), ("AWAITING", "Awaiting approval"), ("SUPERSEDED", "Obsolete or superseded"),
        ]),
        Filter("reviewing", "Only approaching review", lambda rows, v: [r for r in rows if r["reviewing"]],
               kind="toggle"),
    ]

    def records(self, request):
        today = timezone.localdate()
        rows = []
        _samples_seen = Count("samples", filter=Q(samples__in=samples_visible_to(request.user).order_by().values("pk")))
        specs = Specification.objects.select_related("product", "approved_by").annotate(sample_count=_samples_seen)
        for s in specs:
            state, label, tone = {
                SpecStatus.EFFECTIVE: ("CURRENT", "Current approved", "pass"),
                SpecStatus.DRAFT: ("AWAITING", "Awaiting approval", "hot"),
                SpecStatus.SUPERSEDED: ("SUPERSEDED", "Superseded", "muted"),
            }[s.status]
            rows.append({
                "state": state,
                "status_rank": label,
                "reviewing": s.review_date is not None and (s.review_date - today).days <= 90,
                "document": Cell(f"{s.product.code} {s.stage_name + ' tests' if s.stage_key else 'specification'}",
                                 sub=s.product.name),
                "type": "QC stage tests" if s.stage_key else "Specification",
                "version_no": s.version,
                "version": f"v{s.version}",
                "status": Cell(label, tone=tone),
                "effective": s.effective_date,
                "approved": Cell(s.approved_by.display_name(), sub=text_of(s.approved_at)) if s.approved_by_id else "",
                "review": _review_state(s.review_date, today),
                "samples": s.sample_count,
                "linked": Cell(s.sample_count, to=f"/reports/test-results?spec={s.pk}"),
            })
        versions = WorkflowVersion.objects.select_related("workflow").annotate(sample_count=_samples_seen)
        newest = {}
        for v in versions:
            newest[v.workflow_id] = max(newest.get(v.workflow_id, 0), v.version)
        for v in versions:
            current = v.version == newest[v.workflow_id]
            rows.append({
                "state": "CURRENT" if current else "SUPERSEDED",
                "status_rank": "Current approved" if current else "Superseded",
                "reviewing": False,
                "document": v.workflow.name,
                "type": "Review workflow",
                "version_no": v.version,
                "version": f"v{v.version}",
                "status": Cell("Current" if current else "Superseded", tone="pass" if current else "muted"),
                "effective": timezone.localtime(v.created_at).date(),
                "review": None,
                "samples": v.sample_count,
                "linked": v.sample_count,
            })
        templates = list(TestTemplate.objects.all())
        latest = {}
        for t in templates:
            latest[t.code] = max(latest.get(t.code, 0), t.version)
        for t in templates:
            current = t.version == latest[t.code] and not t.is_retired
            label = "Current" if current else "Retired" if t.is_retired else "Superseded"
            rows.append({
                "state": "CURRENT" if current else "SUPERSEDED",
                "status_rank": label,
                "reviewing": False,
                "document": Cell(t.code, sub=t.name),
                "type": "Test template",
                "version_no": t.version,
                "version": f"v{t.version}",
                "status": Cell(label, tone="pass" if current else "muted"),
                "effective": timezone.localtime(t.created_at).date(),
                "review": None,
                "samples": None,
                "linked": None,
            })
        return rows


@register
class Deviations(Report):
    key = "deviations"
    title = "Deviations & CAPA"
    category = "compliance"
    description = "The register of investigations and deviations, with their corrective and preventive actions."
    note = "Open a record to work on it. Closure needs the password signature of someone independent of the work."
    action = ("Record a deviation", "/investigations/new", MANAGE)
    columns = [
        Column("reference", "Deviation ID", "reference", width=1.05),
        Column("kind", "Kind", "kind", width=1),
        Column("classification", "Classification", "classification", width=0.75),
        Column("related", "Related sample, test or batch", width=1.3, wrap=True),
        Column("description", "Description", width=1.7, wrap=True),
        Column("status", "Status", "status", width=1),
        Column("capa", "CAPA", width=1.3, wrap=True),
        Column("responsible", "Responsible", "responsible__first_name", width=0.95),
        Column("opened", "Opened", "opened_at", width=0.95),
        Column("due", "Due", "due_date", width=0.85),
        Column("closure", "Closure approval", "closed_at", width=1.1),
    ]
    dates = {"opened": Dates("Opened date", "opened_at"), "closed": Dates("Closed date", "closed_at")}
    default_sort = "-opened"
    filters = [
        Filter("kind", "Kind", lambda qs, v: qs.filter(kind=v),
               options=[(k.value, k.label) for k in InvestigationKind]),
        Filter("status", "Status", lambda qs, v: qs.filter(status=v),
               options=[(s.value, s.label) for s in InvestigationStatus]),
        Filter("classification", "Classification", lambda qs, v: qs.filter(classification=v),
               options=[(c.value, c.label) for c in Classification]),
        Filter("product", "Product", lambda qs, v: qs.filter(product_id=v), options=product_options),
        Filter("batch", "Batch / Lot", lambda qs, v: qs.filter(batch_no__icontains=v), kind="text"),
        Filter("late", "Only overdue", lambda qs, v: _late(qs), kind="toggle"),
    ]

    def records(self, request):
        return visible_investigations(request.user).annotate(
            actions_total=Count("actions", distinct=True),
            actions_open=Count("actions", filter=Q(actions__completed_at__isnull=True), distinct=True),
            actions_unverified=Count(
                "actions", filter=Q(actions__completed_at__isnull=False, actions__verified_at__isnull=True), distinct=True,
            ),
        ).prefetch_related("actions")

    def rows(self, cases, request):
        today = timezone.localdate()
        rows = []
        for i in cases:
            related = " · ".join(filter(None, [
                i.sample.sample_no if i.sample_id else "",
                i.test_definition.name if i.test_definition_id else "",
                f"Batch {i.batch_no}" if i.batch_no else "",
            ]))
            late = i.status != InvestigationStatus.CLOSED and i.due_date < today
            rows.append({
                "reference": Cell(i.reference, to=f"/investigations/{i.pk}"),
                "kind": i.get_kind_display(),
                "classification": i.get_classification_display(),
                "related": related,
                "description": i.description,
                "status": Cell(i.get_status_display(), tone=INVESTIGATION_TONES[i.status]),
                "capa": Cell(
                    "; ".join(a.description for a in i.actions.all()),
                    sub=", ".join(filter(None, [
                        f"{i.actions_open} of {i.actions_total} open" if i.actions_total else "",
                        f"{i.actions_unverified} not verified" if i.actions_unverified else "",
                    ])),
                ),
                "responsible": i.responsible.display_name(),
                "opened": i.opened_at,
                "due": Cell(i.due_date, tone="fail", sub="Overdue") if late else i.due_date,
                "closure": Cell(i.closed_by.display_name(), sub=text_of(i.closed_at)) if i.closed_by_id else "",
            })
        return rows

    def summary(self, cases, request):
        counts = dict(cases.order_by().values_list("status").annotate(n=Count("id", distinct=True)))
        late = _late(cases).order_by().values("pk").distinct().count()
        open_actions = CapaAction.objects.filter(
            investigation__in=cases.order_by().values("pk"), completed_at__isnull=True,
        ).count()
        return [
            {"label": "Under investigation", "value": counts.get(InvestigationStatus.OPEN, 0)},
            {"label": "Awaiting closure", "value": counts.get(InvestigationStatus.PENDING_CLOSURE, 0)},
            {"label": "Overdue", "value": late, "alert": late > 0},
            {"label": "Open actions", "value": open_actions},
        ]


def _late(qs):
    return qs.exclude(status=InvestigationStatus.CLOSED).filter(due_date__lt=timezone.localdate())
