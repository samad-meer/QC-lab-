"""
What the screens receive. Every record carries who and the exact
server-side time; nothing here is computed by the client.
"""
from accounts.authz import OVERRIDE, has_perm
from lims.models import FINISHED, UNSIGNED
from lims.workflow import may_sign_stage
from .files import ALLOWED, INLINE, MAX_UPLOAD_MB
from .models import (
    TESTING,
    Assignment,
    AssignmentStatus,
    Attachment,
    ChecklistItem,
    ChecklistResponse,
    RetestRequest,
    StepComment,
)
from . import rules


def person(user) -> dict | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.display_name()}


def _num(value):
    return None if value is None else f"{value.normalize():f}"


def item_payload(item: ChecklistItem) -> dict:
    return {
        "id": item.id,
        "order": item.order,
        "label": item.label,
        "help_text": item.help_text,
        "response_type": item.response_type,
        "required": item.required,
        "expected": item.expected,
        "unit": item.unit,
        "min_value": _num(item.min_value),
        "max_value": _num(item.max_value),
        "decimals": item.decimals,
        "options": item.options,
        "file_types": item.file_types,
        "max_size_mb": item.max_size_mb,
        "waivable": item.waivable,
        "requirement": rules.requirement_text(item),
    }


def attachment_payload(a: Attachment) -> dict:
    return {
        "id": a.id,
        "step": a.step,
        "attempt": a.attempt,
        "item_id": a.item_id,
        "version": a.version,
        "name": a.original_name,
        "extension": a.extension,
        "content_type": a.content_type,
        "size": a.size,
        "sha256": a.sha256,
        "note": a.note,
        "uploaded_by": person(a.uploaded_by),
        "uploaded_at": a.uploaded_at,
        "is_current": a.is_current,
        "replaces_id": a.replaces_id,
        "withdrawn_at": a.withdrawn_at,
        "withdrawn_by": person(a.withdrawn_by),
        "withdraw_reason": a.withdraw_reason,
        "url": f"/api/attachments/{a.id}/",
        "inline": a.extension in INLINE,
    }


def response_payload(item: ChecklistItem, r: ChecklistResponse | None) -> dict | None:
    if r is None:
        return None
    return {
        "id": r.id,
        "attempt": r.attempt,
        "value": r.value,
        "display": rules.display_answer(item, r),
        "attachment_id": r.attachment_id,
        "conforms": r.conforms,
        "answered_by": person(r.answered_by),
        "answered_at": r.answered_at,
        "replaced_at": r.replaced_at,
        "replaced_by": person(r.replaced_by),
        "change_reason": r.change_reason,
    }


def comment_payload(c: StepComment) -> dict:
    """A comment as it reads now: its latest amendment, with every earlier version kept."""
    versions = [c]
    while True:
        later = versions[-1].amendments.select_related("author").first()
        if later is None:
            break
        versions.append(later)
    latest = versions[-1]
    return {
        "id": c.id,
        "step": c.step,
        "attempt": c.attempt,
        "kind": c.kind,
        "body": latest.body,
        "author": person(c.author),
        "created_at": c.created_at,
        "latest_id": latest.id,
        "amended_at": latest.created_at if latest is not c else None,
        "versions": [
            {"id": v.id, "body": v.body, "at": v.created_at} for v in versions
        ] if len(versions) > 1 else [],
        "replies": [
            comment_payload(r)
            for r in c.replies.filter(amends__isnull=True).select_related("author").order_by("created_at", "id")
        ],
    }


def threads(sample, step_key: str) -> list[dict]:
    roots = StepComment.objects.filter(
        sample=sample, step=step_key, parent__isnull=True, amends__isnull=True
    ).select_related("author").order_by("created_at", "id")
    return [comment_payload(c) for c in roots]


def assignment_payload(a: Assignment) -> dict:
    return {
        "id": a.id,
        "step": a.step,
        "kind": a.kind,
        "kind_label": a.get_kind_display(),
        "status": a.status,
        "status_label": a.get_status_display(),
        "from_user": person(a.from_user),
        "to_user": person(a.to_user),
        "created_by": person(a.created_by),
        "created_at": a.created_at,
        "note": a.note,
        "responded_by": person(a.responded_by),
        "responded_at": a.responded_at,
        "response_reason": a.response_reason,
    }


def _value(result) -> str:
    """A result as entered — 91.0, not 91.000000."""
    return _num(result.value_numeric) if result.value_numeric is not None else result.value_text


def retest_payload(r: RetestRequest) -> dict:
    failed = r.failed_result
    return {
        "id": r.id,
        "sample_id": r.sample_id,
        "test_definition_id": r.test_definition_id,
        "test_name": r.test_definition.name,
        "failed_value": _value(failed),
        "failed_entered_by": person(failed.entered_by),
        "failed_entered_at": failed.entered_at,
        "kind": r.kind,
        "kind_label": r.get_kind_display(),
        "reason": r.reason,
        "requested_by": person(r.requested_by),
        "requested_at": r.requested_at,
        "status": r.status,
        "status_label": r.get_status_display(),
        "decided_by": person(r.decided_by),
        "decided_at": r.decided_at,
        "decision_comment": r.decision_comment,
        "retest_value": _value(r.retest_result) if r.retest_result_id else None,
        "retest_outcome": r.retest_result.outcome if r.retest_result_id else None,
        "used_at": r.used_at,
    }


def hold_payload(h) -> dict | None:
    if h is None:
        return None
    return {
        "id": h.id,
        "step": h.step,
        "reason": h.reason,
        "placed_by": person(h.placed_by),
        "placed_at": h.placed_at,
        "released_by": person(h.released_by),
        "released_at": h.released_at,
        "release_comment": h.release_comment,
    }


def _decisions(sample, step: rules.Step) -> list[dict]:
    """What happened at this step in every attempt: submitted, passed, returned."""
    out = []
    if step.is_receipt:
        done = rules.receipt_completion(sample)
        if done is not None:
            out.append({"attempt": 1, "outcome": "COMPLETED", "by": person(done.completed_by),
                        "at": done.completed_at, "reason": done.note})
        return out
    for cert in sample.certificates.order_by("version").prefetch_related("signatures__user"):
        signatures = {s.meaning: s for s in cert.signatures.all()}
        meaning = "ANALYSED" if step.is_testing else step.key
        sig = signatures.get(meaning)
        if sig is not None:
            out.append({
                "attempt": cert.version,
                "outcome": "SUBMITTED" if step.is_testing else "PASSED",
                "by": {"id": sig.user_id, "name": sig.name_snapshot},
                "at": sig.signed_at,
                "reason": "",
            })
        if cert.returned_stage == step.key:
            out.append({
                "attempt": cert.version,
                "outcome": "RETURNED",
                "by": person(cert.returned_by),
                "at": cert.returned_at,
                "reason": cert.superseded_reason,
            })
    return out


def step_payload(sample, step: rules.Step, user, attempt: int) -> dict:
    items = rules.items(sample, step)
    answers = rules.current_responses(sample, step, attempt)
    waived = rules.waivers(sample, step, attempt)
    history = {}
    for r in ChecklistResponse.objects.filter(
        sample=sample, item__in=items, replaced_at__isnull=False
    ).select_related("answered_by", "replaced_by", "attachment").order_by("-answered_at", "-id"):
        history.setdefault(r.item_id, []).append(r)

    who = rules.holder(sample, step)
    waiting = rules.pending(sample, step)
    work = rules.work_blockers(sample, step, user)
    is_current = rules.current_step_key(sample) == step.key
    complete = rules.completion_blockers(sample, step, attempt) if is_current else []
    status = rules.step_status(sample, step, attempt)
    open_for_assignment = not step.is_receipt and sample.status not in FINISHED and (
        is_current or (not step.is_testing and status == "NOT_STARTED")
    )
    in_role = step.stage is not None and may_sign_stage(user, step.stage)
    kind = "receipt" if step.is_receipt else "testing" if step.is_testing else "review"
    title = {"receipt": "Front desk", "testing": "Analyst"}.get(kind)

    return {
        "key": step.key,
        "name": step.name,
        "order": step.order,
        "kind": kind,
        "role_name": step.stage.role.name if step.stage else title,
        "holder_title": step.stage.holder if step.stage else title,
        "requires_acceptance": step.requires_acceptance,
        "is_current": is_current,
        "status": status,
        "status_label": rules.STATUS_LABELS[status],
        "holder": person(who),
        "pending": assignment_payload(waiting) if waiting else None,
        "assignments": [
            assignment_payload(a) for a in Assignment.objects.filter(sample=sample, step=step.key)
            .select_related("from_user", "to_user", "created_by", "responded_by").order_by("-created_at", "-id")
        ],
        "checklist": [
            {
                "item": item_payload(item),
                "response": response_payload(item, answers.get(item.id)),
                "history": [response_payload(item, r) for r in history.get(item.id, [])],
                "waiver": (
                    {"reason": waived[item.id].reason, "by": person(waived[item.id].waived_by),
                     "at": waived[item.id].waived_at}
                    if item.id in waived else None
                ),
            }
            for item in items
        ],
        "attachments": [
            attachment_payload(a) for a in Attachment.objects.filter(sample=sample, step=step.key)
            .select_related("uploaded_by", "withdrawn_by")
        ],
        "comments": threads(sample, step.key),
        "decisions": _decisions(sample, step),
        "work_blockers": [b.__dict__ for b in work],
        "blockers": [b.__dict__ for b in complete],
        "overridden": [b.message for b in rules.overridden_blockers(sample, step, user)],
        "can": {
            "work": is_current and not work,
            "accept": waiting is not None and waiting.to_user_id == user.id,
            "cancel": waiting is not None and (waiting.created_by_id == user.id or has_perm(user, "sample.assign")),
            "take": (
                is_current and in_role and who is None and waiting is None
                and not rules.active_hold(sample)
            ),
            "hand_over": open_for_assignment and waiting is None and (
                (who is not None and who.id == user.id) or (who is None and in_role)
            ),
            "assign": open_for_assignment and has_perm(user, "sample.assign"),
            "waive": is_current and has_perm(user, "stage.waive"),
            # Only the receipt checks are completed from this panel; the other
            # steps finish with a signature on their own screens.
            "complete": (
                step.is_receipt and is_current and not work and not complete
                and (has_perm(user, OVERRIDE) or not rules.waived_by(sample, step, attempt, user))
            ),
        },
    }


def execution_payload(sample, user) -> dict:
    attempt = rules.attempt_of(sample)
    hold = rules.active_hold(sample)
    retests = RetestRequest.objects.filter(sample=sample).select_related(
        "test_definition", "failed_result__entered_by", "requested_by", "decided_by", "retest_result"
    )
    return {
        "sample_id": sample.id,
        "attempt": attempt,
        "current_step": rules.current_step_key(sample),
        "hold": hold_payload(hold),
        "holds": [hold_payload(h) for h in sample.holds.select_related("placed_by", "released_by")],
        "can_hold": has_perm(user, "sample.hold") and sample.status not in FINISHED,
        "can_reject": has_perm(user, "investigation.approve") and sample.status in UNSIGNED,
        "can_cancel": has_perm(user, "sample.cancel") and sample.status in UNSIGNED,
        "can_authorize_retests": has_perm(user, "result.retest.authorize"),
        "can_comment": has_perm(user, "sample.comment"),
        "steps": [step_payload(sample, step, user, rules.attempt_for(sample, step)) for step in rules.steps(sample)],
        "general_comments": threads(sample, ""),
        "retests": [retest_payload(r) for r in retests],
        "file_types": sorted(ALLOWED),
        "max_upload_mb": MAX_UPLOAD_MB,
    }


__all__ = ["execution_payload", "TESTING"]
