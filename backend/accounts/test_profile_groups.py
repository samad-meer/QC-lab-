"""My account → What you can do: the role's permissions by area, as the Roles screen orders them."""
from accounts.permissions_registry import MODULES, report_permission
from labrecords.test_base import LabTestBase


class ProfileGroupTests(LabTestBase):
    def groups(self, user):
        return self.ok(self.get("/api/auth/profile/", user))["permission_groups"]

    def test_the_analyst_sees_their_permissions_by_area_in_the_roles_screen_order(self):
        groups = self.groups(self.analyst)
        order = [key for key, *_ in MODULES]
        self.assertEqual([g["key"] for g in groups], sorted((g["key"] for g in groups), key=order.index))
        by_area = {g["key"]: {p["key"] for p in g["permissions"]} for g in groups}
        self.assertIn("result.enter", by_area["results"])
        self.assertNotIn("administration", by_area, "an area they hold nothing in is left out")
        reports = next(g for g in groups if g["key"] == "reports")["permissions"]
        sample_register = next(p for p in reports if p["key"] == report_permission("sample-register"))
        self.assertEqual((sample_register["label"], sample_register["group"]), ("Sample Register", "Samples"))
        self.assertTrue(all(p["help"] for g in groups for p in g["permissions"]))

    def test_what_the_lab_hides_is_not_listed(self):
        self.login(self.admin)
        self.client.put("/api/auth/lab/features/", {"hidden": [report_permission("oot")]}, format="json")
        self.analyst._perm_cache = None
        keys = {p["key"] for g in self.groups(self.analyst) for p in g["permissions"]}
        self.assertNotIn(report_permission("oot"), keys)
        self.assertIn(report_permission("oos"), keys)
