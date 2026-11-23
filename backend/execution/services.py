"""
Lab-execution actions. Each one checks the rules (rules.py) under a row
lock on the sample, writes append-only records, and leaves an audit entry.
A refused action raises ExecutionError with a message for the person.
"""
from decimal import Decimal
from datetime import date

from django.db import transaction
from django.utils import timezone

from accounts.authz import has_perm, overrides
from accounts.models import LabConfig, User
from audit.services import record
from lims.evaluation import ResultValueError, parse_numeric, rounded
from lims.models import FINISHED, Outcome, Sample, SampleStatus, TestResult, WorkflowEvent
from lims.workflow import may_sign_stage
from notifications.services import notify, notify_all, users_with
from quality.models import Conclusion, Investigation, InvestigationKind
from .files import MAX_UPLOAD_MB, FileRejected, check_upload, safe_display_name
from .models import (
    RECEIPT,
    TESTING,
    Assignment,
    AssignmentKind,
    AssignmentStatus,
    Attachment,
    ChecklistItem,
    ChecklistResponse,
    CommentKind,
    ReceiptCompletion,
    ResponseType,
    RetestKind,
    RetestRequest,
    RetestStatus,
    SampleHold,
    StepComment,
    Waiver,
)
from .rules import (
    ExecutionError,
    active_hold,
    attempt_for,
    attempt_of,
    current_step_key,
    display_answer,
    has_receipt_checks,
    holder,
    items,
    live_certificate,
    pending,
    require_can_complete,
    require_can_work,
    stamp,
    step_of,
    waivers,
)

MAX_COMMENT = 4000
TRUE_WORDS = {"true", "yes", "1", "on", "confirmed"}


def _lock(sample) -> Sample:
    return Sample.objects.select_for_update().get(pk=sample.pk)


def _require_perm(user, key: str, sample, message: str):
    if not has_perm(user, key):
        record(user, "ACCESS_REFUSED", "sample", sample.sample_no, reason=message)
        raise ExecutionError(message)


def _required_text(value, message: str, limit: int = 1000) -> str:
    text = (value or "").strip()
    if not text:
        raise ExecutionError(message)
    if len(text) > limit:
        raise ExecutionError(f"Keep it under {limit} characters.")
    return text


# --- checklist answers ---------------------------------------------------

def clean_answer(item: ChecklistItem, raw, attachment=None) -> tuple[str, Decimal | None, bool]:
    """(canonical value, number, conforms) — decided here, never by the client."""
    t = item.response_type
    if t == ResponseType.CHECKBOX:
        if str(raw).strip().lower() not in TRUE_WORDS:
            raise ExecutionError("Tick the box to confirm — an empty box is not an answer.")
        return "YES", None, True
    if t == ResponseType.YES_NO:
        value = str(raw or "").strip().upper()
        if value not in ("YES", "NO"):
            raise ExecutionError(f"Answer “{item.label}” with Yes or No.")
        return value, None, not item.expected or value == item.expected
    if t == ResponseType.PASS_FAIL:
        value = str(raw or "").strip().upper()
        if value not in ("PASS", "FAIL"):
            raise ExecutionError(f"Record “{item.label}” as Pass or Fail.")
        return value, None, value == "PASS"
    if t == ResponseType.NUMBER:
        if raw in (None, ""):
            raise ExecutionError(f"Enter a number for “{item.label}”.")
        try:
            number = parse_numeric(raw)
        except ResultValueError as e:
            raise ExecutionError(str(e))
        if item.decimals is not None:
            number = rounded(number, item.decimals)
        ok = (item.min_value is None or number >= item.min_value) and (
            item.max_value is None or number <= item.max_value
        )
        return f"{number:f}", number, ok
    if t == ResponseType.TEXT:
        return _required_text(raw, f"Write an answer for “{item.label}”."), None, True
    if t == ResponseType.DATE:
        try:
            value = date.fromisoformat(str(raw or "").strip())
        except ValueError:
            raise ExecutionError(f"“{item.label}” needs a valid date.")
        return value.isoformat(), None, True
    if t == ResponseType.CHOICE:
        value = str(raw or "").strip()
        if value not in item.options:
            raise ExecutionError(f"Choose one of the listed answers for “{item.label}”.")
        return value, None, not item.expected or value == item.expected
    if t == ResponseType.FILE:
        if attachment is None:
            raise ExecutionError(f"Upload the document for “{item.label}”.")
        return attachment.original_name, None, True
    raise ExecutionError("Unknown checklist item type.")


def _item_of(sample, item_id) -> ChecklistItem:
    item = (
        ChecklistItem.objects.filter(pk=item_id, version_id=sample.workflow_version_id)
        .select_related("stage").first()
        if str(item_id or "").isdigit() else None
    )
    if item is None:
        raise ExecutionError("That checklist item is not part of this sample's workflow.")
    return item


def _record_answer(sample, item, step, user, attempt, value, number, conforms, attachment, reason):
    """Write one answer, replacing the current one. Caller holds the sample lock."""
    previous = (
        ChecklistResponse.objects.select_for_update(of=("self",))
        .filter(sample=sample, item=item, attempt=attempt, replaced_at__isnull=True)
        .select_related("attachment").first()
    )
    if previous is not None:
        if previous.value == value and previous.number == number and previous.attachment_id == (
            attachment.id if attachment else None
        ):
            return previous
        if not reason:
            raise ExecutionError(f"Say why “{item.label}” is changing: the earlier answer stays on record.")
        previous.replaced_at = timezone.now()
        previous.replaced_by = user
        previous.change_reason = reason
        previous.save()
    response = ChecklistResponse.objects.create(
        sample=sample, item=item, attempt=attempt, value=value, number=number,
        attachment=attachment, conforms=conforms, answered_by=user,
    )
    record(
        user, "CHECKLIST_CHANGED" if previous else "CHECKLIST_ANSWERED", "sample", sample.sample_no,
        step=step.name, item=item.label, answer=display_answer(item, response),
        previous=display_answer(item, previous) if previous else "", conforms=conforms,
        attempt=attempt, reason=reason,
    )
    return response


def answer(sample, item_id, user, value, attachment_id=None, reason: str = "") -> ChecklistResponse:
    item = _item_of(sample, item_id)
    step = step_of(sample, item.step)
    reason = (reason or "").strip()[:500]
    with transaction.atomic():
        sample = _lock(sample)
        require_can_work(sample, step, user)
        attempt = attempt_for(sample, step)
        attachment = None
        if item.response_type == ResponseType.FILE:
            attachment = Attachment.objects.filter(
                pk=attachment_id or 0, sample=sample, item=item,
                withdrawn_at__isnull=True, replaced_by__isnull=True,
            ).first()
        value, number, conforms = clean_answer(item, value, attachment)
        return _record_answer(sample, item, step, user, attempt, value, number, conforms, attachment, reason)


def clear_answer(sample, item_id, user, reason: str):
    """Take back an answer given by mistake. The answer stays on record, marked withdrawn."""
    item = _item_of(sample, item_id)
    step = step_of(sample, item.step)
    reason = _required_text(reason, "Say why the answer is being cleared.", 500)
    with transaction.atomic():
        sample = _lock(sample)
        require_can_work(sample, step, user)
        attempt = attempt_for(sample, step)
        previous = ChecklistResponse.objects.select_for_update().filter(
            sample=sample, item=item, attempt=attempt, replaced_at__isnull=True
        ).first()
        if previous is None:
            raise ExecutionError("That item has no answer to clear.")
        previous.replaced_at = timezone.now()
        previous.replaced_by = user
        previous.change_reason = reason
        previous.save()
        record(user, "CHECKLIST_CLEARED", "sample", sample.sample_no, step=step.name, item=item.label,
               previous=display_answer(item, previous), reason=reason, attempt=attempt)


# --- attachments ---------------------------------------------------------

def upload(sample, step_key: str, user, uploaded, item_id=None, replaces_id=None, note: str = "") -> Attachment:
    step = step_of(sample, step_key)
    item = None
    if item_id not in (None, ""):
        item = _item_of(sample, item_id)
        if item.step != step.key or item.response_type != ResponseType.FILE:
            raise ExecutionError("That item does not take a document.")
    name = safe_display_name(getattr(uploaded, "name", ""))
    try:
        ext, content_type, size, sha = check_upload(
            uploaded, item.file_types if item else None, item.max_size_mb if item else MAX_UPLOAD_MB
        )
    except FileRejected as e:
        record(user, "ATTACHMENT_REFUSED", "sample", sample.sample_no, step=step.name, name=name, reason=str(e))
        raise ExecutionError(str(e))

    with transaction.atomic():
        sample = _lock(sample)
        require_can_work(sample, step, user)
        attempt = attempt_for(sample, step)
        previous = None
        if replaces_id not in (None, ""):
            previous = Attachment.objects.select_for_update().filter(
                pk=replaces_id if str(replaces_id).isdigit() else 0, sample=sample, step=step.key
            ).first()
            if previous is None or not previous.is_current:
                raise ExecutionError("Only the current version of a file can be replaced.")
            item = item or previous.item
        elif item is not None:
            previous = Attachment.objects.select_for_update().filter(
                sample=sample, item=item, withdrawn_at__isnull=True, replaced_by__isnull=True
            ).first()
        attachment = Attachment(
            sample=sample, step=step.key, attempt=attempt, item=item,
            version=(previous.version + 1) if previous else 1, replaces=previous,
            original_name=name, extension=ext, content_type=content_type, size=size, sha256=sha,
            note=(note or "").strip()[:500], uploaded_by=user,
        )
        attachment.file.save(f"upload.{ext}", uploaded, save=False)
        attachment.save()
        if previous is not None:
            previous.replaced_by = attachment
            previous.save()
        record(user, "ATTACHMENT_UPLOADED", "sample", sample.sample_no, step=step.name, name=name,
               version=attachment.version, size=size, sha256=sha, item=item.label if item else "")
        if item is not None:
            value, number, conforms = clean_answer(item, None, attachment)
            _record_answer(sample, item, step, user, attempt, value, number, conforms, attachment, "New file uploaded")
    return attachment


def withdraw(attachment: Attachment, user, reason: str):
    reason = _required_text(reason, "Say why the file is being withdrawn.", 500)
    sample = attachment.sample
    step = step_of(sample, attachment.step)
    with transaction.atomic():
        sample = _lock(sample)
        attachment = Attachment.objects.select_for_update().get(pk=attachment.pk)
        if not attachment.is_current:
            raise ExecutionError("Only the current version of a file can be withdrawn.")
        if attachment.uploaded_by_id != user.id and not overrides(
            user, f"Only {attachment.uploaded_by.display_name()}, who uploaded it, can withdraw {attachment.original_name}."
        ):
            raise ExecutionError("Only the person who uploaded a file can withdraw it.")
        require_can_work(sample, step, user)
        now = timezone.now()
        attachment.withdrawn_at = now
        attachment.withdrawn_by = user
        attachment.withdraw_reason = reason
        attachment.save()
        # An answer that pointed at this file no longer stands.
        for response in ChecklistResponse.objects.select_for_update().filter(
            attachment=attachment, replaced_at__isnull=True
        ):
            response.replaced_at = now
            response.replaced_by = user
            response.change_reason = f"File withdrawn: {reason}"
            response.save()
        record(user, "ATTACHMENT_WITHDRAWN", "sample", sample.sample_no, step=step.name,
               name=attachment.original_name, version=attachment.version, reason=reason)


# --- comments ------------------------------------------------------------

def _original(comment: StepComment) -> StepComment:
    while comment.amends_id:
        comment = comment.amends
    return comment


def add_comment(sample, user, step_key: str, body: str, kind: str = CommentKind.NOTE,
                parent_id=None, amends_id=None) -> StepComment:
    _require_perm(user, "sample.comment", sample,
                  "You do not have permission to add notes or feedback. You can still read them.")
    body = _required_text(body, "Write something first.", MAX_COMMENT)
    if kind not in CommentKind.values:
        raise ExecutionError("Unknown kind of comment.")
    step = step_of(sample, step_key) if step_key else None
    parent = amends = None

    if amends_id not in (None, ""):
        amends = StepComment.objects.filter(pk=amends_id if str(amends_id).isdigit() else 0, sample=sample).first()
        if amends is None:
            raise ExecutionError("That comment does not exist.")
        if amends.author_id != user.id:
            raise ExecutionError("You can only amend your own comments. Reply instead.")
        if amends.amendments.exists():
            raise ExecutionError("That version has already been amended — amend the latest one.")
        step_key, kind, parent = amends.step, amends.kind, amends.parent
    elif parent_id not in (None, ""):
        parent = StepComment.objects.filter(pk=parent_id if str(parent_id).isdigit() else 0, sample=sample).first()
        if parent is None:
            raise ExecutionError("That comment does not exist.")
        # One level of threading: a reply to a reply joins the same thread.
        parent = _original(parent)
        if parent.parent_id:
            parent = _original(parent.parent)
        step_key = parent.step

    comment = StepComment.objects.create(
        sample=sample, step=step_key or "", attempt=attempt_of(sample), kind=kind, body=body,
        parent=parent, amends=amends, author=user,
    )
    action = (
        "COMMENT_AMENDED" if amends else "COMMENT_REPLIED" if parent
        else "FEEDBACK_ADDED" if kind == CommentKind.FEEDBACK else "COMMENT_ADDED"
    )
    record(user, action, "sample", sample.sample_no,
           step=step.name if step else (step_of(sample, step_key).name if step_key else "the sample"),
           excerpt=body[:120])
    return comment


# --- assignments and handovers -------------------------------------------

def candidates(sample, step):
    """Who may hold this step: the people an assignment or handover can go to."""
    if step.is_receipt:
        return User.objects.none()
    if step.is_testing:
        qs = User.objects.filter(
            is_active=True, role__is_active=True, role__grants__permission="result.enter",
            role__grants__revoked_at__isnull=True, sections=sample.section,
        )
    else:
        qs = User.objects.filter(is_active=True, role_id=step.stage.role_id, role__is_active=True)
        cert = live_certificate(sample)
        if cert is not None:
            qs = qs.exclude(pk__in=cert.signatures.values("user_id"))
        qs = qs.exclude(pk=sample.assigned_analyst_id)
    return qs.distinct().order_by("first_name", "username")


def _check_target(sample, step, to_user):
    if candidates(sample, step).filter(pk=to_user.pk).exists():
        return
    name = to_user.display_name()
    if step.is_testing:
        raise ExecutionError(
            f"{name} cannot take the testing — they must be an active analyst trained for {sample.section.name}."
        )
    raise ExecutionError(
        f"{name} cannot take “{step.name}” — they must hold the {step.stage.role.name} role, must not be "
        "the sample's analyst, and must not have signed this certificate already."
    )


def _check_open(sample, step):
    if step.is_receipt:
        raise ExecutionError("Receipt checks are made by the front desk — they are not assigned or handed over.")
    if sample.status in FINISHED:
        raise ExecutionError("This sample is finished — there is nothing left to assign.")
    # Testing can change hands before it starts, while the receipt checks are still open.
    if step.is_testing and sample.status not in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING):
        raise ExecutionError("Testing is finished for this attempt — the analyst has signed.")
    if not step.is_testing:
        cert = live_certificate(sample)
        if cert is not None and cert.signatures.filter(meaning=step.key).exists():
            raise ExecutionError(f"“{step.name}” is already signed.")


def _took_effect(sample, step, assignment, actor):
    """An accepted assignment of the testing moves the sample to its new analyst."""
    if step.is_testing and sample.assigned_analyst_id != assignment.to_user_id:
        sample.assigned_analyst = assignment.to_user
        sample.save(update_fields=["assigned_analyst"])
        WorkflowEvent.objects.create(
            sample=sample, actor=actor, from_status=sample.status, to_status=sample.status,
            comment=f"Testing now held by {assignment.to_user.display_name()}",
        )


def _link(sample, step) -> str:
    """Straight to the review screen when that is where the work is."""
    if not step.is_testing and current_step_key(sample) == step.key:
        return f"/samples/{sample.id}/review"
    return f"/samples/{sample.id}"


def _quoted(text: str) -> str:
    return f"“{text}”" if text else ""


def announce_stage(sample, stage, actor):
    """The sample has reached a stage: tell whoever it is assigned to, or else everyone who could take it."""
    step = step_of(sample, stage.code)
    who = holder(sample, step)
    body = f"{sample.product.name} · {sample.batch_label}. It is ready for your review."
    if who is not None:
        notify(who, "YOUR_TURN", f"{sample.sample_no} has reached “{step.name}” — assigned to you",
               body=body, link=_link(sample, step), sample=sample, actor=actor)
    elif pending(sample, step) is None:
        notify_all(candidates(sample, step), "REVIEW_WAITING", f"{sample.sample_no} is waiting at “{step.name}”",
                   body=body, link=_link(sample, step), sample=sample, actor=actor)


def _cancel_pending(sample, step, by, reason):
    for a in Assignment.objects.select_for_update().filter(
        sample=sample, step=step.key, status=AssignmentStatus.PENDING
    ):
        a.status = AssignmentStatus.CANCELLED
        a.responded_by = by
        a.responded_at = timezone.now()
        a.response_reason = reason
        a.save()


def record_registration(sample, analyst, by):
    """Registration assigns the testing; it needs accepting if the workflow says so."""
    needs = sample.workflow_version.testing_requires_acceptance
    Assignment.objects.create(
        sample=sample, step=TESTING, kind=AssignmentKind.ASSIGNED,
        status=AssignmentStatus.PENDING if needs else AssignmentStatus.ACCEPTED,
        to_user=analyst, created_by=by, note="Assigned at registration",
        responded_at=None if needs else timezone.now(),
        response_reason="" if needs else "Acceptance is not required at this step",
    )
    notify(analyst, "ASSIGNED", f"{sample.sample_no} assigned to you for testing",
           body=f"{sample.product.name} · {sample.batch_label} · due {sample.due_date:%d %b %Y}."
                + (" Accept it to confirm you have received the sample." if needs else "")
                + (" Testing opens once the front desk completes the receipt checks."
                   if has_receipt_checks(sample.workflow_version) else ""),
           sample=sample, actor=by)


def complete_receipt(sample, by, note: str = "") -> ReceiptCompletion:
    """The front desk confirms the receipt checks. Testing can start from here."""
    step = step_of(sample, RECEIPT)
    note = (note or "").strip()[:500]
    # Once to record a refusal, once under the lock to close the race.
    require_can_complete(sample, step, by, 1)
    with transaction.atomic():
        sample = _lock(sample)
        require_can_complete(sample, step, by, 1, audit=False)
        done = ReceiptCompletion.objects.create(sample=sample, completed_by=by, note=note)
        checks = items(sample, step)
        waived = waivers(sample, step, 1)
        WorkflowEvent.objects.create(
            sample=sample, actor=by, from_status=sample.status, to_status=sample.status,
            comment="Receipt checks completed — ready for testing" + (f": {note}" if note else ""),
        )
        record(by, "RECEIPT_COMPLETED", "sample", sample.sample_no,
               checks=len(checks), waived=len(waived), note=note)
        notify(sample.assigned_analyst, "READY_FOR_TESTING", f"{sample.sample_no} is ready for testing",
               body=f"{by.display_name()} completed the receipt checks. "
                    f"{sample.product.name} · {sample.batch_label} · due {sample.due_date:%d %b %Y}.",
               sample=sample, actor=by)
    return done


def assign(sample, step_key: str, to_user, by, note: str = "") -> Assignment:
    _require_perm(by, "sample.assign", sample, "You do not have permission to assign work.")
    step = step_of(sample, step_key)
    note = (note or "").strip()[:1000]
    with transaction.atomic():
        sample = _lock(sample)
        _check_open(sample, step)
        _check_target(sample, step, to_user)
        who = holder(sample, step)
        if who is not None and who.id == to_user.id:
            raise ExecutionError(f"{to_user.display_name()} already holds “{step.name}”.")
        _cancel_pending(sample, step, by, "Replaced by a new assignment")
        needs = step.requires_acceptance
        now = timezone.now()
        a = Assignment.objects.create(
            sample=sample, step=step.key, kind=AssignmentKind.ASSIGNED,
            status=AssignmentStatus.PENDING if needs else AssignmentStatus.ACCEPTED,
            from_user=who, to_user=to_user, created_by=by, note=note,
            responded_at=None if needs else now,
            response_reason="" if needs else "Acceptance is not required at this step",
        )
        if not needs:
            _took_effect(sample, step, a, by)
        record(by, "ASSIGNED", "sample", sample.sample_no, step=step.name, to=to_user.display_name(),
               previous=who.display_name() if who else "nobody", note=note, needs_acceptance=needs)
        notify(to_user, "ASSIGNED", f"“{step.name}” of {sample.sample_no} assigned to you",
               body=" ".join(filter(None, [
                   f"Assigned by {by.display_name()}.", _quoted(note),
                   "Accept it before you start." if needs else "",
               ])),
               link=_link(sample, step), sample=sample, actor=by)
        if who is not None:
            notify(who, "REASSIGNED", f"“{step.name}” of {sample.sample_no} reassigned to {to_user.display_name()}",
                   body=f"By {by.display_name()}." + (" It stays with you until they accept it." if needs else ""),
                   sample=sample, actor=by)
    return a


def hand_over(sample, step_key: str, to_user, by, note: str) -> Assignment:
    step = step_of(sample, step_key)
    note = _required_text(note, "Say what the next person needs to know — a handover always carries a note.")
    with transaction.atomic():
        sample = _lock(sample)
        _check_open(sample, step)
        who = holder(sample, step)
        if step.is_testing:
            if who is None or who.id != by.id:
                raise ExecutionError("Only the analyst holding the testing can hand it over.")
        elif who is not None and who.id != by.id:
            raise ExecutionError(f"Only {who.display_name()} can hand “{step.name}” over.")
        elif who is None and not may_sign_stage(by, step.stage):
            raise ExecutionError(f"Only someone in the {step.stage.role.name} role can hand “{step.name}” over.")
        if to_user.id == by.id:
            raise ExecutionError("You cannot hand work over to yourself.")
        waiting = pending(sample, step)
        if waiting is not None:
            raise ExecutionError(
                f"A handover of “{step.name}” is already waiting for {waiting.to_user.display_name()}. Cancel it first."
            )
        _check_target(sample, step, to_user)
        a = Assignment.objects.create(
            sample=sample, step=step.key, kind=AssignmentKind.HANDOVER, status=AssignmentStatus.PENDING,
            from_user=who, to_user=to_user, created_by=by, note=note,
        )
        record(by, "HANDOVER_OFFERED", "sample", sample.sample_no, step=step.name,
               to=to_user.display_name(), note=note)
        notify(to_user, "HANDOVER", f"{by.display_name()} handed “{step.name}” of {sample.sample_no} to you",
               body=f"{_quoted(note)} Accept it to take the work, or decline with a reason.",
               link=_link(sample, step), sample=sample, actor=by)
    return a


def claim(sample, step_key: str, by) -> Assignment:
    step = step_of(sample, step_key)
    if step.is_testing:
        raise ExecutionError("Testing is assigned at registration — it cannot be taken.")
    with transaction.atomic():
        sample = _lock(sample)
        _check_open(sample, step)
        if not may_sign_stage(by, step.stage):
            raise ExecutionError(f"Only someone in the {step.stage.role.name} role can take “{step.name}”.")
        who = holder(sample, step)
        if who is not None:
            raise ExecutionError(
                "You already hold this stage." if who.id == by.id
                else f"“{step.name}” is assigned to {who.display_name()}."
            )
        waiting = pending(sample, step)
        if waiting is not None:
            raise ExecutionError(
                f"“{step.name}” has been handed to {waiting.to_user.display_name()} — "
                + ("accept it instead." if waiting.to_user_id == by.id else "waiting for them to accept.")
            )
        _check_target(sample, step, by)
        now = timezone.now()
        a = Assignment.objects.create(
            sample=sample, step=step.key, kind=AssignmentKind.CLAIMED, status=AssignmentStatus.ACCEPTED,
            to_user=by, created_by=by, responded_by=by, responded_at=now,
        )
        record(by, "STEP_CLAIMED", "sample", sample.sample_no, step=step.name)
    return a


def respond(assignment: Assignment, by, accept: bool, reason: str = "") -> Assignment:
    reason = (reason or "").strip()[:1000]
    if not accept and not reason:
        raise ExecutionError("Say why you are declining — the person who sent it will read this.")
    with transaction.atomic():
        sample = _lock(assignment.sample)
        a = Assignment.objects.select_for_update().get(pk=assignment.pk)
        if a.status != AssignmentStatus.PENDING:
            raise ExecutionError("This has already been answered.")
        if a.to_user_id != by.id:
            raise ExecutionError(f"Only {a.to_user.display_name()} can answer this.")
        step = step_of(sample, a.step)
        if accept:
            _check_open(sample, step)
            _check_target(sample, step, by)
        a.status = AssignmentStatus.ACCEPTED if accept else AssignmentStatus.REJECTED
        a.responded_by = by
        a.responded_at = timezone.now()
        a.response_reason = reason
        a.save()
        if accept:
            _took_effect(sample, step, a, by)
        record(by, "HANDOVER_ACCEPTED" if accept else "HANDOVER_REJECTED", "sample", sample.sample_no,
               step=step.name, sender=a.created_by.display_name(), reason=reason)
        notify_all(
            [a.created_by, a.from_user], "HANDOVER_ACCEPTED" if accept else "HANDOVER_DECLINED",
            f"{by.display_name()} {'accepted' if accept else 'declined'} “{step.name}” of {sample.sample_no}",
            body=_quoted(reason) if reason else ("The work is now theirs." if accept else ""),
            sample=sample, actor=by,
        )
    return a


def cancel(assignment: Assignment, by, reason: str = "") -> Assignment:
    with transaction.atomic():
        sample = _lock(assignment.sample)
        a = Assignment.objects.select_for_update().get(pk=assignment.pk)
        if a.status != AssignmentStatus.PENDING:
            raise ExecutionError("Only a handover still waiting for an answer can be cancelled.")
        if a.created_by_id != by.id and not has_perm(by, "sample.assign"):
            raise ExecutionError("Only the person who sent it, or someone who assigns work, can cancel it.")
        a.status = AssignmentStatus.CANCELLED
        a.responded_by = by
        a.responded_at = timezone.now()
        a.response_reason = (reason or "").strip()[:1000]
        a.save()
        step = step_of(sample, a.step)
        record(by, "HANDOVER_CANCELLED", "sample", sample.sample_no, step=step.name,
               to=a.to_user.display_name())
        notify(a.to_user, "HANDOVER_CANCELLED", f"The handover of “{step.name}” of {sample.sample_no} was cancelled",
               body=" ".join(filter(None, [f"By {by.display_name()}.", _quoted(a.response_reason)])),
               sample=sample, actor=by)
    return a


# --- holds ---------------------------------------------------------------

def _working_on(sample) -> list:
    """The people a hold affects: the analyst, and whoever holds the current step."""
    people = [sample.assigned_analyst]
    key = current_step_key(sample)
    if key:
        people.append(holder(sample, step_of(sample, key)))
    return people


def place_hold(sample, by, reason: str) -> SampleHold:
    _require_perm(by, "sample.hold", sample, "You do not have permission to put samples on hold.")
    reason = _required_text(reason, "Say why work is stopping — everyone on the sample will see it.")
    with transaction.atomic():
        sample = _lock(sample)
        if sample.status in FINISHED:
            raise ExecutionError("This sample is finished — a finished sample cannot be put on hold.")
        existing = active_hold(sample)
        if existing is not None:
            raise ExecutionError(f"Already on hold since {stamp(existing.placed_at)}.")
        hold = SampleHold.objects.create(
            sample=sample, step=current_step_key(sample) or "", reason=reason, placed_by=by
        )
        WorkflowEvent.objects.create(sample=sample, actor=by, from_status=sample.status,
                                     to_status=sample.status, comment=f"Put on hold: {reason}")
        record(by, "SAMPLE_HELD", "sample", sample.sample_no, reason=reason)
        notify_all(_working_on(sample), "ON_HOLD", f"{sample.sample_no} is on hold",
                   body=f"{_quoted(reason)} Nothing can be entered or signed until it is released.",
                   sample=sample, actor=by)
    return hold


def release_hold(sample, by, comment: str) -> SampleHold:
    _require_perm(by, "sample.hold", sample, "You do not have permission to release samples from hold.")
    comment = _required_text(comment, "Say what was resolved before work resumes.")
    with transaction.atomic():
        sample = _lock(sample)
        hold = SampleHold.objects.select_for_update().filter(sample=sample, released_at__isnull=True).first()
        if hold is None:
            raise ExecutionError("This sample is not on hold.")
        hold.released_by = by
        hold.released_at = timezone.now()
        hold.release_comment = comment
        hold.save()
        WorkflowEvent.objects.create(sample=sample, actor=by, from_status=sample.status,
                                     to_status=sample.status, comment=f"Released from hold: {comment}")
        record(by, "SAMPLE_RELEASED", "sample", sample.sample_no, comment=comment)
        notify_all(_working_on(sample), "RELEASED", f"{sample.sample_no} is released from hold",
                   body=f"{_quoted(comment)} Work can continue.", sample=sample, actor=by)
    return hold


# --- retests -------------------------------------------------------------

def _require_retest_allowed(sample, test, failed):
    """The quality unit's rules: a retest follows an investigation, and there is a limit."""
    lab_rules = LabConfig.get()
    taken = RetestRequest.objects.filter(
        sample=sample, test_definition=test,
        status__in=[RetestStatus.PENDING, RetestStatus.AUTHORIZED, RetestStatus.USED],
    ).count()
    if taken >= lab_rules.oos_max_retests:
        raise ExecutionError(
            f"{test.name} has had {taken} retest(s), the most the lab allows. "
            "The failure stands unless the investigation finds it was a laboratory error."
        )
    if not lab_rules.oos_investigation_required:
        return
    inv = Investigation.objects.filter(
        kind=InvestigationKind.OOS, sample=sample, test_definition=test
    ).order_by("-opened_at", "-id").first()
    if inv is None or (inv.closed_at is not None and inv.closed_at < failed.entered_at):
        raise ExecutionError(
            f"Open an out-of-specification investigation of {test.name} first. "
            "A retest follows the laboratory investigation, never the other way round."
        )
    if not inv.lab_finding:
        raise ExecutionError(f"Record the laboratory finding on {inv.reference} first.")
    if inv.conclusion == Conclusion.CONFIRMED:
        raise ExecutionError(f"{inv.reference} confirmed this failure, so it cannot be retested away.")


def require_second_analyst(sample, test, user):
    """Whoever produced the first failure does not get to test it away."""
    if not LabConfig.get().oos_second_analyst:
        return
    first = TestResult.objects.filter(
        sample=sample, test_definition=test, outcome=Outcome.FAIL
    ).order_by("entered_at", "id").first()
    if first is None or first.entered_by_id != user.id:
        return
    if overrides(user, "A retest is done by a second analyst."):
        return
    record(user, "RETEST_REFUSED_SAME_ANALYST", "sample", sample.sample_no, test=test.name)
    raise ExecutionError(
        "You produced the original failure, so a second analyst must do this retest. "
        "Ask whoever assigns work to hand the testing over."
    )


def request_retest(sample, test_definition_id, by, reason: str, kind: str = RetestKind.RETEST) -> RetestRequest:
    reason = _required_text(reason, "Say why a retest is justified — the person authorizing it will read this.")
    if kind not in RetestKind.values:
        raise ExecutionError("Choose a retest, a repeat analysis or a resample.")
    test = sample.specification.tests.filter(pk=test_definition_id if str(test_definition_id).isdigit() else 0).first()
    if test is None:
        raise ExecutionError("That test is not part of this sample's specification.")
    with transaction.atomic():
        sample = _lock(sample)
        require_can_work(sample, step_of(sample, TESTING), by)
        failed = TestResult.objects.select_for_update().filter(
            sample=sample, test_definition=test, is_superseded=False
        ).first()
        if failed is None or failed.outcome != Outcome.FAIL:
            raise ExecutionError(
                "Only a failed result can be retested. A passing value entered by mistake is "
                "corrected with a reason instead."
            )
        open_request = RetestRequest.objects.filter(
            failed_result=failed, status__in=[RetestStatus.PENDING, RetestStatus.AUTHORIZED]
        ).first()
        if open_request is not None:
            raise ExecutionError(f"A retest of {test.name} is already {open_request.get_status_display().lower()}.")
        _require_retest_allowed(sample, test, failed)
        req = RetestRequest.objects.create(
            sample=sample, test_definition=test, failed_result=failed, kind=kind, reason=reason, requested_by=by
        )
        record(by, "RETEST_REQUESTED", "sample", sample.sample_no, test=test.name, reason=reason, kind=kind,
               failed_value=str(failed.value_numeric if failed.value_numeric is not None else failed.value_text))
        # Only the people who may decide it — never the analyst or whoever entered the failure.
        conflicted = {by.id, failed.entered_by_id, sample.assigned_analyst_id}
        notify_all(
            [u for u in users_with("result.retest.authorize") if u.id not in conflicted],
            "RETEST_REQUESTED", f"Retest requested: {test.name} on {sample.sample_no}",
            body=f"Asked by {by.display_name()}: {_quoted(reason)}", link="/tasks#retests_to_decide",
            sample=sample, actor=by,
        )
    return req


def _independent(req: RetestRequest, by) -> bool:
    involved = {req.requested_by_id, req.failed_result.entered_by_id, req.sample.assigned_analyst_id}
    return by.id not in involved or overrides(by, "A retest is decided by someone independent of the work.")


def decide_retest(req: RetestRequest, by, authorize: bool, comment: str = "") -> RetestRequest:
    _require_perm(by, "result.retest.authorize", req.sample, "You do not have permission to authorize retests.")
    comment = (comment or "").strip()[:1000]
    if not authorize and not comment:
        raise ExecutionError("Say why the retest is declined — the analyst will read this.")
    if not _independent(req, by):
        record(by, "RETEST_REFUSED_NOT_INDEPENDENT", "sample", req.sample.sample_no, test=req.test_definition.name)
        raise ExecutionError(
            "You cannot decide a retest of work you did or asked for — someone independent must. "
            "This attempt has been recorded."
        )
    with transaction.atomic():
        sample = _lock(req.sample)
        req = RetestRequest.objects.select_for_update().get(pk=req.pk)
        if active_hold(sample) is not None:
            raise ExecutionError(f"{sample.sample_no} is on hold: nothing is decided until it is released.")
        if req.status != RetestStatus.PENDING:
            raise ExecutionError("This retest request has already been decided.")
        if not _independent(req, by):
            raise ExecutionError("You cannot decide a retest of work you did or asked for.")
        req.status = RetestStatus.AUTHORIZED if authorize else RetestStatus.DECLINED
        req.decided_by = by
        req.decided_at = timezone.now()
        req.decision_comment = comment
        req.save()
        record(by, "RETEST_AUTHORIZED" if authorize else "RETEST_DECLINED", "sample", sample.sample_no,
               test=req.test_definition.name, comment=comment, analyst=req.requested_by.display_name())
        notify(req.requested_by, "RETEST_AUTHORIZED" if authorize else "RETEST_DECLINED",
               f"Retest of {req.test_definition.name} on {sample.sample_no} "
               + ("authorized — you can enter it now" if authorize else "declined"),
               body=" ".join(filter(None, [f"By {by.display_name()}.", _quoted(comment)])),
               sample=sample, actor=by)
    return req


def authorized_retest_for(failed_result):
    """The authorized, unused retest that allows a new result after this failed one — or None."""
    return (
        RetestRequest.objects.select_for_update(of=("self",))
        .filter(failed_result=failed_result, status=RetestStatus.AUTHORIZED)
        .select_related("decided_by").first()
    )


def mark_retest_used(req: RetestRequest, new_result, by):
    req.status = RetestStatus.USED
    req.retest_result = new_result
    req.used_at = timezone.now()
    req.save()
    record(by, "RETEST_ENTERED", "sample", req.sample.sample_no, test=req.test_definition.name,
           value=str(new_result.value_numeric if new_result.value_numeric is not None else new_result.value_text),
           outcome=new_result.outcome)


# --- waivers -------------------------------------------------------------

def waive(sample, item_id, by, reason: str) -> Waiver:
    _require_perm(by, "stage.waive", sample, "You do not have permission to waive stage requirements.")
    item = _item_of(sample, item_id)
    step = step_of(sample, item.step)
    if not item.waivable:
        raise ExecutionError(f"“{item.label}” cannot be waived — its workflow does not allow it.")
    reason = _required_text(reason, "Say why this requirement can be set aside.")
    with transaction.atomic():
        sample = _lock(sample)
        if current_step_key(sample) != step.key:
            raise ExecutionError("Only a requirement of the step in progress can be waived.")
        hold = active_hold(sample)
        if hold is not None:
            raise ExecutionError("The sample is on hold — release it before waiving anything.")
        if step.is_testing and by.id == sample.assigned_analyst_id and not overrides(
            by, "A requirement of someone's own testing is waived by someone independent."
        ):
            raise ExecutionError("You cannot waive a requirement of your own testing — someone independent must.")
        who = holder(sample, step)
        if not step.is_testing and who is not None and who.id == by.id and not overrides(
            by, "A stage's requirements are waived by someone other than the person holding it."
        ):
            raise ExecutionError("You hold this stage, so someone else must waive its requirements.")
        attempt = attempt_for(sample, step)
        if Waiver.objects.filter(sample=sample, item=item, attempt=attempt).exists():
            raise ExecutionError(f"“{item.label}” is already waived for this attempt.")
        w = Waiver.objects.create(sample=sample, item=item, attempt=attempt, reason=reason, waived_by=by)
        record(by, "REQUIREMENT_WAIVED", "sample", sample.sample_no, step=step.name, item=item.label,
               reason=reason, attempt=attempt)
    return w
