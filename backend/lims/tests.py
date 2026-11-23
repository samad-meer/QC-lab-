from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from audit.models import AuditEvent
from .evaluation import ResultValueError, evaluate, parse_numeric
from .models import (
    LimitType, Outcome, Product, Sample, Section, SpecStatus, Specification, TestDefinition,
    Workflow, WorkflowStage,
)
from .numbering import next_sample_no


def make_test(**kw):
    """Unsaved TestDefinition — evaluate() only reads fields."""
    defaults = dict(name="T", limit_text="x", decimals=1)
    defaults.update(kw)
    return TestDefinition(**defaults)


class EvaluationTests(TestCase):
    def test_range_pass_and_fail(self):
        t = make_test(limit_type=LimitType.NUMERIC_RANGE, min_value=Decimal("95.0"), max_value=Decimal("105.0"))
        self.assertEqual(evaluate(t, "100.0", ""), Outcome.PASS)
        self.assertEqual(evaluate(t, "94.9", ""), Outcome.FAIL)
        self.assertEqual(evaluate(t, "105.1", ""), Outcome.FAIL)

    def test_rounding_half_up_at_the_limit(self):
        # The documented policy: 98.45 rounds to 98.5 (ROUND_HALF_UP) and
        # therefore PASSES a "not less than 98.5" limit.
        t = make_test(limit_type=LimitType.NUMERIC_MIN, min_value=Decimal("98.5"), decimals=1)
        self.assertEqual(evaluate(t, "98.45", ""), Outcome.PASS)
        self.assertEqual(evaluate(t, "98.44", ""), Outcome.FAIL)

    def test_nmt(self):
        t = make_test(limit_type=LimitType.NUMERIC_MAX, max_value=Decimal("0.5"), decimals=2)
        self.assertEqual(evaluate(t, "0.50", ""), Outcome.PASS)
        self.assertEqual(evaluate(t, "0.51", ""), Outcome.FAIL)

    def test_text_complies_case_insensitive(self):
        t = make_test(limit_type=LimitType.TEXT_COMPLIES, text_expected="Complies")
        self.assertEqual(evaluate(t, None, "complies"), Outcome.PASS)
        self.assertEqual(evaluate(t, None, "  COMPLIES "), Outcome.PASS)
        self.assertEqual(evaluate(t, None, "Does not comply"), Outcome.FAIL)

    def test_report_only(self):
        t = make_test(limit_type=LimitType.REPORT_ONLY)
        self.assertEqual(evaluate(t, "76.1", ""), Outcome.REPORTED)
        self.assertEqual(evaluate(t, None, "75.9 - 76.3"), Outcome.REPORTED)

    def test_missing_value_rejected(self):
        t = make_test(limit_type=LimitType.NUMERIC_RANGE, min_value=Decimal("1"), max_value=Decimal("2"))
        with self.assertRaises(ResultValueError):
            evaluate(t, None, "")
        t2 = make_test(limit_type=LimitType.REPORT_ONLY)
        with self.assertRaises(ResultValueError):
            evaluate(t2, None, "")


class NumericInputTests(TestCase):
    def test_json_float_keeps_its_decimal_literal(self):
        # Decimal(2.675) would be 2.67499… and round HALF_UP to 2.67, silently
        # breaking the documented policy. Going through str() keeps 2.675 → 2.68.
        self.assertEqual(parse_numeric(2.675), Decimal("2.675"))
        t = make_test(limit_type=LimitType.NUMERIC_MIN, min_value=Decimal("2.68"), decimals=2)
        self.assertEqual(evaluate(t, 2.675, ""), Outcome.PASS)

    def test_oversized_and_nonsense_values_rejected_not_crashed(self):
        for bad in ["1e30", "999999999", "abc", "NaN", "Infinity"]:
            with self.assertRaises(ResultValueError, msg=bad):
                parse_numeric(bad)

    def test_report_only_validates_its_number_too(self):
        t = make_test(limit_type=LimitType.REPORT_ONLY)
        # Text is fine for a report-only test…
        self.assertEqual(evaluate(t, None, "75.9 - 76.3"), Outcome.REPORTED)
        # …but a numeric that cannot be stored must be refused up front.
        with self.assertRaises(ResultValueError):
            parse_numeric("1e30")


class NumberingTests(TestCase):
    def test_sequential_and_per_section(self):
        gf = Section.objects.create(code="GF", name="General Formulation")
        api = Section.objects.create(code="API", name="API")
        a = next_sample_no(gf)
        b = next_sample_no(gf)
        c = next_sample_no(api)
        year = a.split("-")[1]
        self.assertEqual(a, f"GF-{year}-0001")
        self.assertEqual(b, f"GF-{year}-0002")
        self.assertEqual(c, f"API-{year}-0001")


class WorkflowAdminTests(TestCase):
    """An administrator defines the review stages; the history of every version is kept."""

    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.section = Section.objects.create(code="GF", name="General Formulation")
        self.product = Product.objects.create(code="P1", name="Product One", section=self.section)
        self.admin = User.objects.create_user(username="admin", password="pw-12345-x",
                                              role=self.roles["ADMIN"], first_name="Ada")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def stages(self, *pairs):
        return [{"name": name, "signature_title": f"{name} by", "holder_title": "", "role_id": role.id}
                for name, role in pairs]

    def create(self, name="Sterile products", stages=None):
        return self.client.post("/api/workflows/", {
            "name": name,
            "stages": stages if stages is not None else self.stages(
                ("Checked", self.roles["CHECKER"]), ("Approved", self.roles["APPROVER"])),
        }, format="json")

    def test_create_a_workflow_and_give_it_to_a_product(self):
        r = self.create()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["version"], 1)
        self.assertEqual([s["name"] for s in r.data["stages"]], ["Checked", "Approved"])
        self.assertTrue(AuditEvent.objects.filter(action="WORKFLOW_CREATED").exists())

        r = self.client.put(f"/api/products/{self.product.id}/workflow/",
                            {"workflow_id": r.data["id"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.product.refresh_from_db()
        self.assertEqual(self.product.review_workflow().name, "Sterile products")
        self.assertTrue(AuditEvent.objects.filter(action="PRODUCT_WORKFLOW_CHANGED").exists())

        # Back to the default.
        self.client.put(f"/api/products/{self.product.id}/workflow/", {"workflow_id": None}, format="json")
        self.product.refresh_from_db()
        self.assertEqual(self.product.review_workflow(), Workflow.default())

    def test_changing_the_stages_makes_a_new_version_and_keeps_the_old(self):
        wf_id = self.create().data["id"]
        new = self.stages(("Approved", self.roles["APPROVER"]))
        r = self.client.put(f"/api/workflows/{wf_id}/stages/", {"stages": new, "reason": "CR-7"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["version"], 2)
        # Saving the same stages again is not a change.
        r = self.client.put(f"/api/workflows/{wf_id}/stages/", {"stages": new}, format="json")
        self.assertEqual(r.data["version"], 2)

        history = self.client.get(f"/api/workflows/{wf_id}/history/").data
        self.assertEqual([(v["version"], len(v["stages"])) for v in history], [(2, 1), (1, 2)])
        self.assertEqual(history[0]["reason"], "CR-7")

    def test_stages_are_never_edited_in_place(self):
        stage = WorkflowStage.objects.filter(version__workflow=Workflow.default()).first()
        stage.name = "Something else"
        with self.assertRaises(PermissionError):
            stage.save()

    def test_the_stages_must_make_sense(self):
        self.assertEqual(self.create(stages=[]).status_code, 400)
        r = self.create(stages=[{"name": "Checked", "signature_title": "Checked by", "role_id": None}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Choose who signs", r.data["detail"])
        r = self.create(stages=[{"name": "", "signature_title": "x", "role_id": self.roles["CHECKER"].id}])
        self.assertEqual(r.status_code, 400)

    def test_an_administrator_cannot_make_their_own_role_a_signer(self):
        r = self.create(stages=self.stages(("Approved", self.roles["ADMIN"])))
        self.assertEqual(r.status_code, 400)
        self.assertIn("your own role", r.data["detail"])

    def test_one_default_at_a_time(self):
        wf_id = self.create().data["id"]
        r = self.client.patch(f"/api/workflows/{wf_id}/", {"is_default": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(list(Workflow.objects.filter(is_default=True).values_list("id", flat=True)), [wf_id])

    def test_a_workflow_samples_went_through_cannot_be_deleted(self):
        unused = self.create("Unused").data["id"]
        self.assertEqual(self.client.delete(f"/api/workflows/{unused}/").status_code, 204)

        used = self.create("Used").data["id"]
        spec = Specification.objects.create(product=self.product, version=1,
                                            status=SpecStatus.EFFECTIVE, effective_date="2026-01-01")
        self.product.workflow_id = used
        self.product.save()
        Sample.objects.create(
            sample_no="GF-X-1", product=self.product, specification=spec, section=self.section,
            batch_no="B", quantity="1", received_from="P", received_at=timezone.now(),
            due_date=timezone.localdate(), assigned_analyst=self.admin, registered_by=self.admin,
        )
        self.product.workflow = None
        self.product.save()
        r = self.client.delete(f"/api/workflows/{used}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("stays on record", r.data["detail"])

    def test_only_workflow_managers_reach_the_api(self):
        analyst = User.objects.create_user(username="ann", password="pw-12345-x", role=self.roles["ANALYST"])
        self.client.force_authenticate(analyst)
        self.assertEqual(self.client.get("/api/workflows/").status_code, 403)
        self.assertEqual(self.create().status_code, 403)

