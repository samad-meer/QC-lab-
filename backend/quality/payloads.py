from accounts.authz import OVERRIDE, has_perm
from execution.models import RetestRequest
from execution.payloads import person
from lims.evaluation import reported_value
from lims.models import TestResult
from .models import InvestigationKind, InvestigationStatus
from .services import APPROVE, MANAGE, involved_in


def _action(a, inv, user) -> dict:
    return {
        "id": a.id,
        "kind": a.kind,
        "kind_label": a.get_kind_display(),
        "description": a.description,
        "owner": person(a.owner),
        "due_date": a.due_date,
        "created_at": a.created_at,
        "completed_by": person(a.completed_by),
        "completed_at": a.completed_at,
        "completion_note": a.completion_note,
        "verified_by": person(a.verified_by),
        "verified_at": a.verified_at,
        "verification_note": a.verification_note,
        "can_complete": a.completed_at is None and inv.status == InvestigationStatus.OPEN
        and (a.owner_id == user.id or has_perm(user, MANAGE)),
        "can_verify": a.completed_at is not None and a.verified_at is None and inv.status == InvestigationStatus.OPEN
        and (has_perm(user, MANAGE) or has_perm(user, APPROVE))
        and (user.id not in (a.owner_id, a.completed_by_id) or has_perm(user, OVERRIDE)),
    }


def _failure(inv) -> dict | None:
    """The result in question and everything since, so nobody closes this without seeing them."""
    if inv.result_id is None:
        return None
    results = TestResult.objects.filter(
        sample_id=inv.sample_id, test_definition_id=inv.test_definition_id
    ).select_related("test_definition", "entered_by").order_by("entered_at", "id")
    retests = {
        r.retest_result_id: r for r in RetestRequest.objects.filter(
            sample_id=inv.sample_id, test_definition_id=inv.test_definition_id, retest_result__isnull=False
        ).select_related("decided_by")
    }
    return {
        "limit": inv.result.test_definition.limit_text,
        "unit": inv.result.test_definition.unit,
        "results": [
            {
                "id": r.id,
                "value": reported_value(r),
                "outcome": r.outcome,
                "entered_by": person(r.entered_by),
                "entered_at": r.entered_at,
                "current": not r.is_superseded,
                "retest_kind": retests[r.id].get_kind_display() if r.id in retests else "",
                "authorized_by": person(retests[r.id].decided_by) if r.id in retests else None,
            }
            for r in results
        ],
    }


def investigation_payload(inv, user) -> dict:
    is_open = inv.status == InvestigationStatus.OPEN
    pending = inv.status == InvestigationStatus.PENDING_CLOSURE
    may_approve = has_perm(user, APPROVE)
    independent = user.id not in involved_in(inv) or has_perm(user, OVERRIDE)
    return {
        "id": inv.id,
        "reference": inv.reference,
        "kind": inv.kind,
        "kind_label": inv.get_kind_display(),
        "classification": inv.classification,
        "classification_label": inv.get_classification_display(),
        "status": inv.status,
        "status_label": inv.get_status_display(),
        "sample": {"id": inv.sample_id, "sample_no": inv.sample.sample_no} if inv.sample_id else None,
        "test_name": inv.test_definition.name if inv.test_definition_id else "",
        "product_id": inv.product_id,
        "product_name": inv.product.name if inv.product_id else "",
        "batch_no": inv.batch_no,
        "description": inv.description,
        "root_cause": inv.root_cause,
        "outcome": inv.outcome,
        "lab_finding": inv.lab_finding,
        "lab_finding_label": inv.get_lab_finding_display(),
        "lab_finding_notes": inv.lab_finding_notes,
        "lab_finding_by": person(inv.lab_finding_by),
        "lab_finding_at": inv.lab_finding_at,
        "conclusion": inv.conclusion,
        "conclusion_label": inv.get_conclusion_display(),
        "failure": _failure(inv),
        "responsible": person(inv.responsible),
        "due_date": inv.due_date,
        "opened_by": person(inv.opened_by),
        "opened_at": inv.opened_at,
        "submitted_by": person(inv.submitted_by),
        "submitted_at": inv.submitted_at,
        "closed_by": person(inv.closed_by),
        "closed_at": inv.closed_at,
        "actions": [_action(a, inv, user) for a in inv.actions.select_related("owner", "completed_by", "verified_by")],
        "events": [
            {"id": e.id, "at": e.at, "actor": person(e.actor), "what": e.what,
             "changes": e.changes, "comment": e.comment}
            for e in inv.events.select_related("actor")
        ],
        "can": {
            "edit": is_open and has_perm(user, MANAGE),
            "lab_finding": is_open and has_perm(user, MANAGE) and inv.kind == InvestigationKind.OOS,
            "approve": pending and may_approve and independent,
            # Someone involved is told why they cannot approve, rather than shown nothing.
            "approve_blocked": pending and may_approve and not independent,
        },
    }
