"""
Batches: what a sample was taken from, and the thread that ties a product to
its samples, their results and their certificates.

Two identifiers, deliberately kept apart:

- official_batch_no is the number the manufacturer's approved procedure
  assigned. It is stored exactly as given and the system never generates it.
- internal_id is this system's own reference, issued once by the rule the lab
  configures (BatchNumberRule). Numbers are never reused.

A batch has many samples. A sample that does not belong to a manufactured
batch simply has none.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Upper


class BatchNumberRule(models.Model):
    """How internal batch IDs are built. One row, changed on the Settings screen."""

    prefix = models.CharField(max_length=12, default="BATCH")
    separator = models.CharField(max_length=1, blank=True, default="-")
    include_year = models.BooleanField(default=False)
    include_section = models.BooleanField(default=False)
    include_product = models.BooleanField(default=False)
    digits = models.PositiveSmallIntegerField(default=6)
    # Start again from 1 each January, instead of counting on forever.
    restart_yearly = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "BatchNumberRule":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BatchCounter(models.Model):
    """The last number issued for one scope of the rule. Only ever goes up."""

    scope = models.CharField(max_length=80, unique=True)
    last_no = models.PositiveIntegerField(default=0)


class StageKind(models.TextChoices):
    # Passes when every sample registered for it is approved; fails when one is rejected.
    TESTED = "TESTED", "Tested in the lab"
    # Passes or fails when someone records it, with a password: a line clearance, say.
    RECORDED = "RECORDED", "Recorded by QA"


class QcStagePlan(models.Model):
    """
    The QC stages every batch of a product goes through, in order: one version of
    them. Like a specification it is never edited. A change is a new version, and
    each batch keeps the version in force when it was created.
    """

    product = models.ForeignKey("lims.Product", on_delete=models.PROTECT, related_name="stage_plans")
    version = models.PositiveIntegerField()
    reason = models.CharField(max_length=500)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["product", "version"]
        constraints = [
            models.UniqueConstraint(fields=["product", "version"], name="uniq_stage_plan_version"),
        ]

    def __str__(self):
        return f"{self.product.code} QC stages v{self.version}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A version of the QC stages is never edited — save the change as a new version.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("QC stage versions are never deleted.")


class QcStage(models.Model):
    """
    One QC stage, such as “Final grain” or “Line clearance – compression”: either
    one stage of a version of the product's stages (plan), or one added to a single
    batch by QA (batch). Never both.
    """

    plan = models.ForeignKey(QcStagePlan, null=True, blank=True, on_delete=models.PROTECT, related_name="stages")
    # Set only on a stage added to one batch: the product's stages are not changed.
    batch = models.ForeignKey(
        "Batch", null=True, blank=True, on_delete=models.PROTECT, related_name="extra_stages"
    )
    order = models.PositiveIntegerField()  # 1 = the first stage
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True)
    kind = models.CharField(max_length=10, choices=StageKind.choices)
    # A batch is released only when every required stage has passed. An optional
    # one is shown with the others but never waited for.
    required = models.BooleanField(default=True)
    # Which tests its samples get: the specification of the same key, when one is
    # effective, otherwise the product's own. Kept from version to version, so a
    # renamed stage keeps its tests. Empty on a stage added to a batch means the
    # product's own specification. Null on stages from before keys existed: their
    # key is their name (see stages.tests_key).
    tests_key = models.CharField(max_length=80, null=True, blank=True)
    # Nothing is done for it, no sample registered and nothing recorded, until
    # every earlier required stage of the batch has passed or does not apply.
    after_previous = models.BooleanField(default=False)
    # A batch-record stage's sign-off columns are signed for every step, as the
    # paper record has them, rather than once for the whole stage.
    sign_each_step = models.BooleanField(default=False)
    # Who added a stage to one batch, and why.
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    added_reason = models.CharField(max_length=500, blank=True, default="")
    added_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["plan", "order"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "order"], name="uniq_qc_stage_order"),
            models.UniqueConstraint(fields=["batch", "order"], name="uniq_batch_stage_order"),
            models.CheckConstraint(
                condition=(models.Q(plan__isnull=False, batch__isnull=True)
                           | models.Q(plan__isnull=True, batch__isnull=False)),
                name="qc_stage_plan_or_batch",
            ),
        ]

    def __str__(self):
        return f"{self.order}. {self.name}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A QC stage is never edited — save the change as a new version.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("QC stages are never deleted.")


class _Fixed(models.Model):
    """A row that is written once and never changed or deleted, like the version it belongs to."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError(f"A {self._meta.verbose_name} is never changed (Rule Two).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(f"A {self._meta.verbose_name} is never deleted (Rule Two).")


class QcStep(_Fixed):
    """One step of a recorded stage, as the batch record has it: Premixing, Preparation of binding solution, Drying."""

    stage = models.ForeignKey(QcStage, on_delete=models.PROTECT, related_name="steps")
    order = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    # What to do, as printed on the record: "a) Clean the Sigma Mixer thoroughly and dry it."
    instructions = models.TextField(blank=True)

    class Meta:
        ordering = ["stage", "order"]
        verbose_name = "stage step"
        constraints = [models.UniqueConstraint(fields=["stage", "order"], name="uniq_qc_step_order")]


class CheckpointKind(models.TextChoices):
    NUMBER = "NUMBER", "Number"
    PERCENT = "PERCENT", "Percentage"
    TIME_RANGE = "TIME_RANGE", "Start and end time"
    TIME = "TIME", "Time"
    DATE = "DATE", "Date"
    TEXT = "TEXT", "Text"
    YES_NO = "YES_NO", "Yes / No"
    # Options the lab types itself, such as Complies / Does not comply; an answer
    # not marked acceptable is flagged like a number outside its limits.
    CHOICE = "CHOICE", "Choice from a list"


class QcCheckpoint(_Fixed):
    """
    One value a step asks for: Ciprofloxacin HCl in kg, LOD as a percentage between
    3.00 and 4.50, the start and end time of mixing. A number outside its limits is
    still recorded, flagged, with a reason.
    """

    step = models.ForeignKey(QcStep, on_delete=models.PROTECT, related_name="checkpoints")
    order = models.PositiveIntegerField()
    label = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=CheckpointKind.choices)
    unit = models.CharField(max_length=30, blank=True)  # kg, L, °C; % for a percentage
    min_value = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    max_value = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    decimals = models.PositiveSmallIntegerField(default=2)
    required = models.BooleanField(default=True)
    # A choice's options in order, each with whether it is acceptable:
    # [{"label": "Complies", "ok": true}, {"label": "Does not comply", "ok": false}].
    choices = models.JSONField(default=list, blank=True)
    # The lab's own name for the kind of value, such as Temperature or Equipment ID,
    # when it came from one of its kinds; empty for a built-in kind.
    kind_name = models.CharField(max_length=60, blank=True, default="")

    class Meta:
        ordering = ["step", "order"]
        verbose_name = "check point"
        constraints = [models.UniqueConstraint(fields=["step", "order"], name="uniq_qc_checkpoint_order")]

    def limit_text(self) -> str:
        """“3.00 – 4.50 %”, “NLT 50 °C”, “NMT 4.50 %”, or nothing."""
        def shown(v):
            return f"{v:.{self.decimals}f}"
        unit = f" {self.unit}" if self.unit else ""
        if self.min_value is not None and self.max_value is not None:
            return f"{shown(self.min_value)} – {shown(self.max_value)}{unit}"
        if self.min_value is not None:
            return f"NLT {shown(self.min_value)}{unit}"
        if self.max_value is not None:
            return f"NMT {shown(self.max_value)}{unit}"
        acceptable = [c["label"] for c in self.choices or [] if c.get("ok")]
        if acceptable and len(acceptable) < len(self.choices):
            return "Acceptable: " + " / ".join(acceptable)
        return ""


class CheckpointPreset(models.Model):
    """
    A kind of value the lab defines once and offers in every stage: Temperature in
    °C between 50 and 80, Mixer speed in rpm, Equipment ID, Complies / Does not
    comply. A stage takes a copy when it is saved, so changing or retiring a kind
    later changes no stage already in use.
    """

    name = models.CharField(max_length=60, unique=True)
    kind = models.CharField(max_length=12, choices=CheckpointKind.choices)
    unit = models.CharField(max_length=30, blank=True)
    min_value = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    max_value = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    decimals = models.PositiveSmallIntegerField(default=2)
    choices = models.JSONField(default=list, blank=True)
    # Retired kinds are no longer offered; stages that used one keep their copy.
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class QcSignoff(_Fixed):
    """
    One sign-off column of a recorded stage, signed in order: Done by (Operator),
    Checked by (Production), Checked by (QA). Whoever holds its role signs it.
    """

    stage = models.ForeignKey(QcStage, on_delete=models.PROTECT, related_name="signoffs")
    order = models.PositiveIntegerField()
    title = models.CharField(max_length=60)  # "Done by", "Checked by"
    holder = models.CharField(max_length=60, blank=True)  # "Operator", "Production", "QA"
    role = models.ForeignKey("accounts.Role", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["stage", "order"]
        verbose_name = "sign-off column"
        constraints = [models.UniqueConstraint(fields=["stage", "order"], name="uniq_qc_signoff_order")]


class Batch(models.Model):
    internal_id = models.CharField(max_length=60, unique=True)
    product = models.ForeignKey("lims.Product", on_delete=models.PROTECT, related_name="batches")
    official_batch_no = models.CharField(max_length=60)
    manufacturing_site = models.CharField(max_length=120, blank=True)  # "if applicable"
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    batch_size = models.CharField(max_length=60, blank=True)  # free text, like a sample's quantity
    notes = models.CharField(max_length=500, blank=True)
    # Empty for batches built from the samples registered before batches existed.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # The QC stages this batch goes through, bound when it is created, like a
    # sample's specification. Empty for a batch created before its product had any.
    stage_plan = models.ForeignKey(
        QcStagePlan, null=True, blank=True, on_delete=models.PROTECT, related_name="batches"
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            # B260015 and b260015 are the same batch of the same product.
            models.UniqueConstraint("product", Upper("official_batch_no"), name="uniq_official_batch_per_product"),
        ]

    def __str__(self):
        return f"{self.internal_id} ({self.official_batch_no})"

    def latest_disposition(self) -> "BatchDisposition | None":
        """By the order they were written, which two decisions in one instant cannot blur."""
        return self.dispositions.order_by("-id").first()

    def delete(self, *args, **kwargs):
        raise PermissionError("Batches are never deleted.")


class DispositionDecision(models.TextChoices):
    RELEASED = "RELEASED", "Released"
    REJECTED = "REJECTED", "Rejected"
    QUARANTINED = "QUARANTINED", "Quarantined"


class BatchDisposition(models.Model):
    """
    One decision about a batch by the quality unit. Append-only: the latest row is
    the batch's status, and a batch with none is not decided. A certificate of
    analysis is about a sample and is not this decision.
    """

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="dispositions")
    decision = models.CharField(max_length=12, choices=DispositionDecision.choices)
    reason = models.CharField(max_length=1000)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_at = models.DateTimeField(auto_now_add=True)
    # What the decision was made on, and its hash, so the two stay tied together.
    basis = models.JSONField(default=dict)
    basis_hash = models.CharField(max_length=64)

    class Meta:
        ordering = ["decided_at", "id"]

    def __str__(self):
        return f"{self.batch.internal_id}: {self.decision}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A disposition decision is never changed — record a new one (Rule Two).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Disposition decisions are never deleted (Rule Two).")


class StageDecision(models.TextChoices):
    PASSED = "PASSED", "Passed"
    FAILED = "FAILED", "Failed"


class BatchStageResult(models.Model):
    """
    One record of a QA-recorded stage of one batch, signed with a password.
    Append-only: the latest row counts, and doing a stage again (a second line
    clearance) is a new row beside the first.
    """

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="stage_results")
    stage = models.ForeignKey(QcStage, on_delete=models.PROTECT, related_name="results")
    decision = models.CharField(max_length=10, choices=StageDecision.choices)
    remarks = models.CharField(max_length=1000, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "id"]

    def __str__(self):
        return f"{self.batch.internal_id} · {self.stage.name}: {self.decision}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A stage result is never changed — record the stage again (Rule Two).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Stage results are never deleted (Rule Two).")


class BatchStageApplicability(models.Model):
    """
    QA's word, signed with a password, that one stage does not apply to one batch,
    or applies again. Append-only: the latest row for a stage counts.
    """

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="stage_applicability")
    stage = models.ForeignKey(QcStage, on_delete=models.PROTECT, related_name="applicability")
    applies = models.BooleanField()
    reason = models.CharField(max_length=500)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["recorded_at", "id"]

    def __str__(self):
        return f"{self.batch.internal_id} · {self.stage.name}: {'applies' if self.applies else 'not applicable'}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("This record is never changed — record the stage's applicability again.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("These records are never deleted (Rule Two).")


class DocumentType(models.TextChoices):
    BATCH_RECORD = "BATCH_RECORD", "Batch manufacturing record"
    SPECIFICATION = "SPECIFICATION", "Specification"
    SUPPLIER_COA = "SUPPLIER_COA", "Supplier certificate"
    DEVIATION = "DEVIATION", "Deviation or investigation"
    OTHER = "OTHER", "Other"


def document_path(instance, filename: str) -> str:
    """Never reuse the uploaded name on disk — it can carry path separators."""
    return f"batch-documents/{instance.batch_id}/{uuid.uuid4().hex}.{instance.extension}"


class BatchDocument(models.Model):
    """
    A controlled file kept against a batch. Stored privately and served only to
    people who can see the batch. Never deleted: replaced by a new version, or
    withdrawn with a reason.
    """

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DocumentType.choices)
    title = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1)
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    replaced_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    file = models.FileField(upload_to=document_path, max_length=200)
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
        return f"{self.title} v{self.version}"

    @property
    def is_current(self) -> bool:
        return self.replaced_by_id is None and self.withdrawn_at is None

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = BatchDocument.objects.get(pk=self.pk)
            changed = {
                f.name for f in self._meta.concrete_fields
                if getattr(old, f.attname) != getattr(self, f.attname)
            }
            if changed - self.LATER_FIELDS:
                raise PermissionError("A stored document is never changed — upload a new version instead.")
            if ("replaced_by" in changed and old.replaced_by_id is not None) or (
                changed & {"withdrawn_at", "withdrawn_by", "withdraw_reason"} and old.withdrawn_at is not None
            ):
                raise PermissionError("That document's history is already final.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Batch documents are never deleted — withdraw one with a reason instead.")


class BatchCheckpointEntry(_Fixed):
    """
    A value written on a batch's record for one check point. Never changed: a
    correction is a new entry with its reason, and the latest counts. A number
    outside its limits is flagged and carries why.
    """

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="checkpoint_entries")
    checkpoint = models.ForeignKey(QcCheckpoint, on_delete=models.PROTECT, related_name="entries")
    number = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    text = models.CharField(max_length=1000, blank=True)
    date = models.DateField(null=True, blank=True)
    start = models.DateTimeField(null=True, blank=True)  # a time, or the start of a start and end time
    end = models.DateTimeField(null=True, blank=True)
    yes_no = models.BooleanField(null=True, blank=True)
    out_of_limit = models.BooleanField(default=False)
    reason = models.CharField(max_length=500, blank=True)  # why a value is outside its limits
    correction = models.CharField(max_length=500, blank=True)  # why a value already written was changed
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    entered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["entered_at", "id"]
        verbose_name = "batch record entry"


class BatchStageSignature(_Fixed):
    """
    One sign-off column of a batch's recorded stage, signed with a password. The
    last column also acknowledges every value out of limit on the stage. On a stage
    signed at every step, step says which step it signs, and the last column of a
    step acknowledges that step's values.
    """

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="stage_signatures")
    signoff = models.ForeignKey(QcSignoff, on_delete=models.PROTECT, related_name="signatures")
    # The step it signs, when the stage is signed at every step; empty when once for the stage.
    step = models.ForeignKey(QcStep, null=True, blank=True, on_delete=models.PROTECT, related_name="signatures")
    signed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    signed_at = models.DateTimeField(auto_now_add=True)
    comment = models.CharField(max_length=500, blank=True)
    acknowledged = models.BooleanField(default=False)  # the values out of limit, by the last column

    class Meta:
        ordering = ["signed_at", "id"]
        verbose_name = "stage signature"
        constraints = [
            models.UniqueConstraint(fields=["batch", "signoff"], condition=models.Q(step__isnull=True),
                                    name="uniq_batch_signoff"),
            models.UniqueConstraint(fields=["batch", "signoff", "step"], condition=models.Q(step__isnull=False),
                                    name="uniq_batch_signoff_step"),
        ]


class BatchStageAssignment(_Fixed):
    """
    Who fills one recorded stage of one batch and signs its first column, named by
    whoever may assign stages (the Production supervisor). Never changed: reassigning
    is a new row, and the latest counts. A row naming nobody leaves the stage open to
    anyone who may fill batch records, as a stage never assigned is.
    """

    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="stage_assignments")
    stage = models.ForeignKey(QcStage, on_delete=models.PROTECT, related_name="assignments")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    note = models.CharField(max_length=500, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["assigned_at", "id"]
        verbose_name = "stage assignment"
