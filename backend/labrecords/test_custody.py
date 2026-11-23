"""Chain of custody, retained samples and their destruction."""
from datetime import timedelta

from django.utils import timezone

from audit.models import AuditEvent
from certificates.tests import PW
from lims.models import Sample
from qclab.testing import force_update
from .models import CustodyEvent
from .test_base import LabTestBase


class CustodyTests(LabTestBase):
    def setUp(self):
        super().setUp()
        self.sample = self.register_sample()
        self.url = f"/api/lab/samples/{self.sample.id}/custody/"

    def add(self, action, user=None, **body):
        return self.post(self.url, {"action": action, **body}, user or self.frontdesk)

    def retain(self, days=30, **body):
        return self.add("RETAINED", location="Retain room", retain_until=self.day(days), **body)

    def finish(self):
        force_update(Sample.objects.filter(pk=self.sample.pk), status="APPROVED")

    def destroy(self, user=None, witness=None, password=PW, witness_password=PW):
        return self.add("DESTROYED", user or self.approver, witness_id=(witness or self.checker).id,
                        password=password, witness_password=witness_password, location="Incinerator")

    def lapse(self):
        """Move the retain-until date into the past, as time would."""
        force_update(CustodyEvent.objects.filter(action="RETAINED"), retain_until=timezone.localdate() - timedelta(days=1))

    def test_each_entry_is_on_the_chain_in_order(self):
        self.ok(self.add("RECEIVED", quantity="60 tablets", comment="Seal intact"))
        self.ok(self.add("STORED", location="Fridge 2"))
        data = self.ok(self.add("TRANSFERRED", to_person_id=self.analyst.id))
        self.assertEqual([e["action"] for e in data["entries"]], ["RECEIVED", "STORED", "TRANSFERRED"])
        self.assertEqual(data["entries"][0]["quantity"], "60 tablets")
        self.assertEqual(data["entries"][0]["by"]["id"], self.frontdesk.id)
        self.assertEqual(data["entries"][2]["from_person"]["id"], self.frontdesk.id)
        self.assertTrue(AuditEvent.objects.filter(action="CUSTODY_RECORDED").exists())

    def test_a_transfer_says_who_to_and_they_hear_about_it(self):
        self.refused(self.add("TRANSFERRED"), "transferred to")
        self.refused(self.add("TRANSFERRED", to_person_id=self.frontdesk.id), "from one person to another")
        self.ok(self.add("TRANSFERRED", to_person_id=self.analyst.id))
        self.assertTrue(self.analyst.notifications.filter(kind="HANDOVER").exists())

    def test_storing_says_where(self):
        self.refused(self.add("STORED"), "where it is kept")
        self.refused(self.add("RETAINED", retain_until=self.day(9)), "where it is kept")

    def test_retained_needs_a_date_not_in_the_past(self):
        self.refused(self.add("RETAINED", location="Room"), "kept until")
        self.refused(self.add("RETAINED", location="Room", retain_until="soon"), "kept until")
        self.refused(self.retain(-1), "cannot be in the past")
        self.ok(self.retain(0))

    def test_a_retain_date_can_be_extended_but_never_brought_forward(self):
        self.ok(self.retain(30))
        self.ok(self.retain(60))
        self.refused(self.retain(10), "never brought forward")
        data = self.ok(self.get(self.url))
        self.assertEqual(data["retain_until"].isoformat(), self.day(60))

    def test_it_needs_the_permission_and_a_real_action(self):
        self.refused(self.add("MISLAID"), "Choose what happened")
        self.assertEqual(self.post(self.url, {"action": "STORED", "location": "x"}, self.admin).status_code, 200)
        self.roles["FRONT_DESK"].grants.filter(permission="custody.record").update(revoked_at=timezone.now())
        self.frontdesk._perm_cache = None
        self.refused(self.add("STORED", location="x"), "permission")

    def test_only_who_can_see_the_sample_can_touch_its_chain(self):
        other = type(self.analyst).objects.create_user("other", password=PW, role=self.analyst.role)
        self.assertEqual(self.get(self.url, other).status_code, 404)
        self.assertEqual(self.post(self.url, {"action": "RECEIVED"}, other).status_code, 404)

    def test_destruction_needs_a_witness_who_is_someone_else(self):
        self.finish()
        self.refused(self.add("DESTROYED", self.approver, password=PW), "witnessed")
        self.refused(self.destroy(witness=self.approver), "different person")
        self.assertTrue(AuditEvent.objects.filter(action="SAMPLE_DESTRUCTION_REFUSED").exists())
        self.assertFalse(self.sample.custody_events.exists())

    def test_the_override_passes_the_witness_and_is_flagged(self):
        self.finish()
        self.ok(self.destroy(user=self.admin, witness=self.admin))
        self.assertIn("override", AuditEvent.objects.get(action="SAMPLE_DESTROYED").details)

    def test_it_is_signed_by_both_people(self):
        self.finish()
        self.refused(self.destroy(password="wrong"), "Password incorrect")
        self.refused(self.destroy(witness_password="wrong"), "witness's password")
        self.assertEqual(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED").count(), 2)
        self.assertFalse(self.sample.custody_events.exists())
        self.ok(self.destroy())

    def test_it_is_refused_while_the_retain_date_has_not_passed(self):
        self.ok(self.retain(30))
        self.finish()
        self.refused(self.destroy(), "can be destroyed after that date")
        force_update(CustodyEvent.objects.filter(action="RETAINED"), retain_until=timezone.localdate())
        self.refused(self.destroy(), "can be destroyed after that date")  # the day itself has not passed
        self.lapse()
        self.ok(self.destroy())

    def test_the_latest_date_counts_whichever_order_they_were_written(self):
        self.ok(self.retain(30))
        self.ok(self.retain(60))
        force_update(CustodyEvent.objects.filter(retain_until=self.day(30)),
                     retain_until=timezone.localdate() - timedelta(days=9))
        self.finish()
        self.refused(self.destroy(), "can be destroyed after that date")

    def test_the_override_does_not_pass_the_date(self):
        self.ok(self.retain(30))
        self.finish()
        self.refused(self.destroy(user=self.admin), "can be destroyed after that date")

    def test_a_sample_still_in_work_cannot_be_destroyed(self):
        self.refused(self.destroy(), "still received")

    def test_it_needs_its_own_permission(self):
        self.finish()
        self.refused(self.destroy(user=self.checker), "permission")

    def test_nothing_follows_destruction(self):
        self.finish()
        data = self.ok(self.destroy())
        self.assertTrue(data["destroyed"])
        self.assertFalse(data["can_add"])
        self.refused(self.add("STORED", location="x"), "has been destroyed")
        self.refused(self.destroy(), "has been destroyed")
        self.assertEqual(self.sample.custody_events.filter(action="DESTROYED").count(), 1)

    def test_the_chain_is_append_only(self):
        self.ok(self.add("RECEIVED"))
        event = CustodyEvent.objects.get()
        event.note = "Rewritten"
        with self.assertRaises(PermissionError):
            event.save()
        with self.assertRaises(PermissionError):
            event.delete()

    def test_the_register_lists_what_is_held_and_what_is_due(self):
        self.ok(self.retain(30))
        second = self.register_sample()
        self.ok(self.post(f"/api/lab/samples/{second.id}/custody/", {
            "action": "RETAINED", "location": "Shelf 4", "retain_until": self.day(0), "quantity": "20 tablets",
        }, self.frontdesk))
        force_update(CustodyEvent.objects.filter(sample=second), retain_until=timezone.localdate() - timedelta(days=1))
        rows = self.ok(self.get("/api/lab/retained/"))["results"]
        self.assertEqual([r["cells"]["sample"]["text"] for r in rows], [second.sample_no, self.sample.sample_no])
        self.assertEqual(rows[0]["cells"]["state"]["text"], "Due for destruction")
        self.assertEqual(rows[0]["cells"]["location"], "Shelf 4")
        self.assertEqual(rows[0]["cells"]["quantity"], "20 tablets")
        self.assertEqual(rows[1]["cells"]["state"]["text"], "Held")
        due = self.ok(self.get("/api/lab/retained/?state=due"))["results"]
        self.assertEqual([r["id"] for r in due], [second.id])

    def test_a_destroyed_sample_leaves_the_register(self):
        self.ok(self.retain(0))
        self.lapse()
        self.finish()
        self.ok(self.destroy())
        self.assertEqual(self.ok(self.get("/api/lab/retained/"))["results"], [])

    def test_the_register_shows_only_samples_you_can_see(self):
        self.ok(self.retain(30))
        other = type(self.analyst).objects.create_user("other", password=PW, role=self.analyst.role)
        self.assertEqual(self.ok(self.get("/api/lab/retained/", other))["results"], [])

    def test_the_sample_history_carries_the_chain(self):
        self.ok(self.add("STORED", location="Fridge 2"))
        doc = self.ok(self.get(f"/api/reports/documents/sample/{self.sample.id}/"))
        table = next(p for p in doc["sections"][0]["parts"] if p.get("heading") == "Chain of custody")
        self.assertEqual(table["rows"][0]["location"], "Fridge 2")
