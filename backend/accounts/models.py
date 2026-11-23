from uuid import uuid4

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .permissions_registry import ALL_PERMISSIONS, conflicts_in, effective
from .photos import logo_upload_path, photo_upload_path


class Role(models.Model):
    """
    A role is data, not an enum — an administrator can create new ones and
    change what each may do. What a role CANNOT do is defeat the rules that
    make the system safe: every signature on one certificate must still
    come from a different person, a signed certificate is still frozen,
    and nothing is ever deleted. Those live in code and are not permissions.
    """

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    # System roles ship with the product and cannot be deleted (users depend
    # on them); their permissions are still fully editable.
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def permissions(self) -> set[str]:
        """Currently held permission keys (grants that have not been revoked)."""
        return set(
            self.grants.filter(revoked_at__isnull=True).values_list("permission", flat=True)
        )

    def conflicts(self) -> list[dict]:
        from lims.workflow import stage_conflicts

        return conflicts_in(self.permissions()) + stage_conflicts(self)

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise PermissionError("A system role cannot be deleted. Deactivate it instead.")
        if self.users.exists():
            raise PermissionError(
                f"{self.name} is still assigned to {self.users.count()} user(s). "
                "Move them to another role first."
            )
        if self.grants.exists():
            raise PermissionError(
                f"{self.name} has a permission history, which stays on record. Deactivate the role instead."
            )
        super().delete(*args, **kwargs)


class RolePermissionGrant(models.Model):
    """
    One grant of one permission to one role, append-only and temporal.

    A revoke sets revoked_at rather than deleting the row, so the question
    "who could approve a certificate on 3 March?" is a query, not a guess.
    Nothing here is ever edited except the single revoke transition.
    """

    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="grants")
    permission = models.CharField(max_length=60)
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=500, blank=True)

    REVOKE_FIELDS = {"revoked_at", "revoked_by", "reason"}

    class Meta:
        ordering = ["-granted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission"],
                condition=models.Q(revoked_at__isnull=True),
                name="uniq_active_grant",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            old = RolePermissionGrant.objects.get(pk=self.pk)
            changed = {
                f.name
                for f in self._meta.concrete_fields
                if getattr(old, f.attname) != getattr(self, f.attname)
            }
            if changed - self.REVOKE_FIELDS:
                raise PermissionError("A permission grant is never edited — revoke and re-grant.")
            if old.revoked_at is not None:
                raise PermissionError("A revoked grant can never change again.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Permission history is never deleted.")

    def revoke(self, by, reason: str = ""):
        self.revoked_at = timezone.now()
        self.revoked_by = by
        self.reason = reason
        self.save()

    @property
    def label(self) -> str:
        return ALL_PERMISSIONS.get(self.permission, self.permission)


class User(AbstractUser):
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    # For analysts: the sections they are trained for. The front desk is
    # only offered analysts trained in the chosen section.
    sections = models.ManyToManyField("lims.Section", blank=True, related_name="users")

    # --- Employment record. Set by an administrator only. ---------------
    employee_id = models.CharField(max_length=30, unique=True, null=True, blank=True)
    designation = models.CharField(max_length=80, blank=True)
    # NOTE: distinct from AbstractUser.date_joined, which is when the ACCOUNT
    # was created. joining_date is when the person joined the company.
    joining_date = models.DateField(null=True, blank=True)

    # --- The user's own to change. --------------------------------------
    phone = models.CharField(max_length=30, blank=True)
    # For recognising a colleague on screen. Never appears on a certificate —
    # an electronic signature is not a picture.
    photo = models.ImageField(upload_to=photo_upload_path, null=True, blank=True)

    # --- Sign-in protection (accounts/passwords.py). -----------------------
    failed_logins = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    # Set while the password is one an administrator chose.
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    # Fields an administrator owns; a user may never set these on themselves.
    ADMIN_ONLY_FIELDS = ("employee_id", "designation", "joining_date")
    SELF_EDITABLE_FIELDS = ("phone",)

    def display_name(self) -> str:
        return self.get_full_name() or self.username

    def replace_photo(self, new_file):
        """
        Swap the stored image, discarding the previous file.

        Deleting the old image is not a Rule Two exception: a photo is not a
        lab record, carries no result and appears on no certificate. The
        *change* is written to the audit trail even though the image is not.
        """
        old = self.photo.name if self.photo else None
        self.photo.save(f"{uuid4().hex}.jpg", new_file, save=True)
        if old and old != self.photo.name:
            self.photo.storage.delete(old)

    def clear_photo(self):
        old = self.photo.name if self.photo else None
        self.photo = None
        self.save(update_fields=["photo"])
        if old:
            self.photo.storage.delete(old)

    def has_working_role(self) -> bool:
        return self.role_id is not None and self.role.is_active

    def may_sign_in(self) -> bool:
        """Who is allowed in at all. A lockout is separate, and ends by itself."""
        return self.is_active and self.has_working_role()

    def granted_permissions(self) -> set[str]:
        """What their role gives them: its grants, and what comes with them (seeing a register they
        manage), whether or not the lab shows it now. The Roles screen edits the grants themselves."""
        return effective(self.role.permissions()) if self.may_sign_in() else set()

    def permissions(self) -> set[str]:
        """What this person may do now: what their role gives them, less anything the lab has
        hidden for everyone (Settings → Features shown)."""
        held = self.granted_permissions()
        return held - LabConfig.hidden() if held else held

    def has_perm_key(self, key: str) -> bool:
        return key in self.permissions()

    def delete(self, *args, **kwargs):
        raise PermissionError(
            "Users are never deleted — their name appears on signed certificates. "
            "Deactivate the account instead."
        )


class PasswordHistory(models.Model):
    """Earlier passwords, as hashes, so one is not simply reused."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="password_history")
    password = models.CharField(max_length=128)
    changed_at = models.DateTimeField(auto_now_add=True)


class LabConfig(models.Model):
    """
    Single-row lab configuration: what this lab is called.

    Deliberately NOT a certificate template. The identity block below is
    presentation — a letterhead. Which tests, limits and results appear on a
    certificate is fixed, because a document an administrator can reshape is
    a document that can be made to omit a failing test. What each signature
    is called now belongs to its workflow stage (lims.WorkflowStage).
    """

    lab_name = models.CharField(max_length=200, default="Quality Control Laboratory")
    # The line under the system name in the top bar and on the sign-in page.
    app_tagline = models.CharField(max_length=80, blank=True, default="Certificate of Analysis")
    # Where "today" begins, and how every date and time is shown and printed.
    # Times are stored in UTC, so changing it moves no recorded moment.
    time_zone = models.CharField(max_length=64, default="Asia/Karachi")
    # How a time of day is written on screens, reports and certificates:
    # 02:05:12 PM, or 14:05:12. What is stored is the same either way.
    time_format = models.CharField(
        max_length=3, choices=[("12h", "12-hour, 02:05 PM"), ("24h", "24-hour, 14:05")], default="12h"
    )

    # --- Letterhead: what appears at the top of every certificate --------
    company_name = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    licence_no = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=60, blank=True)
    email = models.EmailField(blank=True)
    website = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(upload_to=logo_upload_path, null=True, blank=True)
    # Printed small at the foot of the certificate, above the QR code.
    footer_note = models.TextField(blank=True)

    # --- After a failed result: the quality unit's rules ------------------
    # A failure needs an investigation: its laboratory finding before any
    # retest, and its closure before any certificate.
    oos_investigation_required = models.BooleanField(default=True)
    # How many retests a test may have on one sample.
    oos_max_retests = models.PositiveSmallIntegerField(default=2)
    # A retest is done by someone other than whoever produced the first failure.
    oos_second_analyst = models.BooleanField(default=True)
    # A failure on one sample stops certificates for every sample of its batch.
    oos_batch_block = models.BooleanField(default=True)

    # --- What the lab shows -------------------------------------------------
    # Parts of the app switched off for everyone until they are needed: the keys of
    # permissions_registry.HIDEABLE. Nothing hidden is deleted or changed.
    hidden_features = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Lab configuration"

    def replace_logo(self, new_file):
        # The old file stays: certificates signed with it still print it.
        self.logo.save(f"{uuid4().hex}.png", new_file, save=True)

    def clear_logo(self):
        self.logo = None
        self.save(update_fields=["logo"])

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "LabConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def hidden(cls) -> set[str]:
        """The permissions nobody holds while the lab hides what they open."""
        listed = cls.objects.filter(pk=1).values_list("hidden_features", flat=True).first()
        return set(listed or [])
