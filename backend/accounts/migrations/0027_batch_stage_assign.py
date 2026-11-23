"""
Assigning batch-record stages: the Production supervisor names the person who fills a
stage of a batch and signs its first column. The administrator, who holds every
permission, gets it too. Anyone can be given it on the Roles screen.
"""
from django.db import migrations
from django.utils import timezone

KEY = "batch.stage.assign"
ROLES = ["PRODUCTION_SUPERVISOR", "ADMIN"]
REASON = "Granted with the release that added stage assignment"


def add(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for role in Role.objects.filter(code__in=ROLES):
        if not Grant.objects.filter(role=role, permission=KEY, revoked_at__isnull=True).exists():
            Grant.objects.create(role=role, permission=KEY, reason=REASON)


def remove(apps, schema_editor):
    # Revoked, not deleted: grants are history, and the database refuses to lose them.
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    Grant.objects.filter(reason=REASON, revoked_at__isnull=True).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0026_labconfig_hidden_features")]

    operations = [migrations.RunPython(add, remove)]
