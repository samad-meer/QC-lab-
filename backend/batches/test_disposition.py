"""
Batch disposition: the quality unit's decision about a batch. A certificate is about
a sample and is not this decision.
"""
from datetime import timedelta

from django.template.loader import get_template
from django.utils import timezone

from accounts.models import LabConfig
from audit.models import AuditEvent
from certificates.tests import PW, WorkflowTestBase
from lims.models import Sample
from qclab.testing import force_update
from .models import Batch, BatchDisposition
from .services import disposition_basis


class DispositionBase(WorkflowTestBase):
    def released_sample(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        sample.refresh_from_db()
        return sample

    def decide(self, batch_id, decision="RELEASED", user=None, reason="All tests within limits", password=PW):
        self.login(user or self.approver)
        return self.client.post(f"/api/batches/{batch_id}/disposition/", {
            "decision": decision, "reason": reason, "password": password,
        }, format="json")

    def refused(self, response, words):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(words, response.data["detail"])


class ReleaseTests(DispositionBase):
    def test_a_batch_with_no_decision_says_so(self):
        batch_id = self.register_sample().batch_id
        self.login(self.approver)
        data = self.client.get(f"/api/batches/{batch_id}/").data["disposition"]
        self.assertEqual((data["label"], data["decision"], data["history"]), ("Not decided", "", []))

    def test_every_sample_approved_is_released(self):
        sample = self.released_sample()
        r = self.decide(sample.batch_id)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["disposition"]["label"], "Released")
        row = BatchDisposition.objects.get()
        self.assertEqual((row.decided_by, row.decision, len(row.basis_hash)), (self.approver, "RELEASED", 64))
        event = AuditEvent.objects.get(action="BATCH_DISPOSITION")
        self.assertEqual(event.details["hash"], row.basis_hash)

    def test_a_cancelled_sample_does_not_count_against_it(self):
        sample = self.released_sample()
        cancelled = self.register_sample()
        self.login(self.approver)
        self.client.post(f"/api/samples/{cancelled.id}/close/",
                         {"action": "cancel", "reason": "Registered twice", "password": PW}, format="json")
        self.assertEqual(self.decide(sample.batch_id).status_code, 200)

    def test_an_unfinished_sample_stops_it(self):
        sample = self.released_sample()
        other = self.register_sample()
        self.refused(self.decide(sample.batch_id), f"{other.sample_no} is not approved")
        self.assertFalse(BatchDisposition.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action="BATCH_DISPOSITION_REFUSED").exists())

    def test_a_batch_with_nothing_but_cancelled_samples_has_nothing_to_release_on(self):
        sample = self.register_sample()
        self.login(self.approver)
        self.client.post(f"/api/samples/{sample.id}/close/",
                         {"action": "cancel", "reason": "Mistake", "password": PW}, format="json")
        self.refused(self.decide(sample.batch_id), "no sample to release it on")

    def test_a_batch_with_no_samples_at_all_is_not_released(self):
        batch = Batch.objects.create(internal_id="B-EMPTY", product=self.product, official_batch_no="E-1")
        self.refused(self.decide(batch.id), "no sample to release it on")

    def test_a_rejected_sample_stops_it(self):
        sample = self.released_sample()
        rejected = self.register_sample()
        force_update(Sample.objects.filter(pk=rejected.pk), status="REJECTED")
        self.refused(self.decide(sample.batch_id), f"{rejected.sample_no} was rejected")

    def test_an_open_investigation_stops_it_even_with_the_failure_rules_off(self):
        """release_blockers stands aside when the lab turns its rules off. This must not."""
        sample = self.released_sample()
        self.assertFalse(LabConfig.get().oos_investigation_required)
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "DEVIATION", "description": "Temperature excursion", "sample_id": sample.id,
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.refused(self.decide(sample.batch_id), "still open on this batch")

    def test_a_deviation_that_only_names_the_batch_stops_it(self):
        sample = self.released_sample()
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "DEVIATION", "description": "x", "product_id": self.product.id,
            "batch_no": sample.batch_no.lower(), "responsible_id": self.checker.id,
            "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.refused(self.decide(sample.batch_id), "still open on this batch")

    def test_the_quality_units_failure_rules_stop_it_as_well(self):
        sample = self.released_sample()
        force_update(sample.results.filter(test_definition=self.t_assay), outcome="FAIL")
        LabConfig.objects.update(oos_investigation_required=True)
        self.refused(self.decide(sample.batch_id), "no investigation of it has closed")

    def test_a_withdrawn_certificate_stops_it(self):
        sample = self.released_sample()
        self.login(self.approver)
        cert = sample.certificates.get()
        r = self.client.post(f"/api/certificates/{cert.id}/withdraw/",
                             {"password": PW, "reason": "Wrong label"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.refused(self.decide(sample.batch_id), "no certificate in force")

    def test_a_batch_past_its_expiry_is_not_released(self):
        sample = self.released_sample()
        force_update(Batch.objects.filter(pk=sample.batch_id), expiry_date=timezone.localdate() - timedelta(days=1))
        self.refused(self.decide(sample.batch_id), "expired on")

    def test_the_override_does_not_pass_the_conditions(self):
        sample = self.register_sample()
        self.refused(self.decide(sample.batch_id, user=self.admin), "cannot be released")

    def test_what_stands_in_the_way_is_listed_for_who_decides(self):
        sample = self.register_sample()
        self.login(self.approver)
        data = self.client.get(f"/api/batches/{sample.batch_id}/").data["disposition"]
        self.assertIn("is not approved", data["release_problems"][0])
        self.login(self.frontdesk)
        self.assertEqual(self.client.get(f"/api/batches/{sample.batch_id}/").data["disposition"]["release_problems"], [])

    def test_it_judges_the_whole_batch_not_what_the_person_can_see(self):
        sample = self.released_sample()
        hidden = self.register_sample()
        self.roles["APPROVER"].grants.filter(permission="sample.view.all").update(revoked_at=timezone.now())
        self.approver._perm_cache = None
        self.refused(self.decide(sample.batch_id), f"{hidden.sample_no} is not approved")


class WhoDecidesTests(DispositionBase):
    def give_analyst_the_permission(self):
        self.analyst.role.grants.create(permission="batch.disposition", reason="test")
        self.analyst._perm_cache = None

    def test_it_needs_the_permission(self):
        sample = self.released_sample()
        self.refused(self.decide(sample.batch_id, user=self.checker), "permission")
        self.assertFalse(BatchDisposition.objects.exists())

    def test_it_needs_a_reason_and_a_decision(self):
        sample = self.released_sample()
        self.refused(self.decide(sample.batch_id, reason=" "), "Say why")
        self.refused(self.decide(sample.batch_id, decision="MAYBE"), "Choose released")

    def test_a_wrong_password_decides_nothing_and_is_recorded(self):
        sample = self.released_sample()
        self.refused(self.decide(sample.batch_id, password="wrong"), "Password")
        self.assertFalse(BatchDisposition.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED", entity="batch").exists())

    def test_never_the_analyst_of_any_sample_of_the_batch(self):
        self.give_analyst_the_permission()
        sample = self.released_sample()
        for decision in ("RELEASED", "REJECTED", "QUARANTINED"):
            self.refused(self.decide(sample.batch_id, decision, self.analyst), "someone else must decide")
        self.assertFalse(BatchDisposition.objects.exists())

    def test_not_the_analyst_of_a_cancelled_sample_either(self):
        self.give_analyst_the_permission()
        sample = self.register_sample()
        self.login(self.approver)
        self.client.post(f"/api/samples/{sample.id}/close/",
                         {"action": "cancel", "reason": "Mistake", "password": PW}, format="json")
        self.refused(self.decide(sample.batch_id, "QUARANTINED", self.analyst), "someone else must decide")

    def test_not_someone_who_entered_a_result_and_handed_the_sample_on(self):
        sample = self.released_sample()
        force_update(Sample.objects.filter(pk=sample.pk), assigned_analyst=self.checker)
        self.give_analyst_the_permission()
        self.refused(self.decide(sample.batch_id, user=self.analyst), "someone else must decide")

    def test_the_override_passes_who_and_is_flagged(self):
        sample = self.register_sample()
        force_update(Sample.objects.filter(pk=sample.pk), assigned_analyst=self.admin)
        r = self.decide(sample.batch_id, "QUARANTINED", self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("override", AuditEvent.objects.get(action="BATCH_DISPOSITION").details)

    def test_the_screen_says_why_someone_who_tested_it_cannot_decide(self):
        self.give_analyst_the_permission()
        sample = self.released_sample()
        self.login(self.analyst)
        data = self.client.get(f"/api/batches/{sample.batch_id}/").data["disposition"]
        self.assertEqual((data["can_decide"], data["tested_it"]), (False, True))


class HistoryTests(DispositionBase):
    def test_the_latest_row_is_the_batchs_status(self):
        sample = self.released_sample()
        self.decide(sample.batch_id, "QUARANTINED", reason="Pending a complaint review")
        r = self.decide(sample.batch_id, "RELEASED")
        self.assertEqual(r.status_code, 200, r.content)
        data = r.data["disposition"]
        self.assertEqual(data["label"], "Released")
        self.assertEqual([h["decision"] for h in data["history"]], ["RELEASED", "QUARANTINED"])

    def test_a_released_batch_can_be_quarantined_and_a_rejected_one_stays_rejected(self):
        sample = self.released_sample()
        self.decide(sample.batch_id)
        self.assertEqual(self.decide(sample.batch_id, "QUARANTINED", reason="Complaint").status_code, 200)
        self.assertEqual(self.decide(sample.batch_id, "REJECTED", reason="Confirmed defect").status_code, 200)
        self.refused(self.decide(sample.batch_id), "stays rejected")
        self.refused(self.decide(sample.batch_id, "QUARANTINED"), "stays rejected")
        self.login(self.approver)
        self.assertFalse(self.client.get(f"/api/batches/{sample.batch_id}/").data["disposition"]["can_decide"])

    def test_the_same_decision_twice_is_refused(self):
        sample = self.released_sample()
        self.decide(sample.batch_id)
        self.refused(self.decide(sample.batch_id), "already released")

    def test_a_batch_can_be_rejected_or_quarantined_with_work_unfinished(self):
        sample = self.register_sample()
        self.assertEqual(self.decide(sample.batch_id, "QUARANTINED").status_code, 200)
        self.assertEqual(self.decide(sample.batch_id, "REJECTED").status_code, 200)

    def test_a_decision_is_never_changed_or_deleted(self):
        sample = self.released_sample()
        self.decide(sample.batch_id)
        row = BatchDisposition.objects.get()
        row.reason = "Rewritten"
        with self.assertRaises(PermissionError):
            row.save()
        with self.assertRaises(PermissionError):
            row.delete()

    def test_the_hash_is_of_what_was_decided_on(self):
        sample = self.released_sample()
        self.decide(sample.batch_id)
        row = BatchDisposition.objects.get()
        certificate = sample.certificates.get()
        self.assertEqual(row.basis["samples"][0]["certificate"]["hash"], certificate.content_hash)
        self.assertEqual(row.basis, disposition_basis(Batch.objects.get(pk=sample.batch_id)))
        assay = next(r for r in row.basis["samples"][0]["results"] if r["test"] == "Assay")
        self.assertEqual((assay["result"], assay["outcome"]), ("99.5", "PASS"))

    def test_it_is_on_the_batchs_history(self):
        sample = self.released_sample()
        self.decide(sample.batch_id)
        self.login(self.approver)
        history = self.client.get(f"/api/batches/{sample.batch_id}/").data["history"]
        self.assertTrue(any("decided batch" in e["sentence"] for e in history))


class ReportTests(DispositionBase):
    def test_the_register_shows_the_decision_or_that_there_is_none(self):
        sample = self.released_sample()
        self.login(self.approver)
        row = self.client.get("/api/reports/batches/").data["results"][0]
        self.assertEqual(row["disposition"]["text"], "Not decided")
        self.decide(sample.batch_id, "QUARANTINED")
        self.decide(sample.batch_id, "RELEASED")
        row = self.client.get("/api/reports/batches/").data["results"][0]
        self.assertEqual((row["disposition"]["text"], row["disposition"]["tone"]), ("Released", "pass"))

    def test_no_report_says_a_disposition_is_not_recorded_any_more(self):
        self.login(self.approver)
        for key in ("batches", "sample-register"):
            note = self.client.get(f"/api/reports/{key}/definition/").data["note"]
            self.assertNotIn("does not record", note)
            self.assertNotIn("records no", note)
            self.assertIn("disposition", note)

    def test_the_summary_document_carries_the_decisions(self):
        sample = self.released_sample()
        self.decide(sample.batch_id)
        self.login(self.approver)
        doc = self.client.get(f"/api/reports/documents/batch/{sample.batch_id}/").data
        facts = {f["label"]: f["value"] for f in doc["sections"][0]["parts"][0]["items"]}
        self.assertEqual(facts["Batch disposition"], "Released")
        table = next(p for p in doc["sections"][0]["parts"] if p.get("heading", "").startswith("Disposition"))
        self.assertEqual(table["rows"][0]["reason"], "All tests within limits")
        r = self.client.get(f"/api/reports/documents/batch/{sample.batch_id}/?file=pdf")
        self.assertEqual(r.status_code, 200)

    def test_the_dashboard_counts_rejected_batches(self):
        sample = self.register_sample()
        self.decide(sample.batch_id, "REJECTED")
        self.login(self.approver)
        self.assertEqual(self.client.get("/api/reports/dashboard/").data["failures"]["rejected_batches"], 1)

    def test_the_certificate_says_it_is_not_a_release_decision(self):
        source = get_template("certificates/coa.html").template.source
        self.assertIn("A certificate of analysis is not a batch release decision.", source)
