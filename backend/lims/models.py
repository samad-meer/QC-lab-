from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class Section(models.Model):
    """One of the three lab sections (extensible)."""

    code = models.CharField(max_length=10, unique=True)  # GF, NUTRA, API
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class SampleSource(models.Model):
    """
    Who samples are received from: a department, a person or a supplier. The
    front desk picks from this list, so one source is never typed three ways.
    A sample keeps the name it was received under, so renaming one later
    never rewrites what was recorded.
    """

    name = models.CharField(max_length=200)
    # Never deleted; inactive stops it being offered.
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(Lower("name"), name="lims_samplesource_name_ci_unique")]

    def __str__(self):
        return self.name


class SampleType(models.TextChoices):
    RAW_MATERIAL = "RAW_MATERIAL", "Raw material"
    PACKAGING = "PACKAGING", "Packaging material"
    IN_PROCESS = "IN_PROCESS", "In-process"
    FINISHED_PRODUCT = "FINISHED_PRODUCT", "Finished product"
    STABILITY = "STABILITY", "Stability"


class Product(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="products")
    # What kind of material this is. Blank until someone sets it; reports show
    # "Not set" rather than guessing.
    sample_type = models.CharField(max_length=20, choices=SampleType.choices, blank=True)
    # --- The product master ------------------------------------------------
    generic_name = models.CharField(max_length=200, blank=True)
    dosage_form = models.CharField(max_length=60, blank=True)  # Tablet, Capsule, Syrup…
    strength = models.CharField(max_length=60, blank=True)  # "500 mg", "100 mg/5 mL"
    pack_size = models.CharField(max_length=60, blank=True)
    # What the front desk starts from; a sample can still say otherwise.
    storage_condition = models.CharField(max_length=120, blank=True)
    shelf_life_months = models.PositiveSmallIntegerField(null=True, blank=True)
    # Never deleted — records point at it. Inactive stops it being offered.
    is_active = models.BooleanField(default=True)
    # How its certificates are laid out. Empty means the lab's default template.
    certificate_template = models.ForeignKey(
        "standards.CertificateTemplate", null=True, blank=True, on_delete=models.PROTECT, related_name="products"
    )
    # The review chain this product's certificates go through. Empty means
    # the lab's default workflow.
    workflow = models.ForeignKey(
        "Workflow", null=True, blank=True, on_delete=models.PROTECT, related_name="products"
    )

    def __str__(self):
        return f"{self.name} ({self.code})"

    def review_workflow(self) -> "Workflow | None":
        return self.workflow or Workflow.default()

    def current_specification(self, stage_key: str = ""):
        """The effective specification: the product's own, or one stage's tests when a key is given."""
        return (
            self.specifications.filter(status=SpecStatus.EFFECTIVE, stage_key=stage_key)
            .order_by("-version")
            .first()
        )

    def current_stage_plan(self):
        """The QC stages a batch created now goes through, or None when none are set up."""
        return self.stage_plans.order_by("-version").first()


class SpecStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    EFFECTIVE = "EFFECTIVE", "Effective"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class Specification(models.Model):
    """
    A versioned specification. Certificates are hard-bound to the spec
    version in force when the sample was registered — editing limits later
    must never re-evaluate old certificates, so specs are never edited in
    place: a change is a new version.
    """

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="specifications")
    # Which tests these are: empty for the product's own specification, or the key of
    # one of its QC stages (batches.stages.tests_key), whose samples are tested on
    # these instead. Each has its own versions. stage_name is the stage's name when
    # the version was drafted, for the record.
    stage_key = models.CharField(max_length=80, blank=True, default="")
    stage_name = models.CharField(max_length=80, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=SpecStatus.choices, default=SpecStatus.EFFECTIVE)
    effective_date = models.DateField()
    # When this version is next due for periodic review, if the lab sets one.
    review_date = models.DateField(null=True, blank=True)
    # Who wrote this version and why, and who made it effective. Empty on
    # versions from before specifications were edited in the application.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    change_reason = models.CharField(max_length=500, blank=True)
    # Whoever last changed the draft is no more independent than whoever started it.
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # A hash of the tests and limits as approved, so the approval is tied to them.
    approved_digest = models.CharField(max_length=64, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "stage_key", "version"], name="uniq_spec_version"),
        ]

    def __str__(self):
        return f"{self.product.code} {self.stage_name + ' ' if self.stage_key else ''}spec v{self.version}"

    @property
    def label(self) -> str:
        """“Specification, version 3”, or “Final grain tests, version 1”."""
        what = f"{self.stage_name} tests" if self.stage_key else "Specification"
        return f"{what}, version {self.version}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Specification.objects.get(pk=self.pk)
            if old.status != SpecStatus.DRAFT:
                changed = {
                    f.name for f in self._meta.concrete_fields
                    if getattr(old, f.attname) != getattr(self, f.attname)
                }
                if changed - {"status", "review_date"} or (
                    "status" in changed and (old.status, self.status) != (SpecStatus.EFFECTIVE, SpecStatus.SUPERSEDED)
                ):
                    raise PermissionError("An approved specification is never edited — draft a new version.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != SpecStatus.DRAFT:
            raise PermissionError("An approved specification is never deleted.")
        super().delete(*args, **kwargs)


class LimitType(models.TextChoices):
    NUMERIC_RANGE = "NUMERIC_RANGE", "Numeric: between min and max"
    NUMERIC_MIN = "NUMERIC_MIN", "Numeric: not less than (NLT)"
    NUMERIC_MAX = "NUMERIC_MAX", "Numeric: not more than (NMT)"
    TEXT_COMPLIES = "TEXT_COMPLIES", "Text: must match expected wording"
    REPORT_ONLY = "REPORT_ONLY", "Report only (no limit)"


class TestDefinition(models.Model):
    specification = models.ForeignKey(Specification, on_delete=models.CASCADE, related_name="tests")
    order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=200)
    method = models.CharField(max_length=200, blank=True)  # e.g. "USP <711>", "In-house HPLC-04"
    # The method in the method master, where the test names one. Approving the
    # specification then needs it effective and validated, and a result on this
    # test needs someone qualified on its code.
    method_record = models.ForeignKey(
        "labrecords.Method", null=True, blank=True, on_delete=models.PROTECT, related_name="tests"
    )
    unit = models.CharField(max_length=30, blank=True)
    limit_type = models.CharField(max_length=20, choices=LimitType.choices)
    min_value = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    max_value = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    # Rounding decided once, at spec level: entered values are rounded to
    # this many decimal places (ROUND_HALF_UP) before comparison.
    decimals = models.PositiveIntegerField(default=2)
    text_expected = models.CharField(max_length=200, blank=True)  # e.g. "Complies"
    # Human-readable limit exactly as it should appear on the COA.
    limit_text = models.CharField(max_length=200)
    # The template this was copied from, e.g. "ASSAY-HPLC v3". A copy: the
    # template can change later without touching this.
    source = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} [{self.limit_text}]"

    def _check_draft(self):
        if self.specification.status != SpecStatus.DRAFT:
            raise PermissionError("A test of an approved specification is never changed — draft a new version.")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            self._check_draft()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._check_draft()
        super().delete(*args, **kwargs)


class Workflow(models.Model):
    """
    The signatures a certificate needs after the analyst's, in order — for
    example Checked → Approved, or just Approved, or Checked → QA review →
    Approved. Each product chooses one; a product without one uses the
    default.

    Like a specification, a workflow is never edited in place: changing its
    stages makes a new WorkflowVersion, and each sample is bound to the
    version in force when it was registered. An edit made today never
    re-routes a sample that is already in review.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=300, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True), name="one_default_workflow"
            ),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def default(cls) -> "Workflow | None":
        return cls.objects.filter(is_default=True).first()

    def current_version(self) -> "WorkflowVersion | None":
        return self.versions.order_by("-version").first()

    def delete(self, *args, **kwargs):
        if self.is_default:
            raise PermissionError("The default workflow cannot be deleted. Make another one the default first.")
        if self.products.exists():
            raise PermissionError(
                f"{self.products.count()} product(s) still use {self.name}. Move them to another workflow first."
            )
        if Sample.objects.filter(workflow_version__workflow=self).exists():
            raise PermissionError(
                f"Samples have already been through {self.name}, so it stays on record (Rule Two)."
            )
        super().delete(*args, **kwargs)


class WorkflowVersion(models.Model):
    """One fixed set of stages. Never edited — a change is a new version."""

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=500, blank=True)
    # The analyst's step: must the analyst accept the sample (confirm they
    # have received it) before entering results? Review stages carry their
    # own flag. Checklists live in execution.ChecklistItem.
    testing_requires_acceptance = models.BooleanField(default=False)
    # Does the certificate carry the retest history (the failed result, who
    # authorized the retest and why, and the retest result)? Frozen into the
    # certificate when the analyst signs, so every copy prints the same.
    coa_show_retests = models.BooleanField(default=False)

    class Meta:
        ordering = ["workflow", "version"]
        constraints = [
            models.UniqueConstraint(fields=["workflow", "version"], name="uniq_workflow_version"),
        ]

    def __str__(self):
        return f"{self.workflow.name} v{self.version}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A workflow version is never edited — save the change as a new version.")
        super().save(*args, **kwargs)


class WorkflowStage(models.Model):
    """
    One review signature after the analyst's. Stages are signed in order, by
    anyone holding the stage's role; signing the last one releases the
    certificate. Which role signs is the grant — review signatures are not
    permissions.
    """

    version = models.ForeignKey(WorkflowVersion, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveIntegerField()  # 1 = the first review after the analyst
    # Recorded as the meaning of the signature; unique within a version.
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=60)  # the step's label, e.g. "Checked"
    signature_title = models.CharField(max_length=60)  # e.g. "Checked by"
    holder_title = models.CharField(max_length=60, blank=True)  # e.g. "AM / DM"
    role = models.ForeignKey("accounts.Role", on_delete=models.PROTECT, related_name="workflow_stages")
    # Must someone take the stage (or accept it when it is assigned to them)
    # before they can sign it? Off means anyone holding the role may sign.
    requires_acceptance = models.BooleanField(default=False)

    class Meta:
        ordering = ["version", "order"]
        constraints = [
            models.UniqueConstraint(fields=["version", "order"], name="uniq_stage_order"),
            models.UniqueConstraint(fields=["version", "code"], name="uniq_stage_code"),
        ]

    def __str__(self):
        return f"{self.version} · {self.order}. {self.name}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A workflow stage is never edited — save the change as a new version.")
        super().save(*args, **kwargs)

    @property
    def full_title(self) -> str:
        """As printed under the signature line: “Checked by (AM / DM)”."""
        return f"{self.signature_title} ({self.holder_title})" if self.holder_title else self.signature_title

    @property
    def holder(self) -> str:
        """Who the work is waiting for, in the words this lab uses."""
        return self.holder_title or self.role.name


class SampleStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received / assigned"
    IN_TESTING = "IN_TESTING", "In testing"
    # Waiting for one of the workflow's review signatures; Sample.review_stage
    # says which. (Before workflows: AWAITING_CHECK and AWAITING_APPROVAL.)
    IN_REVIEW = "IN_REVIEW", "In review"
    APPROVED = "APPROVED", "Approved"
    # The two other ways a sample ends. Neither has a certificate.
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


# Nothing more happens to a sample in one of these.
FINISHED = (SampleStatus.APPROVED, SampleStatus.REJECTED, SampleStatus.CANCELLED)
# Before the analyst signs.
UNSIGNED = (SampleStatus.RECEIVED, SampleStatus.IN_TESTING)


class Sample(models.Model):
    """
    One sample on its journey. The sample number is issued once and never
    reused (SampleCounter); the specification is bound at registration.
    """

    sample_no = models.CharField(max_length=30, unique=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="samples")
    specification = models.ForeignKey(Specification, on_delete=models.PROTECT, related_name="samples")
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="samples")
    # The batch it was taken from. Empty for a sample that does not belong to a
    # manufactured batch (purified water, a swab, a complaint), which says what
    # it is in `reference` instead.
    batch = models.ForeignKey(
        "batches.Batch", null=True, blank=True, on_delete=models.PROTECT, related_name="samples"
    )
    # The official number, copied from the batch at registration. Blank without a batch.
    batch_no = models.CharField(max_length=60, blank=True)
    # The batch's QC stage this sample was taken for, such as “Final grain”. Set at
    # registration and never changed; empty when the batch has no stages.
    qc_stage = models.ForeignKey(
        "batches.QcStage", null=True, blank=True, on_delete=models.PROTECT, related_name="samples"
    )
    reference = models.CharField(max_length=200, blank=True)
    quantity = models.CharField(max_length=60)  # free text: "2 x 100 g", "60 tablets"
    received_from = models.CharField(max_length=200)
    received_at = models.DateTimeField()
    due_date = models.DateField()

    # --- Batch details a certificate of analysis is expected to carry ----
    # Optional: a raw material may have no manufacturing date on the drum,
    # and an in-process sample has no expiry.
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    storage_condition = models.CharField(max_length=120, blank=True)
    # Why a batch already past its expiry date is being tested. Prints on the certificate.
    past_expiry_reason = models.CharField(max_length=300, blank=True)
    assigned_analyst = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_samples"
    )
    status = models.CharField(
        max_length=20, choices=SampleStatus.choices, default=SampleStatus.RECEIVED, db_index=True
    )
    # The review chain, bound at registration like the specification.
    workflow_version = models.ForeignKey(
        WorkflowVersion, on_delete=models.PROTECT, related_name="samples"
    )
    # While IN_REVIEW: the stage whose signature is awaited.
    review_stage = models.ForeignKey(
        WorkflowStage, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registered_samples"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when a sample is rejected or cancelled.
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.sample_no

    def save(self, *args, **kwargs):
        if self.pk is None and self.workflow_version_id is None:
            workflow = self.product.review_workflow()
            if workflow is None:
                raise ValueError("No review workflow is set up. Create a default workflow first.")
            self.workflow_version = workflow.current_version()
        super().save(*args, **kwargs)

    @property
    def batch_label(self) -> str:
        """What to call it wherever a batch would be named."""
        return self.batch_no or self.reference

    def status_label(self) -> str:
        if self.status == SampleStatus.IN_REVIEW and self.review_stage_id:
            return f"Awaiting {self.review_stage.holder}"
        return self.get_status_display()

    def current_results(self):
        return self.results.filter(is_superseded=False).select_related("test_definition", "entered_by")

    def has_failures(self) -> bool:
        return self.current_results().filter(outcome=Outcome.FAIL).exists()

    def delete(self, *args, **kwargs):
        raise PermissionError("Samples are never deleted (Rule Two).")


class SampleCounter(models.Model):
    """Issues sample numbers per section per year. Numbers are never reused."""

    year = models.PositiveIntegerField()
    section = models.ForeignKey(Section, on_delete=models.PROTECT)
    last_no = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["year", "section"], name="uniq_counter_year_section"),
        ]


class Outcome(models.TextChoices):
    PASS = "PASS", "Pass"
    FAIL = "FAIL", "Fail"
    REPORTED = "REPORTED", "Reported (no limit)"


class TestResult(models.Model):
    """
    One entered result. Rule Two: a wrong value is never edited or deleted —
    it is marked superseded (with who/why/when) and a NEW row becomes current.
    save() enforces that nothing else about a row can ever change.
    """

    sample = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name="results")
    test_definition = models.ForeignKey(TestDefinition, on_delete=models.PROTECT, related_name="results")
    value_numeric = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    value_text = models.CharField(max_length=200, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    entered_at = models.DateTimeField(auto_now_add=True)

    is_superseded = models.BooleanField(default=False)
    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    supersede_reason = models.CharField(max_length=500, blank=True)
    replaced_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    SUPERSEDE_FIELDS = {"is_superseded", "superseded_at", "superseded_by_user", "supersede_reason", "replaced_by"}

    class Meta:
        constraints = [
            # Only one CURRENT result per test per sample.
            models.UniqueConstraint(
                fields=["sample", "test_definition"],
                condition=Q(is_superseded=False),
                name="uniq_current_result",
            ),
        ]
        ordering = ["test_definition__order", "entered_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = TestResult.objects.get(pk=self.pk)
            changed = {
                f.name
                for f in self._meta.concrete_fields
                if getattr(old, f.attname) != getattr(self, f.attname)
            }
            illegal = changed - self.SUPERSEDE_FIELDS
            if illegal:
                raise PermissionError(
                    f"Test results are never edited (Rule Two). Attempted change to: {sorted(illegal)}. "
                    "Enter a new result with a supersede reason instead."
                )
            if old.is_superseded:
                # One exception: linking the replacement row, exactly once.
                if not (changed <= {"replaced_by"} and old.replaced_by_id is None):
                    raise PermissionError("A superseded result can never change again.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Test results are never deleted (Rule Two).")


class WorkflowEvent(models.Model):
    """Every movement of a sample, including send-backs with their comments."""

    sample = models.ForeignKey(Sample, on_delete=models.PROTECT, related_name="events")
    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # No choices: history keeps statuses from earlier releases
    # (AWAITING_CHECK, AWAITING_APPROVAL) exactly as they were recorded.
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    comment = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Workflow history is append-only and can never be edited (Rule Two).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Workflow history is never deleted (Rule Two).")
