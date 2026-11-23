"""
A batch number can be corrected on a sample until its certificate is signed.

The sample guard refused any change to batch_no, which made a correction on a
batch with open samples fail on PostgreSQL. Once signed the number is fixed, and
the batch link is held to the same rule.
"""
from django.db import migrations

FORWARD = """
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
    IF OLD.status = 'APPROVED' AND NEW.status IS DISTINCT FROM OLD.status THEN
        RAISE EXCEPTION 'qclab: an approved sample can never be reopened (Rule One)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

REVERSE = """
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
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD, params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE, params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("lims", "0011_standards"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
