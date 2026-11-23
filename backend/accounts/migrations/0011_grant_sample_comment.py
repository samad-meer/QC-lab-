"""
Commenting becomes a permission of its own. Until now everyone who could
see a sample could comment on it, so every existing role keeps that ability
— nothing changes on the day this is installed. An administrator takes it
away from a read-only role on the Roles screen.
"""
from django.db import migrations

KEY = "sample.comment"


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for role in Role.objects.all():
        if not Grant.objects.filter(role=role, permission=KEY, revoked_at__isnull=True).exists():
            Grant.objects.create(
                role=role, permission=KEY,
                reason="Every role could already comment; granted when it became a separate permission",
            )


def ungrant(apps, schema_editor):
    apps.get_model("accounts", "RolePermissionGrant").objects.filter(permission=KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_grant_execution_permissions")]

    operations = [migrations.RunPython(grant, ungrant)]
