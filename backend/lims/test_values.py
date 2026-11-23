"""What is judged, stored and printed is one number, and a limit is never rounded away."""
from datetime import timedelta
from decimal import Decimal as D

from django.test import SimpleTestCase
from django.utils import timezone

from certificates.tests import WorkflowTestBase
from .evaluation import ResultValueError, decimals_of, evaluate, parse_numeric, reporting_decimals
from .models import LimitType, Sample, TestDefinition, TestResult


def test_of(limit_type, decimals=2, lo=None, hi=None):
    return TestDefinition(name="T", limit_type=limit_type, min_value=lo, max_value=hi, decimals=decimals,
                          limit_text="the limit", text_expected="Complies")


class RoundingTests(SimpleTestCase):
    def test_a_result_is_never_rounded_more_coarsely_than_its_limit(self):
        self.assertEqual(evaluate(test_of(LimitType.NUMERIC_MAX, 0, hi=D("0.10")), D("0.40"), ""), "FAIL")
        self.assertEqual(evaluate(test_of(LimitType.NUMERIC_MAX, 1, hi=D("0.14")), D("0.149"), ""), "FAIL")
        self.assertEqual(evaluate(test_of(LimitType.NUMERIC_MIN, 0, lo=D("97.6")), D("97.5"), ""), "FAIL")

    def test_a_limit_read_back_from_the_column_needs_no_more_places_than_it_was_written_to(self):
        self.assertEqual(decimals_of(D("95.000000")), 0)
        self.assertEqual(decimals_of(D("0.100000")), 1)
        self.assertEqual(reporting_decimals(test_of(LimitType.NUMERIC_MAX, 1, hi=D("0.050000"))), 2)

    def test_half_up_at_the_limit_still_applies(self):
        self.assertEqual(evaluate(test_of(LimitType.NUMERIC_MIN, 1, lo=D("98.5")), D("98.45"), ""), "PASS")

    def test_more_decimal_places_than_can_be_stored_are_refused(self):
        for value in ("5.0049999", "99999999.9999999", "0.0000001"):
            with self.subTest(value), self.assertRaises(ResultValueError):
                parse_numeric(value)
        self.assertEqual(parse_numeric("5.000000000"), D("5"))


class BelowLimitTests(SimpleTestCase):
    nmt = test_of(LimitType.NUMERIC_MAX, 2, hi=D("0.10"))

    def test_a_result_below_what_the_method_can_measure_passes_a_maximum(self):
        for text in ("<0.05", "< 0.05", "ND", "nd", "Not detected"):
            with self.subTest(text):
                self.assertEqual(evaluate(self.nmt, None, text), "PASS")

    def test_it_cannot_claim_more_than_the_method_shows(self):
        with self.assertRaises(ResultValueError):
            evaluate(self.nmt, None, "<0.50")

    def test_anything_else_is_not_a_result(self):
        for text in ("low", "<", "<abc", "0.05%"):
            with self.subTest(text), self.assertRaises(ResultValueError):
                evaluate(self.nmt, None, text)

    def test_it_is_only_for_a_maximum(self):
        for kind, limits in ((LimitType.NUMERIC_MIN, {"lo": D("95")}),
                             (LimitType.NUMERIC_RANGE, {"lo": D("95"), "hi": D("105")})):
            with self.subTest(kind), self.assertRaises(ResultValueError):
                evaluate(test_of(kind, 1, **limits), None, "ND")


class OneNumberEverywhereTests(WorkflowTestBase):
    def set_assay(self, **limits):
        TestDefinition.objects.filter(pk=self.t_assay.pk).update(**limits)
        self.t_assay.refresh_from_db()

    def released(self, sample):
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        cert.refresh_from_db()
        return cert

    def assay_on(self, cert):
        return next(t for t in cert.content["tests"] if t["name"] == self.t_assay.name)

    def test_a_certificate_cannot_print_a_value_past_the_limit_it_passed(self):
        self.set_assay(limit_type=LimitType.NUMERIC_MAX, min_value=None, max_value=D("5.00"), decimals=2,
                       limit_text="NMT 5.00 %")
        sample = self.register_sample()
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_numeric": "5.0049999"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("too many decimal places", r.data["detail"])

    def test_every_screen_gets_the_value_the_certificate_prints(self):
        self.set_assay(limit_type=LimitType.NUMERIC_MIN, min_value=D("98.5"), max_value=None, decimals=1,
                       limit_text="NLT 98.5 %")
        sample = self.register_sample()
        r = self.enter_results(sample, assay="98.45")
        self.assertEqual((r.data["reported"], r.data["outcome"]), ("98.5", "PASS"))
        self.assertEqual(self.assay_on(self.released(sample))["value"], "98.5")

    def test_a_result_below_the_method_limit_reaches_the_certificate_as_written(self):
        self.set_assay(limit_type=LimitType.NUMERIC_MAX, min_value=None, max_value=D("0.10"), decimals=2,
                       limit_text="NMT 0.10 %")
        sample = self.register_sample()
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/results/",
                         {"test_definition_id": self.t_desc.id, "value_text": "Complies"}, format="json")
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_text": "<0.05"}, format="json")
        self.assertEqual((r.status_code, r.data["outcome"]), (201, "PASS"))
        self.assertIsNone(TestResult.objects.get(pk=r.data["id"]).value_numeric)
        self.assertEqual(self.assay_on(self.released(sample))["value"], "<0.05")


class PastExpiryTests(WorkflowTestBase):
    def register(self, **extra):
        self.login(self.frontdesk)
        return self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "OLD-1", "quantity": "60 tablets",
            "received_from": "Production", "received_at": timezone.now().isoformat(),
            "due_date": (timezone.localdate() + timedelta(days=3)).isoformat(), "analyst_id": self.analyst.id,
            "manufacturing_date": "2018-01-01", "expiry_date": "2020-01-01", **extra,
        }, format="json")

    def test_an_expired_batch_needs_a_reason(self):
        r = self.register()
        self.assertEqual(r.status_code, 400)
        self.assertIn("expired on 01-Jan-2020", r.data["expiry_date"][0])
        self.assertFalse(Sample.objects.exists())

    def test_the_reason_prints_on_the_certificate(self):
        r = self.register(past_expiry_reason="Complaint investigation")
        self.assertEqual(r.status_code, 201, r.content)
        sample = Sample.objects.get(pk=r.data["id"])
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(cert.content["past_expiry"], "Complaint investigation")

    def test_a_batch_still_in_date_needs_nothing(self):
        r = self.register(expiry_date=(timezone.localdate() + timedelta(days=30)).isoformat())
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["past_expiry_reason"], "")
        self.enter_results(Sample.objects.get(pk=r.data["id"]))
        cert = self.sign_analyst(Sample.objects.get(pk=r.data["id"]))
        self.assertNotIn("past_expiry", cert.content)
