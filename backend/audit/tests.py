"""
The activity log and analytics: readable, filterable, and derived from the
records rather than stored alongside them.
"""
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from qclab.testing import force_update
from accounts.models import Role, User
from lims.models import (
    LimitType, Outcome, Product, Sample, SampleStatus, Section,
    SpecStatus, Specification, TestDefinition, TestResult,
)
from qclab.listing import period_window
from .analytics import build
from .describe import describe
from .models import AuditEvent
from .services import record

PW = "audit-test-pass-1"


class DescribeTests(TestCase):
    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.user = User.objects.create_user(
            username="bilal", password=PW, role=self.roles["CHECKER"], first_name="Bilal"
        )

    def test_an_action_becomes_a_sentence(self):
        event = record(self.user, "SIGNED_CHECKED", "certificate", 41, sample="GF-2026-0004")
        told = describe(event)
        self.assertEqual(
            told["sentence"], "signed the certificate for GF-2026-0004 as “Checked by”"
        )
        self.assertEqual(told["severity"], "signature")
        self.assertFalse(told["notable"])

    def test_refusals_are_flagged_as_notable(self):
        event = record(self.user, "SIGN_REFUSED_SAME_PERSON", "certificate", 41,
                       sample="GF-2026-0004")
        told = describe(event)
        self.assertEqual(told["severity"], "refused")
        self.assertTrue(told["notable"])
        self.assertIn("different person", told["sentence"])

    def test_a_missing_detail_does_not_break_the_sentence(self):
        event = record(self.user, "SIGNED_CHECKED", "certificate", 41)  # no sample key
        self.assertIn("—", describe(event)["sentence"])

    def test_an_unknown_action_still_reads(self):
        event = record(self.user, "SOMETHING_NEW", "widget", 9)
        self.assertEqual(describe(event)["sentence"], "performed something new on 9")


class PeriodTests(TestCase):
    def test_periods_use_the_calendar_not_a_rolling_window(self):
        today = period_window("today")
        self.assertEqual(today.start.date(), timezone.localdate())
        self.assertEqual(today.label, "Today")

        week = period_window("week")
        self.assertEqual(week.start.weekday(), 0)  # Monday
        self.assertEqual((week.stop - week.start).days, 7)

        month = period_window("month")
        self.assertEqual(month.start.day, 1)
        self.assertEqual(month.stop.day, 1)

        everything = period_window("all")
        self.assertIsNone(everything.start)
        self.assertEqual(everything.label, "All time")


class AnalyticsApiTests(TestCase):
    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.section = Section.objects.create(code="GF", name="General Formulation")
        self.product = Product.objects.create(code="P1", name="Product One", section=self.section)
        self.spec = Specification.objects.create(
            product=self.product, version=1, status=SpecStatus.EFFECTIVE, effective_date="2026-01-01"
        )
        self.test = TestDefinition.objects.create(
            specification=self.spec, name="Assay", limit_type=LimitType.NUMERIC_RANGE,
            min_value="95", max_value="105", decimals=1, limit_text="95 – 105 %",
        )
        self.admin = User.objects.create_user(
            username="admin", password=PW, role=self.roles["ADMIN"], first_name="Ada"
        )
        self.analyst = User.objects.create_user(
            username="ahmed", password=PW, role=self.roles["ANALYST"], first_name="Ahmed"
        )
        self.analyst.sections.set([self.section])
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def make_sample(self, batch="B1"):
        return Sample.objects.create(
            sample_no=f"GF-2026-{batch}", product=self.product, specification=self.spec,
            section=self.section, batch_no=batch, quantity="1", received_from="Production",
            received_at=timezone.now(), due_date=timezone.localdate(),
            assigned_analyst=self.analyst, registered_by=self.admin,
        )

    def test_oos_rate_is_derived_from_the_results(self):
        sample = self.make_sample()
        TestResult.objects.create(sample=sample, test_definition=self.test,
                                  value_numeric="99", outcome=Outcome.PASS, entered_by=self.analyst)
        other = self.make_sample("B2")
        TestResult.objects.create(sample=other, test_definition=self.test,
                                  value_numeric="80", outcome=Outcome.FAIL, entered_by=self.analyst)
        data = build(period_window("month"))
        self.assertEqual(data["quality"]["graded_results"], 2)
        self.assertEqual(data["quality"]["failures"], 1)
        self.assertEqual(data["quality"]["oos_rate"], 50.0)

    def test_reported_results_do_not_count_towards_the_oos_rate(self):
        sample = self.make_sample()
        TestResult.objects.create(sample=sample, test_definition=self.test,
                                  value_text="76 C", outcome=Outcome.REPORTED, entered_by=self.analyst)
        data = build(period_window("month"))
        self.assertEqual(data["quality"]["graded_results"], 0)
        self.assertEqual(data["quality"]["oos_rate"], 0.0)

    def test_empty_period_returns_zeroes_not_an_error(self):
        data = build(period_window("today"))
        self.assertEqual(data["throughput"]["received"], 0)
        self.assertIsNone(data["turnaround"]["median_days"])
        self.assertEqual(data["activity"]["daily"], [])

    def test_pipeline_counts_every_status(self):
        self.make_sample()
        data = build(period_window("week"))
        self.assertEqual(set(data["pipeline"]["by_status"]), {s.value for s in SampleStatus})
        self.assertEqual(data["pipeline"]["by_status"]["RECEIVED"], 1)

    def test_endpoint_requires_audit_permission(self):
        self.client.force_authenticate(self.analyst)
        self.assertEqual(self.client.get("/api/auth/analytics/").status_code, 403)

    def test_endpoint_returns_the_period_choices(self):
        r = self.client.get("/api/auth/analytics/?period=today")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["period"], "today")
        self.assertEqual(r.data["label"], "Today")

    def test_a_nonsense_period_falls_back_rather_than_failing(self):
        r = self.client.get("/api/auth/analytics/?period=fortnight")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["period"], "week")


class AuditTrailApiTests(TestCase):
    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.admin = User.objects.create_user(
            username="admin", password=PW, role=self.roles["ADMIN"], first_name="Ada"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_events_carry_a_sentence_and_the_caller_address(self):
        self.client.get("/api/auth/audit/")  # any request populates the context
        record(self.admin, "PRINTED", "certificate", 3, sample="GF-2026-0001", copy_number=2)
        r = self.client.get("/api/auth/audit/?period=today")
        event = next(e for e in r.data["results"] if e["action"] == "PRINTED")
        self.assertEqual(
            event["sentence"], "printed copy 2 of the certificate for GF-2026-0001"
        )
        self.assertEqual(event["sample_no"], "GF-2026-0001")
        self.assertEqual(event["actor_name"], "Ada")

    def test_ip_address_is_captured_from_the_request(self):
        client = APIClient(REMOTE_ADDR="10.1.2.3")
        client.post("/api/auth/login/", {"username": "nobody", "password": "x"}, format="json")
        failed = AuditEvent.objects.get(action="LOGIN_FAILED")
        self.assertEqual(failed.ip_address, "10.1.2.3")

    @override_settings(QCLAB_BEHIND_PROXY=True)
    def test_a_proxied_request_records_the_original_caller(self):
        client = APIClient(REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="10.0.0.1, 203.0.113.9")
        client.post("/api/auth/login/", {"username": "nobody", "password": "x"}, format="json")
        self.assertEqual(AuditEvent.objects.get(action="LOGIN_FAILED").ip_address, "203.0.113.9")

    def test_events_written_outside_a_request_have_no_address(self):
        # Management commands and migrations write audit rows with no request.
        event = record(self.admin, "LOGIN", "auth", "admin")
        self.assertEqual(event.ip_address, "")

    def test_notable_filter_returns_only_refusals_and_corrections(self):
        record(self.admin, "LOGIN", "auth", "admin")
        record(self.admin, "SIGN_REFUSED_SAME_PERSON", "certificate", 1, sample="S1")
        record(self.admin, "RESULT_SUPERSEDED", "sample", "S1", test="Assay", reason="typo")
        r = self.client.get("/api/auth/audit/?period=today&notable=1")
        actions = {e["action"] for e in r.data["results"]}
        self.assertEqual(actions, {"SIGN_REFUSED_SAME_PERSON", "RESULT_SUPERSEDED"})

    def test_results_are_paginated(self):
        for i in range(60):
            record(self.admin, "LOGIN", "auth", f"u{i}")
        r = self.client.get("/api/auth/audit/?period=today&page_size=25&page=2")
        self.assertEqual(len(r.data["results"]), 25)
        self.assertEqual(r.data["page"], 2)
        self.assertGreaterEqual(r.data["count"], 60)

    def test_period_filter_narrows_the_window(self):
        record(self.admin, "LOGIN", "auth", "admin")
        old = AuditEvent.objects.create(actor=self.admin, actor_username="admin",
                                        action="LOGIN", entity="auth", entity_id="old")
        force_update(AuditEvent.objects.filter(pk=old.pk), at=timezone.now() - timezone.timedelta(days=400))
        self.assertEqual(self.client.get("/api/auth/audit/?period=today").data["count"], 1)
        self.assertGreaterEqual(self.client.get("/api/auth/audit/?period=all").data["count"], 2)