from django.contrib import admin

from lims.admin import ReadOnlyAdmin
from .models import CalibrationEvent, ChangeRecord, CustodyEvent, Instrument, Material, Method, Qualification


@admin.register(Instrument)
class InstrumentAdmin(ReadOnlyAdmin):
    list_display = ["code", "name", "type", "location", "status"]


@admin.register(CalibrationEvent)
class CalibrationEventAdmin(ReadOnlyAdmin):
    list_display = ["instrument", "kind", "outcome", "performed_at", "next_due"]


@admin.register(Material)
class MaterialAdmin(ReadOnlyAdmin):
    list_display = ["code", "name", "lot", "kind", "expiry_date", "status"]


@admin.register(Method)
class MethodAdmin(ReadOnlyAdmin):
    list_display = ["code", "version", "title", "validation_status", "status"]


@admin.register(Qualification)
class QualificationAdmin(ReadOnlyAdmin):
    list_display = ["user", "method", "qualified_on", "expires_on", "revoked_at"]


@admin.register(CustodyEvent)
class CustodyEventAdmin(ReadOnlyAdmin):
    list_display = ["sample", "action", "location", "at", "by"]


@admin.register(ChangeRecord)
class ChangeRecordAdmin(ReadOnlyAdmin):
    list_display = ["reference", "title", "category", "status", "raised_by"]
