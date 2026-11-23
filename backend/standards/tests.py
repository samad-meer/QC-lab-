"""
Standardization, through the API: drafting and approving specifications, the
test template library, certificate templates, labels and printable records.
"""
from django.template.loader import render_to_string

from accounts.models import LabConfig, Role, RolePermissionGrant, User
from audit.models import AuditEvent
from certificates.tests import PW, WorkflowTestBase
from lims.models import LimitType, Product, SpecStatus, TestDefinition
from .models import CertificateTemplate, TestTemplate

ASSAY = {"name": "Assay", "method": "HPLC", "unit": "%", "limit_type": "NUMERIC_RANGE", "min_value": "95",
         "max_value": "105", "decimals": 1}


def _digest(spec):
    from standards.api import _digest as digest
    return digest(spec)


class StandardsTestBase(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.author = User.objects.create_user(username="author", password=PW, role=self.roles["CHECKER"])
        self.url = f"/api/products/{self.product.id}/specifications/"

    def draft(self, user=None, reason="New pharmacopoeia limits"):
        self.login(user or self.author)
        return self.client.post(self.url, {"reason": reason}, format="json")

    def the_draft(self):
        return self.product.specifications.get(status=SpecStatus.DRAFT)

    def edit(self, spec, tests, **extra):
        self.login(self.author)
        return self.client.put(f"/api/specifications/{spec.id}/", {"tests": tests, **extra}, format="json")

    def approve(self, spec, user=None, password=PW):
        self.login(user or self.approver)
        return self.client.post(f"/api/specifications/{spec.id}/approve/",
                                {"password": password, "digest": _digest(spec)}, format="json")


class SpecificationTests(StandardsTestBase):
    def test_a_draft_starts_from_the_current_version_and_changes_nothing(self):
        before = self.product.current_specification()
        r = self.draft()
        self.assertEqual(r.status_code, 200, r.content)
        draft = self.the_draft()
        self.assertEqual(draft.version, before.version + 1)
        self.assertEqual(draft.tests.count(), before.tests.count())
        self.assertEqual(self.product.current_specification(), before)
        self.assertEqual(self.register_sample().specification, before)

    def test_only_one_draft_at_a_time_and_a_reason_is_needed(self):
        self.assertEqual(self.draft(reason="").status_code, 400)
        self.draft()
        self.assertEqual(self.draft().status_code, 400)

    def test_approving_replaces_the_version_for_later_samples_only(self):
        early = self.register_sample()
        old = self.product.current_specification()
        self.draft()
        spec = self.the_draft()
        self.edit(spec, [ASSAY])
        r = self.approve(spec)
        self.assertEqual(r.status_code, 200, r.content)
        spec.refresh_from_db()
        old.refresh_from_db()
        self.assertEqual((spec.status, old.status), (SpecStatus.EFFECTIVE, SpecStatus.SUPERSEDED))
        self.assertEqual(spec.approved_by_id, self.approver.id)
        early.refresh_from_db()
        self.assertEqual(early.specification, old)
        self.assertEqual(self.register_sample().specification, spec)

    def test_the_author_cannot_approve_their_own_draft(self):
        approver = self.approver
        RolePermissionGrant.objects.create(role=self.roles["APPROVER"], permission="spec.manage", reason="test")
        self.draft(approver)
        spec = self.the_draft()
        r = self.approve(spec, approver)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone else", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="SPEC_APPROVAL_REFUSED").exists())
        self.assertEqual(self.the_draft().status, SpecStatus.DRAFT)

    def test_approving_needs_the_password_the_permission_and_a_test(self):
        self.draft()
        spec = self.the_draft()
        self.assertEqual(self.approve(spec, password="wrong").status_code, 400)
        self.assertEqual(self.approve(spec, self.analyst).status_code, 403)
        self.edit(spec, [])
        self.assertIn("at least one test", self.approve(spec).data["detail"])

    def test_a_limit_text_is_written_for_you_unless_you_word_it(self):
        self.draft()
        spec = self.the_draft()
        self.edit(spec, [
            ASSAY,
            {"name": "Water", "limit_type": "NUMERIC_MAX", "max_value": "0.5", "unit": "%"},
            {"name": "Dissolution", "limit_type": "NUMERIC_MIN", "min_value": "80", "unit": "%"},
            {"name": "Look", "limit_type": "TEXT_COMPLIES", "text_expected": "White tablet"},
            {"name": "Note", "limit_type": "REPORT_ONLY"},
            {**ASSAY, "name": "Worded", "limit_text": "95.0% to 105.0% of label claim"},
        ])
        self.assertEqual([t.limit_text for t in spec.tests.order_by("order")], [
            "95.0 – 105.0 %", "NMT 0.50 %", "NLT 80.00 %", "White tablet", "Report", "95.0% to 105.0% of label claim",
        ])

    def test_bad_tests_are_refused(self):
        self.draft()
        spec = self.the_draft()
        for bad, message in [
            ({"limit_type": "NUMERIC_MAX"}, "name"),
            ({"name": "A"}, "kind of limit"),
            ({"name": "A", "limit_type": "NUMERIC_RANGE", "min_value": "1"}, "maximum"),
            ({"name": "A", "limit_type": "NUMERIC_RANGE", "min_value": "9", "max_value": "1"}, "above the maximum"),
            ({"name": "A", "limit_type": "TEXT_COMPLIES"}, "wording"),
            ({"name": "A", "limit_type": "REPORT_ONLY", "decimals": 9}, "between 0 and 6"),
        ]:
            r = self.edit(spec, [bad])
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn(message, r.data["detail"])

    def test_an_approved_version_is_never_changed(self):
        spec = self.product.current_specification()
        test = spec.tests.first()
        test.limit_text = "edited"
        with self.assertRaises(PermissionError):
            test.save()
        with self.assertRaises(PermissionError):
            test.delete()
        with self.assertRaises(PermissionError):
            spec.delete()
        spec.change_reason = "edited"
        with self.assertRaises(PermissionError):
            spec.save()
        r = self.edit(spec, [ASSAY])
        self.assertEqual(r.status_code, 404)

    def test_a_draft_can_be_discarded_and_leaves_a_trace(self):
        self.draft()
        spec = self.the_draft()
        self.login(self.author)
        self.assertEqual(self.client.delete(f"/api/specifications/{spec.id}/").status_code, 200)
        self.assertFalse(self.product.specifications.filter(status=SpecStatus.DRAFT).exists())
        self.assertTrue(AuditEvent.objects.filter(action="SPEC_DISCARDED").exists())

    def test_the_review_date_of_an_approved_version_can_move_with_a_reason(self):
        spec = self.product.current_specification()
        self.login(self.author)
        url = f"/api/specifications/{spec.id}/review-date/"
        self.assertEqual(self.client.patch(url, {"review_date": "2027-01-01"}, format="json").status_code, 400)
        r = self.client.patch(url, {"review_date": "2027-01-01", "reason": "Annual review"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        spec.refresh_from_db()
        self.assertEqual(str(spec.review_date), "2027-01-01")

    def test_a_new_product_gets_its_first_specification_here(self):
        product = Product.objects.create(code="NEW", name="New", section=self.section)
        self.login(self.author)
        url = f"/api/products/{product.id}/specifications/"
        self.client.post(url, {"reason": "First version"}, format="json")
        spec = product.specifications.get()
        self.assertEqual(spec.version, 1)
        self.edit(spec, [ASSAY])
        self.approve(spec)
        self.assertEqual(product.current_specification(), spec)

    def test_a_spec_can_be_read_by_anyone_but_drafted_only_with_the_permission(self):
        self.login(self.analyst)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_draft"])
        self.assertEqual(self.draft(self.analyst).status_code, 403)


class TestTemplateTests(StandardsTestBase):
    def create(self, **extra):
        self.login(self.author)
        return self.client.post("/api/test-templates/", {"code": "ASSAY-HPLC", **ASSAY, **extra}, format="json")

    def test_a_template_is_versioned_and_a_change_never_touches_a_specification(self):
        self.assertEqual(self.create().status_code, 201)
        self.draft()
        spec = self.the_draft()
        self.edit(spec, [{**ASSAY, "source": "ASSAY-HPLC v1"}])
        r = self.client.post("/api/test-templates/ASSAY-HPLC/versions/",
                             {**ASSAY, "max_value": "110", "reason": "Wider limit"}, format="json")
        self.assertEqual(r.data["version"], 2)
        test = TestDefinition.objects.get(specification=spec)
        self.assertEqual((test.source, test.limit_text), ("ASSAY-HPLC v1", "95.0 – 105.0 %"))
        rows = self.client.get("/api/test-templates/").data["results"]
        self.assertEqual([(t["code"], t["version"]) for t in rows], [("ASSAY-HPLC", 2)])

    def test_a_change_needs_a_reason_and_codes_are_unique(self):
        self.create()
        self.assertEqual(self.create(code="assay-hplc").status_code, 400)
        r = self.client.post("/api/test-templates/ASSAY-HPLC/versions/", ASSAY, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_retired_template_stops_being_offered_but_stays(self):
        self.create()
        self.client.post("/api/test-templates/ASSAY-HPLC/versions/",
                         {**ASSAY, "is_retired": True, "reason": "Method withdrawn"}, format="json")
        self.assertEqual(self.client.get("/api/test-templates/?active=1").data["count"], 0)
        self.assertEqual(self.client.get("/api/test-templates/").data["count"], 1)
        self.assertEqual(TestTemplate.objects.count(), 2)

    def test_templates_are_never_edited_or_deleted(self):
        self.create()
        template = TestTemplate.objects.get()
        template.limit_text = "x"
        with self.assertRaises(PermissionError):
            template.save()
        with self.assertRaises(PermissionError):
            template.delete()

    def test_managing_needs_the_permission(self):
        self.login(self.analyst)
        r = self.client.post("/api/test-templates/", {"code": "X", **ASSAY}, format="json")
        self.assertEqual(r.status_code, 403)


class CertificateTemplateTests(StandardsTestBase):
    def printed(self, cert):
        return render_to_string("certificates/coa.html", {
            "lh": LabConfig.get(),
            "c": cert.content, "cert": cert, "cfg": LabConfig.get(), "chain": [], "copy_number": 1,
            "is_original": True, "qr": "", "logo": "",
        })

    def certificate(self):
        sample = self.register_sample()
        self.enter_results(sample)
        return self.sign_analyst(sample)

    def template(self, **extra):
        self.login(self.admin)
        r = self.client.post("/api/certificate-templates/", {"name": "Export", **extra}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return CertificateTemplate.objects.get(pk=r.data["id"])

    def test_the_standard_template_prints_as_it_always_has(self):
        cert = self.certificate()
        self.assertEqual(cert.content["layout"]["template"], "Standard certificate")
        html = self.printed(cert)
        self.assertIn("Certificate of Analysis", html)
        self.assertIn(">Method<", html)

    def test_a_product_can_use_its_own_layout(self):
        template = self.template(title="Export Certificate", header_note="For export", show_method=False,
                                 footer_note="Valid for shipment only")
        Product.objects.filter(pk=self.product.pk).update(certificate_template=template)
        html = self.printed(self.certificate())
        self.assertIn("Export Certificate", html)
        self.assertIn("For export", html)
        self.assertIn("Valid for shipment only", html)
        self.assertNotIn(">Method<", html)

    def test_no_layout_can_leave_out_a_test_a_limit_a_result_or_a_signature(self):
        hidden = {option: False for option in CertificateTemplate.OPTIONS}
        template = self.template(**hidden)
        Product.objects.filter(pk=self.product.pk).update(certificate_template=template)
        cert = self.certificate()
        html = self.printed(cert)
        for test in cert.content["tests"]:
            self.assertIn(test["name"], html)
            self.assertIn(test["limit_text"], html)
            self.assertIn(test["value"], html)
        self.assertIn("Outcome", html)
        self.assertEqual(sorted(CertificateTemplate.OPTIONS), sorted(hidden))
        self.assertFalse({"show_results", "show_limits", "show_tests", "show_signatures"} & set(hidden))

    def test_a_signed_certificate_keeps_the_layout_it_was_signed_with(self):
        cert = self.certificate()
        self.login(self.admin)
        default = CertificateTemplate.default()
        self.client.patch(f"/api/certificate-templates/{default.id}/", {"title": "Changed later"}, format="json")
        cert.refresh_from_db()
        self.assertEqual(cert.content["layout"]["title"], "Certificate of Analysis")

    def test_one_default_and_it_cannot_be_deleted(self):
        other = self.template()
        default = CertificateTemplate.default()
        self.assertEqual(self.client.delete(f"/api/certificate-templates/{default.id}/").status_code, 400)
        self.client.patch(f"/api/certificate-templates/{other.id}/", {"is_default": True}, format="json")
        self.assertEqual(CertificateTemplate.objects.filter(is_default=True).count(), 1)
        self.assertEqual(CertificateTemplate.default(), other)

    def test_a_template_in_use_is_not_deleted(self):
        template = self.template()
        Product.objects.filter(pk=self.product.pk).update(certificate_template=template)
        self.assertEqual(self.client.delete(f"/api/certificate-templates/{template.id}/").status_code, 400)

    def listed(self):
        self.login(self.admin)
        return {t["name"]: t for t in self.client.get("/api/certificate-templates/").data["results"]}

    def test_a_template_can_be_added_read_changed_and_deleted_and_each_is_recorded(self):
        template = self.template(title="Export certificate")
        self.assertEqual(self.listed()["Export"]["title"], "Export certificate")

        r = self.client.patch(f"/api/certificate-templates/{template.id}/",
                              {"name": "Export EU", "title": "Certificate", "show_method": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        row = self.listed()["Export EU"]
        self.assertEqual((row["title"], row["show_method"]), ("Certificate", False))

        self.assertEqual(self.client.delete(f"/api/certificate-templates/{template.id}/").status_code, 204)
        self.assertNotIn("Export EU", self.listed())
        self.assertEqual(
            sorted(AuditEvent.objects.filter(action__startswith="CERT_TEMPLATE_").values_list("action", flat=True)),
            ["CERT_TEMPLATE_CHANGED", "CERT_TEMPLATE_CREATED", "CERT_TEMPLATE_DELETED"],
        )

    def test_the_default_counts_the_products_that_fall_back_to_it(self):
        template = self.template()
        default = CertificateTemplate.default().name
        everyone = Product.objects.filter(certificate_template__isnull=True).count()
        self.assertGreater(everyone, 0)
        self.assertEqual((self.listed()[default]["product_count"], self.listed()["Export"]["product_count"]), (everyone, 0))

        Product.objects.filter(pk=self.product.pk).update(certificate_template=template)
        self.assertEqual((self.listed()[default]["product_count"], self.listed()["Export"]["product_count"]), (everyone - 1, 1))

    def test_managing_needs_the_permission(self):
        self.login(self.analyst)
        r = self.client.post("/api/certificate-templates/", {"name": "X"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_product_cannot_be_moved_to_a_template_without_the_permission(self):
        template = self.template()
        role = Role.objects.create(code="PRODUCTS", name="Product keeper")
        RolePermissionGrant.objects.create(role=role, permission="product.manage", reason="test")
        self.login(User.objects.create_user(username="keeper", password=PW, role=role))
        r = self.client.patch(f"/api/product-master/{self.product.id}/",
                              {"certificate_template_id": template.id, "reason": "r"}, format="json")
        self.assertEqual(r.status_code, 403)


class PrintTests(StandardsTestBase):
    def test_a_sample_label_and_record_carry_the_trace_and_are_logged(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.login(self.frontdesk)
        r = self.client.get(f"/api/samples/{sample.id}/label/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, sample.sample_no)
        self.assertContains(r, sample.batch_no)
        self.assertTrue(AuditEvent.objects.filter(action="LABEL_PRINTED", entity_id=sample.sample_no).exists())

        r = self.client.get(f"/api/samples/{sample.id}/record/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Test results, including every replaced value")
        self.assertContains(r, "not a\n    certificate of analysis")
        self.assertTrue(AuditEvent.objects.filter(action="RECORD_PRINTED", entity_id=sample.sample_no).exists())

    def test_a_replaced_result_stays_on_the_record(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/results/", {
            "test_definition_id": self.t_assay.id, "value_numeric": "99.9", "supersede_reason": "Typing slip",
        }, format="json")
        self.login(self.frontdesk)
        self.assertContains(self.client.get(f"/api/samples/{sample.id}/record/"), "Typing slip")

    def test_a_batch_label_and_record(self):
        sample = self.register_sample()
        self.login(self.frontdesk)
        batch = sample.batch
        r = self.client.get(f"/api/batches/{batch.id}/label/")
        self.assertContains(r, batch.internal_id)
        self.assertContains(r, batch.official_batch_no)
        r = self.client.get(f"/api/batches/{batch.id}/record/")
        self.assertContains(r, sample.sample_no)

    def test_a_sample_with_no_batch_prints_its_reference(self):
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "from_batch": False, "reference": "Water point WP-3", "quantity": "1 L",
            "received_from": "Utilities", "received_at": "2026-01-10T09:00:00Z", "due_date": "2026-12-20",
            "analyst_id": self.analyst.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertContains(self.client.get(f"/api/samples/{r.data['id']}/label/"), "Water point WP-3")

    def test_prints_follow_who_can_see_the_record(self):
        sample = self.register_sample()
        other = User.objects.create_user(username="analyst2", password=PW, role=self.roles["ANALYST"])
        self.login(other)
        for url in (f"/api/samples/{sample.id}/label/", f"/api/samples/{sample.id}/record/",
                    f"/api/batches/{sample.batch_id}/label/", f"/api/batches/{sample.batch_id}/record/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_limit_types_stay_in_step_with_the_screens(self):
        self.login(self.frontdesk)
        r = self.client.get(f"/api/products/{self.product.id}/specifications/")
        self.assertEqual({t["key"] for t in r.data["limit_types"]}, set(LimitType.values))
