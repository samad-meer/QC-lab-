"""
Opening, working on and closing an investigation. Every rule lives here, and
every change goes on the investigation's own history and the audit trail.

The closure rules follow the ones for certificates: a signature is the
person's password re-entered at that moment, and whoever approves a closure
is independent of the work. Only the administrator override passes that, and
the audit row says so.
"""
import hashlib
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.authz import OVERRIDE, has_perm, overrides
from accounts.models import LabConfig, User
from accounts.passwords import confirm_password
from audit.services import record
from execution.rules import active_hold
from lims.models import (
    FINISHED, Outcome, Product, Sample, SampleStatus, TestResult, UNSIGNED, WorkflowEvent,
)
from lims.workflow import samples_visible_to
from notifications.services import notify, notify_all, users_with
from .gates import settling_investigation
from .models import (
    CapaAction,
    CapaKind,
    Classification,
    Conclusion,
    Investigation,
    InvestigationCounter,
    InvestigationEvent,
    InvestigationKind,
    InvestigationStatus,
    LabFinding,
)

MANAGE = "investigation.manage"
APPROVE = "investigation.approve"

# What can be changed while it is open, and what each is called on the record.
EDITABLE = {
    "description": "Description",
    "classification": "Classification",
    "root_cause": "Root cause",
    "outcome": "Final outcome",
    "conclusion": "Conclusion",
    "responsible_id": "Responsible",
    "due_date": "Due date",
}


# What an approver does to a closure is not work on the investigation.
SENDING_BACK = ("Sent back for more work", "Closure approved")


class QualityError(Exception):
    """A refused action. The message is written for the person who tried."""


def visible_investigations(user):
    """Whoever sees every sample sees every investigation; others, the ones they have a part in."""
    qs = Investigation.objects.select_related(
        "sample__product", "product", "test_definition", "responsible", "opened_by", "closed_by", "submitted_by",
        "result__entered_by",
    )
    if has_perm(user, "sample.view.all") or has_perm(user, MANAGE) or has_perm(user, APPROVE):
        return qs
    return qs.filter(
        Q(sample__in=samples_visible_to(user).values("pk"))
        | Q(responsible=user) | Q(opened_by=user) | Q(actions__owner=user)
    ).distinct()


def _id(value) -> int:
    return int(value) if str(value).isdigit() else 0


def _text(value, message: str, limit: int = 4000) -> str:
    text = (value or "").strip()
    if not text:
        raise QualityError(message)
    return text[:limit]


def _date(value, message: str) -> date:
    try:
        parsed = parse_date(str(value or ""))
    except ValueError:  # the right shape, but no such date: 31 February
        parsed = None
    if parsed is None:
        raise QualityError(message)
    return parsed


def _person(value, message: str) -> User:
    user = User.objects.filter(pk=_id(value), is_active=True).first()
    if user is None:
        raise QualityError(message)
    return user


def _shown(field: str, value) -> str:
    if value in (None, ""):
        return ""
    if field == "classification":
        return Classification(value).label
    if field == "conclusion":
        return Conclusion(value).label
    if field == "responsible_id":
        return User.objects.get(pk=value).display_name()
    return str(value)


def _next_reference() -> str:
    year = timezone.localdate().year
    InvestigationCounter.objects.get_or_create(year=year)
    counter = InvestigationCounter.objects.select_for_update().get(year=year)
    counter.last_no += 1
    counter.save()
    return f"INV-{year}-{counter.last_no:04d}"


def _event(inv, by, what: str, changes=None, comment: str = ""):
    InvestigationEvent.objects.create(
        investigation=inv, actor=by, what=what, changes=changes or [], comment=comment[:1000]
    )


def _require(by, permission: str, inv: Investigation | None, message: str):
    if not has_perm(by, permission):
        record(by, "ACCESS_REFUSED", "investigation", inv.reference if inv else "new investigation", reason=message)
        raise QualityError(message)


def _require_open(inv: Investigation):
    if inv.status != InvestigationStatus.OPEN:
        raise QualityError(f"This investigation is {inv.get_status_display().lower()}, so it cannot be changed.")


def _require_pending(inv: Investigation):
    if inv.status != InvestigationStatus.PENDING_CLOSURE:
        raise QualityError("This investigation is not waiting for closure approval.")


def _lock(inv: Investigation) -> Investigation:
    return Investigation.objects.select_for_update().get(pk=inv.pk)


def involved_in(inv: Investigation) -> set[int]:
    """
    Everyone whose work a closure would be approving: anyone who wrote on it, was
    responsible for it or owned an action, as well as whoever did the testing.
    Deciding a retest is not on the list: that is a quality decision, and in most
    labs the same person also approves closures.
    """
    people = {inv.opened_by_id, inv.responsible_id, inv.submitted_by_id, inv.lab_finding_by_id}
    people |= set(inv.events.exclude(what__in=SENDING_BACK).values_list("actor_id", flat=True))
    for owner, completed_by in inv.actions.values_list("owner_id", "completed_by_id"):
        people |= {owner, completed_by}
    if inv.result_id:
        people.add(inv.result.entered_by_id)
    if inv.sample_id:
        people.add(inv.sample.assigned_analyst_id)
    return {p for p in people if p}


def _subject(by, data: dict, kind: str) -> dict:
    """What the record concerns, resolved against what this person can see."""
    visible = samples_visible_to(by).values("pk")
    sample = result = test = product = None
    batch_no = (data.get("batch_no") or "").strip()[:60]
    if data.get("result_id"):
        result = TestResult.objects.select_related("sample__product", "test_definition").filter(
            pk=_id(data["result_id"]), sample__in=visible
        ).first()
        if result is None:
            raise QualityError("That result is not one you can see.")
        sample, test = result.sample, result.test_definition
    elif data.get("sample_id"):
        sample = samples_visible_to(by).filter(pk=_id(data["sample_id"])).first()
        if sample is None:
            raise QualityError("That sample is not one you can see.")
    if sample is not None:
        product, batch_no = sample.product, sample.batch_no
    elif data.get("product_id"):
        product = Product.objects.filter(pk=_id(data["product_id"])).first()
        if product is None:
            raise QualityError("That product does not exist.")

    if kind == InvestigationKind.OOS and (result is None or result.outcome != Outcome.FAIL):
        raise QualityError("An out-of-specification investigation starts from a failed result.")
    if kind == InvestigationKind.OOT and result is None:
        raise QualityError("An out-of-trend investigation starts from a result.")
    return {"sample": sample, "result": result, "test_definition": test, "product": product, "batch_no": batch_no}


def open_investigation(by, data: dict) -> Investigation:
    _require(by, MANAGE, None, "You do not have permission to open investigations.")
    kind = data.get("kind")
    if kind not in InvestigationKind.values:
        raise QualityError("Choose what kind of record this is.")
    classification = data.get("classification") or ""
    if classification not in ["", *Classification.values]:
        raise QualityError("Choose minor, major or critical.")
    description = _text(data.get("description"), "Describe what happened.")
    responsible = _person(data.get("responsible_id"), "Choose who is responsible.")
    due_date = _date(data.get("due_date"), "Enter the date this is due.")
    subject = _subject(by, data, kind)
    sample, test = subject["sample"], subject["test_definition"]

    with transaction.atomic():
        if sample is not None:
            Sample.objects.select_for_update().get(pk=sample.pk)  # one at a time, per sample
        if kind == InvestigationKind.OOS and Investigation.objects.filter(
            kind=kind, sample=sample, test_definition=test
        ).exclude(status=InvestigationStatus.CLOSED).exists():
            raise QualityError(f"{test.name} on {sample.sample_no} already has an open investigation.")
        inv = Investigation.objects.create(
            reference=_next_reference(), kind=kind, classification=classification,
            description=description, responsible=responsible, due_date=due_date, opened_by=by, **subject,
        )
        _event(inv, by, "Opened", comment=f"Responsible: {responsible.display_name()}")
        record(by, "INVESTIGATION_OPENED", "investigation", inv.reference,
               kind=inv.get_kind_display(), sample=sample.sample_no if sample else "",
               batch=inv.batch_no, test=test.name if test else "", responsible=responsible.username)
        notify(responsible, "INVESTIGATION", f"{inv.reference} is yours to investigate",
               body=description[:300], link=f"/investigations/{inv.id}", sample=sample, actor=by)
    return inv


def _clean(field: str, value):
    if field == "responsible_id":
        return _person(value, "Choose who is responsible.").id
    if field == "due_date":
        return _date(value, "Enter the date this is due.")
    if field == "classification":
        if value and value not in Classification.values:
            raise QualityError("Choose minor, major or critical.")
        return value or ""
    if field == "conclusion":
        if value and value not in Conclusion.values:
            raise QualityError("Choose how the investigation concluded.")
        return value or ""
    text = (value or "").strip()[:4000]
    if field == "description" and not text:
        raise QualityError("Describe what happened.")
    return text


def update_investigation(inv: Investigation, by, data: dict, reason: str = "") -> Investigation:
    """Changing what is already written needs a reason; filling in a blank does not."""
    _require(by, MANAGE, inv, "You do not have permission to work on investigations.")
    reason = (reason or "").strip()
    with transaction.atomic():
        inv = _lock(inv)
        _require_open(inv)
        changes, overwrites = [], False
        for field, label in EDITABLE.items():
            if field not in data:
                continue
            value, old = _clean(field, data[field]), getattr(inv, field)
            if old == value:
                continue
            overwrites = overwrites or old not in (None, "")
            changes.append({"field": label, "old": _shown(field, old), "new": _shown(field, value)})
            setattr(inv, field, value)
        if not changes:
            return inv
        if overwrites and not reason:
            raise QualityError("Say why you are changing what was recorded.")
        inv.save()
        _event(inv, by, "Changed", changes, reason)
        record(by, "INVESTIGATION_CHANGED", "investigation", inv.reference,
               fields=", ".join(c["field"] for c in changes), changes=changes, reason=reason)
        if any(c["field"] == EDITABLE["responsible_id"] for c in changes):
            notify(inv.responsible, "INVESTIGATION", f"{inv.reference} is now yours to investigate",
                   link=f"/investigations/{inv.id}", sample=inv.sample, actor=by)
    return inv


def record_lab_finding(inv: Investigation, by, finding: str, notes: str, reason: str = "") -> Investigation:
    """
    The first phase of an OOS: was it the laboratory? Whoever entered the failure
    does not get to decide that about their own work.
    """
    _require(by, MANAGE, inv, "You do not have permission to work on investigations.")
    if inv.kind != InvestigationKind.OOS:
        raise QualityError("Only an out-of-specification investigation has a laboratory finding.")
    if finding not in LabFinding.values:
        raise QualityError("Choose what the laboratory investigation found.")
    notes = _text(notes, "Say what was checked and what it showed.")
    reason = (reason or "").strip()
    if inv.result.entered_by_id == by.id and not overrides(
        by, "The laboratory finding is made by someone other than the analyst who got the result."
    ):
        record(by, "ACCESS_REFUSED", "investigation", inv.reference, reason="Own result")
        raise QualityError("You entered this result, so someone else must record the laboratory finding.")
    with transaction.atomic():
        inv = _lock(inv)
        _require_open(inv)
        if inv.lab_finding and not reason:
            raise QualityError("Say why you are changing the laboratory finding.")
        changes = [
            {"field": "Laboratory finding", "old": inv.get_lab_finding_display(), "new": LabFinding(finding).label},
            {"field": "Laboratory findings", "old": inv.lab_finding_notes, "new": notes},
        ]
        inv.lab_finding = finding
        inv.lab_finding_notes = notes
        inv.lab_finding_by = by
        inv.lab_finding_at = timezone.now()
        inv.save()
        _event(inv, by, "Laboratory finding recorded", changes, reason)
        record(by, "INVESTIGATION_LAB_FINDING", "investigation", inv.reference,
               finding=LabFinding(finding).label, changes=changes, reason=reason)
    return inv


def add_action(inv: Investigation, by, data: dict) -> CapaAction:
    _require(by, MANAGE, inv, "You do not have permission to work on investigations.")
    kind = data.get("kind")
    if kind not in CapaKind.values:
        raise QualityError("Choose corrective or preventive.")
    description = _text(data.get("description"), "Describe the action.", 1000)
    owner = _person(data.get("owner_id"), "Choose who owns the action.")
    due_date = _date(data.get("due_date"), "Enter the date the action is due.")
    with transaction.atomic():
        inv = _lock(inv)
        _require_open(inv)
        action = CapaAction.objects.create(
            investigation=inv, kind=kind, description=description, owner=owner, due_date=due_date, created_by=by
        )
        _event(inv, by, f"{action.get_kind_display()} action added", comment=description)
        record(by, "CAPA_ADDED", "investigation", inv.reference, kind=action.get_kind_display().lower(),
               description=description, owner=owner.username)
        notify(owner, "INVESTIGATION", f"An action on {inv.reference} is yours",
               body=description[:300], link=f"/investigations/{inv.id}", sample=inv.sample, actor=by)
    return action


def complete_action(action: CapaAction, by, note: str) -> CapaAction:
    if action.owner_id != by.id and not has_perm(by, MANAGE):
        message = "Only the action's owner, or someone who works on investigations, can complete it."
        record(by, "ACCESS_REFUSED", "investigation", action.investigation.reference, reason=message)
        raise QualityError(message)
    note = _text(note, "Say what was done.", 1000)
    with transaction.atomic():
        inv = _lock(action.investigation)
        _require_open(inv)
        action = CapaAction.objects.select_for_update().get(pk=action.pk)
        if action.completed_at is not None:
            raise QualityError("This action has already been completed.")
        action.completed_by = by
        action.completed_at = timezone.now()
        action.completion_note = note
        action.save()
        _event(inv, by, f"{action.get_kind_display()} action completed", comment=note)
        record(by, "CAPA_COMPLETED", "investigation", inv.reference,
               kind=action.get_kind_display().lower(), description=action.description, note=note)
    return action


def verify_action(action: CapaAction, by, note: str, password: str) -> CapaAction:
    """
    A signed act: did it work? Whoever owned or completed the action does not get
    to say. The verifier counts as having worked on the investigation, so they do
    not also approve its closure.
    """
    reference = action.investigation.reference
    if not (has_perm(by, MANAGE) or has_perm(by, APPROVE)):
        message = "Only someone who works on or approves investigations can verify an action."
        record(by, "ACCESS_REFUSED", "investigation", reference, reason=message)
        raise QualityError(message)
    if action.completed_at is None:
        raise QualityError("This action has not been completed yet.")
    note = _text(note, "Say how you checked that it worked.", 1000)
    kind = action.get_kind_display().lower()
    done_by = {action.owner_id, action.completed_by_id}
    if by.id in done_by and not overrides(by, "An action is verified by someone other than whoever owned or completed it."):
        record(by, "CAPA_VERIFY_REFUSED", "investigation", reference, kind=kind)
        raise QualityError("You owned or completed this action, so someone else must verify it.")
    if not confirm_password(by, password):
        record(by, "SIGN_PASSWORD_FAILED", "investigation", reference, meaning="verification")
        raise QualityError("Password incorrect. The action was not verified.")
    with transaction.atomic():
        inv = _lock(action.investigation)
        _require_open(inv)
        action = CapaAction.objects.select_for_update().get(pk=action.pk)
        if action.verified_at is not None:
            raise QualityError("This action has already been verified.")
        action.verified_by = by
        action.verified_at = timezone.now()
        action.verification_note = note
        action.save()
        _event(inv, by, f"{action.get_kind_display()} action verified", comment=note)
        record(by, "CAPA_VERIFIED", "investigation", inv.reference, kind=kind,
               description=action.description, note=note)
    return action


def submit_for_closure(inv: Investigation, by) -> Investigation:
    _require(by, MANAGE, inv, "You do not have permission to work on investigations.")
    with transaction.atomic():
        inv = _lock(inv)
        _require_open(inv)
        missing = []
        if not inv.classification:
            missing.append("the classification")
        if not inv.root_cause:
            missing.append("the root cause (or that none was established)")
        if not inv.outcome:
            missing.append("the final outcome")
        if inv.kind == InvestigationKind.OOS:
            if not inv.lab_finding:
                missing.append("the laboratory finding")
            if not inv.conclusion:
                missing.append("the conclusion")
        if missing:
            raise QualityError(f"Record {' and '.join(missing)} before sending this for closure.")
        if inv.conclusion == Conclusion.INVALIDATED and inv.lab_finding != LabFinding.ASSIGNABLE:
            raise QualityError("A failure is only invalidated by a laboratory error, and none was found.")
        if inv.classification in (Classification.MAJOR, Classification.CRITICAL) and not inv.actions.exists():
            raise QualityError(
                f"A {inv.get_classification_display().lower()} investigation needs at least one "
                "corrective or preventive action."
            )
        still_open = inv.actions.filter(completed_at__isnull=True).count()
        if still_open:
            raise QualityError(f"{still_open} action(s) are still open. Complete them first.")
        unverified = inv.actions.filter(verified_at__isnull=True).count()
        if unverified:
            raise QualityError(
                f"{unverified} completed action(s) have not been verified. Someone other than the owner, "
                "and whoever completed them, must verify them first."
            )
        inv.status = InvestigationStatus.PENDING_CLOSURE
        inv.submitted_by = by
        inv.submitted_at = timezone.now()
        inv.save()
        _event(inv, by, "Sent for closure approval")
        record(by, "INVESTIGATION_SUBMITTED", "investigation", inv.reference)
        involved = involved_in(inv)
        notify_all(
            [u for u in users_with(APPROVE) if u.id not in involved], "INVESTIGATION",
            f"{inv.reference} is waiting for closure approval",
            link=f"/investigations/{inv.id}", sample=inv.sample, actor=by,
        )
    return inv


def return_investigation(inv: Investigation, by, comment: str) -> Investigation:
    _require(by, APPROVE, inv, "You do not have permission to approve closures.")
    comment = _text(comment, "Say what still needs doing.", 1000)
    with transaction.atomic():
        inv = _lock(inv)
        _require_pending(inv)
        inv.status = InvestigationStatus.OPEN
        inv.submitted_by = None
        inv.submitted_at = None
        inv.save()
        _event(inv, by, "Sent back for more work", comment=comment)
        record(by, "INVESTIGATION_RETURNED", "investigation", inv.reference, comment=comment)
        notify(inv.responsible, "INVESTIGATION", f"{inv.reference} was sent back to you",
               body=comment, link=f"/investigations/{inv.id}", sample=inv.sample, actor=by)
    return inv


def _digest(inv: Investigation) -> str:
    fields = [inv.reference, inv.classification, inv.description, inv.root_cause, inv.outcome, inv.lab_finding,
              inv.lab_finding_notes, inv.conclusion, inv.closed_by_id]
    return hashlib.sha256("|".join(str(f) for f in fields).encode("utf-8")).hexdigest()


def close_investigation(inv: Investigation, by, password: str) -> Investigation:
    _require(by, APPROVE, inv, "You do not have permission to approve closures.")
    _require_pending(inv)
    if by.id in involved_in(inv) and not overrides(
        by, "An investigation is closed by someone independent of the work."
    ):
        record(by, "INVESTIGATION_CLOSE_REFUSED", "investigation", inv.reference)
        raise QualityError(
            "You cannot approve the closure of work you did or were responsible for — someone independent "
            "must. This attempt has been recorded."
        )
    if not confirm_password(by, password):
        record(by, "SIGN_PASSWORD_FAILED", "investigation", inv.reference, meaning="closure")
        raise QualityError("Password incorrect. Closure refused.")
    with transaction.atomic():
        inv = _lock(inv)
        _require_pending(inv)
        if by.id in involved_in(inv) and not has_perm(by, OVERRIDE):
            raise QualityError("You cannot approve the closure of work you did or were responsible for.")
        # Sent for closure before verification existed.
        if inv.actions.filter(verified_at__isnull=True).exists():
            raise QualityError("An action on this investigation has not been verified. Send it back first.")
        inv.status = InvestigationStatus.CLOSED
        inv.closed_by = by
        inv.closed_at = timezone.now()
        inv.closure_digest = _digest(inv)
        inv.save()
        _event(inv, by, "Closure approved")
        record(by, "INVESTIGATION_CLOSED", "investigation", inv.reference, outcome=inv.outcome[:300])
        notify(inv.responsible, "INVESTIGATION", f"{inv.reference} was closed",
               link=f"/investigations/{inv.id}", sample=inv.sample, actor=by)
    return inv


# --- ending a sample --------------------------------------------------------

def _require_rejectable(sample):
    failed = [r for r in sample.current_results() if r.outcome == Outcome.FAIL]
    if not failed:
        raise QualityError("Only a sample with a failed result can be rejected.")
    if not LabConfig.get().oos_investigation_required:
        return
    for result in failed:
        settled = settling_investigation(sample, result.test_definition_id, result.entered_at)
        if settled is None or settled.conclusion != Conclusion.CONFIRMED:
            raise QualityError(
                f"{result.test_definition.name} needs a closed investigation confirming the failure "
                "before the sample can be rejected."
            )


def _require_cancellable(sample):
    if sample.results.filter(outcome=Outcome.FAIL).exists():
        raise QualityError(
            "A sample with a failed result cannot be cancelled. It stays until the failure is "
            "investigated, and is rejected if the failure is confirmed."
        )
    if sample.investigations.exclude(status=InvestigationStatus.CLOSED).exists():
        raise QualityError("This sample has an open investigation. Close it first.")


def close_sample(sample, by, reject: bool, reason: str, password: str):
    """
    The two ways a sample ends without a certificate. Both are signed acts by
    someone other than the analyst.
    """
    word = "reject" if reject else "cancel"
    permission = APPROVE if reject else "sample.cancel"
    if not has_perm(by, permission):
        message = f"You do not have permission to {word} samples."
        record(by, "ACCESS_REFUSED", "sample", sample.sample_no, reason=message)
        raise QualityError(message)
    reason = _text(reason, f"Say why this sample is being {'rejected' if reject else 'cancelled'}.", 1000)
    if not confirm_password(by, password):
        record(by, "SIGN_PASSWORD_FAILED", "sample", sample.sample_no, meaning=word)
        raise QualityError("Password incorrect. Nothing was changed.")
    with transaction.atomic():
        sample = Sample.objects.select_for_update().get(pk=sample.pk)
        if sample.status in FINISHED:
            raise QualityError(f"This sample is already {sample.get_status_display().lower()}.")
        if sample.status not in UNSIGNED:
            raise QualityError("This sample is in review. Send its certificate back first.")
        if active_hold(sample) is not None:
            raise QualityError("This sample is on hold. Release the hold first.")
        if by.id == sample.assigned_analyst_id and not overrides(
            by, "A sample is closed by someone other than its analyst."
        ):
            record(by, "ACCESS_REFUSED", "sample", sample.sample_no, reason="Own sample")
            raise QualityError("This is your own sample, so someone else must close it.")
        if reject:
            _require_rejectable(sample)
        else:
            _require_cancellable(sample)
        was = sample.status
        sample.status = SampleStatus.REJECTED if reject else SampleStatus.CANCELLED
        sample.closed_by = by
        sample.closed_at = timezone.now()
        sample.closed_reason = reason
        sample.save(update_fields=["status", "closed_by", "closed_at", "closed_reason"])
        WorkflowEvent.objects.create(sample=sample, actor=by, from_status=was, to_status=sample.status, comment=reason)
        record(by, "SAMPLE_REJECTED" if reject else "SAMPLE_CANCELLED", "sample", sample.sample_no, reason=reason)
        notify(sample.assigned_analyst, "INVESTIGATION",
               f"{sample.sample_no} was {sample.get_status_display().lower()}",
               body=reason[:300], sample=sample, actor=by)
    return sample


# --- the quality unit's rules -----------------------------------------------

RULES = ("oos_investigation_required", "oos_max_retests", "oos_second_analyst", "oos_batch_block")


def rules_payload(cfg) -> dict:
    return {field: getattr(cfg, field) for field in RULES}


def change_rules(by, data: dict, reason: str):
    if not has_perm(by, APPROVE):
        message = "Only someone who approves closures can change these rules."
        record(by, "ACCESS_REFUSED", "config", "quality rules", reason=message)
        raise QualityError(message)
    reason = _text(reason, "Say why the rule is changing.", 1000)
    with transaction.atomic():
        cfg = LabConfig.objects.select_for_update().get(pk=LabConfig.get().pk)
        before, after = {}, {}
        for field in RULES:
            if field not in data:
                continue
            value = data[field]
            if field == "oos_max_retests":
                if not str(value).isdigit() or not 0 <= int(value) <= 10:
                    raise QualityError("The number of retests must be between 0 and 10.")
                value = int(value)
            elif not isinstance(value, bool):
                raise QualityError("Answer yes or no.")
            if getattr(cfg, field) != value:
                before[field], after[field] = getattr(cfg, field), value
                setattr(cfg, field, value)
        if after:
            cfg.save(update_fields=list(after))
            record(by, "QUALITY_RULES_CHANGED", "config", "quality rules", before=before, after=after, reason=reason)
    return cfg
