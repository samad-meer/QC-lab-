"""
The dashboard's charts: each slice counts what it says and opens exactly the records it counts,
for the person looking, and only what they may see.
"""
from datetime import timedelta

from django.utils import timezone

from batches.models import Batch, BatchDisposition, DispositionDecision
from lims.models import Outcome, Sample, TestResult
from qclab.testing import force_update
from quality.models import Investigation
from .tests import ReportTestBase


class ChartBase(ReportTestBase):
    def charts(self, user=None, query=""):
        self.login(user or self.approver)
        r = self.client.get(f"/api/reports/dashboard/?period=month{query}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data["charts"]

    def opens(self, slice_):
        """The records a slice leads to, counted by the report it opens."""
        path, _, query = slice_["to"].partition("?")
        return self.report(path.rsplit("/", 1)[1], query)["count"]

    def slices(self, rows):
        return {s["key"]: s for s in rows}


class DueDateTests(ChartBase):
    def due_in(self, sample, days):
        Sample.objects.filter(pk=sample.pk).update(due_date=timezone.localdate() + timedelta(days=days))

    def test_open_samples_are_split_by_how_near_their_due_date_is(self):
        late, soon, later = self.register_sample(), self.register_sample(), self.register_sample()
        self.due_in(late, -2)
        self.due_in(soon, 2)
        self.due_in(later, 20)
        done, _ = self.released_sample()
        self.due_in(done, -30)  # finished long ago: not late, not counted at all
        due = self.slices(self.charts()["due"])
        self.assertEqual({k: s["value"] for k, s in due.items()}, {"overdue": 1, "soon": 1, "later": 1})

    def test_each_slice_opens_exactly_the_samples_it_counts(self):
        for days in (-3, -1, 0, 3, 4, 30):
            self.due_in(self.register_sample(), days)
        done, _ = self.released_sample()
        self.due_in(done, -9)
        due = self.slices(self.charts()["due"])
        self.assertEqual({k: s["value"] for k, s in due.items()}, {"overdue": 2, "soon": 2, "later": 2})
        for key, slice_ in due.items():
            self.assertEqual(self.opens(slice_), slice_["value"], key)

    def test_overdue_is_the_same_as_the_dashboards_overdue_tile(self):
        self.due_in(self.register_sample(), -5)
        self.login(self.approver)
        data = self.client.get("/api/reports/dashboard/?period=month").data
        tile = next(t for t in data["now"] if t["key"] == "OVERDUE")
        self.assertEqual(self.slices(data["charts"]["due"])["overdue"]["value"], tile["value"])

    def test_a_filter_that_makes_no_sense_is_refused(self):
        self.report("sample-register", "due=whenever", code=400)

    def test_an_analyst_sees_only_the_samples_they_hold(self):
        mine, other = self.register_sample(), self.register_sample()
        self.someone_elses(other)
        self.due_in(mine, -1)
        self.due_in(other, -1)
        due = self.slices(self.charts(self.analyst)["due"])
        self.assertEqual(due["overdue"]["value"], 1)


class ResultsTests(ChartBase):
    def test_passed_and_failed_count_the_results_entered_in_the_period(self):
        self.released_sample()
        self.failed_sample()
        results = self.charts()["results"]
        entered = TestResult.objects.exclude(outcome=Outcome.REPORTED)
        self.assertEqual(results["passed"], entered.filter(outcome=Outcome.PASS).count())
        self.assertEqual(results["failed"], entered.filter(outcome=Outcome.FAIL).count())
        self.assertEqual(results["failed"], 1)
        self.assertGreater(results["passed"], 0)

    def test_each_slice_opens_exactly_the_results_it_counts(self):
        self.released_sample()
        self.failed_sample()
        results = self.charts()["results"]
        for counted, link in (("passed", "to_passed"), ("failed", "to_failed")):
            path, _, query = results[link].partition("?")
            self.assertEqual(self.report(path.rsplit("/", 1)[1], query)["count"], results[counted], counted)

    def test_a_period_with_no_results_says_zero_for_both(self):
        results = self.charts()["results"]
        self.assertEqual((results["passed"], results["failed"]), (0, 0))


class InvestigationTests(ChartBase):
    def open_one(self, sample):
        failed = sample.results.get(test_definition=self.t_assay, outcome="FAIL")
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "Assay below limit",
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Investigation.objects.get(pk=r.data["id"])

    def test_each_status_counts_and_opens_its_own_records(self):
        first = self.open_one(self.failed_sample())
        second = self.open_one(self.failed_sample())
        third = self.open_one(self.failed_sample())
        Investigation.objects.filter(pk=second.pk).update(status="PENDING_CLOSURE")
        Investigation.objects.filter(pk=third.pk).update(status="CLOSED", closed_at=timezone.now())
        rows = self.slices(self.charts()["investigations"])
        self.assertEqual({k: s["value"] for k, s in rows.items()}, {"OPEN": 1, "PENDING_CLOSURE": 1, "CLOSED": 1})
        for key, slice_ in rows.items():
            self.assertEqual(self.opens(slice_), slice_["value"], key)
        self.assertEqual(first.status, "OPEN")

    def test_one_closed_before_the_period_is_not_counted_as_closed_in_it(self):
        old = self.open_one(self.failed_sample())
        Investigation.objects.filter(pk=old.pk).update(status="CLOSED", closed_at=timezone.now() - timedelta(days=90))
        self.assertEqual(self.slices(self.charts()["investigations"])["CLOSED"]["value"], 0)

    def test_whoever_sees_every_sample_sees_every_case_and_others_only_theirs(self):
        sample = self.failed_sample()
        self.open_one(sample)
        self.assertEqual(sum(s["value"] for s in self.charts(self.frontdesk)["investigations"]), 1)
        self.assertEqual(sum(s["value"] for s in self.charts(self.analyst)["investigations"]), 1, "their own sample")
        self.someone_elses(sample)
        self.assertEqual(sum(s["value"] for s in self.charts(self.analyst)["investigations"]), 0)


class BatchTests(ChartBase):
    def decide(self, batch, decision):
        BatchDisposition.objects.create(batch=batch, decision=decision, reason="Reviewed", decided_by=self.approver,
                                        basis={}, basis_hash="0" * 64)

    def test_batches_are_counted_by_the_latest_decision_or_none(self):
        self.register_sample()  # batch B-001
        released = Batch.objects.get(official_batch_no="B-001")
        waiting, rejected = (
            Batch.objects.create(product=released.product, official_batch_no=number, internal_id=f"BATCH-{number}",
                                 created_by=self.approver)
            for number in ("B-002", "B-003")
        )
        self.decide(released, DispositionDecision.QUARANTINED)
        self.decide(released, DispositionDecision.RELEASED)  # the latest counts
        self.decide(rejected, DispositionDecision.REJECTED)
        rows = self.slices(self.charts()["batches"])
        self.assertEqual({k: s["value"] for k, s in rows.items()},
                         {"RELEASED": 1, "QUARANTINED": 0, "REJECTED": 1, "WAITING": 1})
        self.assertEqual((waiting.dispositions.count(), rejected.dispositions.count()), (0, 1))

    def test_someone_who_sees_no_batches_gets_no_chart_of_them(self):
        self.register_sample()
        self.assertNotIn("batches", self.charts(self.analyst))
        self.assertIn("batches", self.charts(self.approver))

    def test_a_batch_registered_before_the_period_is_left_out(self):
        self.register_sample()
        force_update(Batch.objects.filter(official_batch_no="B-001"), created_at=timezone.now() - timedelta(days=120))
        rows = self.slices(self.charts()["batches"])
        self.assertEqual(sum(s["value"] for s in rows.values()), 0)
