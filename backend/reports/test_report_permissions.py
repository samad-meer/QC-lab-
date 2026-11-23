"""
Each report is a permission of its own: a role can be given one report and no
other, and a link into a report someone cannot open is shown as plain text.
"""
from django.utils import timezone

from accounts.models import Role, RolePermissionGrant, User
from accounts.permissions_registry import NEEDS, REPORTS as LISTED, report_permission
from certificates.tests import PW
from .engine import REPORTS
from .tests import ReportTestBase


def links(value) -> list[str]:
    """Every place a screen's payload leads."""
    if isinstance(value, list):
        return [to for v in value for to in links(v)]
    if isinstance(value, dict):
        own = [value["to"]] if isinstance(value.get("to"), str) else []
        return own + [to for v in value.values() for to in links(v)]
    return []


class OneReportTests(ReportTestBase):
    def person_with(self, *keys, username="planner"):
        role = Role.objects.create(code=f"R_{username.upper()}", name=f"Role of {username}")
        for key in keys:
            RolePermissionGrant.objects.create(role=role, permission=key, reason="test")
        return User.objects.create_user(username=username, password=PW, role=role, first_name=username.title())

    def take(self, user, *keys):
        user.role.grants.filter(permission__in=keys).update(revoked_at=timezone.now())
        user._perm_cache = None

    def catalogue(self, user) -> set[str]:
        self.login(user)
        r = self.client.get("/api/reports/")
        self.assertEqual(r.status_code, 200, r.content)
        return {entry["key"] for group in r.data["categories"] for entry in group["reports"]}

    def test_the_registry_lists_every_report_by_its_own_title(self):
        self.assertEqual({key: title for key, title, *_ in LISTED}, {k: r.title for k, r in REPORTS.items()})
        for key, report in REPORTS.items():
            self.assertEqual(report.permission, report_permission(key))
            self.assertEqual(NEEDS[report.permission], "report.view")

    def test_a_role_can_be_given_one_report_and_no_other(self):
        sample, _ = self.released_sample()
        planner = self.person_with("report.view", "sample.view.all", report_permission("batches"))
        self.assertEqual(self.catalogue(planner), {"batches"})
        self.assertTrue(self.rows("batches", user=planner))
        for key in REPORTS:
            if key != "batches":
                self.report(key, user=planner, code=403)
        self.report("dashboard", user=planner, code=403)

        # The batch's own summary opens from it; the sample and product pages belong to other reports.
        self.login(planner)
        summary = self.client.get(f"/api/reports/documents/batch/{sample.batch_id}/")
        self.assertEqual(summary.status_code, 200, summary.content)
        self.assertEqual(self.client.get(f"/api/reports/documents/sample/{sample.id}/").status_code, 403)
        self.assertEqual(self.client.get(f"/api/reports/documents/product/{sample.product_id}/").status_code, 403)
        shut = [to for to in links(summary.data) if to.startswith(("/reports/sample-history", "/reports/product"))]
        self.assertEqual(shut, [])
        self.assertIn(sample.sample_no, str(summary.data), "the sample is still named, only not linked")

    def test_a_report_stays_shut_without_open_reports(self):
        planner = self.person_with("sample.view.all", report_permission("batches"))
        self.login(planner)
        self.assertEqual(self.client.get("/api/reports/").status_code, 403)
        self.report("batches", user=planner, code=403)

    def test_taking_one_report_away_leaves_the_others(self):
        self.failed_sample()
        self.take(self.analyst, report_permission("oos"))
        self.report("oos", user=self.analyst, code=403)
        self.report("test-results", user=self.analyst)
        self.assertNotIn("oos", self.catalogue(self.analyst))
        self.assertIn("test-results", self.catalogue(self.analyst))

    def test_the_overview_and_sample_history_go_with_the_sample_register(self):
        sample, _ = self.released_sample()
        self.take(self.analyst, report_permission("sample-register"))
        self.assertNotIn("sample-history", self.catalogue(self.analyst))
        self.report("dashboard", user=self.analyst, code=403)
        self.login(self.analyst)
        self.assertEqual(self.client.get(f"/api/reports/documents/sample/{sample.id}/").status_code, 403)

    def test_the_overview_links_only_into_reports_that_open(self):
        self.released_sample()
        self.take(self.analyst, report_permission("turnaround"), report_permission("oos"))
        overview = self.report("dashboard", user=self.analyst)
        self.assertNotIn("to", next(t for t in overview["period"] if t["key"] == "TURNAROUND"))
        self.assertNotIn("to", overview["failures"])
        self.assertTrue(all(t["to"].startswith("/reports/sample-register") for t in overview["now"]))

    def test_the_workload_reports_are_chosen_like_any_other(self):
        self.report("analyst-workload", user=self.analyst, code=403)
        self.grant(self.analyst, report_permission("analyst-workload"))
        self.report("analyst-workload", user=self.analyst)
        self.report("bottlenecks", user=self.analyst, code=403)

    def test_the_roles_screen_says_what_a_report_needs(self):
        self.login(self.admin)
        modules = {m["key"]: m for m in self.client.get("/api/auth/permissions/").data["modules"]}
        entries = {p["key"]: p for p in modules["reports"]["permissions"]}
        batches = entries[report_permission("batches")]
        self.assertEqual((batches["label"], batches["needs"], batches["group"]),
                         ("Batch QC Summary", "report.view", "Batches and products"))
        self.assertNotIn("needs", entries["report.view"])
        self.assertTrue(modules["reports"]["note"])
