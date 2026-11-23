"""
Cancelling a sample and withdrawing a certificate go to the lab head, and to the
administrator, who holds every permission. Either can be moved on the Roles screen.
"""
from django.db import migrations

KEYS = ["sample.cancel", "cert.withdraw"]


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for code in ("APPROVER", "ADMIN"):
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for key in KEYS:
            if not Grant.objects.filter(role=role, permission=key, revoked_at__isnull=True).exists():
                Grant.objects.create(
                    role=role, permission=key,
                    reason="Granted with the release that added rejected and cancelled samples and withdrawn certificates",
                )


def ungrant(apps, schema_editor):
    apps.get_model("accounts", "RolePermissionGrant").objects.filter(permission__in=KEYS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_labconfig_oos_rules")]

    operations = [migrations.RunPython(grant, ungrant)]
