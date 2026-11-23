"""Whether a corrective or preventive action worked is judged by someone else."""
from audit.models import AuditEvent
from certificates.tests import PW
from qclab.testing import force_update
from .models import CapaAction, Investigation
from .tests import QualityTestBase


class VerificationTests(QualityTestBase):
    def setUp(self):
        super().setUp()
        r = self.open()
        self.assertEqual(r.status_code, 201, r.content)
        self.pk = r.data["id"]
        self.url = f"/api/investigations/{self.pk}/"
        self.find(self.pk)
        self.login(self.checker)
        self.client.patch(self.url, {
            "classification": "MINOR", "root_cause": "x", "outcome": "y", "conclusion": "INVALIDATED",
        }, format="json")

    def action(self, owner=None):
        r = self.post(f"{self.url}actions/", {
            "kind": "CORRECTIVE", "description": "Retrain", "owner_id": (owner or self.analyst).id, "due_date": self.today(3),
        })
        self.assertEqual(r.status_code, 200, r.content)
        return r.data["actions"][-1]["id"]

    def complete(self, action, user=None):
        r = self.post(f"{self.url}actions/{action}/complete/", {"note": "Done"}, user or self.analyst)
        self.assertEqual(r.status_code, 200, r.content)

    def done(self):
        action = self.action()
        self.complete(action)
        return action

    def verify(self, action, user=None, note="Observed the next three runs", password=PW):
        return self.post(f"{self.url}actions/{action}/verify/", {"note": note, "password": password}, user or self.checker)

    def test_someone_else_verifies_it_with_their_password(self):
        action = self.done()
        r = self.verify(action)
        self.assertEqual(r.status_code, 200, r.content)
        row = r.data["actions"][0]
        self.assertEqual(row["verified_by"]["id"], self.checker.id)
        self.assertEqual(row["verification_note"], "Observed the next three runs")
        self.assertTrue(row["verified_at"])
        self.assertTrue(AuditEvent.objects.filter(action="CAPA_VERIFIED").exists())

    def test_not_the_owner(self):
        action = self.action(owner=self.checker)
        self.complete(action, self.checker)
        r = self.verify(action)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone else", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="CAPA_VERIFY_REFUSED").exists())

    def test_not_whoever_completed_it_for_the_owner(self):
        action = self.action()
        self.complete(action, self.checker)
        self.assertEqual(self.verify(action).status_code, 400)
        self.assertEqual(self.verify(action, self.approver).status_code, 200)

    def test_the_override_passes_it_and_is_flagged(self):
        action = self.action(owner=self.admin)
        self.complete(action, self.admin)
        r = self.verify(action, self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("override", AuditEvent.objects.get(action="CAPA_VERIFIED").details)

    def test_it_needs_the_permission_a_note_and_the_password(self):
        action = self.done()
        self.assertIn("Only someone", self.verify(action, self.frontdesk).data["detail"])
        self.assertIn("Say how", self.verify(action, note=" ").data["detail"])
        self.assertIn("Password", self.verify(action, password="wrong").data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED", entity="investigation").exists())
        self.assertIsNone(CapaAction.objects.get(pk=action).verified_at)

    def test_only_once_it_is_completed_and_only_once(self):
        action = self.action()
        self.assertIn("not been completed", self.verify(action).data["detail"])
        self.complete(action)
        self.assertEqual(self.verify(action).status_code, 200)
        self.assertIn("already been verified", self.verify(action, self.approver).data["detail"])

    def test_it_cannot_go_for_closure_while_a_completed_action_is_unverified(self):
        action = self.done()
        r = self.post(f"{self.url}submit/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not been verified", r.data["detail"])
        self.verify(action)
        self.assertEqual(self.post(f"{self.url}submit/").status_code, 200)

    def test_whoever_verified_it_is_not_independent_of_the_closure(self):
        action = self.done()
        self.verify(action, self.approver)
        self.post(f"{self.url}submit/")
        r = self.post(f"{self.url}close/", {"password": PW}, self.approver)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone independent", r.data["detail"])

    def test_the_whole_way_through(self):
        action = self.done()
        self.verify(action)
        self.post(f"{self.url}submit/")
        r = self.post(f"{self.url}close/", {"password": PW}, self.approver)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["actions"][0]["verified_by"]["id"], self.checker.id)

    def test_a_closure_sent_before_verification_existed_is_stopped_too(self):
        action = self.done()
        force_update(Investigation.objects.filter(pk=self.pk), status="PENDING_CLOSURE", submitted_by=self.checker)
        r = self.post(f"{self.url}close/", {"password": PW}, self.approver)
        self.assertEqual(r.status_code, 400)
        self.assertIn("not been verified", r.data["detail"])
        self.assertEqual(self.verify(action).status_code, 400)  # sent back first

    def test_the_screen_is_told_who_may_verify(self):
        self.done()
        self.login(self.checker)
        self.assertTrue(self.client.get(self.url).data["actions"][0]["can_verify"])
        self.login(self.analyst)
        self.assertFalse(self.client.get(self.url).data["actions"][0]["can_verify"])

    def test_a_verified_action_never_changes_and_a_completed_one_only_gains_its_verification(self):
        action = CapaAction.objects.get(pk=self.done())
        action.completion_note = "Rewritten"
        with self.assertRaises(PermissionError):
            action.save()
        self.verify(action.pk)
        action = CapaAction.objects.get(pk=action.pk)
        action.verification_note = "Rewritten"
        with self.assertRaises(PermissionError):
            action.save()

    def test_an_open_action_cannot_be_given_a_verification_directly(self):
        action = CapaAction.objects.get(pk=self.action())
        action.verification_note = "Nothing to verify"
        with self.assertRaises(PermissionError):
            action.save()

    def test_the_register_and_documents_say_what_is_not_verified(self):
        self.done()
        self.login(self.approver)
        row = self.client.get("/api/reports/deviations/").data["results"][0]
        self.assertEqual(row["capa"]["sub"], "0 of 1 open, 1 not verified")
