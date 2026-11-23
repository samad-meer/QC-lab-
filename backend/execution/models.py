"""
Lab execution: what happens *inside* each step of a sample's journey.

The journey itself (Received → Tested → review stages → Released → Printed)
lives in lims and certificates. This app adds what a step needs before it
can be completed, and the record of doing it:

- ChecklistItem — a check or document a step requires. Part of a workflow
  version, so it is never edited: a change is a new version.
- ChecklistResponse — one answer. Never edited: a changed answer is a new
  row and the old one is marked replaced, with who and when.
- Attachment — a file kept in private storage and served only through an
  authenticated view. Never deleted: replaced by a new version, or
  withdrawn with a reason.
- StepComment — notes and review feedback, threaded. Never edited: an
  amendment is a new comment that points at the one it amends.
- Assignment — who holds a step, and every handover between people, with
  acceptance or rejection and the reasons.
- SampleHold — work stopped, why, and when it resumed.
- RetestRequest — the only way a failed result can be followed by another.
- Waiver — a waivable requirement set aside for one attempt, with the reason.

A "step" is a string key: RECEIPT for the front desk's checks when the
sample arrives (only where its workflow version has any), TESTING for the
analyst's step, or the code of a review stage in the sample's bound
workflow version (unique within it).
An "attempt" is the certificate version the work is for: attempt 1 builds
v1; a send-back starts attempt 2, and no answer from attempt 1 carries over.

Every timestamp here is set by the server (auto_now_add or timezone.now in
the service layer) — never taken from the client.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

RECEIPT = "RECEIPT"
TESTING = "TESTING"


def _changed(instance, model) -> set[str]:
    old = model.objects.get(pk=instance.pk)
    return {
        f.name
        for f in instance._meta.concrete_fields
        if getattr(old, f.attname) != getattr(instance, f.attname)
    }


class ResponseType(models.TextChoices):
    CHECKBOX = "CHECKBOX", "Tick to confirm"
    YES_NO = "YES_NO", "Yes / No"
    PASS_FAIL = "PASS_FAIL", "Pass / Fail"
    NUMBER = "NUMBER", "Number"
    TEXT = "TEXT", "Text"
    DATE = "DATE", "Date"
    CHOICE = "CHOICE", "Choose from a list"
    FILE = "FILE", "Document or file"


class ChecklistItem(models.Model):
    """One check or required document of one step, in one workflow version."""

    version = models.ForeignKey("lims.WorkflowVersion", on_delete=models.CASCADE, related_name="checklist")
    # None = the analyst's testing step (or the receipt checks, below);
    # otherwise the review stage.
    stage = models.ForeignKey(
        "lims.WorkflowStage", null=True, blank=True, on_delete=models.CASCADE, related_name="checklist"
    )
    # A check the front desk makes when the sample arrives. Testing cannot
    # start until these are complete.
    for_receipt = models.BooleanField(default=False)
    order = models.PositiveIntegerField()
    label = models.CharField(max_length=200)
    help_text = models.CharField(max_length=300, blank=True)
    response_type = models.CharField(max_length=12, choices=ResponseType.choices)
    required = models.BooleanField(default=True)
    # The conforming answer, where one exists: YES / NO for a yes-no item,
    # one of the options for a list. Blank means any answer conforms.
    expected = models.CharField(max_length=100, blank=True)
    # NUMBER
    unit = models.CharField(max_length=30, blank=True)
    min_value = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    max_value = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    decimals = models.PositiveSmallIntegerField(null=True, blank=True)
    # CHOICE
    options = models.JSONField(default=list, blank=True)
    # FILE — allowed extensions (empty = every type the lab accepts) and size cap.
    file_types = models.JSONField(default=list, blank=True)
    max_size_mb = models.PositiveSmallIntegerField(default=10)
    # May someone holding stage.waive set this item aside, with a reason?
    waivable = models.BooleanField(default=False)

    class Meta:
        ordering = ["version", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "for_receipt", "order"], condition=Q(stage__isnull=True),
                name="uniq_testing_item_order",
            ),
            models.UniqueConstraint(
                fields=["stage", "order"], condition=Q(stage__isnull=False), name="uniq_stage_item_order"
            ),
        ]

    def __str__(self):
        return f"{self.step} · {self.order}. {self.label}"

    @property
    def step(self) -> str:
        if self.stage_id:
            return self.stage.code
        return RECEIPT if self.for_receipt else TESTING

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A checklist item is never edited — save the change as a new workflow version.")
        super().save(*args, **kwargs)


class ChecklistResponse(models.Model):
    """One answer to one item, for one attempt. Changing it adds a row."""

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="checklist_responses")
    item = models.ForeignKey(ChecklistItem, on_delete=models.PROTECT, related_name="responses")
    attempt = models.PositiveIntegerField()
    # The answer in canonical text: YES, NO, PASS, FAIL, an ISO date, an
    # option, free text. Numbers are also kept exactly in `number`.
    value = models.CharField(max_length=1000, blank=True)
    number = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    attachment = models.ForeignKey(
        "Attachment", null=True, blank=True, on_delete=models.PROTECT, related_name="responses"
    )
    # Decided by the server from the item's configuration, never by the client.
    conforms = models.BooleanField()
    answered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    answered_at = models.DateTimeField(auto_now_add=True)

    replaced_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    change_reason = models.CharField(max_length=500, blank=True)

    REPLACE_FIELDS = {"replaced_at", "replaced_by", "change_reason"}

    class Meta:
        ordering = ["answered_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "item", "attempt"], condition=Q(replaced_at__isnull=True),
                name="uniq_current_checklist_response",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = ChecklistResponse.objects.get(pk=self.pk)
            if old.replaced_at is not None or _changed(self, ChecklistResponse) - self.REPLACE_FIELDS:
                raise PermissionError("A checklist answer is never edited — give a new answer instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Checklist answers are never deleted.")


def attachment_path(instance, filename: str) -> str:
    """Never reuse the uploaded name on disk — it can carry path separators."""
    return f"attachments/{instance.sample_id}/{uuid.uuid4().hex}.{instance.extension}"


class Attachment(models.Model):
    """
    A file kept against a step. Stored under MEDIA_ROOT with no public URL;
    /api/attachments/<id>/ serves it to people who can see the sample.
    """

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="attachments")
    step = models.CharField(max_length=30)
    attempt = models.PositiveIntegerField()
    # The required document this file answers, if any.
    item = models.ForeignKey(
        ChecklistItem, null=True, blank=True, on_delete=models.PROTECT, related_name="attachments"
    )
    version = models.PositiveIntegerField(default=1)
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    replaced_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    file = models.FileField(upload_to=attachment_path, max_length=200)
    original_name = models.CharField(max_length=255)
    extension = models.CharField(max_length=10)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    note = models.CharField(max_length=500, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    withdraw_reason = models.CharField(max_length=500, blank=True)

    LATER_FIELDS = {"replaced_by", "withdrawn_at", "withdrawn_by", "withdraw_reason"}

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return f"{self.original_name} v{self.version}"

    @property
    def is_current(self) -> bool:
        return self.replaced_by_id is None and self.withdrawn_at is None

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Attachment.objects.get(pk=self.pk)
            changed = _changed(self, Attachment)
            if changed - self.LATER_FIELDS:
                raise PermissionError("An uploaded file is never changed — upload a new version instead.")
            if ("replaced_by" in changed and old.replaced_by_id is not None) or (
                changed & {"withdrawn_at", "withdrawn_by", "withdraw_reason"} and old.withdrawn_at is not None
            ):
                raise PermissionError("That file's history is already final.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Attachments are never deleted — withdraw one with a reason instead.")


class CommentKind(models.TextChoices):
    NOTE = "NOTE", "Note"
    FEEDBACK = "FEEDBACK", "Review feedback"


class StepComment(models.Model):
    """A note or piece of review feedback. Append-only; amendments are new rows."""

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="step_comments")
    step = models.CharField(max_length=30, blank=True)  # blank = about the sample as a whole
    attempt = models.PositiveIntegerField()
    kind = models.CharField(max_length=10, choices=CommentKind.choices, default=CommentKind.NOTE)
    body = models.TextField(max_length=4000)
    # The thread this replies to (always a root comment), if any.
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replies")
    # The author's own earlier comment this one corrects, if any.
    amends = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="amendments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A comment is never edited — add an amendment instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Comments are never deleted.")


class AssignmentKind(models.TextChoices):
    ASSIGNED = "ASSIGNED", "Assigned"  # at registration, or by someone with sample.assign
    HANDOVER = "HANDOVER", "Handed over"  # by the person holding the step
    CLAIMED = "CLAIMED", "Taken"  # someone in the stage's role took it themselves


class AssignmentStatus(models.TextChoices):
    PENDING = "PENDING", "Awaiting acceptance"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Declined"
    CANCELLED = "CANCELLED", "Cancelled"


class Assignment(models.Model):
    """
    Who holds a step, and how they came to. The holder is the person on the
    latest accepted row; a pending row is a handover waiting for its
    receiver. Rows are only ever answered, never rewritten.
    """

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="assignments")
    step = models.CharField(max_length=30)
    kind = models.CharField(max_length=10, choices=AssignmentKind.choices)
    status = models.CharField(max_length=10, choices=AssignmentStatus.choices)
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=1000, blank=True)

    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    response_reason = models.CharField(max_length=1000, blank=True)

    RESPOND_FIELDS = {"status", "responded_by", "responded_at", "response_reason"}

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "step"], condition=Q(status="PENDING"), name="one_pending_handover_per_step"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Assignment.objects.get(pk=self.pk)
            if old.status != AssignmentStatus.PENDING or _changed(self, Assignment) - self.RESPOND_FIELDS:
                raise PermissionError("An assignment is only ever answered once — never rewritten.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Assignment history is never deleted.")


class SampleHold(models.Model):
    """Work stopped on a sample. Nothing is entered or signed until it is released."""

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="holds")
    step = models.CharField(max_length=30)  # where the sample was when it was held
    reason = models.CharField(max_length=1000)
    placed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    placed_at = models.DateTimeField(auto_now_add=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    released_at = models.DateTimeField(null=True, blank=True)
    release_comment = models.CharField(max_length=1000, blank=True)

    RELEASE_FIELDS = {"released_by", "released_at", "release_comment"}

    class Meta:
        ordering = ["-placed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample"], condition=Q(released_at__isnull=True), name="one_active_hold_per_sample"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = SampleHold.objects.get(pk=self.pk)
            if old.released_at is not None or _changed(self, SampleHold) - self.RELEASE_FIELDS:
                raise PermissionError("A hold is only ever released once — never rewritten.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Hold history is never deleted.")


class RetestStatus(models.TextChoices):
    PENDING = "PENDING", "Awaiting authorization"
    AUTHORIZED = "AUTHORIZED", "Authorized — retest not yet entered"
    DECLINED = "DECLINED", "Declined"
    USED = "USED", "Retest entered"


class RetestKind(models.TextChoices):
    # What each one means is the lab's procedure. The record only keeps them apart.
    RETEST = "RETEST", "Retest"
    REPEAT = "REPEAT", "Repeat analysis"
    RESAMPLE = "RESAMPLE", "Resample"


class RetestRequest(models.Model):
    """
    A failed result is never simply replaced. The analyst asks, someone else
    authorizes, and only then is one retest result entered. The failed
    result stays on record, linked to the retest that followed it.
    """

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="retest_requests")
    test_definition = models.ForeignKey("lims.TestDefinition", on_delete=models.PROTECT, related_name="+")
    failed_result = models.ForeignKey("lims.TestResult", on_delete=models.PROTECT, related_name="retest_requests")
    kind = models.CharField(max_length=10, choices=RetestKind.choices, default=RetestKind.RETEST)
    reason = models.CharField(max_length=1000)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=RetestStatus.choices, default=RetestStatus.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.CharField(max_length=1000, blank=True)
    retest_result = models.ForeignKey(
        "lims.TestResult", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    used_at = models.DateTimeField(null=True, blank=True)

    # PENDING → AUTHORIZED | DECLINED; AUTHORIZED → USED. Nothing else.
    MOVES = {
        RetestStatus.PENDING: {RetestStatus.AUTHORIZED, RetestStatus.DECLINED},
        RetestStatus.AUTHORIZED: {RetestStatus.USED},
    }
    LATER_FIELDS = {"status", "decided_by", "decided_at", "decision_comment", "retest_result", "used_at"}

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["failed_result"], condition=Q(status__in=["PENDING", "AUTHORIZED"]),
                name="one_open_retest_per_failed_result",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = RetestRequest.objects.get(pk=self.pk)
            changed = _changed(self, RetestRequest)
            if changed - self.LATER_FIELDS:
                raise PermissionError("A retest request is never rewritten.")
            if "status" in changed and self.status not in self.MOVES.get(old.status, set()):
                raise PermissionError(f"A retest request cannot move from {old.status} to {self.status}.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Retest requests are never deleted.")


class Waiver(models.Model):
    """A waivable checklist item set aside for one attempt, with the reason."""

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="waivers")
    item = models.ForeignKey(ChecklistItem, on_delete=models.PROTECT, related_name="waivers")
    attempt = models.PositiveIntegerField()
    reason = models.CharField(max_length=1000)
    waived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    waived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["waived_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["sample", "item", "attempt"], name="uniq_waiver_per_attempt"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A waiver is never edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Waivers are never deleted.")


class ReceiptCompletion(models.Model):
    """
    The front desk confirmed the receipt checks: what arrived was checked,
    and testing may start. Written once, never edited or removed.
    """

    sample = models.OneToOneField("lims.Sample", on_delete=models.PROTECT, related_name="receipt_completion")
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    completed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=500, blank=True)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A completed receipt is never edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Receipt records are never deleted.")
