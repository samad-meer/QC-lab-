"""
QC stages refined: each lab-tested stage can have its own tests, a stage can wait
for the ones before it, and QA can make a stage not apply to one batch, or add a
stage to one batch alone. Signed, with reasons, and the product's stages untouched.
"""
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext

from audit.describe import describe
from audit.models import AuditEvent
from certificates.models import Certificate
from certificates.tests import PW
from lims.models import Sample, SpecStatus, Specification
from .models import Batch, BatchStageApplicability, QcStage, QcStagePlan
from .services import disposition_basis, release_problems
from .test_qc_stages import StageBase

LINE = {"name": "Line clearance", "kind": "RECORDED", "required": True}
GRAIN = {"name": "Final grain", "kind": "TESTED", "required": True}
FINISHED = {"name": "Finished product", "kind": "TESTED", "required": True}

LOD = {"name": "Loss on drying", "unit": "%", "limit_type": "NUMERIC_MAX", "max_value": "3.0", "decimals": 1,
       "limit_text": "NMT 3.0 %"}


class RefinedBase(StageBase):
    def stage_tests(self, key="final grain", tests=(LOD,)):
        """Draft a stage's own tests as the administrator and have the lab head make them effective."""
        self.login(self.admin)
        r = self.client.post(f"/api/products/{self.product.id}/specifications/",
                             {"reason": "In-process limits from the batch record", "stage": key}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        draft = next(s for s in r.data["specifications"] if s["status"] == "DRAFT")
        r = self.client.put(f"/api/specifications/{draft['id']}/", {"tests": list(tests)}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        draft = next(s for s in r.data["specifications"] if s["status"] == "DRAFT")
        self.login(self.approver)
        r = self.client.post(f"/api/specifications/{draft['id']}/approve/",
                             {"digest": draft["digest"], "password": PW}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return Specification.objects.get(pk=draft["id"])

    def new_batch(self, number="B-001"):
        self.login(self.frontdesk)
        r = self.client.post("/api/batches/", {"product_id": self.product.id, "official_batch_no": number},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return Batch.objects.get(pk=r.data["id"])

    def release_on_own_tests(self, sample, value="1.2"):
        """Enter every test of the sample's own specification, then sign it through."""
        self.login(self.analyst)
        for t in sample.specification.tests.all():
            r = self.client.post(f"/api/samples/{sample.id}/results/",
                                 {"test_definition_id": t.id, "value_numeric": value}, format="json")
            self.assertEqual(r.status_code, 201, r.content)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        sample.refresh_from_db()
        return cert

    def mark(self, batch_id, stage_id, applies=False, reason="Campaign batch, same product on the same line",
             user=None, password=PW):
        self.login(user or self.approver)
        return self.client.post(f"/api/batches/{batch_id}/qc-stages/{stage_id}/applicability/",
                                {"applies": applies, "reason": reason, "password": password}, format="json")

    def add(self, batch_id, user=None, password=PW, **fields):
        body = {"name": "Re-test after re-blending", "kind": "TESTED", "tests": "", "required": True,
                "reason": "Reprocessed under deviation DEV-2026-0012", **fields, "password": password}
        self.login(user or self.approver)
        return self.client.post(f"/api/batches/{batch_id}/qc-stages/", body, format="json")

    def stage(self, batch_id, name):
        return next(s for s in self.stages_of(batch_id)["stages"] if s["name"] == name)


class TestsPerStageTests(RefinedBase):
    def test_a_stage_without_tests_of_its_own_uses_the_products_specification(self):
        ids = self.set_up_stages([GRAIN, FINISHED])
        sample = self.registered(ids["Final grain"])
        self.assertEqual(sample.specification, self.spec)

    def test_a_stage_with_its_own_tests_in_force_gets_them_and_the_rest_do_not(self):
        ids = self.set_up_stages([GRAIN, FINISHED])
        own = self.stage_tests()
        grain = self.registered(ids["Final grain"])
        finished = self.registered(ids["Finished product"])
        self.assertEqual(grain.specification, own)
        self.assertEqual([t.name for t in grain.specification.tests.all()], ["Loss on drying"])
        self.assertEqual(finished.specification, self.spec)
        # The product's own specification is untouched, and the stage's tests count their own versions.
        self.assertEqual(self.product.current_specification(), self.spec)
        self.assertEqual((own.version, own.stage_key, own.stage_name), (1, "final grain", "Final grain"))
        self.login(self.approver)
        detail = self.client.get(f"/api/samples/{grain.id}/").data
        self.assertEqual(detail["specification"]["label"], "Final grain tests, version 1")

    def test_a_draft_is_not_used_until_it_is_made_effective(self):
        ids = self.set_up_stages([GRAIN])
        self.login(self.admin)
        self.client.post(f"/api/products/{self.product.id}/specifications/",
                         {"reason": "In-process limits", "stage": "final grain"}, format="json")
        self.assertEqual(self.registered(ids["Final grain"]).specification, self.spec)

    def test_a_new_version_of_a_stages_tests_replaces_only_its_own(self):
        self.set_up_stages([GRAIN])
        first = self.stage_tests()
        second = self.stage_tests(tests=(LOD, {**LOD, "name": "Bulk density", "unit": "g/ml", "max_value": "0.8",
                                               "limit_text": "NMT 0.8 g/ml"}))
        first.refresh_from_db()
        self.spec.refresh_from_db()
        self.assertEqual((first.status, second.status, second.version), (SpecStatus.SUPERSEDED, SpecStatus.EFFECTIVE, 2))
        self.assertEqual(self.spec.status, SpecStatus.EFFECTIVE)

    def test_a_renamed_stage_keeps_its_tests(self):
        self.set_up_stages([GRAIN])
        own = self.stage_tests()
        self.login(self.admin)
        current = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data["current"]["stages"]
        rows = [{**GRAIN, "name": "Final granules", "key": current[0]["key"]}]
        ids = self.set_up_stages(rows)
        self.assertEqual(self.registered(ids["Final granules"]).specification, own)

    def test_the_front_desk_and_product_page_say_which_tests(self):
        self.set_up_stages([GRAIN, FINISHED])
        self.stage_tests()
        self.login(self.frontdesk)
        products = self.client.get("/api/products/?section=GF").data
        options = next(p for p in products if p["id"] == self.product.id)["qc_stages"]
        self.assertEqual([o["tests"] for o in options], ["Final grain tests, version 1", "Specification, version 1"])
        self.login(self.admin)
        stages = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data["current"]["stages"]
        self.assertEqual(stages[0]["own_tests"], {"version": 1, "draft": False})
        self.assertEqual(stages[1]["own_tests"], {"version": None, "draft": False})
        # The product page shows each stage's tests inside it: its own, or the product's.
        self.assertEqual((stages[0]["tests"]["label"], stages[0]["tests"]["own"]), ("Final grain tests, version 1", True))
        self.assertEqual([t["name"] for t in stages[0]["tests"]["tests"]], ["Loss on drying"])
        self.assertEqual((stages[1]["tests"]["label"], stages[1]["tests"]["own"]), ("Specification, version 1", False))
        product_stages = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data
        self.assertEqual([t["name"] for t in product_stages["product_spec"]["tests"]], ["Description", "Assay"])
        self.assertTrue(product_stages["can_spec"])
        tracks = self.client.get(f"/api/products/{self.product.id}/specifications/").data["tracks"]
        self.assertEqual([(t["key"], t["effective_version"]) for t in tracks],
                         [("", 1), ("final grain", 1), ("finished product", None)])

    def test_only_a_lab_tested_stage_has_tests(self):
        self.set_up_stages([LINE, GRAIN])
        self.login(self.admin)
        for key in ("line clearance", "no such stage"):
            r = self.client.post(f"/api/products/{self.product.id}/specifications/",
                                 {"reason": "x", "stage": key}, format="json")
            self.assertEqual(r.status_code, 400, key)

    def test_the_certificate_names_the_stage_and_its_tests(self):
        ids = self.set_up_stages([GRAIN])
        self.stage_tests()
        sample = self.registered(ids["Final grain"])
        cert = self.release_on_own_tests(sample)
        cert = Certificate.objects.filter(sample=sample).order_by("-version").first()
        self.assertEqual((cert.content["qc_stage"], cert.content["spec_of_stage"]), ("Final grain", "Final grain"))
        self.assertEqual(self.status_of(sample.batch_id, "Final grain"), "PASSED")

    def test_an_approved_stage_specification_cannot_be_moved_to_another_stage(self):
        if connection.vendor != "postgresql":
            self.skipTest("The locks are PostgreSQL triggers.")
        self.set_up_stages([GRAIN])
        own = self.stage_tests()
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"UPDATE lims_specification SET stage_key = '' WHERE id = {own.id}")


class StageOrderTests(RefinedBase):
    WAITING = [LINE, {**GRAIN, "after_previous": True}]

    def test_a_waiting_stage_takes_no_sample_until_the_ones_before_it_pass(self):
        ids = self.set_up_stages(self.WAITING)
        batch = self.new_batch()
        r = self.register(ids["Final grain"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Final grain waits for the stages before it, and 1. Line clearance has not passed yet",
                      str(r.data["qc_stage_id"]))
        self.assertFalse(Sample.objects.exists())
        self.assertEqual(self.stage(batch.id, "Final grain")["waiting_for"], ["1. Line clearance"])
        self.assertEqual(self.record(batch.id, ids["Line clearance"]).status_code, 200)
        self.assertEqual(self.register(ids["Final grain"]).status_code, 201)
        self.assertEqual(self.stage(batch.id, "Final grain")["waiting_for"], [])

    def test_a_new_batch_cannot_start_on_a_waiting_stage(self):
        ids = self.set_up_stages(self.WAITING)
        r = self.register(ids["Final grain"], batch_no="B-NEW")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Batch.objects.filter(official_batch_no="B-NEW").exists())

    def test_recording_a_waiting_stage_is_refused_too(self):
        ids = self.set_up_stages([GRAIN, {**LINE, "name": "Line clearance – compression", "after_previous": True}])
        sample = self.registered(ids["Final grain"])
        r = self.record(sample.batch_id, ids["Line clearance – compression"])
        self.refused(r, "waits for the stages before it, and 1. Final grain has not passed yet")
        self.released(sample)
        self.assertEqual(self.record(sample.batch_id, ids["Line clearance – compression"]).status_code, 200)

    def test_an_optional_or_not_applicable_stage_is_not_waited_for(self):
        ids = self.set_up_stages([{**LINE, "required": False}, {**GRAIN, "after_previous": True}])
        self.new_batch()
        self.assertEqual(self.register(ids["Final grain"]).status_code, 201)

        ids = self.set_up_stages([LINE, {**FINISHED, "after_previous": True}])
        batch = self.new_batch("B-002")
        self.assertEqual(self.mark(batch.id, ids["Line clearance"]).status_code, 200)
        self.assertEqual(self.register(ids["Finished product"], batch_no="B-002").status_code, 201)

    def test_the_first_stage_never_waits(self):
        self.set_up_stages([{**GRAIN, "after_previous": True}, {**FINISHED, "after_previous": True}])
        stages = list(QcStage.objects.order_by("order"))
        self.assertEqual([s.after_previous for s in stages], [False, True])

    def test_the_front_desk_sees_what_a_stage_waits_for(self):
        self.set_up_stages(self.WAITING)
        self.new_batch()
        self.login(self.frontdesk)
        batch = self.client.get(f"/api/batches/lookup/?product={self.product.id}&official_no=B-001").data["batch"]
        self.assertEqual(batch["stage_options"][0]["waiting_for"], ["1. Line clearance"])


class NotApplicableTests(RefinedBase):
    def test_qa_sets_a_stage_aside_and_release_stops_waiting_for_it(self):
        ids = self.set_up_stages([LINE, GRAIN])
        sample = self.released(self.registered(ids["Final grain"]))
        self.assertTrue(any("Line clearance" in p for p in release_problems(sample.batch)))
        r = self.mark(sample.batch_id, ids["Line clearance"])
        self.assertEqual(r.status_code, 200, r.content)
        line = self.stage(sample.batch_id, "Line clearance")
        self.assertEqual((line["status"], line["status_label"]), ("NOT_APPLICABLE", "Not applicable"))
        self.assertEqual(self.stages_of(sample.batch_id)["required"], 1)
        self.assertEqual(release_problems(sample.batch), [])
        self.assertEqual(self.decide(sample.batch_id).status_code, 200)
        basis = disposition_basis(sample.batch)
        self.assertEqual(basis["qc_stages"][0]["status"], "NOT_APPLICABLE")

    def test_only_a_stage_nothing_has_been_done_for_can_be_set_aside(self):
        ids = self.set_up_stages([LINE, GRAIN])
        sample = self.registered(ids["Final grain"])
        self.refused(self.mark(sample.batch_id, ids["Final grain"]), "Only a stage nothing has been done for")
        self.record(sample.batch_id, ids["Line clearance"], decision="FAILED", remarks="Residue of the previous batch")
        self.refused(self.mark(sample.batch_id, ids["Line clearance"]), "(failed)")
        self.assertFalse(BatchStageApplicability.objects.exists())

    def test_it_is_signed_with_a_reason_by_someone_who_may(self):
        ids = self.set_up_stages([LINE, GRAIN])
        batch = self.new_batch()
        self.refused(self.mark(batch.id, ids["Line clearance"], reason="  "), "Say why")
        self.refused(self.mark(batch.id, ids["Line clearance"], password="wrong"), "Password incorrect")
        self.refused(self.mark(batch.id, ids["Line clearance"], user=self.checker), "permission")
        self.assertFalse(BatchStageApplicability.objects.exists())

    def test_it_can_apply_again_and_both_stay_on_the_record(self):
        ids = self.set_up_stages([LINE, GRAIN])
        batch = self.new_batch()
        self.mark(batch.id, ids["Line clearance"])
        r = self.mark(batch.id, ids["Line clearance"], applies=True, reason="Marked by mistake")
        self.assertEqual(r.status_code, 200, r.content)
        line = self.stage(batch.id, "Line clearance")
        self.assertEqual(line["status"], "NOT_STARTED")
        self.assertEqual([m["applies"] for m in line["applicability"]], [True, False])
        sentences = [describe(e)["sentence"] for e in AuditEvent.objects.filter(action__startswith="BATCH_STAGE_")]
        self.assertTrue(any("not applicable to batch" in s for s in sentences), sentences)
        self.assertTrue(any("applies to batch" in s and "after all" in s for s in sentences), sentences)

    def test_a_stage_that_does_not_apply_takes_no_sample_and_no_record(self):
        ids = self.set_up_stages([LINE, GRAIN, FINISHED])
        batch = self.new_batch()
        self.mark(batch.id, ids["Line clearance"])
        self.mark(batch.id, ids["Final grain"])
        self.refused(self.record(batch.id, ids["Line clearance"]), "does not apply to this batch")
        r = self.register(ids["Final grain"])
        self.assertEqual(r.status_code, 400)
        self.login(self.frontdesk)
        options = self.client.get(f"/api/batches/lookup/?product={self.product.id}&official_no=B-001").data
        self.assertEqual([o["name"] for o in options["batch"]["stage_options"]], ["Finished product"])

    def test_nothing_changes_once_the_batch_is_decided(self):
        ids = self.set_up_stages([GRAIN, {**LINE, "required": False}])
        sample = self.released(self.registered(ids["Final grain"]))
        self.assertEqual(self.decide(sample.batch_id).status_code, 200)
        self.refused(self.mark(sample.batch_id, ids["Line clearance"]), "has been released")
        self.refused(self.add(sample.batch_id), "has been released")

    def test_the_records_are_never_changed(self):
        if connection.vendor != "postgresql":
            self.skipTest("The locks are PostgreSQL triggers.")
        ids = self.set_up_stages([LINE, GRAIN])
        batch = self.new_batch()
        self.mark(batch.id, ids["Line clearance"])
        mark = BatchStageApplicability.objects.get()
        for sql in (f"UPDATE batches_batchstageapplicability SET applies = true WHERE id = {mark.id}",
                    f"DELETE FROM batches_batchstageapplicability WHERE id = {mark.id}"):
            with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql)


class AddedStageTests(RefinedBase):
    def test_qa_adds_a_stage_to_one_batch_only(self):
        ids = self.set_up_stages([GRAIN])
        first = self.registered(ids["Final grain"]).batch
        other = self.new_batch("B-002")
        r = self.add(first.id)
        self.assertEqual(r.status_code, 200, r.content)
        added = self.stage(first.id, "Re-test after re-blending")
        self.assertEqual((added["order"], added["added_to_batch"], added["added_reason"]),
                         (2, True, "Reprocessed under deviation DEV-2026-0012"))
        self.assertEqual([s["name"] for s in self.stages_of(other.id)["stages"]], ["Final grain"])
        self.assertEqual(QcStagePlan.objects.filter(product=self.product).count(), 1)
        self.login(self.admin)
        product_stages = self.client.get(f"/api/products/{self.product.id}/qc-stages/").data
        self.assertEqual(len(product_stages["current"]["stages"]), 1)
        self.assertEqual(product_stages["versions"][0]["stage_count"], 1)
        event = AuditEvent.objects.get(action="BATCH_STAGE_ADDED")
        self.assertIn("added QC stage “Re-test after re-blending”", describe(event)["sentence"])

    def test_an_added_required_stage_holds_release_until_it_passes(self):
        ids = self.set_up_stages([GRAIN])
        sample = self.released(self.registered(ids["Final grain"]))
        self.add(sample.batch_id, name="Second line clearance", kind="RECORDED")
        self.assertTrue(any("Second line clearance" in p for p in release_problems(sample.batch)))
        added = self.stage(sample.batch_id, "Second line clearance")
        self.assertEqual(self.record(sample.batch_id, added["id"]).status_code, 200)
        self.assertEqual(release_problems(sample.batch), [])
        self.assertEqual(disposition_basis(sample.batch)["qc_stages"][-1]["added_to_batch"], True)

    def test_a_sample_for_an_added_stage_gets_the_tests_chosen_for_it(self):
        ids = self.set_up_stages([GRAIN, FINISHED])
        own = self.stage_tests()
        batch = self.registered(ids["Finished product"]).batch
        self.assertEqual(self.add(batch.id, tests="final grain").status_code, 200)
        added = self.stage(batch.id, "Re-test after re-blending")
        self.assertEqual(added["tests"], "Final grain tests, version 1")
        self.assertEqual(self.registered(added["id"]).specification, own)

    def test_a_bad_stage_is_refused_in_plain_words(self):
        ids = self.set_up_stages([GRAIN])
        batch = self.registered(ids["Final grain"]).batch
        self.refused(self.add(batch.id, name="final GRAIN"), "already has a stage called")
        self.refused(self.add(batch.id, name=" "), "Give the stage a name")
        self.refused(self.add(batch.id, reason=""), "Say why this batch needs the stage")
        self.refused(self.add(batch.id, tests="no such tests"), "Choose which tests")
        self.refused(self.add(batch.id, password="wrong"), "Password incorrect")
        self.refused(self.add(batch.id, user=self.frontdesk), "permission")
        self.assertFalse(QcStage.objects.filter(batch=batch).exists())

    def test_a_batch_without_product_stages_can_have_one_added(self):
        sample = self.register_sample()
        self.assertIsNone(self.stages_of(sample.batch_id, user=self.analyst))
        self.assertEqual(self.stages_of(sample.batch_id)["stages"], [])
        self.assertEqual(self.add(sample.batch_id, kind="RECORDED", name="Line clearance").status_code, 200)
        view = self.stages_of(sample.batch_id)
        self.assertEqual((view["version"], [s["name"] for s in view["stages"]]), (None, ["Line clearance"]))


class BatchListTests(RefinedBase):
    def test_the_list_and_its_export_show_where_the_stages_stand(self):
        ids = self.set_up_stages([LINE, GRAIN])
        sample = self.released(self.registered(ids["Final grain"]))
        self.login(self.approver)
        row = self.client.get("/api/batches/").data["results"][0]
        self.assertEqual(row["qc_progress"], {"passed": 1, "required": 2, "failed": False})
        self.record(sample.batch_id, ids["Line clearance"], decision="FAILED", remarks="Residue found")
        row = self.client.get("/api/batches/").data["results"][0]
        self.assertTrue(row["qc_progress"]["failed"])
        self.assertEqual(self.client.get("/api/batches/?file=xlsx").status_code, 200)

    def test_a_page_of_batches_is_judged_as_each_batch_alone_would_be(self):
        """The list works out the stages of all its batches together, and must agree with each worked out alone."""
        from .stages import progress, progress_many

        before = self.register_sample().batch  # made before the product had stages: none to show
        ids = self.set_up_stages([LINE, GRAIN])
        passed = self.released(self.registered(ids["Final grain"], batch_no="B-002")).batch
        failed = self.registered(ids["Final grain"], batch_no="B-003").batch
        self.assertEqual(self.record(failed.id, ids["Line clearance"], decision="FAILED",
                                     remarks="Residue found").status_code, 200)
        skipped = self.registered(ids["Final grain"], batch_no="B-004").batch
        self.assertEqual(self.mark(skipped.id, ids["Line clearance"]).status_code, 200)
        added = self.registered(ids["Final grain"], batch_no="B-005").batch
        self.assertEqual(self.add(added.id).status_code, 200)

        batches = list(Batch.objects.all())
        found = progress_many(batches)
        self.assertEqual(found, {b.pk: progress(b) for b in batches})
        self.assertIsNone(found[before.pk])
        self.assertEqual(found[passed.pk], {"passed": 1, "required": 2, "failed": False})
        self.assertTrue(found[failed.pk]["failed"])
        self.assertEqual(found[skipped.pk]["required"], 1, "a stage that does not apply is not counted")
        self.assertEqual(found[added.pk]["required"], 3, "a stage added to the batch is counted")

    def test_the_list_takes_as_many_queries_for_many_batches_as_for_one(self):
        from .stages import progress_many

        ids = self.set_up_stages([LINE, GRAIN])
        self.registered(ids["Final grain"], batch_no="B-001")

        def queries():
            with CaptureQueriesContext(connection) as q:
                progress_many(Batch.objects.all())
            return len(q)

        one = queries()
        for n in range(2, 7):
            self.registered(ids["Final grain"], batch_no=f"B-00{n}")
        self.assertEqual(queries(), one)
        # The whole page stays small too: the batches and their count, their stages, the person asking.
        self.login(self.approver)
        with CaptureQueriesContext(connection) as q:
            self.assertEqual(self.client.get("/api/batches/").status_code, 200)
        self.assertLess(len(q), 25)

    def test_each_batch_shows_the_version_of_the_stages_it_keeps(self):
        before = self.register_sample().batch
        ids = self.set_up_stages([LINE, GRAIN])
        self.registered(ids["Final grain"], batch_no="B-002")
        r = self.put_stages([LINE, GRAIN, FINISHED], reason="Finished product testing added")
        self.assertEqual(r.status_code, 200, r.content)
        newer = {s["name"]: s["id"] for s in r.data["current"]["stages"]}
        self.registered(newer["Final grain"], batch_no="B-003")
        self.login(self.approver)
        rows = {row["official_batch_no"]: row for row in self.client.get("/api/batches/").data["results"]}
        self.assertIsNone(rows[before.official_batch_no]["stage_plan"])
        self.assertEqual(rows["B-002"]["stage_plan"], {"version": 1, "latest": 2})
        self.assertEqual(rows["B-003"]["stage_plan"], {"version": 2, "latest": 2})
        self.assertEqual(self.client.get("/api/batches/?file=xlsx").status_code, 200)
