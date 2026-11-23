"""
Batch actions. Each checks its rules, writes the record and leaves an audit
entry. A refused action raises BatchError with a message for the person.
"""
import hashlib
import json

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.authz import OVERRIDE, has_perm, overrides
from accounts.passwords import confirm_password
from audit.services import record
from certificates.models import ANALYSED, CertStatus, Certificate, Signature
from execution.files import MAX_UPLOAD_MB, FileRejected, check_upload, safe_display_name
from lims.evaluation import reported_value
from lims.models import Product, SampleStatus, TestResult
from quality.gates import release_blockers
from quality.models import Investigation, InvestigationStatus
from .models import Batch, BatchDisposition, BatchDocument, DispositionDecision, DocumentType
from .numbering import next_internal_id
from .stages import stage_basis, stage_problems

# What a certificate copies from its batch.
ON_CERTIFICATE = {"official_batch_no", "manufacturing_site", "manufacturing_date", "expiry_date"}
DISPOSITION = "batch.disposition"


class BatchError(Exception):
    """A refused batch action. The message is written for the person who tried."""


def find(product, official_no: str) -> Batch | None:
    return Batch.objects.filter(product=product, official_batch_no__iexact=official_no.strip()).first()


def _official(raw) -> str:
    """Stored exactly as assigned: only stray spaces around it are dropped."""
    value = (raw or "").strip()
    if not value:
        raise BatchError("Enter the official batch number.")
    return value


def _check_dates(manufactured, expires):
    if manufactured and expires and expires < manufactured:
        raise BatchError("The expiry date cannot be before the date of manufacture.")


def _shown(value) -> str:
    return "—" if value in (None, "") else str(value)


def create(product, official_no, by, **details) -> Batch:
    official = _official(official_no)
    _check_dates(details.get("manufacturing_date"), details.get("expiry_date"))
    with transaction.atomic():
        # One at a time per product, so two desks cannot create the same batch.
        Product.objects.select_for_update().get(pk=product.pk)
        existing = find(product, official)
        if existing is not None:
            raise BatchError(f"{product.name} already has batch {existing.official_batch_no} ({existing.internal_id}).")
        # Bound now, like a sample's specification: a later change to the
        # product's QC stages never alters this batch.
        plan = product.current_stage_plan()
        batch = Batch.objects.create(
            internal_id=next_internal_id(product), product=product, official_batch_no=official,
            created_by=by, stage_plan=plan, **details,
        )
        record(by, "BATCH_CREATED", "batch", batch.internal_id, official=official, product=product.code,
               **({"qc_stages": f"version {plan.version}"} if plan else {}))
    return batch


def for_registration(product, official_no, by, *, site="", manufactured=None, expires=None) -> Batch:
    """
    The batch a new sample belongs to: the one on record, or a new one. What
    the batch already records stands: a different value at the front desk is
    a typing mistake or a different batch, and is refused rather than guessed
    at. Anything the batch does not have yet is filled in.
    """
    official = _official(official_no)
    _check_dates(manufactured, expires)
    with transaction.atomic():
        Product.objects.select_for_update().get(pk=product.pk)
        batch = find(product, official)
        if batch is None:
            return create(product, official, by, manufacturing_site=site, manufacturing_date=manufactured,
                          expiry_date=expires)
        given = {"manufacturing_site": site, "manufacturing_date": manufactured, "expiry_date": expires}
        names = {"manufacturing_site": "manufacturing site", "manufacturing_date": "date of manufacture",
                 "expiry_date": "expiry date"}
        added = {}
        for field, value in given.items():
            held = getattr(batch, field)
            if value and held and value != held:
                raise BatchError(
                    f"Batch {batch.official_batch_no} is recorded with {names[field]} {_shown(held)}, not "
                    f"{_shown(value)}. Use the recorded value, or correct the batch first."
                )
            if value and not held:
                setattr(batch, field, value)
                added[field] = str(value)
        if added:
            _check_dates(batch.manufacturing_date, batch.expiry_date)
            batch.save(update_fields=list(added))
            record(by, "BATCH_DETAILS_ADDED", "batch", batch.internal_id, **added)
    return batch


def update(batch: Batch, by, changes: dict, reason: str) -> Batch:
    """Correct a batch's details. The reason and the old values go on the audit trail."""
    reason = (reason or "").strip()[:500]
    if not reason:
        raise BatchError("Say why the batch is being changed — it stays on the record.")
    with transaction.atomic():
        batch = Batch.objects.select_for_update().get(pk=batch.pk)
        if "official_batch_no" in changes:
            changes["official_batch_no"] = _official(changes["official_batch_no"])
        before = {f: _shown(getattr(batch, f)) for f in changes if getattr(batch, f) != changes[f]}
        if not before:
            return batch

        if "official_batch_no" in before:
            if Certificate.objects.filter(sample__batch=batch).exists():
                raise BatchError(
                    "The official number cannot change: a certificate has been signed for this batch, "
                    "and it carries the number it was signed with."
                )
            clash = find(batch.product, changes["official_batch_no"])
            if clash is not None and clash.pk != batch.pk:
                raise BatchError(f"{batch.product.name} already has batch {clash.official_batch_no} ({clash.internal_id}).")

        # A certificate in review was signed with the old details, and its content
        # is frozen: letting this through would release it with a known mistake.
        in_review = list(batch.samples.filter(status=SampleStatus.IN_REVIEW).values_list("sample_no", flat=True))
        if in_review and ON_CERTIFICATE & set(before):
            raise BatchError(
                f"{', '.join(in_review)} is in review with the old details on its certificate. "
                "Send it back first, then correct the batch."
            )

        for field, value in changes.items():
            setattr(batch, field, value)
        _check_dates(batch.manufacturing_date, batch.expiry_date)
        batch.save(update_fields=list(changes))

        # A signed certificate keeps what it was signed with; work not yet
        # signed picks up the correction, so its certificate is right.
        batch.samples.filter(status__in=[SampleStatus.RECEIVED, SampleStatus.IN_TESTING]).update(
            batch_no=batch.official_batch_no, manufacturing_date=batch.manufacturing_date,
            expiry_date=batch.expiry_date,
        )
        record(by, "BATCH_UPDATED", "batch", batch.internal_id, reason=reason, before=before,
               after={f: _shown(changes[f]) for f in before})
    return batch


def upload_document(batch: Batch, by, uploaded, doc_type: str, title: str, replaces_id=None,
                    note: str = "") -> BatchDocument:
    if doc_type not in DocumentType.values:
        raise BatchError("Choose what kind of document this is.")
    name = safe_display_name(getattr(uploaded, "name", ""))
    try:
        ext, content_type, size, sha = check_upload(uploaded, None, MAX_UPLOAD_MB)
    except FileRejected as e:
        record(by, "ATTACHMENT_REFUSED", "batch", batch.internal_id, step="Batch documents", name=name, reason=str(e))
        raise BatchError(str(e))

    with transaction.atomic():
        previous = None
        if replaces_id not in (None, ""):
            previous = BatchDocument.objects.select_for_update().filter(
                pk=replaces_id if str(replaces_id).isdigit() else 0, batch=batch
            ).first()
            if previous is None or not previous.is_current:
                raise BatchError("Only the current version of a document can be replaced.")
        title = (title or "").strip()[:200] or (previous.title if previous else name)
        document = BatchDocument(
            batch=batch, doc_type=previous.doc_type if previous else doc_type, title=title,
            version=previous.version + 1 if previous else 1, replaces=previous,
            original_name=name, extension=ext, content_type=content_type, size=size, sha256=sha,
            note=(note or "").strip()[:500], uploaded_by=by,
        )
        document.file.save(f"upload.{ext}", uploaded, save=False)
        document.save()
        if previous is not None:
            previous.replaced_by = document
            previous.save()
        record(by, "BATCH_DOCUMENT_ADDED", "batch", batch.internal_id, title=title, version=document.version,
               name=name, size=size, sha256=sha)
    return document


def withdraw_document(document: BatchDocument, by, reason: str):
    reason = (reason or "").strip()[:500]
    if not reason:
        raise BatchError("Say why the document is being withdrawn.")
    with transaction.atomic():
        document = BatchDocument.objects.select_for_update().get(pk=document.pk)
        if not document.is_current:
            raise BatchError("Only the current version of a document can be withdrawn.")
        document.withdrawn_at = timezone.now()
        document.withdrawn_by = by
        document.withdraw_reason = reason
        document.save()
        record(by, "BATCH_DOCUMENT_WITHDRAWN", "batch", document.batch.internal_id, title=document.title,
               version=document.version, reason=reason)


# --- disposition ------------------------------------------------------------------

def tested_by(batch: Batch) -> set[int]:
    """Everyone whose testing a decision on this batch would be judging, in any of its samples."""
    people = set(batch.samples.values_list("assigned_analyst_id", flat=True))
    people |= set(TestResult.objects.filter(sample__batch=batch).values_list("entered_by_id", flat=True))
    people |= set(
        Signature.objects.filter(certificate__sample__batch=batch, meaning=ANALYSED).values_list("user_id", flat=True)
    )
    return people


def release_problems(batch: Batch) -> list[str]:
    """
    Why this batch cannot be released, read from the whole batch: never only what
    the person deciding can see. Empty when nothing stands in the way.
    """
    samples = list(batch.samples.exclude(status=SampleStatus.CANCELLED).select_related("product", "batch", "review_stage"))
    if not samples:
        return ["This batch has no sample to release it on.", *stage_problems(batch)]
    problems = []
    released = set(
        Certificate.objects.filter(sample__in=samples, status=CertStatus.APPROVED).values_list("sample_id", flat=True)
    )
    for sample in samples:
        if sample.status == SampleStatus.REJECTED:
            problems.append(f"{sample.sample_no} was rejected.")
        elif sample.status != SampleStatus.APPROVED:
            problems.append(f"{sample.sample_no} is not approved yet ({sample.status_label().lower()}).")
        elif sample.pk not in released:
            problems.append(f"{sample.sample_no} has no certificate in force.")
    # Asked here as well: the gates below stand aside when the lab turns its failure rules off.
    still_open = Investigation.objects.filter(
        Q(sample__batch=batch) | Q(product=batch.product, batch_no__iexact=batch.official_batch_no)
    ).exclude(status=InvestigationStatus.CLOSED).order_by("id")
    problems += [f"{inv.reference} is still open on this batch." for inv in still_open]
    for sample in samples:
        problems += release_blockers(sample)
    # Strict: every required QC stage has passed. An optional one is never waited for.
    problems += stage_problems(batch)
    if batch.expiry_date and batch.expiry_date < timezone.localdate():
        problems.append(f"This batch expired on {batch.expiry_date:%d-%b-%Y}.")
    return list(dict.fromkeys(problems))


def disposition_basis(batch: Batch) -> dict:
    """What a decision is made on: the batch, each sample's state, its certificate and its current results."""
    samples = batch.samples.order_by("id").select_related("specification")
    certificates = {
        c.sample_id: {"version": c.version, "hash": c.content_hash}
        for c in Certificate.objects.filter(sample__batch=batch, status=CertStatus.APPROVED)
    }
    results = TestResult.objects.filter(sample__batch=batch, is_superseded=False).select_related("test_definition")
    current = {}
    for r in results.order_by("sample_id", "test_definition__order", "id"):
        current.setdefault(r.sample_id, []).append(
            {"test": r.test_definition.name, "result": reported_value(r), "outcome": r.outcome}
        )
    return {
        "batch": batch.internal_id, "official_batch_no": batch.official_batch_no, "product": batch.product.code,
        "expiry_date": str(batch.expiry_date or ""),
        "samples": [
            {"sample_no": s.sample_no, "status": s.status, "specification": s.specification.version,
             # A stage's own tests are a specification of their own, with their own versions.
             **({"specification_of_stage": s.specification.stage_name} if s.specification.stage_key else {}),
             "certificate": certificates.get(s.pk), "results": current.get(s.pk, [])}
            for s in samples
        ],
        **({"qc_stages": stage_rows} if (stage_rows := stage_basis(batch)) else {}),
    }


def _basis_hash(basis: dict, decision: str, reason: str, by) -> str:
    content = json.dumps([basis, decision, reason, by.id], sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _disposition_refusal(batch: Batch, decision: str) -> str | None:
    latest = batch.latest_disposition()
    if latest is not None and latest.decision == DispositionDecision.REJECTED:
        return "This batch was rejected, and a rejected batch stays rejected."
    if latest is not None and latest.decision == decision:
        return f"This batch is already {latest.get_decision_display().lower()}."
    if decision == DispositionDecision.RELEASED:
        problems = release_problems(batch)
        if problems:
            return f"This batch cannot be released. {' '.join(problems)}"
    return None


def decide_disposition(batch: Batch, by, decision: str, reason: str, password: str) -> BatchDisposition:
    """
    A signed act by the quality unit, and never by anyone who tested the batch.
    Only the administrator override passes that, and the audit row says so. Nothing
    passes the conditions for release.
    """
    if not has_perm(by, DISPOSITION):
        message = "You do not have permission to decide batch disposition."
        record(by, "ACCESS_REFUSED", "batch", batch.internal_id, reason=message)
        raise BatchError(message)
    if decision not in DispositionDecision.values:
        raise BatchError("Choose released, rejected or quarantined.")
    reason = (reason or "").strip()
    if not reason:
        raise BatchError("Say why. The reason stays on the batch's record.")
    if len(reason) > 1000:
        raise BatchError("Keep the reason to 1000 characters.")
    if by.id in tested_by(batch) and not overrides(by, "A batch is decided by someone who did not test it."):
        record(by, "BATCH_DISPOSITION_REFUSED", "batch", batch.internal_id, reason="They tested this batch")
        raise BatchError("You tested a sample of this batch, so someone else must decide it.")
    refusal = _disposition_refusal(batch, decision)
    if refusal:
        record(by, "BATCH_DISPOSITION_REFUSED", "batch", batch.internal_id, reason=refusal)
        raise BatchError(refusal)
    if not confirm_password(by, password):
        record(by, "SIGN_PASSWORD_FAILED", "batch", batch.internal_id, meaning="disposition")
        raise BatchError("Password incorrect. Nothing was decided.")
    with transaction.atomic():
        batch = Batch.objects.select_for_update().get(pk=batch.pk)
        if by.id in tested_by(batch) and not has_perm(by, OVERRIDE):
            raise BatchError("You tested a sample of this batch, so someone else must decide it.")
        refusal = _disposition_refusal(batch, decision)
        if refusal:
            raise BatchError(refusal)
        basis = disposition_basis(batch)
        disposition = BatchDisposition.objects.create(
            batch=batch, decision=decision, reason=reason, decided_by=by, basis=basis,
            basis_hash=_basis_hash(basis, decision, reason, by),
        )
        record(by, "BATCH_DISPOSITION", "batch", batch.internal_id, decision=disposition.get_decision_display().lower(),
               reason=reason, hash=disposition.basis_hash)
    return disposition
