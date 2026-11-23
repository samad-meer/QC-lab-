"""
Review signatures move from permissions to workflow stages.

- The signature titles leave LabConfig: each stage carries its own now, and
  lims 0005 copied the lab's titles onto the default workflow's stages.
- cert.sign.checked / cert.sendback / cert.sign.approved / cert.reject are
  retired. Each review stage names the role that signs it (and may send
  the work back), so these grants no longer mean anything. They are
  revoked — never deleted — so "who could approve on 3 March?" still has
  its answer.
- workflow.manage is new; like config.manage in 0007, it goes to the roles
  that already administer the system.
"""
from django.db import migrations
from django.utils import timezone

RETIRED = ["cert.sign.checked", "cert.sendback", "cert.sign.approved", "cert.reject"]
RETIRED_REASON = "Retired: review signatures are now assigned per workflow stage"
NEW_REASON = "Granted with the release that introduced review workflows"


def forward(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")

    Grant.objects.filter(permission__in=RETIRED, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), reason=RETIRED_REASON
    )

    admin_roles = Role.objects.filter(
        grants__permission="role.manage", grants__revoked_at__isnull=True
    ).distinct()
    for role in admin_roles:
        if not Grant.objects.filter(role=role, permission="workflow.manage", revoked_at__isnull=True).exists():
            Grant.objects.create(role=role, permission="workflow.manage", reason=NEW_REASON)


def reverse(apps, schema_editor):
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    Grant.objects.filter(permission="workflow.manage", reason=NEW_REASON).delete()
    for grant in Grant.objects.filter(permission__in=RETIRED, reason=RETIRED_REASON):
        Grant.objects.create(role_id=grant.role_id, permission=grant.permission,
                             reason="Restored by reversing the workflows migration")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_grant_config_manage"),
        # The default workflow reads the titles before they are removed.
        ("lims", "0005_default_workflow"),
    ]

    operations = [
        migrations.RemoveField(model_name="labconfig", name="approved_by_title"),
        migrations.RemoveField(model_name="labconfig", name="checked_by_title"),
        migrations.RunPython(forward, reverse),
    ]
