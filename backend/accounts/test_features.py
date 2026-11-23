"""
What the lab shows: a report, a register or a whole module switched off for
everyone, administrators too, without touching any role or record.
"""
from accounts.models import Role
from accounts.permissions_registry import LAB_REGISTER_VIEWS, report_permission
from audit.models import AuditEvent
from labrecords.test_base import LabTestBase

FEATURES = "/api/auth/lab/features/"


class FeatureTests(LabTestBase):
    def hide(self, *keys, user=None):
        self.login(user or self.admin)
        r = self.client.put(FEATURES, {"hidden": list(keys)}, format="json")
        for person in (self.frontdesk, self.analyst, self.checker, self.approver, self.admin):
            person._perm_cache = None
        return r

    def reports_of(self, user) -> set[str]:
        data = self.ok(self.get("/api/reports/", user))
        return {entry["key"] for group in data["categories"] for entry in group["reports"]}

    def test_nothing_is_hidden_to_begin_with(self):
        data = self.ok(self.get(FEATURES, self.admin))
        self.assertEqual(data["hidden"], [])
        self.assertEqual([m["key"] for m in data["modules"]], ["reports", "labrecords"])

    def test_a_hidden_report_is_gone_for_everyone_and_its_grants_stay(self):
        self.ok(self.hide(report_permission("oot")))
        for user in (self.analyst, self.admin):
            self.assertNotIn("oot", self.reports_of(user), user.username)
            self.assertEqual(self.get("/api/reports/oot/", user).status_code, 403, user.username)
        self.assertIn("test-results", self.reports_of(self.analyst))
        self.assertIn(report_permission("oot"), self.roles["ANALYST"].permissions(), "the role is untouched")

    def test_hiding_reports_hides_the_whole_module(self):
        self.ok(self.hide("report.view"))
        self.assertEqual(self.get("/api/reports/", self.admin).status_code, 403)
        self.assertNotIn("report.view", self.ok(self.get("/api/auth/me/", self.approver))["permissions"])

    def test_a_hidden_register_is_refused_even_to_whoever_manages_it(self):
        self.usable_instrument()
        self.ok(self.hide("instrument.view"))
        self.assertEqual(self.get("/api/lab/instruments/", self.checker).status_code, 403)
        listed = {r["key"] for r in self.ok(self.get("/api/lab/registers/", self.admin))["registers"]}
        self.assertNotIn("instruments", listed)
        self.assertIn("methods", listed)
        # A result still names the instrument: hiding changes what is shown, not the work.
        options = self.ok(self.get("/api/lab/result-options/", self.analyst))
        self.assertEqual([i["code"] for i in options["instruments"]], ["HPLC-01"])

    def test_every_register_hidden_leaves_no_lab_records(self):
        self.ok(self.hide(*LAB_REGISTER_VIEWS))
        self.assertEqual(self.ok(self.get("/api/lab/registers/", self.admin))["registers"], [])
        mine = set(self.ok(self.get("/api/auth/me/", self.admin))["permissions"])
        self.assertFalse(mine & set(LAB_REGISTER_VIEWS))

    def test_showing_it_again_brings_it_back(self):
        self.ok(self.hide(report_permission("oot"), "instrument.view"))
        self.ok(self.hide())
        self.assertIn("oot", self.reports_of(self.analyst))
        self.ok(self.get("/api/lab/instruments/", self.checker))

    def test_only_what_can_be_hidden_and_only_by_whoever_manages_the_lab_details(self):
        self.assertEqual(self.hide("result.enter").status_code, 400)
        self.login(self.admin)
        self.assertEqual(self.client.put(FEATURES, {"hidden": "report.view"}, format="json").status_code, 400)
        self.assertEqual(self.hide(report_permission("oot"), user=self.analyst).status_code, 403)
        self.assertEqual(self.ok(self.get(FEATURES, self.admin))["hidden"], [])

    def test_the_change_is_in_the_activity_log_by_name(self):
        self.ok(self.hide(report_permission("oot")))
        self.ok(self.hide())
        hid, showed = AuditEvent.objects.filter(action="FEATURES_CHANGED").order_by("id")
        self.assertEqual((hid.details["hidden"], hid.details["shown"]), ("OOT Trends", "nothing"))
        self.assertEqual((showed.details["hidden"], showed.details["shown"]), ("nothing", "OOT Trends"))

    def test_a_hidden_report_can_still_be_granted_and_the_roles_screen_says_it_is_hidden(self):
        self.ok(self.hide(report_permission("oot")))
        role = Role.objects.create(code="TRAINEE", name="Trainee")
        self.login(self.admin)
        r = self.client.put(f"/api/auth/roles/{role.id}/permissions/", {
            "permissions": ["report.view", report_permission("oot")], "reason": "Ready for when it is shown",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(report_permission("oot"), self.ok(self.get("/api/auth/permissions/", self.admin))["hidden"])
