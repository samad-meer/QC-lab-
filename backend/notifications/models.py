from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    """
    A message to one person: work assigned or handed to them, an answer to
    something they sent, work returned to them. Kept, never deleted — the
    only thing that ever changes is when it was read.
    """

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notifications")
    kind = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=1000, blank=True)
    # Where in the app it leads, e.g. /samples/12/review.
    link = models.CharField(max_length=200, blank=True)
    sample = models.ForeignKey("lims.Sample", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at"], name="notif_recipient_read")]

    def __str__(self):
        return f"{self.recipient} · {self.title}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = Notification.objects.get(pk=self.pk)
            changed = {
                f.name for f in self._meta.concrete_fields
                if getattr(old, f.attname) != getattr(self, f.attname)
            }
            if changed - {"read_at"} or old.read_at is not None:
                raise PermissionError("A notification is never changed — only marked read, once.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Notifications are kept.")


class NotificationRule(models.Model):
    """
    How one event behaves (see rules.EVENTS for the events). Changed on the
    Notification rules screen; every change is on the audit trail.
    """

    event = models.CharField(max_length=30, unique=True)
    enabled = models.BooleanField(default=True)
    # Also told, beyond the people the event always reaches.
    roles = models.ManyToManyField("accounts.Role", blank=True, related_name="+")
    # How long before the due date the warning goes out.
    days_before = models.PositiveSmallIntegerField(default=1)
    # Remind again every so many days. 0 means once.
    repeat_days = models.PositiveSmallIntegerField(default=0)
    # Also sent by email, once a mail server is set up.
    email = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)


class AlertSweep(models.Model):
    """One row: when due dates were last swept for alerts."""

    last_run = models.DateTimeField()


class EmailOutbox(models.Model):
    """
    One email waiting to go. A notification is written inside the action that
    caused it, so sending there would make a signature wait on a mail server,
    and could announce an action that then rolls back. Queued here instead, it
    commits with the action and goes out afterwards, with retries.
    """

    notification = models.OneToOneField(Notification, on_delete=models.PROTECT, related_name="+")
    to = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)
    next_try = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveSmallIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)

    class Meta:
        indexes = [models.Index(fields=["sent_at", "next_try"], name="email_waiting")]
