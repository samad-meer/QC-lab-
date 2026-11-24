"""
Dynamic roles: an administrator can invent roles and change permissions,
and the changes take effect immediately — but the rules that make the
system safe are not permissions and cannot be granted away.

Plus the self-service side: what a person may change about themselves.
"""
import shutil
import tempfile
from io import BytesIO

from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from audit.models import AuditEvent
from lims.models import Section, Workflow, WorkflowStage, WorkflowVersion
from .models import LabConfig, Role, RolePermissionGrant, User
from .permissions_registry import LAB_REGISTER_VIEWS, REPORTS, report_permission

PW = "role-test-pass-1"
# What accounts/0025 gave every role, and every role that could open reports. The reports about
# other people's work (the two workload reports and the two team reports) came with "See workload
# on the overview" as well, and the Audit Trail with "View the audit trail".
SEES_REGISTERS = set(LAB_REGISTER_VIEWS)
ALL_REPORTS = {report_permission(key) for key, *_ in REPORTS}
USUAL_REPORTS = ALL_REPORTS - {
    report_permission(k) for k in ("analyst-workload", "bottlenecks", "tasks-by-person", "team-tasks", "audit-trail")
}
# What accounts/0028 gave every active role, so that anyone can print their own week.
OWN_REPORTS = {"report.view", report_permission("person-activity")}


def make_image(size=(600, 400), fmt="PNG") -> BytesIO:
    buf = BytesIO()
    Image.new("RGB", size, (30, 90, 140)).save(buf, format=fmt)
    buf.seek(0)
    buf.name = f"photo.{fmt.lower()}"
    return buf


class RoleAdminTests(TestCase):
    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.section = Section.objects.create(code="GF", name="General Formulation")
        self.admin = User.objects.create_user(
            username="admin", password=PW, role=self.roles["ADMIN"], first_name="Ada"
        )
        self.analyst = User.objects.create_user(
            username="analyst", password=PW, role=self.roles["ANALYST"], first_name="Ann"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    # -- seeding ------------------------------------------------------------
    def test_system_roles_are_seeded_with_their_permissions(self):
        # The five lab roles, and production's two (accounts/0024).
        self.assertEqual(Role.objects.count(), 7)
        # Production has no other report, but opens its own Person Activity (accounts/0028).
        self.assertEqual(Role.objects.get(code="PRODUCTION_OPERATOR").permissions(),
                         {"batch.view.all", "batch.record.fill", *SEES_REGISTERS, *OWN_REPORTS})
        self.assertEqual(self.roles["APPROVER"].permissions(), {
            "sample.view.all", "cert.print", "sample.assign", "sample.hold", "result.retest.authorize",
            "stage.waive", "sample.comment", "report.view", "report.export", "report.performance",
            "investigation.manage", "investigation.approve", "batch.manage", "spec.approve",
            "sample.cancel", "cert.withdraw", "audit.view", "batch.disposition", "batch.stage.record",
            "instrument.manage", "material.manage", "method.manage", "method.approve", "qualification.manage",
            "custody.record", "custody.destroy", "change.manage", "change.approve",
            *SEES_REGISTERS, *ALL_REPORTS,
        })
        self.assertEqual(self.roles["FRONT_DESK"].permissions(), {
            "sample.register", "sample.view.all", "cert.print", "sample.assign", "sample.comment", "report.view",
            "batch.manage", "custody.record", *SEES_REGISTERS, *USUAL_REPORTS,
        })
        self.assertIn("workflow.manage", self.roles["ADMIN"].permissions())

    def test_review_signatures_come_from_the_default_workflow_not_permissions(self):
        stages = Workflow.default().current_version().stages.all()
        self.assertEqual([(s.code, s.role.code) for s in stages],
                         [("CHECKED", "CHECKER"), ("APPROVED", "APPROVER")])
        # The administrator manages workflows but signs no stage.
        self.assertFalse(stages.filter(role=self.roles["ADMIN"]).exists())

    def test_system_role_cannot_be_deleted(self):
        with self.assertRaises(PermissionError):
            self.roles["ANALYST"].delete()

    # -- creating and editing roles ----------------------------------------
    def test_create_role_then_grant_permissions(self):
        r = self.client.post("/api/auth/roles/",
                             {"code": "senior analyst", "name": "Senior Analyst"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["code"], "SENIOR_ANALYST")
        self.assertEqual(r.data["permissions"], [])
        role_id = r.data["id"]

        r = self.client.put(f"/api/auth/roles/{role_id}/permissions/",
                            {"permissions": ["result.enter", "cert.sign.analysed", "sample.view.all"],
                             "reason": "CR-2026-014"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            set(r.data["permissions"]), {"result.enter", "cert.sign.analysed", "sample.view.all"}
        )
        self.assertTrue(AuditEvent.objects.filter(action="ROLE_PERMISSIONS_CHANGED").exists())

    def test_unknown_permission_is_refused(self):
        r = self.client.put(f"/api/auth/roles/{self.roles['ANALYST'].id}/permissions/",
                            {"permissions": ["cert.sign.analysed", "make.tea"]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("make.tea", r.data["detail"])

    def test_revoking_keeps_the_history(self):
        role = self.roles["APPROVER"]
        r = self.client.put(f"/api/auth/roles/{role.id}/permissions/",
                            {"permissions": ["sample.view.all"], "reason": "No longer prints"},
                            format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn("cert.print", role.permissions())
        # The grant row survives, marked revoked with who and why.
        old = RolePermissionGrant.objects.get(role=role, permission="cert.print")
        self.assertIsNotNone(old.revoked_at)
        self.assertEqual(old.revoked_by, self.admin)
        self.assertEqual(old.reason, "No longer prints")
        # And it is visible in the history endpoint.
        h = self.client.get(f"/api/auth/roles/{role.id}/history/")
        self.assertIn("cert.print", [row["permission"] for row in h.data])

    def test_grants_are_never_edited_or_deleted(self):
        grant = RolePermissionGrant.objects.filter(permission="cert.print").first()
        grant.permission = "cert.sign.analysed"
        with self.assertRaises(PermissionError):
            grant.save()
        with self.assertRaises(PermissionError):
            RolePermissionGrant.objects.get(pk=grant.pk).delete()

    def test_permission_change_takes_effect_immediately(self):
        # The analyst role loses the ability to sign; the next call fails.
        self.client.put(f"/api/auth/roles/{self.roles['ANALYST'].id}/permissions/",
                        {"permissions": ["result.enter"], "reason": "Test"}, format="json")
        self.assertFalse(self.analyst.has_perm_key("cert.sign.analysed"))
        self.assertTrue(self.analyst.has_perm_key("result.enter"))

    # -- guardrails ---------------------------------------------------------
    def test_admin_cannot_widen_their_own_role(self):
        # They ship holding everything, so first give one up.
        everything = self.roles["ADMIN"].permissions()
        narrower = {"permissions": sorted(everything - {"cert.print"}), "reason": "Narrowing it"}
        url = f"/api/auth/roles/{self.roles['ADMIN'].id}/permissions/"
        self.assertEqual(self.client.put(url, narrower, format="json").status_code, 200)
        r = self.client.put(url, {"permissions": sorted(everything), "reason": "Back"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("cannot add permissions to a role you hold", r.data["detail"])

    def test_admin_can_narrow_their_own_role(self):
        keep = sorted(self.roles["ADMIN"].permissions() - {"sample.view.all"})
        r = self.client.put(f"/api/auth/roles/{self.roles['ADMIN'].id}/permissions/",
                            {"permissions": keep, "reason": "Test"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_segregation_conflict_is_reported_not_blocked(self):
        # A small lab whose analysts also do the final approval.
        role = Role.objects.create(code="SMALL_LAB", name="Small lab")
        version = WorkflowVersion.objects.create(
            workflow=Workflow.objects.create(name="Small lab review"), version=1
        )
        WorkflowStage.objects.create(version=version, order=1, code="APPROVED", name="Approved",
                                     signature_title="Approved by", role=role)
        r = self.client.put(f"/api/auth/roles/{role.id}/permissions/",
                            {"permissions": ["result.enter", "cert.sign.analysed"], "reason": "Test"},
                            format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data["warnings"]), 1)
        self.assertIn("sign as the analyst and also sign “Approved by”", r.data["warnings"][0]["message"])

    def test_a_role_that_signs_a_stage_cannot_be_deleted(self):
        role = Role.objects.create(code="QA", name="QA")
        version = WorkflowVersion.objects.create(workflow=Workflow.objects.create(name="With QA"), version=1)
        WorkflowStage.objects.create(version=version, order=1, code="QA", name="QA",
                                     signature_title="Reviewed by", role=role)
        r = self.client.delete(f"/api/auth/roles/{role.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("signs a stage", r.data["detail"])

    def test_role_in_use_cannot_be_deleted_or_deactivated(self):
        r = self.client.delete(f"/api/auth/roles/{self.roles['ANALYST'].id}/")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/auth/roles/{self.roles['ANALYST'].id}/",
                              {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_non_admin_cannot_reach_the_admin_api(self):
        self.client.force_authenticate(self.analyst)
        for method, url in [
            ("get", "/api/auth/roles/"),
            ("get", "/api/auth/users/"),
            ("get", "/api/auth/audit/"),
        ]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 403, url)


class UserAdminTests(TestCase):
    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.section = Section.objects.create(code="GF", name="General Formulation")
        self.admin = User.objects.create_user(
            username="admin", password=PW, role=self.roles["ADMIN"], first_name="Ada"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_create_user_with_role_and_sections(self):
        r = self.client.post("/api/auth/users/", {
            "username": "new.analyst", "password": "a-strong-pass-9",
            "first_name": "Nadia", "last_name": "Sheikh",
            "role_id": self.roles["ANALYST"].id, "section_ids": [self.section.id],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        u = User.objects.get(username="new.analyst")
        self.assertEqual(u.role.code, "ANALYST")
        self.assertEqual(list(u.sections.values_list("code", flat=True)), ["GF"])
        self.assertTrue(u.check_password("a-strong-pass-9"))
        self.assertTrue(AuditEvent.objects.filter(action="USER_CREATED", entity_id="new.analyst").exists())

    def test_weak_password_is_refused(self):
        r = self.client.post("/api/auth/users/", {
            "username": "weak", "password": "123",
            "role_id": self.roles["ANALYST"].id,
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_users_are_deactivated_never_deleted(self):
        u = User.objects.create_user(username="leaver", password=PW, role=self.roles["ANALYST"])
        with self.assertRaises(PermissionError):
            u.delete()
        r = self.client.patch(f"/api/auth/users/{u.id}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200)
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        self.assertEqual(u.permissions(), set())  # an inactive account can do nothing

    def test_admin_cannot_change_or_disable_their_own_account(self):
        r = self.client.patch(f"/api/auth/users/{self.admin.id}/",
                              {"role_id": self.roles["APPROVER"].id}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/auth/users/{self.admin.id}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_password_reset_is_audited_but_never_stores_the_password(self):
        u = User.objects.create_user(username="forgot", password=PW, role=self.roles["ANALYST"])
        r = self.client.post(f"/api/auth/users/{u.id}/reset-password/",
                             {"password": "brand-new-pass-7"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        u.refresh_from_db()
        self.assertTrue(u.check_password("brand-new-pass-7"))
        event = AuditEvent.objects.get(action="PASSWORD_RESET")
        self.assertNotIn("brand-new-pass-7", str(event.details))

    def test_admin_can_set_the_employment_fields(self):
        r = self.client.post("/api/auth/users/", {
            "username": "emp", "password": "a-strong-pass-9",
            "first_name": "Rida", "last_name": "Aslam",
            "role_id": self.roles["ANALYST"].id,
            "employee_id": "EMP-0142", "designation": "Senior Analyst",
            "joining_date": "2024-03-01", "phone": "+92 300 1234567",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        u = User.objects.get(username="emp")
        self.assertEqual(u.employee_id, "EMP-0142")
        self.assertEqual(u.designation, "Senior Analyst")
        self.assertEqual(str(u.joining_date), "2024-03-01")
        event = AuditEvent.objects.get(action="USER_CREATED", entity_id="emp")
        self.assertEqual(event.details["employee_id"], "EMP-0142")

    def test_employee_id_cannot_be_reused(self):
        User.objects.create_user(username="one", password=PW,
                                 role=self.roles["ANALYST"], employee_id="EMP-1")
        two = User.objects.create_user(username="two", password=PW, role=self.roles["ANALYST"])
        r = self.client.patch(f"/api/auth/users/{two.id}/", {"employee_id": "emp-1"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already used", r.data["detail"])

    def test_permission_catalogue_is_readable_by_anyone_signed_in(self):
        analyst = User.objects.create_user(username="a", password=PW, role=self.roles["ANALYST"])
        self.client.force_authenticate(analyst)
        r = self.client.get("/api/auth/permissions/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data["mine"]), {
            "result.enter", "cert.sign.analysed", "sample.comment", "report.view", "custody.record",
            *SEES_REGISTERS, *USUAL_REPORTS,
        })
        keys = {p["key"] for m in r.data["modules"] for p in m["permissions"]}
        self.assertIn("workflow.manage", keys)
        # Review signatures are workflow stages now, not permissions.
        self.assertNotIn("cert.sign.approved", keys)


MEDIA_TMP = tempfile.mkdtemp(prefix="qclab-test-media-")


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class LabDetailsTests(TestCase):
    """
    The letterhead is configurable; what a certificate CONTAINS is not.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.admin = User.objects.create_user(
            username="admin", password=PW, role=self.roles["ADMIN"], first_name="Ada"
        )
        self.analyst = User.objects.create_user(
            username="ahmed", password=PW, role=self.roles["ANALYST"], first_name="Ahmed"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_admin_role_was_granted_the_new_permission_by_migration(self):
        self.assertIn("config.manage", self.roles["ADMIN"].permissions())
        self.assertNotIn("config.manage", self.roles["ANALYST"].permissions())

    def test_letterhead_can_be_set(self):
        r = self.client.patch("/api/auth/lab/", {
            "company_name": "Samad Pharmaceuticals (Pvt) Ltd",
            "address": "Plot 42, Industrial Estate\nKarachi",
            "licence_no": "DRAP-000123",
            "phone": "+92 21 111 2222",
            "footer_note": "This certificate relates only to the sample tested.",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["licence_no"], "DRAP-000123")
        self.assertTrue(AuditEvent.objects.filter(action="LAB_CONFIG_UPDATED").exists())

    def test_lab_name_cannot_be_emptied(self):
        r = self.client.patch("/api/auth/lab/", {"lab_name": "  "}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_system_name_and_tagline_reach_the_sign_in_page(self):
        r = self.client.patch("/api/auth/lab/", {"lab_name": "Samad QC", "app_tagline": "Release testing"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.content)
        public = APIClient().get("/api/auth/config/")
        self.assertEqual(public.data["lab_name"], "Samad QC")
        self.assertEqual(public.data["app_tagline"], "Release testing")
        event = AuditEvent.objects.filter(action="LAB_CONFIG_UPDATED").latest("at")
        self.assertEqual(event.details["lab_name"], "Samad QC")

    def test_a_bad_email_is_refused_with_a_readable_message(self):
        r = self.client.patch("/api/auth/lab/", {"email": "not-an-email"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("valid email", r.data["detail"].lower())

    def test_logo_keeps_its_shape_and_transparency(self):
        buf = BytesIO()
        Image.new("RGBA", (900, 300), (0, 0, 0, 0)).save(buf, format="PNG")
        buf.seek(0)
        buf.name = "logo.png"
        r = self.client.post("/api/auth/lab/logo/upload/", {"logo": buf}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        cfg = LabConfig.get()
        with Image.open(cfg.logo.path) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.mode, "RGBA")          # transparency preserved
            self.assertEqual(img.width / img.height, 3)  # not cropped square
            self.assertLessEqual(img.width, 600)
        self.assertTrue(AuditEvent.objects.filter(action="LAB_LOGO_CHANGED").exists())

    def test_a_non_image_logo_is_refused(self):
        fake = BytesIO(b"not a picture at all")
        fake.name = "logo.png"
        r = self.client.post("/api/auth/lab/logo/upload/", {"logo": fake}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not an image", r.data["detail"])

    def test_without_config_manage_the_letterhead_is_read_only(self):
        self.client.force_authenticate(self.analyst)
        self.assertEqual(self.client.get("/api/auth/lab/").status_code, 403)
        self.assertEqual(
            self.client.patch("/api/auth/lab/", {"lab_name": "Mine"}, format="json").status_code, 403
        )


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class ProfileTests(TestCase):
    """A user's own record: what they may see and what they may change."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.roles = {r.code: r for r in Role.objects.all()}
        self.section = Section.objects.create(code="GF", name="General Formulation")
        self.user = User.objects.create_user(
            username="ahmed", password=PW, role=self.roles["ANALYST"],
            first_name="Ahmed", last_name="Raza",
            employee_id="EMP-7", designation="Analyst", joining_date="2023-06-15",
        )
        self.user.sections.set([self.section])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    # -- reading your own record -------------------------------------------
    def test_profile_shows_what_you_may_do_and_are_trained_for(self):
        r = self.client.get("/api/auth/profile/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["employee_id"], "EMP-7")
        self.assertEqual(r.data["joining_date"], "2023-06-15")
        self.assertEqual(r.data["section_names"], ["General Formulation"])
        self.assertEqual(
            {p["key"] for p in r.data["permission_labels"]},
            {"result.enter", "cert.sign.analysed", "sample.comment", "report.view", "custody.record",
             *SEES_REGISTERS, *USUAL_REPORTS},
        )
        self.assertIsNone(r.data["photo_url"])

    # -- what you may change ------------------------------------------------
    def test_user_can_change_their_own_contact_details(self):
        r = self.client.patch("/api/auth/profile/",
                              {"phone": "+92 300 111", "email": "a@lab.test"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "+92 300 111")
        self.assertTrue(AuditEvent.objects.filter(action="PROFILE_UPDATED").exists())

    def test_user_cannot_change_their_own_employment_record(self):
        for field, value in [
            ("employee_id", "EMP-999"),
            ("designation", "Lab Head"),
            ("joining_date", "2000-01-01"),
            ("role_id", self.roles["APPROVER"].id),
            ("is_active", False),
        ]:
            r = self.client.patch("/api/auth/profile/", {field: value}, format="json")
            self.assertEqual(r.status_code, 400, f"{field} was not refused")
            self.assertIn("administrator", r.data["detail"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.employee_id, "EMP-7")
        self.assertEqual(self.user.role.code, "ANALYST")

    # -- passwords are administered centrally -------------------------------
    def test_a_profile_update_cannot_set_a_password(self):
        self.client.force_authenticate(self.user)
        self.client.patch("/api/auth/profile/", {"password": "changed-this-way-1"}, format="json")
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password("changed-this-way-1"))

    def test_only_an_administrator_can_reset_a_password(self):
        r = self.client.post(f"/api/auth/users/{self.user.id}/reset-password/",
                             {"password": "brand-new-9x"}, format="json")
        self.assertEqual(r.status_code, 403)  # the analyst holds no user.manage

    def test_only_an_administrator_can_deactivate_an_account(self):
        r = self.client.patch(f"/api/auth/users/{self.user.id}/",
                              {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 403)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    # -- photo --------------------------------------------------------------
    def test_upload_normalises_to_a_square_jpeg_and_is_audited(self):
        r = self.client.post("/api/auth/profile/photo/",
                             {"photo": make_image((600, 400))}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertTrue(self.user.photo)
        with Image.open(self.user.photo.path) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (512, 512))  # centre-cropped square
        self.assertTrue(AuditEvent.objects.filter(action="PROFILE_PHOTO_CHANGED").exists())
        self.assertIn(f"/api/auth/users/{self.user.pk}/photo/", r.data["photo_url"])

    def test_a_file_that_is_not_an_image_is_refused(self):
        fake = BytesIO(b"MZ\x90\x00 this is not a picture")
        fake.name = "photo.png"
        r = self.client.post("/api/auth/profile/photo/", {"photo": fake}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not an image", r.data["detail"])

    def test_an_oversized_image_is_refused(self):
        r = self.client.post("/api/auth/profile/photo/",
                             {"photo": make_image((2400, 2400))}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("pixels", r.data["detail"])

    def test_replacing_a_photo_discards_the_old_file(self):
        self.client.post("/api/auth/profile/photo/", {"photo": make_image()}, format="multipart")
        self.user.refresh_from_db()
        first = self.user.photo.path
        self.client.post("/api/auth/profile/photo/", {"photo": make_image()}, format="multipart")
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.photo.path, first)
        import os
        self.assertFalse(os.path.exists(first))

    def test_photo_is_served_only_to_signed_in_users(self):
        self.client.post("/api/auth/profile/photo/", {"photo": make_image()}, format="multipart")
        r = self.client.get(f"/api/auth/users/{self.user.pk}/photo/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")

        anon = APIClient()
        self.assertEqual(anon.get(f"/api/auth/users/{self.user.pk}/photo/").status_code, 403)

    def test_removing_a_photo(self):
        self.client.post("/api/auth/profile/photo/", {"photo": make_image()}, format="multipart")
        r = self.client.delete("/api/auth/profile/photo/")
        self.assertEqual(r.status_code, 200, r.content)
        self.user.refresh_from_db()
        self.assertFalse(self.user.photo)
        self.assertTrue(AuditEvent.objects.filter(action="PROFILE_PHOTO_REMOVED").exists())
        self.assertEqual(self.client.get(f"/api/auth/users/{self.user.pk}/photo/").status_code, 404)
