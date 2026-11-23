"""
Bring existing records into the lab-execution model, and lock the new
tables down on PostgreSQL.

1. Every sample already registered gets the assignment its registration
   implied — testing held by its analyst, accepted, at the moment it was
   registered — so its handover history starts at the beginning.
2. Every certificate already sent back gets the stage, person and time of
   the send-back, taken from the sample's own workflow history: the first
   review stage it carries no signature for, and the movement back to
   testing that followed it.
3. On PostgreSQL, triggers make the answer, file, comment and waiver
   records append-only even against direct SQL (no-op on SQLite).
"""
from django.db import migrations

REVIEW_STATUSES = ["IN_REVIEW", "AWAITING_CHECK", "AWAITING_APPROVAL"]


def backfill(apps, schema_editor):
    Sample = apps.get_model("lims", "Sample")
    WorkflowEvent = apps.get_model("lims", "WorkflowEvent")
    Certificate = apps.get_model("certificates", "Certificate")
    Assignment = apps.get_model("execution", "Assignment")

    for sample in Sample.objects.all():
        if Assignment.objects.filter(sample=sample, step="TESTING").exists():
            continue
        a = Assignment.objects.create(
            sample=sample, step="TESTING", kind="ASSIGNED", status="ACCEPTED",
            to_user_id=sample.assigned_analyst_id, created_by_id=sample.registered_by_id,
            note="Assigned at registration", responded_at=sample.created_at,
            response_reason="Recorded before handovers existed",
        )
        # Historical models have no save() guard; the timestamp is the registration's.
        Assignment.objects.filter(pk=a.pk).update(created_at=sample.created_at)

    for cert in Certificate.objects.filter(status="SUPERSEDED", returned_at__isnull=True):
        sample = cert.sample
        signed = set(cert.signatures.values_list("meaning", flat=True))
        stage = next(
            (s for s in sample.workflow_version.stages.order_by("order") if s.code not in signed), None
        )
        event = (
            WorkflowEvent.objects.filter(
                sample=sample, at__gte=cert.created_at, from_status__in=REVIEW_STATUSES, to_status="IN_TESTING"
            ).order_by("at", "id").first()
        )
        Certificate.objects.filter(pk=cert.pk).update(
            returned_stage=stage.code if stage else "",
            returned_by_id=event.actor_id if event else None,
            returned_at=event.at if event else None,
        )


FORWARD = """
CREATE OR REPLACE FUNCTION qclab_response_update_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.replaced_at IS NOT NULL
       OR NEW.sample_id IS DISTINCT FROM OLD.sample_id
       OR NEW.item_id IS DISTINCT FROM OLD.item_id
       OR NEW.attempt IS DISTINCT FROM OLD.attempt
       OR NEW.value IS DISTINCT FROM OLD.value
       OR NEW.number IS DISTINCT FROM OLD.number
       OR NEW.attachment_id IS DISTINCT FROM OLD.attachment_id
       OR NEW.conforms IS DISTINCT FROM OLD.conforms
       OR NEW.answered_by_id IS DISTINCT FROM OLD.answered_by_id
       OR NEW.answered_at IS DISTINCT FROM OLD.answered_at THEN
        RAISE EXCEPTION 'qclab: checklist answers are never edited — give a new answer';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION qclab_attachment_update_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.file IS DISTINCT FROM OLD.file
       OR NEW.sha256 IS DISTINCT FROM OLD.sha256
       OR NEW.size IS DISTINCT FROM OLD.size
       OR NEW.sample_id IS DISTINCT FROM OLD.sample_id
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.uploaded_by_id IS DISTINCT FROM OLD.uploaded_by_id
       OR NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at THEN
        RAISE EXCEPTION 'qclab: an uploaded file is never changed — upload a new version';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER qclab_item_lock BEFORE UPDATE ON execution_checklistitem
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_response_update_lock BEFORE UPDATE ON execution_checklistresponse
    FOR EACH ROW EXECUTE FUNCTION qclab_response_update_guard();
CREATE TRIGGER qclab_response_delete_lock BEFORE DELETE ON execution_checklistresponse
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_attachment_update_lock BEFORE UPDATE ON execution_attachment
    FOR EACH ROW EXECUTE FUNCTION qclab_attachment_update_guard();
CREATE TRIGGER qclab_attachment_delete_lock BEFORE DELETE ON execution_attachment
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_comment_lock BEFORE UPDATE OR DELETE ON execution_stepcomment
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_waiver_lock BEFORE UPDATE OR DELETE ON execution_waiver
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_assignment_delete_lock BEFORE DELETE ON execution_assignment
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_hold_delete_lock BEFORE DELETE ON execution_samplehold
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_retest_delete_lock BEFORE DELETE ON execution_retestrequest
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
"""

REVERSE = """
DROP TRIGGER IF EXISTS qclab_item_lock ON execution_checklistitem;
DROP TRIGGER IF EXISTS qclab_response_update_lock ON execution_checklistresponse;
DROP TRIGGER IF EXISTS qclab_response_delete_lock ON execution_checklistresponse;
DROP TRIGGER IF EXISTS qclab_attachment_update_lock ON execution_attachment;
DROP TRIGGER IF EXISTS qclab_attachment_delete_lock ON execution_attachment;
DROP TRIGGER IF EXISTS qclab_comment_lock ON execution_stepcomment;
DROP TRIGGER IF EXISTS qclab_waiver_lock ON execution_waiver;
DROP TRIGGER IF EXISTS qclab_assignment_delete_lock ON execution_assignment;
DROP TRIGGER IF EXISTS qclab_hold_delete_lock ON execution_samplehold;
DROP TRIGGER IF EXISTS qclab_retest_delete_lock ON execution_retestrequest;
DROP FUNCTION IF EXISTS qclab_response_update_guard();
DROP FUNCTION IF EXISTS qclab_attachment_update_guard();
"""


def lockdown(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def unlock(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [
        ("execution", "0001_initial"),
        ("lims", "0007_workflowstage_requires_acceptance_and_more"),
        ("certificates", "0004_certificate_returned_at_certificate_returned_by_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.RunPython(lockdown, unlock),
    ]
