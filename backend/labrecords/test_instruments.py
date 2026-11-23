"""Instruments and their logbooks; reference standards, reagents and columns."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from audit.models import AuditEvent
from qclab.testing import force_update
from .models import CalibrationEvent, Instrument, Material, RecordEvent
from .services import instrument_problem, material_problem
from .test_base import LabTestBase


class InstrumentTests(LabTestBase):
    def problem(self, pk):
        return instrument_problem(Instrument.objects.get(pk=pk))

    def test_adding_one_needs_the_permission_and_a_code_of_its_own(self):
        self.refused(self.post("/api/lab/instruments/", {"code": "X"}, self.analyst), "permission")
        self.add_instrument("HPLC-01")
        r = self.post("/api/lab/instruments/", {"code": "hplc-01", "name": "N", "type": "T", "location": "L"})
        self.refused(r, "already exists")

    def test_a_new_instrument_cannot_be_used_until_it_is_calibrated(self):
        pk = self.add_instrument()
        self.assertIn("no passing calibration", self.problem(pk))
        self.ok(self.calibrate(pk))
        self.assertIsNone(self.problem(pk))

    def test_it_can_be_used_on_the_day_calibration_is_due_and_not_after(self):
        pk = self.add_instrument()
        self.ok(self.calibrate(pk, days=-5, due=0))
        self.assertIsNone(self.problem(pk))
        force_update(CalibrationEvent.objects.all(), next_due=timezone.localdate() - timedelta(days=1))
        self.assertIn("was due for calibration on", self.problem(pk))

    def test_only_a_calibration_keeps_it_in_date(self):
        pk = self.add_instrument()
        self.ok(self.calibrate(pk, kind="MAINTENANCE"))
        self.assertIn("no passing calibration", self.problem(pk))

    def test_an_old_certificate_entered_late_extends_nothing(self):
        pk = self.add_instrument()
        self.ok(self.calibrate(pk, days=-2, due=-1))
        self.ok(self.calibrate(pk, days=-300, due=30))
        self.assertIn("was due for calibration", self.problem(pk))

    def test_a_failed_calibration_takes_it_out_of_service(self):
        pk = self.usable_instrument()
        self.ok(self.calibrate(pk, days=0, due=None, outcome="FAIL"))
        self.assertEqual(Instrument.objects.get(pk=pk).status, "OUT_OF_SERVICE")
        self.assertIn("out of service", self.problem(pk))
        self.assertTrue(AuditEvent.objects.filter(action="INSTRUMENT_OUT_OF_SERVICE").exists())

    def test_a_failed_repair_counts_as_well(self):
        pk = self.usable_instrument()
        self.ok(self.calibrate(pk, days=0, due=None, outcome="FAIL", kind="REPAIR"))
        self.assertEqual(Instrument.objects.get(pk=pk).status, "OUT_OF_SERVICE")

    def status(self, pk, status, comment="Decided"):
        return self.post(f"/api/lab/instruments/{pk}/status/", {"status": status, "comment": comment})

    def test_it_goes_back_in_service_only_on_a_calibration_since_the_failure(self):
        pk = self.usable_instrument()
        self.ok(self.calibrate(pk, days=-1, due=None, outcome="FAIL"))
        self.refused(self.status(pk, "IN_SERVICE"), "needs a passing calibration")
        self.ok(self.calibrate(pk, days=0, due=30))
        self.ok(self.status(pk, "IN_SERVICE"))
        self.assertIsNone(self.problem(pk))

    def test_a_status_change_needs_a_reason_and_is_on_the_history(self):
        pk = self.usable_instrument()
        self.refused(self.status(pk, "OUT_OF_SERVICE", " "), "Say why")
        data = self.ok(self.status(pk, "OUT_OF_SERVICE", "Pump leaking"))
        self.assertEqual(data["history"][-1]["comment"], "Pump leaking")
        self.assertEqual(data["history"][-1]["changes"][0]["new"], "Out of service")

    def test_retired_is_final(self):
        pk = self.usable_instrument()
        self.ok(self.status(pk, "RETIRED"))
        self.refused(self.status(pk, "IN_SERVICE"), "cannot go back")
        self.refused(self.calibrate(pk), "retired")
        with self.assertRaises(PermissionError):
            Instrument.objects.get(pk=pk).save()

    def test_a_passing_calibration_needs_a_due_date_and_a_reference(self):
        pk = self.add_instrument()
        self.refused(self.calibrate(pk, due=None), "next calibration is due")
        self.refused(self.calibrate(pk, days=-1, due=-1), "must be due after")
        self.refused(self.calibrate(pk, days=2), "future")
        r = self.post(f"/api/lab/instruments/{pk}/calibrate/", {
            "kind": "CALIBRATION", "outcome": "PASS", "performed_at": self.moment(-1), "next_due": self.day(30),
        })
        self.refused(r, "certificate or logbook number")
        self.assertFalse(CalibrationEvent.objects.exists())

    def test_a_correction_needs_a_reason_and_keeps_the_old_value(self):
        pk = self.add_instrument()
        self.refused(self.post(f"/api/lab/instruments/{pk}/correct/", {"location": "Lab 3"}), "Say why")
        data = self.ok(self.post(f"/api/lab/instruments/{pk}/correct/", {"location": "Lab 3", "comment": "Moved"}))
        change = data["history"][-1]["changes"][0]
        self.assertEqual((change["field"], change["old"], change["new"]), ("Location", "Lab 2", "Lab 3"))
        self.assertEqual(Instrument.objects.get(pk=pk).name, "Agilent 1260")

    def test_the_logbook_is_append_only_and_nothing_is_deleted(self):
        pk = self.usable_instrument()
        event = CalibrationEvent.objects.get()
        event.notes = "Rewritten"
        with self.assertRaises(PermissionError):
            event.save()
        with self.assertRaises(PermissionError):
            event.delete()
        with self.assertRaises(PermissionError):
            Instrument.objects.get(pk=pk).delete()

    def test_the_register_says_what_can_be_used_today(self):
        good = self.usable_instrument("A-1")
        self.add_instrument("B-2")
        rows = self.ok(self.get("/api/lab/instruments/"))["results"]
        self.assertEqual([r["cells"]["usable"]["text"] for r in rows], ["Usable", "Not usable"])
        usable = self.ok(self.get("/api/lab/instruments/?usable=yes"))["results"]
        self.assertEqual([r["id"] for r in usable], [good])
        self.assertEqual(self.get("/api/lab/instruments/?usable=maybe").status_code, 400)

    def test_someone_without_the_permission_sees_no_buttons(self):
        pk = self.usable_instrument()
        self.assertEqual(self.ok(self.get(f"/api/lab/instruments/{pk}/", self.analyst))["actions"], [])
        self.assertTrue(self.ok(self.get(f"/api/lab/instruments/{pk}/", self.approver))["actions"])

    def test_a_bad_body_is_a_refusal_not_a_crash(self):
        self.login(self.approver)
        self.assertEqual(self.client.post("/api/lab/instruments/", ["x"], format="json").status_code, 400)
        r = self.post("/api/lab/instruments/", {"code": 12, "name": 12, "type": 12, "location": 12})
        self.assertEqual(r.status_code, 201, r.content)


class MaterialTests(LabTestBase):
    def problem(self, pk):
        return material_problem(Material.objects.get(pk=pk))

    def correct(self, pk, **body):
        return self.post(f"/api/lab/materials/{pk}/correct/", body)

    def test_each_lot_is_its_own_row(self):
        self.add_material("L-1")
        self.add_material("L-2")
        r = self.post("/api/lab/materials/", {
            "kind": "REAGENT", "code": "rs-pcm", "name": "x", "lot": "l-1", "received_on": self.day(-1),
            "expiry_date": self.day(9),
        })
        self.refused(r, "already on the register")

    def test_a_lot_starts_in_quarantine_unless_said_otherwise(self):
        r = self.ok(self.post("/api/lab/materials/", {
            "kind": "REAGENT", "code": "ACN", "name": "Acetonitrile", "lot": "7", "received_on": self.day(-1),
            "expiry_date": self.day(9),
        }), 201)
        self.assertEqual(r["status"]["text"], "Quarantined")
        self.assertIn("quarantined", self.problem(r["id"]))

    def test_it_can_be_used_on_its_expiry_date_and_not_after(self):
        pk = self.add_material(expiry=0)
        self.assertIsNone(self.problem(pk))
        force_update(Material.objects.filter(pk=pk), expiry_date=timezone.localdate() - timedelta(days=1))
        self.assertIn("expired on", self.problem(pk))

    def test_a_retired_or_quarantined_lot_cannot_be_used(self):
        pk = self.add_material()
        self.ok(self.post(f"/api/lab/materials/{pk}/status/", {"status": "QUARANTINED", "comment": "Seal broken"}))
        self.assertIn("quarantined", self.problem(pk))
        self.ok(self.post(f"/api/lab/materials/{pk}/status/", {"status": "RETIRED", "comment": "Used up"}))
        self.assertIn("retired", self.problem(pk))
        self.refused(self.post(f"/api/lab/materials/{pk}/status/", {"status": "AVAILABLE", "comment": "x"}), "cannot be brought back")

    def test_a_correction_needs_a_reason_and_keeps_the_old_value(self):
        pk = self.add_material()
        self.refused(self.correct(pk, potency="99.5"), "Say why")
        data = self.ok(self.correct(pk, potency="99.5", comment="Certificate misread"))
        change = data["history"][-1]["changes"][0]
        self.assertEqual((change["field"], change["new"]), ("Potency", "99.5"))
        self.assertTrue(change["old"].startswith("99.8"))
        self.assertEqual(Material.objects.get(pk=pk).potency, Decimal("99.5"))
        self.assertTrue(AuditEvent.objects.filter(action="MATERIAL_CORRECTED").exists())

    def test_potency_is_optional_and_a_number(self):
        pk = self.add_material()
        self.refused(self.correct(pk, potency="lots", comment="x"), "Potency")
        self.refused(self.correct(pk, potency="NaN", comment="x"), "Potency")
        self.refused(self.correct(pk, potency="-1", comment="x"), "above zero")
        self.ok(self.correct(pk, potency="", comment="Not assayed"))
        self.assertIsNone(Material.objects.get(pk=pk).potency)

    def test_dates_must_make_sense(self):
        pk = self.add_material()
        self.refused(self.correct(pk, received_on=self.day(1), comment="x"), "future")
        self.refused(self.correct(pk, expiry_date=self.day(-40), comment="x"), "before it was received")
        self.refused(self.correct(pk, opened_on=self.day(-31), comment="x"), "on or after")
        self.refused(self.correct(pk, expiry_date="2026-02-31", comment="x"), "expiry date")

    def test_what_a_result_relied_on_cannot_be_renamed(self):
        pk = self.add_material()
        sample = self.register_sample()
        self.ok(self.enter(sample, value_numeric="99.0", material_ids=[pk]), 201)
        self.refused(self.correct(pk, lot="L-9", comment="Typing mistake"), "named on recorded results")
        self.ok(self.correct(pk, supplier="Sigma", comment="Wrong supplier"))
        used = self.ok(self.get(f"/api/lab/materials/{pk}/"))["tables"][0]["rows"]
        self.assertEqual(used[0]["sample"]["text"], sample.sample_no)

    def test_nothing_is_deleted_and_history_stays(self):
        pk = self.add_material()
        with self.assertRaises(PermissionError):
            Material.objects.get(pk=pk).delete()
        event = RecordEvent.objects.get(register="materials", record_id=pk)
        with self.assertRaises(PermissionError):
            event.save()
        with self.assertRaises(PermissionError):
            event.delete()
