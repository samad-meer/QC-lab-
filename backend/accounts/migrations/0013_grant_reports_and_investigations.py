"""
Give the shipped roles the reporting and investigation permissions this
release adds.

New keys ship with a release, so no role holds them yet. Everyone may open
reports, which show them only the samples they can already see. The people
who supervise and review also export and see workload; the checker works on
investigations, and the lab head also approves their closure. The
administrator holds every key, which needs a migration because an
administrator may not add to a role they hold themselves. Each grant is
recorded like any other, and any of them can be moved on the Roles screen.
"""
from django.db import migrations

EVERY_KEY = [
    "report.view", "report.export", "report.performance", "investigation.manage", "investigation.approve",
]
DEFAULTS = {
    "FRONT_DESK": ["report.view"],
    "ANALYST": ["report.view"],
    "CHECKER": ["report.view", "report.export", "report.performance", "investigation.manage"],
    "APPROVER": EVERY_KEY,
    "ADMIN": EVERY_KEY,
}
REASON = "Granted with the release that introduced the Reports module and investigations"


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for code, keys in DEFAULTS.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        held = set(Grant.objects.filter(role=role, revoked_at__isnull=True).values_list("permission", flat=True))
        for key in keys:
            if key not in held:
                Grant.objects.create(role=role, permission=key, reason=REASON)


def ungrant(apps, schema_editor):
    apps.get_model("accounts", "RolePermissionGrant").objects.filter(permission__in=EVERY_KEY).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_administrator_does_everything")]

    operations = [migrations.RunPython(grant, ungrant)]
