"""Who may sign in: one switch, and no way round it."""
from django.test import override_settings
from rest_framework.test import APIClient

from audit.models import AuditEvent
from .models import Role, User
from .test_sign_in import PW, SignInBase


class AccessBase(SignInBase):
    def setUp(self):
        super().setUp()
        self.manager = APIClient()
        self.sign_in(username="admin1", client=self.manager)

    def allow(self, user, allowed, **extra):
        return self.manager.patch(f"/api/auth/users/{user.pk}/", {"is_active": allowed, **extra}, format="json")

    def row_of(self, user):
        rows = self.manager.get("/api/auth/users/").data["results"]
        return next(r for r in rows if r["id"] == user.pk)


class BlockingTests(AccessBase):
    def test_a_blocked_person_cannot_sign_in(self):
        self.assertEqual(self.allow(self.user, False).status_code, 200)
        self.assertEqual(self.sign_in().status_code, 400)

    def test_the_refusal_does_not_say_the_account_is_blocked(self):
        wrong = self.sign_in("wrong-password").data
        self.allow(self.user, False)
        self.assertEqual(self.sign_in().data, wrong)

    def test_a_session_already_open_ends_at_once(self):
        self.sign_in()
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        self.allow(self.user, False)
        self.assertIn(self.client.get("/api/auth/me/").status_code, (401, 403))

    def test_allowing_them_again_lets_them_back(self):
        self.allow(self.user, False)
        self.allow(self.user, True)
        self.assertEqual(self.sign_in().status_code, 200)

    def test_allowing_them_again_does_not_wake_the_old_session(self):
        self.sign_in()
        self.allow(self.user, False)
        self.allow(self.user, True)
        self.assertIn(self.client.get("/api/auth/me/").status_code, (401, 403))

    def test_everyone_else_stays_signed_in(self):
        User.objects.create_user("colleague", password=PW, role=self.analyst_role)
        colleague = APIClient()
        self.sign_in(username="colleague", client=colleague)
        self.sign_in()
        self.allow(self.user, False)
        self.assertEqual(colleague.get("/api/auth/me/").status_code, 200)
        self.assertEqual(self.manager.get("/api/auth/me/").status_code, 200)

    def test_the_change_is_in_the_audit_trail(self):
        self.allow(self.user, False)
        event = AuditEvent.objects.get(action="USER_UPDATED", entity_id="person")
        self.assertEqual(event.actor_username, "admin1")
        self.assertEqual(event.details["is_active"], False)
        self.assertEqual(event.details["was"]["is_active"], "True")

    def test_the_trail_says_what_it_was_when_someone_is_allowed_back(self):
        self.allow(self.user, False)
        self.allow(self.user, True)
        event = AuditEvent.objects.filter(action="USER_UPDATED", entity_id="person").order_by("-id").first()
        self.assertEqual(event.details["is_active"], True)
        self.assertEqual(event.details["was"]["is_active"], "False")

    def test_you_cannot_block_yourself(self):
        self.assertEqual(self.allow(self.admin, False).status_code, 400)

    def test_it_takes_user_manage(self):
        self.sign_in()
        r = self.client.patch(f"/api/auth/users/{self.admin.pk}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)


class NoWorkingRoleTests(AccessBase):
    def test_an_account_with_no_role_cannot_sign_in(self):
        User.objects.create_user("norole", password=PW)
        self.assertEqual(self.sign_in(username="norole").status_code, 400)

    def test_a_role_that_is_switched_off_keeps_its_people_out(self):
        role = Role.objects.create(code="OLD", name="Old role", is_active=False)
        User.objects.create_user("old.hand", password=PW, role=role)
        self.assertEqual(self.sign_in(username="old.hand").status_code, 400)

    def test_the_admin_site_is_no_way_round_it(self):
        User.objects.create_user("norole", password=PW, is_staff=True, is_superuser=True)
        client = APIClient()
        client.post("/site-admin/login/", {"username": "norole", "password": PW})
        self.assertNotIn("_auth_user_id", client.session)

    def test_allowing_someone_with_no_role_is_refused_in_plain_words(self):
        person = User.objects.create_user("norole", password=PW, is_active=False)
        r = self.allow(person, True)
        self.assertEqual(r.status_code, 400)
        self.assertIn("no active role", r.data["detail"])
        person.refresh_from_db()
        self.assertFalse(person.is_active)

    def test_a_role_given_in_the_same_change_counts(self):
        person = User.objects.create_user("norole", password=PW, is_active=False)
        self.assertEqual(self.allow(person, True, role_id=self.analyst_role.pk).status_code, 200)
        self.assertEqual(self.sign_in(username="norole").status_code, 200)

    def test_the_list_shows_who_can_really_sign_in(self):
        person = User.objects.create_user("norole", password=PW)
        self.assertTrue(person.is_active)
        self.assertFalse(self.row_of(person)["can_sign_in"])
        self.assertTrue(self.row_of(self.user)["can_sign_in"])
        self.allow(self.user, False)
        self.assertFalse(self.row_of(self.user)["can_sign_in"])


class DemoListTests(AccessBase):
    def setUp(self):
        super().setUp()
        self.frontdesk = User.objects.create_user("frontdesk", password=PW, role=self.analyst_role)
        self.checker = User.objects.create_user("checker", password=PW, role=self.analyst_role)

    def listed(self):
        return [d["username"] for d in self.client.get("/api/auth/config/").data["demo_logins"]]

    @override_settings(DEBUG=True)
    def test_it_leaves_out_anyone_who_cannot_sign_in(self):
        self.assertCountEqual(self.listed(), ["frontdesk", "checker"])
        self.allow(self.checker, False)
        self.assertEqual(self.listed(), ["frontdesk"])

    def test_a_real_installation_lists_nobody_and_no_password(self):
        data = self.client.get("/api/auth/config/").data
        self.assertEqual(data["demo_logins"], [])
        self.assertEqual(data["demo_password"], "")
