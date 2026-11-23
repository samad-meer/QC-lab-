"""
The lab head reads the activity log too. If only the administrator could, the
person holding the override would be the only one reviewing their own overrides.
"""
from django.db import migrations

KEY = "audit.view"


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    role = Role.objects.filter(code="APPROVER").first()
    if role is not None and not Grant.objects.filter(role=role, permission=KEY, revoked_at__isnull=True).exists():
        Grant.objects.create(role=role, permission=KEY, reason="So that someone other than the administrator reviews the trail")


def ungrant(apps, schema_editor):
    apps.get_model("accounts", "RolePermissionGrant").objects.filter(role__code="APPROVER", permission=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0018_grant_history_is_kept")]

    operations = [migrations.RunPython(grant, ungrant)]
