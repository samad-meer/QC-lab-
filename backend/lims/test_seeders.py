"""
The demo seeders: seed_demo makes the sections, products and demo logins, and seed_floxcip
enters Floxcip 500 mg batch 26FB017 on top of them.

Their lab records carry dates, and the API refuses a result that uses an instrument or lot that has
run out. A seeder with those dates fixed works on the day it is written and then stops working, so one
test runs it as if it were months later.
"""
import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from batches.models import Batch, BatchStageSignature, QcStage
from labrecords.models import CalibrationEvent, Instrument, Material
from lims.models import Product, Sample, TestResult


def seed(name, **options):
    call_command(name, stdout=StringIO(), **options)


@override_settings(DEBUG=True)  # the seeders publish a password, so they refuse to run with DEBUG off
class SeedFloxcipTests(TestCase):
    def test_enters_the_batch_as_it_is_on_paper(self):
        seed("seed_demo")
        seed("seed_floxcip")

        batch = Batch.objects.get(official_batch_no="26FB017")
        self.assertEqual(batch.product.code, "FLX-500")
        self.assertEqual(QcStage.objects.filter(plan=batch.stage_plan).count(), 12)
        self.assertTrue(BatchStageSignature.objects.filter(batch=batch).exists())

        by_stage = {s.qc_stage.name: s for s in Sample.objects.filter(batch=batch).select_related("qc_stage")}
        self.assertEqual(set(by_stage), {"Final grain", "Core tablets"})
        final = TestResult.objects.filter(sample=by_stage["Final grain"], is_superseded=False)
        core = TestResult.objects.filter(sample=by_stage["Core tablets"], is_superseded=False)
        self.assertEqual({r.outcome for r in core}, {"PASS"})
        self.assertEqual(core.count(), 11)
        lod = final.get(test_definition__name="Loss on drying")
        self.assertEqual((str(lod.value_numeric), lod.outcome), ("1.840000", "FAIL"))

    def test_the_overdue_instrument_and_quarantined_lot_are_the_only_ones_kept_out(self):
        seed("seed_demo")
        seed("seed_floxcip")
        today = timezone.localdate()

        overdue = [i.code for i in Instrument.objects.all()
                   if CalibrationEvent.objects.filter(instrument=i).order_by("-id").first().next_due < today]
        self.assertEqual(overdue, ["HPLC-01"])
        self.assertEqual(list(Material.objects.filter(status="QUARANTINED").values_list("lot", flat=True)),
                         ["WS/CIP/26/03"])

    def test_the_demo_logins_include_the_production_users(self):
        seed("seed_demo")
        for username in ("prod.operator", "prod.officer", "analyst.gf2", "qa.officer", "sysadmin"):
            self.assertTrue(User.objects.filter(username=username, is_active=True).exists(), username)

    def test_it_runs_only_once_and_says_so(self):
        seed("seed_demo")
        seed("seed_floxcip")
        with self.assertRaisesMessage(CommandError, "already on record"):
            seed("seed_floxcip")
        self.assertEqual(Product.objects.filter(code="FLX-500").count(), 1)

    def test_a_dry_run_leaves_nothing_behind(self):
        seed("seed_demo")
        seed("seed_floxcip", dry_run=True)
        self.assertFalse(Product.objects.filter(code="FLX-500").exists())

    def test_it_still_works_months_later(self):
        """Calibrations, lot expiries and qualifications written for 2026 must not run out on a copy
        seeded in 2027: each keeps its date while it is ahead and otherwise runs on from the day it is seeded."""
        seed("seed_demo")
        later = datetime.datetime(2027, 4, 1, 10, 0, tzinfo=datetime.timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=later):
            seed("seed_floxcip")
            today = timezone.localdate()
            self.assertEqual(today, datetime.date(2027, 4, 1))
            overdue = [i.code for i in Instrument.objects.all()
                       if CalibrationEvent.objects.filter(instrument=i).order_by("-id").first().next_due < today]
        self.assertEqual(overdue, ["HPLC-01"], "only the instrument that is meant to be overdue may be")
        self.assertTrue(Batch.objects.filter(official_batch_no="26FB017").exists())


@override_settings(DEBUG=True)
class SeedFloxcipBatchesTests(TestCase):
    """seed_floxcip_batches adds the batches made after 26FB017, so QA has Floxcip work to sign."""

    @classmethod
    def setUpTestData(cls):  # seeded once for the class: the tests only read it
        seed("seed_demo")
        seed("seed_floxcip")
        seed("seed_floxcip_batches")

    def added(self):
        return Sample.objects.filter(batch_no__in=["26FB019", "26FB020", "26FB021"]).select_related("qc_stage")

    def test_three_samples_wait_in_qas_queue(self):
        from lims.workflow import review_queue

        queue = review_queue(User.objects.get(username="qa.officer"))
        self.assertEqual(sorted(queue.values_list("batch_no", "qc_stage__name")), [
            ("26FB020", "Core tablets"), ("26FB020", "Final grain"), ("26FB021", "Final grain")])

    def test_each_sample_is_as_far_as_it_would_have_got(self):
        where = {(s.batch_no, s.qc_stage.name): s.status for s in self.added()}
        self.assertEqual(where, {
            ("26FB019", "Final grain"): "APPROVED", ("26FB019", "Core tablets"): "APPROVED",
            ("26FB020", "Final grain"): "IN_REVIEW", ("26FB020", "Core tablets"): "IN_REVIEW",
            ("26FB021", "Final grain"): "IN_REVIEW", ("26FB021", "Core tablets"): "IN_TESTING",
        })
        self.assertFalse(TestResult.objects.filter(sample__in=self.added(), outcome="FAIL").exists())

    def test_the_work_is_spread_over_the_last_week(self):
        today = timezone.localdate()
        received = sorted(timezone.localtime(s.received_at).date() for s in self.added())
        self.assertEqual((received[0], received[-1]), (today - datetime.timedelta(days=7),
                                                       today - datetime.timedelta(days=1)))
        # Nothing waiting for QA is late: each was due a few days after it arrived, testing and reviews included.
        waiting = self.added().filter(status="IN_REVIEW")
        self.assertFalse(waiting.filter(due_date__lt=today).exists())

    def test_it_runs_only_once_and_says_so(self):
        with self.assertRaisesMessage(CommandError, "already on record"):
            seed("seed_floxcip_batches")
        self.assertEqual(self.added().count(), 6)


@override_settings(DEBUG=True)
class SeedFloxcipBatchesFirstTests(TestCase):
    def test_it_needs_seed_floxcip_first(self):
        seed("seed_demo")
        with self.assertRaisesMessage(CommandError, "Run seed_floxcip first"):
            seed("seed_floxcip_batches")

    def test_a_dry_run_leaves_nothing_behind(self):
        seed("seed_demo")
        seed("seed_floxcip")
        seed("seed_floxcip_batches", dry_run=True)
        self.assertFalse(Batch.objects.filter(official_batch_no__in=["26FB019", "26FB020", "26FB021"]).exists())
