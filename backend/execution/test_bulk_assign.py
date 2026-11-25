"""
Assigning the testing of several samples to one analyst at once, from the samples
list: each sample goes through the same checks, record and notice as on its own
page, and one that cannot go to them is left as it was, with the reason.
"""
from audit.models import AuditEvent
from notifications.models import Notification
from .models import TESTING, Assignment
from .tests import ExecutionTestBase


class BulkAssignTests(ExecutionTestBase):
    def three(self):
        return [self.register_sample() for _ in range(3)]

    def bulk(self, user, samples, to, note=""):
        self.login(user)
        ids = [s.id if hasattr(s, "id") else s for s in samples]
        return self.client.post("/api/samples/assign-testing/",
                                {"sample_ids": ids, "user_id": to.id, "note": note}, format="json")

    def test_the_front_desk_gives_several_samples_to_one_analyst(self):
        samples = self.three()
        r = self.bulk(self.frontdesk, samples, self.analyst2, note="Morning batch")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(a["id"] for a in r.data["assigned"]), sorted(s.id for s in samples))
        self.assertEqual(r.data["skipped"], [])
        for s in samples:
            s.refresh_from_db()
            self.assertEqual(s.assigned_analyst_id, self.analyst2.id)
        # One record and one notice for each sample, as on its own page.
        self.assertEqual(AuditEvent.objects.filter(action="ASSIGNED").count(), 3)
        self.assertEqual(Notification.objects.filter(recipient=self.analyst2, kind="ASSIGNED").count(), 3)
        self.assertEqual(Assignment.objects.filter(step=TESTING, to_user=self.analyst2, note="Morning batch").count(), 3)

    def test_one_that_cannot_go_is_left_with_its_reason(self):
        samples = self.three()
        self.bulk(self.frontdesk, samples[:1], self.analyst2)
        untrained = self.make_user("analyst3", "ANALYST")
        r = self.bulk(self.approver, [*samples, 999999], self.analyst2)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(a["id"] for a in r.data["assigned"]), sorted(s.id for s in samples[1:]))
        reasons = {x["id"]: x["reason"] for x in r.data["skipped"]}
        self.assertIn("already holds", reasons[samples[0].id])
        self.assertIn("Not found", reasons[999999])
        r = self.bulk(self.frontdesk, samples, untrained)
        self.assertEqual(r.data["assigned"], [])
        self.assertTrue(all("trained for" in x["reason"] for x in r.data["skipped"]))

    def test_who_can_take_them_and_how_many(self):
        samples = self.three()
        self.make_user("analyst3", "ANALYST")  # trained for no section: never offered
        self.login(self.frontdesk)
        r = self.client.get(f"/api/samples/assign-testing/candidates/?ids={','.join(str(s.id) for s in samples)}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["open"], 3)
        people = {p["id"]: p for p in r.data["people"]}
        self.assertEqual((people[self.analyst.id]["can_take"], people[self.analyst.id]["holds"]), (3, 3))
        self.assertEqual((people[self.analyst2.id]["can_take"], people[self.analyst2.id]["holds"]), (3, 0))
        self.assertNotIn("analyst3", [p["name"].lower() for p in r.data["people"]])

    def test_only_those_who_assign_work(self):
        samples = self.three()
        self.assertEqual(self.bulk(self.analyst, samples, self.analyst2).status_code, 403)
        self.assertEqual(self.client.get(f"/api/samples/assign-testing/candidates/?ids={samples[0].id}").status_code, 403)
        for s in samples:
            s.refresh_from_db()
            self.assertEqual(s.assigned_analyst_id, self.analyst.id)

    def test_nothing_chosen_is_refused(self):
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/assign-testing/", {"sample_ids": [], "user_id": self.analyst2.id},
                             format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/samples/assign-testing/", {"sample_ids": [1]}, format="json")
        self.assertEqual(r.status_code, 400)


class AssignScreenTests(ExecutionTestBase):
    """What the Assign work screen reads: who holds how much, and one person's samples."""

    def overview(self, user):
        self.login(user)
        return self.client.get("/api/assign/overview/")

    def test_each_analyst_with_what_they_hold_and_what_is_late(self):
        first, second = self.register_sample(), self.register_sample()
        second.due_date = second.due_date.replace(year=second.due_date.year - 1)
        type(second).objects.filter(pk=second.pk).update(due_date=second.due_date)
        r = self.overview(self.frontdesk)
        self.assertEqual(r.status_code, 200, r.content)
        people = {p["id"]: p for p in r.data["people"]}
        self.assertEqual((people[self.analyst.id]["open"], people[self.analyst.id]["late"]), (2, 1))
        self.assertEqual((people[self.analyst2.id]["open"], people[self.analyst2.id]["late"]), (0, 0))
        self.assertEqual(people[self.analyst.id]["sections"], ["GF"])
        self.assertEqual((r.data["open"], r.data["late"]), (2, 1))
        # Someone who is not an analyst, and holds nothing, is not on the screen.
        self.assertNotIn(self.checker.id, people)
        self.assertEqual(first.assigned_analyst_id, self.analyst.id)

    def test_a_finished_sample_is_not_work_to_give_out(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.login(self.analyst)
        self.sign_analyst(sample)
        people = {p["id"]: p for p in self.overview(self.frontdesk).data["people"]}
        self.assertEqual(people[self.analyst.id]["open"], 0)

    def test_only_those_who_assign_work_see_it(self):
        self.assertEqual(self.overview(self.analyst).status_code, 403)

    def test_the_sample_list_can_be_narrowed_to_one_analyst(self):
        mine = self.register_sample()
        self.login(self.frontdesk)
        r = self.client.post(f"/api/samples/assign-testing/", {"sample_ids": [mine.id], "user_id": self.analyst2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.register_sample()
        for who, expect in ((self.analyst2, [mine.id]),):
            r = self.client.get(f"/api/samples/?analyst={who.id}&status=RECEIVED,IN_TESTING")
            self.assertEqual([s["id"] for s in r.data["results"]], expect)
        r = self.client.get("/api/samples/?status=RECEIVED,IN_TESTING")
        self.assertEqual(r.data["count"], 2)
        # Anything that is not a number is ignored, not an error.
        self.assertEqual(self.client.get("/api/samples/?analyst=abc&status=RECEIVED,IN_TESTING").data["count"], 2)
