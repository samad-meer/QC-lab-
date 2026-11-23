"""
The lab's own records: what a result depends on, and what happens around it.

- Instrument, CalibrationEvent — what was measured with, and its logbook.
- Material — reference standards, reagents, columns and consumables, by lot.
- Method — the method master, versioned like a specification.
- Qualification — who may run a method, and until when.
- ResultRecord, ResultReading — the raw data behind one entered result.
- CustodyEvent — who held a sample, where it was kept, and how it ended.
- ChangeRecord, ChangeCounter — change control.
- RecordEvent — what happened to any of these, with old and new values.

Nothing here is deleted. A log is append-only: a mistake is corrected by a new
row. A master record is corrected with a reason, and RecordEvent keeps the old
value. The rules live in services.py.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Upper
from django.db.models.signals import m2m_changed
from django.dispatch import receiver


def _changed(instance, model) -> set[str]:
    old = model.objects.get(pk=instance.pk)
    return {
        f.name
        for f in instance._meta.concrete_fields
        if getattr(old, f.attname) != getattr(instance, f.attname)
    }


class AppendOnly(models.Model):
    """A row written once. A mistake in it is put right by a new row, not by changing this one."""

    NAME = "This record"

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError(f"{self.NAME} is append-only (Rule Two).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(f"{self.NAME} is never deleted (Rule Two).")


class RecordEvent(AppendOnly):
    """One thing that happened to a record here. Its register and id say which."""

    NAME = "Record history"

    register = models.CharField(max_length=20)
    record_id = models.PositiveBigIntegerField()
    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # "Corrected", "Made effective"… as a person reads it.
    what = models.CharField(max_length=60)
    # [{"field": "Location", "old": "…", "new": "…"}]
    changes = models.JSONField(default=list, blank=True)
    comment = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["at", "id"]
        indexes = [models.Index(fields=["register", "record_id"], name="record_event_lookup")]


# --- instruments ---------------------------------------------------------------

class InstrumentStatus(models.TextChoices):
    IN_SERVICE = "IN_SERVICE", "In service"
    OUT_OF_SERVICE = "OUT_OF_SERVICE", "Out of service"
    RETIRED = "RETIRED", "Retired"


class Instrument(models.Model):
    """One instrument. Corrected with a reason; once retired it never changes again."""

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=100)
    location = models.CharField(max_length=120)
    serial_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=16, choices=InstrumentStatus.choices, default=InstrumentStatus.IN_SERVICE, db_index=True
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "id"]
        constraints = [models.UniqueConstraint(Upper("code"), name="uniq_instrument_code")]

    def __str__(self):
        return f"{self.code} ({self.name})"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            if Instrument.objects.get(pk=self.pk).status == InstrumentStatus.RETIRED:
                raise PermissionError("A retired instrument never changes again.")
            if _changed(self, Instrument) & {"created_by", "created_at"}:
                raise PermissionError("Who added an instrument is fixed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Instruments are never deleted — retire one instead.")


class CalibrationKind(models.TextChoices):
    CALIBRATION = "CALIBRATION", "Calibration"
    MAINTENANCE = "MAINTENANCE", "Maintenance"
    REPAIR = "REPAIR", "Repair"
    QUALIFICATION = "QUALIFICATION", "Qualification"


class CalibrationOutcome(models.TextChoices):
    PASS = "PASS", "Pass"
    FAIL = "FAIL", "Fail"


class CalibrationEvent(AppendOnly):
    """One line of an instrument's logbook."""

    NAME = "An instrument's logbook"

    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=14, choices=CalibrationKind.choices)
    performed_at = models.DateTimeField()
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    outcome = models.CharField(max_length=4, choices=CalibrationOutcome.choices)
    # The certificate or logbook number.
    reference = models.CharField(max_length=100)
    # When the next one is due. Needed on a passing calibration.
    next_due = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=1000, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at", "-id"]


# --- reference standards, reagents, columns -------------------------------------

class MaterialKind(models.TextChoices):
    REFERENCE_STANDARD = "REFERENCE_STANDARD", "Reference standard"
    REAGENT = "REAGENT", "Reagent"
    COLUMN = "COLUMN", "Column"
    CONSUMABLE = "CONSUMABLE", "Consumable"


class MaterialStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    QUARANTINED = "QUARANTINED", "Quarantined"
    RETIRED = "RETIRED", "Retired"


class Material(models.Model):
    """
    One lot of something used in testing. The same code on another lot is
    another row, because each lot has its own expiry and potency.
    """

    kind = models.CharField(max_length=18, choices=MaterialKind.choices)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    lot = models.CharField(max_length=60)
    supplier = models.CharField(max_length=200, blank=True)
    potency = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    received_on = models.DateField()
    opened_on = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    status = models.CharField(
        max_length=12, choices=MaterialStatus.choices, default=MaterialStatus.QUARANTINED, db_index=True
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "lot", "id"]
        constraints = [models.UniqueConstraint(Upper("code"), Upper("lot"), name="uniq_material_lot")]

    def __str__(self):
        return f"{self.code} lot {self.lot}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            if Material.objects.get(pk=self.pk).status == MaterialStatus.RETIRED:
                raise PermissionError("A retired material never changes again.")
            if _changed(self, Material) & {"created_by", "created_at"}:
                raise PermissionError("Who added a material is fixed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Materials are never deleted — retire one instead.")


# --- the method master ----------------------------------------------------------

class ValidationStatus(models.TextChoices):
    VALIDATED = "VALIDATED", "Validated"
    VERIFIED = "VERIFIED", "Verified"
    COMPENDIAL = "COMPENDIAL", "Compendial"
    NOT_VALIDATED = "NOT_VALIDATED", "Not validated"


class MethodStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    EFFECTIVE = "EFFECTIVE", "Effective"
    RETIRED = "RETIRED", "Retired"


class Method(models.Model):
    """
    One version of a test method. It moves one way, like a specification: a draft
    changes freely and affects nothing, and someone other than its author makes
    it effective. The version it replaces is retired then, not before.
    """

    code = models.CharField(max_length=40)
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=200)
    document_ref = models.CharField(max_length=200)
    validation_status = models.CharField(max_length=14, choices=ValidationStatus.choices)
    status = models.CharField(max_length=10, choices=MethodStatus.choices, default=MethodStatus.DRAFT, db_index=True)
    # Why this version exists. Blank on a first version.
    change_reason = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Whoever last changed the draft is no more independent than whoever started it.
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # A hash of what was approved, so the approval is tied to it.
    approved_digest = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["code", "-version"]
        constraints = [
            models.UniqueConstraint(Upper("code"), "version", name="uniq_method_version"),
            models.UniqueConstraint(Upper("code"), condition=Q(status="EFFECTIVE"), name="one_effective_method"),
            models.UniqueConstraint(Upper("code"), condition=Q(status="DRAFT"), name="one_draft_method"),
        ]

    def __str__(self):
        return f"{self.code} v{self.version}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Method.objects.get(pk=self.pk)
            changed = _changed(self, Method)
            if old.status == MethodStatus.RETIRED:
                raise PermissionError("A retired method never changes again.")
            if old.status == MethodStatus.EFFECTIVE and (changed - {"status"} or self.status != MethodStatus.RETIRED):
                raise PermissionError("An effective method is never edited — draft a new version.")
            if changed & {"code", "version", "created_by", "created_at"}:
                raise PermissionError("Which method and version a row is, and who wrote it, is fixed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Methods are never deleted — retire one instead.")


class Qualification(models.Model):
    """
    One person qualified on one method, until a date. Holds the method's code,
    not one version, so it survives a new version of the method. Granted once,
    and only ever revoked; a renewal is a new row.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="qualifications")
    method = models.CharField(max_length=40, db_index=True)
    qualified_on = models.DateField()
    expires_on = models.DateField()
    qualified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revoke_reason = models.CharField(max_length=500, blank=True)

    REVOKE_FIELDS = {"revoked_at", "revoked_by", "revoke_reason"}

    class Meta:
        ordering = ["-qualified_on", "-id"]

    def __str__(self):
        return f"{self.user} on {self.method}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Qualification.objects.get(pk=self.pk)
            if old.revoked_at is not None or _changed(self, Qualification) - self.REVOKE_FIELDS:
                raise PermissionError("A qualification is only ever revoked once — never rewritten.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Qualifications are never deleted — revoke one instead.")


# --- raw data ---------------------------------------------------------------------

class ResultRecord(AppendOnly):
    """
    What stands behind one entered result. A result corrected later is a new
    TestResult with a record of its own, so this one never needs to change.
    """

    NAME = "The raw data of a result"

    result = models.OneToOneField("lims.TestResult", on_delete=models.PROTECT, related_name="raw_data")
    worksheet_ref = models.CharField(max_length=100, blank=True)
    instrument = models.ForeignKey(
        Instrument, null=True, blank=True, on_delete=models.PROTECT, related_name="result_records"
    )
    materials = models.ManyToManyField(Material, blank=True, related_name="result_records")
    notes = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


@receiver(m2m_changed, sender=ResultRecord.materials.through)
def materials_are_written_once(sender, instance, action, reverse, **kwargs):
    """A many-to-many row never passes through save(), so the same rule is kept here."""
    if action in ("pre_remove", "pre_clear") or (action == "pre_add" and (reverse or instance.materials.exists())):
        raise PermissionError("The materials on a result are written once (Rule Two).")


class ResultReading(AppendOnly):
    """One replicate. The reported value comes from these, on the server."""

    NAME = "A reading"

    record = models.ForeignKey(ResultRecord, on_delete=models.PROTECT, related_name="readings")
    order = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=60)
    value = models.DecimalField(max_digits=14, decimal_places=6)

    class Meta:
        ordering = ["order", "id"]


# --- chain of custody -------------------------------------------------------------

class CustodyAction(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    TRANSFERRED = "TRANSFERRED", "Transferred"
    STORED = "STORED", "Stored"
    RETAINED = "RETAINED", "Retained"
    DESTROYED = "DESTROYED", "Destroyed"


class CustodyEvent(AppendOnly):
    """One movement of a sample. The sample's chain of custody is these, in order."""

    NAME = "The chain of custody"

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="custody_events")
    action = models.CharField(max_length=12, choices=CustodyAction.choices)
    location = models.CharField(max_length=120, blank=True)
    from_person = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    to_person = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.CharField(max_length=60, blank=True)  # free text, like a sample's quantity
    note = models.CharField(max_length=1000, blank=True)
    # Only on RETAINED: nothing is destroyed until this date has passed.
    retain_until = models.DateField(null=True, blank=True)
    # Only on DESTROYED.
    witness = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    at = models.DateTimeField(auto_now_add=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(action="RETAINED") | Q(retain_until__isnull=False), name="retained_has_a_date",
            ),
            models.CheckConstraint(
                condition=~Q(action="DESTROYED") | Q(witness__isnull=False), name="destroyed_has_a_witness",
            ),
            # One end per sample, whatever two screens try at the same moment.
            models.UniqueConstraint(fields=["sample"], condition=Q(action="DESTROYED"), name="destroyed_once"),
        ]


# --- change control ---------------------------------------------------------------

class ChangeCategory(models.TextChoices):
    SPECIFICATION = "SPECIFICATION", "Specification"
    METHOD = "METHOD", "Method"
    INSTRUMENT = "INSTRUMENT", "Instrument"
    PROCESS = "PROCESS", "Process"
    SYSTEM = "SYSTEM", "System"
    OTHER = "OTHER", "Other"


class ChangeStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    APPROVED = "APPROVED", "Approved"
    IMPLEMENTED = "IMPLEMENTED", "Implemented"
    CLOSED = "CLOSED", "Closed"
    REJECTED = "REJECTED", "Rejected"


class ChangeRecord(models.Model):
    """One proposed change. What it says is fixed once approved; closed or rejected, nothing changes."""

    reference = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=4000)
    reason = models.TextField(max_length=4000)
    impact_assessment = models.TextField(max_length=4000)
    category = models.CharField(max_length=14, choices=ChangeCategory.choices)
    status = models.CharField(max_length=12, choices=ChangeStatus.choices, default=ChangeStatus.OPEN, db_index=True)

    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    raised_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # A hash of what was approved, so the approval is tied to it.
    approved_digest = models.CharField(max_length=64, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.CharField(max_length=1000, blank=True)
    implemented_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    implemented_at = models.DateTimeField(null=True, blank=True)
    implementation_note = models.CharField(max_length=1000, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    FIXED_FIELDS = {"reference", "raised_by", "raised_at"}
    # What the approver read.
    CONTENT_FIELDS = {"title", "description", "reason", "impact_assessment", "category"}
    MOVES = {
        ChangeStatus.OPEN: {ChangeStatus.APPROVED, ChangeStatus.REJECTED},
        ChangeStatus.APPROVED: {ChangeStatus.IMPLEMENTED},
        ChangeStatus.IMPLEMENTED: {ChangeStatus.CLOSED},
    }

    class Meta:
        ordering = ["-raised_at", "-id"]

    def __str__(self):
        return self.reference

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = ChangeRecord.objects.get(pk=self.pk)
            changed = _changed(self, ChangeRecord)
            if old.status in (ChangeStatus.CLOSED, ChangeStatus.REJECTED):
                raise PermissionError("A closed or rejected change never changes again (Rule One).")
            if changed & self.FIXED_FIELDS:
                raise PermissionError("A change record's reference and who raised it are fixed.")
            if old.status != ChangeStatus.OPEN and changed & self.CONTENT_FIELDS:
                raise PermissionError("What was approved cannot change. Raise a new change record.")
            if "status" in changed and self.status not in self.MOVES.get(old.status, ()):
                raise PermissionError(f"A change record cannot move from {old.status} to {self.status}.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Change records are never deleted (Rule Two).")


class ChangeCounter(models.Model):
    """Issues change references per year. Numbers are never reused."""

    year = models.PositiveIntegerField(unique=True)
    last_no = models.PositiveIntegerField(default=0)
