"""
Labels and printable records. One label layout and one record layout serve
samples and batches alike: each view only says what goes on the page.
Printing a label or a record is recorded, like printing a certificate.
"""
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from rest_framework.decorators import api_view

from accounts.lab_zone import clock
from accounts.models import LabConfig
from audit.describe import describe
from audit.models import AuditEvent
from audit.services import record
from batches.api import batches_visible_to
from certificates.models import Certificate
from certificates.views import qr_data_uri
from execution.models import Attachment, ChecklistResponse, RetestRequest
from lims.models import TestResult
from lims.workflow import samples_visible_to


def _when(moment) -> str:
    return timezone.localtime(moment).strftime(f"%d %b %Y, {clock()}") if moment else "—"


def _day(date) -> str:
    return date.strftime("%d %b %Y") if date else "—"


def _value(result) -> str:
    value = f"{result.value_numeric.normalize():f}" if result.value_numeric is not None else result.value_text
    unit = result.test_definition.unit
    return f"{value} {unit}" if unit else value


def _pairs(title: str, pairs: list[tuple]) -> dict:
    return {"title": title, "pairs": [(k, v) for k, v in pairs if v not in ("", None)]}


def _table(title: str, columns: list[str], rows: list[list], empty: str = "None recorded.") -> dict:
    return {"title": title, "columns": columns, "rows": rows, "empty": empty}


def _sample(request, pk):
    sample = samples_visible_to(request.user).filter(pk=pk).select_related("batch", "product", "section").first()
    if sample is None:
        raise Http404("No such sample.")
    return sample


def _batch(request, pk):
    batch = batches_visible_to(request.user).filter(pk=pk).first()
    if batch is None:
        raise Http404("No such batch.")
    return batch


def _label(request, kind: str, identity: str, heading: str, lines: list[tuple]):
    record(request.user, "LABEL_PRINTED", kind, identity)
    return render(request, "prints/label.html", {
        "cfg": LabConfig.get(), "identity": identity, "heading": heading, "kind": kind,
        "lines": [(k, v) for k, v in lines if v not in ("", None)], "qr": qr_data_uri(identity),
    })


def _record(request, kind: str, identity: str, title: str, sections: list[dict]):
    record(request.user, "RECORD_PRINTED", kind, identity, kind=kind)
    return render(request, "prints/record.html", {
        "cfg": LabConfig.get(), "identity": identity, "title": title, "sections": sections,
        "printed_by": request.user.display_name(), "printed_at": _when(timezone.now()),
        "qr": qr_data_uri(identity),
    })


def _result_rows(results) -> list[list]:
    return [
        [r.sample.sample_no, r.test_definition.name, r.test_definition.limit_text, _value(r), r.get_outcome_display(),
         r.entered_by.display_name(), _when(r.entered_at)]
        for r in results
    ]


def _certificate_rows(certificates) -> list[list]:
    return [
        [c.sample.sample_no, f"Version {c.version}", c.content.get("overall", ""), c.get_status_display(),
         _when(c.created_at), ", ".join(f"{s.name_snapshot} ({_when(s.signed_at)})" for s in c.signatures.all())]
        for c in certificates
    ]


@api_view(["GET"])
def sample_label(request, pk):
    s = _sample(request, pk)
    return _label(request, "sample", s.sample_no, s.product.name, [
        ("Batch" if s.batch_id else "Reference", s.batch_label),
        ("Received", _day(timezone.localtime(s.received_at).date())),
        ("Due", _day(s.due_date)),
        ("Analyst", s.assigned_analyst.display_name()),
        ("Storage", s.storage_condition),
    ])


@api_view(["GET"])
def batch_label(request, pk):
    b = _batch(request, pk)
    return _label(request, "batch", b.internal_id, b.product.name, [
        ("Batch", b.official_batch_no),
        ("Product code", b.product.code),
        ("Manufactured", _day(b.manufacturing_date) if b.manufacturing_date else ""),
        ("Expiry", _day(b.expiry_date) if b.expiry_date else ""),
        ("Site", b.manufacturing_site),
    ])


@api_view(["GET"])
def sample_record(request, pk):
    s = _sample(request, pk)
    results = TestResult.objects.filter(sample=s).select_related("sample", "test_definition", "entered_by")
    answers = ChecklistResponse.objects.filter(sample=s).select_related("item__stage", "answered_by", "attachment")
    retests = RetestRequest.objects.filter(sample=s).select_related(
        "test_definition", "failed_result__test_definition", "retest_result__test_definition", "requested_by",
        "decided_by",
    )
    files = Attachment.objects.filter(sample=s).select_related("uploaded_by")
    certificates = Certificate.objects.filter(sample=s).select_related("sample").prefetch_related("signatures")
    return _record(request, "sample", s.sample_no, f"Sample record — {s.sample_no}", [
        _pairs("Sample", [
            ("Sample number", s.sample_no), ("Product", f"{s.product.name} ({s.product.code})"),
            ("Dosage form", s.product.dosage_form), ("Strength", s.product.strength),
            ("Official batch number", s.batch_no), ("Internal batch ID", s.batch.internal_id if s.batch_id else ""),
            ("Reference", s.reference), ("Section", s.section.name), ("Quantity received", s.quantity),
            ("Received from", s.received_from), ("Received at", _when(s.received_at)), ("Due", _day(s.due_date)),
            ("Date of manufacture", _day(s.manufacturing_date) if s.manufacturing_date else ""),
            ("Expiry / retest", _day(s.expiry_date) if s.expiry_date else ""),
            ("Storage condition", s.storage_condition), ("Analyst", s.assigned_analyst.display_name()),
            ("Specification", f"Version {s.specification.version}"), ("Status", s.status_label()),
        ]),
        _table("Test results, including every replaced value",
               ["Test", "Limit", "Result", "Outcome", "Entered by", "Entered at", "Replaced"],
               [[r.test_definition.name, r.test_definition.limit_text, _value(r), r.get_outcome_display(),
                 r.entered_by.display_name(), _when(r.entered_at),
                 f"{_when(r.superseded_at)} — {r.supersede_reason}" if r.is_superseded else ""] for r in results]),
        _table("Retests", ["Test", "Failed result", "Reason", "Status", "Decided by", "Retest result"],
               [[r.test_definition.name, _value(r.failed_result), r.reason, r.get_status_display(),
                 f"{r.decided_by.display_name()} ({_when(r.decided_at)})" if r.decided_by_id else "—",
                 _value(r.retest_result) if r.retest_result_id else "—"] for r in retests]),
        _table("Checks, including every changed answer",
               ["Step", "Check", "Answer", "Answered by", "At", "Changed"],
               [[a.item.step.title(), a.item.label, a.value or "—", a.answered_by.display_name(), _when(a.answered_at),
                 f"{_when(a.replaced_at)} — {a.change_reason}" if a.replaced_at else ""] for a in answers]),
        _table("Files", ["Step", "File", "Version", "Uploaded by", "At", "SHA-256"],
               [[a.step.title(), a.original_name, f"v{a.version}", a.uploaded_by.display_name(), _when(a.uploaded_at),
                 a.sha256[:16] + "…"] for a in files]),
        _table("Certificates", ["Sample", "Version", "Conclusion", "Status", "Created", "Signatures"],
               _certificate_rows(certificates)),
        _table("History", ["When", "Who", "From", "To", "Note"],
               [[_when(e.at), e.actor.display_name(), e.from_status, e.to_status, e.comment]
                for e in s.events.select_related("actor")]),
    ])


@api_view(["GET"])
def batch_record(request, pk):
    b = _batch(request, pk)
    samples = samples_visible_to(request.user).filter(batch=b).order_by("sample_no")
    results = TestResult.objects.filter(sample__in=samples, is_superseded=False).select_related(
        "sample", "test_definition", "entered_by"
    ).order_by("sample__sample_no", "test_definition__order")
    certificates = Certificate.objects.filter(sample__in=samples).select_related("sample").prefetch_related(
        "signatures"
    ).order_by("sample__sample_no", "version")
    history = AuditEvent.objects.filter(entity="batch", entity_id=b.internal_id).select_related("actor")
    return _record(request, "batch", b.internal_id, f"Batch record — {b.official_batch_no}", [
        _pairs("Batch", [
            ("Official batch number", b.official_batch_no), ("Internal ID", b.internal_id),
            ("Product", f"{b.product.name} ({b.product.code})"), ("Dosage form", b.product.dosage_form),
            ("Strength", b.product.strength), ("Manufacturing site", b.manufacturing_site),
            ("Date of manufacture", _day(b.manufacturing_date) if b.manufacturing_date else ""),
            ("Expiry / retest", _day(b.expiry_date) if b.expiry_date else ""), ("Batch size", b.batch_size),
            ("Notes", b.notes), ("Recorded", _when(b.created_at)),
        ]),
        _table("Samples", ["Sample", "Received", "Due", "Analyst", "Status"],
               [[s.sample_no, _when(s.received_at), _day(s.due_date), s.assigned_analyst.display_name(),
                 s.status_label()] for s in samples]),
        _table("Current test results", ["Sample", "Test", "Limit", "Result", "Outcome", "Entered by", "Entered at"],
               _result_rows(results)),
        _table("Certificates", ["Sample", "Version", "Conclusion", "Status", "Created", "Signatures"],
               _certificate_rows(certificates)),
        _table("Documents", ["Title", "Kind", "Version", "Uploaded by", "At", "State"],
               [[d.title, d.get_doc_type_display(), f"v{d.version}", d.uploaded_by.display_name(), _when(d.uploaded_at),
                 "Current" if d.is_current else "Withdrawn" if d.withdrawn_at else "Replaced"]
                for d in b.documents.select_related("uploaded_by")]),
        _table("History", ["When", "Who", "What"],
               [[_when(e.at), e.actor.display_name() if e.actor_id else "System", describe(e)["sentence"]]
                for e in history]),
    ])
