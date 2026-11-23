"""
Production signs in: the Production operator and Production supervisor roles, and
two permissions, to see every batch and to fill batch records. The administrator,
who holds every permission, gets both. Anyone can be moved on the Roles screen.
"""
from django.db import migrations
from django.utils import timezone

ROLES = {
    "PRODUCTION_OPERATOR": (
        "Production operator",
        "Fills the batch record on the shop floor and signs a stage's “Done by” column.",
        ["batch.view.all", "batch.record.fill"],
    ),
    "PRODUCTION_SUPERVISOR": (
        "Production supervisor",
        "Checks the operator's entries and signs a stage's “Checked by (Production)” column; can open batches.",
        ["batch.view.all", "batch.record.fill", "batch.manage"],
    ),
}
ADMIN_KEYS = ["batch.view.all", "batch.record.fill"]
REASON = "Granted with the release that added batch records"


def add(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")

    def give(role, keys):
        for key in keys:
            if not Grant.objects.filter(role=role, permission=key, revoked_at__isnull=True).exists():
                Grant.objects.create(role=role, permission=key, reason=REASON)

    for code, (name, description, keys) in ROLES.items():
        role, _ = Role.objects.get_or_create(
            code=code, defaults={"name": name, "description": description, "is_system": True, "is_active": True},
        )
        give(role, keys)
    admin = Role.objects.filter(code="ADMIN").first()
    if admin is not None:
        give(admin, ADMIN_KEYS)


def remove(apps, schema_editor):
    # Revoked, not deleted: grants are history, and the database refuses to lose them.
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    Grant.objects.filter(reason=REASON, revoked_at__isnull=True).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0023_labconfig_time_format")]

    operations = [migrations.RunPython(add, remove)]
