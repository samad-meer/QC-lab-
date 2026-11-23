"""
Give the shipped roles the lab-execution permissions this release adds.

New keys ship with a release, so no role holds them yet. The defaults
follow who already does the work: the front desk assigns analysts, the
checker can stop work, and the lab head assigns, stops, authorizes retests
and waives requirements. Each grant is recorded like any other, and an
administrator can move any of them on the Roles screen.
"""
from django.db import migrations

DEFAULTS = {
    "FRONT_DESK": ["sample.assign"],
    "CHECKER": ["sample.hold"],
    "APPROVER": ["sample.assign", "sample.hold", "result.retest.authorize", "stage.waive"],
}
KEYS = sorted({k for keys in DEFAULTS.values() for k in keys})


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for code, keys in DEFAULTS.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for key in keys:
            if not Grant.objects.filter(role=role, permission=key, revoked_at__isnull=True).exists():
                Grant.objects.create(
                    role=role, permission=key,
                    reason="Granted with the release that introduced stage requirements and handovers",
                )


def ungrant(apps, schema_editor):
    apps.get_model("accounts", "RolePermissionGrant").objects.filter(permission__in=KEYS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0009_labconfig_app_tagline")]

    operations = [migrations.RunPython(grant, ungrant)]
