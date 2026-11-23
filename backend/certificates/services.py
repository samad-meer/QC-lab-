"""
The signing state machine. Every rule from the brief lives here:

- content snapshot frozen + hashed at analyst sign (Rule One)
- then the review stages of the sample's workflow, signed in order; the
  last one releases the certificate
- send-backs supersede the version; re-signing creates a new version
- every signature from a different person (Rule Three) — refusals are recorded;
  only the administrator override passes it, and the audit row says so
- OOS blocks the analyst's signature: no certificate around a failure
- printing only after approval; copy 1 original, then numbered duplicates
"""
import hashlib
import json
from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.authz import OVERRIDE, has_perm, overrides
from accounts.models import LabConfig
from accounts.passwords import confirm_password
from audit.models import AuditEvent
from audit.services import record
from lims.evaluation import reported_value
from quality.models import InvestigationStatus
from lims.models import Outcome, Sample, SampleStatus, WorkflowEvent
from lims.workflow import may_sign_stage
from execution.models import TESTING, RetestRequest, RetestStatus
from execution.rules import ExecutionError, attempt_of, require_can_complete, require_can_work, step_of
from execution.services import announce_stage
from notifications.alerts import certificate_released
from notifications.services import notify
from standards.models import CertificateTemplate
from .models import ANALYSED, CertStatus, Certificate, PrintEvent, Signature


class SignError(Exception):
    """A refused signing action; the refusal is already in the audit trail."""


# A copy recorded but never opened, because its window closed first, is not lost:
# whoever printed it can still open it, for this long. Prints from before copies
# were tracked show no opening, so with no limit an old original could print again.
COPY_OPENS_WITHIN = timedelta(hours=24)


STALE = (
    "Someone else has already acted on this certificate — it is no longer waiting at that stage. "
    "Reload and review again."
)


def review_stages(cert: Certificate) -> list:
    """The review stages this certificate needs, from the workflow version its sample is bound to."""
    return list(cert.sample.workflow_version.stages.select_related("role"))


def awaiting_stage(cert: Certificate):
    """The review stage the certificate is waiting at: the first one not yet signed."""
    if cert.status != CertStatus.IN_REVIEW:
        return None
    signed = set(cert.signatures.values_list("meaning", flat=True))
    return next((s for s in review_stages(cert) if s.code not in signed), None)


def signature_chain(cert: Certificate) -> list[dict]:
    """Every signature the certificate needs, in order, with whoever has signed so far."""
    signed = {s.meaning: s for s in cert.signatures.all()}
    chain = [{"code": ANALYSED, "title": "Analysed by", "holder": "", "signature": signed.get(ANALYSED)}]
    chain += [
        {"code": s.code, "title": s.signature_title, "holder": s.holder_title, "signature": signed.get(s.code)}
        for s in review_stages(cert)
    ]
    return chain


def _iso(value) -> str:
    """
    Snapshot values must be JSON — the content is stored and hashed. In the
    lab's time zone, because the certificate prints the date part as it stands.
    """
    return timezone.localtime(value).isoformat() if value else ""


def _retest_history(sample: Sample) -> list[dict]:
    """Each authorized retest behind a reported result — the failure stays on the certificate."""
    rows = RetestRequest.objects.filter(sample=sample, status=RetestStatus.USED).select_related(
        "test_definition", "failed_result__test_definition", "retest_result__test_definition",
        "requested_by", "decided_by",
    ).order_by("used_at", "id")
    return [
        {
            "test": r.test_definition.name,
            "unit": r.test_definition.unit,
            "original_value": reported_value(r.failed_result),
            "original_entered_at": _iso(r.failed_result.entered_at),
            "reason": r.reason,
            "requested_by": r.requested_by.display_name(),
            "authorized_by": r.decided_by.display_name(),
            "authorized_at": _iso(r.decided_at),
            "retest_value": reported_value(r.retest_result),
            "retest_outcome": r.retest_result.outcome,
            "retest_entered_at": _iso(r.retest_result.entered_at),
        }
        for r in rows
    ]


LETTERHEAD = ("lab_name", "company_name", "address", "licence_no", "phone", "email", "website", "footer_note")


def _investigations(sample: Sample) -> list[dict]:
    return [
        {"reference": i.reference, "kind": i.get_kind_display(), "conclusion": i.get_conclusion_display(),
         "closed_at": _iso(i.closed_at)}
        for i in sample.investigations.filter(status=InvestigationStatus.CLOSED).order_by("closed_at", "id")
    ]


def _layout(sample: Sample) -> dict:
    """How this certificate is presented. Frozen with it, so every copy prints the same."""
    template = sample.product.certificate_template or CertificateTemplate.default()
    return template.layout() if template else {}


def _letterhead() -> dict:
    """Frozen with the rest, so a reprint reads as the original did."""
    cfg = LabConfig.get()
    return {
        **{field: getattr(cfg, field) for field in LETTERHEAD},
        "logo": cfg.logo.name if cfg.logo else "",
    }


def build_snapshot(sample: Sample, version: int) -> dict:
    results = list(sample.current_results())
    content = {
        "letterhead": _letterhead(),
        "layout": _layout(sample),
        "sample_no": sample.sample_no,
        "certificate_version": version,
        "product_name": sample.product.name,
        "product_code": sample.product.code,
        "section": sample.section.name,
        "dosage_form": sample.product.dosage_form,
        "strength": sample.product.strength,
        "batch_no": sample.batch_no,
        "reference": sample.reference,
        "internal_batch_id": sample.batch.internal_id if sample.batch_id else "",
        "manufacturing_site": sample.batch.manufacturing_site if sample.batch_id else "",
        "quantity": sample.quantity,
        "received_from": sample.received_from,
        "received_at": sample.received_at.isoformat(),
        "due_date": sample.due_date.isoformat(),
        "spec_version": sample.specification.version,
        # An in-process sample: the batch's QC stage it was taken for, and the stage's
        # own tests when it was tested on them. Empty for the rest.
        "qc_stage": sample.qc_stage.name if sample.qc_stage_id else "",
        "spec_of_stage": sample.specification.stage_name if sample.specification.stage_key else "",
        # Batch details. Frozen with everything else, so a certificate keeps
        # the dates that were true when it was signed. Certificates issued
        # before these fields existed simply do not carry them.
        "manufacturing_date": sample.manufacturing_date.isoformat() if sample.manufacturing_date else "",
        "expiry_date": sample.expiry_date.isoformat() if sample.expiry_date else "",
        "storage_condition": sample.storage_condition,
        # When the testing actually happened — a standard COA field, taken
        # from the first and last result entered rather than typed by hand.
        # (results is ordered by test, not by time — so take min/max, not [0].)
        "analysis_started": _iso(min(r.entered_at for r in results)) if results else "",
        "analysis_completed": _iso(max(r.entered_at for r in results)) if results else "",
        "tests": [
            {
                "name": r.test_definition.name,
                "method": r.test_definition.method,
                "unit": r.test_definition.unit,
                "limit_text": r.test_definition.limit_text,
                "value": reported_value(r),
                "outcome": r.outcome,
            }
            for r in results
        ],
        "overall": "COMPLIES" if all(r.outcome != Outcome.FAIL for r in results) else "DOES NOT COMPLY",
    }
    if sample.expiry_date and sample.expiry_date < timezone.localtime(sample.received_at).date():
        content["past_expiry"] = sample.past_expiry_reason or "No reason recorded."
    # Reviewers always see what lay behind a passing result; it goes in the
    # frozen content so they sign knowing it.
    history = _retest_history(sample)
    if history:
        content["history_for_review"] = history
    investigations = _investigations(sample)
    if investigations:
        content["investigations"] = investigations
    # Whether the retest history is printed is the workflow's choice, bound at
    # registration; once frozen here, every copy of this version prints the same.
    if sample.workflow_version.coa_show_retests:
        if history:
            content["retests"] = history
            retested = {h["test"] for h in history}
            for row in content["tests"]:
                if row["name"] in retested:
                    row["retested"] = True
    return content


def content_hash(content: dict) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _verify_password(user, password: str, sample_no: str, action: str):
    """E-sign = re-entering your password at the moment of signing."""
    if not confirm_password(user, password):
        record(user, "SIGN_PASSWORD_FAILED", "sample", sample_no, meaning=action)
        raise SignError("Password incorrect. Signing refused.")


def _require_distinct(certificate: Certificate, user, action: str):
    """Rule Three: every signature on a certificate comes from a different person."""
    if certificate.signatures.filter(user=user).exists() and not overrides(
        user, "Every signature on a certificate must come from a different person."
    ):
        record(
            user, "SIGN_REFUSED_SAME_PERSON", "certificate", certificate.id,
            sample=certificate.sample.sample_no, meaning=action,
        )
        raise SignError(
            "Every signature on a certificate must come from a different person. "
            "You have already signed this certificate; this attempt has been recorded."
        )


def _step_rules(check, *args, **kwargs):
    """Run a lab-execution rule; its refusal becomes a signing refusal."""
    try:
        check(*args, **kwargs)
    except ExecutionError as e:
        raise SignError(str(e))


def signature_seal(certificate_id, meaning: str, user_id, name: str, signed_hash: str) -> str:
    """A signature cannot be lifted onto another record, or reattributed, without this changing."""
    text = "|".join(str(part) for part in (certificate_id, meaning, user_id, name, signed_hash))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sign(certificate: Certificate, user, meaning: str):
    name = user.display_name()
    Signature.objects.create(
        certificate=certificate,
        meaning=meaning,
        user=user,
        name_snapshot=name,
        content_hash=certificate.content_hash,
        seal=signature_seal(certificate.id, meaning, user.id, name, certificate.content_hash),
    )


def integrity_problems(cert: Certificate) -> list[str]:
    """What no longer matches what was signed. Empty for a sound certificate."""
    problems = []
    if content_hash(cert.content) != cert.content_hash:
        problems.append("its content has changed since it was signed")
    for s in cert.signatures.all():
        if s.content_hash != cert.content_hash:
            problems.append(f"the {s.meaning} signature was made on different content")
        elif s.seal and s.seal != signature_seal(cert.id, s.meaning, s.user_id, s.name_snapshot, s.content_hash):
            problems.append(f"the {s.meaning} signature has been altered")
    return problems


def require_intact(cert: Certificate, by):
    problems = integrity_problems(cert)
    if problems:
        record(by, "CERT_INTEGRITY_FAILED", "certificate", cert.sample.sample_no, version=cert.version,
               problems=problems)
        raise SignError("This certificate no longer matches what was signed, so it cannot be printed. Tell QA.")


def sign_as_analyst(sample: Sample, user, password: str) -> Certificate:
    # The checks below note the override when an administrator signs in the analyst's place.
    if not has_perm(user, "cert.sign.analysed") or (
        sample.assigned_analyst_id != user.id and not has_perm(user, OVERRIDE)
    ):
        message = "Only the assigned analyst can sign this certificate."
        record(user, "ACCESS_REFUSED", "sample", sample.sample_no, reason=message)
        raise SignError(message)
    testing = step_of(sample, TESTING)
    # The step's checklist, documents, hold and acceptance — and the results
    # themselves — before a password is even asked for.
    if sample.status in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING):
        _step_rules(require_can_complete, sample, testing, user, attempt_of(sample))

    _verify_password(user, password, sample.sample_no, ANALYSED)

    with transaction.atomic():
        # Lock the sample and validate everything against the exact data
        # that will be frozen — closes the race between result entry,
        # double-submitted sign requests, and the OOS gate.
        sample = Sample.objects.select_for_update().get(pk=sample.pk)
        if sample.status not in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING):
            raise SignError(f"Cannot sign while the sample is {sample.get_status_display()}.")
        if sample.certificates.exclude(status=CertStatus.SUPERSEDED).exists():
            raise SignError("A live certificate already exists for this sample.")

        test_ids = set(sample.specification.tests.values_list("id", flat=True))
        if not test_ids:
            raise SignError("This specification has no tests, so there is nothing to certify.")
        entered = set(sample.current_results().values_list("test_definition_id", flat=True))
        missing = test_ids - entered
        if missing:
            raise SignError(
                f"{len(missing)} test(s) still have no result. Every test needs a result before signing."
            )

        version = (sample.certificates.aggregate(m=Max("version"))["m"] or 0) + 1
        content = build_snapshot(sample, version)
        if any(t["outcome"] == Outcome.FAIL for t in content["tests"]):
            # No certificate can be built around a failure (brief: OOS locks
            # the certificate). Stage Two adds the full investigation record;
            # today the failed value stays on record and any retest is a
            # superseded-with-reason correction, which is itself audited.
            raise SignError(
                "One or more results are out of specification. "
                "The certificate is locked until the failure is resolved."
            )

        _step_rules(require_can_complete, sample, testing, user, version, audit=False)

        first = sample.workflow_version.stages.select_related("role").first()
        if first is None:
            raise SignError("This sample's review workflow has no stages. Ask an administrator to fix it.")

        cert = Certificate.objects.create(
            sample=sample,
            version=version,
            content=content,
            content_hash=content_hash(content),
        )
        _sign(cert, user, ANALYSED)
        sample.review_stage = first
        _move(sample, user, SampleStatus.IN_REVIEW,
              f"Certificate v{version} signed as “Analysed by” — now with {first.holder}")
        record(user, "SIGNED_ANALYSED", "certificate", cert.id, sample=sample.sample_no, version=version)
        announce_stage(sample, first, user)
    return cert


def _lock_for_transition(cert: Certificate, required_status: str):
    """
    Re-fetch sample and certificate under row locks (sample first — the same
    order everywhere, to avoid deadlocks) and re-validate the certificate
    status. Closes the TOCTOU where two concurrent decisions (e.g. reject
    and approve) both saw the same pre-commit state.
    """
    sample = Sample.objects.select_for_update().get(pk=cert.sample_id)
    locked = Certificate.objects.select_for_update().get(pk=cert.pk)
    if locked.status != required_status:
        raise SignError(
            f"This certificate is no longer {required_status.replace('_', ' ').lower()} — "
            "someone else acted on it first. Reload and review again."
        )
    return sample, locked


def _stage_for_action(cert: Certificate, user, stage_order: int | None, verb: str):
    """The stage being acted on, after the checks that need no lock."""
    stage = awaiting_stage(cert)
    if stage is None:
        raise SignError("This certificate is not waiting for a review signature.")
    if stage_order is not None and stage.order != stage_order:
        raise SignError(STALE)
    if not may_sign_stage(user, stage) and not has_perm(user, OVERRIDE):
        message = f"Only someone in the {stage.role.name} role can {verb} at “{stage.name}”."
        record(user, "ACCESS_REFUSED", "certificate", cert.id, sample=cert.sample.sample_no, reason=message)
        raise SignError(message)
    return stage


def sign_stage(cert: Certificate, user, password: str, stage_order: int | None = None) -> Certificate:
    """
    Sign the stage the certificate is waiting at. stage_order is the stage
    the signer's screen showed — if someone acted since, the signature is
    refused rather than landing on a different stage than the one reviewed.
    """
    stage = _stage_for_action(cert, user, stage_order, "sign")
    _require_distinct(cert, user, stage.code)
    step = step_of(cert.sample, stage.code)
    _step_rules(require_can_complete, cert.sample, step, user, cert.version)
    _verify_password(user, password, cert.sample.sample_no, stage.code)

    with transaction.atomic():
        sample, cert = _lock_for_transition(cert, CertStatus.IN_REVIEW)
        if awaiting_stage(cert) != stage:
            raise SignError(STALE)
        _require_distinct(cert, user, stage.code)
        _step_rules(require_can_complete, sample, step, user, cert.version, audit=False)
        _sign(cert, user, stage.code)
        following = awaiting_stage(cert)
        details = dict(sample=sample.sample_no, title=stage.full_title, step=stage.order,
                       of=len(review_stages(cert)))
        if following is not None:
            sample.review_stage = following
            _move(sample, user, SampleStatus.IN_REVIEW,
                  f"Signed as “{stage.full_title}” — now with {following.holder}")
            record(user, "SIGNED_STAGE", "certificate", cert.id, **details)
            announce_stage(sample, following, user)
        else:
            cert.status = CertStatus.APPROVED
            cert.save(update_fields=["status"])
            sample.review_stage = None
            _move(sample, user, SampleStatus.APPROVED,
                  f"Signed as “{stage.full_title}” — certificate released for print")
            record(user, "SIGNED_FINAL", "certificate", cert.id, **details)
            certificate_released(cert, sample, user)
    return cert


def return_to_analyst(cert: Certificate, user, comment: str, stage_order: int | None = None) -> Certificate:
    """
    Send the work back from whichever stage it is at. The analyst owns the
    correction; the corrected version is a new certificate that needs every
    signature again — no earlier review carries over.
    """
    stage = _stage_for_action(cert, user, stage_order, "send work back")
    if not comment.strip():
        raise SignError("Sending work back must say why. Write a comment.")
    step = step_of(cert.sample, stage.code)
    _step_rules(require_can_work, cert.sample, step, user)

    with transaction.atomic():
        sample, cert = _lock_for_transition(cert, CertStatus.IN_REVIEW)
        if awaiting_stage(cert) != stage:
            raise SignError(STALE)
        _step_rules(require_can_work, sample, step, user)
        cert.status = CertStatus.SUPERSEDED
        cert.superseded_reason = comment.strip()
        cert.returned_stage = stage.code
        cert.returned_by = user
        cert.returned_at = timezone.now()
        cert.save(update_fields=["status", "superseded_reason", "returned_stage", "returned_by", "returned_at"])
        sample.review_stage = None
        _move(sample, user, SampleStatus.IN_TESTING, comment.strip())
        record(user, "RETURNED_TO_ANALYST", "certificate", cert.id,
               sample=sample.sample_no, stage=stage.name, comment=comment.strip())
        notify(sample.assigned_analyst, "RETURNED", f"{sample.sample_no} was sent back to you from “{stage.name}”",
               body=f"By {user.display_name()}: “{comment.strip()}”", sample=sample, actor=user)
    return cert


def copy_was_opened(cert_id, copy_number: int) -> bool:
    return AuditEvent.objects.filter(
        action="CERT_COPY_OPENED", entity_id=str(cert_id), details__copy=copy_number
    ).exists()


def can_open_copy(print_event: PrintEvent, user) -> bool:
    return (
        print_event.printed_by_id == user.id
        and timezone.now() - print_event.printed_at <= COPY_OPENS_WITHIN
        and not copy_was_opened(print_event.certificate_id, print_event.copy_number)
    )


def record_print(cert: Certificate, user) -> PrintEvent:
    """Not one moment earlier: only an approved certificate prints."""
    if not has_perm(user, "cert.print"):
        record(user, "PRINT_REFUSED_NO_PERMISSION", "certificate", cert.id,
               sample=cert.sample.sample_no)
        raise SignError("You do not have permission to print certificates.")
    if cert.status != CertStatus.APPROVED:
        record(user, "PRINT_REFUSED_UNAPPROVED", "certificate", cert.id, sample=cert.sample.sample_no)
        raise SignError("Only an approved certificate can be printed.")
    require_intact(cert, user)
    with transaction.atomic():
        locked = Certificate.objects.select_for_update().get(pk=cert.pk)
        if locked.status != CertStatus.APPROVED:
            record(user, "PRINT_REFUSED_UNAPPROVED", "certificate", cert.id, sample=cert.sample.sample_no)
            raise SignError("Only an approved certificate can be printed.")
        next_copy = (locked.prints.aggregate(m=Max("copy_number"))["m"] or 0) + 1
        pe = PrintEvent.objects.create(certificate=locked, copy_number=next_copy, printed_by=user)
        record(user, "PRINTED", "certificate", cert.id,
               sample=cert.sample.sample_no, copy_number=next_copy)
    return pe


def _move(sample: Sample, actor, to_status: str, comment: str):
    from_status = sample.status
    sample.status = to_status
    sample.save(update_fields=["status", "review_stage"])
    WorkflowEvent.objects.create(
        sample=sample, actor=actor, from_status=from_status, to_status=to_status, comment=comment
    )


def withdraw_certificate(cert: Certificate, by, password: str, reason: str) -> Certificate:
    """
    Stop a released certificate being relied on. Its content stays as it was
    signed; the verification page says it was withdrawn, and why.
    """
    if not has_perm(by, "cert.withdraw"):
        message = "You do not have permission to withdraw certificates."
        record(by, "ACCESS_REFUSED", "certificate", cert.sample.sample_no, reason=message)
        raise SignError(message)
    reason = (reason or "").strip()[:1000]
    if not reason:
        raise SignError("Say why this certificate is being withdrawn. The reason is shown on the verification page.")
    _verify_password(by, password, cert.sample.sample_no, "WITHDRAWN")
    with transaction.atomic():
        locked = Certificate.objects.select_for_update().get(pk=cert.pk)
        if locked.status != CertStatus.APPROVED:
            raise SignError("Only a released certificate can be withdrawn.")
        locked.status = CertStatus.WITHDRAWN
        locked.withdrawn_by = by
        locked.withdrawn_at = timezone.now()
        locked.withdrawn_reason = reason
        locked.save()
        record(by, "CERT_WITHDRAWN", "certificate", locked.sample.sample_no, version=locked.version, reason=reason)
    return locked
