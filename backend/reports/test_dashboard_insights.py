"""
The dashboard's deeper views: the period beside the one before, what is coming due, how long work has
waited, where failures come from, how long release takes, and whether the equipment is in date. Each
figure opens exactly the records it counts, and counts only what the person looking may see.
"""
from datetime import timedelta

from django.utils import timezone

from accounts.models import Role, RolePermissionGrant, User
from certificates.tests import PW
from labrecords.models import (
    CalibrationEvent, CalibrationKind, CalibrationOutcome, Instrument, InstrumentStatus, Material, MaterialKind,
    MaterialStatus,
)
from lims.models import Sample
from qclab.listing import period_window
from qclab.testing import force_update
from .insights import AGE_BANDS, previous_window
from .tests import ReportTestBase


class InsightBase(ReportTestBase):
    def insights(self, user=None, query="period=month"):
        self.login(user or self.approver)
        r = self.client.get(f"/api/reports/dashboard/?{query}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data["insights"]

    def opens(self, link, user=None):
        """The records a link leads to, counted by the report it opens."""
        path, _, query = link.partition("?")
        return self.report(path.rsplit("/", 1)[1], query, user)["count"]

    def tiles(self, **kw):
        return {t["key"]: t for t in self.insights(**kw)["tiles"]}

    def due_in(self, sample, days):
        Sample.objects.filter(pk=sample.pk).update(due_date=timezone.localdate() + timedelta(days=days))

    def received_ago(self, sample, days):
        force_update(Sample.objects.filter(pk=sample.pk), received_at=timezone.now() - timedelta(days=days))


class PreviousPeriodTests(InsightBase):
    def test_this_month_is_compared_with_the_same_days_of_last_month(self):
        window = period_window("month")
        before, label = previous_window(window)
        first = timezone.localtime(window.start)
        last_month = timezone.localtime(before.start)
        self.assertEqual(label, "last month")
        self.assertEqual((last_month.day, last_month.hour), (1, 0))
        self.assertEqual((last_month.year, last_month.month) < (first.year, first.month), True)
        # Never a stretch that runs into the month being measured
        self.assertLessEqual(before.stop, window.start)

    def test_a_finished_month_is_compared_with_the_whole_month_before_it(self):
        window = period_window("lastmonth")
        before, _ = previous_window(window)
        self.assertEqual(before.stop, window.start)

    def test_a_week_is_compared_with_the_week_before(self):
        window = period_window("week")
        before, label = previous_window(window)
        self.assertEqual(label, "last week")
        self.assertEqual(before.start, window.start - timedelta(days=7))

    def test_all_time_has_nothing_to_be_compared_with(self):
        self.assertEqual(previous_window(period_window("all")), (None, ""))

    def test_a_change_is_the_difference_and_the_percentage(self):
        before, _ = previous_window(period_window("month"))
        old = self.register_sample()
        force_update(Sample.objects.filter(pk=old.pk), received_at=before.start + timedelta(minutes=1))
        self.register_sample()
        self.register_sample()
        data = self.insights()
        received = {t["key"]: t for t in data["tiles"]}["received"]
        self.assertEqual(data["compare"], "last month")
        self.assertEqual(received["value"], 2)
        self.assertEqual(received["delta"]["change"], 1)
        self.assertEqual(received["delta"]["percent"], 100)

    def test_nothing_before_it_gives_a_change_but_no_percentage(self):
        self.register_sample()
        delta = self.tiles()["received"]["delta"]
        self.assertEqual(delta["change"], 1)
        self.assertIsNone(delta["percent"])

    def test_all_time_gives_no_change_at_all(self):
        self.register_sample()
        data = self.insights(query="period=all")
        self.assertIsNone(data["compare"])
        self.assertTrue(all(t["delta"] is None for t in data["tiles"]))


class HeadlineTests(InsightBase):
    def test_received_and_completed_open_exactly_the_samples_they_count(self):
        self.released_sample()
        self.register_sample()
        self.register_sample()
        tiles = self.tiles()
        self.assertEqual((tiles["received"]["value"], tiles["completed"]["value"]), (3, 1))
        for key in ("received", "completed"):
            self.assertEqual(self.opens(tiles[key]["to"]), tiles[key]["value"], key)

    def test_the_small_trend_adds_up_to_the_figure(self):
        self.released_sample()
        self.register_sample()
        tiles = self.tiles()
        self.assertEqual(sum(tiles["received"]["spark"]), tiles["received"]["value"])
        self.assertEqual(sum(tiles["completed"]["spark"]), tiles["completed"]["value"])

    def test_the_pass_rate_is_passed_over_passed_and_failed(self):
        self.released_sample()  # Description and Assay both pass
        self.failed_sample()  # Description passes, Assay fails
        tile = self.tiles()["pass_rate"]
        self.assertEqual(tile["value"], 75.0)
        self.assertEqual(tile["display"], "75%")
        self.assertEqual(tile["sub"], "3 passed, 1 failed")

    def test_the_pass_rate_opens_exactly_the_results_it_is_a_share_of(self):
        self.released_sample()
        self.failed_sample()
        tile = self.tiles()["pass_rate"]
        self.assertEqual(self.opens(tile["to"]), 4)
        self.report("test-results", "outcome=JUDGED")

    def test_a_period_with_no_results_has_no_pass_rate_instead_of_a_zero(self):
        tile = self.tiles()["pass_rate"]
        self.assertIsNone(tile["value"])
        self.assertEqual(tile["display"], "–")

    def test_overdue_is_the_open_samples_past_their_due_date(self):
        late = self.register_sample()
        self.due_in(late, -3)
        done, _ = self.released_sample()
        self.due_in(done, -9)
        tile = self.tiles()["overdue"]
        self.assertEqual(tile["value"], 1)
        self.assertEqual(self.opens(tile["to"]), 1)
        self.assertTrue(tile["alert"])

    def test_released_on_time_counts_the_samples_released_by_their_due_date(self):
        on_time, _ = self.released_sample()
        late, _ = self.released_sample()
        self.due_in(late, -2)
        tile = self.tiles()["on_time"]
        self.assertEqual((tile["value"], tile["sub"]), (50.0, "1 of 2 by their due date"))
        # It agrees with the Turnaround report it opens
        summary = {s["label"]: s["value"] for s in self.report(
            "turnaround", tile["to"].partition("?")[2])["summary"]}
        self.assertEqual(summary["Released"], 2)
        self.assertIsNotNone(on_time)

    def test_an_analyst_sees_the_figures_of_their_own_samples_only(self):
        mine, other = self.register_sample(), self.register_sample()
        self.someone_elses(other)
        self.assertEqual(self.tiles(user=self.analyst)["received"]["value"], 1)
        self.assertEqual(self.tiles()["received"]["value"], 2)


class OutlookTests(InsightBase):
    def test_each_day_counts_the_open_samples_due_that_day_and_opens_them(self):
        for days in (0, 0, 1, 3, 20, -2):
            self.due_in(self.register_sample(), days)
        done, _ = self.released_sample()
        self.due_in(done, 1)  # finished: nothing is waiting on it
        outlook = self.insights()["outlook"]
        self.assertEqual([d["value"] for d in outlook["days"]][:4], [2, 1, 0, 1])
        self.assertEqual((outlook["overdue"]["value"], outlook["later"]["value"]), (1, 1))
        for day in outlook["days"]:
            self.assertEqual(self.opens(day["to"]), day["value"], day["date"])
        for part in ("overdue", "later"):
            self.assertEqual(self.opens(outlook[part]["to"]), outlook[part]["value"], part)

    def test_the_outlook_runs_for_two_weeks_starting_today(self):
        days = self.insights()["outlook"]["days"]
        self.assertEqual(len(days), 14)
        self.assertEqual(days[0]["date"], timezone.localdate().isoformat())

    def test_an_analyst_sees_only_the_samples_they_hold(self):
        mine, other = self.register_sample(), self.register_sample()
        self.someone_elses(other)
        self.due_in(mine, 1)
        self.due_in(other, 1)
        self.assertEqual(self.insights(self.analyst)["outlook"]["days"][1]["value"], 1)


class AgeingTests(InsightBase):
    def test_each_cell_counts_the_samples_in_that_stage_of_that_age_and_opens_them(self):
        ages = [0, 1, 4, 7, 12, 30]
        for days in ages:
            self.received_ago(self.register_sample(), days)
        self.received_ago(self.failed_sample(), 5)
        data = self.insights()["ageing"]
        stages = {s["key"]: s for s in data["stages"]}
        self.assertEqual(stages["AWAITING_TESTING"]["values"], [2, 1, 1, 2])
        for stage in data["stages"]:
            for value, link in zip(stage["values"], stage["links"]):
                self.assertEqual(self.opens(link), value, (stage["key"], link))
        self.assertEqual([b["key"] for b in data["bands"]], list(AGE_BANDS))

    def test_finished_samples_are_not_waiting(self):
        done, _ = self.released_sample()
        self.received_ago(done, 40)
        total = sum(sum(s["values"]) for s in self.insights()["ageing"]["stages"])
        self.assertEqual(total, 0)

    def test_a_filter_that_makes_no_sense_is_refused(self):
        self.report("sample-register", "age=forever", code=400)


class FailureTests(InsightBase):
    def test_failures_are_ranked_by_test_with_the_share_that_failed(self):
        self.released_sample()
        self.failed_sample()
        self.failed_sample()
        rows = self.insights()["failures"]["tests"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["label"], rows[0]["failed"], rows[0]["total"], rows[0]["rate"]), ("Assay", 2, 3, 67))

    def test_each_row_opens_exactly_the_failed_results_it_counts(self):
        self.released_sample()
        self.failed_sample()
        self.failed_sample()
        failures = self.insights()["failures"]
        for kind in ("tests", "products"):
            for row in failures[kind]:
                self.assertEqual(self.opens(row["to"]), row["failed"], (kind, row["label"]))

    def test_failures_by_product_name_the_product(self):
        self.failed_sample()
        rows = self.insights()["failures"]["products"]
        self.assertEqual([r["label"] for r in rows], [self.product.name])

    def test_a_test_is_found_by_its_exact_name_not_by_part_of_it(self):
        self.failed_sample()  # one Description result and one Assay result
        self.assertEqual(self.report("test-results", "test_name=Assay")["count"], 1)
        self.report("test-results", "test_name=Assa", code=400)

    def test_nothing_failed_means_nothing_to_rank(self):
        self.released_sample()
        self.assertEqual(self.insights()["failures"], {"tests": [], "products": []})

    def test_an_analyst_sees_the_failures_of_their_own_samples_only(self):
        mine, other = self.failed_sample(), self.failed_sample()
        self.someone_elses(other)
        self.assertEqual(self.insights(self.analyst)["failures"]["tests"][0]["failed"], 1)
        self.assertEqual(self.insights()["failures"]["tests"][0]["failed"], 2)


class TurnaroundTests(InsightBase):
    def test_released_samples_fall_into_bands_that_add_up_to_the_released_count(self):
        self.released_sample()
        self.released_sample()
        turnaround = self.insights()["turnaround"]
        self.assertEqual(sum(b["value"] for b in turnaround["bands"]), 2)
        self.assertEqual(turnaround["bands"][0]["value"], 2)  # released within minutes
        self.assertEqual((turnaround["on_time"], turnaround["late"]), (2, 0))

    def test_a_sample_released_after_its_due_date_is_late(self):
        sample, _ = self.released_sample()
        self.due_in(sample, -1)
        turnaround = self.insights()["turnaround"]
        self.assertEqual((turnaround["on_time"], turnaround["late"]), (0, 1))

    def test_it_opens_the_turnaround_report_with_the_same_count(self):
        self.released_sample()
        turnaround = self.insights()["turnaround"]
        self.assertEqual(self.opens(turnaround["to"]), sum(b["value"] for b in turnaround["bands"]))

    def test_nothing_released_has_no_average(self):
        self.register_sample()
        turnaround = self.insights()["turnaround"]
        self.assertIsNone(turnaround["mean"])
        self.assertEqual(sum(b["value"] for b in turnaround["bands"]), 0)


class EquipmentTests(InsightBase):
    def instrument(self, code, due=None, status=InstrumentStatus.IN_SERVICE):
        i = Instrument.objects.create(code=code, name=code, type="HPLC", location="Lab", status=status,
                                      created_by=self.admin)
        if due is not None:
            CalibrationEvent.objects.create(
                instrument=i, kind=CalibrationKind.CALIBRATION, performed_at=timezone.now() - timedelta(days=10),
                performed_by=self.admin, outcome=CalibrationOutcome.PASS, reference=f"CAL-{code}",
                next_due=timezone.localdate() + timedelta(days=due), recorded_by=self.admin,
            )
        return i

    def material(self, code, expires_in, status=MaterialStatus.AVAILABLE):
        return Material.objects.create(
            kind=MaterialKind.REFERENCE_STANDARD, code=code, name=code, lot=code, received_on=timezone.localdate(),
            expiry_date=timezone.localdate() + timedelta(days=expires_in), status=status, created_by=self.admin,
        )

    def counts(self, group):
        return {r["key"]: r["value"] for r in self.insights()["equipment"][group]["rows"]}

    def test_instruments_are_sorted_by_when_their_calibration_runs_out(self):
        self.instrument("A", due=90)
        self.instrument("B", due=10)
        self.instrument("C", due=-1)
        self.instrument("D")  # never calibrated
        self.instrument("E", due=60, status=InstrumentStatus.OUT_OF_SERVICE)
        self.instrument("F", due=60, status=InstrumentStatus.RETIRED)  # retired: no longer the lab's concern
        self.assertEqual(self.counts("instruments"), {"ok": 1, "soon": 1, "late": 2, "out": 1})

    def test_materials_are_sorted_by_their_expiry(self):
        self.material("S1", 200)
        self.material("S2", 12)
        self.material("S3", -4)
        self.material("S4", 200, status=MaterialStatus.QUARANTINED)
        self.material("S5", 200, status=MaterialStatus.RETIRED)
        self.assertEqual(self.counts("materials"), {"ok": 1, "soon": 1, "late": 1, "held": 1})

    def person_with(self, *keys, name="kit"):
        """Someone who may open the dashboard and see every sample, and the registers they are given."""
        role = Role.objects.create(code=f"R_{name.upper()}", name=f"Role of {name}")
        for key in ("report.view", "report.open.sample-register", "sample.view.all", *keys):
            RolePermissionGrant.objects.create(role=role, permission=key, reason="test")
        return User.objects.create_user(username=name, password=PW, role=role, first_name=name.title())

    def test_someone_who_may_see_neither_register_gets_no_equipment(self):
        self.instrument("A", due=90)
        self.assertNotIn("equipment", self.insights(self.person_with()))

    def test_someone_who_may_see_one_register_gets_only_that_one(self):
        self.instrument("A", due=90)
        self.material("S1", 200)
        self.assertEqual(list(self.insights(self.person_with("instrument.view"))["equipment"]), ["instruments"])
        self.assertEqual(list(self.insights(self.person_with("material.view", name="mat"))["equipment"]), ["materials"])
