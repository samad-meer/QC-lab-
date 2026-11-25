"""
Three reports about who holds what: Tasks by Person, Team Tasks and Person Activity.

Everyone may open and print their own Person Activity, so every active role is given
"Open reports" with that one report, and nothing else: each report is a permission of its
own, so a role that could open no report before still opens no other. The two team reports
go to the roles that could already see workload ("See workload on the overview" with
"Open reports"), and choosing another person in Person Activity is that same permission.
An administrator then takes away what a role should not have, on the Roles screen.

The keys are written out here rather than read from the registry, so this migration does
the same thing whenever it runs.
"""
from django.db import migrations
from django.utils import timezone

REASON = "Granted with the release that added the team task reports"
TEAM_REPORTS = ["tasks-by-person", "team-tasks"]
OWN_REPORT = "person-activity"


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for role in Role.objects.all():
        held = set(Grant.objects.filter(role=role, revoked_at__isnull=True).values_list("permission", flat=True))
        if not role.is_active:
            continue
        keys = ["report.view", f"report.open.{OWN_REPORT}"]
        if "report.view" in held and "report.performance" in held:
            keys += [f"report.open.{r}" for r in TEAM_REPORTS]
        for key in keys:
            if key not in held:
                Grant.objects.create(role=role, permission=key, reason=REASON)


def ungrant(apps, schema_editor):
    # Revoked, not deleted: grants are history, and the database refuses to lose them.
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    Grant.objects.filter(reason=REASON, revoked_at__isnull=True).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0027_batch_stage_assign")]

    operations = [migrations.RunPython(grant, ungrant)]
