"""The raw data behind a result, and that a caller who sends none of it sees no difference."""
from decimal import Decimal

from django.db import transaction

from audit.models import AuditEvent
from certificates.tests import PW
from lims.models import LimitType, TestDefinition, TestResult
from qclab.testing import force_update, unlocked
from .models import Instrument, Material, ResultReading, ResultRecord
from .rawdata import mean_of
from .test_base import LabTestBase


def replicates(*values):
    return [{"label": f"Replicate {i}", "value": v} for i, v in enumerate(values, start=1)]


class NothingSentTests(LabTestBase):
    def test_a_caller_who_sends_none_of_it_gets_what_they_always_got(self):
        sample = self.register_sample()
        r = self.ok(self.enter(sample, value_numeric="99.5"), 201)
        self.assertIsNone(r["raw_data"])
        self.assertEqual((r["reported"], r["outcome"]), ("99.5", "PASS"))
        self.assertFalse(ResultRecord.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="RESULT_RAW_DATA_RECORDED").exists())

    def test_blanks_from_the_form_count_as_nothing(self):
        sample = self.register_sample()
        self.ok(self.enter(sample, value_numeric="99.5", worksheet_ref=" ", instrument_id="", material_ids=[],
                           readings=[], notes=""), 201)
        self.assertFalse(ResultRecord.objects.exists())


class ReadingTests(LabTestBase):
    def setUp(self):
        super().setUp()
        self.sample = self.register_sample()

    def narrow_test(self):
        """Not more than 5.00, to two places."""
        with unlocked(TestDefinition):
            return TestDefinition.objects.create(
                specification=self.spec, order=5, name="Impurity", unit="%", limit_type=LimitType.NUMERIC_MAX,
                max_value="5.00", decimals=2, limit_text="NMT 5.00 %",
            )

    def test_the_mean_is_worked_out_on_the_server_and_stored(self):
        r = self.ok(self.enter(self.sample, readings=replicates("99.1", "99.2", "99.4")), 201)
        self.assertEqual((r["reported"], r["outcome"]), ("99.2", "PASS"))
        result = TestResult.objects.get(pk=r["id"])
        self.assertEqual(result.value_numeric, Decimal("99.2"))
        self.assertEqual([x.label for x in result.raw_data.readings.all()], ["Replicate 1", "Replicate 2", "Replicate 3"])
        self.assertEqual(r["raw_data"]["mean"], "99.2")

    def test_it_is_exact_decimal_arithmetic(self):
        self.assertEqual(mean_of([Decimal("0.1"), Decimal("0.2")]), Decimal("0.15"))
        r = self.ok(self.enter(self.sample, readings=replicates(0.1, 0.2)), 201)
        self.assertEqual(r["raw_data"]["readings"][0]["value"], "0.1")  # no float noise

    def test_half_way_rounds_up_as_every_other_result_does(self):
        r = self.ok(self.enter(self.sample, readings=replicates("99.10", "99.15")), 201)
        self.assertEqual(r["reported"], "99.1")
        sample = self.register_sample()
        r = self.ok(self.enter(sample, readings=replicates("99.10", "99.20")), 201)
        self.assertEqual(r["reported"], "99.2")  # 99.15

    def test_the_mean_is_rounded_once_so_a_limit_is_not_lost_to_double_rounding(self):
        test = self.narrow_test()
        # 5.0049995: at six places that is 5.005000, which would then round to 5.01 and fail.
        r = self.ok(self.enter(self.sample, test, readings=replicates("5.004999", "5.005000")), 201)
        self.assertEqual((r["reported"], r["outcome"]), ("5.00", "PASS"))

    def test_the_outcome_is_judged_on_the_mean(self):
        r = self.ok(self.enter(self.sample, readings=replicates("90.0", "92.0")), 201)
        self.assertEqual((r["reported"], r["outcome"]), ("91.0", "FAIL"))

    def test_a_value_that_agrees_once_rounded_is_kept_as_entered(self):
        r = self.ok(self.enter(self.sample, value_numeric="99.26", readings=replicates("99.2", "99.3")), 201)
        self.assertEqual(TestResult.objects.get(pk=r["id"]).value_numeric, Decimal("99.26"))

    def test_a_value_that_does_not_agree_is_refused(self):
        r = self.enter(self.sample, value_numeric="99.9", readings=replicates("99.2", "99.3"))
        self.refused(r, "readings average 99.3")
        self.assertEqual(self.sample.results.count(), 0)

    def test_readings_must_be_numbers(self):
        for bad in ("abc", "NaN", "Infinity", "1e99", "1.1234567", True):
            self.assertEqual(self.enter(self.sample, readings=replicates("99", bad)).status_code, 400, bad)
        self.assertEqual(self.sample.results.count(), 0)

    def test_a_reading_needs_a_value_and_the_list_a_shape(self):
        self.refused(self.enter(self.sample, readings=[{"label": "R1"}]), "Enter the value of R1")
        self.refused(self.enter(self.sample, readings="99"), "not valid")
        self.refused(self.enter(self.sample, readings=[99]), "not valid")
        self.refused(self.enter(self.sample, readings=replicates(*["99"] * 101)), "at most 100")

    def test_a_reading_with_no_name_gets_one(self):
        r = self.ok(self.enter(self.sample, readings=[{"value": "99"}]), 201)
        self.assertEqual(r["raw_data"]["readings"][0]["label"], "Reading 1")

    def test_an_observation_takes_no_readings(self):
        self.refused(self.enter(self.sample, self.t_desc, value_text="Complies", readings=replicates("1")), "observation")

    def test_a_written_result_and_readings_cannot_both_stand(self):
        test = self.narrow_test()
        self.refused(self.enter(self.sample, test, value_text="<0.05", readings=replicates("0.01")), "not both")

    def test_with_no_value_and_no_readings_it_is_refused_as_ever(self):
        self.refused(self.enter(self.sample, worksheet_ref="WS-1"), "Enter the value you measured")

    def test_the_mean_can_be_reported_on_a_report_only_test(self):
        with unlocked(TestDefinition):
            test = TestDefinition.objects.create(
                specification=self.spec, order=6, name="Water", limit_type=LimitType.REPORT_ONLY, limit_text="Report",
            )
        r = self.ok(self.enter(self.sample, test, readings=replicates("1.11", "1.22")), 201)
        self.assertEqual((r["reported"], r["outcome"]), ("1.17", "REPORTED"))


class WhatWasUsedTests(LabTestBase):
    def setUp(self):
        super().setUp()
        self.sample = self.register_sample()
        self.instrument = self.usable_instrument()
        self.material = self.add_material()

    def test_all_of_it_is_recorded_with_the_result(self):
        r = self.ok(self.enter(
            self.sample, value_numeric="99.5", worksheet_ref="WS-2026-77", instrument_id=self.instrument,
            material_ids=[self.material], notes="Second injection used", readings=replicates("99.4", "99.6"),
        ), 201)
        raw = r["raw_data"]
        self.assertEqual(raw["worksheet_ref"], "WS-2026-77")
        self.assertEqual(raw["instrument"]["code"], "HPLC-01")
        self.assertEqual(raw["materials"][0]["lot"], "L-1")
        self.assertEqual(raw["notes"], "Second injection used")
        event = AuditEvent.objects.get(action="RESULT_RAW_DATA_RECORDED")
        self.assertEqual(event.details["materials"], ["RS-PCM lot L-1"])

    def test_an_instrument_out_of_date_is_refused_naming_why(self):
        pk = self.add_instrument("OLD-1")
        r = self.enter(self.sample, value_numeric="99.5", instrument_id=pk)
        self.refused(r, "OLD-1 has no passing calibration")
        self.assertEqual(self.sample.results.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action="RESULT_REFUSED_RAW_DATA").exists())

    def test_an_instrument_out_of_service_is_refused(self):
        force_update(Instrument.objects.filter(pk=self.instrument), status="OUT_OF_SERVICE")
        self.refused(self.enter(self.sample, value_numeric="99.5", instrument_id=self.instrument), "out of service")

    def test_a_material_that_cannot_be_used_is_refused_naming_why(self):
        expired = self.add_material("L-2")
        force_update(Material.objects.filter(pk=expired), expiry_date="2020-01-01")
        self.refused(self.enter(self.sample, value_numeric="99.5", material_ids=[self.material, expired]),
                     "L-2 expired on 01-Jan-2020")
        held = self.add_material("L-3", status="QUARANTINED")
        self.refused(self.enter(self.sample, value_numeric="99.5", material_ids=[held]), "L-3 is quarantined")
        self.assertEqual(self.sample.results.count(), 0)

    def test_what_is_not_on_a_register_is_refused(self):
        self.refused(self.enter(self.sample, value_numeric="99.5", instrument_id=99999), "not on the register")
        self.refused(self.enter(self.sample, value_numeric="99.5", instrument_id="abc"), "not on the register")
        self.refused(self.enter(self.sample, value_numeric="99.5", material_ids=[99999]), "not on the register")
        self.refused(self.enter(self.sample, value_numeric="99.5", material_ids="abc"), "not valid")
        self.refused(self.enter(self.sample, value_numeric="99.5", material_ids=[10 ** 30]), "not valid")
        self.refused(self.enter(self.sample, value_numeric="99.5", instrument_id=10 ** 30), "not on the register")

    def test_the_same_material_twice_is_one_material(self):
        r = self.ok(self.enter(self.sample, value_numeric="99.5", material_ids=[self.material, self.material]), 201)
        self.assertEqual(len(r["raw_data"]["materials"]), 1)

    def test_what_can_be_used_is_what_is_offered(self):
        self.add_instrument("OLD-1")
        self.add_material("L-9", status="QUARANTINED")
        data = self.ok(self.get("/api/lab/result-options/", self.analyst))
        self.assertEqual([i["code"] for i in data["instruments"]], ["HPLC-01"])
        self.assertEqual([m["lot"] for m in data["materials"]], ["L-1"])

    def test_a_replacement_has_its_own_raw_data_and_the_old_keeps_its_own(self):
        first = self.ok(self.enter(self.sample, value_numeric="99.5", worksheet_ref="WS-1"), 201)
        second = self.ok(self.enter(self.sample, value_numeric="99.0", worksheet_ref="WS-2",
                                    supersede_reason="Wrong dilution"), 201)
        rows = {r["id"]: r for r in self.ok(self.get(f"/api/samples/{self.sample.id}/"))["results"]}
        self.assertEqual(rows[first["id"]]["raw_data"]["worksheet_ref"], "WS-1")
        self.assertEqual(rows[second["id"]]["raw_data"]["worksheet_ref"], "WS-2")

    def test_the_sample_history_document_carries_it(self):
        self.ok(self.enter(self.sample, worksheet_ref="WS-2026-77", instrument_id=self.instrument,
                           material_ids=[self.material], readings=replicates("99.4", "99.6")), 201)
        doc = self.ok(self.get(f"/api/reports/documents/sample/{self.sample.id}/"))
        testing = next(s for s in doc["sections"] if s["title"].startswith("3."))
        table = next(p for p in testing["parts"] if p.get("heading") == "Raw data behind the results")
        row = table["rows"][0]
        self.assertEqual((row["worksheet"], row["instrument"], row["mean"]), ("WS-2026-77", "HPLC-01", "99.5"))
        self.assertIn("Replicate 1: 99.4", row["readings"])
        self.assertIn("RS-PCM lot L-1", row["materials"])

    def test_the_pdf_of_it_builds(self):
        self.ok(self.enter(self.sample, worksheet_ref="WS-1", readings=replicates("99.4", "99.6")), 201)
        self.login(self.approver)
        r = self.client.get(f"/api/reports/documents/sample/{self.sample.id}/?file=pdf")
        self.assertEqual(r.status_code, 200)

    def test_it_is_append_only(self):
        r = self.ok(self.enter(self.sample, value_numeric="99.5", material_ids=[self.material],
                               readings=replicates("99.5")), 201)
        entry = ResultRecord.objects.get(result_id=r["id"])
        for row in (entry, ResultReading.objects.get(record=entry)):
            with self.assertRaises(PermissionError):
                row.save()
            with self.assertRaises(PermissionError):
                row.delete()
        spare = self.add_material("L-5")
        attempts = [
            lambda: entry.materials.clear(),
            lambda: entry.materials.remove(self.material),
            lambda: entry.materials.add(spare),
            lambda: Material.objects.get(pk=spare).result_records.add(entry),
        ]
        for attempt in attempts:
            with self.assertRaises(PermissionError), transaction.atomic():
                attempt()
        self.assertEqual(entry.materials.count(), 1)


class SignedSampleTests(LabTestBase):
    def test_a_sample_with_raw_data_still_goes_all_the_way_through(self):
        sample = self.register_sample()
        self.ok(self.enter(sample, self.t_desc, value_text="Complies"), 201)
        self.ok(self.enter(sample, worksheet_ref="WS-1", readings=replicates("99.4", "99.6")), 201)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")
        self.ok(r, 201)
        assay = next(t for t in r.data["content"]["tests"] if t["name"] == "Assay")
        self.assertEqual(assay["value"], "99.5")
