"""
Database-level guard on sample status — PostgreSQL only (no-op on SQLite).

An approved sample must never be walked backwards into testing by direct
SQL or the Django admin: doing so would let a second certificate version be
built and approved while the first stays APPROVED, leaving two "genuine and
current" certificates for one batch.
"""
from django.db import migrations

FORWARD = """
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

CREATE TRIGGER qclab_sample_update_lock BEFORE UPDATE ON lims_sample
    FOR EACH ROW EXECUTE FUNCTION qclab_sample_update_guard();
CREATE TRIGGER qclab_sample_delete_lock BEFORE DELETE ON lims_sample
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
"""

REVERSE = """
DROP TRIGGER IF EXISTS qclab_sample_update_lock ON lims_sample;
DROP TRIGGER IF EXISTS qclab_sample_delete_lock ON lims_sample;
DROP FUNCTION IF EXISTS qclab_sample_update_guard();
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [
        ("lims", "0001_initial"),
        # qclab_forbid() is created there.
        ("certificates", "0002_pg_lockdown"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
