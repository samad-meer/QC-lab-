"""The sections screen, and renaming a role."""
from accounts.models import Role
from audit.models import AuditEvent
from certificates.tests import WorkflowTestBase
from lims.models import Product, Section


class SectionTests(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def make(self, code="NEW", name="New section"):
        return self.client.post("/api/section-master/", {"code": code, "name": name}, format="json")

    def test_a_section_can_be_added_renamed_and_deleted_and_each_is_recorded(self):
        r = self.make()
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.data["id"]
        self.assertEqual(self.client.patch(f"/api/section-master/{pk}/", {"name": "Renamed"}, format="json").status_code, 200)
        self.assertEqual(Section.objects.get(pk=pk).name, "Renamed")
        self.assertEqual(self.client.delete(f"/api/section-master/{pk}/").status_code, 204)
        self.assertFalse(Section.objects.filter(pk=pk).exists())
        self.assertEqual(
            sorted(AuditEvent.objects.filter(action__startswith="SECTION_").values_list("action", flat=True)),
            ["SECTION_CREATED", "SECTION_DELETED", "SECTION_RENAMED"],
        )

    def test_a_code_is_cleaned_and_never_repeated(self):
        self.assertEqual(self.make(code="qa1").data["code"], "QA1")
        self.assertEqual(self.make(code="QA1").status_code, 400)

    def test_a_code_starts_sample_numbers_so_it_must_be_short_and_plain(self):
        for code in ("", "A B", "TOO-LONG-CODE", "GF/1"):
            self.assertEqual(self.make(code=code).status_code, 400, code)

    def test_a_name_is_required(self):
        self.assertEqual(self.make(name="  ").status_code, 400)
        r = self.client.patch(f"/api/section-master/{self.section.id}/", {"name": ""}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_the_code_cannot_be_changed(self):
        r = self.client.patch(f"/api/section-master/{self.section.id}/", {"code": "XX", "name": "Same"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Section.objects.get(pk=self.section.id).code, "GF")

    def test_a_section_with_products_stays(self):
        r = self.client.delete(f"/api/section-master/{self.section.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("stays on record", r.data["detail"])

    def test_a_section_with_people_trained_stays(self):
        pk = self.make().data["id"]
        self.analyst.sections.add(pk)
        r = self.client.delete(f"/api/section-master/{pk}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("trained", r.data["detail"])

    def test_the_list_says_what_uses_each_section(self):
        row = next(s for s in self.client.get("/api/section-master/").data if s["code"] == "GF")
        self.assertEqual(row["product_count"], Product.objects.filter(section=self.section).count())
        self.assertGreater(row["user_count"], 0)

    def test_managing_needs_the_permission(self):
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/section-master/").status_code, 403)
        self.assertEqual(self.make().status_code, 403)

    def test_malformed_requests_are_refused(self):
        self.assertEqual(self.client.post("/api/section-master/", [1, 2], format="json").status_code, 400)
        self.assertEqual(self.make(name="bad\x00").status_code, 201)  # the NUL goes, the name stays
        r = self.client.post("/api/section-master/", {"code": {"x": 1}, "name": "Y"}, format="json")
        self.assertEqual(r.status_code, 400)


class RoleRenameTests(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)
        self.role = Role.objects.create(code="TEMP", name="Temporary")

    def test_a_role_can_be_renamed_and_keeps_its_code(self):
        r = self.client.patch(f"/api/auth/roles/{self.role.id}/", {"name": "Senior", "description": "Leads"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.role.refresh_from_db()
        self.assertEqual((self.role.name, self.role.description, self.role.code), ("Senior", "Leads", "TEMP"))

    def test_a_role_cannot_lose_its_name(self):
        r = self.client.patch(f"/api/auth/roles/{self.role.id}/", {"name": "   "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.role.refresh_from_db()
        self.assertEqual(self.role.name, "Temporary")
