"""
Quality records: investigations of out-of-specification and out-of-trend
results, deviations, and the corrective and preventive actions that follow.

A failed result stays exactly as it was entered (lims.TestResult) and an
investigation only ever points at it. Nothing here changes a result, a
retest or a certificate, and a passing retest closes nothing: an
investigation ends when someone independent approves its closure.

- Investigation — one OOS, OOT or deviation, from opening to closure.
- CapaAction — one corrective or preventive action. Added, completed once, then
  verified once by someone else. Never removed.
- InvestigationEvent — everything that happened to it, with old and new
  values. Append-only.
- InvestigationCounter — issues references. Never reused.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


class InvestigationKind(models.TextChoices):
    OOS = "OOS", "Out of specification"
    OOT = "OOT", "Out of trend"
    DEVIATION = "DEVIATION", "Deviation"


class Classification(models.TextChoices):
    MINOR = "MINOR", "Minor"
    MAJOR = "MAJOR", "Major"
    CRITICAL = "CRITICAL", "Critical"


class LabFinding(models.TextChoices):
    """What the laboratory investigation, the first phase of an OOS, found."""

    ASSIGNABLE = "ASSIGNABLE", "Laboratory error found"
    NONE_FOUND = "NONE_FOUND", "No laboratory error found"


class Conclusion(models.TextChoices):
    """Where an OOS investigation ended. Only a found error invalidates a failure."""

    INVALIDATED = "INVALIDATED", "Invalidated: a laboratory error caused it"
    NOT_CONFIRMED = "NOT_CONFIRMED", "Not confirmed: no error found, retests within limits"
    CONFIRMED = "CONFIRMED", "Confirmed: the failure stands"


class InvestigationStatus(models.TextChoices):
    OPEN = "OPEN", "Under investigation"
    PENDING_CLOSURE = "PENDING_CLOSURE", "Awaiting closure approval"
    CLOSED = "CLOSED", "Closed"


def _changed(instance, model) -> set[str]:
    old = model.objects.get(pk=instance.pk)
    return {
        f.name
        for f in instance._meta.concrete_fields
        if getattr(old, f.attname) != getattr(instance, f.attname)
    }


class Investigation(models.Model):
    """One investigation or deviation. Once closed it never changes again."""

    reference = models.CharField(max_length=30, unique=True)
    kind = models.CharField(max_length=10, choices=InvestigationKind.choices)
    classification = models.CharField(max_length=10, choices=Classification.choices, blank=True)
    # What it concerns. A deviation may concern a batch, or nothing recorded here.
    sample = models.ForeignKey(
        "lims.Sample", null=True, blank=True, on_delete=models.PROTECT, related_name="investigations"
    )
    test_definition = models.ForeignKey(
        "lims.TestDefinition", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    result = models.ForeignKey(
        "lims.TestResult", null=True, blank=True, on_delete=models.PROTECT, related_name="investigations"
    )
    product = models.ForeignKey(
        "lims.Product", null=True, blank=True, on_delete=models.PROTECT, related_name="investigations"
    )
    batch_no = models.CharField(max_length=60, blank=True)

    description = models.TextField(max_length=4000)
    root_cause = models.TextField(max_length=4000, blank=True)
    outcome = models.TextField(max_length=4000, blank=True)
    # The laboratory investigation, which comes before any retest.
    lab_finding = models.CharField(max_length=12, choices=LabFinding.choices, blank=True)
    lab_finding_notes = models.TextField(max_length=4000, blank=True)
    lab_finding_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    lab_finding_at = models.DateTimeField(null=True, blank=True)
    conclusion = models.CharField(max_length=14, choices=Conclusion.choices, blank=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    due_date = models.DateField()
    status = models.CharField(
        max_length=16, choices=InvestigationStatus.choices, default=InvestigationStatus.OPEN, db_index=True
    )

    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    opened_at = models.DateTimeField(auto_now_add=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    # A hash of what was approved, so the closure is tied to it.
    closure_digest = models.CharField(max_length=64, blank=True)

    FIXED_FIELDS = {"reference", "kind", "sample", "test_definition", "result", "opened_by", "opened_at"}

    class Meta:
        ordering = ["-opened_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "test_definition"],
                condition=Q(kind="OOS") & ~Q(status="CLOSED"),
                name="one_open_oos_per_test",
            ),
        ]

    def __str__(self):
        return self.reference

    def save(self, *args, **kwargs):
        if self.pk is not None:
            if Investigation.objects.get(pk=self.pk).status == InvestigationStatus.CLOSED:
                raise PermissionError("A closed investigation never changes again (Rule One).")
            fixed = _changed(self, Investigation) & self.FIXED_FIELDS
            if fixed:
                raise PermissionError(f"What an investigation concerns is fixed. Attempted: {sorted(fixed)}.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Investigations are never deleted (Rule Two).")


class CapaKind(models.TextChoices):
    CORRECTIVE = "CORRECTIVE", "Corrective"
    PREVENTIVE = "PREVENTIVE", "Preventive"


class CapaAction(models.Model):
    """One action. Completed once, verified once; never edited, reopened or removed."""

    investigation = models.ForeignKey(Investigation, on_delete=models.PROTECT, related_name="actions")
    kind = models.CharField(max_length=12, choices=CapaKind.choices)
    description = models.CharField(max_length=1000)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    due_date = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completion_note = models.CharField(max_length=1000, blank=True)
    # Whether it worked is judged by someone other than its owner and whoever completed it.
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_note = models.CharField(max_length=1000, blank=True)

    COMPLETE_FIELDS = {"completed_by", "completed_at", "completion_note"}
    VERIFY_FIELDS = {"verified_by", "verified_at", "verification_note"}

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = CapaAction.objects.get(pk=self.pk)
            allowed = self.COMPLETE_FIELDS if old.completed_at is None else self.VERIFY_FIELDS
            if old.verified_at is not None or _changed(self, CapaAction) - allowed:
                raise PermissionError("An action is only ever completed once, and verified once — never rewritten.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Actions are never deleted (Rule Two).")


class InvestigationEvent(models.Model):
    """One thing that happened to an investigation. Append-only."""

    investigation = models.ForeignKey(Investigation, on_delete=models.PROTECT, related_name="events")
    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # "Opened", "Changed", "Sent for closure approval"… as a person reads it.
    what = models.CharField(max_length=60)
    # [{"field": "Root cause", "old": "…", "new": "…"}]
    changes = models.JSONField(default=list, blank=True)
    comment = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["at", "id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Investigation history is append-only (Rule Two).")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Investigation history is never deleted (Rule Two).")


class InvestigationCounter(models.Model):
    """Issues investigation references per year. Numbers are never reused."""

    year = models.PositiveIntegerField(unique=True)
    last_no = models.PositiveIntegerField(default=0)
