"""
The task center: everything waiting on one person, worked out on the
server from the same rules that enforce it — never from what a screen
happens to have loaded.
"""
from django.utils import timezone

from accounts.authz import OVERRIDE, has_perm
from lims.models import FINISHED, SampleStatus
from lims.workflow import review_queue, samples_visible_to
from .models import RECEIPT, TESTING, Assignment, AssignmentStatus, RetestRequest, RetestStatus, SampleHold
from .payloads import assignment_payload, hold_payload, person, retest_payload
from . import rules


def _sample_ref(s) -> dict:
    return {
        "id": s.id,
        "sample_no": s.sample_no,
        "product_name": s.product.name,
        "product_code": s.product.code,
        "batch_no": s.batch_no,
        "batch_label": s.batch_label,
        "due_date": s.due_date,
        "status": s.status,
        "status_label": s.status_label(),
        "overdue": s.status not in FINISHED and s.due_date < timezone.localdate(),
    }


def _row(sample, step: rules.Step | None, **extra) -> dict:
    row = {"sample": _sample_ref(sample), "step": step.key if step else "", "step_name": step.name if step else ""}
    row.update(extra)
    return row


def _returned(sample) -> dict | None:
    """Why the current attempt exists, if it follows a send-back."""
    cert = sample.certificates.filter(returned_at__isnull=False).select_related("returned_by").order_by("-version").first()
    if cert is None or rules.attempt_of(sample) != cert.version + 1:
        return None
    stage = next((s for s in rules.steps(sample) if s.key == cert.returned_stage), None)
    return {
        "from_step": stage.name if stage else cert.returned_stage,
        "by": person(cert.returned_by),
        "at": cert.returned_at,
        "reason": cert.superseded_reason,
    }


def tasks_for(user, detail: bool = True) -> dict:
    """
    Everything waiting on this person. Without `detail`, each list holds the same samples but not what
    each still needs (its status and blockers), which is most of the work: the menu badge and the
    dashboard only count.
    """
    visible = samples_visible_to(user)

    to_accept = [
        _row(a.sample, rules.step_of(a.sample, a.step), assignment=assignment_payload(a))
        for a in Assignment.objects.filter(to_user=user, status=AssignmentStatus.PENDING)
        .select_related("sample__product", "sample__workflow_version", "from_user", "to_user", "created_by")
        .order_by("created_at")
    ]
    sent = [
        _row(a.sample, rules.step_of(a.sample, a.step), assignment=assignment_payload(a))
        for a in Assignment.objects.filter(created_by=user, status=AssignmentStatus.PENDING)
        .exclude(to_user=user)
        .select_related("sample__product", "sample__workflow_version", "from_user", "to_user", "created_by")
        .order_by("created_at")
    ]

    receipts = []
    if has_perm(user, "sample.register"):
        for s in visible.filter(
            status=SampleStatus.RECEIVED, receipt_completion__isnull=True,
            workflow_version__checklist__for_receipt=True, workflow_version__checklist__stage__isnull=True,
        ).distinct().order_by("received_at", "id"):
            step = rules.step_of(s, RECEIPT)
            receipts.append(_row(s, step, **({
                "status": rules.step_status(s, step, 1),
                "blockers": [b.message for b in rules.completion_blockers(s, step, 1)][:3],
            } if detail else {})))

    my_testing, returned, upcoming = [], [], []
    for s in visible.filter(
        assigned_analyst=user, status__in=[SampleStatus.RECEIVED, SampleStatus.IN_TESTING]
    ).order_by("due_date", "id"):
        step = rules.step_of(s, TESTING)
        attempt = rules.attempt_of(s)
        waiting = rules.pending(s, step)
        if waiting is not None and waiting.to_user_id == user.id:
            continue  # listed under to_accept until they accept it
        if rules.receipt_open(s):
            upcoming.append(_row(s, step, status="WAITING"))  # reaches them once the receipt checks are done
            continue
        back = _returned(s)
        row = _row(s, step, attempt=attempt, returned=back, **({
            "status": rules.step_status(s, step, attempt),
            "blockers": [b.message for b in rules.completion_blockers(s, step, attempt)][:3],
        } if detail else {}))
        (returned if back else my_testing).append(row)

    to_review = []
    for s in review_queue(user).select_related("product", "review_stage__role").order_by("due_date", "id"):
        step = rules.step_of(s, s.review_stage.code)
        who = rules.holder(s, step)
        if who is not None and who.id != user.id:
            continue
        waiting = rules.pending(s, step)
        if who is None and waiting is not None and (waiting.to_user_id == user.id or step.requires_acceptance):
            continue  # handed to them (listed under to_accept), or to someone else who must accept it
        to_review.append(_row(
            s, step, needs_taking=who is None and step.requires_acceptance,
            **({"blockers": [b.message for b in rules.completion_blockers(s, step, rules.attempt_of(s))][:3]}
               if detail else {}),
        ))
    queued = {r["sample"]["id"] for r in to_review}
    seen = set()
    for a in Assignment.objects.filter(to_user=user, status=AssignmentStatus.ACCEPTED).exclude(
            sample__status__in=FINISHED).exclude(step=TESTING) \
            .select_related("sample__product", "sample__review_stage").order_by("-responded_at"):
        key = (a.sample_id, a.step)
        if key in seen or a.sample_id in queued:
            continue
        seen.add(key)
        s = a.sample
        step = rules.step_of(s, a.step)
        holder = rules.holder(s, step)
        status = rules.step_status(s, step, rules.attempt_of(s))
        if holder is None or holder.id != user.id or status != "NOT_STARTED":
            continue
        upcoming.append(_row(s, step, status=status))

    retests_to_decide = []
    if has_perm(user, "result.retest.authorize"):
        for r in RetestRequest.objects.filter(status=RetestStatus.PENDING).select_related(
            "sample__product", "test_definition", "failed_result__entered_by", "requested_by",
            "decided_by", "retest_result",
        ):
            conflicted = user.id in {r.requested_by_id, r.failed_result.entered_by_id, r.sample.assigned_analyst_id}
            if conflicted and not has_perm(user, OVERRIDE):
                continue
            retests_to_decide.append(_row(r.sample, None, retest=retest_payload(r)))
    my_retests = [
        _row(r.sample, None, retest=retest_payload(r))
        for r in RetestRequest.objects.filter(
            requested_by=user, status__in=[RetestStatus.PENDING, RetestStatus.AUTHORIZED]
        ).select_related("sample__product", "test_definition", "failed_result__entered_by",
                         "requested_by", "decided_by", "retest_result")
    ]

    needs_reassigning = []
    if has_perm(user, "sample.assign"):
        for a in Assignment.objects.filter(status=AssignmentStatus.REJECTED).exclude(
            sample__status__in=FINISHED).select_related(
            "sample__product", "from_user", "to_user", "created_by", "responded_by"
        ).order_by("-responded_at"):
            s = a.sample
            step = rules.step_of(s, a.step)
            if rules.current_step_key(s) != step.key or rules.holder(s, step) is not None or rules.pending(s, step):
                continue
            if any(r["sample"]["id"] == s.id and r["step"] == step.key for r in needs_reassigning):
                continue
            needs_reassigning.append(_row(s, step, assignment=assignment_payload(a)))

    on_hold = [
        _row(h.sample, None, hold=hold_payload(h))
        for h in SampleHold.objects.filter(released_at__isnull=True, sample__in=visible)
        .select_related("sample__product", "placed_by").order_by("placed_at")
    ]
    overdue = [
        _row(s, None)
        for s in visible.exclude(status__in=FINISHED).filter(due_date__lt=timezone.localdate())
        .order_by("due_date")[:50]
    ]

    # Batch-record stages assigned to this person: values to write or their column to sign.
    batch_stages = _batch_stages(user)

    buckets = {
        "receipts": receipts,
        "to_accept": to_accept,
        "returned": returned,
        "my_testing": my_testing,
        "to_review": to_review,
        "retests_to_decide": retests_to_decide,
        "needs_reassigning": needs_reassigning,
        "batch_stages": batch_stages,
        "upcoming": upcoming,
        "sent": sent,
        "my_retests": my_retests,
        "on_hold": on_hold,
        "overdue": overdue,
    }
    actionable = ("receipts", "to_accept", "returned", "my_testing", "to_review", "retests_to_decide",
                  "needs_reassigning")
    return {
        **buckets,
        "counts": {k: len(v) for k, v in buckets.items()},
        # A stage still waiting for the stages before it is listed, not counted as work to do now.
        "actionable": sum(len(buckets[k]) for k in actionable)
        + sum(1 for w in batch_stages if w["state"] != "waiting"),
        "generated_at": timezone.now(),
    }


def _batch_stages(user) -> list[dict]:
    if not has_perm(user, "batch.record.fill"):
        return []
    from batches.stages import assigned_work  # batches builds on this app; imported when needed

    return [
        {
            "batch": {"id": w["batch"].id, "official_batch_no": w["batch"].official_batch_no,
                      "internal_id": w["batch"].internal_id, "product": w["batch"].product.name},
            "stage": {"id": w["stage"].id, "order": w["stage"].order, "name": w["stage"].name},
            "state": w["state"], "missing": w["missing"], "waiting_for": w["waiting_for"], "column": w["column"],
            "assigned_by": person(w["assignment"].assigned_by), "assigned_at": w["assignment"].assigned_at,
            "note": w["assignment"].note,
        }
        for w in assigned_work(user)
    ]
