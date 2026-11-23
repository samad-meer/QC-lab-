"""Sign-in: guessing stops, a session ends, and a password is the person's own."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from audit.middleware import client_ip
from audit.models import AuditEvent
from .models import Role, User
from .passwords import confirm_password, needs_new_password

PW = "correct-horse-battery"


class SignInBase(TestCase):
    def setUp(self):
        self.admin_role = Role.objects.get(code="ADMIN")
        self.analyst_role = Role.objects.get(code="ANALYST")
        self.admin = User.objects.create_user("admin1", password=PW, role=self.admin_role)
        self.user = User.objects.create_user("person", password=PW, role=self.analyst_role)
        self.client = APIClient()

    def sign_in(self, password=PW, username="person", client=None):
        return (client or self.client).post("/api/auth/login/", {"username": username, "password": password},
                                            format="json")


class LockoutTests(SignInBase):
    def test_five_wrong_passwords_lock_the_account(self):
        for _ in range(5):
            self.sign_in("wrong-password")
        self.assertEqual(self.sign_in().status_code, 400)
        self.assertTrue(AuditEvent.objects.filter(action="ACCOUNT_LOCKED", entity_id="person").exists())

    def test_the_lock_ends_by_itself(self):
        for _ in range(5):
            self.sign_in("wrong-password")
        User.objects.filter(pk=self.user.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.sign_in().status_code, 200)

    def test_a_success_clears_the_count(self):
        for _ in range(4):
            self.sign_in("wrong-password")
        self.assertEqual(self.sign_in().status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_logins, 0)

    def test_the_answer_does_not_say_whether_the_account_exists_or_is_locked(self):
        unknown = self.sign_in("wrong-password", username="nobody").data
        known = self.sign_in("wrong-password").data
        self.assertEqual(unknown, known)

    def test_a_signature_prompt_is_no_way_round_it(self):
        for _ in range(5):
            self.assertFalse(confirm_password(self.user, "wrong-password"))
        self.assertFalse(confirm_password(self.user, PW))
        self.assertTrue(AuditEvent.objects.filter(action="ACCOUNT_LOCKED").exists())

    def test_the_admin_site_is_no_way_round_it(self):
        for _ in range(5):
            self.client.post("/site-admin/login/", {"username": "person", "password": "wrong-password"})
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.locked_until)
        self.assertEqual(AuditEvent.objects.filter(action="LOGIN_FAILED").count(), 5)

    def test_something_typed_as_a_username_is_not_kept(self):
        self.sign_in("wrong-password", username="my-secret-password")
        event = AuditEvent.objects.get(action="LOGIN_FAILED")
        self.assertNotIn("my-secret-password", str(event.details) + event.entity_id)

    def test_a_malformed_body_is_a_refusal_not_a_crash(self):
        r = self.client.post("/api/auth/login/", [], format="json")
        self.assertEqual(r.status_code, 400)


class SessionTests(SignInBase):
    def test_a_session_ends_when_nobody_is_there(self):
        self.sign_in()
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        later = timezone.now().timestamp() + 16 * 60
        with patch("accounts.middleware.time.time", return_value=later):
            r = self.client.get("/api/auth/me/")
        self.assertEqual(r.status_code, 401)
        self.assertIn("without activity", r.data["detail"] if hasattr(r, "data") else r.json()["detail"])
        self.assertTrue(AuditEvent.objects.filter(action="SESSION_TIMED_OUT").exists())
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 403)

    def test_polling_does_not_keep_a_session_alive(self):
        self.sign_in()
        self.client.get("/api/auth/me/")
        start = timezone.now().timestamp()
        with patch("accounts.middleware.time.time", return_value=start + 10 * 60):
            self.client.get("/api/auth/me/", HTTP_X_BACKGROUND="1")
        with patch("accounts.middleware.time.time", return_value=start + 16 * 60):
            self.assertEqual(self.client.get("/api/auth/me/", HTTP_X_BACKGROUND="1").status_code, 401)

    def test_working_does(self):
        self.sign_in()
        self.client.get("/api/auth/me/")
        start = timezone.now().timestamp()
        with patch("accounts.middleware.time.time", return_value=start + 10 * 60):
            self.client.get("/api/auth/me/")
        with patch("accounts.middleware.time.time", return_value=start + 20 * 60):
            self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)


class PasswordTests(SignInBase):
    def setUp(self):
        super().setUp()
        self.boss = APIClient()
        self.boss.force_authenticate(self.admin)

    def change(self, new, current=PW):
        return self.client.post("/api/auth/change-password/", {"current_password": current, "new_password": new},
                                format="json")

    def test_a_password_an_administrator_set_must_be_changed_before_anything_else(self):
        r = self.boss.post(f"/api/auth/users/{self.user.id}/reset-password/", {"password": "temporary-pass-1"},
                           format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.sign_in("temporary-pass-1").data["must_change_password"], True)
        r = self.client.get("/api/summary/")
        self.assertEqual((r.status_code, r.json()["code"]), (403, "password_change_required"))

        r = self.change("my-own-choice-22", current="temporary-pass-1")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["must_change_password"], False)
        self.assertEqual(self.client.get("/api/summary/").status_code, 200)
        self.assertTrue(AuditEvent.objects.filter(action="PASSWORD_CHANGED").exists())

    def test_it_needs_the_current_password(self):
        self.sign_in()
        self.assertEqual(self.change("my-own-choice-22", current="wrong").status_code, 400)

    def test_a_recent_password_cannot_be_used_again(self):
        self.sign_in()
        self.assertEqual(self.change("second-password-2").status_code, 200)
        self.assertEqual(self.change("third-password-3", current="second-password-2").status_code, 200)
        r = self.change("second-password-2", current="third-password-3")
        self.assertEqual(r.status_code, 400)
        self.assertIn("recently", r.data["detail"])

    def test_the_temporary_password_cannot_simply_be_kept(self):
        self.boss.post(f"/api/auth/users/{self.user.id}/reset-password/", {"password": "temporary-pass-1"},
                       format="json")
        self.sign_in("temporary-pass-1")
        r = self.change("temporary-pass-1", current="temporary-pass-1")
        self.assertEqual(r.status_code, 400)

    def test_a_short_password_is_refused(self):
        self.sign_in()
        self.assertEqual(self.change("short1").status_code, 400)

    def test_a_password_expires(self):
        self.assertFalse(needs_new_password(self.user))
        self.user.password_changed_at = timezone.now() - timedelta(days=181)
        self.assertTrue(needs_new_password(self.user))

    def test_a_reset_is_flagged_for_attention(self):
        self.boss.post(f"/api/auth/users/{self.user.id}/reset-password/", {"password": "temporary-pass-1"},
                       format="json")
        from audit.describe import describe
        self.assertEqual(describe(AuditEvent.objects.get(action="PASSWORD_RESET"))["severity"], "attention")


class EscalationTests(SignInBase):
    def limited_client(self):
        role = Role.objects.create(code="HR", name="HR")
        role.grants.create(permission="user.manage", reason="test")
        role.grants.create(permission="role.manage", reason="test")
        person = User.objects.create_user("hr", password=PW, role=role)
        client = APIClient()
        client.force_authenticate(person)
        return client, role

    def test_nobody_hands_out_more_access_than_they_hold(self):
        client, _ = self.limited_client()
        r = client.post("/api/auth/users/", {
            "username": "newadmin", "password": "temporary-pass-1", "role_id": self.admin_role.id,
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("access you do not hold", r.data["detail"])
        r = client.patch(f"/api/auth/users/{self.user.id}/", {"role_id": self.admin_role.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_nobody_takes_over_an_account_with_more_access(self):
        client, _ = self.limited_client()
        r = client.post(f"/api/auth/users/{self.admin.id}/reset-password/", {"password": "temporary-pass-1"},
                        format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(User.objects.get(pk=self.admin.pk).check_password(PW))

    def test_nobody_puts_access_they_lack_on_a_role(self):
        client, role = self.limited_client()
        other = Role.objects.create(code="OTHER", name="Other")
        r = client.put(f"/api/auth/roles/{other.id}/permissions/",
                        {"permissions": ["admin.override"], "reason": "Why not"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("do not hold", r.data["detail"])


class ProductionDefaultsTests(SignInBase):
    def test_seed_demo_refuses_to_run_with_debug_off(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command("seed_demo", stdout=StringIO())

    def test_the_first_administrator_is_created_with_a_temporary_password(self):
        with patch("accounts.management.commands.create_administrator.getpass", return_value="temporary-pass-1"):
            call_command("create_administrator", "first.admin", stdout=StringIO())
        made = User.objects.get(username="first.admin")
        self.assertTrue(made.must_change_password)
        self.assertEqual(made.role.code, "ADMIN")

    def request(self, **meta):
        return type("R", (), {"META": meta})()

    def test_a_caller_cannot_forge_their_address(self):
        request = self.request(REMOTE_ADDR="198.51.100.7", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(client_ip(request), "198.51.100.7")

    @override_settings(QCLAB_BEHIND_PROXY=True)
    def test_behind_our_proxy_the_entry_it_added_is_the_one_that_counts(self):
        request = self.request(REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9")
        self.assertEqual(client_ip(request), "203.0.113.9")

    def test_an_oversized_request_is_refused_before_it_is_read(self):
        r = self.client.post("/api/auth/login/", data="{}", content_type="application/json",
                             CONTENT_LENGTH=str(26 * 1024 * 1024))
        self.assertEqual(r.status_code, 413)
