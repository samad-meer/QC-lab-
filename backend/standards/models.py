"""
What makes the lab's work the same each time: a library of test templates,
and the layouts its certificates are printed in.

A test template is copied into a specification, not linked: a specification
keeps exactly what it was approved with, whatever happens to the template
later. A new version of a template is a new row.

A certificate template can change how a certificate is presented, and nothing
else. No option can leave out a test, a limit, a result, an outcome or a
signature — a document an administrator can reshape must never be one that can
be made to omit a failing test. The layout in force is frozen into each
certificate when the analyst signs, so a later edit never changes a signed one.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from lims.models import LimitType


class TestTemplate(models.Model):
    code = models.CharField(max_length=40)  # the same across all versions of one template
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=200)
    method = models.CharField(max_length=200, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    limit_type = models.CharField(max_length=20, choices=LimitType.choices)
    min_value = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    max_value = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    decimals = models.PositiveIntegerField(default=2)
    text_expected = models.CharField(max_length=200, blank=True)
    limit_text = models.CharField(max_length=200)
    # A retired template stays on record but is no longer offered.
    is_retired = models.BooleanField(default=False)
    reason = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["code", "version"], name="uniq_test_template_version"),
        ]

    def __str__(self):
        return f"{self.code} v{self.version}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("A test template is never edited — save the change as a new version.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Test templates are never deleted — retire one instead.")


class CertificateTemplate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_default = models.BooleanField(default=False)
    title = models.CharField(max_length=80, default="Certificate of Analysis")
    # Printed under the title, e.g. "For export".
    header_note = models.CharField(max_length=200, blank=True)
    # Used in place of the footer note in Settings, when given.
    footer_note = models.TextField(blank=True)
    show_method = models.BooleanField(default=True)
    show_internal_batch_id = models.BooleanField(default=True)
    show_manufacturing_site = models.BooleanField(default=True)
    show_dosage_form = models.BooleanField(default=True)
    show_analysis_dates = models.BooleanField(default=True)
    show_storage_condition = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    OPTIONS = ("show_method", "show_internal_batch_id", "show_manufacturing_site", "show_dosage_form",
               "show_analysis_dates", "show_storage_condition")

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True), name="one_default_certificate_template"
            ),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def default(cls) -> "CertificateTemplate | None":
        return cls.objects.filter(is_default=True).first()

    def layout(self) -> dict:
        """What a certificate freezes when the analyst signs."""
        return {
            "template": self.name, "title": self.title, "header_note": self.header_note,
            "footer_note": self.footer_note, **{option: getattr(self, option) for option in self.OPTIONS},
        }

    def delete(self, *args, **kwargs):
        if self.is_default:
            raise PermissionError("The default template cannot be deleted. Make another one the default first.")
        if self.products.exists():
            raise PermissionError(f"{self.products.count()} product(s) still use {self.name}.")
        super().delete(*args, **kwargs)
