"""
Lock the lab records down on PostgreSQL (no-op on SQLite), even against direct SQL.

- A log is append-only: logbooks, raw data with its readings and materials,
  custody, and the history of every record.
- Nothing here is deleted, and TRUNCATE is refused on every table.
- A retired instrument, material or method never changes, and nor does an
  effective method apart from being retired.
- A qualification is only ever revoked, once.
- A change record moves one way, what was approved stays as it was approved, and
  closed or rejected is final.
"""
from django.db import migrations

APPEND_ONLY = (
    "labrecords_calibrationevent", "labrecords_custodyevent", "labrecords_recordevent",
    "labrecords_resultreading", "labrecords_resultrecord", "labrecords_resultrecord_materials",
)
KEPT = (
    "labrecords_changerecord", "labrecords_instrument", "labrecords_material", "labrecords_method",
    "labrecords_qualification",
)
NO_TRUNCATE = (*APPEND_ONLY, *KEPT, "labrecords_changecounter")

GUARDS = """
CREATE OR REPLACE FUNCTION qclab_master_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'RETIRED'
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'qclab: a retired record never changes, and who added a record is fixed';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_master_lock BEFORE UPDATE ON labrecords_instrument
    FOR EACH ROW EXECUTE FUNCTION qclab_master_guard();
CREATE TRIGGER qclab_master_lock BEFORE UPDATE ON labrecords_material
    FOR EACH ROW EXECUTE FUNCTION qclab_master_guard();

CREATE OR REPLACE FUNCTION qclab_method_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.code IS DISTINCT FROM OLD.code
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR OLD.status = 'RETIRED' THEN
        RAISE EXCEPTION 'qclab: a retired method never changes, and which method a row is stays fixed';
    END IF;
    IF OLD.status = 'EFFECTIVE' AND (
        NEW.title IS DISTINCT FROM OLD.title
        OR NEW.document_ref IS DISTINCT FROM OLD.document_ref
        OR NEW.validation_status IS DISTINCT FROM OLD.validation_status
        OR NEW.change_reason IS DISTINCT FROM OLD.change_reason
        OR NEW.edited_by_id IS DISTINCT FROM OLD.edited_by_id
        OR NEW.approved_by_id IS DISTINCT FROM OLD.approved_by_id
        OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
        OR NEW.approved_digest IS DISTINCT FROM OLD.approved_digest
        OR (NEW.status IS DISTINCT FROM OLD.status AND NEW.status <> 'RETIRED')
    ) THEN
        RAISE EXCEPTION 'qclab: an effective method is never edited — draft a new version';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_method_lock BEFORE UPDATE ON labrecords_method
    FOR EACH ROW EXECUTE FUNCTION qclab_method_guard();

CREATE OR REPLACE FUNCTION qclab_qualification_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.revoked_at IS NOT NULL
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.method IS DISTINCT FROM OLD.method
       OR NEW.qualified_on IS DISTINCT FROM OLD.qualified_on
       OR NEW.expires_on IS DISTINCT FROM OLD.expires_on
       OR NEW.qualified_by_id IS DISTINCT FROM OLD.qualified_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'qclab: a qualification is only ever revoked once';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_qualification_lock BEFORE UPDATE ON labrecords_qualification
    FOR EACH ROW EXECUTE FUNCTION qclab_qualification_guard();

CREATE OR REPLACE FUNCTION qclab_change_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('CLOSED', 'REJECTED')
       OR NEW.reference IS DISTINCT FROM OLD.reference
       OR NEW.raised_by_id IS DISTINCT FROM OLD.raised_by_id
       OR NEW.raised_at IS DISTINCT FROM OLD.raised_at THEN
        RAISE EXCEPTION 'qclab: a closed or rejected change, and who raised any change, never change';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'OPEN' AND NEW.status IN ('APPROVED', 'REJECTED'))
        OR (OLD.status = 'APPROVED' AND NEW.status = 'IMPLEMENTED')
        OR (OLD.status = 'IMPLEMENTED' AND NEW.status = 'CLOSED')
    ) THEN
        RAISE EXCEPTION 'qclab: a change record cannot move from % to %', OLD.status, NEW.status;
    END IF;
    IF OLD.status <> 'OPEN' AND (
        NEW.title IS DISTINCT FROM OLD.title
        OR NEW.description IS DISTINCT FROM OLD.description
        OR NEW.reason IS DISTINCT FROM OLD.reason
        OR NEW.impact_assessment IS DISTINCT FROM OLD.impact_assessment
        OR NEW.category IS DISTINCT FROM OLD.category
        OR NEW.approved_digest IS DISTINCT FROM OLD.approved_digest
    ) THEN
        RAISE EXCEPTION 'qclab: what was approved cannot change';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER qclab_change_lock BEFORE UPDATE ON labrecords_changerecord
    FOR EACH ROW EXECUTE FUNCTION qclab_change_guard();
"""

UNLOCK_GUARDS = """
DROP TRIGGER IF EXISTS qclab_change_lock ON labrecords_changerecord;
DROP FUNCTION IF EXISTS qclab_change_guard();
DROP TRIGGER IF EXISTS qclab_qualification_lock ON labrecords_qualification;
DROP FUNCTION IF EXISTS qclab_qualification_guard();
DROP TRIGGER IF EXISTS qclab_method_lock ON labrecords_method;
DROP FUNCTION IF EXISTS qclab_method_guard();
DROP TRIGGER IF EXISTS qclab_master_lock ON labrecords_material;
DROP TRIGGER IF EXISTS qclab_master_lock ON labrecords_instrument;
DROP FUNCTION IF EXISTS qclab_master_guard();
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(GUARDS, params=None)
    for table in APPEND_ONLY:
        schema_editor.execute(
            f"CREATE TRIGGER qclab_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION qclab_forbid();",
            params=None,
        )
    for table in KEPT:
        schema_editor.execute(
            f"CREATE TRIGGER qclab_kept BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION qclab_forbid();",
            params=None,
        )
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
    for table in KEPT:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS qclab_kept ON {table};", params=None)
    for table in APPEND_ONLY:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS qclab_append_only ON {table};", params=None)
    schema_editor.execute(UNLOCK_GUARDS, params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("labrecords", "0001_initial"),
        # qclab_forbid() and qclab_no_truncate() are created in these.
        ("certificates", "0002_pg_lockdown"),
        ("quality", "0005_record_locks"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
