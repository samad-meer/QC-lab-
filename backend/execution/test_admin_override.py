"""
The administrator override, end to end through the API: an administrator can
do every step, whatever they do in someone's place is flagged in the audit
trail, the rules about the record still stop them, and taking the one
permission away puts the separation of duties back.
"""
from django.test import Client

from accounts.models import RolePermissionGrant, User
from accounts.permissions_registry import ALL_PERMISSIONS
from audit.models import AuditEvent
from certificates.models import CertStatus, Certificate
from certificates.tests import PW
from lims.models import Section, TestResult
from .models import TESTING, Attachment, ChecklistItem, StepComment
from .tests import PDF, ExecutionTestBase

ROW_UNCHANGED = "A signed certificate can never be edited"


class OverrideTestBase(ExecutionTestBase):
    def flagged(self, action, actor=None):
        """The rules an audit row says were passed; fails if the action left no row."""
        row = AuditEvent.objects.filter(action=action, actor=actor or self.admin).first()
        self.assertIsNotNone(row, f"no {action} row")
        return " ".join(row.details.get("override", []))

    def post_result(self, sample, test, user=None, **value):
        self.login(user or self.admin)
        return self.client.post(f"/api/samples/{sample.id}/results/",
                                {"test_definition_id": test.id, **value}, format="json")

    def admin_enters_results(self, sample, assay="99.5"):
        self.assertEqual(self.post_result(sample, self.t_desc, value_text="Complies").status_code, 201)
        r = self.post_result(sample, self.t_assay, value_numeric=assay)
        self.assertEqual(r.status_code, 201, r.content)

    def admin_signs_as_analyst(self, sample, password=PW):
        self.login(self.admin)
        return self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": password}, format="json")

    def post(self, path, body, user=None):
        self.login(user or self.admin)
        return self.client.post(path, body, format="json")


class AdministratorDoesEverythingTests(OverrideTestBase):
    def test_the_administrator_holds_every_permission(self):
        self.assertEqual(self.roles["ADMIN"].permissions(), set(ALL_PERMISSIONS))

    def test_results_go_on_someone_elses_sample_in_the_administrators_own_name(self):
        sample = self.register_sample()
        r = self.post_result(sample, self.t_assay, value_numeric="99.5")
        self.assertEqual(r.status_code, 201, r.content)
        result = TestResult.objects.get(sample=sample, test_definition=self.t_assay)
        self.assertEqual(result.entered_by, self.admin)
        sample.refresh_from_db()
        self.assertEqual(sample.assigned_analyst, self.analyst)  # still the analyst's sample
        self.assertIn("Testing is held by", self.flagged("RESULT_ENTERED"))

    def test_one_administrator_can_take_a_sample_from_the_door_to_print(self):
        self.login(self.admin)
        sample = self.register_sample()
        self.admin_enters_results(sample)

        # Their own password, every time: the override is not a way round signing.
        self.assertEqual(self.admin_signs_as_analyst(sample, password="wrong").status_code, 400)
        self.assertFalse(Certificate.objects.filter(sample=sample).exists())
        r = self.admin_signs_as_analyst(sample)
        self.assertEqual(r.status_code, 201, r.content)
        cert = Certificate.objects.get(pk=r.data["id"])

        self.assertEqual(self.sign(cert, self.admin).status_code, 200)
        self.assertEqual(self.sign(cert, self.admin).status_code, 200)
        cert.refresh_from_db()
        self.assertEqual(cert.status, CertStatus.APPROVED)
        self.assertEqual({s.user_id for s in cert.signatures.all()}, {self.admin.id})
        self.assertEqual({s.name_snapshot for s in cert.signatures.all()}, {self.admin.display_name()})

        r = self.client.post(f"/api/certificates/{cert.id}/print/", format="json")
        self.assertEqual(r.status_code, 200, r.content)

        self.assertIn("Testing is held by", self.flagged("SIGNED_ANALYSED"))
        self.assertIn("different person", self.flagged("SIGNED_STAGE"))
        self.assertIn("different person", self.flagged("SIGNED_FINAL"))

    def test_they_can_send_work_back_from_any_stage(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        r = self.send_back(cert, self.admin, "Wrong column recorded")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("role can work", self.flagged("RETURNED_TO_ANALYST"))

    def test_they_can_decide_a_retest_of_their_own_work(self):
        sample = self.register_sample()
        self.admin_enters_results(sample, assay="90.0")
        r = self.post(f"/api/samples/{sample.id}/retests/",
                      {"test_definition_id": self.t_assay.id, "reason": "Dilution error"})
        self.assertEqual(r.status_code, 200, r.content)
        retest = r.data["retests"][0]
        r = self.post(f"/api/retests/{retest['id']}/decide/", {"action": "authorize"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("independent", self.flagged("RETEST_AUTHORIZED"))
        r = self.post_result(sample, self.t_assay, value_numeric="99.0")
        self.assertEqual(r.status_code, 201, r.content)

    def test_they_can_waive_a_requirement_and_still_sign_that_stage(self):
        self.configure(stages={0: {"checklist": [
            {"label": "Raw data matches worksheet", "response_type": "YES_NO", "expected": "YES",
             "waivable": True},
        ]}})
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        item = ChecklistItem.objects.get(label="Raw data matches worksheet", version=sample.workflow_version)
        r = self.post(f"/api/samples/{sample.id}/waivers/", {"item_id": item.id, "reason": "Approved deviation"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.sign(cert, self.admin).status_code, 200)
        self.assertIn("same person", self.flagged("SIGNED_STAGE"))

    def test_they_can_withdraw_a_file_someone_else_uploaded(self):
        self.configure(testing={"checklist": [
            {"label": "Chromatogram", "response_type": "FILE", "file_types": ["pdf"], "max_size_mb": 1},
        ]})
        sample = self.register_sample()
        item = ChecklistItem.objects.get(label="Chromatogram", version=sample.workflow_version)
        r = self.upload(sample, self.analyst, TESTING, "run.pdf", PDF, item_id=item.id)
        self.assertEqual(r.status_code, 200, r.content)
        attachment = Attachment.objects.get(sample=sample)
        r = self.post(f"/api/attachments/{attachment.id}/withdraw/", {"reason": "Wrong batch"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("uploaded it", self.flagged("ATTACHMENT_WITHDRAWN"))

    def test_the_screens_are_told_they_may_act_and_whose_work_it_is(self):
        sample = self.register_sample()
        before = AuditEvent.objects.count()
        step = self.step(sample, self.admin, TESTING)
        self.assertTrue(step["can"]["work"])
        self.assertEqual(step["work_blockers"], [])
        self.assertIn("Testing is held by", step["overridden"][0])
        self.assertEqual(self.step(sample, self.analyst, TESTING)["overridden"], [])
        self.assertEqual(AuditEvent.objects.count(), before)  # looking is not an action

        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        for user, my_turn, can_sign in ((self.admin, False, True), (self.checker, True, True),
                                        (self.analyst, False, False)):
            self.login(user)
            for path in (f"/api/samples/{sample.id}/", f"/api/certificates/{cert.id}/"):
                data = self.client.get(path).data
                self.assertEqual((data["my_turn"], data["can_sign"]), (my_turn, can_sign), (user, path))


class TheRecordStillBindsTheAdministratorTests(OverrideTestBase):
    def test_a_hold_stops_them_until_they_release_it(self):
        sample = self.register_sample()
        hold = f"/api/samples/{sample.id}/hold/"
        self.assertEqual(self.post(hold, {"reason": "Standard expired"}).status_code, 200)
        r = self.post_result(sample, self.t_assay, value_numeric="99.5")
        self.assertEqual(r.status_code, 400)
        self.assertIn("On hold", r.data["detail"])
        self.assertEqual(self.post(hold, {"release": True, "comment": "New standard"}).status_code, 200)
        self.assertEqual(self.post_result(sample, self.t_assay, value_numeric="99.5").status_code, 201)

    def test_a_failed_result_is_still_not_replaced_directly(self):
        sample = self.register_sample()
        self.admin_enters_results(sample, assay="90.0")
        r = self.post_result(sample, self.t_assay, value_numeric="99.0", supersede_reason="Looks wrong")
        self.assertEqual(r.status_code, 400)
        self.assertIn("never replaced directly", r.data["detail"])

    def test_a_failing_sample_still_cannot_be_signed(self):
        sample = self.register_sample()
        self.admin_enters_results(sample, assay="90.0")
        self.assertEqual(self.admin_signs_as_analyst(sample).status_code, 400)
        self.assertFalse(Certificate.objects.filter(sample=sample).exists())

    def test_a_signed_certificate_still_cannot_be_changed(self):
        sample = self.register_sample()
        self.admin_enters_results(sample)
        r = self.admin_signs_as_analyst(sample)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.post_result(sample, self.t_assay, value_numeric="100.0",
                                          supersede_reason="Too late").status_code, 400)
        cert = Certificate.objects.get(pk=r.data["id"])
        cert.content = {"tampered": True}
        with self.assertRaisesMessage(PermissionError, ROW_UNCHANGED):
            cert.save()

    def test_a_step_that_has_not_opened_cannot_be_signed(self):
        sample = self.register_sample()
        self.admin_enters_results(sample)
        cert_id = self.admin_signs_as_analyst(sample).data["id"]
        r = self.post(f"/api/certificates/{cert_id}/sign/", {"password": PW, "stage": 2})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no longer waiting at that stage", r.data["detail"])

    def test_someone_elses_words_and_acceptance_stay_theirs(self):
        sample = self.register_sample()
        self.post(f"/api/samples/{sample.id}/comments/", {"step": TESTING, "body": "Column 4"}, self.analyst)
        r = self.post(f"/api/samples/{sample.id}/comments/",
                      {"amends_id": StepComment.objects.get().id, "body": "Column 5"})
        self.assertEqual(r.status_code, 400)

        r = self.post(f"/api/samples/{sample.id}/assignments/",
                      {"mode": "handover", "step": TESTING, "user_id": self.analyst2.id, "note": "Please take"},
                      self.analyst)
        pending = next(a for a in self.step(sample, self.admin, TESTING)["assignments"] if a["status"] == "PENDING")
        r = self.post(f"/api/assignments/{pending['id']}/respond/", {"action": "accept"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("can answer this", r.data["detail"])

    def test_the_audit_trail_cannot_be_changed_by_anyone(self):
        sample = self.register_sample()
        self.post_result(sample, self.t_assay, value_numeric="99.5")
        event = AuditEvent.objects.filter(action="RESULT_ENTERED").get()
        event.details = {}
        with self.assertRaises(PermissionError):
            event.save()
        with self.assertRaises(PermissionError):
            event.delete()


class OneSwitchPutsTheSeparationBackTests(OverrideTestBase):
    def setUp(self):
        super().setUp()
        RolePermissionGrant.objects.get(
            role=self.roles["ADMIN"], permission="admin.override", revoked_at__isnull=True
        ).revoke(self.admin, "Separating duties")
        # force_authenticate reuses the object, and permissions are cached on it.
        self.admin = User.objects.get(pk=self.admin.pk)

    def test_without_it_a_permission_alone_does_not_reach_someone_elses_work(self):
        sample = self.register_sample()
        r = self.post_result(sample, self.t_assay, value_numeric="99.5")
        self.assertEqual(r.status_code, 403)
        step = self.step(sample, self.admin, TESTING)
        self.assertFalse(step["can"]["work"])
        self.assertEqual(step["overridden"], [])

    def test_without_it_they_cannot_sign_a_stage(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.admin).status_code, 400)
        self.login(self.admin)
        self.assertFalse(self.client.get(f"/api/certificates/{cert.id}/").data["can_sign"])

    def test_without_it_they_cannot_sign_twice(self):
        self.login(self.admin)
        analyst_role = self.analyst.role
        User.objects.filter(pk=self.admin.pk).update(role=analyst_role)
        self.admin = User.objects.get(pk=self.admin.pk)
        self.admin.sections.set([self.section])
        self.product.workflow = self.make_workflow("Own role", [("Checked", "Checked by", analyst_role)])
        self.product.save()
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "B-9", "quantity": "1", "received_from": "Production",
            "received_at": "2026-10-30T09:00:00Z", "due_date": "2027-10-30", "analyst_id": self.admin.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sample_id = r.data["id"]
        for test, value in ((self.t_desc, {"value_text": "Complies"}), (self.t_assay, {"value_numeric": "99.5"})):
            self.post(f"/api/samples/{sample_id}/results/", {"test_definition_id": test.id, **value})
        r = self.post(f"/api/samples/{sample_id}/sign-analyst/", {"password": PW})
        self.assertEqual(r.status_code, 201, r.content)
        cert = Certificate.objects.get(pk=r.data["id"])
        r = self.sign(cert, self.admin)
        self.assertEqual(r.status_code, 400)
        self.assertIn("different person", r.data["detail"])

    def test_work_done_by_its_owner_is_never_flagged(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        self.sign(cert, self.approver)
        rows = AuditEvent.objects.filter(details__has_key="override")
        self.assertEqual(list(rows), [])


class AuditCoverageTests(OverrideTestBase):
    def trail(self, query):
        self.login(self.admin)
        r = self.client.get(f"/api/auth/audit/?period=all&{query}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data["results"]

    def test_an_override_reads_as_one_and_can_be_found(self):
        sample = self.register_sample()
        self.post_result(sample, self.t_assay, value_numeric="99.5")
        self.post_result(sample, self.t_desc, self.analyst, value_text="Complies")  # their own work: not flagged

        overrides = self.trail("override=1")
        self.assertEqual([e["action"] for e in overrides], ["RESULT_ENTERED"])
        row = overrides[0]
        self.assertIn("administrator override", row["sentence"])
        self.assertIn("Testing is held by", row["sentence"])
        self.assertEqual(row["severity"], "attention")
        self.assertTrue(row["notable"])
        self.assertIn(row["id"], [e["id"] for e in self.trail("notable=1")])
        self.login(self.admin)
        attention = self.client.get("/api/auth/analytics/?period=all").data["attention"]
        self.assertIn(row["id"], [e["id"] for e in attention])

    def test_every_row_of_a_replaced_result_is_flagged(self):
        sample = self.register_sample()
        self.post_result(sample, self.t_assay, value_numeric="99.5")
        self.post_result(sample, self.t_assay, value_numeric="99.7", supersede_reason="Transcription error")
        self.assertIn("Testing is held by", self.flagged("RESULT_SUPERSEDED"))
        self.assertEqual(AuditEvent.objects.filter(action="RESULT_ENTERED", details__has_key="override").count(), 2)

    def test_a_refused_change_is_recorded_and_a_refused_read_is_not(self):
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/auth/roles/").status_code, 403)
        self.assertFalse(AuditEvent.objects.filter(action="ACCESS_REFUSED").exists())
        self.assertEqual(self.client.post("/api/auth/roles/", {"code": "X", "name": "X"}, format="json").status_code, 403)
        row = AuditEvent.objects.get(action="ACCESS_REFUSED")
        self.assertEqual((row.actor, row.entity_id), (self.analyst, "/api/auth/roles/"))

    def test_trying_someone_elses_work_is_recorded(self):
        sample = self.register_sample()
        self.assertEqual(self.post_result(sample, self.t_assay, self.analyst2, value_numeric="99").status_code, 403)
        self.assertEqual(AuditEvent.objects.get(action="ACCESS_REFUSED").entity_id, sample.sample_no)

    def test_signing_outside_ones_role_or_sample_is_recorded(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.assertEqual(self.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW},
                                   self.analyst2).status_code, 400)
        self.login(self.analyst)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.frontdesk).status_code, 400)
        self.assertEqual(
            sorted(AuditEvent.objects.filter(action="ACCESS_REFUSED").values_list("actor__username", flat=True)),
            ["analyst2", "frontdesk"],
        )

    def test_a_missing_service_permission_is_recorded(self):
        sample = self.register_sample()
        r = self.post(f"/api/samples/{sample.id}/hold/", {"reason": "Stop"}, self.analyst)
        self.assertEqual(r.status_code, 400)
        self.assertTrue(AuditEvent.objects.filter(action="ACCESS_REFUSED", actor=self.analyst).exists())

    def test_the_django_admin_site_reaches_the_audit_trail(self):
        root = User.objects.create_superuser(username="root", password=PW, role=self.roles["ADMIN"])
        site = Client()
        site.force_login(root)

        r = site.post(f"/site-admin/lims/section/{self.section.id}/change/", {"code": "GF", "name": "Renamed section"})
        self.assertEqual(r.status_code, 302, r.content)
        changed = AuditEvent.objects.get(action="ADMIN_SITE_CHANGED")
        self.assertEqual((changed.actor, changed.entity), (root, "section"))
        self.assertIn("Name", changed.details["change"])

        r = site.post("/site-admin/lims/section/add/", {"code": "NEW", "name": "New section"})
        self.assertEqual(r.status_code, 302, r.content)
        self.assertEqual(AuditEvent.objects.get(action="ADMIN_SITE_ADDED").details["name"], "New section")

        added = Section.objects.get(code="NEW")
        r = site.post(f"/site-admin/lims/section/{added.id}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 302, r.content)
        self.assertEqual(AuditEvent.objects.get(action="ADMIN_SITE_DELETED").entity_id, str(added.id))

        sentence = self.trail("action=ADMIN_SITE_CHANGED")[0]["sentence"]
        self.assertIn("Django admin site", sentence)
        self.assertEqual(self.trail("action=ADMIN_SITE_CHANGED")[0]["severity"], "attention")

    def test_the_django_admin_site_is_no_way_round_a_temporary_password(self):
        root = User.objects.create_superuser(username="root", password=PW, role=self.roles["ADMIN"])
        site = Client()
        site.force_login(root)
        secret = "brand-new-Secret-123"
        r = site.post(f"/site-admin/accounts/user/{self.analyst.id}/password/",
                      {"password1": secret, "password2": secret, "usable_password": "true"})
        self.assertEqual(r.status_code, 403, r.content)
        self.analyst.refresh_from_db()
        self.assertFalse(self.analyst.check_password(secret))
