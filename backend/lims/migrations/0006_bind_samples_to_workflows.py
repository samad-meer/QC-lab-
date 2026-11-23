"""
Every sample is now bound to a workflow version (0005 bound the existing
ones), so the binding becomes required.

PostgreSQL only (no-op on SQLite), extending 0002's guard:
- a sample's workflow version is fixed at registration, like its
  specification — direct SQL cannot re-route it to different signatures;
- workflow versions and their stages are never updated. A change is a new
  version, so what a past sample was required to carry stays answerable.
"""
from django.db import migrations, models
import django.db.models.deletion

FORWARD = """
CREATE OR REPLACE FUNCTION qclab_sample_update_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.sample_no IS DISTINCT FROM OLD.sample_no
       OR NEW.specification_id IS DISTINCT FROM OLD.specification_id
       OR NEW.workflow_version_id IS DISTINCT FROM OLD.workflow_version_id
       OR NEW.product_id IS DISTINCT FROM OLD.product_id
       OR NEW.batch_no IS DISTINCT FROM OLD.batch_no
       OR NEW.received_at IS DISTINCT FROM OLD.received_at
       OR NEW.registered_by_id IS DISTINCT FROM OLD.registered_by_id THEN
        RAISE EXCEPTION 'qclab: sample identity, its specification and its workflow are fixed at registration';
    END IF;
    IF OLD.status = 'APPROVED' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'qclab: an approved sample can never be reopened (Rule One)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER qclab_wfversion_lock BEFORE UPDATE ON lims_workflowversion
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_wfstage_lock BEFORE UPDATE ON lims_workflowstage
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
"""

REVERSE = """
DROP TRIGGER IF EXISTS qclab_wfversion_lock ON lims_workflowversion;
DROP TRIGGER IF EXISTS qclab_wfstage_lock ON lims_workflowstage;
CREATE OR REPLACE FUNCTION qclab_sample_update_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.sample_no IS DISTINCT FROM OLD.sample_no
       OR NEW.specification_id IS DISTINCT FROM OLD.specification_id
       OR NEW.product_id IS DISTINCT FROM OLD.product_id
       OR NEW.batch_no IS DISTINCT FROM OLD.batch_no
       OR NEW.received_at IS DISTINCT FROM OLD.received_at
       OR NEW.registered_by_id IS DISTINCT FROM OLD.registered_by_id THEN
        RAISE EXCEPTION 'qclab: sample identity and its bound specification are fixed at registration';
    END IF;
    IF OLD.status = 'APPROVED' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'qclab: an approved sample can never be reopened (Rule One)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("lims", "0005_default_workflow")]

    operations = [
        migrations.AlterField(
            model_name="sample",
            name="workflow_version",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="samples",
                to="lims.workflowversion",
            ),
        ),
        migrations.RunPython(forward, reverse),
    ]
