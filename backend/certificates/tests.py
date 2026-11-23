"""
End-to-end tests of the journey in the brief, and of the three rules —
through the default review workflow and through workflows with fewer and
more review stages.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import LabConfig, Role, RolePermissionGrant, User
from qclab.testing import relax_failure_rules
from audit.models import AuditEvent
from lims.models import (
    LimitType, Product, Sample, SampleSource, SampleStatus, Section, SpecStatus, Specification, TestDefinition,
    TestResult, Workflow, WorkflowStage, WorkflowVersion,
)
from .models import CertStatus, Certificate, Signature

PW = "test-pass-123"


def due() -> str:
    """Two weeks out — a fixed date would fall behind the receipt date as time passes."""
    return (timezone.localdate() + timedelta(days=14)).isoformat()


class WorkflowTestBase(TestCase):
    def setUp(self):
        relax_failure_rules()
        self.section = Section.objects.create(code="GF", name="General Formulation")
        # The front desk picks "Received from" from this list.
        for name in ("Production", "Utilities"):
            SampleSource.objects.create(name=name)
        self.product = Product.objects.create(code="PCM-500", name="Paracetamol 500 mg Tablets", section=self.section)
        self.spec = Specification.objects.create(
            product=self.product, version=1, status=SpecStatus.EFFECTIVE, effective_date="2026-01-01"
        )
        self.t_desc = TestDefinition.objects.create(
            specification=self.spec, order=0, name="Description",
            limit_type=LimitType.TEXT_COMPLIES, text_expected="Complies", limit_text="White tablets",
        )
        self.t_assay = TestDefinition.objects.create(
            specification=self.spec, order=1, name="Assay", unit="%",
            limit_type=LimitType.NUMERIC_RANGE, min_value="95.0", max_value="105.0",
            decimals=1, limit_text="95.0 – 105.0 %",
        )

        # Roles are data now — the seeded system roles come from migration
        # accounts/0003, so tests exercise the same rows production uses.
        self.roles = {r.code: r for r in Role.objects.all()}

        def mk(username, role_code, sections=()):
            u = User.objects.create_user(
                username=username, password=PW,
                role=self.roles[role_code], first_name=username.title(),
            )
            u.sections.set(sections)
            return u

        self.frontdesk = mk("frontdesk", "FRONT_DESK")
        self.analyst = mk("analyst", "ANALYST", [self.section])
        self.checker = mk("checker", "CHECKER", [self.section])
        self.approver = mk("labhead", "APPROVER", [self.section])
        self.admin = mk("sysadmin", "ADMIN")
        self.client = APIClient()

    # -- helpers ------------------------------------------------------------
    def login(self, user):
        self.client.force_authenticate(user)

    def register_sample(self):
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "B-001", "quantity": "60 tablets",
            "received_from": "Production", "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": self.analyst.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Sample.objects.get(pk=r.data["id"])

    def enter_results(self, sample, assay="99.5"):
        self.login(self.analyst)
        r1 = self.client.post(f"/api/samples/{sample.id}/results/",
                              {"test_definition_id": self.t_desc.id, "value_text": "Complies"}, format="json")
        self.assertEqual(r1.status_code, 201, r1.content)
        r2 = self.client.post(f"/api/samples/{sample.id}/results/",
                              {"test_definition_id": self.t_assay.id, "value_numeric": assay}, format="json")
        self.assertEqual(r2.status_code, 201, r2.content)
        return r2

    def sign_analyst(self, sample):
        r = self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Certificate.objects.get(pk=r.data["id"])

    def sign(self, cert, user, stage=None):
        """Sign the review stage the certificate is waiting at, as `user`."""
        self.login(user)
        body = {"password": PW} if stage is None else {"password": PW, "stage": stage}
        return self.client.post(f"/api/certificates/{cert.id}/sign/", body, format="json")

    def send_back(self, cert, user, comment):
        self.login(user)
        return self.client.post(f"/api/certificates/{cert.id}/return/", {"comment": comment}, format="json")

    def make_workflow(self, name, stages):
        """stages: [(stage name, signature title, role)] — built directly, as an admin would."""
        version = WorkflowVersion.objects.create(workflow=Workflow.objects.create(name=name), version=1)
        for order, (stage_name, title, role) in enumerate(stages, start=1):
            WorkflowStage.objects.create(
                version=version, order=order, code=stage_name.upper().replace(" ", "_"),
                name=stage_name, signature_title=title, role=role,
            )
        return version.workflow


class HappyPathTests(WorkflowTestBase):
    def test_full_journey_to_print(self):
        sample = self.register_sample()
        self.assertRegex(sample.sample_no, r"^GF-\d{4}-0001$")
        self.assertEqual(sample.status, SampleStatus.RECEIVED)

        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        sample.refresh_from_db()
        self.assertEqual(sample.status, SampleStatus.IN_REVIEW)
        self.assertEqual(sample.review_stage.code, "CHECKED")
        self.assertEqual(cert.status, CertStatus.IN_REVIEW)
        self.assertEqual(len(cert.content["tests"]), 2)
        self.assertEqual(cert.content["overall"], "COMPLIES")

        r = self.sign(cert, self.checker)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["awaiting_stage"]["code"], "APPROVED")

        r = self.sign(cert, self.approver)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], CertStatus.APPROVED)
        cert.refresh_from_db()
        sample.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.APPROVED)
        self.assertEqual(sample.status, SampleStatus.APPROVED)
        self.assertEqual(cert.signatures.count(), 3)

        # printing: copy 1 (original), copy 2 (duplicate)
        r = self.client.post(f"/api/certificates/{cert.id}/print/", format="json")
        self.assertEqual(r.data["copy_number"], 1)
        r = self.client.post(f"/api/certificates/{cert.id}/print/", format="json")
        self.assertEqual(r.data["copy_number"], 2)
        r = self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=2")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"DUPLICATE COPY 2", r.content)

        # public verify page
        anon = APIClient()
        r = anon.get(f"/verify/{cert.verification_uuid}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"genuine and current", r.content)

    def test_wrong_password_refused_and_audited(self):
        sample = self.register_sample()
        self.enter_results(sample)
        r = self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": "wrong"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED").exists())


class RuleTests(WorkflowTestBase):
    def test_rule_one_signed_certificate_is_frozen(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        cert.content = {"tampered": True}
        with self.assertRaises(PermissionError):
            cert.save()
        with self.assertRaises(PermissionError):
            cert.delete()

    def test_rule_two_results_supersede_never_edit(self):
        sample = self.register_sample()
        self.enter_results(sample, assay="99.5")
        # editing the row directly is refused
        res = TestResult.objects.get(sample=sample, test_definition=self.t_assay, is_superseded=False)
        res.value_numeric = "101.0"
        with self.assertRaises(PermissionError):
            res.save()
        with self.assertRaises(PermissionError):
            res.delete()
        # correcting without a reason is refused
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_numeric": "100.2"}, format="json")
        self.assertEqual(r.status_code, 400)
        # with a reason: old stays, marked superseded
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_numeric": "100.2",
                              "supersede_reason": "Transcription error from instrument"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        rows = TestResult.objects.filter(sample=sample, test_definition=self.t_assay).order_by("entered_at")
        self.assertEqual(rows.count(), 2)
        self.assertTrue(rows[0].is_superseded)
        self.assertEqual(rows[0].supersede_reason, "Transcription error from instrument")
        self.assertFalse(rows[1].is_superseded)

    def test_rule_three_same_person_cannot_sign_twice(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        # The same human moves to the approver role and tries to approve
        # the very check they signed.
        self.checker.role = self.roles["APPROVER"]
        self.checker.save()
        r = self.sign(cert, self.checker)
        self.assertEqual(r.status_code, 400)
        self.assertIn("different person", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_REFUSED_SAME_PERSON").exists())

    def test_rule_three_survives_a_role_holding_every_signature(self):
        """
        The admin may build an all-powerful role that signs every stage — a
        small lab might need it. The different-people rule is NOT a
        permission and still holds.
        """
        omni = Role.objects.create(code="OMNI", name="Everything")
        for key in ("result.enter", "cert.sign.analysed", "sample.view.all"):
            RolePermissionGrant.objects.create(role=omni, permission=key)
        self.product.workflow = self.make_workflow(
            "Everything", [("Checked", "Checked by", omni), ("Approved", "Approved by", omni)]
        )
        self.product.save()
        self.analyst.role = omni
        self.analyst.save()

        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        # Same person, permitted to sign the next stage — still refused.
        r = self.sign(cert, self.analyst)
        self.assertEqual(r.status_code, 400)
        self.assertIn("different person", r.data["detail"])

    def test_signatures_can_never_be_deleted(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        sig = Signature.objects.get(certificate=cert)
        with self.assertRaises(PermissionError):
            sig.delete()


class OosAndSendBackTests(WorkflowTestBase):
    def test_oos_blocks_the_analyst_signature(self):
        sample = self.register_sample()
        self.enter_results(sample, assay="90.0")  # out of 95.0–105.0
        r = self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("out of specification", r.data["detail"])

    def test_send_back_supersedes_and_resign_creates_new_version(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert1 = self.sign_analyst(sample)

        # a send-back must say why
        r = self.send_back(cert1, self.checker, "")
        self.assertEqual(r.status_code, 400)
        r = self.send_back(cert1, self.checker, "Assay raw data does not match worksheet")
        self.assertEqual(r.status_code, 200, r.content)
        cert1.refresh_from_db()
        sample.refresh_from_db()
        self.assertEqual(cert1.status, CertStatus.SUPERSEDED)
        self.assertEqual(sample.status, SampleStatus.IN_TESTING)
        # the old signature is retained on the superseded version (Rule Two)
        self.assertEqual(cert1.signatures.count(), 1)

        # analyst corrects and signs again -> version 2, fresh signatures
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/results/",
                         {"test_definition_id": self.t_assay.id, "value_numeric": "99.8",
                          "supersede_reason": "Re-integrated per checker comment"}, format="json")
        cert2 = self.sign_analyst(sample)
        self.assertEqual(cert2.version, 2)
        self.assertEqual(cert2.signatures.count(), 1)

    def test_print_refused_until_approved(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        # Someone who MAY print still cannot, because it is not approved yet.
        self.login(self.approver)
        r = self.client.post(f"/api/certificates/{cert.id}/print/", format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("approved certificate", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="PRINT_REFUSED_UNAPPROVED").exists())

    def test_print_refused_without_the_permission_and_recorded(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.approve_all_as(sample)
        # The analyst's role holds no cert.print — refused, and recorded.
        self.login(self.analyst)
        r = self.client.post(f"/api/certificates/{cert.id}/print/", format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("permission to print", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="PRINT_REFUSED_NO_PERMISSION").exists())
        self.assertEqual(cert.prints.count(), 0)

    def approve_all_as(self, sample):
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        self.sign(cert, self.approver)
        cert.refresh_from_db()
        return cert

    def test_results_locked_after_analyst_signs(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_numeric": "99.0",
                              "supersede_reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)


class ReviewFixTests(WorkflowTestBase):
    """Regressions for defects found in the adversarial review."""

    def approve_all(self, sample):
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        self.sign(cert, self.approver)
        cert.refresh_from_db()
        return cert

    def test_printed_value_matches_the_outcome_beside_it(self):
        # 98.45 at 1 dp rounds HALF_UP to 98.5 and passes "NLT 98.5"; the
        # certificate must print 98.5, not 98.4 (HALF_EVEN).
        spec_test = TestDefinition.objects.create(
            specification=self.spec, order=2, name="Purity", unit="%",
            limit_type=LimitType.NUMERIC_MIN, min_value="98.5", decimals=1,
            limit_text="NLT 98.5 %",
        )
        sample = self.register_sample()
        self.enter_results(sample)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": spec_test.id, "value_numeric": "98.45"}, format="json")
        self.assertEqual(r.data["outcome"], "PASS")
        cert = self.sign_analyst(sample)
        printed = next(t for t in cert.content["tests"] if t["name"] == "Purity")
        self.assertEqual(printed["value"], "98.5")
        self.assertEqual(printed["outcome"], "PASS")

    def test_second_sign_refused_no_duplicate_live_certificate(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)
        # A double-submit must be refused, not create a second live version.
        r = self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Certificate.objects.filter(sample=sample).count(), 1)

    def test_stale_decision_refused_once_someone_else_acted(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.send_back(cert, self.checker, "Recheck the assay")
        # The approver's screen was loaded before the send-back: acting now
        # must be refused rather than resurrecting a superseded version.
        r = self.sign(cert, self.approver, stage=2)
        self.assertEqual(r.status_code, 400)
        cert.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.SUPERSEDED)

    def test_analyst_cannot_print_another_analysts_certificate(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.approve_all(sample)
        other = User.objects.create_user(username="analyst2", password=PW, role=self.roles["ANALYST"])
        other.sections.set([self.section])
        self.login(other)
        self.assertEqual(self.client.post(f"/api/certificates/{cert.id}/print/", format="json").status_code, 403)
        self.assertEqual(self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=1").status_code, 403)
        self.assertEqual(self.client.get(f"/api/certificates/{cert.id}/").status_code, 403)
        self.assertEqual(cert.prints.count(), 0)

    def test_oversized_number_is_a_clean_400_not_a_crash(self):
        sample = self.register_sample()
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_numeric": "1e30"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("too large", r.data["detail"])

    def test_batch_details_are_frozen_onto_the_certificate(self):
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "B-DATES", "quantity": "60 tablets",
            "received_from": "Production", "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": self.analyst.id,
            "manufacturing_date": "2026-01-15", "expiry_date": "2029-01-14",
            "storage_condition": "Store below 25 °C, protected from light",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sample = Sample.objects.get(pk=r.data["id"])

        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(cert.content["manufacturing_date"], "2026-01-15")
        self.assertEqual(cert.content["expiry_date"], "2029-01-14")
        self.assertIn("25 °C", cert.content["storage_condition"])

        # Changing the sample afterwards must not touch the signed content.
        Sample.objects.filter(pk=sample.pk).update(storage_condition="Anything else")
        cert.refresh_from_db()
        self.assertIn("25 °C", cert.content["storage_condition"])

    def test_batch_details_are_optional(self):
        sample = self.register_sample()  # no dates given
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(cert.content["manufacturing_date"], "")
        self.assertEqual(cert.content["expiry_date"], "")

    def test_printed_certificate_carries_the_letterhead_and_end_marker(self):
        cfg = LabConfig.get()
        cfg.company_name = "Samad Pharmaceuticals"
        cfg.address = "Plot 42, Karachi"
        cfg.licence_no = "DRAP-000123"
        cfg.footer_note = "This certificate relates only to the sample tested."
        cfg.save()

        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.approve_all(sample)
        self.client.post(f"/api/certificates/{cert.id}/print/", format="json")
        html = self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=1").content.decode()

        self.assertIn("SAMAD PHARMACEUTICALS", html)
        self.assertIn("Plot 42, Karachi", html)
        self.assertIn("DRAP-000123", html)
        self.assertIn("END OF CERTIFICATE", html)
        self.assertIn("Checked by (AM / DM)", html)
        self.assertIn("Approved by (QCM / HOD)", html)
        self.assertIn("relates only to the sample tested", html)
        self.assertIn("counter(pages)", html)  # page X of Y in the print CSS

    def test_renaming_a_user_does_not_rewrite_a_signed_certificate(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        signed_as = cert.signatures.get(meaning="ANALYSED").name_snapshot

        # The person marries, changes their name, gains a designation.
        self.analyst.first_name = "Ahmed"
        self.analyst.last_name = "Raza-Khan"
        self.analyst.designation = "Senior Analyst"
        self.analyst.save()

        cert.refresh_from_db()
        self.assertEqual(cert.signatures.get(meaning="ANALYSED").name_snapshot, signed_as)
        self.assertNotEqual(self.analyst.display_name(), signed_as)

    def test_workflow_history_cannot_be_edited(self):
        sample = self.register_sample()
        event = sample.events.first()
        event.comment = "rewritten"
        with self.assertRaises(PermissionError):
            event.save()


class AccessTests(WorkflowTestBase):
    def test_analyst_sees_only_their_samples(self):
        sample = self.register_sample()
        other = User.objects.create_user(username="analyst2", password=PW, role=self.roles["ANALYST"])
        other.sections.set([self.section])
        self.login(other)
        r = self.client.get("/api/samples/")
        self.assertEqual(r.data["results"], [])
        r = self.client.get(f"/api/samples/{sample.id}/")
        self.assertEqual(r.status_code, 403)

    def test_front_desk_cannot_pick_untrained_analyst(self):
        untrained = User.objects.create_user(username="untrained", password=PW, role=self.roles["ANALYST"])
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "B-002", "quantity": "1",
            "received_from": "Production", "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": untrained.id,
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not trained", r.data["detail"])

    def test_only_front_desk_registers(self):
        self.login(self.analyst)
        r = self.client.post("/api/samples/", {}, format="json")
        self.assertEqual(r.status_code, 403)


class DynamicWorkflowTests(WorkflowTestBase):
    """Products need different numbers of review signatures; the rules hold for all of them."""

    def setUp(self):
        super().setUp()
        self.qa_role = Role.objects.create(code="QA", name="QA officer")
        self.qa = User.objects.create_user(username="qa", password=PW, role=self.qa_role, first_name="Qa")

    def use(self, stages):
        self.product.workflow = self.make_workflow("Product workflow", stages)
        self.product.save()

    def test_a_single_review_stage_releases_after_one_signature(self):
        self.use([("Approved", "Approved by", self.roles["APPROVER"])])
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)

        # The checker has no stage in this workflow.
        self.assertEqual(self.sign(cert, self.checker).status_code, 400)
        r = self.sign(cert, self.approver)
        self.assertEqual(r.status_code, 200, r.content)
        cert.refresh_from_db()
        sample.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.APPROVED)
        self.assertEqual(sample.status, SampleStatus.APPROVED)
        self.assertEqual(cert.signatures.count(), 2)

        self.client.post(f"/api/certificates/{cert.id}/print/", format="json")
        html = self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=1").content.decode()
        self.assertIn("Approved by", html)
        self.assertNotIn("Checked by", html)

    def test_four_signatures_in_order_by_four_people(self):
        self.use([
            ("Checked", "Checked by", self.roles["CHECKER"]),
            ("QA review", "Reviewed by", self.qa_role),
            ("Approved", "Approved by", self.roles["APPROVER"]),
        ])
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)

        # Out of order is refused: the approver cannot jump ahead of QA.
        self.assertEqual(self.sign(cert, self.approver).status_code, 400)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 400)
        r = self.sign(cert, self.qa)
        self.assertEqual(r.status_code, 200, r.content)
        sample.refresh_from_db()
        self.assertEqual(sample.review_stage.name, "Approved")
        r = self.sign(cert, self.approver)
        self.assertEqual(r.status_code, 200, r.content)

        cert.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.APPROVED)
        self.assertEqual([row["title"] for row in r.data["chain"]],
                         ["Analysed by", "Checked by", "Reviewed by", "Approved by"])
        self.assertEqual(len({row["name_snapshot"] for row in r.data["chain"]}), 4)
        self.assertEqual(AuditEvent.objects.filter(action="SIGNED_STAGE").count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action="SIGNED_FINAL").count(), 1)

    def test_any_stage_can_send_the_work_back(self):
        self.use([
            ("Checked", "Checked by", self.roles["CHECKER"]),
            ("QA review", "Reviewed by", self.qa_role),
            ("Approved", "Approved by", self.roles["APPROVER"]),
        ])
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        # Only the stage the work is waiting at may send it back.
        self.assertEqual(self.send_back(cert, self.approver, "Not yours").status_code, 400)
        r = self.send_back(cert, self.qa, "Batch record reference missing")
        self.assertEqual(r.status_code, 200, r.content)
        cert.refresh_from_db()
        sample.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.SUPERSEDED)
        self.assertEqual(sample.status, SampleStatus.IN_TESTING)
        self.assertIsNone(sample.review_stage)
        self.assertTrue(AuditEvent.objects.filter(action="RETURNED_TO_ANALYST").exists())

    def test_a_signature_from_a_stale_screen_is_refused(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        # The approver's screen claims stage 2, but the certificate is at stage 1.
        r = self.sign(cert, self.checker, stage=2)
        self.assertEqual(r.status_code, 400)
        self.assertIn("no longer waiting at that stage", r.data["detail"])
        self.assertEqual(cert.signatures.count(), 1)

    def test_editing_a_workflow_never_reroutes_a_sample_already_registered(self):
        admin = self.admin
        before = self.register_sample()
        self.enter_results(before)
        cert = self.sign_analyst(before)

        # The administrator adds a QA stage to the default workflow.
        self.login(admin)
        default = Workflow.default()
        r = self.client.put(f"/api/workflows/{default.id}/stages/", {"stages": [
            {"name": "Checked", "signature_title": "Checked by", "role_id": self.roles["CHECKER"].id},
            {"name": "QA review", "signature_title": "Reviewed by", "role_id": self.qa_role.id},
            {"name": "Approved", "signature_title": "Approved by", "role_id": self.roles["APPROVER"].id},
        ], "reason": "QA review added under CR-2026-031"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["version"], 2)

        # The sample already in review still needs only its original two reviews.
        self.sign(cert, self.checker)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        cert.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.APPROVED)

        # A sample registered now goes through the new version.
        after = self.register_sample()
        self.assertEqual(after.workflow_version.version, 2)
        self.assertEqual(after.workflow_version.stages.count(), 3)

    def test_each_reviewer_sees_only_what_waits_for_their_stage(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)

        self.login(self.checker)
        self.assertEqual([s["id"] for s in self.client.get("/api/samples/").data["results"]], [sample.id])
        self.assertEqual(self.client.get("/api/summary/").data["awaiting_me"], 1)
        self.login(self.approver)
        self.assertEqual(self.client.get("/api/samples/").data["results"], [])
        self.assertEqual(self.client.get("/api/summary/").data["awaiting_me"], 0)

    def test_a_reviewer_without_view_all_sees_the_samples_waiting_for_them(self):
        self.use([("QA review", "Reviewed by", self.qa_role)])  # QA role holds no sample.view.all
        sample = self.register_sample()
        self.login(self.qa)
        self.assertEqual(self.client.get(f"/api/samples/{sample.id}/").status_code, 403)

        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.login(self.qa)
        self.assertEqual(self.client.get(f"/api/samples/{sample.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/certificates/{cert.id}/").data["my_turn"], True)
        self.assertEqual(self.sign(cert, self.qa).status_code, 200)
        # Having signed, they can still look at what they signed.
        self.assertEqual(self.client.get(f"/api/certificates/{cert.id}/").status_code, 200)
