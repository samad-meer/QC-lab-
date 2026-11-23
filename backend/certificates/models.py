import uuid

from django.conf import settings
from django.db import models


class CertStatus(models.TextChoices):
    # Signed by the analyst and moving through the workflow's review stages.
    # How far it has got is the signatures it carries, not a status per stage.
    IN_REVIEW = "IN_REVIEW", "Signed by analyst — in review"
    APPROVED = "APPROVED", "Approved — releasable"
    SUPERSEDED = "SUPERSEDED", "Superseded (sent back / corrected)"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


# The only status movements that exist. There is no path that edits content.
ALLOWED_TRANSITIONS = {
    CertStatus.IN_REVIEW: {CertStatus.APPROVED, CertStatus.SUPERSEDED},
    # Its content never changes again, but it can stop being relied on.
    CertStatus.APPROVED: {CertStatus.WITHDRAWN},
    CertStatus.SUPERSEDED: set(),
    CertStatus.WITHDRAWN: set(),
}


class Certificate(models.Model):
    """
    Rule One: the content is frozen at the moment the analyst signs — the
    snapshot and its hash can never change. Later signatures are appended
    as Signature rows; they do not touch the content. A send-back marks
    this version SUPERSEDED and a NEW version is created on the way back
    up — an old approval never carries over onto corrected work.
    """

    sample = models.ForeignKey("lims.Sample", on_delete=models.PROTECT, related_name="certificates")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=CertStatus.choices, default=CertStatus.IN_REVIEW)
    content = models.JSONField()
    content_hash = models.CharField(max_length=64)
    verification_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    superseded_reason = models.CharField(max_length=1000, blank=True)
    # Set once, when a reviewer sends this version back: where, who, when.
    returned_stage = models.CharField(max_length=30, blank=True)
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    returned_at = models.DateTimeField(null=True, blank=True)
    # Set once, if a released certificate is withdrawn.
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_reason = models.CharField(max_length=1000, blank=True)

    IMMUTABLE_FIELDS = {"sample", "version", "content", "content_hash", "verification_uuid", "created_at"}

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sample", "version"], name="uniq_cert_version"),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Certificate.objects.get(pk=self.pk)
            changed = {
                f.name
                for f in self._meta.concrete_fields
                if getattr(old, f.attname) != getattr(self, f.attname)
            }
            frozen = changed & self.IMMUTABLE_FIELDS
            if frozen:
                raise PermissionError(
                    f"A signed certificate can never be edited (Rule One). Attempted: {sorted(frozen)}."
                )
            if "status" in changed and self.status not in ALLOWED_TRANSITIONS[old.status]:
                raise PermissionError(
                    f"Illegal certificate transition {old.status} → {self.status}."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Certificates are never deleted (Rule Two).")

    def __str__(self):
        return f"COA {self.sample.sample_no} v{self.version} [{self.status}]"


# The analyst's signature. Review signatures carry the code of their
# workflow stage instead — "CHECKED", "APPROVED", "QA_REVIEW", …
ANALYSED = "ANALYSED"


class Signature(models.Model):
    """
    An electronic signature: this user approved this exact content
    (identified by hash) at this exact time, after re-entering their
    password. One signature per meaning per certificate version.
    """

    certificate = models.ForeignKey(Certificate, on_delete=models.PROTECT, related_name="signatures")
    meaning = models.CharField(max_length=30)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="signatures")
    name_snapshot = models.CharField(max_length=200)  # name at signing time, permanent
    content_hash = models.CharField(max_length=64)  # what exactly was signed
    # Binds who signed and what they meant to what they signed. Blank on
    # signatures from before it existed.
    seal = models.CharField(max_length=64, blank=True)
    signed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["certificate", "meaning"], name="uniq_signature_meaning"),
        ]
        ordering = ["signed_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A signature can never be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("A signature can never be deleted (Rule Two).")


class PrintEvent(models.Model):
    """Every print recorded: copy 1 is the ORIGINAL, later ones DUPLICATE COPY n."""

    certificate = models.ForeignKey(Certificate, on_delete=models.PROTECT, related_name="prints")
    copy_number = models.PositiveIntegerField()
    printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    printed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["certificate", "copy_number"], name="uniq_print_copy"),
        ]
        ordering = ["copy_number"]

    def delete(self, *args, **kwargs):
        raise PermissionError("The print record is never deleted (Rule Two).")
