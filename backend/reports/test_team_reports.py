"""
Tasks by Person, Team Tasks and Person Activity: that every kind of open work is counted
under the right person, that each report agrees with the others, who may open them and
choose another person, and that anyone can print their own week.
"""
import csv
import io
from datetime import timedelta

from django.utils import timezone
from openpyxl import load_workbook

from audit.models import AuditEvent
from batches.test_stage_assignment import AssignBase
from lims.models import Sample
from qclab.testing import force_update
from .team import WORK_ACTIONS
from .tests import ReportTestBase


class TeamReportBase(ReportTestBase):
    def held_by(self, report="team-tasks", query="", user=None):
        return [(self.text(r["person"]), self.text(r["type"])) for r in self.rows(report, query, user)]


class OpenWorkTests(TeamReportBase):
    def test_tasks_by_person_counts_what_each_person_holds(self):
        self.register_sample()
        self.non_batch_sample()
        rows = {self.text(r["person"]): r for r in self.rows("tasks-by-person", user=self.approver)}
        mine = rows[self.analyst.display_name()]
        self.assertEqual((self.text(mine["sample"]), self.text(mine["total"])), ("2", "2"))
        self.assertEqual(self.text(mine["review"]), "0")
        self.assertNotIn(self.checker.display_name(), rows, "someone holding nothing is not listed")

    def test_everyone_can_be_listed_including_those_with_nothing(self):
        self.register_sample()
        rows = self.rows("tasks-by-person", "everyone=1", self.approver)
        names = {self.text(r["person"]): self.text(r["total"]) for r in rows}
        self.assertEqual(names[self.analyst.display_name()], "1")
        self.assertEqual(names[self.checker.display_name()], "0")

    def test_team_tasks_says_who_gave_it_when_and_where(self):
        sample = self.register_sample()
        [row] = self.rows("team-tasks", user=self.approver)
        self.assertEqual(self.text(row["person"]), self.analyst.display_name())
        self.assertEqual(self.text(row["by"]), self.frontdesk.display_name())
        self.assertEqual(self.text(row["type"]), "Sample testing")
        self.assertEqual(self.text(row["task"]), sample.sample_no)
        self.assertEqual(row["task"]["to"], f"/samples/{sample.pk}")
        self.assertIn(sample.product.name, self.text(row["product"]))
        self.assertTrue(self.text(row["since"]) and self.text(row["due"]))

    def test_a_review_waits_on_its_role_and_is_not_counted_against_the_analyst(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)
        held = self.held_by()
        self.assertEqual([t for _, t in held], ["Sample review or approval"])
        self.assertNotEqual(held[0][0], self.analyst.display_name())
        by_person = self.rows("tasks-by-person", user=self.approver)
        self.assertEqual(len(by_person), 1)
        self.assertEqual(by_person[0]["person"].get("to", ""), "", "a role has no page of its own to open")
        self.assertEqual(self.rows("team-tasks", f"person={self.analyst.id}", self.approver), [])

    def test_the_filters_narrow_by_person_kind_and_lateness(self):
        late = self.register_sample()
        self.non_batch_sample()
        force_update(Sample.objects.filter(pk=late.pk), due_date=timezone.localdate() - timedelta(days=3))
        self.assertEqual(len(self.rows("team-tasks", user=self.approver)), 2)
        only = self.rows("team-tasks", "overdue=1", self.approver)
        self.assertEqual([self.text(r["task"]) for r in only], [late.sample_no])
        self.assertEqual(self.text(only[0]["status"]), "Overdue 3 d")
        self.assertEqual(len(self.rows("team-tasks", f"person={self.analyst.id}", self.approver)), 2)
        self.assertEqual(self.rows("team-tasks", f"person={self.checker.id}", self.approver), [])
        self.assertEqual(self.rows("team-tasks", "kind=batch", self.approver), [])
        by_person = self.rows("tasks-by-person", user=self.approver)
        self.assertEqual(self.text(by_person[0]["overdue"]), "1")
        self.report("team-tasks", "kind=nonsense", self.approver, code=400)

    def test_assigned_in_a_week_or_a_month_shows_what_was_handed_out_in_it(self):
        self.register_sample()
        self.assertEqual(len(self.rows("team-tasks", "period=week", self.approver)), 1)
        self.assertEqual(len(self.rows("team-tasks", "period=month", self.approver)), 1)
        self.assertEqual(self.rows("team-tasks", "from=2020-01-01&to=2020-01-31", self.approver), [])
        data = self.report("team-tasks", "period=week", self.approver)
        self.assertEqual(data["period"], "This week")

    def test_an_investigation_and_its_action_are_tasks_of_their_owners(self):
        sample = self.failed_sample()
        failed = sample.results.get(outcome="FAIL")
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "Assay below limit",
            "responsible_id": self.checker.id, "due_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.post(f"/api/investigations/{r.data['id']}/actions/", {
            "kind": "CORRECTIVE", "description": "Retrain the analyst", "owner_id": self.analyst.id,
            "due_date": (timezone.localdate() + timedelta(days=3)).isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        held = self.held_by("team-tasks", "kind=investigation", self.approver)
        self.assertEqual(held, [(self.checker.display_name(), "Investigation")])
        action = self.rows("team-tasks", "kind=capa", self.approver)
        self.assertEqual([(self.text(a["person"]), self.text(a["by"])) for a in action],
                         [(self.analyst.display_name(), self.checker.display_name())])
        by_person = {self.text(r["person"]): r for r in self.rows("tasks-by-person", user=self.approver)}
        self.assertEqual(self.text(by_person[self.checker.display_name()]["investigation"]), "1")
        self.assertEqual(self.text(by_person[self.analyst.display_name()]["capa"]), "1")


class BatchStageTests(AssignBase, TeamReportBase):
    def test_a_batch_record_stage_is_the_task_of_whoever_it_was_assigned_to(self):
        self.assertEqual(self.rows("team-tasks", "kind=batch", self.approver), [], "not assigned yet")
        self.assertEqual(self.assign(self.operator, note="Day shift").status_code, 200)
        [row] = self.rows("team-tasks", "kind=batch", self.approver)
        self.assertEqual(self.text(row["person"]), "Operator")
        self.assertEqual(self.text(row["by"]), "Supervisor")
        self.assertEqual(self.text(row["type"]), "Batch record stage")
        self.assertEqual(row["task"]["to"], f"/batches/{self.batch.pk}")
        self.assertIn("Bulking (Lot-C)", self.text(row["stage"]))
        self.assertIn("Fill", row["stage"]["sub"])

        # Handing it on moves it to the new person, and the old one holds nothing.
        self.assertEqual(self.assign(self.operator2).status_code, 200)
        held = self.held_by("team-tasks", "kind=batch", self.approver)
        self.assertEqual(held, [("Imran", "Batch record stage")])
        counts = {self.text(r["person"]): self.text(r["batch"]) for r in self.rows("tasks-by-person", user=self.approver)}
        self.assertEqual(counts, {"Imran": "1"})

    def test_a_stage_handed_back_and_forth_is_still_one_task(self):
        for person in (self.operator, self.operator2, self.operator):
            self.assertEqual(self.assign(person).status_code, 200)
        self.assertEqual(self.held_by("team-tasks", "kind=batch", self.approver), [("Operator", "Batch record stage")])
        self.login(self.operator)
        self.assertEqual(len(self.client.get("/api/tasks/").data["batch_stages"]), 1)

    def test_it_is_the_same_list_the_assignee_sees_in_my_tasks(self):
        self.assign(self.operator)
        self.login(self.operator)
        mine = self.client.get("/api/tasks/").data["batch_stages"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(len(self.rows("team-tasks", "kind=batch", self.approver)), 1)


class PersonActivityTests(TeamReportBase):
    def mine(self, user, query=""):
        return self.report("person-activity", query, user)

    def work_of(self, user):
        return AuditEvent.objects.filter(actor=user, action__in=WORK_ACTIONS).count()

    def test_everyone_gets_their_own_week_and_nobody_elses(self):
        self.released_sample()
        data = self.mine(self.analyst)
        self.assertEqual(data["count"], self.work_of(self.analyst))
        self.assertGreater(data["count"], 0)
        self.assertEqual(data["subject"], f"{self.analyst.display_name()} ({self.analyst.role.name})")
        sentences = " ".join(self.text(r["what"]) for r in data["results"])
        self.assertIn("Signed certificate", sentences)
        self.assertNotIn("as “Checked by”", sentences, "the checker's signature is the checker's")

    def test_choosing_someone_else_needs_the_workload_permission(self):
        self.released_sample()
        self.login(self.analyst)
        self.assertEqual(self.client.get(f"/api/reports/person-activity/?person={self.checker.id}").status_code, 403)
        data = self.mine(self.approver, f"person={self.analyst.id}")
        self.assertEqual(data["count"], self.work_of(self.analyst))
        self.assertTrue(data["subject"].startswith(self.analyst.display_name()))
        self.login(self.approver)
        self.assertEqual(self.client.get("/api/reports/person-activity/?person=999999").status_code, 400)

    def test_the_week_the_month_and_any_dates_decide_what_is_listed(self):
        self.released_sample()
        self.assertEqual(self.mine(self.analyst, "period=week")["count"], self.work_of(self.analyst))
        self.assertEqual(self.mine(self.analyst, "period=month")["count"], self.work_of(self.analyst))
        empty = self.mine(self.analyst, "from=2020-01-01&to=2020-01-31")
        self.assertEqual((empty["count"], empty["results"]), (0, []))
        tiles = {t["label"]: t["value"] for t in empty["summary"]}
        self.assertEqual((tiles["Things done"], tiles["Results entered"], tiles["Signatures"]), (0, 0, 0))

    def test_the_figures_above_the_list_say_what_was_done_given_and_is_still_held(self):
        self.register_sample()
        sample = self.register_sample()
        self.enter_results(sample)
        tiles = {t["label"]: t["value"] for t in self.mine(self.analyst)["summary"]}
        self.assertEqual(tiles["Results entered"], sample.results.count())
        self.assertEqual(tiles["Given to them"], 2)
        self.assertEqual(tiles["Holding now"], 2)
        self.assertEqual(tiles["Overdue now"], 0)

    def test_the_kind_of_work_filter_narrows_the_list(self):
        self.released_sample()
        results = self.mine(self.analyst, "kind=results")["results"]
        self.assertTrue(results)
        self.assertTrue(all("ntered" in self.text(r["what"]) or "eplaced" in self.text(r["what"]) for r in results))
        signed = self.mine(self.analyst, "kind=signatures")["results"]
        self.assertTrue(signed)
        self.assertTrue(all("igned" in self.text(r["what"]) for r in signed))

    def test_without_the_permission_their_own_can_be_read_but_not_printed(self):
        self.released_sample()
        self.login(self.analyst)
        definition = self.client.get("/api/reports/person-activity/definition/").data
        self.assertFalse(definition["can_export"])
        self.assertEqual(self.client.get("/api/reports/person-activity/").status_code, 200, "the screen stays open")
        for kind in ("csv", "xlsx", "pdf"):
            self.assertEqual(self.client.get(f"/api/reports/person-activity/export/?file={kind}").status_code, 403, kind)
        self.assertFalse(AuditEvent.objects.filter(action="REPORT_EXPORTED").exists())

    def test_the_permission_to_print_their_own_prints_only_their_own(self):
        self.released_sample()
        self.grant(self.analyst, "report.print.own")
        self.login(self.analyst)
        self.assertTrue(self.client.get("/api/reports/person-activity/definition/").data["can_export"])
        self.assertEqual(self.client.get("/api/reports/person-activity/export/?file=pdf").status_code, 200)
        self.assertEqual(self.client.get(
            f"/api/reports/person-activity/export/?file=pdf&person={self.checker.id}").status_code, 403)
        # It opens no other report's downloads.
        self.assertEqual(self.client.get("/api/reports/sample-register/export/?file=csv").status_code, 403)

    def test_whoever_may_export_reports_prints_their_own_too(self):
        self.released_sample()
        self.grant(self.analyst, "report.export")
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/reports/person-activity/export/?file=csv").status_code, 200)

    def test_a_print_says_whose_it_is_and_only_an_exporter_prints_another_persons(self):
        self.released_sample()
        self.grant(self.analyst, "report.print.own")
        self.login(self.analyst)
        definition = self.client.get("/api/reports/person-activity/definition/").data
        self.assertTrue(definition["can_export"], "given the permission, the analyst prints their own")
        for kind in ("csv", "xlsx", "pdf"):
            r = self.client.get(f"/api/reports/person-activity/export/?file={kind}")
            self.assertEqual(r.status_code, 200, (kind, r.content[:200]))
        own = self.client.get("/api/reports/person-activity/export/?file=csv").content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(own)))
        self.assertTrue(any("Signed certificate" in " ".join(r) for r in rows))
        # A print says whose it is, at the head, as the screen does.
        book = load_workbook(io.BytesIO(self.client.get("/api/reports/person-activity/export/?file=xlsx").content))
        head = [c.value for c in book.active["A"] if c.value]
        self.assertIn(f"Report for: {self.analyst.display_name()} ({self.analyst.role.name})", head)
        totals = next(line for line in head if str(line).startswith("Things done:"))
        for label in ("Results entered:", "Signatures:", "Given to them:", "Holding now:", "Overdue now:"):
            self.assertIn(label, totals)
        screen = {t["label"]: t["value"] for t in self.mine(self.analyst)["summary"]}
        self.assertIn(f"Things done: {screen['Things done']}", totals, "a print says what the screen says")
        self.assertEqual(self.client.get(
            f"/api/reports/person-activity/export/?file=csv&person={self.checker.id}").status_code, 403)
        # The approver exports anyone's.
        self.login(self.approver)
        r = self.client.get(f"/api/reports/person-activity/export/?file=pdf&person={self.analyst.id}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertTrue(AuditEvent.objects.filter(action="REPORT_EXPORTED", entity_id="person-activity").exists())

    def test_it_is_not_limited_to_the_samples_the_reader_can_see(self):
        self.register_sample()
        data = self.mine(self.analyst)
        self.assertFalse(data["partial"], "it is about their own work, so it is whole")


class SomeoneWhoHasLeftTests(TeamReportBase):
    def test_what_a_person_who_left_did_and_holds_can_still_be_read(self):
        self.register_sample()
        self.login(self.approver)
        self.analyst.is_active = False
        self.analyst.save()
        for key in ("person-activity", "team-tasks", "tasks-by-person"):
            options = self.client.get(f"/api/reports/{key}/definition/").data["filters"][0]["options"]
            labels = [o["label"] for o in options]
            self.assertIn(f"{self.analyst.display_name()} (inactive)", labels, key)
        data = self.report("person-activity", f"person={self.analyst.id}", self.approver)
        self.assertTrue(data["subject"].startswith(self.analyst.display_name()))
        self.assertEqual(len(self.rows("team-tasks", f"person={self.analyst.id}", self.approver)), 1,
                         "what they still hold is how QA finds work to reassign")
        listed = [self.text(r["person"]) for r in self.rows("tasks-by-person", "everyone=1", self.approver)]
        self.assertEqual(listed.count(self.analyst.display_name()), 1)
        self.assertNotIn(f"{self.analyst.display_name()} (inactive)", listed)


class WhoMayOpenTests(TeamReportBase):
    def catalogue(self, user):
        self.login(user)
        r = self.client.get("/api/reports/")
        self.assertEqual(r.status_code, 200)
        return {e["key"] for g in r.data["categories"] for e in g["reports"]}

    def test_everyone_with_reports_opens_their_own_activity_and_the_planners_open_the_team_reports(self):
        team = {"tasks-by-person", "team-tasks"}
        for user in (self.analyst, self.frontdesk):
            keys = self.catalogue(user)
            self.assertIn("person-activity", keys)
            self.assertFalse(team & keys, f"{user.username} plans no one's work")
        for user in (self.checker, self.approver, self.admin):
            self.assertTrue(team | {"person-activity"} <= self.catalogue(user), user.username)

    def test_the_team_reports_stay_shut_to_those_without_them(self):
        for key in ("tasks-by-person", "team-tasks"):
            self.report(key, user=self.analyst, code=403)
            self.report(key, user=self.approver)
        self.report("person-activity", user=self.analyst)
