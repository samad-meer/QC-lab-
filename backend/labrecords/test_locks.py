"""
What can be checked of the database locks without PostgreSQL: that each trigger
names real tables and columns, and that every table here has one. Plus the things
every register owes the rest of the system.
"""
import importlib
import re
from pathlib import Path

from django.apps import apps
from django.db import connection
from django.test import SimpleTestCase, TestCase

from accounts.permissions_registry import ALL_PERMISSIONS
from audit.describe import TEMPLATES
from .registers import REGISTERS
from .test_base import LabTestBase

lockdown = importlib.import_module("labrecords.migrations.0002_lockdown")
capa = importlib.import_module("quality.migrations.0006_capa_verification")
disposition = importlib.import_module("batches.migrations.0003_batch_disposition")

GUARDED = {
    "qclab_master_guard": ["labrecords_instrument", "labrecords_material"],
    "qclab_method_guard": ["labrecords_method"],
    "qclab_qualification_guard": ["labrecords_qualification"],
    "qclab_change_guard": ["labrecords_changerecord"],
}


def functions(sql: str) -> dict[str, str]:
    parts = re.split(r"CREATE OR REPLACE FUNCTION (\w+)\(\)", sql)
    return dict(zip(parts[1::2], parts[2::2]))


class TriggerTests(TestCase):
    def columns(self, table: str) -> set[str]:
        with connection.cursor() as cursor:
            return {c.name for c in connection.introspection.get_table_description(cursor, table)}

    def assert_columns_exist(self, body: str, table: str):
        used = set(re.findall(r"\b(?:NEW|OLD)\.(\w+)", body))
        self.assertTrue(used)
        self.assertEqual(used - self.columns(table), set(), table)

    def test_every_guard_names_columns_its_tables_have(self):
        found = functions(lockdown.GUARDS)
        self.assertEqual(set(found), set(GUARDED))
        for name, tables in GUARDED.items():
            for table in tables:
                self.assert_columns_exist(found[name], table)

    def test_the_capa_guard_names_real_columns_and_keeps_the_old_one_for_reversing(self):
        self.assert_columns_exist(capa.GUARD, "quality_capaaction")
        self.assert_columns_exist(capa.PREVIOUS, "quality_capaaction")

    def test_the_new_capa_guard_allows_verifying_only_once_it_is_completed(self):
        self.assertIn("OLD.verified_at IS NOT NULL", capa.GUARD)
        self.assertIn("OLD.completed_at IS NULL AND", capa.GUARD)
        self.assertIn("NEW.completion_note IS DISTINCT FROM OLD.completion_note", capa.GUARD)

    def test_every_table_of_the_app_is_locked_including_the_many_to_many(self):
        tables = {
            m._meta.db_table for m in apps.get_app_config("labrecords").get_models(include_auto_created=True)
        }
        self.assertIn("labrecords_resultrecord_materials", tables)
        self.assertEqual(tables, set(lockdown.NO_TRUNCATE))
        self.assertEqual(tables, {*lockdown.APPEND_ONLY, *lockdown.KEPT, "labrecords_changecounter"})

    def test_the_disposition_table_is_locked(self):
        self.assertIn("batches_batchdisposition", disposition.LOCK)
        self.assertIn("batches_batchdisposition", connection.introspection.table_names())

    def test_the_sql_is_only_sent_on_postgresql_and_without_placeholders(self):
        """`%` in a RAISE must not be read as a placeholder: every call passes params=None."""
        for module in (lockdown, capa, disposition):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"schema_editor\.execute\(", source)),
                             len(re.findall(r"params=None", source)), module.__name__)
            self.assertIn('vendor', source)


class AuditCoverageTests(SimpleTestCase):
    def test_every_action_written_has_a_sentence(self):
        root = Path(__file__).resolve().parent.parent
        written = set()
        for path in [*root.glob("labrecords/*.py"), root / "batches/services.py", root / "quality/services.py"]:
            if path.name.startswith("test"):
                continue
            source = path.read_text(encoding="utf-8")
            written |= set(re.findall(r"record\(\s*[\w.]+,\s*\"([A-Z_]+)\"", source))
            written |= set(re.findall(r"^\s+\"([A-Z]+_[A-Z_]*REFUSED)\",$", source, re.M))
        self.assertIn("CHANGE_APPROVAL_REFUSED", written)
        self.assertEqual(written - set(TEMPLATES), set())

    def test_the_permissions_used_are_real_keys(self):
        from . import services
        for name in ("INSTRUMENTS", "MATERIALS", "METHODS", "METHOD_APPROVE", "QUALIFICATIONS", "CUSTODY", "DESTROY",
                     "CHANGES", "CHANGE_APPROVE"):
            self.assertIn(getattr(services, name), ALL_PERMISSIONS)
        self.assertIn("batch.disposition", ALL_PERMISSIONS)


class RegisterTests(LabTestBase):
    def test_the_definitions_say_what_this_person_may_do(self):
        mine = {r["key"]: r for r in self.ok(self.get("/api/lab/registers/", self.analyst))["registers"]}
        self.assertEqual(set(mine), {"instruments", "materials", "methods", "qualifications", "retained", "changes"})
        self.assertFalse(mine["instruments"]["can_add"])
        self.assertEqual(mine["instruments"]["add_fields"], [])
        boss = {r["key"]: r for r in self.ok(self.get("/api/lab/registers/"))["registers"]}
        self.assertTrue(boss["instruments"]["can_add"])
        self.assertTrue(any(f["kind"] == "password" for f in boss["qualifications"]["add_fields"]))
        self.assertFalse(boss["retained"]["can_add"])

    def test_each_register_lists_with_nothing_in_it(self):
        for key in REGISTERS:
            data = self.ok(self.get(f"/api/lab/{key}/"))
            self.assertEqual((data["results"], data["count"]), ([], 0))

    def test_what_does_not_exist_is_a_404(self):
        self.assertEqual(self.get("/api/lab/nothing/").status_code, 404)
        self.assertEqual(self.get("/api/lab/instruments/999/").status_code, 404)
        self.assertEqual(self.post("/api/lab/instruments/999/correct/", {}).status_code, 404)
        pk = self.add_instrument()
        self.assertEqual(self.post(f"/api/lab/instruments/{pk}/explode/", {}).status_code, 404)
        self.assertEqual(self.post("/api/lab/retained/", {}).status_code, 404)
        self.assertEqual(self.get("/api/lab/retained/1/").status_code, 404)

    def test_every_detail_page_builds_with_real_records(self):
        instrument = self.usable_instrument()
        material = self.add_material()
        method = self.effective_method()
        qualification = self.ok(self.qualify(self.analyst), 201)["id"]
        for key, pk in (("instruments", instrument), ("materials", material), ("methods", method.pk),
                        ("qualifications", qualification)):
            data = self.ok(self.get(f"/api/lab/{key}/{pk}/"))
            self.assertTrue(data["facts"], key)
            self.assertTrue(data["history"], key)

    def test_signing_in_is_needed(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/lab/registers/").status_code, 403)
