from django.contrib import admin

from audit.admin import AuditedAdmin
from .models import (
    Product,
    Sample,
    SampleCounter,
    Section,
    Specification,
    TestDefinition,
    TestResult,
    WorkflowEvent,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """
    Inspectable in admin, never editable. The workflow record and its data
    move only through the application's signing path — even an administrator
    acts there, where it is recorded, and must not be able to rewrite lab
    history here, including via admin's bulk actions (which bypass Model.delete()).
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TestDefinitionInline(admin.TabularInline):
    model = TestDefinition
    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Specification)
class SpecificationAdmin(ReadOnlyAdmin):
    """Limits are approved with a signature in the application, never edited here."""

    list_display = ["product", "version", "status", "effective_date"]
    inlines = [TestDefinitionInline]


@admin.register(Sample)
class SampleAdmin(ReadOnlyAdmin):
    list_display = ["sample_no", "product", "batch_no", "status", "assigned_analyst", "due_date"]
    list_filter = ["status", "section"]
    search_fields = ["sample_no", "batch_no"]


@admin.register(WorkflowEvent)
class WorkflowEventAdmin(ReadOnlyAdmin):
    list_display = ["sample", "at", "actor", "from_status", "to_status", "comment"]


@admin.register(TestResult)
class TestResultAdmin(ReadOnlyAdmin):
    list_display = ["sample", "test_definition", "value_numeric", "value_text", "outcome", "is_superseded"]


admin.site.register(Section, AuditedAdmin)
admin.site.register(Product, AuditedAdmin)
admin.site.register(SampleCounter, AuditedAdmin)
