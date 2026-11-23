"""
QC stages: set on the product and versioned, bound to each batch when it is created,
passed by its samples or by a QA record, and required before the batch is released.
"""
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from audit.models import AuditEvent
from certificates.tests import PW, due
from lims.models import Sample, SampleStatus
from qclab.testing import force_update
from .models import Batch, BatchDisposition, BatchStageResult, QcStage, QcStagePlan
from .test_disposition import DispositionBase

STAGES = [
    {"name": "Line clearance – manufacturing", "kind": "RECORDED", "required": True},
    {"name": "Final grain", "kind": "TESTED", "required": True, "description": "LOD and assay of the final grain"},
    {"name": "Retained sample check", "kind": "RECORDED", "required": False},
]


class StageBase(DispositionBase):
    def put_stages(self, rows=None, reason="Stages from the batch record", user=None):
        self.login(user or self.admin)
        return self.client.put(f"/api/products/{self.product.id}/qc-stages/",
                               {"stages": STAGES if rows is None else rows, "reason": reason}, format="json")

    def set_up_stages(self, rows=None):
        r = self.put_stages(rows)
        self.assertEqual(r.status_code, 200, r.content)
        return {s["name"]: s["id"] for s in r.data["current"]["stages"]}

    def register(self, stage_id=None, batch_no="B-001"):
        self.login(self.frontdesk)
        body = {
            "product_id": self.product.id, "batch_no": batch_no, "quantity": "150 g",
            "received_from": "Production", "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": self.analyst.id,
        }
        if stage_id is not None:
            body["qc_stage_id"] = stage_id
        return self.client.post("/api/samples/", body, format="json")

    def registered(self, stage_id, batch_no="B-001"):
        r = self.register(stage_id, batch_no)
        self.assertEqual(r.status_code, 201, r.content)
        return Sample.objects.get(pk=r.data["id"])

    def released(self, sample):
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        sample.refresh_from_db()
        return sample

    def record(self, batch_id, stage_id, decision="PASSED", remarks="", user=None, password=PW):
        self.login(user or self.approver)
        return self.client.post(f"/api/batches/{batch_id}/qc-stages/{stage_id}/record/", {
            "decision": decision, "remarks": remarks, "password": password,
        }, format="json")

    def stages_of(self, batch_id, user=None):
        self.login(user or self.approver)
        return self.client.get(f"/api/batches/{batch_id}/").data["qc_stages"]

    def status_of(self, batch_id, name):
        return next(s["status"] for s in self.stages_of(batch_id)["stages"] if s["name"] == name)


class ProductStagesTests(StageBase):
    def test_saving_makes_a_version_and_keeps_every_earlier_one(self):
        self.set_up_stages()
        r = self.put_stages(STAGES[:2], reason="The retained sample check is done elsewhere")
        self.assertEqual(r.data["current"]["version"], 2)
        self.assertEqual([v["version"] for v in r.data["versions"]], [2, 1])
        first = QcStagePlan.objects.get(product=self.product, version=1)
        self.assertEqual(first.stages.count(), 3)
        self.assertEqual([s["order"] for s in r.data["current"]["stages"]], [1, 2])

    def test_unchanged_stages_make_no_new_version(self):
        self.set_up_stages()
        r = self.put_stages(reason="")
        self.assertEqual((r.status_code, r.data["current"]["version"]), (200, 1))
        self.assertEqual(QcStagePlan.objects.filter(product=self.product).count(), 1)

    def test_a_change_needs_a_reason(self):
        r = self.put_stages(reason="  ")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Say why", r.data["detail"])

    def test_bad_stages_are_refused_in_plain_words(self):
        for rows, words in (
            ([{"name": " ", "kind": "TESTED"}], "needs a name"),
            ([{"name": "Final grain", "kind": "TESTED"}, {"name": "final grain", "kind": "RECORDED"}], "Two stages"),
            ([{"name": "Final grain", "kind": "SOMETIMES"}], "tested in the lab or recorded by QA"),
        ):
            r = self.put_stages(rows)
            self.assertEqual(r.status_code, 400, rows)
            self.assertIn(words, r.data["detail"])

    def test_it_takes_the_product_master_permission(self):
        r = self.put_stages(user=self.approver)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(QcStagePlan.objects.exists())

    def test_the_change_is_in_the_activity_log(self):
        self.set_up_stages()
        event = AuditEvent.objects.get(action="QC_STAGES_CHANGED")
        self.assertEqual((event.actor_username, event.details["version"]), ("sysadmin", 1))
        self.assertIn("Retained sample check (optional)", event.details["stages"])


class BatchBindingTests(StageBase):
    def test_a_new_batch_gets_the_products_stages(self):
        ids = self.set_up_stages()
        batch = self.registered(ids["Final grain"]).batch
        self.assertEqual(batch.stage_plan.version, 1)
        payload = self.stages_of(batch.id)
        self.assertEqual([s["name"] for s in payload["stages"]], [s["name"] for s in STAGES])
        self.assertEqual((payload["required"], payload["passed"]), (2, 0))

    def test_a_later_change_never_reaches_a_batch_already_created(self):
        ids = self.set_up_stages()
        first = self.registered(ids["Final grain"]).batch
        new_ids = self.set_up_stages(STAGES[1:])
        second = self.registered(new_ids["Final grain"], batch_no="B-002").batch
        first.refresh_from_db()
        self.assertEqual((first.stage_plan.version, second.stage_plan.version), (1, 2))
        self.assertEqual(len(self.stages_of(first.id)["stages"]), 3)
        self.assertEqual(len(self.stages_of(second.id)["stages"]), 2)

    def test_every_new_batch_goes_through_the_stages_again(self):
        ids = self.set_up_stages()
        first = self.registered(ids["Final grain"]).batch
        second = self.registered(ids["Final grain"], batch_no="B-002").batch
        self.assertEqual(self.record(first.id, ids["Line clearance – manufacturing"]).status_code, 200)
        self.assertEqual(self.status_of(first.id, "Line clearance – manufacturing"), "PASSED")
        self.assertEqual(self.status_of(second.id, "Line clearance – manufacturing"), "NOT_STARTED")

    def test_a_batch_from_before_the_stages_has_none_and_is_released_as_before(self):
        sample = self.released_sample()
        self.set_up_stages()
        # Nothing to show to someone who cannot add a stage; QA sees none, and may add one for this batch.
        self.assertIsNone(self.stages_of(sample.batch_id, user=self.analyst))
        self.assertEqual(self.stages_of(sample.batch_id)["stages"], [])
        self.assertEqual(self.decide(sample.batch_id).status_code, 200)


class RegistrationTests(StageBase):
    def test_the_stage_must_be_chosen(self):
        self.set_up_stages()
        r = self.register()
        self.assertEqual(r.status_code, 400)
        self.assertIn("Choose which QC stage", str(r.data["qc_stage_id"]))
        self.assertFalse(Batch.objects.exists())

    def test_a_stage_recorded_by_qa_is_not_offered_for_a_sample(self):
        ids = self.set_up_stages()
        r = self.register(ids["Line clearance – manufacturing"])
        self.assertEqual(r.status_code, 400)

    def test_a_known_batch_keeps_its_own_stages(self):
        ids = self.set_up_stages()
        self.registered(ids["Final grain"])
        new_ids = self.set_up_stages(STAGES[1:])
        self.assertEqual(self.register(new_ids["Final grain"]).status_code, 400)
        self.assertEqual(self.register(ids["Final grain"]).status_code, 201)

    def test_a_product_without_stages_needs_none(self):
        self.assertEqual(self.register().status_code, 201)

    def test_the_sample_shows_its_stage(self):
        ids = self.set_up_stages()
        sample = self.registered(ids["Final grain"])
        self.login(self.approver)
        self.assertEqual(self.client.get(f"/api/samples/{sample.id}/").data["qc_stage_name"], "Final grain")
        event = AuditEvent.objects.get(action="SAMPLE_REGISTERED")
        self.assertEqual(event.details["qc_stage"], "Final grain")


class StatusTests(StageBase):
    def test_a_tested_stage_moves_with_its_samples(self):
        ids = self.set_up_stages()
        sample = self.registered(ids["Final grain"])
        self.assertEqual(self.status_of(sample.batch_id, "Final grain"), "IN_PROGRESS")
        self.released(sample)
        self.assertEqual(self.status_of(sample.batch_id, "Final grain"), "PASSED")

    def test_a_rejected_sample_fails_its_stage(self):
        ids = self.set_up_stages()
        sample = self.registered(ids["Final grain"])
        force_update(Sample.objects.filter(pk=sample.pk), status=SampleStatus.REJECTED)
        self.assertEqual(self.status_of(sample.batch_id, "Final grain"), "FAILED")

    def test_a_cancelled_sample_does_not_count(self):
        ids = self.set_up_stages()
        sample = self.registered(ids["Final grain"])
        force_update(Sample.objects.filter(pk=sample.pk), status=SampleStatus.CANCELLED)
        self.assertEqual(self.status_of(sample.batch_id, "Final grain"), "NOT_STARTED")

    def test_a_recorded_stage_can_be_done_again_and_the_latest_counts(self):
        ids = self.set_up_stages()
        batch_id = self.registered(ids["Final grain"]).batch_id
        clearance = ids["Line clearance – manufacturing"]
        self.assertEqual(self.record(batch_id, clearance, "FAILED", "Previous batch label found").status_code, 200)
        self.assertEqual(self.status_of(batch_id, "Line clearance – manufacturing"), "FAILED")
        self.assertEqual(self.record(batch_id, clearance, "PASSED", "Re-line clearance").status_code, 200)
        row = next(s for s in self.stages_of(batch_id)["stages"] if s["id"] == clearance)
        self.assertEqual(row["status"], "PASSED")
        self.assertEqual([r["label"] for r in row["records"]], ["Passed", "Failed"])


class RecordingTests(StageBase):
    def setUp(self):
        super().setUp()
        self.ids = self.set_up_stages()
        self.batch_id = self.registered(self.ids["Final grain"]).batch_id
        self.clearance = self.ids["Line clearance – manufacturing"]

    def test_it_takes_the_permission(self):
        r = self.record(self.batch_id, self.clearance, user=self.checker)
        self.assertEqual(r.status_code, 400)
        self.assertIn("permission", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="ACCESS_REFUSED").exists())
        self.assertFalse(BatchStageResult.objects.exists())

    def test_a_wrong_password_records_nothing(self):
        r = self.record(self.batch_id, self.clearance, password="wrong")
        self.assertIn("Password incorrect", r.data["detail"])
        self.assertFalse(BatchStageResult.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED").exists())

    def test_a_failure_needs_remarks(self):
        r = self.record(self.batch_id, self.clearance, "FAILED", "")
        self.assertIn("Say why the stage failed", r.data["detail"])

    def test_a_stage_tested_in_the_lab_is_not_recorded_by_hand(self):
        r = self.record(self.batch_id, self.ids["Final grain"])
        self.assertIn("passes when its samples are approved", r.data["detail"])

    def test_nothing_changes_once_the_batch_is_decided(self):
        self.assertEqual(self.decide(self.batch_id, "REJECTED", reason="Line clearance failed").status_code, 200)
        r = self.record(self.batch_id, self.clearance)
        self.assertIn("has been rejected", r.data["detail"])
        self.assertFalse(self.stages_of(self.batch_id)["can_record"])

    def test_the_record_is_signed_in_the_activity_log(self):
        self.record(self.batch_id, self.clearance, remarks="Area clean, 24 °C, 42 % RH")
        event = AuditEvent.objects.get(action="BATCH_STAGE_RECORDED")
        self.assertEqual((event.actor_username, event.details["decision"]), ("labhead", "passed"))


class StrictReleaseTests(StageBase):
    def test_release_waits_for_every_required_stage_and_never_for_an_optional_one(self):
        ids = self.set_up_stages()
        sample = self.released(self.registered(ids["Final grain"]))
        r = self.decide(sample.batch_id)
        self.refused(r, "Line clearance – manufacturing, has not passed (not started)")
        self.assertNotIn("Retained sample check", r.data["detail"])
        self.assertEqual(self.record(sample.batch_id, ids["Line clearance – manufacturing"]).status_code, 200)
        r = self.decide(sample.batch_id)
        self.assertEqual(r.status_code, 200, r.content)
        basis = BatchDisposition.objects.get().basis["qc_stages"]
        self.assertEqual([s["status"] for s in basis], ["PASSED", "PASSED", "NOT_STARTED"])

    def test_a_failed_required_stage_stops_release(self):
        ids = self.set_up_stages()
        sample = self.released(self.registered(ids["Final grain"]))
        self.record(sample.batch_id, ids["Line clearance – manufacturing"], "FAILED", "Previous product found")
        self.refused(self.decide(sample.batch_id), "has not passed (failed)")

    def test_the_problems_are_listed_for_who_decides(self):
        ids = self.set_up_stages()
        batch_id = self.registered(ids["Final grain"]).batch_id
        self.login(self.approver)
        problems = " ".join(self.client.get(f"/api/batches/{batch_id}/").data["disposition"]["release_problems"])
        self.assertIn("QC stage 1, Line clearance – manufacturing, has not passed", problems)
        self.assertIn("QC stage 2, Final grain, has not passed (in progress)", problems)


class DatabaseLockTests(StageBase):
    def refused_sql(self, sql):
        if connection.vendor != "postgresql":
            self.skipTest("The locks are PostgreSQL triggers.")
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)

    def test_a_version_of_the_stages_cannot_be_rewritten_or_deleted(self):
        self.set_up_stages()
        stage = QcStage.objects.first()
        self.refused_sql(f"UPDATE batches_qcstage SET required = false WHERE id = {stage.id}")
        self.refused_sql(f"DELETE FROM batches_qcstage WHERE id = {stage.id}")

    def test_a_stage_result_cannot_be_rewritten(self):
        ids = self.set_up_stages()
        batch_id = self.registered(ids["Final grain"]).batch_id
        self.record(batch_id, ids["Line clearance – manufacturing"], "FAILED", "Dust on the granulator")
        result = BatchStageResult.objects.get()
        self.refused_sql(f"UPDATE batches_batchstageresult SET decision = 'PASSED' WHERE id = {result.id}")

    def test_a_batch_keeps_its_stages_and_a_sample_its_stage(self):
        ids = self.set_up_stages()
        sample = self.registered(ids["Final grain"])
        self.set_up_stages(STAGES[1:])
        newer = QcStagePlan.objects.get(version=2)
        self.refused_sql(f"UPDATE batches_batch SET stage_plan_id = {newer.id} WHERE id = {sample.batch_id}")
        other = newer.stages.first()
        self.refused_sql(f"UPDATE lims_sample SET qc_stage_id = {other.id} WHERE id = {sample.id}")
