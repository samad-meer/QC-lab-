"""
Turn the fixed three-signature chain into the default review workflow.

Nothing changes for work already in the lab: the default workflow's stages
are exactly the old chain — "Checked by" then "Approved by", signed by the
roles that held those permissions, titled as the lab had titled them — and
every existing sample is bound to it. Samples that were waiting for a check
or an approval are waiting at the same stage now.

The stage codes are the old signature meanings (CHECKED, APPROVED), so the
signatures already on existing certificates line up with their stages.
"""
from django.db import migrations

CHECKED, APPROVED = "CHECKED", "APPROVED"


def _signer(Role, permission, preferred_code):
    holders = Role.objects.filter(
        grants__permission=permission, grants__revoked_at__isnull=True
    ).distinct()
    return (
        holders.filter(code=preferred_code).first()
        or holders.order_by("id").first()
        or Role.objects.filter(code=preferred_code).first()
    )


def forward(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    LabConfig = apps.get_model("accounts", "LabConfig")
    Workflow = apps.get_model("lims", "Workflow")
    WorkflowVersion = apps.get_model("lims", "WorkflowVersion")
    WorkflowStage = apps.get_model("lims", "WorkflowStage")
    Sample = apps.get_model("lims", "Sample")

    checker = _signer(Role, "cert.sign.checked", "CHECKER")
    approver = _signer(Role, "cert.sign.approved", "APPROVER")
    if checker is None or approver is None:
        if Sample.objects.exists():
            raise RuntimeError(
                "Cannot build the default review workflow: no role signs as Checked or Approved."
            )
        return

    cfg = LabConfig.objects.filter(pk=1).first()
    workflow = Workflow.objects.create(
        name="Standard review",
        description="Checked, then approved — the original three-signature chain.",
        is_default=True,
    )
    v1 = WorkflowVersion.objects.create(
        workflow=workflow, version=1,
        reason="Created from the fixed three-signature chain when review workflows were introduced",
    )
    checked = WorkflowStage.objects.create(
        version=v1, order=1, code=CHECKED, name="Checked", signature_title="Checked by",
        holder_title=cfg.checked_by_title if cfg else "AM / DM", role=checker,
    )
    approved = WorkflowStage.objects.create(
        version=v1, order=2, code=APPROVED, name="Approved", signature_title="Approved by",
        holder_title=cfg.approved_by_title if cfg else "QCM / HOD", role=approver,
    )

    Sample.objects.update(workflow_version=v1)
    Sample.objects.filter(status="AWAITING_CHECK").update(status="IN_REVIEW", review_stage=checked)
    Sample.objects.filter(status="AWAITING_APPROVAL").update(status="IN_REVIEW", review_stage=approved)


def reverse(apps, schema_editor):
    Sample = apps.get_model("lims", "Sample")
    Workflow = apps.get_model("lims", "Workflow")
    Sample.objects.filter(status="IN_REVIEW", review_stage__order=1).update(status="AWAITING_CHECK")
    Sample.objects.filter(status="IN_REVIEW").exclude(review_stage__order=1).update(status="AWAITING_APPROVAL")
    Sample.objects.update(workflow_version=None, review_stage=None)
    apps.get_model("lims", "Product").objects.update(workflow=None)
    Workflow.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("lims", "0004_workflows"),
        ("accounts", "0007_grant_config_manage"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
