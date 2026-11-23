"""
A sample is registered for one QC stage of its batch. On PostgreSQL that choice
is fixed once made, like its specification.
"""
import django.db.models.deletion
from django.db import migrations, models

LOCK = """
CREATE OR REPLACE FUNCTION qclab_sample_stage_fixed() RETURNS trigger AS $$
BEGIN
    IF OLD.qc_stage_id IS NOT NULL AND NEW.qc_stage_id IS DISTINCT FROM OLD.qc_stage_id THEN
        RAISE EXCEPTION 'qclab: a sample keeps the QC stage it was registered for';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_qc_stage_fixed BEFORE UPDATE OF qc_stage_id ON lims_sample
    FOR EACH ROW EXECUTE FUNCTION qclab_sample_stage_fixed();
"""
UNLOCK = """
DROP TRIGGER IF EXISTS qclab_qc_stage_fixed ON lims_sample;
DROP FUNCTION IF EXISTS qclab_sample_stage_fixed();
"""


def lockdown(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(LOCK, params=None)


def unlock(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UNLOCK, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ('batches', '0004_qc_stages'),
        ('lims', '0018_samplesource'),
    ]

    operations = [
        migrations.AddField(
            model_name='sample',
            name='qc_stage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='samples', to='batches.qcstage'),
        ),
        migrations.RunPython(lockdown, unlock),
    ]
