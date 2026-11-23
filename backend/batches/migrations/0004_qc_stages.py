"""
QC stages: the stages every batch of a product goes through, versioned like a
specification, and the QA-recorded results of a batch's stages. On PostgreSQL a
version of the stages and a recorded result can never be changed, deleted or
truncated, and a batch keeps the stages it was created with.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

TABLES = ("batches_qcstageplan", "batches_qcstage", "batches_batchstageresult")
LOCK = "".join(
    f"""
CREATE TRIGGER qclab_append_only BEFORE UPDATE OR DELETE ON {t}
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_no_truncate BEFORE TRUNCATE ON {t}
    FOR EACH STATEMENT EXECUTE FUNCTION qclab_no_truncate();
"""
    for t in TABLES
) + """
CREATE OR REPLACE FUNCTION qclab_batch_stage_plan_fixed() RETURNS trigger AS $$
BEGIN
    IF OLD.stage_plan_id IS NOT NULL AND NEW.stage_plan_id IS DISTINCT FROM OLD.stage_plan_id THEN
        RAISE EXCEPTION 'qclab: a batch keeps the QC stages it was created with';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_stage_plan_fixed BEFORE UPDATE OF stage_plan_id ON batches_batch
    FOR EACH ROW EXECUTE FUNCTION qclab_batch_stage_plan_fixed();
"""
UNLOCK = "".join(
    f"""
DROP TRIGGER IF EXISTS qclab_no_truncate ON {t};
DROP TRIGGER IF EXISTS qclab_append_only ON {t};
"""
    for t in TABLES
) + """
DROP TRIGGER IF EXISTS qclab_stage_plan_fixed ON batches_batch;
DROP FUNCTION IF EXISTS qclab_batch_stage_plan_fixed();
"""


def lockdown(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(LOCK, params=None)


def unlock(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UNLOCK, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ('batches', '0003_batch_disposition'),
        ('lims', '0018_samplesource'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='QcStage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.PositiveIntegerField()),
                ('name', models.CharField(max_length=80)),
                ('description', models.CharField(blank=True, max_length=300)),
                ('kind', models.CharField(choices=[('TESTED', 'Tested in the lab'), ('RECORDED', 'Recorded by QA')], max_length=10)),
                ('required', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['plan', 'order'],
            },
        ),
        migrations.CreateModel(
            name='BatchStageResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('decision', models.CharField(choices=[('PASSED', 'Passed'), ('FAILED', 'Failed')], max_length=10)),
                ('remarks', models.CharField(blank=True, max_length=1000)),
                ('recorded_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stage_results', to='batches.batch')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('stage', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='results', to='batches.qcstage')),
            ],
            options={
                'ordering': ['recorded_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='QcStagePlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField()),
                ('reason', models.CharField(max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stage_plans', to='lims.product')),
            ],
            options={
                'ordering': ['product', 'version'],
            },
        ),
        migrations.AddField(
            model_name='qcstage',
            name='plan',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='stages', to='batches.qcstageplan'),
        ),
        migrations.AddField(
            model_name='batch',
            name='stage_plan',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='batches', to='batches.qcstageplan'),
        ),
        migrations.AddConstraint(
            model_name='qcstageplan',
            constraint=models.UniqueConstraint(fields=('product', 'version'), name='uniq_stage_plan_version'),
        ),
        migrations.AddConstraint(
            model_name='qcstage',
            constraint=models.UniqueConstraint(fields=('plan', 'order'), name='uniq_qc_stage_order'),
        ),
        migrations.RunPython(lockdown, unlock),
    ]
