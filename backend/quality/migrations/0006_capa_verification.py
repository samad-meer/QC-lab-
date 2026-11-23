"""
A completed action is verified once, by someone else. On PostgreSQL the trigger
from 0002 refused every change after completion, so it is replaced: while an
action is open it can be completed, once it is completed it can be verified, and
once verified it never changes. What it says stays fixed throughout.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

GUARD = """
CREATE OR REPLACE FUNCTION qclab_capa_update_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.verified_at IS NOT NULL
       OR NEW.investigation_id IS DISTINCT FROM OLD.investigation_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
       OR NEW.due_date IS DISTINCT FROM OLD.due_date
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'qclab: an action is only ever completed once, and verified once';
    END IF;
    IF OLD.completed_at IS NOT NULL AND (
        NEW.completed_at IS DISTINCT FROM OLD.completed_at
        OR NEW.completed_by_id IS DISTINCT FROM OLD.completed_by_id
        OR NEW.completion_note IS DISTINCT FROM OLD.completion_note
    ) THEN
        RAISE EXCEPTION 'qclab: an action is only ever completed once';
    END IF;
    IF OLD.completed_at IS NULL AND (
        NEW.verified_at IS NOT NULL
        OR NEW.verified_by_id IS NOT NULL
        OR NEW.verification_note <> ''
    ) THEN
        RAISE EXCEPTION 'qclab: an action is verified after it is completed';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# As 0002 left it.
PREVIOUS = """
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
"""


def forward(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(GUARD, params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(PREVIOUS, params=None)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("quality", "0005_record_locks"),
    ]

    operations = [
        migrations.AddField(
            model_name="capaaction",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="capaaction",
            name="verified_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="capaaction",
            name="verification_note",
            field=models.CharField(blank=True, max_length=1000),
        ),
        migrations.RunPython(forward, reverse),
    ]
