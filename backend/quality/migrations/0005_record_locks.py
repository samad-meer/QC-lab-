"""
The rest of the database locks.

- TRUNCATE passes row triggers, so it is refused on every record table.
- What a retest, hold, handover, batch document or permission grant says is
  fixed. Only their own later steps (a decision, a release) can be added.
- A certificate's status moves only the ways the application allows.
- Tests and limits stop changing once a sample uses them, and an approved
  specification stops changing altogether, apart from moving to superseded and
  its next review date.
"""
from django.db import migrations

NO_TRUNCATE = (
    "accounts_passwordhistory", "accounts_rolepermissiongrant", "audit_auditevent", "audit_auditreview",
    "batches_batch", "batches_batchdocument",
    "certificates_certificate", "certificates_printevent", "certificates_signature",
    "execution_assignment", "execution_attachment", "execution_checklistitem", "execution_checklistresponse",
    "execution_receiptcompletion", "execution_retestrequest", "execution_samplehold", "execution_stepcomment",
    "execution_waiver",
    "lims_sample", "lims_specification", "lims_testdefinition", "lims_testresult", "lims_workflowevent",
    "lims_workflowstage", "lims_workflowversion",
    "quality_capaaction", "quality_investigation", "quality_investigationevent",
)

FIXED_COLUMNS = {
    "execution_retestrequest": ("sample_id", "test_definition_id", "failed_result_id", "kind", "reason",
                                "requested_by_id", "requested_at"),
    "execution_samplehold": ("sample_id", "step", "reason", "placed_by_id", "placed_at"),
    "execution_assignment": ("sample_id", "step", "kind", "from_user_id", "to_user_id", "created_by_id",
                             "created_at", "note"),
    "batches_batchdocument": ("batch_id", "doc_type", "title", "version", "replaces_id", "file", "original_name",
                              "extension", "content_type", "size", "sha256", "note", "uploaded_by_id", "uploaded_at"),
    "accounts_rolepermissiongrant": ("role_id", "permission", "granted_at", "granted_by_id"),
}

GENERAL = """
CREATE OR REPLACE FUNCTION qclab_no_truncate() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'qclab: TRUNCATE on % is forbidden — records are never deleted (Rule Two)', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION qclab_cert_status_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'IN_REVIEW' AND NEW.status IN ('APPROVED', 'SUPERSEDED'))
        OR (OLD.status = 'APPROVED' AND NEW.status = 'WITHDRAWN')
    ) THEN
        RAISE EXCEPTION 'qclab: a certificate cannot move from % to %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_cert_status BEFORE UPDATE ON certificates_certificate
    FOR EACH ROW EXECUTE FUNCTION qclab_cert_status_guard();

CREATE OR REPLACE FUNCTION qclab_spec_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'qclab: an approved specification is never deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status <> 'DRAFT' AND (
        NEW.product_id IS DISTINCT FROM OLD.product_id OR NEW.version IS DISTINCT FROM OLD.version
        OR NEW.effective_date IS DISTINCT FROM OLD.effective_date
        OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
        OR NEW.approved_by_id IS DISTINCT FROM OLD.approved_by_id
        OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
        OR NEW.approved_digest IS DISTINCT FROM OLD.approved_digest
        OR (NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'EFFECTIVE' AND NEW.status = 'SUPERSEDED'))
    ) THEN
        RAISE EXCEPTION 'qclab: an approved specification is never edited — draft a new version';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_spec_lock BEFORE UPDATE OR DELETE ON lims_specification
    FOR EACH ROW EXECUTE FUNCTION qclab_spec_guard();

CREATE OR REPLACE FUNCTION qclab_test_guard() RETURNS trigger AS $$
DECLARE
    spec bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN spec := NEW.specification_id; ELSE spec := OLD.specification_id; END IF;
    IF EXISTS (SELECT 1 FROM lims_sample WHERE specification_id = spec) THEN
        RAISE EXCEPTION 'qclab: the tests of a specification in use never change';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_test_lock BEFORE INSERT OR UPDATE OR DELETE ON lims_testdefinition
    FOR EACH ROW EXECUTE FUNCTION qclab_test_guard();

CREATE TRIGGER qclab_grant_lock BEFORE DELETE ON accounts_rolepermissiongrant
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_review_lock BEFORE UPDATE OR DELETE ON audit_auditreview
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
"""

UNLOCK_GENERAL = """
DROP TRIGGER IF EXISTS qclab_review_lock ON audit_auditreview;
DROP TRIGGER IF EXISTS qclab_grant_lock ON accounts_rolepermissiongrant;
DROP TRIGGER IF EXISTS qclab_test_lock ON lims_testdefinition;
DROP FUNCTION IF EXISTS qclab_test_guard();
DROP TRIGGER IF EXISTS qclab_spec_lock ON lims_specification;
DROP FUNCTION IF EXISTS qclab_spec_guard();
DROP TRIGGER IF EXISTS qclab_cert_status ON certificates_certificate;
DROP FUNCTION IF EXISTS qclab_cert_status_guard();
"""


def _fixed(table: str, columns) -> str:
    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in columns)
    return f"""
CREATE OR REPLACE FUNCTION qclab_fixed_{table}() RETURNS trigger AS $$
BEGIN
    IF {changed} THEN
        RAISE EXCEPTION 'qclab: what this record says is fixed ({table})';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_fixed BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION qclab_fixed_{table}();
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(GENERAL, params=None)
    for table, columns in FIXED_COLUMNS.items():
        schema_editor.execute(_fixed(table, columns), params=None)
    for table in NO_TRUNCATE:
        schema_editor.execute(
            f"CREATE TRIGGER qclab_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION qclab_no_truncate();",
            params=None,
        )


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in NO_TRUNCATE:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS qclab_no_truncate ON {table};", params=None)
    schema_editor.execute("DROP FUNCTION IF EXISTS qclab_no_truncate();", params=None)
    for table in FIXED_COLUMNS:
        schema_editor.execute(
            f"DROP TRIGGER IF EXISTS qclab_fixed ON {table}; DROP FUNCTION IF EXISTS qclab_fixed_{table}();",
            params=None,
        )
    schema_editor.execute(UNLOCK_GENERAL, params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_grant_audit_view_to_lab_head"),
        ("audit", "0003_auditreview"),
        ("batches", "0002_backfill_and_lockdown"),
        ("certificates", "0006_signature_seal"),
        ("execution", "0004_reporting_fields"),
        ("lims", "0016_specification_approval_record"),
        ("quality", "0004_investigation_closure_digest"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
