"""
Lock the quality records down on PostgreSQL (no-op on SQLite): nothing is
deleted, the history is append-only, an action is completed once, and a
closed investigation never changes again, even against direct SQL.
"""
from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION qclab_investigation_update_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'CLOSED'
       OR NEW.reference IS DISTINCT FROM OLD.reference
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.sample_id IS DISTINCT FROM OLD.sample_id
       OR NEW.test_definition_id IS DISTINCT FROM OLD.test_definition_id
       OR NEW.result_id IS DISTINCT FROM OLD.result_id
       OR NEW.opened_by_id IS DISTINCT FROM OLD.opened_by_id
       OR NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN
        RAISE EXCEPTION 'qclab: a closed investigation, and what any investigation concerns, never change';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION qclab_capa_update_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.completed_at IS NOT NULL
       OR NEW.investigation_id IS DISTINCT FROM OLD.investigation_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.due_date IS DISTINCT FROM OLD.due_date
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'qclab: an action is only ever completed once';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER qclab_investigation_update_lock BEFORE UPDATE ON quality_investigation
    FOR EACH ROW EXECUTE FUNCTION qclab_investigation_update_guard();
CREATE TRIGGER qclab_investigation_delete_lock BEFORE DELETE ON quality_investigation
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_capa_update_lock BEFORE UPDATE ON quality_capaaction
    FOR EACH ROW EXECUTE FUNCTION qclab_capa_update_guard();
CREATE TRIGGER qclab_capa_delete_lock BEFORE DELETE ON quality_capaaction
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
CREATE TRIGGER qclab_investigation_event_lock BEFORE UPDATE OR DELETE ON quality_investigationevent
    FOR EACH ROW EXECUTE FUNCTION qclab_forbid();
"""

REVERSE = """
DROP TRIGGER IF EXISTS qclab_investigation_update_lock ON quality_investigation;
DROP TRIGGER IF EXISTS qclab_investigation_delete_lock ON quality_investigation;
DROP TRIGGER IF EXISTS qclab_capa_update_lock ON quality_capaaction;
DROP TRIGGER IF EXISTS qclab_capa_delete_lock ON quality_capaaction;
DROP TRIGGER IF EXISTS qclab_investigation_event_lock ON quality_investigationevent;
DROP FUNCTION IF EXISTS qclab_investigation_update_guard();
DROP FUNCTION IF EXISTS qclab_capa_update_guard();
"""


def lockdown(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FORWARD)


def unlock(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0001_initial"),
        # qclab_forbid() is created there.
        ("certificates", "0002_pg_lockdown"),
    ]

    operations = [migrations.RunPython(lockdown, unlock)]
