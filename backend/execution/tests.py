"""
Lab execution, end to end through the API: checklists and required
documents, acceptance and handovers, holds, retests of failed results,
waivers, comments, and the task center — each rule tested where the
server enforces it, not where a screen shows it.
"""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import override_settings
from django.utils import timezone

from accounts.models import LabConfig, Role, RolePermissionGrant
from audit.models import AuditEvent
from certificates.models import CertStatus
from certificates.services import content_hash
from certificates.tests import PW, WorkflowTestBase
from lims.models import SampleStatus, TestResult, Workflow
from notifications.models import Notification
from .models import (
    RECEIPT, TESTING, Assignment, AssignmentStatus, Attachment, ChecklistItem, ChecklistResponse,
    ReceiptCompletion, RetestRequest, RetestStatus, StepComment,
)

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class ExecutionTestBase(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.analyst2 = self.make_user("analyst2", "ANALYST", [self.section])
        self.checker2 = self.make_user("checker2", "CHECKER", [self.section])
        self.workflow = Workflow.default()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def make_user(self, username, role_code, sections=()):
        from accounts.models import User

        u = User.objects.create_user(username=username, password=PW, role=self.roles[role_code],
                                     first_name=username.title())
        u.sections.set(sections)
        return u

    def configure(self, testing=None, stages=None, **extra):
        """Save new step requirements on the default workflow, through the admin API."""
        current = [
            {"name": s.name, "signature_title": s.signature_title, "holder_title": s.holder_title,
             "role_id": s.role_id}
            for s in self.workflow.current_version().stages.all()
        ]
        for i, extra in (stages or {}).items():
            current[i].update(extra)
        self.login(self.admin)
        r = self.client.put(f"/api/workflows/{self.workflow.id}/stages/",
                            {"stages": current, "testing": testing or {}, "reason": "test", **extra}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r

    def state(self, sample, user):
        self.login(user)
        r = self.client.get(f"/api/samples/{sample.id}/execution/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def step(self, sample, user, key):
        return next(s for s in self.state(sample, user)["steps"] if s["key"] == key)

    def answer(self, sample, user, item_id, value, **extra):
        self.login(user)
        return self.client.post(f"/api/samples/{sample.id}/checklist/",
                                {"item_id": item_id, "value": value, **extra}, format="json")

    def try_sign_analyst(self, sample):
        self.login(self.analyst)
        return self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")

    def upload(self, sample, user, step, name, content, **extra):
        self.login(user)
        return self.client.post(f"/api/samples/{sample.id}/attachments/",
                                {"step": step, "file": SimpleUploadedFile(name, content), **extra},
                                format="multipart")


class ChecklistTests(ExecutionTestBase):
    def test_a_required_check_blocks_the_analyst_signature_until_answered(self):
        self.configure(testing={"checklist": [
            {"label": "Balance calibration checked", "response_type": "CHECKBOX", "required": True},
        ]})
        sample = self.register_sample()
        self.enter_results(sample)
        r = self.try_sign_analyst(sample)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Balance calibration checked", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_REFUSED_BLOCKED").exists())

        item = ChecklistItem.objects.get(label="Balance calibration checked", version=sample.workflow_version)
        self.assertEqual(self.answer(sample, self.analyst, item.id, True).status_code, 200)
        r = self.try_sign_analyst(sample)
        self.assertEqual(r.status_code, 201, r.content)

    def test_only_the_analyst_holding_the_step_can_answer_its_checklist(self):
        self.configure(testing={"checklist": [{"label": "Glassware clean", "response_type": "YES_NO"}]})
        sample = self.register_sample()
        item = ChecklistItem.objects.get(label="Glassware clean", version=sample.workflow_version)
        r = self.answer(sample, self.checker, item.id, "YES")
        self.assertIn(r.status_code, (400, 404))
        self.assertFalse(ChecklistResponse.objects.exists())

    def test_a_failing_answer_blocks_and_a_changed_answer_keeps_its_history(self):
        self.configure(testing={"checklist": [
            {"label": "System suitability", "response_type": "PASS_FAIL"},
        ]})
        sample = self.register_sample()
        self.enter_results(sample)
        item = ChecklistItem.objects.get(label="System suitability", version=sample.workflow_version)
        self.answer(sample, self.analyst, item.id, "FAIL")
        r = self.try_sign_analyst(sample)
        self.assertEqual(r.status_code, 400)
        self.assertIn("requirement is Pass", r.data["detail"])

        r = self.answer(sample, self.analyst, item.id, "PASS", reason="Re-injected after column flush")
        self.assertEqual(r.status_code, 200, r.content)
        rows = ChecklistResponse.objects.filter(sample=sample, item=item).order_by("id")
        self.assertEqual([(x.value, x.replaced_at is None) for x in rows], [("FAIL", False), ("PASS", True)])
        self.assertEqual(rows[0].change_reason, "Re-injected after column flush")
        # Never edited, never deleted.
        first = rows[0]
        first.value = "PASS"
        with self.assertRaises(PermissionError):
            first.save()
        with self.assertRaises(PermissionError):
            rows[1].delete()
        self.assertEqual(self.try_sign_analyst(sample).status_code, 201)

    def test_number_items_are_rounded_and_checked_against_their_limits(self):
        self.configure(testing={"checklist": [
            {"label": "Room temperature", "response_type": "NUMBER", "unit": "°C",
             "min_value": "15", "max_value": "25", "decimals": 1},
        ]})
        sample = self.register_sample()
        item = ChecklistItem.objects.get(label="Room temperature", version=sample.workflow_version)
        self.answer(sample, self.analyst, item.id, "25.04")
        r = ChecklistResponse.objects.get(sample=sample, item=item, replaced_at__isnull=True)
        self.assertEqual((r.value, r.conforms), ("25.0", True))
        self.answer(sample, self.analyst, item.id, "25.06", reason="Read it again")
        r = ChecklistResponse.objects.get(sample=sample, item=item, replaced_at__isnull=True)
        self.assertEqual((r.value, r.conforms), ("25.1", False))
        self.assertEqual(self.answer(sample, self.analyst, item.id, "warm").status_code, 400)

    def test_a_waiver_needs_permission_and_independence(self):
        self.configure(testing={"checklist": [
            {"label": "Second-person witness", "response_type": "CHECKBOX", "waivable": True},
        ]})
        sample = self.register_sample()
        self.enter_results(sample)
        item = ChecklistItem.objects.get(label="Second-person witness", version=sample.workflow_version)
        body = {"item_id": item.id, "reason": "Single-analyst shift, approved by QA"}
        self.login(self.checker)  # no stage.waive
        self.assertEqual(self.client.post(f"/api/samples/{sample.id}/waivers/", body, format="json").status_code, 400)
        self.login(self.approver)
        r = self.client.post(f"/api/samples/{sample.id}/waivers/", body, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(AuditEvent.objects.filter(action="REQUIREMENT_WAIVED").exists())
        self.assertEqual(self.try_sign_analyst(sample).status_code, 201)

    def test_a_non_waivable_item_cannot_be_waived(self):
        self.configure(testing={"checklist": [{"label": "Column ID recorded", "response_type": "TEXT"}]})
        sample = self.register_sample()
        item = ChecklistItem.objects.get(label="Column ID recorded", version=sample.workflow_version)
        self.login(self.approver)
        r = self.client.post(f"/api/samples/{sample.id}/waivers/", {"item_id": item.id, "reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cannot be waived", r.data["detail"])

    def test_review_stage_checklist_blocks_its_signature_and_a_waiver_cannot_sign(self):
        self.configure(stages={0: {"checklist": [
            {"label": "Raw data matches worksheet", "response_type": "YES_NO", "expected": "YES",
             "waivable": True},
        ]}})
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        r = self.sign(cert, self.checker)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Raw data matches worksheet", r.data["detail"])

        # A second checker waives it; that checker may then not sign the stage.
        item = ChecklistItem.objects.get(label="Raw data matches worksheet", version=sample.workflow_version)
        self.roles["CHECKER"].grants.create(permission="stage.waive")
        self.login(self.checker2)
        r = self.client.post(f"/api/samples/{sample.id}/waivers/", {"item_id": item.id, "reason": "Worksheet held by QA"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.sign(cert, self.checker2)
        self.assertEqual(r.status_code, 400)
        self.assertIn("waived a requirement", r.data["detail"])
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)

    def test_answers_do_not_carry_over_to_a_new_attempt(self):
        self.configure(testing={"checklist": [{"label": "Balance checked", "response_type": "CHECKBOX"}]})
        sample = self.register_sample()
        self.enter_results(sample)
        item = ChecklistItem.objects.get(label="Balance checked", version=sample.workflow_version)
        self.answer(sample, self.analyst, item.id, True)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.send_back(cert, self.checker, "Recheck the balance log").status_code, 200)
        cert.refresh_from_db()
        self.assertEqual((cert.returned_stage, cert.returned_by_id), ("CHECKED", self.checker.id))
        self.assertIsNotNone(cert.returned_at)

        testing = self.step(sample, self.analyst, TESTING)
        self.assertEqual(testing["status"], "REOPENED")
        self.assertIsNone(testing["checklist"][0]["response"])
        self.assertEqual(self.try_sign_analyst(sample).status_code, 400)
        self.answer(sample, self.analyst, item.id, True)
        self.assertEqual(self.try_sign_analyst(sample).status_code, 201)

    def test_samples_keep_the_requirements_they_were_registered_under(self):
        before = self.register_sample()
        self.configure(testing={"checklist": [{"label": "New check", "response_type": "CHECKBOX"}]})
        self.enter_results(before)
        self.assertEqual(self.try_sign_analyst(before).status_code, 201)
        self.assertEqual(self.step(self.register_sample(), self.analyst, TESTING)["checklist"][0]["item"]["label"],
                         "New check")


class WorkflowConfigTests(ExecutionTestBase):
    def test_unchanged_requirements_make_no_new_version_and_bad_items_are_refused(self):
        self.configure(testing={"checklist": [{"label": "A", "response_type": "CHECKBOX"}]})
        version = self.workflow.current_version().version
        self.configure(testing={"checklist": [{"label": "A", "response_type": "CHECKBOX"}]})
        self.assertEqual(self.workflow.current_version().version, version)

        stages = [{"name": s.name, "signature_title": s.signature_title, "role_id": s.role_id}
                  for s in self.workflow.current_version().stages.all()]
        for bad, message in [
            ({"label": "", "response_type": "CHECKBOX"}, "label"),
            ({"label": "pH", "response_type": "NUMBER", "min_value": "8", "max_value": "6"}, "minimum is above"),
            ({"label": "Look", "response_type": "CHOICE", "options": ["Only one"]}, "between 2 and 20"),
            ({"label": "Doc", "response_type": "FILE", "file_types": ["exe"]}, "not a file type"),
        ]:
            r = self.client.put(f"/api/workflows/{self.workflow.id}/stages/",
                                {"stages": stages, "testing": {"checklist": [bad]}}, format="json")
            self.assertEqual(r.status_code, 400)
            self.assertIn(message, r.data["detail"])

    def test_an_older_screen_that_sends_no_testing_settings_keeps_them(self):
        self.configure(testing={"requires_acceptance": True,
                                "checklist": [{"label": "Kept", "response_type": "CHECKBOX"}]})
        stages = [{"name": s.name, "signature_title": s.signature_title, "role_id": s.role_id}
                  for s in self.workflow.current_version().stages.all()]
        stages[0]["name"] = "Checked again"
        r = self.client.put(f"/api/workflows/{self.workflow.id}/stages/", {"stages": stages, "reason": "Test"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.data["testing"]["requires_acceptance"])
        self.assertEqual(r.data["testing"]["checklist"][0]["label"], "Kept")


class AttachmentTests(ExecutionTestBase):
    def setUp(self):
        super().setUp()
        self.configure(testing={"checklist": [
            {"label": "Chromatogram", "response_type": "FILE", "file_types": ["pdf"], "max_size_mb": 1},
        ]})
        self.sample = self.register_sample()
        self.item = ChecklistItem.objects.get(label="Chromatogram", version=self.sample.workflow_version)

    def test_a_required_document_is_answered_by_uploading_it(self):
        self.enter_results(self.sample)
        self.assertEqual(self.try_sign_analyst(self.sample).status_code, 400)
        r = self.upload(self.sample, self.analyst, TESTING, "run-1.pdf", PDF, item_id=self.item.id)
        self.assertEqual(r.status_code, 200, r.content)
        a = Attachment.objects.get()
        self.assertEqual((a.version, a.extension, a.size), (1, "pdf", len(PDF)))
        self.assertEqual(len(a.sha256), 64)
        self.assertNotIn("run-1", a.file.name)  # never the uploaded name on disk
        self.assertEqual(self.try_sign_analyst(self.sample).status_code, 201)

    def test_wrong_type_fake_content_and_oversize_files_are_refused_and_recorded(self):
        for name, content, message in [
            ("notes.png", PNG, "must be PDF"),
            ("fake.pdf", b"<html><script>alert(1)</script>", "not a genuine PDF"),
            ("big.pdf", PDF + b"0" * (1024 * 1024), "limit here is 1 MB"),
            ("run.exe", b"MZ", "not accepted"),
        ]:
            r = self.upload(self.sample, self.analyst, TESTING, name, content, item_id=self.item.id)
            self.assertEqual(r.status_code, 400, name)
            self.assertIn(message, r.data["detail"])
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.filter(action="ATTACHMENT_REFUSED").count(), 4)

    def test_new_versions_keep_the_old_and_withdrawal_needs_a_reason(self):
        self.upload(self.sample, self.analyst, TESTING, "run-1.pdf", PDF, item_id=self.item.id)
        self.upload(self.sample, self.analyst, TESTING, "run-2.pdf", PDF + b"%2", item_id=self.item.id)
        v1, v2 = Attachment.objects.order_by("version")
        self.assertEqual((v1.version, v2.version, v1.replaced_by_id), (1, 2, v2.id))
        with self.assertRaises(PermissionError):
            v1.delete()
        self.login(self.analyst)
        self.assertEqual(self.client.post(f"/api/attachments/{v2.id}/withdraw/", {"reason": ""},
                                          format="json").status_code, 400)
        r = self.client.post(f"/api/attachments/{v2.id}/withdraw/", {"reason": "Wrong sample's run"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        v2.refresh_from_db()
        self.assertIsNotNone(v2.withdrawn_at)
        # The answer that pointed at it no longer stands.
        self.assertFalse(ChecklistResponse.objects.filter(item=self.item, replaced_at__isnull=True).exists())

    def test_files_are_served_only_to_people_who_can_see_the_sample(self):
        self.upload(self.sample, self.analyst, TESTING, "run-1.pdf", PDF, item_id=self.item.id)
        a = Attachment.objects.get()
        self.login(self.analyst)
        r = self.client.get(f"/api/attachments/{a.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), PDF)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("sandbox", r["Content-Security-Policy"])
        self.login(self.analyst2)  # not assigned, no sample.view.all
        self.assertEqual(self.client.get(f"/api/attachments/{a.id}/").status_code, 404)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(f"/api/attachments/{a.id}/").status_code, (401, 403))


class RetestTests(ExecutionTestBase):
    def fail_assay(self):
        sample = self.register_sample()
        self.enter_results(sample, assay="90.0")
        return sample, TestResult.objects.get(sample=sample, test_definition=self.t_assay, is_superseded=False)

    def enter_assay(self, sample, value, reason=""):
        self.login(self.analyst)
        return self.client.post(f"/api/samples/{sample.id}/results/",
                                {"test_definition_id": self.t_assay.id, "value_numeric": value,
                                 "supersede_reason": reason}, format="json")

    def test_a_failed_result_is_never_replaced_without_an_authorized_retest(self):
        sample, failed = self.fail_assay()
        r = self.enter_assay(sample, "99.0", "Typo")
        self.assertEqual(r.status_code, 400)
        self.assertIn("never replaced directly", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="RESULT_REPLACE_REFUSED_FAILED").exists())
        failed.refresh_from_db()
        self.assertFalse(failed.is_superseded)

    def test_the_full_retest_path_keeps_the_failure_on_record(self):
        sample, failed = self.fail_assay()
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/retests/",
                             {"test_definition_id": self.t_assay.id, "reason": "Dilution error found"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        req = RetestRequest.objects.get()
        # Still refused while only requested.
        self.assertEqual(self.enter_assay(sample, "99.0").status_code, 400)

        # The analyst cannot authorize (no permission), and a requester never decides their own.
        self.login(self.analyst)
        self.assertEqual(self.client.post(f"/api/retests/{req.id}/decide/", {"action": "authorize"},
                                          format="json").status_code, 400)
        self.roles["ANALYST"].grants.create(permission="result.retest.authorize")
        self.analyst._perm_cache = None
        r = self.client.post(f"/api/retests/{req.id}/decide/", {"action": "authorize"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone independent", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="RETEST_REFUSED_NOT_INDEPENDENT").exists())

        self.login(self.approver)
        r = self.client.post(f"/api/retests/{req.id}/decide/", {"action": "authorize", "comment": "OK per OOS-12"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.enter_assay(sample, "99.0")
        self.assertEqual(r.status_code, 201, r.content)

        failed.refresh_from_db()
        req.refresh_from_db()
        self.assertTrue(failed.is_superseded)
        self.assertIn("Retest authorized by", failed.supersede_reason)
        self.assertEqual(failed.outcome, "FAIL")  # the failure itself is untouched
        self.assertEqual((req.status, req.retest_result_id), (RetestStatus.USED, failed.replaced_by_id))
        # One authorization, one retest: a second replacement is a plain correction of a pass.
        self.assertEqual(self.try_sign_analyst(sample).status_code, 201)

    def test_a_declined_retest_needs_a_reason_and_leaves_the_failure_standing(self):
        sample, failed = self.fail_assay()
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/retests/",
                         {"test_definition_id": self.t_assay.id, "reason": "Suspect"}, format="json")
        req = RetestRequest.objects.get()
        self.login(self.approver)
        self.assertEqual(self.client.post(f"/api/retests/{req.id}/decide/", {"action": "decline"},
                                          format="json").status_code, 400)
        self.client.post(f"/api/retests/{req.id}/decide/", {"action": "decline", "comment": "No assignable cause"},
                         format="json")
        req.refresh_from_db()
        self.assertEqual(req.status, RetestStatus.DECLINED)
        self.assertEqual(self.enter_assay(sample, "99.0").status_code, 400)

    def test_only_a_failed_result_can_be_retested(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/retests/",
                             {"test_definition_id": self.t_assay.id, "reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Only a failed result", r.data["detail"])


class HoldTests(ExecutionTestBase):
    def test_a_hold_stops_entry_and_signing_until_released(self):
        sample = self.register_sample()
        self.login(self.analyst)  # no sample.hold
        self.assertEqual(self.client.post(f"/api/samples/{sample.id}/hold/", {"reason": "x"},
                                          format="json").status_code, 400)
        self.login(self.checker)
        self.assertEqual(self.client.post(f"/api/samples/{sample.id}/hold/", {"reason": ""},
                                          format="json").status_code, 400)
        r = self.client.post(f"/api/samples/{sample.id}/hold/", {"reason": "Reference standard expired"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["hold"]["reason"], "Reference standard expired")

        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_desc.id, "value_text": "Complies"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("On hold since", r.data["detail"])

        self.login(self.checker)
        r = self.client.post(f"/api/samples/{sample.id}/hold/", {"release": True, "comment": "New lot received"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.enter_results(sample)
        self.assertEqual(self.try_sign_analyst(sample).status_code, 201)
        self.assertEqual(sample.holds.count(), 1)

    def test_a_hold_blocks_review_signatures_and_send_backs(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.login(self.approver)
        self.client.post(f"/api/samples/{sample.id}/hold/", {"reason": "Customer complaint on batch"}, format="json")
        self.assertEqual(self.sign(cert, self.checker).status_code, 400)
        self.assertEqual(self.send_back(cert, self.checker, "x").status_code, 400)
        cert.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.IN_REVIEW)


class AcceptanceAndHandoverTests(ExecutionTestBase):
    def test_testing_that_needs_acceptance_waits_for_the_analyst(self):
        self.configure(testing={"requires_acceptance": True})
        sample = self.register_sample()
        a = Assignment.objects.get(sample=sample, step=TESTING)
        self.assertEqual(a.status, AssignmentStatus.PENDING)

        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_desc.id, "value_text": "Complies"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Accept it first", r.data["detail"])
        r = self.client.post(f"/api/assignments/{a.id}/respond/", {"action": "accept"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.enter_results(sample)

    def test_a_declined_sample_goes_back_for_reassignment(self):
        self.configure(testing={"requires_acceptance": True})
        sample = self.register_sample()
        a = Assignment.objects.get(sample=sample, step=TESTING)
        self.login(self.analyst)
        self.assertEqual(self.client.post(f"/api/assignments/{a.id}/respond/", {"action": "reject"},
                                          format="json").status_code, 400)
        self.client.post(f"/api/assignments/{a.id}/respond/",
                         {"action": "reject", "reason": "Container seal broken"}, format="json")
        self.assertEqual(self.step(sample, self.analyst, TESTING)["status"], "DECLINED")

        self.login(self.frontdesk)
        tasks = self.client.get("/api/tasks/").data
        self.assertEqual(tasks["needs_reassigning"][0]["sample"]["id"], sample.id)
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": TESTING, "user_id": self.analyst2.id,
                              "note": "Replacement container"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.login(self.analyst2)
        pending = Assignment.objects.get(sample=sample, status=AssignmentStatus.PENDING)
        self.client.post(f"/api/assignments/{pending.id}/respond/", {"action": "accept"}, format="json")
        sample.refresh_from_db()
        self.assertEqual(sample.assigned_analyst_id, self.analyst2.id)

    def test_a_handover_moves_the_work_only_once_accepted(self):
        sample = self.register_sample()
        self.login(self.analyst)
        body = {"mode": "handover", "step": TESTING, "user_id": self.analyst2.id}
        self.assertEqual(self.client.post(f"/api/samples/{sample.id}/assignments/", body, format="json").status_code, 400)
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {**body, "note": "Assay prep done, HPLC run pending"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        sample.refresh_from_db()
        self.assertEqual(sample.assigned_analyst_id, self.analyst.id)  # still theirs

        untrained = self.make_user("analyst3", "ANALYST")
        self.login(self.frontdesk)
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": TESTING, "user_id": untrained.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("trained for", r.data["detail"])

        self.login(self.analyst2)
        self.assertIn(sample.id, [t["sample"]["id"] for t in self.client.get("/api/tasks/").data["to_accept"]])
        a = Assignment.objects.get(status=AssignmentStatus.PENDING)
        self.client.post(f"/api/assignments/{a.id}/respond/", {"action": "accept"}, format="json")
        sample.refresh_from_db()
        self.assertEqual(sample.assigned_analyst_id, self.analyst2.id)
        self.assertTrue(AuditEvent.objects.filter(action="HANDOVER_ACCEPTED").exists())

    def test_a_stage_that_must_be_taken_and_a_stage_assigned_to_someone_else(self):
        self.configure(stages={0: {"requires_acceptance": True}})
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        r = self.sign(cert, self.checker)
        self.assertEqual(r.status_code, 400)
        self.assertIn("must be taken", r.data["detail"])

        # The lab head assigns it to checker2; checker is now turned away.
        self.login(self.approver)
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": "CHECKED", "user_id": self.checker2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        a = Assignment.objects.get(status=AssignmentStatus.PENDING)
        self.login(self.checker2)
        self.client.post(f"/api/assignments/{a.id}/respond/", {"action": "accept"}, format="json")
        r = self.sign(cert, self.checker)
        self.assertEqual(r.status_code, 400)
        self.assertIn("assigned to Checker2", r.data["detail"])
        self.assertEqual(self.sign(cert, self.checker2).status_code, 200)

    def test_the_analyst_can_never_be_assigned_to_review_their_own_sample(self):
        from accounts.models import Role

        # A small lab's role that both tests and checks — legitimate, but
        # never on the same sample.
        hybrid = Role.objects.create(code="HYBRID", name="Analyst-checker")
        for key in ("result.enter", "cert.sign.analysed"):
            hybrid.grants.create(permission=key)
        self.configure(stages={0: {"role_id": hybrid.id}})
        self.analyst2.role = hybrid
        self.analyst2.save()
        other = self.make_user("hybrid2", "ANALYST", [self.section])
        other.role = hybrid
        other.save()
        sample = self.register_sample_for(self.analyst2)
        self.login(self.approver)
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": "CHECKED", "user_id": self.analyst2.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("must not be the sample's analyst", r.data["detail"])
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": "CHECKED", "user_id": other.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def register_sample_for(self, analyst):
        from django.utils import timezone
        from certificates.tests import due
        from lims.models import Sample

        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "B-002", "quantity": "60 tablets",
            "received_from": "Production", "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": analyst.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Sample.objects.get(pk=r.data["id"])


class CommentTests(ExecutionTestBase):
    def test_comments_are_threaded_and_amendments_keep_the_original(self):
        sample = self.register_sample()
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/comments/",
                             {"step": TESTING, "body": "Used column C-18 #4"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        root = StepComment.objects.get()
        self.login(self.checker)
        self.client.post(f"/api/samples/{sample.id}/comments/", {"parent_id": root.id, "body": "Which lot?"},
                         format="json")
        # Only the author can amend — others reply.
        r = self.client.post(f"/api/samples/{sample.id}/comments/", {"amends_id": root.id, "body": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/comments/",
                             {"amends_id": root.id, "body": "Used column C-18 #5"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        testing = next(s for s in r.data["steps"] if s["key"] == TESTING)
        thread = testing["comments"][0]
        self.assertEqual(thread["body"], "Used column C-18 #5")
        self.assertEqual([v["body"] for v in thread["versions"]], ["Used column C-18 #4", "Used column C-18 #5"])
        self.assertEqual(thread["replies"][0]["body"], "Which lot?")
        self.assertIsNotNone(thread["created_at"])
        with self.assertRaises(PermissionError):
            root.delete()
        root.body = "edited"
        with self.assertRaises(PermissionError):
            root.save()


class CommentPermissionTests(ExecutionTestBase):
    def take_away(self, role_code):
        RolePermissionGrant.objects.filter(
            role=self.roles[role_code], permission="sample.comment", revoked_at__isnull=True
        ).update(revoked_at=timezone.now())

    def test_every_role_keeps_commenting_when_the_permission_arrives(self):
        # Production's roles came later (accounts/0024) and see no samples to comment on.
        for role in Role.objects.exclude(code__startswith="PRODUCTION_"):
            self.assertIn("sample.comment", role.permissions(), role.code)

    def test_without_it_a_person_can_read_notes_but_not_write_them(self):
        sample = self.register_sample()
        self.login(self.checker)
        self.client.post(f"/api/samples/{sample.id}/comments/", {"step": TESTING, "body": "Check the lot"}, format="json")
        self.take_away("ANALYST")

        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/comments/", {"step": TESTING, "body": "Noted"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("permission", r.data["detail"])
        self.assertEqual(StepComment.objects.count(), 1)

        state = self.state(sample, self.analyst)
        self.assertFalse(state["can_comment"])
        testing = next(s for s in state["steps"] if s["key"] == TESTING)
        self.assertEqual(testing["comments"][0]["body"], "Check the lot")
        self.assertTrue(self.state(sample, self.checker)["can_comment"])


class ReceiptCheckTests(ExecutionTestBase):
    CHECKS = {"checklist": [
        {"label": "Container intact", "response_type": "YES_NO", "expected": "YES"},
        {"label": "Temperature on arrival", "response_type": "NUMBER", "min_value": "2", "max_value": "8",
         "unit": "°C", "waivable": True},
    ]}

    def setUp(self):
        super().setUp()
        self.configure(receipt=self.CHECKS)
        self.intact, self.temperature = ChecklistItem.objects.filter(
            version=self.workflow.current_version(), for_receipt=True
        ).order_by("order")

    def complete(self, sample, user):
        self.login(user)
        return self.client.post(f"/api/samples/{sample.id}/receipt/complete/", {}, format="json")

    def pass_receipt(self, sample):
        self.answer(sample, self.frontdesk, self.intact.id, "YES")
        self.answer(sample, self.frontdesk, self.temperature.id, "5")
        r = self.complete(sample, self.frontdesk)
        self.assertEqual(r.status_code, 200, r.content)

    def test_without_receipt_checks_a_sample_goes_straight_to_testing(self):
        self.configure(receipt={"checklist": []})
        sample = self.register_sample()
        state = self.state(sample, self.analyst)
        self.assertEqual(state["current_step"], TESTING)
        self.assertEqual([s["key"] for s in state["steps"]][0], TESTING)

    def test_testing_waits_until_the_front_desk_completes_the_checks(self):
        sample = self.register_sample()
        state = self.state(sample, self.frontdesk)
        self.assertEqual(state["current_step"], RECEIPT)
        self.assertEqual(state["steps"][0]["kind"], "receipt")
        self.assertEqual(state["steps"][1]["status"], "WAITING")

        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_numeric": "99.5"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("receipt checks", r.data["detail"])
        self.assertIn("receipt checks", self.try_sign_analyst(sample).data["detail"])

        self.pass_receipt(sample)
        done = ReceiptCompletion.objects.get(sample=sample)
        self.assertEqual(done.completed_by_id, self.frontdesk.id)
        self.assertIsNotNone(done.completed_at)
        self.assertTrue(AuditEvent.objects.filter(action="RECEIPT_COMPLETED").exists())
        ready = Notification.objects.get(recipient=self.analyst, kind="READY_FOR_TESTING")
        self.assertIn(sample.sample_no, ready.title)

        state = self.state(sample, self.analyst)
        self.assertEqual(state["current_step"], TESTING)
        self.assertEqual(state["steps"][0]["status"], "COMPLETED")
        self.enter_results(sample)
        self.sign_analyst(sample)

    def test_it_cannot_be_completed_until_every_check_is_met(self):
        sample = self.register_sample()
        r = self.complete(sample, self.frontdesk)
        self.assertEqual(r.status_code, 400)
        self.assertIn("2 things are outstanding", r.data["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="RECEIPT_REFUSED_BLOCKED").exists())

        self.answer(sample, self.frontdesk, self.intact.id, "NO")
        self.answer(sample, self.frontdesk, self.temperature.id, "5")
        step = self.step(sample, self.frontdesk, RECEIPT)
        self.assertFalse(step["can"]["complete"])
        self.assertIn("put the sample on hold", step["blockers"][0]["message"])
        self.assertEqual(self.complete(sample, self.frontdesk).status_code, 400)
        self.assertFalse(ReceiptCompletion.objects.exists())

        self.answer(sample, self.frontdesk, self.intact.id, "YES", reason="Second look: only the box was scuffed")
        self.assertTrue(self.step(sample, self.frontdesk, RECEIPT)["can"]["complete"])
        self.assertEqual(self.complete(sample, self.frontdesk).status_code, 200)

    def test_only_the_front_desk_makes_the_checks(self):
        sample = self.register_sample()
        r = self.answer(sample, self.analyst, self.intact.id, "YES")
        self.assertEqual(r.status_code, 400)
        self.assertIn("register samples", r.data["detail"])
        self.assertEqual(self.complete(sample, self.analyst).status_code, 400)
        self.assertFalse(ChecklistResponse.objects.filter(sample=sample).exists())

    def test_the_checks_close_once_completed_and_cannot_be_completed_twice(self):
        sample = self.register_sample()
        self.pass_receipt(sample)
        r = self.answer(sample, self.frontdesk, self.temperature.id, "6", reason="Too late")
        self.assertEqual(r.status_code, 400)
        self.assertIn("were completed on", r.data["detail"])
        self.assertEqual(self.complete(sample, self.frontdesk).status_code, 400)
        self.assertEqual(ReceiptCompletion.objects.count(), 1)
        done = ReceiptCompletion.objects.get()
        with self.assertRaises(PermissionError):
            done.save()
        with self.assertRaises(PermissionError):
            done.delete()

    def test_a_hold_stops_the_checks(self):
        sample = self.register_sample()
        self.login(self.checker)
        self.client.post(f"/api/samples/{sample.id}/hold/", {"reason": "Wrong product label"}, format="json")
        r = self.answer(sample, self.frontdesk, self.intact.id, "YES")
        self.assertEqual(r.status_code, 400)
        self.assertIn("On hold", r.data["detail"])
        self.assertEqual(self.step(sample, self.frontdesk, RECEIPT)["status"], "ON_HOLD")

    def test_a_waiver_and_the_completion_come_from_different_people(self):
        RolePermissionGrant.objects.create(role=self.roles["FRONT_DESK"], permission="stage.waive", reason="test")
        colleague = self.make_user("frontdesk2", "FRONT_DESK")
        sample = self.register_sample()
        self.answer(sample, self.frontdesk, self.intact.id, "YES")
        self.login(self.frontdesk)
        r = self.client.post(f"/api/samples/{sample.id}/waivers/",
                             {"item_id": self.intact.id, "reason": "Not applicable"}, format="json")
        self.assertEqual(r.status_code, 400)  # not waivable in this workflow
        r = self.client.post(f"/api/samples/{sample.id}/waivers/",
                             {"item_id": self.temperature.id, "reason": "Shipped at ambient by design"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        self.assertFalse(self.step(sample, self.frontdesk, RECEIPT)["can"]["complete"])
        r = self.complete(sample, self.frontdesk)
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone else must complete", r.data["detail"])
        self.assertEqual(self.complete(sample, colleague).status_code, 200)

    def test_answers_stay_on_the_step_after_a_send_back(self):
        sample = self.register_sample()
        self.pass_receipt(sample)
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.send_back(cert, self.checker, "Recheck the assay")

        state = self.state(sample, self.analyst)
        self.assertEqual(state["attempt"], 2)
        self.assertEqual(state["current_step"], TESTING)
        receipt = state["steps"][0]
        self.assertEqual(receipt["status"], "COMPLETED")
        self.assertEqual({r["response"]["value"] for r in receipt["checklist"]}, {"YES", "5"})
        self.assertEqual(receipt["decisions"][0]["outcome"], "COMPLETED")

    def test_the_step_is_never_assigned_but_the_testing_can_still_change_hands(self):
        sample = self.register_sample()
        self.login(self.approver)
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": RECEIPT, "user_id": self.frontdesk.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not assigned", r.data["detail"])
        r = self.client.post(f"/api/samples/{sample.id}/assignments/",
                             {"mode": "assign", "step": TESTING, "user_id": self.analyst2.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_the_analyst_can_accept_while_the_checks_are_open(self):
        self.configure(testing={"requires_acceptance": True}, receipt=self.CHECKS)
        sample = self.register_sample()
        a = Assignment.objects.get(sample=sample, step=TESTING, status=AssignmentStatus.PENDING)
        self.login(self.analyst)
        r = self.client.post(f"/api/assignments/{a.id}/respond/", {"action": "accept"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.step(sample, self.analyst, TESTING)["status"], "WAITING")

    def test_the_task_center_sends_it_to_the_front_desk_first(self):
        sample = self.register_sample()
        self.login(self.frontdesk)
        tasks = self.client.get("/api/tasks/").data
        self.assertEqual([r["sample"]["id"] for r in tasks["receipts"]], [sample.id])
        self.assertEqual(tasks["actionable"], 1)
        self.assertIn("Container intact", tasks["receipts"][0]["blockers"][0])

        self.login(self.analyst)
        tasks = self.client.get("/api/tasks/").data
        self.assertEqual(tasks["receipts"], [])
        self.assertEqual(tasks["my_testing"], [])
        self.assertEqual([r["sample"]["id"] for r in tasks["upcoming"]], [sample.id])
        self.assertEqual(tasks["actionable"], 0)

        self.pass_receipt(sample)
        self.login(self.frontdesk)
        self.assertEqual(self.client.get("/api/tasks/").data["receipts"], [])
        self.login(self.analyst)
        tasks = self.client.get("/api/tasks/").data
        self.assertEqual([r["sample"]["id"] for r in tasks["my_testing"]], [sample.id])
        self.assertEqual(tasks["upcoming"], [])

    def test_a_change_to_the_checks_is_a_new_version_and_never_reaches_a_registered_sample(self):
        sample = self.register_sample()
        version = self.workflow.current_version().version
        self.configure(receipt=self.CHECKS)
        self.assertEqual(self.workflow.current_version().version, version)  # unchanged: no new version

        self.configure(receipt={"checklist": []})
        self.assertEqual(self.workflow.current_version().version, version + 1)
        self.assertEqual(self.state(sample, self.frontdesk)["current_step"], RECEIPT)
        self.assertEqual(self.state(self.register_sample(), self.frontdesk)["current_step"], TESTING)

    def test_an_older_screen_that_sends_no_receipt_settings_keeps_them(self):
        stages = [{"name": s.name, "signature_title": s.signature_title, "role_id": s.role_id}
                  for s in self.workflow.current_version().stages.all()]
        stages[0]["name"] = "Checked again"
        r = self.client.put(f"/api/workflows/{self.workflow.id}/stages/", {"stages": stages, "reason": "Test"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([i["label"] for i in r.data["receipt"]["checklist"]],
                         ["Container intact", "Temperature on arrival"])

    def test_the_products_list_says_how_many_checks_a_new_sample_will_need(self):
        self.login(self.frontdesk)
        rows = self.client.get("/api/products/").data
        self.assertEqual(rows[0]["workflow"]["receipt_checks"], 2)


class RetestOnCertificateTests(ExecutionTestBase):
    def retested_certificate(self):
        """A sample whose assay failed, was retested with authorization, and was then signed."""
        sample = self.register_sample()
        self.enter_results(sample, assay="90.0")
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/retests/",
                         {"test_definition_id": self.t_assay.id, "reason": "Dilution error"}, format="json")
        req = RetestRequest.objects.get(sample=sample)
        self.login(self.approver)
        self.client.post(f"/api/retests/{req.id}/decide/", {"action": "authorize"}, format="json")
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/",
                             {"test_definition_id": self.t_assay.id, "value_numeric": "99.0"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return self.sign_analyst(sample)

    def printed(self, cert):
        return render_to_string("certificates/coa.html", {
            "lh": LabConfig.get(),
            "c": cert.content, "cert": cert, "cfg": LabConfig.get(), "chain": [], "copy_number": 1,
            "is_original": True, "qr": "", "logo": "",
        })

    def test_retests_stay_off_the_certificate_by_default(self):
        cert = self.retested_certificate()
        self.assertNotIn("retests", cert.content)
        self.assertFalse(any("retested" in t for t in cert.content["tests"]))
        self.assertNotIn("Reason for retest", self.printed(cert))
        # The sample keeps the full story either way.
        self.assertEqual(RetestRequest.objects.get().status, RetestStatus.USED)

    def test_a_workflow_can_put_them_on_the_certificate(self):
        r = self.configure(certificate={"show_retests": True})
        self.assertTrue(r.data["certificate"]["show_retests"])
        cert = self.retested_certificate()

        history = cert.content["retests"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["test"], self.t_assay.name)
        self.assertEqual(history[0]["reason"], "Dilution error")
        self.assertEqual(history[0]["authorized_by"], self.approver.display_name())
        self.assertEqual(history[0]["retest_outcome"], "PASS")
        self.assertTrue(next(t for t in cert.content["tests"] if t["name"] == self.t_assay.name)["retested"])
        # It is part of what was signed, not decoration added at print time.
        self.assertEqual(cert.content_hash, content_hash(cert.content))

        html = self.printed(cert)
        self.assertIn("Reason for retest", html)
        self.assertIn("Dilution error", html)

    def test_a_certificate_without_retests_looks_the_same_with_the_option_on(self):
        self.configure(certificate={"show_retests": True})
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertNotIn("retests", cert.content)
        self.assertNotIn("Reason for retest", self.printed(cert))

    def test_the_choice_is_bound_at_registration(self):
        sample = self.register_sample()
        self.configure(certificate={"show_retests": True})
        self.assertFalse(sample.workflow_version.coa_show_retests)
        self.enter_results(sample)
        self.assertNotIn("retests", self.sign_analyst(sample).content)

    def test_turning_it_on_is_a_new_version_on_the_record(self):
        before = self.workflow.current_version().version
        self.configure(certificate={"show_retests": True})
        self.assertEqual(self.workflow.current_version().version, before + 1)
        self.assertIn("certificate shows retests", AuditEvent.objects.filter(
            action="WORKFLOW_CHANGED").latest("id").details["stages"])
        # Sent again unchanged, it makes no new version; left out, it stays on.
        self.configure(certificate={"show_retests": True})
        self.assertEqual(self.workflow.current_version().version, before + 1)
        self.configure()
        self.assertTrue(self.workflow.current_version().coa_show_retests)


class TaskCenterTests(ExecutionTestBase):
    def test_returned_work_and_retests_reach_the_right_people(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.send_back(cert, self.checker, "Attach the balance printout")
        self.login(self.analyst)
        tasks = self.client.get("/api/tasks/").data
        self.assertEqual(tasks["returned"][0]["returned"]["reason"], "Attach the balance printout")
        self.assertEqual(tasks["returned"][0]["returned"]["from_step"], "Checked")

        other = self.register_sample()
        self.enter_results(other, assay="80")
        self.login(self.analyst)
        self.client.post(f"/api/samples/{other.id}/retests/",
                         {"test_definition_id": self.t_assay.id, "reason": "Pipette out of calibration"},
                         format="json")
        self.login(self.approver)
        self.assertEqual(self.client.get("/api/tasks/").data["counts"]["retests_to_decide"], 1)
        self.login(self.checker)  # no result.retest.authorize
        self.assertEqual(self.client.get("/api/tasks/").data["counts"]["retests_to_decide"], 0)

    def test_a_stage_handed_to_someone_is_counted_once_until_they_accept(self):
        self.configure(stages={0: {"requires_acceptance": True}})
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)
        self.login(self.approver)
        self.client.post(f"/api/samples/{sample.id}/assignments/",
                         {"mode": "assign", "step": "CHECKED", "user_id": self.checker2.id}, format="json")
        self.login(self.checker2)
        counts = self.client.get("/api/tasks/").data["counts"]
        self.assertEqual((counts["to_accept"], counts["to_review"]), (1, 0))
        self.login(self.checker)  # same role, but it is waiting for checker2 to accept
        self.assertEqual(self.client.get("/api/tasks/").data["counts"]["to_review"], 0)

    def test_the_review_queue_shows_only_work_the_person_may_do(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)
        self.login(self.checker)
        self.assertEqual(self.client.get("/api/tasks/").data["counts"]["to_review"], 1)
        self.login(self.approver)
        self.client.post(f"/api/samples/{sample.id}/assignments/",
                         {"mode": "assign", "step": "CHECKED", "user_id": self.checker2.id}, format="json")
        self.login(self.checker)
        self.assertEqual(self.client.get("/api/tasks/").data["counts"]["to_review"], 0)
        self.login(self.checker2)
        self.assertEqual(self.client.get("/api/tasks/").data["counts"]["to_review"], 1)
        sample.refresh_from_db()
        self.assertEqual(sample.status, SampleStatus.IN_REVIEW)
