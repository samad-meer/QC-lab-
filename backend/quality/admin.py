from django.contrib import admin

from lims.admin import ReadOnlyAdmin
from .models import CapaAction, Investigation, InvestigationEvent


@admin.register(Investigation)
class InvestigationAdmin(ReadOnlyAdmin):
    list_display = ["reference", "kind", "status", "sample", "responsible", "due_date"]
    list_filter = ["kind", "status"]
    search_fields = ["reference", "batch_no"]


@admin.register(CapaAction)
class CapaActionAdmin(ReadOnlyAdmin):
    list_display = ["investigation", "kind", "owner", "due_date", "completed_at"]


@admin.register(InvestigationEvent)
class InvestigationEventAdmin(ReadOnlyAdmin):
    list_display = ["investigation", "at", "actor", "what"]
