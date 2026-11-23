"""
Assigning a recorded stage of a batch to the person who fills it and signs its first
column: who may assign, who it can go to, what it stops others doing, reassignment and
its history, and the assignee's task list.
"""
from django.db import DatabaseError, transaction

from accounts.models import User
from audit.describe import describe
from audit.models import AuditEvent
from certificates.tests import PW
from .models import BatchStageAssignment
from .test_batch_records import RecordBase


class AssignBase(RecordBase):
    def setUp(self):
        super().setUp()
        self.operator2 = User.objects.create_user(username="operator2", password=PW, role=self.op_role,
                                                  first_name="Imran")
        self.batch, ids = self.batch_with(self.bulking())
        self.sid = ids["Bulking (Lot-C)"]

    def assign(self, person, user=None, note=""):
        self.login(user or self.supervisor)
        return self.client.post(f"/api/batches/{self.batch.id}/qc-stages/{self.sid}/assign/",
                                {"assignee_id": person.id if person else None, "note": note}, format="json")

    def assignment(self, user=None):
        return self.stage(self.batch.id, "Bulking (Lot-C)") if user is None else next(
            s for s in self.stages_of(self.batch.id, user)["stages"] if s["name"] == "Bulking (Lot-C)")

    def api_point(self):
        return self.points(self.batch.id)["Ciprofloxacin HCl"]["id"]


class AssigningTests(AssignBase):
    def test_the_supervisor_assigns_a_stage_and_everyone_sees_who_has_it(self):
        offered = self.assignment(self.supervisor)["assignment"]
        self.assertTrue(offered["can_assign"])
        # Only people who sign its first column, "Done by (Operator)", and may fill records.
        self.assertEqual(sorted(p["name"] for p in offered["people"]), ["Imran", "Operator"])
        r = self.assign(self.operator, note="Day shift")
        self.assertEqual(r.status_code, 200, r.content)
        shown = self.assignment()["assignment"]
        self.assertEqual((shown["holder"]["name"], shown["by"]["name"], shown["note"]), ("Operator", "Supervisor", "Day shift"))
        self.assertFalse(shown["can_assign"])  # the lab head looking may not assign
        sentence = describe(AuditEvent.objects.get(action="BATCH_STAGE_ASSIGNED"))["sentence"]
        self.assertIn("assigned stage “Bulking (Lot-C)” of batch", sentence)
        self.assertIn("to Operator — “Day shift”", sentence)

    def test_only_those_allowed_assign_and_only_to_someone_who_can_do_the_stage(self):
        self.refused(self.assign(self.operator2, user=self.operator), "permission to assign batch-record stages")
        # The supervisor signs "Checked by", not "Done by": not someone this stage can go to.
        self.refused(self.assign(self.supervisor), "can only be assigned to someone who signs “Done by”")
        self.refused(self.assign(self.analyst), "can only be assigned to someone who signs “Done by”")
        self.assertFalse(BatchStageAssignment.objects.exists())
        self.assertEqual(self.assign(self.operator2, user=self.admin).status_code, 200)

    def test_assigned_only_the_assignee_fills_and_signs_done_by(self):
        self.assign(self.operator)
        self.refused(self.write(self.batch.id, self.sid, [{"checkpoint_id": self.api_point(), "number": "17.887"}],
                                user=self.operator2),
                     "Bulking (Lot-C) is assigned to Operator. Only they write its values.")
        self.login(self.operator2)
        record = self.assignment(self.operator2)["record"]
        self.assertEqual((record["can_fill"], record["fill_blocked"]),
                         (False, "Bulking (Lot-C) is assigned to Operator. Only they write its values."))
        self.fill_all(self.batch, self.sid)  # as the operator it is assigned to
        done, prod, _qa = (c["id"] for c in self.columns(self.batch.id))
        self.refused(self.sign(self.batch.id, self.sid, done, self.operator2), "They sign “Done by”")
        self.assertEqual(self.sign(self.batch.id, self.sid, done, self.operator).status_code, 200)
        # The columns after the first are signed as before, by their roles.
        self.assertEqual(self.sign(self.batch.id, self.sid, prod, self.supervisor).status_code, 200)

    def test_an_administrator_may_step_in_and_it_is_flagged(self):
        self.assign(self.operator)
        r = self.write(self.batch.id, self.sid, [{"checkpoint_id": self.api_point(), "number": "17.887"}],
                       user=self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        event = AuditEvent.objects.filter(action="BATCH_RECORD_WRITTEN").latest("id")
        self.assertIn("assigned to Operator", str(event.details.get("override")))

    def test_reassigning_keeps_the_history_and_nobody_opens_it_again(self):
        self.assign(self.operator)
        self.refused(self.assign(self.operator), "already assigned to Operator")
        self.assertEqual(self.assign(self.operator2, note="Operator on leave").status_code, 200)
        shown = self.assignment()["assignment"]
        self.assertEqual(shown["holder"]["name"], "Imran")
        self.assertEqual([h["holder"]["name"] for h in shown["history"]], ["Imran", "Operator"])
        self.assertIn("(it was Operator’s)",
                      describe(AuditEvent.objects.filter(action="BATCH_STAGE_ASSIGNED").latest("id"))["sentence"])
        # Taken away from everyone: the stage is open to anyone who may fill records, as before.
        self.assertEqual(self.assign(None).status_code, 200)
        self.assertIsNone(self.assignment()["assignment"]["holder"])
        self.assertIn("leaving it open to anyone",
                      describe(AuditEvent.objects.get(action="BATCH_STAGE_UNASSIGNED"))["sentence"])
        r = self.write(self.batch.id, self.sid, [{"checkpoint_id": self.api_point(), "number": "17.887"}],
                       user=self.operator2)
        self.assertEqual(r.status_code, 200, r.content)
        self.refused(self.assign(None), "is not assigned to anyone")

    def test_a_stage_never_assigned_works_as_it_always_has(self):
        self.fill_all(self.batch, self.sid)
        done = self.columns(self.batch.id)[0]["id"]
        self.assertEqual(self.sign(self.batch.id, self.sid, done, self.operator2).status_code, 200)

    def test_once_done_by_is_signed_there_is_nothing_left_to_assign(self):
        self.assign(self.operator)
        self.fill_all(self.batch, self.sid)
        self.sign(self.batch.id, self.sid, self.columns(self.batch.id)[0]["id"], self.operator)
        self.refused(self.assign(self.operator2), "the work it is assigned for is done")
        self.assertFalse(self.assignment(self.supervisor)["assignment"]["can_assign"])

    def test_an_assignment_is_never_changed_or_deleted(self):
        self.assign(self.operator)
        with self.assertRaises(PermissionError):
            BatchStageAssignment.objects.get().save()
        with self.assertRaises(DatabaseError), transaction.atomic():
            BatchStageAssignment.objects.update(note="changed")


class TaskListTests(AssignBase):
    def tasks(self, user):
        self.login(user)
        return self.client.get("/api/tasks/").data

    def test_the_assignee_finds_the_stage_in_their_tasks_until_they_have_signed_it(self):
        self.assertEqual(self.tasks(self.operator)["batch_stages"], [])
        self.assign(self.operator, note="Day shift")
        data = self.tasks(self.operator)
        [item] = data["batch_stages"]
        self.assertEqual((item["stage"]["name"], item["state"], item["column"], item["note"]),
                         ("Bulking (Lot-C)", "fill", "Done by", "Day shift"))
        self.assertEqual(item["missing"], 3)
        self.assertGreaterEqual(data["actionable"], 1)
        self.assertEqual(self.tasks(self.operator2)["batch_stages"], [])
        self.fill_all(self.batch, self.sid)
        self.assertEqual(self.tasks(self.operator)["batch_stages"][0]["state"], "sign")
        self.sign(self.batch.id, self.sid, self.columns(self.batch.id)[0]["id"], self.operator)
        self.assertEqual(self.tasks(self.operator)["batch_stages"], [])

    def test_reassigned_it_moves_to_the_new_assignee(self):
        self.assign(self.operator)
        self.assign(self.operator2)
        self.assertEqual(self.tasks(self.operator)["batch_stages"], [])
        self.assertEqual(len(self.tasks(self.operator2)["batch_stages"]), 1)


class ByAssignmentTests(AssignBase):
    """Once a stage of a batch is assigned, the batch works by assignment: the rest wait for a name."""

    NAMES = ["Stage 1", "Stage 2", "Stage 3", "Stage 4", "Stage 5"]

    def setUp(self):
        super().setUp()
        self.ids = self.set_up_stages([self.bulking(name=n) for n in self.NAMES])
        self.five = self.new_batch("B-002")

    def give(self, name, person, user=None):
        self.login(user or self.supervisor)
        return self.client.post(f"/api/batches/{self.five.id}/qc-stages/{self.ids[name]}/assign/",
                                {"assignee_id": person.id if person else None}, format="json")

    def write_on(self, name, user):
        first = self.stage(self.five.id, name)["record"]["steps"][0]["checkpoints"][0]["id"]
        return self.write(self.five.id, self.ids[name], [{"checkpoint_id": first, "number": "17.887"}], user=user)

    def test_with_only_the_third_assigned_everyone_sees_all_five_and_only_its_assignee_fills_it(self):
        self.assertEqual(self.give("Stage 3", self.operator).status_code, 200)
        seen = self.stages_of(self.five.id, self.operator)["stages"]
        self.assertEqual([s["name"] for s in seen], self.NAMES)
        self.assertTrue(all(s["assignment"]["required"] for s in seen))
        self.assertEqual(self.write_on("Stage 3", self.operator).status_code, 200)
        for other in ("Stage 1", "Stage 2", "Stage 4", "Stage 5"):
            self.refused(self.write_on(other, self.operator), f"{other} is not assigned to anyone yet")
        self.refused(self.write_on("Stage 1", self.operator2), "the production supervisor names who does it")
        self.refused(self.write_on("Stage 3", self.operator2), "Stage 3 is assigned to Operator")
        first = next(s for s in seen if s["name"] == "Stage 1")["record"]
        self.assertFalse(first["can_fill"])
        self.assertIn("not assigned to anyone yet", first["fill_blocked"])
        # An administrator may still step in, flagged as always.
        self.assertEqual(self.write_on("Stage 1", self.admin).status_code, 200)

    def test_taking_one_away_says_whether_it_waits_or_is_open_again(self):
        self.give("Stage 3", self.operator)
        self.give("Stage 4", self.operator2)
        self.give("Stage 4", None)
        self.assertIn("waits to be assigned again",
                      describe(AuditEvent.objects.filter(action="BATCH_STAGE_UNASSIGNED").latest("id"))["sentence"])
        self.refused(self.write_on("Stage 4", self.operator2), "not assigned to anyone yet")
        self.give("Stage 3", None)
        # Nothing assigned any more: the batch is open to anyone who fills batch records again.
        self.assertIn("leaving it open to anyone",
                      describe(AuditEvent.objects.filter(action="BATCH_STAGE_UNASSIGNED").latest("id"))["sentence"])
        self.assertEqual(self.write_on("Stage 4", self.operator2).status_code, 200)
        self.assertFalse(self.stage(self.five.id, "Stage 1")["assignment"]["required"])
