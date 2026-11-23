"""
The administrator can do every step of the lab's work. It needs a migration
because an administrator may not add to a role they hold themselves.

admin.override is what lets them act in someone's place, and is flagged on
every audit row it is used for. Each grant is recorded like any other, the
change itself goes on the audit trail, and taking admin.override away on the
Roles screen puts the separation of duties back.
"""
from django.db import migrations

KEYS = [
    "sample.register", "sample.assign", "sample.hold",
    "result.enter", "result.retest.authorize", "stage.waive",
    "cert.sign.analysed", "cert.print",
    "admin.override",
]
REASON = "The administrator can do every step of the lab's work; each use of the override is flagged"
BEFORE = "Manages users, roles, permissions, workflows and the lab's details. Signs nothing."
# What databases seeded before workflows existed still carry.
OLDER = "Manages users, roles and permissions. Holds no signing capability."
AFTER = (
    "Manages users, roles, permissions, workflows and the lab's details, and can do every step "
    "of the lab's work. Each time they act in someone's place it is flagged in the activity log."
)


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    role = Role.objects.filter(code="ADMIN").first()
    if role is None:
        return
    # Left alone if the lab has reworded it.
    Role.objects.filter(pk=role.pk, description__in=[BEFORE, OLDER]).update(description=AFTER)
    held = set(Grant.objects.filter(role=role, revoked_at__isnull=True).values_list("permission", flat=True))
    added = [key for key in KEYS if key not in held]
    for key in added:
        Grant.objects.create(role=role, permission=key, reason=REASON)
    if added:
        apps.get_model("audit", "AuditEvent").objects.create(
            action="ROLE_PERMISSIONS_CHANGED", entity="role", entity_id=role.code,
            details={"granted": added, "revoked": [], "reason": REASON},
        )


def ungrant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    apps.get_model("accounts", "RolePermissionGrant").objects.filter(role__code="ADMIN", reason=REASON).delete()
    Role.objects.filter(code="ADMIN", description=AFTER).update(description=BEFORE)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_grant_sample_comment"),
        ("audit", "0002_auditevent_ip_address_alter_auditevent_entity_id"),
    ]

    operations = [migrations.RunPython(grant, ungrant)]
