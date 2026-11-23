"""
Give existing administrator roles the new `config.manage` permission.

A new permission key ships with a release, so no role holds it yet. Rather
than guess, grant it to whoever already administers the system — the roles
that can manage users — and record the grant like any other so the history
stays complete.
"""
from django.db import migrations


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")

    admin_roles = Role.objects.filter(
        grants__permission="user.manage", grants__revoked_at__isnull=True
    ).distinct()
    for role in admin_roles:
        if not Grant.objects.filter(
            role=role, permission="config.manage", revoked_at__isnull=True
        ).exists():
            Grant.objects.create(
                role=role,
                permission="config.manage",
                reason="Granted with the release that introduced lab details",
            )


def ungrant(apps, schema_editor):
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    Grant.objects.filter(permission="config.manage").delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_labconfig_address_labconfig_company_name_and_more")]

    operations = [migrations.RunPython(grant, ungrant)]
