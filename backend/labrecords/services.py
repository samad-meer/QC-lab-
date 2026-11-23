"""
Every rule of the lab's own records. Each action checks its rules, writes the
record and its history, and leaves an audit row. A refused action raises
LabRecordError with a message for the person who tried.

Refusals and failed passwords are recorded outside the transaction: inside it,
the error that follows would roll the audit row back with everything else.

The rules about who may act (independence, a witness, a qualification) pass
only through accounts.authz.overrides, which flags the audit row. The rules
about the record (an expiry date, a retain-until date, the order of the steps)
pass for nobody.
"""
import hashlib
import json
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Max, OuterRef, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.authz import OVERRIDE, has_perm, overrides
from accounts.models import User
from accounts.passwords import confirm_password
from audit.services import record
from lims.evaluation import ResultValueError, parse_numeric
from lims.models import FINISHED, Sample
from notifications.services import notify, notify_all, users_with
from .models import (
    CalibrationEvent,
    CalibrationKind,
    CalibrationOutcome,
    ChangeCategory,
    ChangeCounter,
    ChangeRecord,
    ChangeStatus,
    CustodyAction,
    CustodyEvent,
    Instrument,
    InstrumentStatus,
    Material,
    MaterialKind,
    MaterialStatus,
    Method,
    MethodStatus,
    Qualification,
    RecordEvent,
    ValidationStatus,
)

INSTRUMENTS = "instrument.manage"
MATERIALS = "material.manage"
METHODS = "method.manage"
METHOD_APPROVE = "method.approve"
QUALIFICATIONS = "qualification.manage"
CUSTODY = "custody.record"
DESTROY = "custody.destroy"
CHANGES = "change.manage"
CHANGE_APPROVE = "change.approve"

# How dates read in a message, as they read in every report.
DAY = "%d-%b-%Y"


class LabRecordError(Exception):
    """A refused action. The message is written for the person who tried."""


# --- reading what was sent ---------------------------------------------------------

def _id(value) -> int:
    return int(value) if str(value).isdigit() and len(str(value)) <= 18 else 0


def _plain(value) -> str:
    return "" if value is None else str(value).strip()


def _optional(value, limit: int, name: str) -> str:
    text = _plain(value)
    if len(text) > limit:
        raise LabRecordError(f"Keep the {name} to {limit} characters.")
    return text


def _text(value, message: str, limit: int, name: str) -> str:
    text = _optional(value, limit, name)
    if not text:
        raise LabRecordError(message)
    return text


def _date(value, message: str) -> date:
    try:
        parsed = parse_date(_plain(value))
    except ValueError:  # the right shape, but no such date: 31 February
        parsed = None
    if parsed is None:
        raise LabRecordError(message)
    return parsed


def _optional_date(value, message: str) -> date | None:
    return _date(value, message) if _plain(value) else None


def _moment(value, message: str) -> datetime:
    """A date and time. With no time zone it is the lab's, as everywhere else."""
    try:
        parsed = parse_datetime(_plain(value))
    except ValueError:
        parsed = None
    if parsed is None:
        raise LabRecordError(message)
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def _person(value, message: str) -> User:
    user = User.objects.filter(pk=_id(value), is_active=True).first()
    if user is None:
        raise LabRecordError(message)
    return user


def _optional_person(value, message: str) -> User | None:
    return _person(value, message) if _plain(value) else None


def _choice(value, choices, message: str) -> str:
    if value not in choices.values:
        raise LabRecordError(message)
    return value


def _day(value) -> str:
    return value.strftime(DAY) if value else ""


def _shown(value) -> str:
    """A value as the history records it."""
    if value in (None, ""):
        return ""
    if isinstance(value, date):
        return _day(value)
    if isinstance(value, User):
        return value.display_name()
    return str(value)


# --- what every action does ---------------------------------------------------------

def _event(register: str, pk: int, by, what: str, changes=None, comment: str = ""):
    RecordEvent.objects.create(
        register=register, record_id=pk, actor=by, what=what, changes=changes or [], comment=comment[:1000]
    )


def history(register: str, pk: int):
    return RecordEvent.objects.filter(register=register, record_id=pk).select_related("actor")


def _require(by, permission: str, entity: str, entity_id, message: str):
    if not has_perm(by, permission):
        record(by, "ACCESS_REFUSED", entity, entity_id, reason=message)
        raise LabRecordError(message)


def _sign(by, password, entity: str, entity_id, meaning: str, message: str = "Password incorrect. Nothing was changed."):
    """A signature is the person's password, re-entered at that moment."""
    if not confirm_password(by, password or ""):
        record(by, "SIGN_PASSWORD_FAILED", entity, entity_id, meaning=meaning)
        raise LabRecordError(message)


def _apply(obj, cleaned: dict, labels: dict) -> list[dict]:
    """Set what differs. Returns what changed, as the record's history keeps it."""
    changes = []
    for field, value in cleaned.items():
        old = getattr(obj, field)
        if old == value:
            continue
        changes.append({"field": labels[field], "old": _shown(old), "new": _shown(value)})
        setattr(obj, field, value)
    return changes


def _given(data: dict, labels: dict) -> dict:
    return {field: data[field] for field in labels if field in data}


def _digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()


# --- instruments --------------------------------------------------------------------

INSTRUMENT_LABELS = {"name": "Name", "type": "Type", "location": "Location", "serial_number": "Serial number"}


def _clean_instrument(data: dict) -> dict:
    return {
        "name": _text(data.get("name"), "Give the instrument a name.", 200, "name"),
        "type": _text(data.get("type"), "Say what type of instrument it is.", 100, "type"),
        "location": _text(data.get("location"), "Say where the instrument is kept.", 120, "location"),
        "serial_number": _optional(data.get("serial_number"), 100, "serial number"),
    }


def instruments_with_next_due():
    """Every instrument, with the date its latest passing calibration runs out as `next_due`."""
    latest = CalibrationEvent.objects.filter(
        instrument=OuterRef("pk"), kind=CalibrationKind.CALIBRATION, outcome=CalibrationOutcome.PASS,
    ).order_by("-performed_at", "-id")
    return Instrument.objects.annotate(next_due=Subquery(latest.values("next_due")[:1]))


def latest_calibration(instrument: Instrument) -> CalibrationEvent | None:
    """
    By when it was done, not when it was typed in: an old certificate entered
    late does not extend anything. Only a calibration counts. Maintenance and
    repairs say nothing about whether it still measures correctly.
    """
    return instrument.events.filter(
        kind=CalibrationKind.CALIBRATION, outcome=CalibrationOutcome.PASS
    ).order_by("-performed_at", "-id").first()


def calibration_problem(instrument: Instrument, next_due: date | None, today: date | None = None) -> str | None:
    """Why it cannot be used, given when its latest passing calibration runs out. None when it can."""
    today = today or timezone.localdate()
    if instrument.status != InstrumentStatus.IN_SERVICE:
        return f"{instrument.code} is {instrument.get_status_display().lower()}."
    if next_due is None:
        return f"{instrument.code} has no passing calibration on record."
    if next_due < today:
        return f"{instrument.code} was due for calibration on {_day(next_due)}."
    return None


def instrument_problem(instrument: Instrument) -> str | None:
    latest = latest_calibration(instrument)
    return calibration_problem(instrument, latest.next_due if latest else None)


def add_instrument(by, data: dict) -> Instrument:
    _require(by, INSTRUMENTS, "instrument", "new instrument", "You do not have permission to manage instruments.")
    code = _text(data.get("code"), "Give the instrument a code.", 40, "code")
    fields = _clean_instrument(data)
    with transaction.atomic():
        if Instrument.objects.filter(code__iexact=code).exists():
            raise LabRecordError(f"An instrument with the code {code} already exists.")
        instrument = Instrument.objects.create(code=code, created_by=by, **fields)
        _event("instruments", instrument.pk, by, "Added")
        record(by, "INSTRUMENT_ADDED", "instrument", code, name=instrument.name)
    return instrument


def correct_instrument(instrument: Instrument, by, data: dict) -> Instrument:
    _require(by, INSTRUMENTS, "instrument", instrument.code, "You do not have permission to manage instruments.")
    reason = _text(data.get("comment"), "Say why this is being corrected.", 500, "reason")
    cleaned = _clean_instrument({**{f: getattr(instrument, f) for f in INSTRUMENT_LABELS}, **_given(data, INSTRUMENT_LABELS)})
    with transaction.atomic():
        instrument = Instrument.objects.select_for_update().get(pk=instrument.pk)
        if instrument.status == InstrumentStatus.RETIRED:
            raise LabRecordError("A retired instrument cannot be changed.")
        changes = _apply(instrument, cleaned, INSTRUMENT_LABELS)
        if not changes:
            raise LabRecordError("Nothing was changed.")
        instrument.save()
        _event("instruments", instrument.pk, by, "Corrected", changes, reason)
        record(by, "INSTRUMENT_CORRECTED", "instrument", instrument.code, changes=changes, reason=reason)
    return instrument


def _return_problem(instrument: Instrument) -> str | None:
    """It goes back in service on a calibration done since whatever put it out."""
    latest = latest_calibration(instrument)
    failed = instrument.events.filter(outcome=CalibrationOutcome.FAIL).order_by("-performed_at", "-id").first()
    if latest is None or (failed is not None and latest.performed_at <= failed.performed_at):
        return f"{instrument.code} needs a passing calibration before it can go back in service."
    if latest.next_due is None or latest.next_due < timezone.localdate():
        return f"{instrument.code} was due for calibration on {_day(latest.next_due)}. Calibrate it first."
    return None


def change_instrument_status(instrument: Instrument, by, data: dict) -> Instrument:
    _require(by, INSTRUMENTS, "instrument", instrument.code, "You do not have permission to manage instruments.")
    status = _choice(data.get("status"), InstrumentStatus, "Choose the new status.")
    reason = _text(data.get("comment"), "Say why the status is changing.", 500, "reason")
    with transaction.atomic():
        instrument = Instrument.objects.select_for_update().get(pk=instrument.pk)
        if instrument.status == InstrumentStatus.RETIRED:
            raise LabRecordError("A retired instrument cannot go back in service. Add it again under a new code.")
        if status == instrument.status:
            raise LabRecordError(f"{instrument.code} is already {instrument.get_status_display().lower()}.")
        if status == InstrumentStatus.IN_SERVICE:
            problem = _return_problem(instrument)
            if problem:
                raise LabRecordError(problem)
        was = instrument.get_status_display()
        instrument.status = status
        instrument.save()
        changes = [{"field": "Status", "old": was, "new": instrument.get_status_display()}]
        _event("instruments", instrument.pk, by, "Status changed", changes, reason)
        record(by, "INSTRUMENT_STATUS_CHANGED", "instrument", instrument.code,
               before=was, after=instrument.get_status_display(), reason=reason)
    return instrument


def record_calibration(instrument: Instrument, by, data: dict) -> CalibrationEvent:
    _require(by, INSTRUMENTS, "instrument", instrument.code, "You do not have permission to manage instruments.")
    kind = _choice(data.get("kind"), CalibrationKind, "Choose what was done.")
    outcome = _choice(data.get("outcome"), CalibrationOutcome, "Say whether it passed.")
    performed_at = _moment(data.get("performed_at"), "Enter when it was done.")
    if performed_at > timezone.now() + timedelta(minutes=5):
        raise LabRecordError("It cannot have been done in the future.")
    performer = _person(data.get("performed_by_id") or by.id, "Choose who did it.")
    reference = _text(data.get("reference"), "Enter the certificate or logbook number.", 100, "reference")
    next_due = _optional_date(data.get("next_due"), "That is not a valid date for when the next one is due.")
    notes = _optional(data.get("comment"), 1000, "notes")
    if kind == CalibrationKind.CALIBRATION and outcome == CalibrationOutcome.PASS and next_due is None:
        raise LabRecordError("Enter when the next calibration is due.")
    if next_due is not None and next_due <= timezone.localtime(performed_at).date():
        raise LabRecordError("The next one must be due after this one was done.")
    with transaction.atomic():
        instrument = Instrument.objects.select_for_update().get(pk=instrument.pk)
        if instrument.status == InstrumentStatus.RETIRED:
            raise LabRecordError("A retired instrument cannot be logged against.")
        event = CalibrationEvent.objects.create(
            instrument=instrument, kind=kind, performed_at=performed_at, performed_by=performer, outcome=outcome,
            reference=reference, next_due=next_due, notes=notes, recorded_by=by,
        )
        record(by, "CALIBRATION_RECORDED", "instrument", instrument.code, kind=event.get_kind_display().lower(),
               outcome=event.get_outcome_display().lower(), reference=reference,
               next_due=_day(next_due), performed_by=performer.username)
        # Any failure, whatever was being done: it cannot be trusted until shown otherwise.
        if outcome == CalibrationOutcome.FAIL and instrument.status == InstrumentStatus.IN_SERVICE:
            instrument.status = InstrumentStatus.OUT_OF_SERVICE
            instrument.save()
            changes = [{"field": "Status", "old": InstrumentStatus.IN_SERVICE.label,
                        "new": InstrumentStatus.OUT_OF_SERVICE.label}]
            _event("instruments", instrument.pk, by, "Taken out of service", changes,
                   f"{event.get_kind_display()} failed, {reference}")
            record(by, "INSTRUMENT_OUT_OF_SERVICE", "instrument", instrument.code, reference=reference)
    return event


# --- reference standards, reagents and columns ---------------------------------------

MATERIAL_LABELS = {
    "kind": "Kind", "code": "Code", "name": "Name", "lot": "Lot", "supplier": "Supplier", "potency": "Potency",
    "received_on": "Received", "opened_on": "Opened", "expiry_date": "Expiry",
}
# What a result that used this lot is relying on.
MATERIAL_IDENTITY = {"kind", "code", "lot"}


def _potency(value):
    if value in (None, ""):
        return None
    try:
        potency = parse_numeric(value)
    except ResultValueError as e:
        raise LabRecordError(f"Potency: {e}")
    if potency <= 0:
        raise LabRecordError("Potency must be above zero, or left empty.")
    return potency


def _clean_material(data: dict) -> dict:
    today = timezone.localdate()
    received = _date(data.get("received_on"), "Enter the date it was received.")
    opened = _optional_date(data.get("opened_on"), "That is not a valid date for when it was opened.")
    expiry = _date(data.get("expiry_date"), "Enter its expiry date.")
    if received > today:
        raise LabRecordError("It cannot have been received in the future.")
    if opened is not None and (opened < received or opened > today):
        raise LabRecordError("It must have been opened on or after it was received, and not in the future.")
    if expiry < received:
        raise LabRecordError("The expiry date cannot be before it was received.")
    return {
        "kind": _choice(data.get("kind"), MaterialKind, "Choose what kind of material this is."),
        "code": _text(data.get("code"), "Give the material a code.", 40, "code"),
        "name": _text(data.get("name"), "Give the material a name.", 200, "name"),
        "lot": _text(data.get("lot"), "Enter the lot number.", 60, "lot number"),
        "supplier": _optional(data.get("supplier"), 200, "supplier"),
        "potency": _potency(data.get("potency")),
        "received_on": received, "opened_on": opened, "expiry_date": expiry,
    }


def material_label(material: Material) -> str:
    return f"{material.code} lot {material.lot}"


def material_problem(material: Material, today: date | None = None) -> str | None:
    """Why this lot cannot be used right now. None when it can."""
    today = today or timezone.localdate()
    if material.status != MaterialStatus.AVAILABLE:
        return f"{material_label(material)} is {material.get_status_display().lower()}."
    if material.expiry_date < today:
        return f"{material_label(material)} expired on {_day(material.expiry_date)}."
    return None


def add_material(by, data: dict) -> Material:
    _require(by, MATERIALS, "material", "new material", "You do not have permission to manage materials.")
    fields = _clean_material(data)
    # A lot starts in quarantine unless someone says it has been checked.
    status = _choice(data.get("status") or MaterialStatus.QUARANTINED, MaterialStatus, "Choose a status.")
    with transaction.atomic():
        if Material.objects.filter(code__iexact=fields["code"], lot__iexact=fields["lot"]).exists():
            raise LabRecordError(f"{fields['code']} lot {fields['lot']} is already on the register.")
        material = Material.objects.create(status=status, created_by=by, **fields)
        _event("materials", material.pk, by, "Added", comment=f"Status: {material.get_status_display()}")
        record(by, "MATERIAL_ADDED", "material", material_label(material), kind=material.get_kind_display(),
               name=material.name, status=material.get_status_display())
    return material


def correct_material(material: Material, by, data: dict) -> Material:
    """Changing what is recorded needs a reason, and the old value stays on the history."""
    label = material_label(material)
    _require(by, MATERIALS, "material", label, "You do not have permission to manage materials.")
    reason = _text(data.get("comment"), "Say why this is being corrected.", 500, "reason")
    cleaned = _clean_material({**{f: getattr(material, f) for f in MATERIAL_LABELS}, **_given(data, MATERIAL_LABELS)})
    with transaction.atomic():
        material = Material.objects.select_for_update().get(pk=material.pk)
        if material.status == MaterialStatus.RETIRED:
            raise LabRecordError("A retired material cannot be changed.")
        changes = _apply(material, dict(cleaned), MATERIAL_LABELS)
        if not changes:
            raise LabRecordError("Nothing was changed.")
        identity = {MATERIAL_LABELS[f] for f in MATERIAL_IDENTITY}
        if {c["field"] for c in changes} & identity and material.result_records.exists():
            raise LabRecordError(
                f"{label} is named on recorded results, so its kind, code and lot cannot change. "
                "Retire it and add the right one."
            )
        clash = Material.objects.filter(code__iexact=material.code, lot__iexact=material.lot).exclude(pk=material.pk)
        if clash.exists():
            raise LabRecordError(f"{material_label(material)} is already on the register.")
        material.save()
        _event("materials", material.pk, by, "Corrected", changes, reason)
        record(by, "MATERIAL_CORRECTED", "material", material_label(material), changes=changes, reason=reason)
    return material


def change_material_status(material: Material, by, data: dict) -> Material:
    label = material_label(material)
    _require(by, MATERIALS, "material", label, "You do not have permission to manage materials.")
    status = _choice(data.get("status"), MaterialStatus, "Choose the new status.")
    reason = _text(data.get("comment"), "Say why the status is changing.", 500, "reason")
    with transaction.atomic():
        material = Material.objects.select_for_update().get(pk=material.pk)
        if material.status == MaterialStatus.RETIRED:
            raise LabRecordError("A retired material cannot be brought back. Add the lot again if it was a mistake.")
        if status == material.status:
            raise LabRecordError(f"{label} is already {material.get_status_display().lower()}.")
        was = material.get_status_display()
        material.status = status
        material.save()
        changes = [{"field": "Status", "old": was, "new": material.get_status_display()}]
        _event("materials", material.pk, by, "Status changed", changes, reason)
        record(by, "MATERIAL_STATUS_CHANGED", "material", label, before=was,
               after=material.get_status_display(), reason=reason)
    return material


# --- the method master ---------------------------------------------------------------

METHOD_LABELS = {"title": "Title", "document_ref": "Document reference", "validation_status": "Validation status"}


def method_digest(m: Method) -> str:
    """What is being approved, exactly."""
    return _digest(m.code, m.version, m.title, m.document_ref, m.validation_status)


def _clean_method(data: dict) -> dict:
    return {
        "title": _text(data.get("title"), "Give the method a title.", 200, "title"),
        "document_ref": _text(data.get("document_ref"), "Enter the document reference.", 200, "document reference"),
        "validation_status": _choice(data.get("validation_status"), ValidationStatus, "Choose the validation status."),
    }


def _versions_of(code: str):
    return Method.objects.select_for_update().filter(code__iexact=code)


def _require_draft(method: Method):
    if method.status != MethodStatus.DRAFT:
        raise LabRecordError(f"This version is {method.get_status_display().lower()}, not a draft.")


def draft_method(by, data: dict) -> Method:
    _require(by, METHODS, "method", "new method", "You do not have permission to draft methods.")
    code = _text(data.get("code"), "Give the method a code.", 40, "code")
    fields = _clean_method(data)
    with transaction.atomic():
        if _versions_of(code).exists():
            raise LabRecordError(f"Method {code} already exists. Open it and draft a new version.")
        method = Method.objects.create(code=code, created_by=by, **fields)
        _event("methods", method.pk, by, "Drafted")
        record(by, "METHOD_DRAFTED", "method", str(method), title=method.title)
    return method


def new_method_version(method: Method, by, data: dict) -> Method:
    """It starts as a copy and changes nothing until someone else makes it effective."""
    _require(by, METHODS, "method", str(method), "You do not have permission to draft methods.")
    reason = _text(data.get("comment"), "Say why a new version is needed.", 500, "reason")
    with transaction.atomic():
        versions = list(_versions_of(method.code).order_by("version"))
        if any(v.status == MethodStatus.DRAFT for v in versions):
            raise LabRecordError(f"Version {versions[-1].version} of {method.code} is already a draft. Finish it first.")
        latest = versions[-1]
        draft = Method.objects.create(
            code=latest.code, version=latest.version + 1, title=latest.title, document_ref=latest.document_ref,
            validation_status=latest.validation_status, change_reason=reason, created_by=by,
        )
        _event("methods", draft.pk, by, "Drafted", comment=reason)
        record(by, "METHOD_DRAFTED", "method", str(draft), title=draft.title, reason=reason)
    return draft


def edit_method(method: Method, by, data: dict) -> Method:
    """A draft changes freely, but whoever changes it can no longer approve it."""
    _require(by, METHODS, "method", str(method), "You do not have permission to draft methods.")
    cleaned = _clean_method({**{f: getattr(method, f) for f in METHOD_LABELS}, **_given(data, METHOD_LABELS)})
    comment = _optional(data.get("comment"), 500, "comment")
    with transaction.atomic():
        method = Method.objects.select_for_update().get(pk=method.pk)
        _require_draft(method)
        changes = _apply(method, cleaned, METHOD_LABELS)
        if not changes:
            raise LabRecordError("Nothing was changed.")
        method.edited_by = by
        method.save()
        _event("methods", method.pk, by, "Changed", changes, comment)
        record(by, "METHOD_EDITED", "method", str(method), changes=changes)
    return method


def method_authors(method: Method) -> set[int]:
    return {method.created_by_id, method.edited_by_id}


def approve_method(method: Method, by, data: dict) -> Method:
    """A signed act. The version it replaces is retired in the same moment."""
    _require(by, METHOD_APPROVE, "method", str(method), "You do not have permission to make methods effective.")
    _require_draft(method)
    if by.id in method_authors(method) and not overrides(
        by, "A method is made effective by someone other than whoever drafted or changed it."
    ):
        record(by, "METHOD_APPROVAL_REFUSED", "method", str(method))
        raise LabRecordError("You drafted or changed this version, so someone else must make it effective.")
    _sign(by, data.get("password"), "method", str(method), "made effective", "Password incorrect. The method is still a draft.")
    with transaction.atomic():
        versions = list(_versions_of(method.code))
        method = next(v for v in versions if v.pk == method.pk)
        _require_draft(method)
        if by.id in method_authors(method) and not has_perm(by, OVERRIDE):
            raise LabRecordError("You drafted or changed this version, so someone else must make it effective.")
        digest = method_digest(method)
        if data.get("digest") != digest:
            raise LabRecordError("This draft has changed since you opened it. Review it again before approving.")
        replaced = [v for v in versions if v.status == MethodStatus.EFFECTIVE]
        for old in replaced:
            old.status = MethodStatus.RETIRED
            old.save()
            _event("methods", old.pk, by, "Retired", [{"field": "Status", "old": "Effective", "new": "Retired"}],
                   f"Replaced by version {method.version}")
        method.status = MethodStatus.EFFECTIVE
        method.approved_by = by
        method.approved_at = timezone.now()
        method.approved_digest = digest
        method.save()
        _event("methods", method.pk, by, "Made effective")
        record(by, "METHOD_APPROVED", "method", str(method), digest=digest,
               replaces=f"v{replaced[-1].version}" if replaced else "nothing")
    return method


def retire_method(method: Method, by, data: dict) -> Method:
    """Abandoning a draft is the drafter's to do; withdrawing a method in use takes an approver."""
    needed = METHODS if method.status == MethodStatus.DRAFT else METHOD_APPROVE
    _require(by, needed, "method", str(method), "You do not have permission to retire this method.")
    reason = _text(data.get("comment"), "Say why it is being retired.", 500, "reason")
    with transaction.atomic():
        method = Method.objects.select_for_update().get(pk=method.pk)
        if method.status == MethodStatus.RETIRED:
            raise LabRecordError("This version is already retired.")
        was = method.get_status_display()
        method.status = MethodStatus.RETIRED
        method.save()
        _event("methods", method.pk, by, "Retired", [{"field": "Status", "old": was, "new": "Retired"}], reason)
        record(by, "METHOD_RETIRED", "method", str(method), reason=reason)
    return method


def method_problems(tests) -> list[str]:
    """Why these tests cannot go into an approved specification. Empty when they can."""
    problems = []
    for test in tests:
        method = test.method_record
        if method is None:
            continue
        if method.status != MethodStatus.EFFECTIVE:
            problems.append(f"{test.name} names {method}, which is {method.get_status_display().lower()}.")
        elif method.validation_status == ValidationStatus.NOT_VALIDATED:
            problems.append(f"{test.name} names {method}, which is not validated.")
    return problems


# --- analyst qualification ------------------------------------------------------------

def qualification_problem(user, code: str, today: date | None = None) -> str | None:
    """
    Why this person may not run this method today, to be read by them. None when
    they may. The newest row speaks for them, so revoking it is not undone by an
    earlier grant that has not run out yet, and a renewal after a revocation counts.
    """
    today = today or timezone.localdate()
    latest = Qualification.objects.filter(user=user, method__iexact=code).first()
    if latest is None:
        return f"You are not qualified on method {code}. Someone who manages qualifications must record it first."
    if latest.revoked_at is not None:
        return f"Your qualification on {code} was revoked on {_day(timezone.localtime(latest.revoked_at))}: {latest.revoke_reason}"
    if latest.qualified_on > today:
        return f"Your qualification on {code} starts on {_day(latest.qualified_on)}."
    if latest.expires_on < today:
        return f"Your qualification on {code} expired on {_day(latest.expires_on)}. It must be renewed first."
    return None


def grant_qualification(by, data: dict) -> Qualification:
    """A signed act, by someone other than the analyst."""
    _require(by, QUALIFICATIONS, "qualification", "new qualification", "You do not have permission to grant qualifications.")
    person = _person(data.get("user_id"), "Choose who is being qualified.")
    written = _text(data.get("method"), "Choose the method.", 40, "method code")
    known = Method.objects.filter(code__iexact=written).exclude(status=MethodStatus.RETIRED).first()
    if known is None:
        raise LabRecordError(f"There is no draft or effective method with the code {written}.")
    qualified_on = _date(data.get("qualified_on"), "Enter the date they qualified.")
    expires_on = _date(data.get("expires_on"), "Enter the date the qualification expires.")
    today = timezone.localdate()
    if qualified_on > today:
        raise LabRecordError("The date they qualified cannot be in the future.")
    if expires_on <= qualified_on or expires_on < today:
        raise LabRecordError("The expiry date must be after they qualified, and not already past.")
    label = f"{person.username} on {known.code}"
    if person.id == by.id and not overrides(by, "A qualification is granted by someone other than the analyst."):
        record(by, "QUALIFICATION_REFUSED", "qualification", label)
        raise LabRecordError("You cannot qualify yourself. Someone else must grant it.")
    _sign(by, data.get("password"), "qualification", label, "qualification")
    with transaction.atomic():
        qualification = Qualification.objects.create(
            user=person, method=known.code, qualified_on=qualified_on, expires_on=expires_on, qualified_by=by,
        )
        _event("qualifications", qualification.pk, by, "Granted",
               comment=f"{_day(qualified_on)} to {_day(expires_on)}")
        record(by, "QUALIFICATION_GRANTED", "qualification", label, person=person.display_name(),
               method=known.code, expires=_day(expires_on))
        notify(person, "LAB_RECORD", f"You are qualified on {known.code}",
               body=f"Until {_day(expires_on)}.", link=f"/lab/qualifications/{qualification.pk}", actor=by)
    return qualification


def revoke_qualification(qualification: Qualification, by, data: dict) -> Qualification:
    label = f"{qualification.user.username} on {qualification.method}"
    _require(by, QUALIFICATIONS, "qualification", label, "You do not have permission to revoke qualifications.")
    reason = _text(data.get("comment"), "Say why it is being revoked.", 500, "reason")
    if qualification.revoked_at is not None:
        raise LabRecordError("This qualification has already been revoked.")
    _sign(by, data.get("password"), "qualification", label, "revocation")
    with transaction.atomic():
        qualification = Qualification.objects.select_for_update().get(pk=qualification.pk)
        if qualification.revoked_at is not None:
            raise LabRecordError("This qualification has already been revoked.")
        qualification.revoked_at = timezone.now()
        qualification.revoked_by = by
        qualification.revoke_reason = reason
        qualification.save()
        _event("qualifications", qualification.pk, by, "Revoked", comment=reason)
        record(by, "QUALIFICATION_REVOKED", "qualification", label, reason=reason)
        notify(qualification.user, "LAB_RECORD", f"Your qualification on {qualification.method} was revoked",
               body=reason, link=f"/lab/qualifications/{qualification.pk}", actor=by)
    return qualification


# --- chain of custody -------------------------------------------------------------------

def retain_until(sample: Sample) -> date | None:
    """The latest date anyone said to keep it until. Nothing shortens it."""
    return sample.custody_events.filter(action=CustodyAction.RETAINED).aggregate(d=Max("retain_until"))["d"]


def is_destroyed(sample: Sample) -> bool:
    return sample.custody_events.filter(action=CustodyAction.DESTROYED).exists()


def _destruction_problem(sample: Sample) -> str | None:
    if sample.status not in FINISHED:
        return f"{sample.sample_no} is still {sample.get_status_display().lower()}, so it cannot be destroyed."
    until = retain_until(sample)
    if until is not None and until >= timezone.localdate():
        return f"{sample.sample_no} is retained until {_day(until)}. It can be destroyed after that date."
    return None


def _chain_ended(sample: Sample):
    if is_destroyed(sample):
        raise LabRecordError(f"{sample.sample_no} has been destroyed, so its chain of custody has ended.")


def _custody_fields(by, action: str, data: dict) -> dict:
    fields = {
        "location": _optional(data.get("location"), 120, "location"),
        "quantity": _optional(data.get("quantity"), 60, "quantity"),
        "note": _optional(data.get("comment"), 1000, "note"),
        "from_person": _optional_person(data.get("from_person_id"), "Choose who it came from."),
        "to_person": _optional_person(data.get("to_person_id"), "Choose who it went to."),
    }
    if action == CustodyAction.TRANSFERRED:
        fields["from_person"] = fields["from_person"] or by
        if fields["to_person"] is None:
            raise LabRecordError("Choose who it was transferred to.")
        if fields["to_person"] == fields["from_person"]:
            raise LabRecordError("A transfer goes from one person to another.")
    if action in (CustodyAction.STORED, CustodyAction.RETAINED) and not fields["location"]:
        raise LabRecordError("Say where it is kept.")
    return fields


def add_custody(sample: Sample, by, data: dict) -> CustodyEvent:
    action = _choice(data.get("action"), CustodyAction, "Choose what happened to the sample.")
    destroying = action == CustodyAction.DESTROYED
    _require(by, DESTROY if destroying else CUSTODY, "sample", sample.sample_no,
             "You do not have permission to record this on a sample.")
    fields = _custody_fields(by, action, data)
    until = None
    if action == CustodyAction.RETAINED:
        until = _date(data.get("retain_until"), "Enter the date it must be kept until.")
        if until < timezone.localdate():
            raise LabRecordError("The retain-until date cannot be in the past.")
    if destroying:
        _chain_ended(sample)
        problem = _destruction_problem(sample)
        if problem:
            record(by, "SAMPLE_DESTRUCTION_REFUSED", "sample", sample.sample_no, reason=problem)
            raise LabRecordError(problem)
        witness = _person(data.get("witness_id"), "Choose who witnessed it.")
        if witness.id == by.id and not overrides(by, "A destruction is witnessed by a different person."):
            record(by, "SAMPLE_DESTRUCTION_REFUSED", "sample", sample.sample_no, reason="No independent witness")
            raise LabRecordError("The witness must be a different person.")
        # Naming someone is not the same as them having been there.
        _sign(by, data.get("password"), "sample", sample.sample_no, "destruction")
        _sign(witness, data.get("witness_password"), "sample", sample.sample_no, "witness to destruction",
              "The witness's password is incorrect. Nothing was changed.")
        fields["witness"] = witness

    with transaction.atomic():
        sample = Sample.objects.select_for_update().get(pk=sample.pk)
        _chain_ended(sample)
        if destroying:
            problem = _destruction_problem(sample)
            if problem:
                raise LabRecordError(problem)
        if action == CustodyAction.RETAINED:
            held_until = retain_until(sample)
            if held_until is not None and until < held_until:
                raise LabRecordError(f"{sample.sample_no} is already retained until {_day(held_until)}. "
                                     "That date can be extended, never brought forward.")
        event = CustodyEvent.objects.create(sample=sample, action=action, retain_until=until, by=by, **fields)
        if destroying:
            record(by, "SAMPLE_DESTROYED", "sample", sample.sample_no, witness=fields["witness"].display_name(),
                   location=fields["location"], quantity=fields["quantity"], note=fields["note"])
        else:
            record(by, "CUSTODY_RECORDED", "sample", sample.sample_no, movement=event.get_action_display().lower(),
                   location=fields["location"], to=_shown(fields["to_person"]), retain_until=_day(until))
        if action == CustodyAction.TRANSFERRED:
            notify(fields["to_person"], "HANDOVER", f"{sample.sample_no} was transferred to you",
                   body=fields["note"], sample=sample, actor=by)
    return event


# --- change control ------------------------------------------------------------------------

CHANGE_LABELS = {
    "title": "Title", "description": "Description", "reason": "Reason for the change",
    "impact_assessment": "Impact assessment", "category": "Category",
}


def change_digest(c: ChangeRecord) -> str:
    """What is being approved, exactly."""
    return _digest(c.reference, c.title, c.description, c.reason, c.impact_assessment, c.category)


def _clean_change(data: dict) -> dict:
    return {
        "title": _text(data.get("title"), "Give the change a title.", 200, "title"),
        "description": _text(data.get("description"), "Describe the change.", 4000, "description"),
        "reason": _text(data.get("reason"), "Say why the change is needed.", 4000, "reason"),
        "impact_assessment": _text(data.get("impact_assessment"), "Assess its impact.", 4000, "impact assessment"),
        "category": _choice(data.get("category"), ChangeCategory, "Choose a category."),
    }


def _next_change_reference() -> str:
    year = timezone.localdate().year
    ChangeCounter.objects.get_or_create(year=year)
    counter = ChangeCounter.objects.select_for_update().get(year=year)
    counter.last_no += 1
    counter.save()
    return f"CC-{year}-{counter.last_no:04d}"


def _lock_change(change: ChangeRecord) -> ChangeRecord:
    return ChangeRecord.objects.select_for_update().get(pk=change.pk)


def _require_change_status(change: ChangeRecord, status: str, message: str):
    if change.status != status:
        raise LabRecordError(message)


def change_authors(change: ChangeRecord) -> set[int]:
    """Whoever raised it or changed what it says. A decision on it is not theirs to make."""
    people = {change.raised_by_id}
    people |= set(history("changes", change.pk).filter(what="Changed").values_list("actor_id", flat=True))
    return people


def _independent(change: ChangeRecord, by, people: set[int], rule: str, action: str, message: str):
    if by.id in people and not overrides(by, rule):
        record(by, action, "change", change.reference)
        raise LabRecordError(message)


def raise_change(by, data: dict) -> ChangeRecord:
    _require(by, CHANGES, "change", "new change", "You do not have permission to raise change records.")
    fields = _clean_change(data)
    with transaction.atomic():
        change = ChangeRecord.objects.create(reference=_next_change_reference(), raised_by=by, **fields)
        _event("changes", change.pk, by, "Raised")
        record(by, "CHANGE_RAISED", "change", change.reference, title=change.title,
               category=change.get_category_display())
        notify_all(
            [u for u in users_with(CHANGE_APPROVE) if u.id != by.id], "LAB_RECORD",
            f"{change.reference} is waiting for a decision", body=change.title,
            link=f"/lab/changes/{change.pk}", actor=by,
        )
    return change


def edit_change(change: ChangeRecord, by, data: dict) -> ChangeRecord:
    """Changing what is written needs a reason, and it costs that person any say in the decision."""
    _require(by, CHANGES, "change", change.reference, "You do not have permission to work on change records.")
    note = _text(data.get("comment"), "Say why this is being changed.", 500, "comment")
    cleaned = _clean_change({**{f: getattr(change, f) for f in CHANGE_LABELS}, **_given(data, CHANGE_LABELS)})
    with transaction.atomic():
        change = _lock_change(change)
        _require_change_status(change, ChangeStatus.OPEN, "Only an open change record can be edited.")
        changes = _apply(change, cleaned, CHANGE_LABELS)
        if not changes:
            raise LabRecordError("Nothing was changed.")
        change.save()
        _event("changes", change.pk, by, "Changed", changes, note)
        record(by, "CHANGE_EDITED", "change", change.reference,
               fields=", ".join(c["field"] for c in changes), changes=changes, reason=note)
    return change


def approve_change(change: ChangeRecord, by, data: dict) -> ChangeRecord:
    _require(by, CHANGE_APPROVE, "change", change.reference, "You do not have permission to approve changes.")
    _require_change_status(change, ChangeStatus.OPEN, "Only an open change record can be approved.")
    _independent(change, by, change_authors(change),
                 "A change is approved by someone other than whoever raised or changed it.",
                 "CHANGE_APPROVAL_REFUSED",
                 "You raised or changed this record, so someone else must approve it.")
    _sign(by, data.get("password"), "change", change.reference, "approval")
    with transaction.atomic():
        change = _lock_change(change)
        _require_change_status(change, ChangeStatus.OPEN, "Only an open change record can be approved.")
        if by.id in change_authors(change) and not has_perm(by, OVERRIDE):
            raise LabRecordError("You raised or changed this record, so someone else must approve it.")
        digest = change_digest(change)
        if data.get("digest") != digest:
            raise LabRecordError("This record has changed since you opened it. Review it again before approving.")
        change.status = ChangeStatus.APPROVED
        change.approved_by = by
        change.approved_at = timezone.now()
        change.approved_digest = digest
        change.save()
        _event("changes", change.pk, by, "Approved")
        record(by, "CHANGE_APPROVED", "change", change.reference, digest=digest)
        notify(change.raised_by, "LAB_RECORD", f"{change.reference} was approved",
               link=f"/lab/changes/{change.pk}", actor=by)
    return change


def reject_change(change: ChangeRecord, by, data: dict) -> ChangeRecord:
    _require(by, CHANGE_APPROVE, "change", change.reference, "You do not have permission to reject changes.")
    reason = _text(data.get("comment"), "Say why it is being rejected.", 1000, "reason")
    _require_change_status(change, ChangeStatus.OPEN, "Only an open change record can be rejected.")
    _independent(change, by, change_authors(change),
                 "A change is rejected by someone other than whoever raised or changed it.",
                 "CHANGE_APPROVAL_REFUSED",
                 "You raised or changed this record, so someone else must decide it.")
    _sign(by, data.get("password"), "change", change.reference, "rejection")
    with transaction.atomic():
        change = _lock_change(change)
        _require_change_status(change, ChangeStatus.OPEN, "Only an open change record can be rejected.")
        change.status = ChangeStatus.REJECTED
        change.rejected_by = by
        change.rejected_at = timezone.now()
        change.rejected_reason = reason
        change.save()
        _event("changes", change.pk, by, "Rejected", comment=reason)
        record(by, "CHANGE_REJECTED", "change", change.reference, reason=reason)
        notify(change.raised_by, "LAB_RECORD", f"{change.reference} was rejected", body=reason,
               link=f"/lab/changes/{change.pk}", actor=by)
    return change


def implement_change(change: ChangeRecord, by, data: dict) -> ChangeRecord:
    _require(by, CHANGES, "change", change.reference, "You do not have permission to work on change records.")
    note = _text(data.get("comment"), "Say what was done.", 1000, "note")
    with transaction.atomic():
        change = _lock_change(change)
        _require_change_status(change, ChangeStatus.APPROVED, "Only an approved change can be implemented.")
        change.status = ChangeStatus.IMPLEMENTED
        change.implemented_by = by
        change.implemented_at = timezone.now()
        change.implementation_note = note
        change.save()
        _event("changes", change.pk, by, "Implemented", comment=note)
        record(by, "CHANGE_IMPLEMENTED", "change", change.reference, note=note)
    return change


def close_change(change: ChangeRecord, by, data: dict) -> ChangeRecord:
    """A signed act, by someone who neither raised the change nor carried it out."""
    _require(by, CHANGE_APPROVE, "change", change.reference, "You do not have permission to close changes.")
    _require_change_status(change, ChangeStatus.IMPLEMENTED, "Only an implemented change can be closed.")
    _independent(change, by, change_authors(change) | {change.implemented_by_id},
                 "A change is closed by someone other than whoever raised or implemented it.",
                 "CHANGE_CLOSE_REFUSED",
                 "You raised or implemented this change, so someone else must close it.")
    _sign(by, data.get("password"), "change", change.reference, "closure")
    with transaction.atomic():
        change = _lock_change(change)
        _require_change_status(change, ChangeStatus.IMPLEMENTED, "Only an implemented change can be closed.")
        change.status = ChangeStatus.CLOSED
        change.closed_by = by
        change.closed_at = timezone.now()
        change.save()
        _event("changes", change.pk, by, "Closed")
        record(by, "CHANGE_CLOSED", "change", change.reference)
    return change
