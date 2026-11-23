"""
What must happen after a failed result, with the quality unit's rules as they ship.
Everything here goes through the API, in the order a lab would do it.
"""
from datetime import timedelta

from django.utils import timezone

from accounts.models import LabConfig
from audit.models import AuditEvent
from certificates.models import CertStatus, PrintEvent
from certificates.tests import PW, WorkflowTestBase
from execution.models import TESTING, RetestRequest
from lims.models import Sample
from .models import Investigation


class FailurePathBase(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        LabConfig.objects.filter(pk=1).delete()
        LabConfig.get()  # the rules as shipped
        self.grant_second_analyst()

    def grant_second_analyst(self):
        self.second = type(self.analyst).objects.create_user(
            "analyst2", password=PW, first_name="Second", last_name="Analyst", role=self.analyst.role
        )
        self.second.sections.add(self.section)

    def failed_sample(self, value="80.0"):
        sample = self.register_sample()
        self.enter_results(sample, assay=value)
        return sample

    def failure_of(self, sample):
        return sample.results.filter(test_definition=self.t_assay, outcome="FAIL").order_by("-entered_at", "-id").first()

    def open_oos(self, sample):
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": self.failure_of(sample).id, "description": "Assay below limit",
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Investigation.objects.get(pk=r.data["id"])

    def find(self, inv, finding="ASSIGNABLE", notes="Dilution was wrong on the worksheet", user=None):
        self.login(user or self.checker)
        return self.client.post(f"/api/investigations/{inv.id}/lab-finding/", {"finding": finding, "notes": notes},
                                format="json")

    def request_retest(self, sample, user=None):
        self.login(user or self.analyst)
        return self.client.post(f"/api/samples/{sample.id}/retests/", {
            "test_definition_id": self.t_assay.id, "reason": "Laboratory error found", "kind": "RETEST",
        }, format="json")

    def authorize(self, sample):
        request = RetestRequest.objects.filter(sample=sample).order_by("-id").first()
        self.login(self.approver)
        r = self.client.post(f"/api/retests/{request.id}/decide/", {"action": "authorize"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def hand_over(self, sample, to):
        self.login(self.frontdesk)
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": TESTING, "user_id": to.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def enter_retest(self, sample, value, user):
        self.login(user)
        return self.client.post(f"/api/samples/{sample.id}/results/", {
            "test_definition_id": self.t_assay.id, "value_numeric": value,
        }, format="json")

    def retested(self, sample, value="99.0"):
        """A failure taken through its finding and a retest by a second analyst."""
        inv = self.open_oos(sample)
        self.assertEqual(self.find(inv).status_code, 200)
        self.assertEqual(self.request_retest(sample).status_code, 200)
        self.authorize(sample)
        self.hand_over(sample, self.second)
        r = self.enter_retest(sample, value, self.second)
        self.assertEqual(r.status_code, 201, r.content)
        return inv

    def close(self, inv, conclusion="INVALIDATED"):
        self.login(self.checker)
        r = self.client.patch(f"/api/investigations/{inv.id}/", {
            "classification": "MINOR", "root_cause": "Dilution error", "outcome": "Retest stands",
            "conclusion": conclusion,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.post(f"/api/investigations/{inv.id}/submit/", format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.login(self.approver)
        r = self.client.post(f"/api/investigations/{inv.id}/close/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 200, r.content)


class RetestRuleTests(FailurePathBase):
    def test_a_retest_needs_an_investigation_first(self):
        r = self.request_retest(self.failed_sample())
        self.assertEqual(r.status_code, 400)
        self.assertIn("Open an out-of-specification investigation", r.data["detail"])

    def test_a_retest_needs_the_laboratory_finding(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        r = self.request_retest(sample)
        self.assertEqual(r.status_code, 400)
        self.assertIn(f"laboratory finding on {inv.reference}", r.data["detail"])

    def test_whoever_entered_the_failure_cannot_record_the_finding(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        self.analyst.role.grants.create(permission="investigation.manage", reason="test")
        self.analyst._perm_cache = None
        r = self.find(inv, user=self.analyst)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone else", r.data["detail"])

    def test_the_analyst_who_failed_it_cannot_retest_it(self):
        sample = self.failed_sample()
        self.open_oos(sample)
        self.find(Investigation.objects.get())
        self.request_retest(sample)
        self.authorize(sample)
        r = self.enter_retest(sample, "99.0", self.analyst)
        self.assertEqual(r.status_code, 400)
        self.assertIn("second analyst", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="RETEST_REFUSED_SAME_ANALYST").exists())

    def test_the_lab_can_turn_the_second_analyst_rule_off(self):
        LabConfig.objects.update(oos_second_analyst=False)
        sample = self.failed_sample()
        self.open_oos(sample)
        self.find(Investigation.objects.get())
        self.request_retest(sample)
        self.authorize(sample)
        self.assertEqual(self.enter_retest(sample, "99.0", self.analyst).status_code, 201)

    def test_retests_stop_at_the_limit(self):
        sample = self.failed_sample()
        self.retested(sample, "81.0")
        self.assertEqual(self.request_retest(sample, self.second).status_code, 200)
        self.authorize(sample)
        self.assertEqual(self.enter_retest(sample, "82.0", self.second).status_code, 201)
        r = self.request_retest(sample, self.second)
        self.assertEqual(r.status_code, 400)
        self.assertIn("the most the lab allows", r.data["detail"])

    def test_a_confirmed_failure_cannot_be_retested_away(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        self.find(inv, "NONE_FOUND")
        self.close(inv, "CONFIRMED")
        r = self.request_retest(sample)
        self.assertEqual(r.status_code, 400)
        self.assertIn("confirmed this failure", r.data["detail"])


class ReleaseTests(FailurePathBase):
    def sign(self, sample):
        self.login(self.second)
        return self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")

    def test_a_passing_retest_does_not_release_while_the_investigation_is_open(self):
        sample = self.failed_sample()
        inv = self.retested(sample)
        r = self.sign(sample)
        self.assertEqual(r.status_code, 400)
        self.assertIn(inv.reference, str(r.data))

    def test_once_it_closes_the_certificate_can_go_forward_and_shows_the_history(self):
        sample = self.failed_sample()
        inv = self.retested(sample)
        self.close(inv)
        r = self.sign(sample)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["content"]["investigations"][0]["reference"], inv.reference)
        self.assertEqual(r.data["content"]["history_for_review"][0]["original_value"], "80.0")

    def test_a_failure_cannot_be_invalidated_without_a_laboratory_error(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        self.find(inv, "NONE_FOUND")
        self.login(self.checker)
        self.client.patch(f"/api/investigations/{inv.id}/", {
            "classification": "MINOR", "root_cause": "None found", "outcome": "x", "conclusion": "INVALIDATED",
        }, format="json")
        r = self.client.post(f"/api/investigations/{inv.id}/submit/", format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("only invalidated by a laboratory error", r.data["detail"])

    def test_a_new_sample_of_the_batch_does_not_escape_the_failure(self):
        failed = self.failed_sample()
        second = self.register_sample()
        self.assertEqual(second.batch_id, failed.batch_id)
        self.enter_results(second)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{second.id}/sign-analyst/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn(failed.sample_no, str(r.data))

    def test_the_lab_can_keep_a_failure_to_its_own_sample(self):
        LabConfig.objects.update(oos_batch_block=False)
        self.failed_sample()
        second = self.register_sample()
        self.enter_results(second)
        self.assertEqual(self.sign_analyst(second).status, CertStatus.IN_REVIEW)

    def test_an_open_deviation_on_the_batch_stops_its_certificates(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "DEVIATION", "description": "Temperature excursion", "product_id": self.product.id,
            "batch_no": sample.batch_no.lower(), "responsible_id": self.checker.id,
            "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("still open on this batch", str(r.data))

    def test_a_clean_sample_is_not_held_up(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.assertEqual(self.sign_analyst(sample).status, CertStatus.IN_REVIEW)


class SampleEndTests(FailurePathBase):
    def close(self, sample, action, user=None, password=PW, reason="It is what happened"):
        self.login(user or self.approver)
        return self.client.post(f"/api/samples/{sample.id}/close/",
                                {"action": action, "reason": reason, "password": password}, format="json")

    def confirmed(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        self.find(inv, "NONE_FOUND")
        FailurePathBase.close(self, inv, "CONFIRMED")
        return sample

    def test_a_confirmed_failure_ends_as_a_rejected_sample(self):
        sample = self.confirmed()
        r = self.close(sample, "reject")
        self.assertEqual(r.status_code, 200, r.content)
        sample.refresh_from_db()
        self.assertEqual((sample.status, sample.closed_by), ("REJECTED", self.approver))
        self.assertTrue(AuditEvent.objects.filter(action="SAMPLE_REJECTED").exists())

    def test_it_stops_being_overdue(self):
        sample = self.confirmed()
        self.close(sample, "reject")
        self.login(self.approver)
        rows = self.client.get("/api/reports/overdue/").data["results"]
        self.assertFalse(rows)

    def test_a_sample_cannot_be_rejected_on_an_unconfirmed_failure(self):
        r = self.close(self.failed_sample(), "reject")
        self.assertEqual(r.status_code, 400)
        self.assertIn("confirming the failure", r.data["detail"])

    def test_a_rejected_sample_stops_the_rest_of_its_batch(self):
        rejected = self.confirmed()
        self.close(rejected, "reject")
        second = self.register_sample()
        self.enter_results(second)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{second.id}/sign-analyst/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("was rejected", str(r.data))

    def test_a_failure_cannot_be_cancelled_away(self):
        r = self.close(self.failed_sample(), "cancel")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cannot be cancelled", r.data["detail"])

    def test_a_sample_registered_by_mistake_is_cancelled(self):
        sample = self.register_sample()
        self.assertEqual(self.close(sample, "cancel").status_code, 200)
        sample.refresh_from_db()
        self.assertEqual(sample.status, "CANCELLED")

    def test_closing_needs_the_password_and_the_permission(self):
        sample = self.register_sample()
        self.assertIn("Password", self.close(sample, "cancel", password="wrong").data["detail"])
        self.assertIn("permission", self.close(sample, "cancel", user=self.checker).data["detail"])

    def test_finished_means_finished(self):
        sample = self.register_sample()
        self.close(sample, "cancel")
        self.assertIn("already cancelled", self.close(sample, "cancel").data["detail"])
        self.enter_retest(sample, "99.0", self.analyst)
        self.assertEqual(sample.results.count(), 0)


class WithdrawalTests(FailurePathBase):
    def released(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        return cert

    def withdraw(self, cert, user=None, password=PW, reason="Wrong batch on the label"):
        self.login(user or self.approver)
        return self.client.post(f"/api/certificates/{cert.id}/withdraw/",
                                {"password": password, "reason": reason}, format="json")

    def test_a_withdrawn_certificate_says_so_on_its_verification_page(self):
        cert = self.released()
        self.assertEqual(self.withdraw(cert).status_code, 200)
        page = self.client.get(f"/verify/{cert.verification_uuid}/").content.decode()
        self.assertIn("withdrawn", page)
        self.assertIn("Wrong batch on the label", page)
        self.assertNotIn("genuine and current", page)

    def test_its_content_stays_and_it_cannot_be_printed(self):
        cert = self.released()
        content = cert.content
        self.withdraw(cert)
        cert.refresh_from_db()
        self.assertEqual((cert.status, cert.content), ("WITHDRAWN", content))
        self.login(self.approver)
        self.assertEqual(self.client.post(f"/api/certificates/{cert.id}/print/", {}, format="json").status_code, 400)
        self.assertFalse(PrintEvent.objects.filter(certificate=cert).exists())

    def test_it_needs_the_permission_a_reason_and_a_password(self):
        cert = self.released()
        self.assertEqual(self.withdraw(cert, user=self.checker).status_code, 400)
        self.assertEqual(self.withdraw(cert, reason=" ").status_code, 400)
        self.assertEqual(self.withdraw(cert, password="wrong").status_code, 400)
        cert.refresh_from_db()
        self.assertEqual(cert.status, "APPROVED")

    def test_only_a_released_certificate_can_be_withdrawn(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.assertEqual(self.withdraw(self.sign_analyst(sample)).status_code, 400)


class RuleChangeTests(FailurePathBase):
    def test_changing_a_rule_needs_a_reason_and_is_recorded(self):
        self.login(self.approver)
        r = self.client.patch("/api/quality-rules/", {"oos_max_retests": 1}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch("/api/quality-rules/", {"oos_max_retests": 1, "reason": "SOP QC-012"}, format="json")
        self.assertEqual((r.status_code, r.data["oos_max_retests"]), (200, 1))
        event = AuditEvent.objects.get(action="QUALITY_RULES_CHANGED")
        self.assertEqual((event.details["before"], event.details["after"]),
                         ({"oos_max_retests": 2}, {"oos_max_retests": 1}))

    def test_only_someone_who_approves_closures_can_change_them(self):
        self.login(self.checker)
        r = self.client.patch("/api/quality-rules/", {"oos_max_retests": 9, "reason": "Why not"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(LabConfig.get().oos_max_retests, 2)

    def test_they_ship_strict(self):
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/quality-rules/").data, {
            "oos_investigation_required": True, "oos_max_retests": 2,
            "oos_second_analyst": True, "oos_batch_block": True,
        })


class ClosureDetailTests(FailurePathBase):
    def test_a_major_investigation_needs_an_action(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        self.find(inv, "NONE_FOUND")
        self.login(self.checker)
        self.client.patch(f"/api/investigations/{inv.id}/", {
            "classification": "MAJOR", "root_cause": "x", "outcome": "y", "conclusion": "CONFIRMED",
        }, format="json")
        r = self.client.post(f"/api/investigations/{inv.id}/submit/", format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("at least one", r.data["detail"])

    def test_whoever_worked_on_it_is_not_independent(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        self.login(self.approver)
        self.client.patch(f"/api/investigations/{inv.id}/", {"root_cause": "My theory"}, format="json")
        self.find(inv, "NONE_FOUND")
        self.login(self.checker)
        self.client.patch(f"/api/investigations/{inv.id}/", {
            "classification": "MINOR", "outcome": "y", "conclusion": "CONFIRMED",
        }, format="json")
        self.client.post(f"/api/investigations/{inv.id}/submit/", format="json")
        self.login(self.approver)
        r = self.client.post(f"/api/investigations/{inv.id}/close/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone independent", r.data["detail"])

    def test_sending_it_back_does_not_cost_the_approver_their_independence(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        self.find(inv, "NONE_FOUND")
        self.login(self.checker)
        self.client.patch(f"/api/investigations/{inv.id}/", {
            "classification": "MINOR", "root_cause": "x", "outcome": "y", "conclusion": "CONFIRMED",
        }, format="json")
        self.client.post(f"/api/investigations/{inv.id}/submit/", format="json")
        self.login(self.approver)
        self.client.post(f"/api/investigations/{inv.id}/return/", {"comment": "More detail"}, format="json")
        self.login(self.checker)
        self.client.post(f"/api/investigations/{inv.id}/submit/", format="json")
        self.login(self.approver)
        r = self.client.post(f"/api/investigations/{inv.id}/close/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_the_record_shows_the_failure_and_everything_since(self):
        sample = self.failed_sample()
        inv = self.retested(sample)
        self.login(self.approver)
        failure = self.client.get(f"/api/investigations/{inv.id}/").data["failure"]
        self.assertEqual([(r["value"], r["outcome"]) for r in failure["results"][-2:]],
                         [("80.0", "FAIL"), ("99.0", "PASS")])
        self.assertEqual(failure["results"][-1]["authorized_by"]["id"], self.approver.id)
