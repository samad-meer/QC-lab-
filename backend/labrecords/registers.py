"""
One way to show a register, as reports do for reports.

A register states what is particular to it: which records, its columns and
filters, the form that adds one, how one record reads, and what can be done to
it. The screens (frontend/src/pages/lab) draw whatever is defined here, so a new
register needs no new screen, and a button only appears for someone the service
behind it would let through.

Dates go out as dates, and the screen writes them, because it writes every
other date in the application the same way.
"""
from dataclasses import dataclass
from typing import Callable

from django.db.models import Max, Q
from django.http import Http404
from django.utils import timezone

from accounts.authz import OVERRIDE, has_perm
from accounts.models import User
from execution.payloads import person
from lims.models import Sample
from lims.workflow import samples_visible_to
from . import services
from .models import (
    CalibrationKind,
    CalibrationOutcome,
    ChangeCategory,
    ChangeRecord,
    ChangeStatus,
    CustodyAction,
    Instrument,
    InstrumentStatus,
    Material,
    MaterialKind,
    MaterialStatus,
    Method,
    MethodStatus,
    Qualification,
    ResultRecord,
    ValidationStatus,
)


def choices(enum) -> list[tuple]:
    return [(c.value, c.label) for c in enum]


def people() -> list[tuple]:
    active = User.objects.filter(is_active=True, role__isnull=False).order_by("first_name", "username")
    return [(u.id, u.display_name()) for u in active]


def cell(value, **extra):
    return {"text": value, **extra} if extra else value


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"  # text, textarea, number, date, datetime, select or password
    required: bool = False
    options: list | None = None
    note: str = ""
    initial: object = None

    def json(self) -> dict:
        return {
            "key": self.key, "label": self.label, "kind": self.kind, "required": self.required, "note": self.note,
            "options": [{"value": str(v), "label": label} for v, label in self.options or []],
            "initial": str(self.initial) if self.kind == "select" and self.initial is not None else self.initial,
        }


SIGNATURE = Field("password", "Your password", "password", required=True, note="this is a signature")


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = ""  # date or datetime, for the screen to write


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    options: list
    apply: Callable


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    run: Callable  # (record, by, data)
    may: Callable  # (record, user) -> may this person do this now?
    title: str = ""
    hint: str = ""
    tone: str = "primary"
    done: str = "Saved"
    # A signed act asks for the password, under the meaning below.
    signed: bool = False
    meaning: str = ""
    # The words on the comment box; empty means there is none.
    comment: str = ""
    comment_required: bool = True
    fields: Callable | None = None  # (record, request) -> [Field]
    digest: Callable | None = None  # (record) -> what the person is looking at

    def json(self, record, request) -> dict:
        return {
            "key": self.key, "label": self.label, "title": self.title or self.label, "hint": self.hint,
            "tone": self.tone, "done": self.done, "signed": self.signed, "meaning": self.meaning,
            "comment": self.comment, "comment_required": self.comment_required,
            "fields": [f.json() for f in self.fields(record, request)] if self.fields else [],
            "digest": self.digest(record) if self.digest else "",
        }


def table(heading: str, columns: list[Column], rows: list[dict], empty: str = "None on record.") -> dict:
    return {
        "heading": heading, "empty": empty, "rows": rows,
        "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in columns],
    }


def fact(label: str, value, kind: str = "") -> dict:
    return {"label": label, "value": value, "kind": kind}


def recent_use(records, request) -> dict:
    """The results that relied on this, for those whose samples this person can see."""
    visible = samples_visible_to(request.user).order_by().values("pk")
    rows = records.filter(result__sample__in=visible).select_related(
        "result__sample", "result__test_definition", "result__entered_by"
    ).order_by("-created_at", "-id")[:50]
    return table(
        "Used on results",
        [Column("sample", "Sample"), Column("test", "Test"), Column("by", "Entered by"), Column("at", "When", "datetime")],
        [
            {
                "sample": cell(r.result.sample.sample_no, to=f"/samples/{r.result.sample_id}"),
                "test": r.result.test_definition.name, "by": r.result.entered_by.display_name(),
                "at": r.result.entered_at,
            }
            for r in rows
        ],
        "Not used on any result yet.",
    )


class Register:
    key = ""
    title = ""
    singular = ""
    description = ""
    # Shown under the title: what the list means and what it does not.
    note = ""
    # On the overview: where this register reaches the lab's daily work.
    purpose = ""
    # Who may open it at all. Working on a register comes with seeing it (accounts.permissions_registry).
    sees = ""
    # Who may add one, the label of the button, and what the form asks.
    adds = ""
    add_label = ""
    add_hint = ""
    columns: list[Column] = []
    filters: list[Filter] = []
    search: list[str] = []
    search_hint = ""
    actions: list[Action] = []

    def records(self, request):
        raise NotImplementedError

    def visible_to(self, user) -> bool:
        return has_perm(user, self.sees)

    def order(self, records):
        return records

    def rows(self, records: list, request) -> list[dict]:
        raise NotImplementedError

    def add_fields(self, request) -> list[Field]:
        return []

    def add(self, by, data):
        raise Http404

    def detail(self, record, request) -> dict:
        raise Http404

    def definition(self, request) -> dict:
        can_add = bool(self.adds) and has_perm(request.user, self.adds)
        return {
            "key": self.key, "title": self.title, "singular": self.singular, "description": self.description,
            "note": self.note, "purpose": self.purpose, "count": self.records(request).count(),
            "search_hint": self.search_hint if self.search else "",
            "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in self.columns],
            "filters": [
                {"key": f.key, "label": f.label, "options": [{"value": str(v), "label": label} for v, label in f.options]}
                for f in self.filters
            ],
            "can_add": can_add, "add_label": self.add_label, "add_hint": self.add_hint,
            "add_fields": [f.json() for f in self.add_fields(request)] if can_add else [],
        }

    def find(self, request, pk):
        found = self.records(request).filter(pk=pk).first()
        if found is None:
            raise Http404
        return found

    def action(self, name: str) -> Action:
        found = next((a for a in self.actions if a.key == name), None)
        if found is None:
            raise Http404
        return found

    def built(self, record, request, **parts) -> dict:
        """One record as the detail screen draws it."""
        history = services.history(self.key, record.pk)
        return {
            "register": self.key, "id": record.pk, "singular": self.singular, "register_title": self.title,
            "subtitle": "", "status": None, "notice": "", "facts": [], "texts": [], "tables": [],
            "history": [
                {"id": e.id, "at": e.at, "actor": person(e.actor), "what": e.what, "changes": e.changes, "comment": e.comment}
                for e in history
            ],
            "actions": [a.json(record, request) for a in self.actions if a.may(record, request.user)],
            **parts,
        }


REGISTERS: dict[str, Register] = {}


def register(cls):
    entry = cls()
    REGISTERS[entry.key] = entry
    return cls


# --- instruments ----------------------------------------------------------------------

STATUS_TONES = {
    InstrumentStatus.IN_SERVICE: "pass", InstrumentStatus.OUT_OF_SERVICE: "fail", InstrumentStatus.RETIRED: "muted",
    MaterialStatus.AVAILABLE: "pass", MaterialStatus.QUARANTINED: "warn", MaterialStatus.RETIRED: "muted",
    MethodStatus.DRAFT: "hot", MethodStatus.EFFECTIVE: "pass",
    ChangeStatus.OPEN: "warn", ChangeStatus.APPROVED: "info", ChangeStatus.IMPLEMENTED: "hot",
    ChangeStatus.CLOSED: "pass", ChangeStatus.REJECTED: "fail",
}


def _status(record) -> dict:
    return {"text": record.get_status_display(), "tone": STATUS_TONES.get(record.status, "muted")}


def _instrument_open(i, user) -> bool:
    return has_perm(user, services.INSTRUMENTS) and i.status != InstrumentStatus.RETIRED


def _instrument_fields(i: Instrument | None) -> list[Field]:
    return [
        Field("name", "Name", required=True, initial=i and i.name),
        Field("type", "Type", required=True, note="e.g. HPLC, balance, pH meter", initial=i and i.type),
        Field("location", "Location", required=True, initial=i and i.location),
        Field("serial_number", "Serial number", initial=i and i.serial_number),
    ]


def _usable_filter(qs, value):
    usable = Q(status=InstrumentStatus.IN_SERVICE, next_due__gte=timezone.localdate())
    return qs.filter(usable) if value == "yes" else qs.exclude(usable)


def _calibration_fields(i, request) -> list[Field]:
    return [
        Field("kind", "What was done", "select", required=True, options=choices(CalibrationKind),
              initial=CalibrationKind.CALIBRATION.value),
        Field("outcome", "Outcome", "select", required=True, options=choices(CalibrationOutcome),
              note="a failure takes the instrument out of service"),
        Field("performed_at", "When", "datetime", required=True),
        Field("performed_by_id", "Done by", "select", required=True, options=people(), initial=request.user.id),
        Field("reference", "Certificate or logbook number", required=True),
        Field("next_due", "Next due", "date", note="needed on a passing calibration"),
    ]


@register
class Instruments(Register):
    key = "instruments"
    sees = "instrument.view"
    title = "Instruments"
    singular = "instrument"
    description = "Each instrument, its logbook, and whether it can be used today."
    note = "An instrument can be used only while it is in service and its latest passing calibration has not run out."
    purpose = ("The Instrument list when results are entered offers only instruments that are in service and "
               "calibrated, so no result is tied to one that cannot be relied on.")
    adds = services.INSTRUMENTS
    add_label = "Add an instrument"
    columns = [
        Column("code", "Code"), Column("name", "Name"), Column("type", "Type"), Column("location", "Location"),
        Column("status", "Status"), Column("next_due", "Calibration due", "date"), Column("usable", "Today"),
    ]
    filters = [
        Filter("status", "Status", choices(InstrumentStatus), lambda qs, v: qs.filter(status=v)),
        Filter("usable", "Usable today", [("yes", "Usable"), ("no", "Not usable")], _usable_filter),
    ]
    search = ["code", "name", "type", "location", "serial_number"]
    search_hint = "Code, name, type or location"
    actions = [
        Action(
            "calibrate", "Record calibration or maintenance…", services.record_calibration, _instrument_open,
            title="Add to the logbook", hint="Logbook entries are never changed: a mistake is put right by a new entry.",
            done="Added to the logbook", comment="Notes", comment_required=False, fields=_calibration_fields,
        ),
        Action(
            "correct", "Correct…", services.correct_instrument, _instrument_open, title="Correct this instrument",
            hint="The old values stay on its history.", done="Corrected", comment="Why is this being corrected?",
            fields=lambda i, request: _instrument_fields(i),
        ),
        Action(
            "status", "Change status…", services.change_instrument_status, _instrument_open, title="Change its status",
            hint="Back in service needs a passing calibration since whatever took it out. Retiring it is final.",
            done="Status changed", comment="Why is the status changing?",
            fields=lambda i, request: [Field("status", "New status", "select", required=True,
                                             options=choices(InstrumentStatus), initial=i.status)],
        ),
    ]

    def records(self, request):
        return services.instruments_with_next_due()

    def rows(self, records, request):
        rows = []
        for i in records:
            problem = services.calibration_problem(i, i.next_due)
            rows.append({
                "id": i.pk, "to": f"/lab/instruments/{i.pk}",
                "cells": {
                    "code": cell(i.code, to=f"/lab/instruments/{i.pk}"), "name": i.name, "type": i.type,
                    "location": i.location, "status": cell(i.get_status_display(), tone=STATUS_TONES[i.status]),
                    "next_due": i.next_due,
                    "usable": cell("Not usable", tone="fail", sub=problem) if problem else cell("Usable", tone="pass"),
                },
            })
        return rows

    def add_fields(self, request):
        return [Field("code", "Code", required=True, note="never changes"), *_instrument_fields(None)]

    def add(self, by, data):
        return services.add_instrument(by, data)

    def detail(self, i, request):
        latest = services.latest_calibration(i)
        problem = services.instrument_problem(i)
        logbook = i.events.select_related("performed_by", "recorded_by")
        return self.built(
            i, request,
            title=i.code, subtitle=i.name, status=_status(i),
            notice=f"Not usable: {problem}" if problem else "",
            facts=[
                fact("Name", i.name), fact("Type", i.type), fact("Location", i.location),
                fact("Serial number", i.serial_number),
                fact("Latest passing calibration", latest.performed_at if latest else None, "datetime"),
                fact("Calibration due", latest.next_due if latest else None, "date"),
                fact("Certificate", latest.reference if latest else ""),
                fact("Added by", i.created_by.display_name()),
            ],
            tables=[
                table("Logbook", [
                    Column("at", "When", "datetime"), Column("kind", "What"), Column("outcome", "Outcome"),
                    Column("reference", "Reference"), Column("by", "Done by"), Column("next", "Next due", "date"),
                    Column("notes", "Notes"),
                ], [
                    {
                        "at": e.performed_at, "kind": e.get_kind_display(),
                        "outcome": cell(e.get_outcome_display(), tone="pass" if e.outcome == "PASS" else "fail"),
                        "reference": e.reference, "by": e.performed_by.display_name(), "next": e.next_due,
                        "notes": e.notes,
                    }
                    for e in logbook
                ], "Nothing in the logbook yet. It cannot be used until a passing calibration is recorded."),
                recent_use(ResultRecord.objects.filter(instrument=i), request),
            ],
        )


# --- materials ---------------------------------------------------------------------------

def _potency_text(m: Material | None) -> str:
    return format(m.potency.normalize(), "f") if m is not None and m.potency is not None else ""


def _material_open(m, user) -> bool:
    return has_perm(user, services.MATERIALS) and m.status != MaterialStatus.RETIRED


def _material_fields(m: Material | None) -> list[Field]:
    return [
        Field("kind", "Kind", "select", required=True, options=choices(MaterialKind), initial=m and m.kind),
        Field("code", "Code", required=True, initial=m and m.code),
        Field("name", "Name", required=True, initial=m and m.name),
        Field("lot", "Lot", required=True, initial=m and m.lot),
        Field("supplier", "Supplier", initial=m and m.supplier),
        Field("potency", "Potency", "number", note="optional", initial=_potency_text(m)),
        Field("received_on", "Received", "date", required=True, initial=m and m.received_on),
        Field("opened_on", "Opened", "date", initial=m and m.opened_on),
        Field("expiry_date", "Expiry", "date", required=True, initial=m and m.expiry_date),
    ]


def _material_usable_filter(qs, value):
    usable = Q(status=MaterialStatus.AVAILABLE, expiry_date__gte=timezone.localdate())
    return qs.filter(usable) if value == "yes" else qs.exclude(usable)


@register
class Materials(Register):
    key = "materials"
    sees = "material.view"
    title = "Standards and reagents"
    singular = "material"
    description = "Reference standards, reagents, columns and consumables, by lot."
    note = "A lot can be used only while it is available and not past its expiry date."
    purpose = "When results are entered, the analyst ticks the lots used. Only available lots in date are offered."
    adds = services.MATERIALS
    add_label = "Add a lot"
    columns = [
        Column("code", "Code"), Column("name", "Name"), Column("kind", "Kind"), Column("lot", "Lot"),
        Column("potency", "Potency"), Column("expiry", "Expiry", "date"), Column("status", "Status"),
        Column("usable", "Today"),
    ]
    filters = [
        Filter("kind", "Kind", choices(MaterialKind), lambda qs, v: qs.filter(kind=v)),
        Filter("status", "Status", choices(MaterialStatus), lambda qs, v: qs.filter(status=v)),
        Filter("usable", "Usable today", [("yes", "Usable"), ("no", "Not usable")], _material_usable_filter),
    ]
    search = ["code", "name", "lot", "supplier"]
    search_hint = "Code, name, lot or supplier"
    actions = [
        Action(
            "correct", "Correct…", services.correct_material, _material_open, title="Correct this lot",
            hint="The old values stay on its history. Kind, code and lot are fixed once a result has used it.",
            done="Corrected", comment="Why is this being corrected?", fields=lambda m, request: _material_fields(m),
        ),
        Action(
            "status", "Change status…", services.change_material_status, _material_open, title="Change its status",
            hint="Retiring a lot is final.", done="Status changed", comment="Why is the status changing?",
            fields=lambda m, request: [Field("status", "New status", "select", required=True,
                                             options=choices(MaterialStatus), initial=m.status)],
        ),
    ]

    def records(self, request):
        return Material.objects.all()

    def rows(self, records, request):
        rows = []
        for m in records:
            problem = services.material_problem(m)
            rows.append({
                "id": m.pk, "to": f"/lab/materials/{m.pk}",
                "cells": {
                    "code": cell(m.code, to=f"/lab/materials/{m.pk}"), "name": m.name, "kind": m.get_kind_display(),
                    "lot": m.lot, "potency": _potency_text(m),
                    "expiry": m.expiry_date, "status": cell(m.get_status_display(), tone=STATUS_TONES[m.status]),
                    "usable": cell("Not usable", tone="fail", sub=problem) if problem else cell("Usable", tone="pass"),
                },
            })
        return rows

    def add_fields(self, request):
        return [
            *_material_fields(None),
            Field("status", "Status", "select", required=True, options=choices(MaterialStatus)[:2],
                  initial=MaterialStatus.QUARANTINED.value, note="available means it has been checked"),
        ]

    def add(self, by, data):
        return services.add_material(by, data)

    def detail(self, m, request):
        problem = services.material_problem(m)
        return self.built(
            m, request,
            title=services.material_label(m), subtitle=f"{m.get_kind_display()}: {m.name}", status=_status(m),
            notice=f"Not usable: {problem}" if problem else "",
            facts=[
                fact("Kind", m.get_kind_display()), fact("Code", m.code), fact("Name", m.name), fact("Lot", m.lot),
                fact("Supplier", m.supplier),
                fact("Potency", _potency_text(m)),
                fact("Received", m.received_on, "date"), fact("Opened", m.opened_on, "date"),
                fact("Expiry", m.expiry_date, "date"), fact("Added by", m.created_by.display_name()),
            ],
            tables=[recent_use(ResultRecord.objects.filter(materials=m), request)],
        )


# --- the method master ----------------------------------------------------------------------

def _method_fields(m: Method | None) -> list[Field]:
    return [
        Field("title", "Title", required=True, initial=m and m.title),
        Field("document_ref", "Document reference", required=True, note="the controlled document or monograph",
              initial=m and m.document_ref),
        Field("validation_status", "Validation status", "select", required=True, options=choices(ValidationStatus),
              initial=m and m.validation_status),
    ]


def _may_approve(m: Method, user) -> bool:
    return (
        m.status == MethodStatus.DRAFT and has_perm(user, services.METHOD_APPROVE)
        and (user.id not in services.method_authors(m) or has_perm(user, OVERRIDE))
    )


def _may_draft_version(m: Method, user) -> bool:
    if not has_perm(user, services.METHODS) or m.status == MethodStatus.DRAFT:
        return False
    return not Method.objects.filter(code__iexact=m.code, status=MethodStatus.DRAFT).exists()


def _may_retire(m: Method, user) -> bool:
    if m.status == MethodStatus.RETIRED:
        return False
    return has_perm(user, services.METHODS if m.status == MethodStatus.DRAFT else services.METHOD_APPROVE)


@register
class Methods(Register):
    key = "methods"
    sees = "method.view"
    title = "Methods"
    singular = "method"
    description = "The method master: each version, its validation status, and who made it effective."
    note = "A specification can only be approved on effective, validated methods. A new version retires the old one."
    purpose = ("A test in a specification can name the method it follows. A draft method does nothing until "
               "someone else makes it effective.")
    adds = services.METHODS
    add_label = "Draft a method"
    add_hint = "A draft changes nothing until someone else makes it effective."
    columns = [
        Column("code", "Code"), Column("version", "Version"), Column("title", "Title"),
        Column("document", "Document"), Column("validation", "Validation"), Column("status", "Status"),
        Column("approved", "Effective from", "datetime"),
    ]
    filters = [
        Filter("status", "Status", choices(MethodStatus), lambda qs, v: qs.filter(status=v)),
        Filter("validation", "Validation", choices(ValidationStatus), lambda qs, v: qs.filter(validation_status=v)),
    ]
    search = ["code", "title", "document_ref"]
    search_hint = "Code, title or document"
    actions = [
        Action(
            "edit", "Edit…", services.edit_method,
            lambda m, user: m.status == MethodStatus.DRAFT and has_perm(user, services.METHODS),
            title="Edit this draft", hint="Whoever changes a draft can no longer make it effective.",
            done="Draft saved", comment="Comment", comment_required=False,
            fields=lambda m, request: _method_fields(m),
        ),
        Action(
            "approve", "Make effective…", services.approve_method, _may_approve, title="Make this version effective",
            hint="It takes effect now, and any earlier version is retired.", done="Now effective",
            signed=True, meaning="Approved by", digest=services.method_digest,
        ),
        Action(
            "new-version", "Draft a new version…", services.new_method_version, _may_draft_version,
            title="Draft a new version", hint="It starts as a copy. Nothing changes until someone else makes it effective.",
            done="Draft created", comment="Why is a new version needed?",
        ),
        Action(
            "retire", "Retire…", services.retire_method, _may_retire, title="Retire this version", tone="danger",
            hint="It stays on record. A specification cannot be approved on it again, and retiring it is final.",
            done="Retired", comment="Why is it being retired?",
        ),
    ]

    def records(self, request):
        return Method.objects.select_related("created_by", "edited_by", "approved_by")

    def rows(self, records, request):
        return [
            {
                "id": m.pk, "to": f"/lab/methods/{m.pk}",
                "cells": {
                    "code": cell(m.code, to=f"/lab/methods/{m.pk}"), "version": f"v{m.version}", "title": m.title,
                    "document": m.document_ref, "validation": m.get_validation_status_display(),
                    "status": cell(m.get_status_display(), tone=STATUS_TONES.get(m.status, "muted")),
                    "approved": m.approved_at,
                },
            }
            for m in records
        ]

    def add_fields(self, request):
        return [Field("code", "Code", required=True, note="stays the same across versions"), *_method_fields(None)]

    def add(self, by, data):
        return services.draft_method(by, data)

    def detail(self, m, request):
        user = request.user
        blocked = (
            m.status == MethodStatus.DRAFT and has_perm(user, services.METHOD_APPROVE)
            and not _may_approve(m, user)
        )
        versions = Method.objects.filter(code__iexact=m.code).select_related("approved_by")
        return self.built(
            m, request,
            title=str(m), subtitle=m.title, status=_status(m),
            notice="You drafted or changed this version, so someone else must make it effective." if blocked else "",
            facts=[
                fact("Code", m.code), fact("Version", m.version), fact("Title", m.title),
                fact("Document reference", m.document_ref), fact("Validation status", m.get_validation_status_display()),
                fact("Drafted by", m.created_by.display_name()),
                fact("Last changed by", m.edited_by.display_name() if m.edited_by_id else ""),
                fact("Approved by", m.approved_by.display_name() if m.approved_by_id else ""),
                fact("Approved at", m.approved_at, "datetime"),
                fact("Why this version", m.change_reason),
            ],
            tables=[table("Versions", [
                Column("version", "Version"), Column("status", "Status"), Column("validation", "Validation"),
                Column("approved", "Approved by"), Column("at", "When", "datetime"),
            ], [
                {
                    "version": cell(f"v{v.version}", to=f"/lab/methods/{v.pk}"),
                    "status": cell(v.get_status_display(), tone=STATUS_TONES.get(v.status, "muted")),
                    "validation": v.get_validation_status_display(),
                    "approved": v.approved_by.display_name() if v.approved_by_id else "", "at": v.approved_at,
                }
                for v in versions
            ])],
        )


# --- analyst qualification ----------------------------------------------------------------------

def _qualification_state(q: Qualification, today) -> dict:
    if q.revoked_at is not None:
        return {"text": "Revoked", "tone": "fail"}
    if q.expires_on < today:
        return {"text": "Expired", "tone": "muted"}
    return {"text": "Current", "tone": "pass"}


def _state_filter(qs, value):
    today = timezone.localdate()
    if value == "revoked":
        return qs.filter(revoked_at__isnull=False)
    live = qs.filter(revoked_at__isnull=True)
    return live.filter(expires_on__lt=today) if value == "expired" else live.filter(expires_on__gte=today)


def _method_codes() -> list[tuple]:
    codes = Method.objects.exclude(status=MethodStatus.RETIRED).order_by("code").values_list("code", flat=True)
    return [(c, c) for c in dict.fromkeys(codes)]


@register
class Qualifications(Register):
    key = "qualifications"
    sees = "qualification.view"
    title = "Analyst qualifications"
    singular = "qualification"
    description = "Who may run which method, and until when. It follows the method's code, not one version."
    note = "A result on a test with a method record is refused unless the person holds a current qualification."
    purpose = "When a test names a method, only an analyst currently qualified on it can enter that result."
    adds = services.QUALIFICATIONS
    add_label = "Grant a qualification"
    add_hint = "Granted by someone other than the analyst, with your password."
    columns = [
        Column("person", "Analyst"), Column("method", "Method"), Column("from", "Qualified on", "date"),
        Column("to", "Expires", "date"), Column("by", "Granted by"), Column("state", "State"),
    ]
    filters = [
        Filter("state", "State", [("current", "Current"), ("expired", "Expired"), ("revoked", "Revoked")], _state_filter),
    ]
    search = ["method", "user__first_name", "user__last_name", "user__username"]
    search_hint = "Analyst or method code"
    actions = [
        Action(
            "revoke", "Revoke…", services.revoke_qualification,
            lambda q, user: q.revoked_at is None and has_perm(user, services.QUALIFICATIONS),
            title="Revoke this qualification", hint="It stays on record, marked revoked. They can no longer enter results on this method.",
            tone="danger", done="Revoked", signed=True, meaning="Revoked by", comment="Why is it being revoked?",
        ),
    ]

    def records(self, request):
        return Qualification.objects.select_related("user", "qualified_by", "revoked_by")

    def rows(self, records, request):
        today = timezone.localdate()
        return [
            {
                "id": q.pk, "to": f"/lab/qualifications/{q.pk}",
                "cells": {
                    "person": cell(q.user.display_name(), to=f"/lab/qualifications/{q.pk}"), "method": q.method,
                    "from": q.qualified_on, "to": q.expires_on, "by": q.qualified_by.display_name(),
                    "state": _qualification_state(q, today),
                },
            }
            for q in records
        ]

    def add_fields(self, request):
        return [
            Field("user_id", "Analyst", "select", required=True, options=people()),
            Field("method", "Method", "select", required=True, options=_method_codes()),
            Field("qualified_on", "Qualified on", "date", required=True),
            Field("expires_on", "Expires on", "date", required=True),
            SIGNATURE,
        ]

    def add(self, by, data):
        return services.grant_qualification(by, data)

    def detail(self, q, request):
        return self.built(
            q, request,
            title=f"{q.user.display_name()} on {q.method}", subtitle="Analyst qualification",
            status=_qualification_state(q, timezone.localdate()),
            facts=[
                fact("Analyst", q.user.display_name()), fact("Method", q.method),
                fact("Qualified on", q.qualified_on, "date"), fact("Expires", q.expires_on, "date"),
                fact("Granted by", q.qualified_by.display_name()),
                fact("Revoked by", q.revoked_by.display_name() if q.revoked_by_id else ""),
                fact("Revoked at", q.revoked_at, "datetime"),
            ],
            texts=[{"label": "Why it was revoked", "text": q.revoke_reason}] if q.revoke_reason else [],
        )


# --- retained samples -----------------------------------------------------------------------------

def _retained_filter(qs, value):
    today = timezone.localdate()
    return qs.filter(until__lt=today) if value == "due" else qs.filter(until__gte=today)


@register
class Retained(Register):
    key = "retained"
    sees = "retained.view"
    title = "Retained samples"
    singular = "retained sample"
    description = "What is being held, until when, and what is due for destruction."
    note = "Only samples you can see. Open one to add a custody entry: destruction needs a witness."
    purpose = ("Samples kept after testing. One is destroyed only after its keep-until date, with a password "
               "and a witness.")
    columns = [
        Column("sample", "Sample"), Column("product", "Product"), Column("batch", "Batch / reference"),
        Column("location", "Kept at"), Column("quantity", "Quantity"), Column("until", "Retain until", "date"),
        Column("state", "State"),
    ]
    filters = [Filter("state", "State", [("held", "Held"), ("due", "Due for destruction")], _retained_filter)]
    search = ["sample_no", "batch_no", "reference", "product__name"]
    search_hint = "Sample, batch or product"

    def records(self, request):
        visible = samples_visible_to(request.user).order_by().values("pk")
        return (
            Sample.objects.filter(pk__in=visible, custody_events__action=CustodyAction.RETAINED)
            .exclude(custody_events__action=CustodyAction.DESTROYED)
            .annotate(until=Max("custody_events__retain_until"))
            .select_related("product").prefetch_related("custody_events")
        )

    def order(self, records):
        return records.order_by("until", "pk")

    def rows(self, records, request):
        today = timezone.localdate()
        rows = []
        for s in records:
            # The latest place it was put, and the latest amount said to be there.
            events = list(s.custody_events.all())
            location = next((e.location for e in reversed(events) if e.location), "")
            quantity = next((e.quantity for e in reversed(events) if e.quantity), "")
            due = s.until < today
            rows.append({
                "id": s.pk, "to": f"/samples/{s.pk}",
                "cells": {
                    "sample": cell(s.sample_no, to=f"/samples/{s.pk}"), "product": s.product.name,
                    "batch": s.batch_label, "location": location, "quantity": quantity, "until": s.until,
                    "state": cell("Due for destruction", tone="hot") if due else cell("Held", tone="info"),
                },
            })
        return rows


# --- change control ----------------------------------------------------------------------------------

def _change_fields(c: ChangeRecord | None) -> list[Field]:
    return [
        Field("title", "Title", required=True, initial=c and c.title),
        Field("category", "Category", "select", required=True, options=choices(ChangeCategory), initial=c and c.category),
        Field("description", "What is changing", "textarea", required=True, initial=c and c.description),
        Field("reason", "Why it is needed", "textarea", required=True, initial=c and c.reason),
        Field("impact_assessment", "Impact assessment", "textarea", required=True,
              note="on products, methods, validation, training and documents", initial=c and c.impact_assessment),
    ]


def _may_decide(c: ChangeRecord, user) -> bool:
    if c.status != ChangeStatus.OPEN or not has_perm(user, services.CHANGE_APPROVE):
        return False
    return user.id not in services.change_authors(c) or has_perm(user, OVERRIDE)


def _may_close(c: ChangeRecord, user) -> bool:
    if c.status != ChangeStatus.IMPLEMENTED or not has_perm(user, services.CHANGE_APPROVE):
        return False
    return user.id not in services.change_authors(c) | {c.implemented_by_id} or has_perm(user, OVERRIDE)


@register
class Changes(Register):
    key = "changes"
    sees = "change.view"
    title = "Change control"
    singular = "change record"
    description = "Proposed changes, from raising one through approval and implementation to closure."
    note = "Approved and closed by someone independent, each with their password. Every change is on the history."
    purpose = ("A new instrument, a method change or any other planned change, approved by someone other than "
               "the person who raised or implemented it.")
    adds = services.CHANGES
    add_label = "Raise a change"
    add_hint = "It stays open until someone independent approves or rejects it."
    columns = [
        Column("reference", "Reference"), Column("title", "Title"), Column("category", "Category"),
        Column("status", "Status"), Column("raised", "Raised by"), Column("at", "Raised", "datetime"),
    ]
    filters = [
        Filter("status", "Status", choices(ChangeStatus), lambda qs, v: qs.filter(status=v)),
        Filter("category", "Category", choices(ChangeCategory), lambda qs, v: qs.filter(category=v)),
    ]
    search = ["reference", "title", "description"]
    search_hint = "Reference, title or description"
    actions = [
        Action(
            "edit", "Edit…", services.edit_change,
            lambda c, user: c.status == ChangeStatus.OPEN and has_perm(user, services.CHANGES),
            title="Edit this change record", hint="Whoever changes it can no longer approve it. The old values stay on its history.",
            done="Saved", comment="Why is this being changed?", fields=lambda c, request: _change_fields(c),
        ),
        Action(
            "approve", "Approve…", services.approve_change, _may_decide, title="Approve this change",
            hint="What it says is fixed from here on.", done="Approved", signed=True, meaning="Approved by",
            digest=services.change_digest,
        ),
        Action(
            "reject", "Reject…", services.reject_change, _may_decide, title="Reject this change", tone="danger",
            hint="This ends the record. It stays on the register, marked rejected.", done="Rejected", signed=True,
            meaning="Rejected by", comment="Why is it being rejected?",
        ),
        Action(
            "implement", "Mark implemented…", services.implement_change,
            lambda c, user: c.status == ChangeStatus.APPROVED and has_perm(user, services.CHANGES),
            title="Mark it implemented", done="Marked implemented", comment="What was done?",
        ),
        Action(
            "close", "Close…", services.close_change, _may_close, title="Close this change",
            hint="Once closed, this record can never be changed.", done="Closed", signed=True, meaning="Closed by",
        ),
    ]

    def records(self, request):
        return ChangeRecord.objects.select_related(
            "raised_by", "approved_by", "rejected_by", "implemented_by", "closed_by"
        )

    def rows(self, records, request):
        return [
            {
                "id": c.pk, "to": f"/lab/changes/{c.pk}",
                "cells": {
                    "reference": cell(c.reference, to=f"/lab/changes/{c.pk}"), "title": c.title,
                    "category": c.get_category_display(),
                    "status": cell(c.get_status_display(), tone=STATUS_TONES[c.status]),
                    "raised": c.raised_by.display_name(), "at": c.raised_at,
                },
            }
            for c in records
        ]

    def add_fields(self, request):
        return _change_fields(None)

    def add(self, by, data):
        return services.raise_change(by, data)

    def detail(self, c, request):
        user = request.user
        blocked = (
            c.status in (ChangeStatus.OPEN, ChangeStatus.IMPLEMENTED) and has_perm(user, services.CHANGE_APPROVE)
            and not (_may_decide(c, user) or _may_close(c, user))
        )
        names = lambda who: who.display_name() if who else ""  # noqa: E731
        return self.built(
            c, request,
            title=c.reference, subtitle=c.title, status=_status(c),
            notice="You raised, changed or implemented this record, so someone independent must decide it." if blocked else "",
            facts=[
                fact("Category", c.get_category_display()), fact("Raised by", names(c.raised_by)),
                fact("Raised", c.raised_at, "datetime"), fact("Approved by", names(c.approved_by)),
                fact("Approved", c.approved_at, "datetime"), fact("Implemented by", names(c.implemented_by)),
                fact("Implemented", c.implemented_at, "datetime"), fact("Closed by", names(c.closed_by)),
                fact("Closed", c.closed_at, "datetime"), fact("Rejected by", names(c.rejected_by)),
            ],
            texts=[
                t for t in [
                    {"label": "What is changing", "text": c.description},
                    {"label": "Why it is needed", "text": c.reason},
                    {"label": "Impact assessment", "text": c.impact_assessment},
                    {"label": "What was done", "text": c.implementation_note},
                    {"label": "Why it was rejected", "text": c.rejected_reason},
                ] if t["text"]
            ],
        )
