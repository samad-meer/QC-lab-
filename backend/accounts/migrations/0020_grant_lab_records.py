"""
The lab records and batch disposition go to the lab head, and to the administrator,
who holds every permission. Whoever does the work gets the part that is theirs, as
with specifications: the checker drafts, and someone else approves. Anyone can be
moved on the Roles screen.
"""
from django.db import migrations
from django.utils import timezone

GRANTS = {
    "FRONT_DESK": ["custody.record"],
    "ANALYST": ["custody.record"],
    "CHECKER": ["custody.record", "instrument.manage", "material.manage", "method.manage", "change.manage"],
    "APPROVER": [
        "batch.disposition", "instrument.manage", "material.manage", "method.manage", "method.approve",
        "qualification.manage", "custody.record", "custody.destroy", "change.manage", "change.approve",
    ],
    "ADMIN": [
        "batch.disposition", "instrument.manage", "material.manage", "method.manage", "method.approve",
        "qualification.manage", "custody.record", "custody.destroy", "change.manage", "change.approve",
    ],
}
REASON = "Granted with the release that added the lab records and batch disposition"


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
    dependencies = [("accounts", "0019_grant_audit_view_to_lab_head")]

    operations = [migrations.RunPython(grant, ungrant)]
