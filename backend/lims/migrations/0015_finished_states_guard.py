"""A rejected or cancelled sample is as final as an approved one."""
from django.db import migrations

BODY = """
CREATE OR REPLACE FUNCTION qclab_sample_update_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.sample_no IS DISTINCT FROM OLD.sample_no
       OR NEW.specification_id IS DISTINCT FROM OLD.specification_id
       OR NEW.workflow_version_id IS DISTINCT FROM OLD.workflow_version_id
       OR NEW.product_id IS DISTINCT FROM OLD.product_id
       OR NEW.received_at IS DISTINCT FROM OLD.received_at
       OR NEW.registered_by_id IS DISTINCT FROM OLD.registered_by_id THEN
        RAISE EXCEPTION 'qclab: sample identity, its specification and its workflow are fixed at registration';
    END IF;
    IF OLD.status NOT IN ('RECEIVED', 'IN_TESTING')
       AND (NEW.batch_no IS DISTINCT FROM OLD.batch_no OR NEW.batch_id IS DISTINCT FROM OLD.batch_id) THEN
        RAISE EXCEPTION 'qclab: the batch on a signed sample never changes';
    END IF;
    IF OLD.status IN ({finished}) AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'qclab: a finished sample can never be reopened (Rule One)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(BODY.format(finished="'APPROVED', 'REJECTED', 'CANCELLED'"), params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(BODY.format(finished="'APPROVED'"), params=None)


class Migration(migrations.Migration):
    dependencies = [("lims", "0014_sample_closing")]

    operations = [migrations.RunPython(forward, reverse)]
