"""
The demo-data seeders: seed_dashboard enters a month of lab work and seed_production the production side,
both on top of seed_demo, so the dashboard and the production screens have something to show.

They run on a clock that moves from weeks ago to now, so the tests read the result the way a person
would: through the same API, over the last 90 days, whatever day they are run on.
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from audit.models import AuditEvent
from batches.models import Batch, BatchStageSignature
from lims.models import Product, Sample, TestResult


def seed(name, **options):
    call_command(name, stdout=StringIO(), **options)


def api_as(username):
    client = APIClient(SERVER_NAME="localhost", HTTP_HOST="localhost")
    client.force_authenticate(User.objects.get(username=username))
    return client


@override_settings(DEBUG=True)  # the seeders publish a password, so they refuse to run with DEBUG off
class SeedDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):  # seeded once for the class: the tests only read it
        seed("seed_demo")
        seed("seed_dashboard")
        cls.board = api_as("sysadmin").get("/api/reports/dashboard/?period=quarter").data

    def test_it_enters_a_month_of_lab_work(self):
        self.assertEqual(Sample.objects.count(), 21)
        self.assertEqual(Batch.objects.filter(official_batch_no__startswith="DM-").count(), 13)
        received = sorted(timezone.localtime(s.received_at).date() for s in Sample.objects.all())
        self.assertGreaterEqual((received[-1] - received[0]).days, 20, "spread over three weeks, not one day")

    def test_every_chart_of_the_dashboard_has_something_in_it(self):
        charts = self.board["charts"]
        # Samples in the lab, in each position: the donut has all four slices, and some are done.
        positions = {s["label"]: s["value"] for s in charts["status"]}
        for label in ("Awaiting testing", "Under testing", "Awaiting review", "Awaiting approval", "Completed"):
            self.assertGreater(positions[label], 0, label)
        # Received and completed over the weeks (90 days are drawn week by week): several with
        # something in them, not a single bar.
        flow = charts["flow"]["points"]
        self.assertGreaterEqual(sum(1 for p in flow if p["values"][0] > 0), 4)
        self.assertGreaterEqual(sum(1 for p in flow if p["values"][1] > 0), 3)
        # Results passed and failed.
        self.assertGreater(charts["results"]["passed"], 40)
        self.assertEqual(charts["results"]["failed"], 3)
        outcomes = charts["outcomes"]["points"]
        self.assertGreaterEqual(sum(1 for p in outcomes if p["values"][0] > 0), 4)
        # Investigations: one open, one waiting for its closure to be approved, one closed.
        self.assertEqual([i["value"] for i in charts["investigations"]], [1, 1, 1])
        # The quality unit's decisions on the batches.
        decisions = {b["key"]: b["value"] for b in charts["batches"]}
        self.assertEqual((decisions["RELEASED"], decisions["QUARANTINED"], decisions["REJECTED"]), (3, 1, 1))
        self.assertGreater(decisions["WAITING"], 3)
        # Who holds the open work.
        self.assertGreaterEqual(len(charts["analysts"]), 3)
        self.assertTrue(any(a["overdue"] > 0 for a in charts["analysts"]))

    def test_the_headline_figures_are_not_zero(self):
        tiles = {t["key"]: t["value"] for t in self.board["period"]}
        self.assertGreaterEqual(tiles["RECEIVED"], 20)
        self.assertGreaterEqual(tiles["COMPLETED"], 8)
        self.assertNotEqual(tiles["TURNAROUND"], "—")
        now = {t["key"]: t["value"] for t in self.board["now"]}
        self.assertGreater(now["OVERDUE"], 0)
        self.assertGreater(now["INVESTIGATE"], 0)

    def test_the_records_are_dated_in_the_order_they_were_made(self):
        """Nothing is edited afterwards: the trail reads in order, and none of it is in the future."""
        times = list(AuditEvent.objects.order_by("id").values_list("at", flat=True))
        self.assertGreater(len(times), 200)
        self.assertEqual(times, sorted(times))
        self.assertLess(times[-1], timezone.now())
        self.assertLess(times[0], timezone.now() - timedelta(days=20))

    def test_it_runs_once_and_says_so(self):
        with self.assertRaisesMessage(CommandError, "already on record"):
            seed("seed_dashboard")
        self.assertEqual(Sample.objects.count(), 21)

    def test_the_clock_is_back_to_normal_afterwards(self):
        self.assertLess(abs((timezone.now() - timezone.localtime()).total_seconds()), 5)

    def test_a_failed_result_is_what_it_says(self):
        failed = TestResult.objects.filter(outcome="FAIL", is_superseded=False)
        self.assertEqual(failed.count(), 3)
        self.assertEqual(len({f.sample_id for f in failed}), 3)


@override_settings(DEBUG=True)
class SeedDashboardRefusalTests(TestCase):
    def test_a_dry_run_leaves_nothing_behind(self):
        seed("seed_demo")
        seed("seed_dashboard", dry_run=True)
        self.assertEqual(Sample.objects.count(), 0)
        self.assertFalse(Batch.objects.exists())

    def test_it_needs_the_demo_accounts(self):
        with self.assertRaisesMessage(CommandError, "Run seed_demo first"):
            seed("seed_dashboard")


class SeedRefusesInProductionTests(TestCase):
    @override_settings(DEBUG=False)
    def test_neither_seeder_runs_with_debug_off(self):
        for name in ("seed_dashboard", "seed_production"):
            with self.assertRaisesMessage(CommandError, "never runs in production"):
                seed(name)


@override_settings(DEBUG=True)
class SeedProductionTests(TestCase):
    @classmethod
    def setUpTestData(cls):  # seeded once for the class: the tests only read it
        seed("seed_demo")
        seed("seed_production")

    def test_it_enters_the_batch_record_and_four_batches(self):
        product = Product.objects.get(code="MET-500")
        batches = Batch.objects.filter(product=product).order_by("official_batch_no")
        self.assertEqual([b.official_batch_no for b in batches], ["MET-26-001", "MET-26-002", "MET-26-003", "MET-26-004"])
        self.assertEqual(batches[0].stage_plan.stages.count(), 3)

    def test_each_batch_stands_at_its_own_point(self):
        by_no = {b.official_batch_no: b for b in Batch.objects.filter(product__code="MET-500")}
        signed = {no: BatchStageSignature.objects.filter(batch=b).count() for no, b in by_no.items()}
        # 001: two columns for dispensing and three each for the other two; 002: 2 + 2; 003: 1; 004: none.
        self.assertEqual(signed, {"MET-26-001": 8, "MET-26-002": 4, "MET-26-003": 1, "MET-26-004": 0})

    def test_the_operator_has_batch_records_waiting_and_the_supervisor_has_one_to_sign(self):
        operator = api_as("prod.operator").get("/api/tasks/").data
        waiting = {(w["batch"]["official_batch_no"], w["state"]) for w in operator["batch_stages"]}
        self.assertIn(("MET-26-004", "fill"), waiting)
        officer = api_as("prod.officer").get("/api/tasks/").data
        self.assertTrue(officer["batch_stages"] is not None)

    def test_the_dashboard_counts_the_batches(self):
        board = api_as("sysadmin").get("/api/reports/dashboard/?period=quarter").data
        waiting = {b["key"]: b["value"] for b in board["charts"]["batches"]}["WAITING"]
        self.assertEqual(waiting, 4)

    def test_it_runs_once_and_says_so(self):
        with self.assertRaisesMessage(CommandError, "already on record"):
            seed("seed_production")
        self.assertEqual(Batch.objects.filter(product__code="MET-500").count(), 4)



@override_settings(DEBUG=True)
class SeedProductionRefusalTests(TestCase):
    def test_a_dry_run_leaves_nothing_behind(self):
        seed("seed_demo")
        seed("seed_production", dry_run=True)
        self.assertFalse(Product.objects.filter(code="MET-500").exists())
        self.assertFalse(Batch.objects.exists())

    def test_it_needs_the_demo_accounts(self):
        with self.assertRaisesMessage(CommandError, "Run seed_demo first"):
            seed("seed_production")


@override_settings(DEBUG=True)
class SeedBothTests(TestCase):
    def test_together_they_make_one_consistent_dashboard(self):
        seed("seed_demo")
        seed("seed_dashboard")
        seed("seed_production")
        board = api_as("sysadmin").get("/api/reports/dashboard/?period=quarter").data
        waiting = {b["key"]: b["value"] for b in board["charts"]["batches"]}["WAITING"]
        self.assertGreater(waiting, 8)
        self.assertEqual(Sample.objects.count(), 21)


@override_settings(DEBUG=True)
class SeedWithReceiptChecksTests(TestCase):
    """Some labs make receipt checks on arrival, and testing waits for them: the seeder makes them too."""

    @classmethod
    def setUpTestData(cls):
        from execution.models import ChecklistItem, ReceiptCompletion
        from lims.models import Workflow

        seed("seed_demo")
        for workflow in Workflow.objects.all():
            version = workflow.current_version()
            ChecklistItem.objects.create(version=version, for_receipt=True, order=1, label="Sampling form received",
                                         response_type="CHECKBOX")
            ChecklistItem.objects.create(version=version, for_receipt=True, order=2, label="Containers received",
                                         response_type="NUMBER", min_value="1", max_value="20")
            ChecklistItem.objects.create(version=version, for_receipt=True, order=3, label="Containers sealed",
                                         response_type="YES_NO", expected="YES")
        seed("seed_dashboard")
        cls.completed = ReceiptCompletion.objects.count()

    def test_testing_started_and_the_newest_samples_wait_for_their_receipt_checks(self):
        self.assertEqual(Sample.objects.count(), 21)
        # Every sample but the two newest had its receipt checks made.
        self.assertEqual(self.completed, 19)
        self.assertGreater(TestResult.objects.count(), 70)
