"""
Database-level immutability — PostgreSQL only (no-op on SQLite dev DB).

Application code already refuses illegal changes, but Rule One/Two must
hold even against direct SQL by someone with database access. These
triggers make the tables physically append-only where the brief demands:

- audit_auditevent: no UPDATE, no DELETE, ever
- certificates_signature: no UPDATE, no DELETE
- certificates_printevent: no UPDATE, no DELETE
- certificates_certificate: no DELETE; UPDATE may only change
  status/superseded_reason (content, hash, version, sample frozen)
- lims_testresult: no DELETE; UPDATE may only set the supersede fields
- lims_workflowevent: no UPDATE, no DELETE
"""
from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION qclab_forbid() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'qclab: % on % is forbidden — records are immutable (Rule One/Two)',
        TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION qclab_cert_update_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.content::text IS DISTINCT FROM OLD.content::text
       OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.sample_id IS DISTINCT FROM OLD.sample_id
       OR NEW.verification_uuid IS DISTINCT FROM OLD.verification_uuid
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'qclab: signed certificate content is frozen (Rule One)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION qclab_result_update_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.sample_id IS DISTINCT FROM OLD.sample_id
       OR NEW.test_definition_id IS DISTINCT FROM OLD.test_definition_id
       OR NEW.value_numeric IS DISTINCT FROM OLD.value_numeric
       OR NEW.value_text IS DISTINCT FROM OLD.value_text
       OR NEW.outcome IS DISTINCT FROM OLD.outcome
       OR NEW.entered_by_id IS DISTINCT FROM OLD.entered_by_id
       OR NEW.entered_at IS DISTINCT FROM OLD.entered_at THEN
        RAISE EXCEPTION 'qclab: test results are never edited (Rule Two) — supersede instead';
    END IF;
    IF OLD.is_superseded THEN
        -- One exception: linking the replacement row, exactly once.
        IF OLD.replaced_by_id IS NULL AND NEW.replaced_by_id IS NOT NULL
           AND NEW.is_superseded
           AND NEW.superseded_at IS NOT DISTINCT FROM OLD.superseded_at
           AND NEW.superseded_by_user_id IS NOT DISTINCT FROM OLD.superseded_by_user_id
           AND NEW.supersede_reason IS NOT DISTINCT FROM OLD.supersede_reason THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'qclab: a superseded result can never change again (Rule Two)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER qclab_audit_lock BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_signature_lock BEFORE UPDATE OR DELETE ON certificates_signature
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_print_lock BEFORE UPDATE OR DELETE ON certificates_printevent
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_wfevent_lock BEFORE UPDATE OR DELETE ON lims_workflowevent
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_cert_delete_lock BEFORE DELETE ON certificates_certificate
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_result_delete_lock BEFORE DELETE ON lims_testresult
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_cert_update_lock BEFORE UPDATE ON certificates_certificate
    FOR EACH ROW EXECUTE FUNCTION qclab_cert_update_guard();
CREATE TRIGGER qclab_result_update_lock BEFORE UPDATE ON lims_testresult
    FOR EACH ROW EXECUTE FUNCTION qclab_result_update_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS qclab_audit_lock ON audit_auditevent;
DROP TRIGGER IF EXISTS qclab_signature_lock ON certificates_signature;
DROP TRIGGER IF EXISTS qclab_print_lock ON certificates_printevent;
DROP TRIGGER IF EXISTS qclab_wfevent_lock ON lims_workflowevent;
DROP TRIGGER IF EXISTS qclab_cert_delete_lock ON certificates_certificate;
DROP TRIGGER IF EXISTS qclab_result_delete_lock ON lims_testresult;
DROP TRIGGER IF EXISTS qclab_cert_update_lock ON certificates_certificate;
DROP TRIGGER IF EXISTS qclab_result_update_lock ON lims_testresult;
DROP FUNCTION IF EXISTS qclab_forbid();
DROP FUNCTION IF EXISTS qclab_cert_update_guard();
DROP FUNCTION IF EXISTS qclab_result_update_guard();
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        # params=None: the SQL holds a literal % and must not be read as a placeholder.
        schema_editor.execute(FORWARD, params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [
        ("certificates", "0001_initial"),
        ("audit", "0001_initial"),
        ("lims", "0001_initial"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
