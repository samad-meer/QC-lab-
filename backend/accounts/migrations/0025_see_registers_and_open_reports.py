"""
Each Lab records register can be seen on its own, and each report opened on its
own. Nothing changes for anyone on the day: every role keeps seeing every register,
and a role that could open reports keeps every report it could open — the usual
ones with "Open reports", the two workload reports only with "See workload and
performance" as well, and the Audit Trail only with "View the audit trail" as
well. An administrator then takes away what a role should not have.

The keys are written out here rather than read from the registry, so this
migration does the same thing whenever it runs.
"""
from django.db import migrations
from django.utils import timezone

REGISTER_VIEWS = [
    "instrument.view", "material.view", "method.view", "qualification.view", "retained.view", "change.view",
]
# The reports "Open reports" opened by itself.
USUAL_REPORTS = [
    "sample-register", "turnaround", "test-results", "oos", "oot", "retests", "batches", "product-history",
    "certificates", "pending-work", "overdue", "document-control", "deviations",
]
# The reports that needed a second permission as well.
WITH_ALSO = {
    "analyst-workload": "report.performance",
    "bottlenecks": "report.performance",
    "audit-trail": "audit.view",
}
REASON = "Granted with the release that let each register be seen, and each report opened, on its own"


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    for role in Role.objects.all():
        held = set(Grant.objects.filter(role=role, revoked_at__isnull=True).values_list("permission", flat=True))
        keys = list(REGISTER_VIEWS)
        if "report.view" in held:
            keys += [f"report.open.{r}" for r in USUAL_REPORTS]
            keys += [f"report.open.{r}" for r, also in WITH_ALSO.items() if also in held]
        for key in keys:
            if key not in held:
                Grant.objects.create(role=role, permission=key, reason=REASON)


def ungrant(apps, schema_editor):
    # Revoked, not deleted: grants are history, and the database refuses to lose them.
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    Grant.objects.filter(reason=REASON, revoked_at__isnull=True).update(revoked_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0024_production_roles")]

    operations = [migrations.RunPython(grant, ungrant)]
