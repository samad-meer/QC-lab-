from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    """
    Append-only audit trail. Rule Two: nothing is ever deleted.

    Application-level guards below; on PostgreSQL, database triggers
    (certificates migration 0002) additionally forbid UPDATE/DELETE so
    not even direct SQL can alter history.
    """

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    # Denormalised so the trail stays readable even if the account changes.
    actor_username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=60, db_index=True)
    entity = models.CharField(max_length=60)
    entity_id = models.CharField(max_length=60, db_index=True)
    details = models.JSONField(default=dict, blank=True)
    # Where the action came from. Blank for anything not raised by a request
    # (management commands, migrations).
    ip_address = models.CharField(max_length=45, blank=True)

    class Meta:
        ordering = ["-at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Audit events are append-only and can never be edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit events can never be deleted.")

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.actor_username} {self.action} {self.entity}#{self.entity_id}"


class AuditReview(models.Model):
    """Someone read the trail for a period and signed for what they found. Append-only."""

    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    name_snapshot = models.CharField(max_length=200)
    reviewed_at = models.DateTimeField(auto_now_add=True)
    covered_from = models.DateTimeField()
    covered_to = models.DateTimeField()
    events = models.PositiveIntegerField()
    findings = models.TextField(max_length=2000)

    class Meta:
        ordering = ["-covered_to", "-id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("An audit review is never edited.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("An audit review is never deleted.")
