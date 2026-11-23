"""
Reports about one thing: a sample's full history, a batch's QC summary, a
product's quality history. Each is built as a plain document (sections made of
facts, tables and trends), so the screen and the PDF draw the same content.

Everything in a document is read from the records at the moment it is built.
What it holds is the record as it stands, superseded and replaced entries
included: nothing is left out because something later came after it.
"""
from collections import defaultdict
from statistics import fmean

from django.db.models import Q
from django.utils import timezone

from certificates.models import ANALYSED, CertStatus, Certificate, PrintEvent, Signature
from certificates.services import signature_chain
from execution import rules
from execution.models import (
    Assignment,
    Attachment,
    ChecklistResponse,
    ReceiptCompletion,
    RetestRequest,
    SampleHold,
    StepComment,
    Waiver,
)
from labrecords.rawdata import payload as raw_data_payload
from lims.models import Outcome, Sample, TestResult
from lims.workflow import samples_visible_to
from quality.models import Investigation, InvestigationKind
from quality.services import visible_investigations
from .batches import CERT_TONES, disposition_cell
from .engine import Cell, cell_json, text_of
from .records import (
    INVESTIGATION_TONES,
    OUTCOME_TONES,
    batch_text,
    measure,
    result_value,
    tests_required,
    with_unit,
)
from .results import COMPARABLE, comparable_key
from .samples import stage_of


def facts(*pairs) -> dict:
    return {
        "kind": "facts",
        "items": [{"label": label, "value": text_of(value) or "—"} for label, value in pairs],
    }


def table(heading: str, columns: list[tuple], rows: list[dict], empty: str = "None on record.") -> dict:
    """columns: (key, label, share of the page's width)."""
    return {
        "kind": "table",
        "heading": heading,
        "columns": [{"key": k, "label": label, "width": w} for k, label, w in columns],
        "rows": [{k: cell_json(row.get(k)) for k, _, _ in columns} for row in rows],
        "empty": empty,
    }


def note(text: str) -> dict:
    return {"kind": "note", "text": text}


def section(title: str, *parts) -> dict:
    return {"title": title, "parts": [p for p in parts if p]}


def _action_text(action) -> str:
    verified = f" (verified by {action.verified_by.display_name()})" if action.verified_by_id else ""
    return f"{action.get_kind_display()}: {action.description}{verified}"


def _investigation_rows(cases) -> list[dict]:
    rows = []
    for i in cases:
        actions = list(i.actions.all())
        rows.append({
            "reference": Cell(i.reference, to=f"/investigations/{i.pk}"),
            "kind": i.get_kind_display(),
            "test": i.test_definition.name if i.test_definition_id else "",
            "status": Cell(i.get_status_display(), tone=INVESTIGATION_TONES[i.status]),
            "root_cause": i.root_cause,
            "actions": "; ".join(_action_text(a) for a in actions),
            "outcome": i.outcome,
            "closure": f"{i.closed_by.display_name()}, {text_of(i.closed_at)}" if i.closed_by_id else "",
        })
    return rows


INVESTIGATION_COLUMNS = [
    ("reference", "Reference", 1), ("kind", "Kind", 0.9), ("test", "Test", 1), ("status", "Status", 1),
    ("root_cause", "Root cause", 1.4), ("actions", "Actions", 1.4), ("outcome", "Final outcome", 1.4),
    ("closure", "Closure approval", 1.1),
]


def _retest_rows(requests) -> list[dict]:
    rows = []
    for r in requests:
        later = r.retest_result
        rows.append({
            "sample": r.sample.sample_no,
            "test": r.test_definition.name,
            "kind": r.get_kind_display(),
            "original": Cell(with_unit(r.failed_result), tone="fail"),
            "reason": r.reason,
            "requested": f"{r.requested_by.display_name()}, {text_of(r.requested_at)}",
            "decision": Cell(r.get_status_display(), sub=(
                f"{r.decided_by.display_name()}, {text_of(r.decided_at)}" if r.decided_by_id else ""
            )),
            "later": Cell(with_unit(later), tone=OUTCOME_TONES.get(later.outcome, "")) if later else "",
        })
    return rows


RETEST_COLUMNS = [
    ("test", "Test", 1), ("kind", "Type", 0.7), ("original", "Original result", 0.8), ("reason", "Reason", 1.6),
    ("requested", "Requested", 1.3), ("decision", "Authorization", 1.3), ("later", "Subsequent result", 0.9),
]


def _result_rows(results) -> list[dict]:
    rows = []
    for r in results:
        rows.append({
            "sample": Cell(r.sample.sample_no, to=f"/reports/sample-history/{r.sample_id}"),
            "test": r.test_definition.name,
            "method": Cell(r.test_definition.method, sub=r.test_definition.source),
            "spec": f"v{r.sample.specification.version}",
            "limit": r.test_definition.limit_text,
            "result": with_unit(r),
            "outcome": Cell(r.get_outcome_display(), tone=OUTCOME_TONES.get(r.outcome, "")),
            "state": Cell("Superseded", tone="muted", sub=r.supersede_reason) if r.is_superseded else "Current",
            "entered": f"{r.entered_by.display_name()}, {text_of(r.entered_at)}",
        })
    return rows


def _raw_data_rows(results) -> list[dict]:
    rows = []
    for r in results:
        raw = raw_data_payload(r)
        if raw is None:
            continue
        rows.append({
            "test": r.test_definition.name,
            "result": with_unit(r),
            "worksheet": raw["worksheet_ref"],
            "instrument": raw["instrument"]["code"] if raw["instrument"] else "",
            "materials": "; ".join(f"{m['code']} lot {m['lot']}" for m in raw["materials"]),
            "readings": "; ".join(f"{x['label']}: {x['value']}" for x in raw["readings"]),
            "mean": raw["mean"],
            "notes": raw["notes"],
        })
    return rows


def _custody_rows(sample: Sample) -> list[dict]:
    return [
        {
            "action": e.get_action_display(), "location": e.location,
            "from": e.from_person.display_name() if e.from_person_id else "",
            "to": e.to_person.display_name() if e.to_person_id else "",
            "quantity": e.quantity,
            "until": e.retain_until,
            "witness": e.witness.display_name() if e.witness_id else "",
            "by": f"{e.by.display_name()}, {text_of(e.at)}",
            "note": e.note,
        }
        for e in sample.custody_events.select_related("from_person", "to_person", "witness", "by")
    ]


def sample_history(sample: Sample) -> dict:
    steps = {s.key: s.name for s in rules.steps(sample)}

    def step_name(key: str) -> str:
        return steps.get(key, key) or "Whole sample"

    receipt = ReceiptCompletion.objects.filter(sample=sample).select_related("completed_by").first()
    answers = list(
        ChecklistResponse.objects.filter(sample=sample)
        .select_related("item__stage", "answered_by", "replaced_by", "attachment").order_by("answered_at", "id")
    )

    def answer_row(a) -> dict:
        return {
            "step": step_name(a.item.step),
            "attempt": a.attempt,
            "item": a.item.label,
            "answer": rules.display_answer(a.item, a),
            "conforms": Cell("Conforms", tone="pass") if a.conforms else Cell("Does not conform", tone="fail"),
            "by": f"{a.answered_by.display_name()}, {text_of(a.answered_at)}",
            "state": Cell("Replaced", tone="muted", sub=a.change_reason) if a.replaced_at else "Current",
        }

    checks = [("item", "Check", 1.5), ("answer", "Answer", 1), ("conforms", "Conformance", 0.8),
              ("by", "Answered", 1.3), ("state", "State", 0.9)]

    registration = section(
        "1. Registration and receipt",
        facts(
            ("Sample ID", sample.sample_no), ("Product", sample.product.name), ("Product code", sample.product.code),
            ("Batch / Lot", sample.batch_label), ("Sample type", sample.product.get_sample_type_display() or "Not set"),
            ("Section", sample.section.name), ("Quantity", sample.quantity), ("Received from", sample.received_from),
            ("Received", sample.received_at), ("Due", sample.due_date),
            ("Manufactured", sample.manufacturing_date), ("Expiry / retest", sample.expiry_date),
            ("Storage", sample.storage_condition), ("Registered by", sample.registered_by.display_name()),
            ("Specification", f"{sample.product.code} v{sample.specification.version}, "
                              f"effective {text_of(sample.specification.effective_date)}"),
            ("Review workflow", str(sample.workflow_version)),
            ("Current stage", stage_of(sample)), ("Status", sample.status_label()),
        ),
        table("Receipt checks", checks, [answer_row(a) for a in answers if a.item.for_receipt],
              "No receipt checks on this sample's workflow."),
        note(f"Receipt checks completed by {receipt.completed_by.display_name()}, {text_of(receipt.completed_at)}.")
        if receipt else None,
        table("Chain of custody", [
            ("action", "What happened", 0.8), ("location", "Where", 0.9), ("from", "From", 0.9), ("to", "To", 0.9),
            ("quantity", "Quantity", 0.6), ("until", "Retain until", 0.8), ("witness", "Witness", 0.9),
            ("by", "Recorded", 1.3), ("note", "Note", 1.2),
        ], _custody_rows(sample), "No custody entries recorded."),
    )

    assignment = section("2. Assignment", table(
        "", [("step", "Step", 0.9), ("kind", "How", 0.8), ("from", "From", 1), ("to", "To", 1),
             ("status", "Status", 0.9), ("when", "When", 1.1), ("note", "Note or reason", 1.6)],
        [
            {
                "step": step_name(a.step), "kind": a.get_kind_display(),
                "from": a.from_user.display_name() if a.from_user_id else "",
                "to": a.to_user.display_name(), "status": a.get_status_display(), "when": a.created_at,
                "note": " — ".join(filter(None, [a.note, a.response_reason])),
            }
            for a in Assignment.objects.filter(sample=sample).select_related("from_user", "to_user")
        ],
    ))

    results = list(
        TestResult.objects.filter(sample=sample)
        .select_related("sample__specification", "test_definition", "entered_by", "superseded_by_user",
                        "raw_data__instrument")
        .prefetch_related("raw_data__materials", "raw_data__readings")
        .order_by("entered_at", "id")
    )
    testing = section(
        "3. Testing and recorded results",
        table("Results, every value ever entered, oldest first", [
            ("test", "Test", 1.1), ("method", "Method", 0.9), ("limit", "Acceptance criteria", 1),
            ("result", "Result", 0.7), ("outcome", "Pass/fail", 0.7), ("state", "State", 1.1),
            ("entered", "Entered", 1.3),
        ], _result_rows(results), "No results entered yet."),
        table("Raw data behind the results", [
            ("test", "Test", 1), ("result", "Result", 0.6), ("worksheet", "Worksheet", 0.8),
            ("instrument", "Instrument", 0.8), ("materials", "Materials", 1.2), ("readings", "Readings", 1.3),
            ("mean", "Mean", 0.5), ("notes", "Notes", 1),
        ], _raw_data_rows(results), "No raw data recorded with these results."),
        table("Checklists at each step", [("step", "Step", 0.8), ("attempt", "Attempt", 0.5), *checks],
              [answer_row(a) for a in answers if not a.item.for_receipt], "No checklist answers recorded."),
    )

    evidence = section("4. Attachments and supporting evidence", table(
        "", [("step", "Step", 0.8), ("name", "File", 1.5), ("version", "Version", 0.5), ("sha", "SHA-256", 1),
             ("by", "Uploaded", 1.2), ("state", "State", 1.2)],
        [
            {
                "step": step_name(f.step), "name": f.original_name, "version": f.version, "sha": f.sha256[:16],
                "by": f"{f.uploaded_by.display_name()}, {text_of(f.uploaded_at)}",
                "state": (
                    Cell("Withdrawn", tone="muted", sub=f.withdraw_reason) if f.withdrawn_at
                    else Cell("Replaced", tone="muted") if f.replaced_by_id else "Current"
                ),
            }
            for f in Attachment.objects.filter(sample=sample).select_related("uploaded_by")
        ],
    ))

    failed = [r for r in results if r.outcome == Outcome.FAIL]
    cases = Investigation.objects.filter(sample=sample).select_related("test_definition", "closed_by") \
        .prefetch_related("actions__verified_by").order_by("opened_at")
    failures = section(
        "5. Failed tests and investigations",
        table("Failed results", [
            ("test", "Test", 1.1), ("limit", "Acceptance criteria", 1), ("result", "Result", 0.7),
            ("state", "State", 1.1), ("entered", "Entered", 1.3),
        ], _result_rows(failed), "No result of this sample has failed."),
        table("Investigations", INVESTIGATION_COLUMNS, _investigation_rows(cases), "No investigation opened."),
    )

    retests = section("6. Retesting history", table(
        "", RETEST_COLUMNS,
        _retest_rows(RetestRequest.objects.filter(sample=sample).select_related(
            "sample", "test_definition", "failed_result__test_definition", "retest_result__test_definition",
            "requested_by", "decided_by",
        ).order_by("requested_at")),
    ))

    returned = Certificate.objects.filter(sample=sample, returned_at__isnull=False).select_related("returned_by")
    review = section(
        "7. Reviewer comments and corrections",
        table("Notes and review feedback", [
            ("step", "Step", 0.9), ("kind", "Kind", 0.8), ("by", "Written", 1.3), ("text", "Comment", 2.4),
        ], [
            {
                "step": step_name(c.step), "kind": c.get_kind_display(),
                "by": f"{c.author.display_name()}, {text_of(c.created_at)}",
                "text": f"(amends an earlier comment) {c.body}" if c.amends_id else c.body,
            }
            for c in StepComment.objects.filter(sample=sample).select_related("author")
        ]),
        table("Work sent back", [
            ("version", "Certificate version", 0.7), ("stage", "From", 0.9), ("by", "By", 1.2), ("reason", "Reason", 2.2),
        ], [
            {
                "version": f"v{c.version}", "stage": step_name(c.returned_stage),
                "by": f"{c.returned_by.display_name() if c.returned_by_id else ''}, {text_of(c.returned_at)}",
                "reason": c.superseded_reason,
            }
            for c in returned
        ]),
        table("Requirements waived", [
            ("step", "Step", 0.9), ("item", "Requirement", 1.4), ("by", "Waived", 1.3), ("reason", "Reason", 1.8),
        ], [
            {
                "step": step_name(w.item.step), "item": w.item.label,
                "by": f"{w.waived_by.display_name()}, {text_of(w.waived_at)}", "reason": w.reason,
            }
            for w in Waiver.objects.filter(sample=sample).select_related("item__stage", "waived_by")
        ]),
        table("Holds", [
            ("step", "At step", 0.8), ("placed", "Placed", 1.3), ("reason", "Reason", 1.6), ("released", "Released", 1.3),
        ], [
            {
                "step": step_name(h.step), "placed": f"{h.placed_by.display_name()}, {text_of(h.placed_at)}",
                "reason": h.reason,
                "released": (f"{h.released_by.display_name()}, {text_of(h.released_at)}: {h.release_comment}"
                             if h.released_at else "Still on hold"),
            }
            for h in SampleHold.objects.filter(sample=sample).select_related("placed_by", "released_by")
        ]),
    )

    certs = list(Certificate.objects.filter(sample=sample).order_by("version"))
    signatures = Signature.objects.filter(certificate__sample=sample).select_related("certificate").order_by("signed_at")
    meanings = {s.code: s.signature_title for s in sample.workflow_version.stages.all()}
    approvals = section(
        "8. Approvals and certificates",
        table("Certificate versions", [
            ("number", "Certificate no.", 1.1), ("status", "Status", 1.2), ("created", "Frozen", 1.1),
            ("hash", "Content hash", 1), ("reason", "Why superseded", 1.6),
        ], [
            {
                "number": Cell(f"{sample.sample_no}/v{c.version}", to=f"/certificates/{c.pk}"),
                "status": Cell(c.get_status_display(), tone=CERT_TONES[c.status]),
                "created": c.created_at, "hash": c.content_hash[:16], "reason": c.superseded_reason,
            }
            for c in certs
        ], "No certificate has been built yet."),
        table("Signatures", [
            ("version", "Version", 0.5), ("title", "Signed as", 1), ("name", "Name", 1.2), ("when", "When", 1.1),
            ("hash", "Hash signed", 1),
        ], [
            {
                "version": f"v{s.certificate.version}",
                "title": "Analysed by" if s.meaning == ANALYSED else meanings.get(s.meaning, s.meaning),
                "name": s.name_snapshot, "when": s.signed_at, "hash": s.content_hash[:16],
            }
            for s in signatures
        ], "Not signed yet."),
        table("Copies printed", [("version", "Version", 0.5), ("copy", "Copy", 0.6), ("by", "Printed", 2)], [
            {
                "version": f"v{p.certificate.version}",
                "copy": "Original" if p.copy_number == 1 else f"Duplicate {p.copy_number}",
                "by": f"{p.printed_by.display_name()}, {text_of(p.printed_at)}",
            }
            for p in PrintEvent.objects.filter(certificate__in=certs).select_related("certificate", "printed_by")
        ], "Not printed."),
    )

    movements = section("9. Movement through the workflow", table(
        "", [("when", "When", 1.1), ("who", "Who", 1), ("from", "From", 0.8), ("to", "To", 0.8), ("comment", "Comment", 2.4)],
        [
            {"when": e.at, "who": e.actor.display_name(), "from": e.from_status, "to": e.to_status, "comment": e.comment}
            for e in sample.events.select_related("actor")
        ],
    ))

    return {
        "title": "Sample History Report",
        "reference": sample.sample_no,
        "subtitle": f"{sample.product.name}, {batch_text(sample)}",
        "links": [{"label": "Open the sample", "to": f"/samples/{sample.pk}"}],
        "sections": [registration, assignment, testing, evidence, failures, retests, review, approvals, movements],
    }


def batch_summary(user, batch) -> dict | None:
    product = batch.product
    samples = list(
        samples_visible_to(user).filter(batch=batch)
        .select_related("specification", "workflow_version").order_by("received_at")
    )
    if not samples:
        return None
    ids = [s.pk for s in samples]
    required = tests_required(s.specification_id for s in samples)
    results = list(
        TestResult.objects.filter(sample_id__in=ids)
        .select_related("sample__specification", "test_definition", "entered_by")
        .order_by("sample__received_at", "test_definition__order", "entered_at")
    )
    entered, failing = defaultdict(int), defaultdict(int)
    for r in results:
        entered[r.sample_id] += 0 if r.is_superseded else 1
        failing[r.sample_id] += 1 if r.outcome == Outcome.FAIL else 0

    # A deviation names its batch in words, so the case it was typed in does not matter.
    cases = visible_investigations(user).filter(
        Q(sample__batch=batch) | Q(product=product, batch_no__iexact=batch.official_batch_no)) \
        .prefetch_related("actions__verified_by").order_by("opened_at")
    open_cases = [i for i in cases if i.status != "CLOSED"]
    certs = list(
        Certificate.objects.filter(sample_id__in=ids).select_related("sample").prefetch_related("signatures", "prints")
        .order_by("sample_id", "version")
    )
    live = [c for c in certs if c.status != CertStatus.SUPERSEDED]
    documents = Attachment.objects.filter(sample_id__in=ids, withdrawn_at__isnull=True, replaced_by__isnull=True) \
        .select_related("sample", "uploaded_by")

    batch_documents = batch.documents.filter(withdrawn_at__isnull=True, replaced_by__isnull=True) \
        .select_related("uploaded_by")
    latest = batch.latest_disposition()
    return {
        "title": "Batch QC Summary",
        "reference": batch.official_batch_no,
        "subtitle": product.name,
        "links": [
            {"label": "Open the batch record", "to": f"/batches/{batch.pk}"},
            {"label": "Product quality history", "to": f"/reports/product/{product.pk}"},
        ],
        "sections": [
            section(
                "Batch",
                facts(
                    ("Official batch number", batch.official_batch_no), ("Internal ID", batch.internal_id),
                    ("Product", product.name), ("Product code", product.code),
                    ("Sample type", product.get_sample_type_display() or "Not set"), ("Section", product.section.name),
                    ("Manufacturing site", batch.manufacturing_site), ("Batch size", batch.batch_size),
                    ("Manufactured", batch.manufacturing_date), ("Expiry / retest", batch.expiry_date),
                    ("Samples", len(samples)), ("Open investigations", len(open_cases)),
                    ("Batch disposition", latest.get_decision_display() if latest else "Not decided"),
                ),
                note(
                    "Released certificates and passing tests are not a release decision for the batch. "
                    "That is the disposition, decided by the quality unit."
                ),
                table("Disposition decisions, newest first", [
                    ("decision", "Decision", 0.7), ("reason", "Reason", 2), ("by", "Decided", 1.3),
                    ("hash", "Hash of what was decided on", 1),
                ], [
                    {
                        "decision": disposition_cell(d),
                        "reason": d.reason,
                        "by": f"{d.decided_by.display_name()}, {text_of(d.decided_at)}",
                        "hash": d.basis_hash[:16],
                    }
                    for d in batch.dispositions.select_related("decided_by").order_by("-id")
                ], "Not decided."),
            ),
            section("Associated samples and tests", table(
                "", [("sample", "Sample ID", 1.1), ("spec", "Specification", 0.8), ("analyst", "Analyst", 1),
                     ("stage", "Current stage", 0.8), ("required", "Tests required", 0.7),
                     ("completed", "Tests completed", 0.7), ("failed", "Failed results", 0.7)],
                [
                    {
                        "sample": Cell(s.sample_no, to=f"/reports/sample-history/{s.pk}"),
                        "spec": f"v{s.specification.version}", "analyst": s.assigned_analyst.display_name(),
                        "stage": stage_of(s), "required": required.get(s.specification_id, 0),
                        "completed": entered[s.pk],
                        "failed": Cell(failing[s.pk], tone="fail") if failing[s.pk] else 0,
                    }
                    for s in samples
                ],
            )),
            section("Test results and applicable specifications", table(
                "", [("sample", "Sample ID", 1), ("test", "Test", 1.1), ("spec", "Spec", 0.4), ("method", "Method", 0.9),
                     ("limit", "Acceptance criteria", 1), ("result", "Result", 0.7), ("outcome", "Pass/fail", 0.6),
                     ("state", "State", 0.9), ("entered", "Entered", 1.2)],
                _result_rows(results), "No results entered yet.",
            )),
            section("Investigations and deviations", table(
                "", INVESTIGATION_COLUMNS, _investigation_rows(cases), "None opened for this batch.",
            )),
            section("Retests", table(
                "", [("sample", "Sample ID", 1), *RETEST_COLUMNS],
                _retest_rows(RetestRequest.objects.filter(sample_id__in=ids).select_related(
                    "sample", "test_definition", "failed_result__test_definition", "retest_result__test_definition",
                    "requested_by", "decided_by",
                ).order_by("requested_at")),
            )),
            section("Approvals", table(
                "", [("certificate", "Certificate no.", 1.1), ("title", "Signature", 1.1), ("name", "Name", 1.2),
                     ("when", "When", 1.1)],
                [
                    {
                        "certificate": f"{c.sample.sample_no}/v{c.version}", "title": link["title"],
                        "name": link["signature"].name_snapshot if link["signature"] else "Not signed yet",
                        "when": link["signature"].signed_at if link["signature"] else None,
                    }
                    for c in live for link in signature_chain(c)
                ], "No certificate has been built yet.",
            )),
            section(
                "Certificates and documents",
                table("Certificates", [
                    ("number", "Certificate no.", 1.1), ("status", "Status", 1.2), ("copies", "Copies printed", 0.7),
                ], [
                    {
                        "number": Cell(f"{c.sample.sample_no}/v{c.version}", to=f"/certificates/{c.pk}"),
                        "status": Cell(c.get_status_display(), tone=CERT_TONES[c.status]),
                        "copies": len(c.prints.all()),
                    }
                    for c in certs
                ]),
                table("Documents on the batch", [
                    ("type", "Type", 1), ("title", "Document", 1.5), ("version", "Version", 0.5),
                    ("by", "Uploaded", 1.3), ("sha", "SHA-256", 1),
                ], [
                    {
                        "type": d.get_doc_type_display(), "title": d.title, "version": d.version,
                        "by": f"{d.uploaded_by.display_name()}, {text_of(d.uploaded_at)}", "sha": d.sha256[:16],
                    }
                    for d in batch_documents
                ]),
                table("Documents on the samples", [
                    ("sample", "Sample ID", 1), ("name", "File", 1.6), ("by", "Uploaded", 1.3), ("sha", "SHA-256", 1),
                ], [
                    {
                        "sample": f.sample.sample_no, "name": f.original_name,
                        "by": f"{f.uploaded_by.display_name()}, {text_of(f.uploaded_at)}", "sha": f.sha256[:16],
                    }
                    for f in documents
                ]),
            ),
        ],
    }


def _trend(key: tuple, results: list) -> dict:
    t = results[0].test_definition
    points = [
        {
            "date": timezone.localtime(r.entered_at).date().isoformat(),
            "label": text_of(r.entered_at),
            "y": float(result_value(r)),
            "text": with_unit(r),
            "batch": r.sample.batch_label,
            "sample": r.sample.sample_no,
            "spec": f"v{r.sample.specification.version}",
            "outcome": r.outcome,
            "to": f"/reports/sample-history/{r.sample_id}",
        }
        for r in results
    ]
    return {
        "kind": "trend",
        "heading": t.name,
        "sub": " · ".join(filter(None, [t.method, t.limit_text])),
        "unit": t.unit,
        "low": float(t.min_value) if t.min_value is not None else None,
        "high": float(t.max_value) if t.max_value is not None else None,
        "points": points,
    }


def product_history(user, product, window) -> dict | None:
    visible = samples_visible_to(user).filter(product=product)
    if not visible.exists():
        return None
    results = list(
        window.apply(
            TestResult.objects.filter(sample__in=visible.order_by().values("pk")), "entered_at"
        ).select_related("sample__specification", "test_definition").order_by("entered_at", "id")
    )
    groups = defaultdict(list)
    for r in results:
        groups[comparable_key(r)].append(r)

    rates = []
    for key, members in groups.items():
        t = members[0].test_definition
        graded = [r for r in members if r.outcome != Outcome.REPORTED]
        failed = sum(1 for r in graded if r.outcome == Outcome.FAIL)
        rates.append({
            "test": t.name, "method": t.method, "limit": t.limit_text, "graded": len(graded),
            "passed": len(graded) - failed,
            "failed": Cell(failed, tone="fail") if failed else 0,
            "rate": f"{100 * failed / len(graded):.1f}%" if graded else "",
        })

    numeric = {k: [r for r in v if not r.is_superseded and r.value_numeric is not None] for k, v in groups.items()}
    numeric = {k: v for k, v in numeric.items() if len(v) >= 2}

    variation = []
    for key, members in numeric.items():
        by_batch = defaultdict(list)
        for r in members:
            if r.sample.batch_id:
                by_batch[r.sample.batch_id].append(float(result_value(r)))
        if len(by_batch) < 2:
            continue
        averages = [fmean(values) for values in by_batch.values()]
        t = members[0].test_definition
        variation.append({
            "test": t.name, "method": t.method, "batches": len(by_batch),
            "low": measure(min(averages), t.decimals + 1), "high": measure(max(averages), t.decimals + 1),
            "spread": measure(max(averages) - min(averages), t.decimals + 1), "unit": t.unit,
        })

    # The product's own specification first, then each QC stage's own tests.
    specs = product.specifications.order_by("stage_key", "version")
    cases = visible_investigations(user).filter(product=product, kind=InvestigationKind.OOS).order_by("opened_at")
    recurring = defaultdict(list)
    for i in cases:
        recurring[i.test_definition.name if i.test_definition_id else "Not tied to a test"].append(i)

    graded = [r for r in results if r.outcome != Outcome.REPORTED]
    failed = sum(1 for r in graded if r.outcome == Outcome.FAIL)
    return {
        "title": "Product Quality History",
        "reference": product.code,
        "subtitle": product.name,
        "period": window.label,
        "links": [{"label": "Batches of this product", "to": f"/reports/batches?product={product.pk}"}],
        "sections": [
            section("Overview", facts(
                ("Product", product.name), ("Code", product.code), ("Section", product.section.name),
                ("Sample type", product.get_sample_type_display() or "Not set"),
                ("Period", window.label), ("Graded results", len(graded)), ("Failed results", failed),
                ("Failed, all tests pooled", f"{100 * failed / len(graded):.1f}%" if graded else "—"),
            )),
            section(
                "Pass and fail by test",
                table("", [("test", "Test", 1.3), ("method", "Method", 1), ("limit", "Limit", 1), ("graded", "Graded", 0.5),
                           ("passed", "Passed", 0.5), ("failed", "Failed", 0.5), ("rate", "Failure rate", 0.6)],
                      rates, "No results in this period."),
                note(f"{COMPARABLE} Superseded results stay counted, so a failure does not vanish after a retest."),
            ),
            section(
                "Trends over time",
                *[_trend(key, members) for key, members in numeric.items()],
                None if numeric else note("At least two comparable numeric results are needed for a trend."),
            ),
            section("Batch-to-batch variation", table(
                "", [("test", "Test", 1.3), ("method", "Method", 1), ("batches", "Batches", 0.5),
                     ("low", "Lowest batch average", 0.8), ("high", "Highest batch average", 0.8),
                     ("spread", "Spread", 0.5), ("unit", "Unit", 0.4)],
                variation, "Fewer than two comparable batches in this period.",
            )),
            section("Recurring OOS investigations", table(
                "", [("test", "Test", 1.3), ("count", "Investigations", 0.7), ("references", "References", 2)],
                [
                    {"test": name, "count": len(found), "references": ", ".join(i.reference for i in found)}
                    for name, found in sorted(recurring.items(), key=lambda item: -len(item[1]))
                ],
            )),
            section("Specification versions", table(
                "", [("version", "Version", 0.5), ("status", "Status", 0.8), ("effective", "Effective", 0.9),
                     ("review", "Review date", 0.9), ("samples", "Samples", 0.6)],
                [
                    {
                        "version": Cell(f"{s.stage_name + ' tests ' if s.stage_key else ''}v{s.version}",
                                        to=f"/reports/test-results?spec={s.pk}&superseded=1"),
                        "status": s.get_status_display(), "effective": s.effective_date, "review": s.review_date,
                        "samples": visible.filter(specification=s).count(),
                    }
                    for s in specs
                ],
            )),
        ],
    }

