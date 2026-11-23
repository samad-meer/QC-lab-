from django.contrib import admin

from .models import Certificate, PrintEvent, Signature


class ReadOnlyAdmin(admin.ModelAdmin):
    """Signed records can be inspected in admin, never edited or deleted."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Certificate)
class CertificateAdmin(ReadOnlyAdmin):
    list_display = ["__str__", "status", "content_hash", "created_at"]


@admin.register(Signature)
class SignatureAdmin(ReadOnlyAdmin):
    list_display = ["certificate", "meaning", "name_snapshot", "signed_at"]


@admin.register(PrintEvent)
class PrintEventAdmin(ReadOnlyAdmin):
    list_display = ["certificate", "copy_number", "printed_by", "printed_at"]
