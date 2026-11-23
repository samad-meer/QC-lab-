"""
Turn the batch numbers already on samples into batch records, so existing
samples join the same trace as new ones. Same product and same number (ignoring
case) is one batch; dates come from the earliest sample that has them. Nothing
on the samples changes except the link. Certificates already signed are frozen
and are not touched.

On PostgreSQL, batches and their documents cannot be deleted.
"""
from django.db import migrations

LOCK = """
CREATE TRIGGER qclab_batch_delete_lock BEFORE DELETE ON batches_batch
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_batch_document_delete_lock BEFORE DELETE ON batches_batchdocument
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
"""
UNLOCK = """
DROP TRIGGER IF EXISTS qclab_batch_delete_lock ON batches_batch;
DROP TRIGGER IF EXISTS qclab_batch_document_delete_lock ON batches_batchdocument;
"""


def backfill(apps, schema_editor):
    Sample = apps.get_model("lims", "Sample")
    Batch = apps.get_model("batches", "Batch")
    Counter = apps.get_model("batches", "BatchCounter")
    seen = {}
    for sample in Sample.objects.order_by("created_at", "id"):
        if not sample.batch_no:
            continue
        key = (sample.product_id, sample.batch_no.upper())
        batch = seen.get(key)
        if batch is None:
            batch = Batch.objects.create(
                internal_id=f"BATCH-{len(seen) + 1:06d}", product_id=sample.product_id,
                official_batch_no=sample.batch_no, manufacturing_date=sample.manufacturing_date,
                expiry_date=sample.expiry_date,
            )
            Batch.objects.filter(pk=batch.pk).update(created_at=sample.created_at)
            seen[key] = batch
        elif (batch.manufacturing_date is None and sample.manufacturing_date) or (
            batch.expiry_date is None and sample.expiry_date
        ):
            batch.manufacturing_date = batch.manufacturing_date or sample.manufacturing_date
            batch.expiry_date = batch.expiry_date or sample.expiry_date
            batch.save(update_fields=["manufacturing_date", "expiry_date"])
        Sample.objects.filter(pk=sample.pk).update(batch=batch)
    if seen:
        # The default rule's scope, so the next batch carries on from here.
        Counter.objects.create(scope="BATCH|||", last_no=len(seen))


def unlink(apps, schema_editor):
    apps.get_model("lims", "Sample").objects.update(batch=None)
    apps.get_model("batches", "Batch").objects.all().delete()
    apps.get_model("batches", "BatchCounter").objects.all().delete()


def lockdown(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(LOCK)


def unlock(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(UNLOCK)


class Migration(migrations.Migration):
    dependencies = [
        ("batches", "0001_traceability"),
        ("lims", "0010_traceability"),
        ("execution", "0002_backfill_and_lockdown"),
    ]

    operations = [
        migrations.RunPython(backfill, unlink),
        migrations.RunPython(lockdown, unlock),
    ]
