"""
The investigation record: what opens one, who may close one, and that nothing
about it can be rewritten afterwards.
"""
from datetime import timedelta

from django.utils import timezone

from qclab.testing import force_update
from audit.models import AuditEvent
from certificates.tests import PW, WorkflowTestBase
from notifications.models import Notification
from .models import CapaAction, Investigation, InvestigationEvent


class QualityTestBase(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.sample = self.register_sample()
        self.enter_results(self.sample, assay="80.0")
        self.failed = self.sample.results.get(outcome="FAIL")

    def post(self, url, body=None, user=None):
        self.login(user or self.checker)
        return self.client.post(url, body or {}, format="json")

    def today(self, days=0):
        return (timezone.localdate() + timedelta(days=days)).isoformat()

    def open(self, user=None, **extra):
        body = {
            "kind": "OOS", "result_id": self.failed.id, "description": "Assay below limit",
            "responsible_id": self.checker.id, "due_date": self.today(7), **extra,
        }
        return self.post("/api/investigations/", body, user)

    def find(self, pk, user=None):
        r = self.post(f"/api/investigations/{pk}/lab-finding/",
                      {"finding": "ASSIGNABLE", "notes": "Dilution error"}, user)
        self.assertEqual(r.status_code, 200, r.content)

    def ready(self):
        """An investigation complete and sent for closure."""
        r = self.open()
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.data["id"]
        self.find(pk)
        self.login(self.checker)
        r = self.client.patch(f"/api/investigations/{pk}/", {
            "classification": "MINOR", "root_cause": "Dilution error", "outcome": "Confirmed laboratory error",
            "conclusion": "INVALIDATED",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.post(f"/api/investigations/{pk}/submit/")
        self.assertEqual(r.status_code, 200, r.content)
        return pk


class OpeningTests(QualityTestBase):
    def test_an_oos_starts_from_a_failed_result_and_copies_what_it_concerns(self):
        r = self.open()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertRegex(r.data["reference"], r"^INV-\d{4}-0001$")
        self.assertEqual(r.data["sample"]["sample_no"], self.sample.sample_no)
        self.assertEqual(r.data["batch_no"], "B-001")
        self.assertEqual(r.data["test_name"], "Assay")
        self.assertTrue(AuditEvent.objects.filter(action="INVESTIGATION_OPENED").exists())

    def test_a_passing_result_cannot_start_an_oos(self):
        passing = self.sample.results.get(outcome="PASS")
        self.assertEqual(self.open(result_id=passing.id).status_code, 400)

    def test_one_open_investigation_per_failed_test(self):
        self.assertEqual(self.open().status_code, 201)
        r = self.open()
        self.assertEqual(r.status_code, 400)
        self.assertIn("already has an open investigation", r.data["detail"])

    def test_opening_one_needs_the_permission(self):
        r = self.open(user=self.analyst)
        self.assertEqual(r.status_code, 400)
        self.assertIn("permission", r.data["detail"])
        self.assertFalse(Investigation.objects.exists())

    def test_nobody_opens_one_on_a_sample_they_cannot_see(self):
        self.roles["CHECKER"].grants.filter(permission="sample.view.all").update(revoked_at=timezone.now())
        self.assertEqual(self.open().status_code, 400)

    def test_a_deviation_needs_no_sample(self):
        r = self.post("/api/investigations/", {
            "kind": "DEVIATION", "description": "Balance out of calibration", "batch_no": "B-777",
            "responsible_id": self.checker.id, "due_date": self.today(3), "product_id": self.product.id,
        })
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(r.data["sample"])
        self.assertEqual(r.data["batch_no"], "B-777")

    def test_references_are_never_reused(self):
        first = self.open().data["reference"]
        r = self.post("/api/investigations/", {
            "kind": "DEVIATION", "description": "Second", "responsible_id": self.checker.id, "due_date": self.today(),
        })
        self.assertNotEqual(first, r.data["reference"])

    def test_nonsense_is_refused_with_a_reason(self):
        self.assertEqual(self.open(due_date="2026-02-31").status_code, 400)
        self.assertEqual(self.open(kind="WHO_KNOWS").status_code, 400)
        self.assertEqual(self.open(responsible_id="abc").status_code, 400)
        self.assertEqual(self.open(description="   ").status_code, 400)

    def test_whoever_is_made_responsible_is_told(self):
        self.open(responsible_id=self.approver.id)
        self.assertTrue(Notification.objects.filter(recipient=self.approver, kind="INVESTIGATION").exists())


class WorkingTests(QualityTestBase):
    def setUp(self):
        super().setUp()
        self.pk = self.open().data["id"]
        self.url = f"/api/investigations/{self.pk}/"

    def patch(self, body):
        self.login(self.checker)
        return self.client.patch(self.url, body, format="json")

    def test_filling_in_a_blank_needs_no_reason_but_changing_it_does(self):
        self.assertEqual(self.patch({"root_cause": "Dilution error"}).status_code, 200)
        r = self.patch({"root_cause": "Instrument drift"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("why", r.data["detail"])
        self.assertEqual(self.patch({"root_cause": "Instrument drift", "reason": "Log reviewed"}).status_code, 200)

    def test_every_change_keeps_the_old_and_new_values(self):
        self.patch({"root_cause": "Dilution error"})
        self.patch({"root_cause": "Instrument drift", "reason": "Log reviewed"})
        changed = InvestigationEvent.objects.filter(investigation_id=self.pk, what="Changed").last()
        self.assertEqual(changed.changes, [{"field": "Root cause", "old": "Dilution error", "new": "Instrument drift"}])
        self.assertEqual(changed.comment, "Log reviewed")
        event = AuditEvent.objects.filter(action="INVESTIGATION_CHANGED").first()
        self.assertEqual(event.details["reason"], "Log reviewed")

    def test_what_it_concerns_cannot_change(self):
        inv = Investigation.objects.get(pk=self.pk)
        inv.batch_no = "B-1"
        inv.save()  # what the batch is called is not fixed; which sample it concerns is
        inv.sample = None
        with self.assertRaises(PermissionError):
            inv.save()

    def test_an_action_is_owned_and_completed_once(self):
        r = self.post(f"{self.url}actions/", {
            "kind": "CORRECTIVE", "description": "Retrain", "owner_id": self.analyst.id, "due_date": self.today(3),
        })
        self.assertEqual(r.status_code, 200, r.content)
        action = r.data["actions"][0]
        self.assertTrue(Notification.objects.filter(recipient=self.analyst, kind="INVESTIGATION").exists())

        self.assertEqual(self.post(f"{self.url}actions/{action['id']}/complete/", {}, self.analyst).status_code, 400)
        done = self.post(f"{self.url}actions/{action['id']}/complete/", {"note": "Done"}, self.analyst)
        self.assertEqual(done.status_code, 200, done.content)
        again = self.post(f"{self.url}actions/{action['id']}/complete/", {"note": "Twice"}, self.analyst)
        self.assertEqual(again.status_code, 400)

    def test_only_the_owner_or_an_investigator_completes_an_action(self):
        r = self.post(f"{self.url}actions/", {
            "kind": "PREVENTIVE", "description": "Review SOP", "owner_id": self.checker.id, "due_date": self.today(),
        })
        action = r.data["actions"][0]["id"]
        self.assertEqual(self.post(f"{self.url}actions/{action}/complete/", {"note": "x"}, self.frontdesk).status_code, 400)

    def test_an_action_cannot_be_deleted_or_rewritten(self):
        self.post(f"{self.url}actions/", {
            "kind": "CORRECTIVE", "description": "Retrain", "owner_id": self.checker.id, "due_date": self.today(),
        })
        action = CapaAction.objects.get(investigation_id=self.pk)
        with self.assertRaises(PermissionError):
            action.delete()
        action.description = "Something else"
        with self.assertRaises(PermissionError):
            action.save()

    def test_it_cannot_go_for_closure_incomplete(self):
        r = self.post(f"{self.url}submit/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("classification", r.data["detail"])
        self.assertIn("root cause", r.data["detail"])
        self.assertIn("final outcome", r.data["detail"])

    def test_it_cannot_go_for_closure_with_actions_open(self):
        self.find(self.pk)
        self.patch({"classification": "MINOR", "root_cause": "x", "outcome": "y", "conclusion": "INVALIDATED"})
        self.post(f"{self.url}actions/", {
            "kind": "CORRECTIVE", "description": "Retrain", "owner_id": self.checker.id, "due_date": self.today(),
        })
        r = self.post(f"{self.url}submit/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("still open", r.data["detail"])

    def test_someone_who_cannot_see_it_gets_nothing(self):
        self.roles["FRONT_DESK"].grants.filter(permission="sample.view.all").update(revoked_at=timezone.now())
        self.frontdesk._perm_cache = None
        force_update(type(self.sample).objects.filter(pk=self.sample.pk), registered_by=self.approver)
        self.login(self.frontdesk)
        self.assertEqual(self.client.get(self.url).status_code, 404)


class ClosureTests(QualityTestBase):
    def test_someone_independent_closes_it_with_their_password(self):
        pk = self.ready()
        r = self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.approver)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "CLOSED")
        self.assertEqual(r.data["closed_by"]["id"], self.approver.id)
        self.assertTrue(AuditEvent.objects.filter(action="INVESTIGATION_CLOSED").exists())

    def test_a_wrong_password_closes_nothing_and_is_recorded(self):
        pk = self.ready()
        r = self.post(f"/api/investigations/{pk}/close/", {"password": "wrong"}, self.approver)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Investigation.objects.get(pk=pk).status, "PENDING_CLOSURE")
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED", entity="investigation").exists())

    def test_nobody_closes_their_own_investigation(self):
        self.login(self.approver)
        r = self.open(user=self.approver, responsible_id=self.approver.id)
        pk = r.data["id"]
        self.find(pk, self.approver)
        self.client.patch(f"/api/investigations/{pk}/", {
            "classification": "MINOR", "root_cause": "x", "outcome": "y", "conclusion": "INVALIDATED",
        }, format="json")
        self.client.post(f"/api/investigations/{pk}/submit/", {}, format="json")
        r = self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.approver)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone independent", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="INVESTIGATION_CLOSE_REFUSED").exists())

    def test_whoever_entered_the_failure_cannot_close_it(self):
        self.roles["ANALYST"].grants.create(permission="investigation.approve", reason="test")
        self.analyst._perm_cache = None
        pk = self.ready()
        r = self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.analyst)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone independent", r.data["detail"])

    def test_closing_needs_the_permission(self):
        pk = self.ready()
        r = self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.frontdesk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Investigation.objects.get(pk=pk).status, "PENDING_CLOSURE")

    def test_the_administrator_override_passes_independence_and_is_flagged(self):
        self.login(self.admin)
        pk = self.open(user=self.admin, responsible_id=self.admin.id).data["id"]
        self.find(pk, self.admin)
        self.client.patch(f"/api/investigations/{pk}/", {
            "classification": "MINOR", "root_cause": "x", "outcome": "y", "conclusion": "INVALIDATED",
        }, format="json")
        self.client.post(f"/api/investigations/{pk}/submit/", {}, format="json")
        r = self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        event = AuditEvent.objects.get(action="INVESTIGATION_CLOSED")
        self.assertIn("override", event.details)

    def test_it_can_be_sent_back_with_a_reason_and_goes_back_to_work(self):
        pk = self.ready()
        self.assertEqual(self.post(f"/api/investigations/{pk}/return/", {}, self.approver).status_code, 400)
        r = self.post(f"/api/investigations/{pk}/return/", {"comment": "Root cause too thin"}, self.approver)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "OPEN")
        self.assertIsNone(r.data["submitted_by"])
        self.assertTrue(Notification.objects.filter(recipient=self.checker, kind="INVESTIGATION").exists())

    def test_a_closed_investigation_never_changes_again(self):
        pk = self.ready()
        self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.approver)
        self.login(self.checker)
        r = self.client.patch(f"/api/investigations/{pk}/", {"outcome": "Rewritten", "reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.post(f"/api/investigations/{pk}/return/", {"comment": "x"}, self.approver).status_code, 400)
        inv = Investigation.objects.get(pk=pk)
        inv.outcome = "Rewritten"
        with self.assertRaises(PermissionError):
            inv.save()
        with self.assertRaises(PermissionError):
            inv.delete()

    def test_a_closed_oos_allows_a_new_one_on_the_same_test(self):
        pk = self.ready()
        self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.approver)
        self.assertEqual(self.open().status_code, 201)

    def test_closing_an_investigation_changes_no_result(self):
        pk = self.ready()
        self.post(f"/api/investigations/{pk}/close/", {"password": PW}, self.approver)
        self.failed.refresh_from_db()
        self.assertEqual(self.failed.outcome, "FAIL")
        self.assertFalse(self.failed.is_superseded)

    def test_the_history_is_append_only(self):
        pk = self.ready()
        event = InvestigationEvent.objects.filter(investigation_id=pk).first()
        with self.assertRaises(PermissionError):
            event.save()
        with self.assertRaises(PermissionError):
            event.delete()
