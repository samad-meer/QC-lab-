from django.contrib import admin

from .models import AuditEvent
from .services import record


class AuditedAdmin(admin.ModelAdmin):
    """
    For the screens of this site that can change data. Django keeps its own
    log of them, which nobody reviews; without this they would be the one way
    to change the lab's users and specifications that the audit trail misses.
    """

    def _audit(self, request, action, obj, **details):
        record(request.user, action, self.opts.model_name, obj.pk,
               model=str(self.opts.verbose_name), name=str(obj), **details)

    def log_addition(self, request, obj, message):
        entry = super().log_addition(request, obj, message)
        self._audit(request, "ADMIN_SITE_ADDED", obj)
        return entry

    def log_change(self, request, obj, message):
        entry = super().log_change(request, obj, message)
        self._audit(request, "ADMIN_SITE_CHANGED", obj, change=entry.get_change_message())
        return entry

    def log_deletions(self, request, queryset):
        for obj in queryset:
            self._audit(request, "ADMIN_SITE_DELETED", obj)
        return super().log_deletions(request, queryset)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only in admin: the trail can be inspected, never edited."""

    list_display = ["at", "actor_username", "action", "entity", "entity_id"]
    list_filter = ["action"]
    search_fields = ["actor_username", "entity_id"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
