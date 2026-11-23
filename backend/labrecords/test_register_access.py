"""
Each register is seen with a permission of its own, and working on a register
comes with seeing it. A role that sees none has no Lab records at all, while the
pick-lists a result needs stay open to whoever enters results.
"""
from django.utils import timezone

from accounts.models import Role, User
from accounts.permissions_registry import LAB_REGISTER_VIEWS
from certificates.tests import PW
from .registers import REGISTERS
from .test_base import LabTestBase


class RegisterAccessTests(LabTestBase):
    def take(self, user, *keys):
        user.role.grants.filter(permission__in=keys).update(revoked_at=timezone.now())
        user._perm_cache = None

    def listed(self, user) -> set[str]:
        return {r["key"] for r in self.ok(self.get("/api/lab/registers/", user))["registers"]}

    def test_every_register_has_its_own_see_permission(self):
        self.assertEqual({entry.sees for entry in REGISTERS.values()}, set(LAB_REGISTER_VIEWS))

    def test_today_every_role_sees_every_register(self):
        for user in (self.frontdesk, self.analyst, self.checker, self.approver, self.admin):
            self.assertEqual(self.listed(user), set(REGISTERS), user.username)

    def test_a_register_taken_away_is_refused_and_not_listed(self):
        pk = self.add_instrument()
        self.take(self.frontdesk, "instrument.view")
        self.assertNotIn("instruments", self.listed(self.frontdesk))
        self.assertIn("materials", self.listed(self.frontdesk))
        for url in ("/api/lab/instruments/", f"/api/lab/instruments/{pk}/"):
            r = self.get(url, self.frontdesk)
            self.assertEqual(r.status_code, 403, url)
            self.assertIn("permission to see instruments", r.data["detail"])
        r = self.post(f"/api/lab/instruments/{pk}/calibrate/", {}, self.frontdesk)
        self.assertEqual(r.status_code, 403)
        self.ok(self.get("/api/lab/materials/", self.frontdesk))

    def test_working_on_a_register_comes_with_seeing_it(self):
        self.take(self.checker, "instrument.view", "change.view")
        self.assertLessEqual({"instruments", "changes"}, self.listed(self.checker))
        self.ok(self.get("/api/lab/instruments/", self.checker))
        self.assertIn("instrument.view", self.ok(self.get("/api/auth/me/", self.checker))["permissions"])

    def test_a_role_that_sees_no_register_has_no_lab_records(self):
        role = Role.objects.create(code="STORES", name="Stores")
        role.grants.create(permission="batch.view.all", reason="test")
        clerk = User.objects.create_user(username="clerk", password=PW, role=role, first_name="Clerk")
        self.assertEqual(self.listed(clerk), set())
        for key in REGISTERS:
            self.assertEqual(self.get(f"/api/lab/{key}/", clerk).status_code, 403, key)
        mine = set(self.ok(self.get("/api/auth/me/", clerk))["permissions"])
        self.assertFalse(mine & set(LAB_REGISTER_VIEWS))

    def test_a_result_still_names_its_instrument_and_standard(self):
        self.usable_instrument()
        self.add_material()
        self.take(self.analyst, *LAB_REGISTER_VIEWS)
        options = self.ok(self.get("/api/lab/result-options/", self.analyst))
        self.assertEqual([i["code"] for i in options["instruments"]], ["HPLC-01"])
        self.assertEqual([m["code"] for m in options["materials"]], ["RS-PCM"])

    def test_the_roles_screen_says_what_comes_with_what(self):
        modules = {m["key"]: m for m in self.ok(self.get("/api/auth/permissions/", self.admin))["modules"]}
        entries = {p["key"]: p for p in modules["labrecords"]["permissions"]}
        self.assertEqual(entries["method.view"]["included_with"], ["method.manage", "method.approve"])
        self.assertNotIn("included_with", entries["method.manage"])
        self.assertIn("menu", modules["labrecords"]["note"])
