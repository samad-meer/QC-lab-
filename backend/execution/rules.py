"""
The lab-execution rules: the steps of a sample, who holds each one, and
what stops a step being worked on or completed.

Screens and services read the same functions — a blocker shown on screen
is exactly the check the server makes before it lets anything through.
"""
from dataclasses import dataclass

from django.utils import timezone

from accounts.authz import OVERRIDE, has_perm, overrides
from accounts.lab_zone import clock
from lims.models import FINISHED, Outcome, SampleStatus
from lims.workflow import may_sign_stage
from quality.gates import release_blockers
from .models import (
    RECEIPT,
    TESTING,
    Assignment,
    AssignmentStatus,
    ChecklistItem,
    ChecklistResponse,
    ReceiptCompletion,
    ResponseType,
    SampleHold,
    Waiver,
)


class ExecutionError(Exception):
    """A refused lab-execution action. The message is written for the person who tried."""


def stamp(dt) -> str:
    """The exact local date and time, as every message prints it."""
    return timezone.localtime(dt).strftime(f"%d %b %Y, {clock()}")


@dataclass(frozen=True, eq=False)
class Step:
    key: str
    name: str
    order: int  # -1 = receipt checks; 0 = the analyst's testing step; 1… = review stages
    stage: object | None  # the lims.WorkflowStage, or None for receipt and testing
    requires_acceptance: bool

    @property
    def is_receipt(self) -> bool:
        return self.key == RECEIPT

    @property
    def is_testing(self) -> bool:
        return self.key == TESTING

    @property
    def verb(self) -> str:
        """What finishing this step is called."""
        return "completed" if self.is_receipt else "signed"


@dataclass
class Blocker:
    code: str
    message: str
    item_id: int | None = None
    waivable: bool = False


# --- the journey -------------------------------------------------------

def has_receipt_checks(version) -> bool:
    return ChecklistItem.objects.filter(version=version, stage__isnull=True, for_receipt=True).exists()


def steps(sample) -> list[Step]:
    version = sample.workflow_version
    out = []
    if has_receipt_checks(version):
        out.append(Step(RECEIPT, "Receipt checks", -1, None, False))
    out.append(Step(TESTING, "Tested", 0, None, version.testing_requires_acceptance))
    for stage in version.stages.select_related("role"):
        out.append(Step(stage.code, stage.name, stage.order, stage, stage.requires_acceptance))
    return out


def step_of(sample, key: str) -> Step:
    for step in steps(sample):
        if step.key == key:
            return step
    raise ExecutionError("That step is not part of this sample's workflow.")


def receipt_completion(sample):
    return ReceiptCompletion.objects.filter(sample=sample).select_related("completed_by").first()


def receipt_open(sample) -> bool:
    """Checks to make on arrival, not yet completed — testing waits for them."""
    return (
        sample.status == SampleStatus.RECEIVED
        and has_receipt_checks(sample.workflow_version)
        and not ReceiptCompletion.objects.filter(sample=sample).exists()
    )


def current_step_key(sample) -> str | None:
    if sample.status in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING):
        return RECEIPT if receipt_open(sample) else TESTING
    if sample.status == SampleStatus.IN_REVIEW and sample.review_stage_id:
        return sample.review_stage.code
    return None


def attempt_of(sample) -> int:
    """The certificate version the current work is for (see models docstring)."""
    from certificates.models import CertStatus

    latest = sample.certificates.order_by("-version").first()
    if latest is None:
        return 1
    return latest.version + 1 if latest.status == CertStatus.SUPERSEDED else latest.version


def attempt_for(sample, step: Step) -> int:
    """Receipt checks are made once, on arrival; every other step follows the attempt."""
    return 1 if step.is_receipt else attempt_of(sample)


def live_certificate(sample):
    from certificates.models import CertStatus

    return sample.certificates.exclude(status=CertStatus.SUPERSEDED).order_by("-version").first()


def active_hold(sample):
    return SampleHold.objects.filter(sample=sample, released_at__isnull=True).select_related("placed_by").first()


# --- who holds a step --------------------------------------------------

def holder(sample, step: Step):
    """The person on the latest accepted assignment — or, for a review stage, nobody yet."""
    latest = (
        Assignment.objects.filter(sample=sample, step=step.key, status=AssignmentStatus.ACCEPTED)
        .select_related("to_user")
        .order_by("-responded_at", "-id")
        .first()
    )
    if latest is not None:
        return latest.to_user
    if step.is_testing and not Assignment.objects.filter(sample=sample, step=TESTING).exists():
        # Registered before assignments were recorded.
        return sample.assigned_analyst
    return None


def pending(sample, step: Step):
    return (
        Assignment.objects.filter(sample=sample, step=step.key, status=AssignmentStatus.PENDING)
        .select_related("to_user", "from_user", "created_by")
        .first()
    )


# --- checklist ---------------------------------------------------------

def item_filter(sample, step: Step, prefix: str = "") -> dict:
    """The checklist items of one step of this sample, as queryset filters."""
    f = {"version_id": sample.workflow_version_id}
    if step.stage is not None:
        f["stage"] = step.stage
    else:
        f.update(stage__isnull=True, for_receipt=step.is_receipt)
    return {prefix + k: v for k, v in f.items()}


def items(sample, step: Step) -> list[ChecklistItem]:
    return list(ChecklistItem.objects.filter(**item_filter(sample, step)).order_by("order"))


def current_responses(sample, step: Step, attempt: int) -> dict[int, ChecklistResponse]:
    rows = ChecklistResponse.objects.filter(
        sample=sample, attempt=attempt, replaced_at__isnull=True, **item_filter(sample, step, "item__"),
    ).select_related("answered_by", "attachment")
    return {r.item_id: r for r in rows}


def waivers(sample, step: Step, attempt: int) -> dict[int, Waiver]:
    rows = Waiver.objects.filter(
        sample=sample, attempt=attempt, **item_filter(sample, step, "item__"),
    ).select_related("waived_by")
    return {w.item_id: w for w in rows}


def display_answer(item: ChecklistItem, response: ChecklistResponse) -> str:
    if item.response_type == ResponseType.CHECKBOX:
        return "Confirmed"
    if item.response_type == ResponseType.YES_NO:
        return "Yes" if response.value == "YES" else "No"
    if item.response_type == ResponseType.PASS_FAIL:
        return "Pass" if response.value == "PASS" else "Fail"
    if item.response_type == ResponseType.NUMBER:
        return f"{response.value} {item.unit}".strip()
    if item.response_type == ResponseType.FILE:
        return response.attachment.original_name if response.attachment_id else "—"
    return response.value


def requirement_text(item: ChecklistItem) -> str:
    """What a conforming answer is, in words — for blockers and screens."""
    t = item.response_type
    if t == ResponseType.PASS_FAIL:
        return "Pass"
    if t in (ResponseType.YES_NO, ResponseType.CHOICE) and item.expected:
        return {"YES": "Yes", "NO": "No"}.get(item.expected, item.expected) if t == ResponseType.YES_NO else item.expected
    if t == ResponseType.NUMBER:
        unit = f" {item.unit}" if item.unit else ""
        if item.min_value is not None and item.max_value is not None:
            return f"{item.min_value.normalize():f} – {item.max_value.normalize():f}{unit}"
        if item.min_value is not None:
            return f"not less than {item.min_value.normalize():f}{unit}"
        if item.max_value is not None:
            return f"not more than {item.max_value.normalize():f}{unit}"
    return ""


# --- blockers ----------------------------------------------------------

def hold_blocker(sample) -> Blocker | None:
    hold = active_hold(sample)
    if hold is None:
        return None
    return Blocker(
        "ON_HOLD",
        f"On hold since {stamp(hold.placed_at)} by {hold.placed_by.display_name()}: “{hold.reason}”. "
        "Nothing can be entered or signed until it is released.",
    )


def _not_open(sample, step: Step) -> str:
    current = current_step_key(sample)
    if step.is_receipt:
        done = receipt_completion(sample)
        if done is not None:
            return (f"The receipt checks were completed on {stamp(done.completed_at)} "
                    f"by {done.completed_by.display_name()}.")
        return "The receipt checks are closed — testing has already started."
    if sample.status == SampleStatus.APPROVED:
        return "The certificate has been released — no step is open any more."
    if sample.status in FINISHED:
        return f"This sample was {sample.get_status_display().lower()} — no step is open any more."
    if step.is_testing:
        if current == RECEIPT:
            return "Testing cannot start until the front desk completes the receipt checks."
        return "Testing is finished for this attempt — the analyst has signed."
    if current in (RECEIPT, TESTING):
        return f"“{step.name}” has not started — the sample is still in testing."
    if sample.review_stage_id and step.order < sample.review_stage.order:
        return f"“{step.name}” is already signed for this attempt."
    return f"“{step.name}” has not started — the certificate is waiting at “{sample.review_stage.name}”."


# Blockers about WHO is working, which the administrator override passes.
# The others are about the sample itself and stop everyone: a hold is released
# with a reason, and a closed step opens only when the work reaches it.
PERSONAL = {
    "NOT_YOUR_ROLE", "NOT_YOURS", "DECLINED", "ACCEPT_FIRST", "ASSIGNED_TO_OTHER",
    "AWAITING_ACCEPTANCE", "TAKE_FIRST",
}


def work_blockers(sample, step: Step, user) -> list[Blocker]:
    """What stops this user working at this step right now."""
    blockers = _blockers_for(sample, step, user)
    if has_perm(user, OVERRIDE):
        return [b for b in blockers if b.code not in PERSONAL]
    return blockers


def overridden_blockers(sample, step: Step, user) -> list[Blocker]:
    """What would stop this user here, were they not acting on the administrator override."""
    if not has_perm(user, OVERRIDE):
        return []
    return [b for b in _blockers_for(sample, step, user) if b.code in PERSONAL]


def _blockers_for(sample, step: Step, user) -> list[Blocker]:
    out = []
    hold = hold_blocker(sample)
    if hold:
        out.append(hold)
    if current_step_key(sample) != step.key:
        out.append(Blocker("NOT_OPEN", _not_open(sample, step)))
        return out

    if step.is_receipt:
        if not has_perm(user, "sample.register"):
            out.append(Blocker(
                "NOT_YOUR_ROLE", "Receipt checks are made by the people who register samples (the front desk).",
            ))
        return out

    who = holder(sample, step)
    waiting = pending(sample, step)
    if step.is_testing:
        if who is not None and who.id == user.id:
            pass
        elif waiting is not None and waiting.to_user_id == user.id:
            out.append(Blocker(
                "ACCEPT_FIRST",
                "This sample has been handed to you. Accept it first — confirming you have received it.",
            ))
        elif who is None and sample.assigned_analyst_id == user.id:
            out.append(Blocker("DECLINED", "You declined this sample. It is waiting to be reassigned."))
        else:
            name = (who or sample.assigned_analyst).display_name()
            out.append(Blocker("NOT_YOURS", f"Testing is held by {name}. Only they can work on it."))
        return out

    stage = step.stage
    if not may_sign_stage(user, stage):
        out.append(Blocker("NOT_YOUR_ROLE", f"Only someone in the {stage.role.name} role can work at “{stage.name}”."))
    elif who is not None and who.id != user.id:
        out.append(Blocker(
            "ASSIGNED_TO_OTHER",
            f"“{stage.name}” is assigned to {who.display_name()}. "
            "Ask them to hand it over, or ask a supervisor to reassign it.",
        ))
    elif who is None and step.requires_acceptance:
        if waiting is not None and waiting.to_user_id == user.id:
            out.append(Blocker("ACCEPT_FIRST", f"“{stage.name}” has been handed to you — accept it before working on it."))
        elif waiting is not None:
            out.append(Blocker(
                "AWAITING_ACCEPTANCE",
                f"“{stage.name}” has been handed to {waiting.to_user.display_name()} — waiting for them to accept.",
            ))
        else:
            out.append(Blocker("TAKE_FIRST", f"“{stage.name}” must be taken before anyone works on it — choose “Take this stage”."))
    return out


def completion_blockers(sample, step: Step, attempt: int) -> list[Blocker]:
    """What stops the step being signed, whoever signs it."""
    out = []
    answers = current_responses(sample, step, attempt)
    waived = waivers(sample, step, attempt)
    for item in items(sample, step):
        if item.id in waived:
            continue
        response = answers.get(item.id)
        if response is None:
            if item.required:
                verb = "attached" if item.response_type == ResponseType.FILE else "answered"
                out.append(Blocker("CHECK_MISSING", f"“{item.label}” has not been {verb}.", item.id, item.waivable))
        elif not response.conforms:
            need = requirement_text(item)
            if step.is_receipt:
                fix = (" Correct it, or have it waived." if item.waivable
                       else " Correct it, or put the sample on hold until it is resolved with the sender.")
            else:
                fix = (" Correct it, send the work back, or have it waived." if item.waivable
                       else " Correct it or send the work back.")
            out.append(Blocker(
                "CHECK_NONCONFORMING",
                f"“{item.label}” is “{display_answer(item, response)}”"
                + (f" — the requirement is {need}." if need else " — that does not meet the requirement.")
                + fix,
                item.id, item.waivable,
            ))

    if step.is_testing:
        current = list(sample.current_results())
        entered = {r.test_definition_id for r in current}
        missing = sample.specification.tests.exclude(pk__in=entered).count()
        if missing:
            out.append(Blocker("TESTS_MISSING", f"{missing} test(s) still have no result."))
        failed = [r.test_definition.name for r in current if r.outcome == Outcome.FAIL]
        if failed:
            out.append(Blocker(
                "RESULT_FAILED",
                f"A result is out of specification: {', '.join(failed)}. A failed result is never replaced "
                "directly — investigate it, then request a retest; once someone else authorizes it, enter the "
                "retest.",
            ))
    if not step.is_receipt:
        out += [Blocker("QUALITY_OPEN", message) for message in release_blockers(sample)]
    return out


def waived_by(sample, step: Step, attempt: int, user) -> bool:
    return Waiver.objects.filter(
        sample=sample, attempt=attempt, waived_by=user, **item_filter(sample, step, "item__"),
    ).exists()


def _note_overridden(sample, step: Step, user):
    for blocker in overridden_blockers(sample, step, user):
        overrides(user, blocker.message)


def require_can_work(sample, step: Step, user):
    blockers = work_blockers(sample, step, user)
    if blockers:
        raise ExecutionError(blockers[0].message)
    _note_overridden(sample, step, user)


def require_can_complete(sample, step: Step, user, attempt: int, audit: bool = True):
    """
    Everything a signature at this step needs beyond the signing rules
    themselves. Call once before the transaction (audit=True records the
    refusal) and again under the row lock (audit=False) to close the race.
    """
    from audit.services import record

    _note_overridden(sample, step, user)
    blockers = work_blockers(sample, step, user) + completion_blockers(sample, step, attempt)
    if blockers:
        if audit:
            record(user, "RECEIPT_REFUSED_BLOCKED" if step.is_receipt else "SIGN_REFUSED_BLOCKED",
                   "sample", sample.sample_no, step=step.name, reasons=[b.message for b in blockers])
        if len(blockers) == 1:
            raise ExecutionError(blockers[0].message)
        raise ExecutionError(
            f"“{step.name}” cannot be {step.verb} yet — {len(blockers)} things are outstanding: "
            + " ".join(f"({i}) {b.message}" for i, b in enumerate(blockers, start=1))
        )
    if (
        not step.is_testing and waived_by(sample, step, attempt, user)
        and not overrides(user, "A waiver and the signature it lets through never come from the same person.")
    ):
        if audit:
            record(user, "SIGN_REFUSED_WAIVER", "sample", sample.sample_no, step=step.name)
        if step.is_receipt:
            raise ExecutionError(
                "You waived one of the receipt checks, so someone else must complete them. "
                "A waiver and the completion it lets through never come from the same person."
            )
        raise ExecutionError(
            "You waived a requirement at this stage, so someone else must sign it. "
            "A waiver and the signature it lets through never come from the same person."
        )


# --- the state of each step ---------------------------------------------

STATUS_LABELS = {
    "NOT_STARTED": "Not started",
    "WAITING": "Waiting for receipt checks",
    "COMPLETED": "Completed",
    "AWAITING_ACCEPTANCE": "Awaiting acceptance",
    "DECLINED": "Declined — needs reassigning",
    "IN_PROGRESS": "In progress",
    "REOPENED": "Reopened",
    "FAILED": "Failed — retest needed",
    "ON_HOLD": "On hold",
    "SUBMITTED": "Submitted",
    "PASSED": "Passed",
    "RETURNED": "Returned",
}


def step_status(sample, step: Step, attempt: int) -> str:
    current = current_step_key(sample)
    is_current = current == step.key
    if is_current and active_hold(sample) is not None:
        return "ON_HOLD"

    if step.is_receipt:
        if receipt_completion(sample) is not None:
            return "COMPLETED"
        if is_current and current_responses(sample, step, attempt):
            return "IN_PROGRESS"
        return "NOT_STARTED"

    if step.is_testing:
        if sample.status not in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING):
            return "SUBMITTED"
        who = holder(sample, step)
        if who is None:
            return "AWAITING_ACCEPTANCE" if pending(sample, step) else "DECLINED"
        if not is_current:
            return "WAITING"
        results = list(sample.current_results())
        if any(r.outcome == Outcome.FAIL for r in results):
            return "FAILED"
        if attempt > 1:
            return "REOPENED"
        if results or current_responses(sample, step, attempt):
            return "IN_PROGRESS"
        return "NOT_STARTED"

    cert = live_certificate(sample)
    if cert is not None and cert.version == attempt and cert.signatures.filter(meaning=step.key).exists():
        return "PASSED"
    if is_current:
        if holder(sample, step) is None and (step.requires_acceptance or pending(sample, step)):
            return "AWAITING_ACCEPTANCE"
        return "IN_PROGRESS"
    return "NOT_STARTED"
