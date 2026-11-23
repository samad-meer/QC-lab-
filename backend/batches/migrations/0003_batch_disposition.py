"""
A disposition decision is append-only. On PostgreSQL it cannot be changed, deleted
or truncated, even against direct SQL.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

LOCK = """
CREATE TRIGGER qclab_append_only BEFORE UPDATE OR DELETE ON batches_batchdisposition
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_no_truncate BEFORE TRUNCATE ON batches_batchdisposition
    FOR EACH STATEMENT EXECUTE FUNCTION qclab_no_truncate();
"""
UNLOCK = """
DROP TRIGGER IF EXISTS qclab_no_truncate ON batches_batchdisposition;
DROP TRIGGER IF EXISTS qclab_append_only ON batches_batchdisposition;
"""


def lockdown(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(LOCK, params=None)


def unlock(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UNLOCK, params=None)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("batches", "0002_backfill_and_lockdown"),
        # qclab_forbid() and qclab_no_truncate() are created by then.
        ("quality", "0005_record_locks"),
    ]

    operations = [
        migrations.CreateModel(
            name="BatchDisposition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("decision", models.CharField(choices=[("RELEASED", "Released"), ("REJECTED", "Rejected"), ("QUARANTINED", "Quarantined")], max_length=12)),
                ("reason", models.CharField(max_length=1000)),
                ("decided_at", models.DateTimeField(auto_now_add=True)),
                ("basis", models.JSONField(default=dict)),
                ("basis_hash", models.CharField(max_length=64)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="dispositions", to="batches.batch")),
                ("decided_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["decided_at", "id"]},
        ),
        migrations.RunPython(lockdown, unlock),
    ]
