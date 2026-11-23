"""
Recording a batch's QA stages, such as a line clearance, goes to the lab head, the
QA officer where the lab has one, and the administrator, who holds every
permission. Anyone can be moved on the Roles screen.
"""
from django.db import migrations
from django.utils import timezone

GRANTS = {
    "APPROVER": ["batch.stage.record"],
    "QA_OFFICER": ["batch.stage.record"],
    "ADMIN": ["batch.stage.record"],
}
REASON = "Granted with the release that added QC stages to batches"


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for code, keys in GRANTS.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for key in keys:
            if not Grant.objects.filter(role=role, permission=key, revoked_at__isnull=True).exists():
                Grant.objects.create(role=role, permission=key, reason=REASON)


def ungrant(apps, schema_editor):
    # Revoked, not deleted: grants are history, and the database refuses to lose them.
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for code, keys in GRANTS.items():
        Grant.objects.filter(
            role__code=code, permission__in=keys, reason=REASON, revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0020_grant_lab_records")]

    operations = [migrations.RunPython(grant, ungrant)]
