"""Change control: from raising a change to closing it."""
from django.utils import timezone

from audit.models import AuditEvent
from certificates.tests import PW
from .models import ChangeRecord, RecordEvent
from .services import change_digest
from .test_base import LabTestBase


class ChangeTests(LabTestBase):
    def raise_one(self, user=None, **extra):
        return self.ok(self.post("/api/lab/changes/", {
            "title": "New HPLC column", "description": "Move to a C18 column", "reason": "Old one discontinued",
            "impact_assessment": "Method revalidation needed", "category": "METHOD", **extra,
        }, user or self.checker), 201)

    def digest(self, pk):
        return change_digest(ChangeRecord.objects.get(pk=pk))

    def act(self, pk, action, user=None, **body):
        return self.post(f"/api/lab/changes/{pk}/{action}/", body, user)

    def approve(self, pk, user=None, password=PW):
        return self.act(pk, "approve", user, password=password, digest=self.digest(pk))

    def implemented(self):
        pk = self.raise_one()["id"]
        self.ok(self.approve(pk))
        self.ok(self.act(pk, "implement", self.checker, comment="Column installed, SOP updated"))
        return pk

    def test_a_reference_is_issued_in_order_and_never_reused(self):
        year = timezone.localdate().year
        self.assertEqual(self.raise_one()["title"], f"CC-{year}-0001")
        self.assertEqual(self.raise_one()["title"], f"CC-{year}-0002")

    def test_raising_one_needs_the_permission_and_every_part_of_it(self):
        self.refused(self.post("/api/lab/changes/", {"title": "x"}, self.analyst), "permission")
        self.refused(self.post("/api/lab/changes/", {"title": "x"}, self.checker), "Describe the change")
        r = self.post("/api/lab/changes/", {
            "title": "x", "description": "y", "reason": "z", "impact_assessment": "a", "category": "NOPE",
        }, self.checker)
        self.refused(r, "category")
        self.assertFalse(ChangeRecord.objects.exists())

    def test_approval_is_independent_of_whoever_raised_it_and_signed(self):
        pk = self.raise_one(user=self.approver)["id"]
        self.refused(self.approve(pk, self.approver), "someone else")
        self.assertTrue(AuditEvent.objects.filter(action="CHANGE_APPROVAL_REFUSED").exists())
        pk = self.raise_one()["id"]
        self.refused(self.approve(pk, password="wrong"), "Password")
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED", entity="change").exists())
        data = self.ok(self.approve(pk))
        self.assertEqual(data["status"]["text"], "Approved")
        change = ChangeRecord.objects.get(pk=pk)
        self.assertEqual(change.approved_by, self.approver)
        self.assertEqual(change.approved_digest, self.digest(pk))

    def test_whoever_changed_it_is_no_more_independent_than_whoever_raised_it(self):
        pk = self.raise_one()["id"]
        self.ok(self.act(pk, "edit", self.approver, title="Sharper title", comment="Clearer"))
        self.refused(self.approve(pk, self.approver), "someone else")

    def test_the_override_passes_independence_and_is_flagged(self):
        pk = self.raise_one(user=self.admin)["id"]
        self.ok(self.approve(pk, self.admin))
        self.assertIn("override", AuditEvent.objects.get(action="CHANGE_APPROVED").details)

    def test_an_approval_is_tied_to_what_was_read(self):
        pk = self.raise_one()["id"]
        self.refused(self.act(pk, "approve", password=PW, digest="stale"), "changed since you opened it")

    def test_editing_needs_a_reason_and_keeps_the_old_and_new_values(self):
        pk = self.raise_one()["id"]
        self.refused(self.act(pk, "edit", self.checker, title="x"), "Say why")
        self.refused(self.act(pk, "edit", self.checker, comment="No change"), "Nothing was changed")
        data = self.ok(self.act(pk, "edit", self.checker, reason="Vendor stopped making it", comment="More precise"))
        last = data["history"][-1]
        self.assertEqual(last["what"], "Changed")
        self.assertEqual(last["comment"], "More precise")
        self.assertEqual(last["changes"], [{
            "field": "Reason for the change", "old": "Old one discontinued", "new": "Vendor stopped making it",
        }])

    def test_what_was_approved_cannot_change(self):
        pk = self.raise_one()["id"]
        self.ok(self.approve(pk))
        self.refused(self.act(pk, "edit", self.checker, title="x", comment="y"), "Only an open")
        change = ChangeRecord.objects.get(pk=pk)
        change.title = "Rewritten"
        with self.assertRaises(PermissionError):
            change.save()

    def test_it_moves_one_way(self):
        pk = self.raise_one()["id"]
        self.refused(self.act(pk, "implement", self.checker, comment="x"), "Only an approved")
        self.refused(self.act(pk, "close", password=PW), "Only an implemented")
        self.ok(self.approve(pk))
        self.refused(self.approve(pk), "Only an open")
        self.refused(self.act(pk, "reject", comment="x", password=PW), "Only an open")
        change = ChangeRecord.objects.get(pk=pk)
        change.status = "CLOSED"
        with self.assertRaises(PermissionError):
            change.save()

    def test_it_is_closed_by_someone_who_neither_raised_nor_implemented_it(self):
        pk = self.raise_one(user=self.approver)["id"]
        self.ok(self.approve(pk, self.admin))
        self.ok(self.act(pk, "implement", self.checker, comment="Done"))
        self.refused(self.act(pk, "close", self.approver, password=PW), "someone else must close")
        self.assertTrue(AuditEvent.objects.filter(action="CHANGE_CLOSE_REFUSED").exists())

        pk = self.raise_one()["id"]
        self.ok(self.approve(pk))
        self.ok(self.act(pk, "implement", self.approver, comment="Done"))
        self.refused(self.act(pk, "close", self.approver, password=PW), "someone else must close")

    def test_closing_is_signed_and_final(self):
        pk = self.implemented()
        self.refused(self.act(pk, "close", password="wrong"), "Password")
        data = self.ok(self.act(pk, "close", password=PW))
        self.assertEqual(data["status"]["text"], "Closed")
        self.assertEqual(data["actions"], [])
        change = ChangeRecord.objects.get(pk=pk)
        self.assertEqual(change.closed_by, self.approver)
        with self.assertRaises(PermissionError):
            change.save()
        with self.assertRaises(PermissionError):
            change.delete()

    def test_implementing_records_what_was_done(self):
        pk = self.implemented()
        change = ChangeRecord.objects.get(pk=pk)
        self.assertEqual(change.implemented_by, self.checker)
        self.assertEqual(change.implementation_note, "Column installed, SOP updated")

    def test_rejecting_needs_a_reason_a_password_and_someone_independent(self):
        pk = self.raise_one(user=self.approver)["id"]
        self.refused(self.act(pk, "reject", self.approver, comment="No", password=PW), "someone else")
        pk = self.raise_one()["id"]
        self.refused(self.act(pk, "reject", password=PW), "Say why")
        self.refused(self.act(pk, "reject", comment="Not needed", password="wrong"), "Password")
        data = self.ok(self.act(pk, "reject", comment="Not needed", password=PW))
        self.assertEqual(data["status"]["text"], "Rejected")
        self.assertEqual(data["actions"], [])
        with self.assertRaises(PermissionError):
            ChangeRecord.objects.get(pk=pk).save()

    def test_the_buttons_follow_the_rules(self):
        pk = self.raise_one()["id"]
        keys = lambda user: {a["key"] for a in self.ok(self.get(f"/api/lab/changes/{pk}/", user))["actions"]}  # noqa: E731
        self.assertEqual(keys(self.checker), {"edit"})
        self.assertEqual(keys(self.approver), {"edit", "approve", "reject"})
        self.assertEqual(keys(self.analyst), set())
        detail = self.ok(self.get(f"/api/lab/changes/{pk}/", self.approver))
        approve = next(a for a in detail["actions"] if a["key"] == "approve")
        self.assertEqual(approve["digest"], self.digest(pk))

    def test_the_history_holds_every_step_and_is_append_only(self):
        pk = self.implemented()
        steps = [e.what for e in RecordEvent.objects.filter(register="changes", record_id=pk)]
        self.assertEqual(steps, ["Raised", "Approved", "Implemented"])
        event = RecordEvent.objects.filter(register="changes", record_id=pk).first()
        with self.assertRaises(PermissionError):
            event.save()

    def test_the_register_filters_by_status_and_finds_words(self):
        first = self.raise_one()["id"]
        second = self.raise_one(title="Different thing")["id"]
        self.ok(self.approve(second))
        found = self.ok(self.get("/api/lab/changes/?status=OPEN"))["results"]
        self.assertEqual([r["id"] for r in found], [first])
        found = self.ok(self.get("/api/lab/changes/?q=different"))["results"]
        self.assertEqual([r["id"] for r in found], [second])

    def test_those_who_may_decide_are_told_and_the_raiser_hears_the_decision(self):
        pk = self.raise_one()["id"]
        self.assertTrue(self.approver.notifications.filter(kind="LAB_RECORD").exists())
        self.ok(self.approve(pk))
        self.assertTrue(self.checker.notifications.filter(kind="LAB_RECORD").exists())
