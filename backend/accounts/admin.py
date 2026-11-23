from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied

from audit.admin import AuditedAdmin
from .models import LabConfig, Role, RolePermissionGrant, User


@admin.register(User)
class QcUserAdmin(AuditedAdmin, UserAdmin):
    """
    Kept as a break-glass tool. Day-to-day user administration belongs in
    the app, where the screens guide it; changes here reach the audit trail too.
    """

    fieldsets = UserAdmin.fieldsets + (("QC Lab", {"fields": ("role", "sections")}),)
    list_display = ["username", "first_name", "last_name", "role", "is_active"]
    filter_horizontal = UserAdmin.filter_horizontal + ("sections",)

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead — names appear on signed certificates

    def get_readonly_fields(self, request, obj=None):
        # A username reissued to someone else would merge two people in the trail.
        return (*super().get_readonly_fields(request, obj), "username") if obj else ()

    def user_change_password(self, request, id, form_url=""):
        raise PermissionDenied("Set passwords in the application, where they are temporary until changed.")


@admin.register(Role)
class RoleAdmin(AuditedAdmin):
    list_display = ["name", "code", "is_system", "is_active"]

    def has_delete_permission(self, request, obj=None):
        return False  # its permission history stays on record; deactivate instead


@admin.register(RolePermissionGrant)
class GrantAdmin(admin.ModelAdmin):
    """Permission history is inspectable, never editable."""

    list_display = ["role", "permission", "granted_at", "granted_by", "revoked_at", "revoked_by"]
    list_filter = ["role", "permission"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(LabConfig, AuditedAdmin)
