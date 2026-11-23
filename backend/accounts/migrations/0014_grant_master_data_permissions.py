"""
Give the shipped roles the permissions that come with the product master,
batches, specifications, templates and notification rules. The defaults follow
who already does the work: the front desk keeps batches, the checker drafts
specifications and the lab head makes them effective. The administrator holds
every permission. Any of these can be moved on the Roles screen.
"""
from django.db import migrations

DEFAULTS = {
    "FRONT_DESK": ["batch.manage"],
    "CHECKER": ["spec.manage"],
    "APPROVER": ["batch.manage", "spec.approve"],
    "ADMIN": ["batch.manage", "product.manage", "spec.manage", "spec.approve", "template.manage",
              "notification.manage"],
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
                    reason="Granted with the release that introduced batches and the product master",
                )


def ungrant(apps, schema_editor):
    apps.get_model("accounts", "RolePermissionGrant").objects.filter(permission__in=KEYS).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0013_grant_reports_and_investigations")]

    operations = [migrations.RunPython(grant, ungrant)]
