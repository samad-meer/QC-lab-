"""
Sign-in and sessions: who is signed in now, from where and on what; ending a
session; lifting a lockout. Real sign-ins, so real sessions.
"""
import time

from django.contrib.sessions.models import Session
from django.test import override_settings
from rest_framework.test import APIClient

from audit.models import AuditEvent
from .models import User
from .sessions_api import device_of
from .test_sign_in import PW, SignInBase

EDGE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")
PHONE = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 "
         "Mobile Safari/537.36")


class SessionTests(SignInBase):
    def computer(self, username, agent=EDGE, ip="10.0.0.5"):
        client = APIClient(HTTP_USER_AGENT=agent, REMOTE_ADDR=ip)
        r = self.sign_in(username=username, client=client)
        self.assertEqual(r.status_code, 200, r.content)
        return client

    def board(self, client):
        r = client.get("/api/auth/sessions/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def test_the_screen_shows_who_is_signed_in_from_where_and_on_what(self):
        desk = self.computer("admin1")
        self.computer("person", agent=PHONE, ip="10.0.0.9")
        data = self.board(desk)
        rows = {r["user"]["username"]: r for r in data["sessions"]}
        self.assertEqual(set(rows), {"admin1", "person"})
        self.assertEqual((rows["person"]["ip"], rows["person"]["device"]), ("10.0.0.9", "Chrome on Android"))
        self.assertEqual(rows["person"]["state"], "active")
        self.assertTrue(rows["admin1"]["current"])
        self.assertFalse(rows["person"]["current"])
        self.assertEqual((data["summary"]["online"], data["summary"]["signed_in"]), (2, 2))
        self.assertNotIn(Session.objects.first().session_key, str(data), "a session key is never sent")

    def test_only_whoever_manages_users_sees_it(self):
        analyst = self.computer("person")
        self.assertEqual(analyst.get("/api/auth/sessions/").status_code, 403)

    def test_a_session_idle_past_the_limit_is_not_listed(self):
        desk = self.computer("admin1")
        self.computer("person")
        for session in Session.objects.all():
            data = session.get_decoded()
            if data.get("_auth_user_id") == str(self.user.pk):
                data["last_activity"] = time.time() - 60 * 60
                session.session_data = Session.objects.encode(data)
                session.save()
        self.assertEqual([r["user"]["username"] for r in self.board(desk)["sessions"]], ["admin1"])

    @override_settings(QCLAB_IDLE_MINUTES=15)
    def test_someone_quiet_for_a_while_is_idle_and_says_when_they_will_be_signed_out(self):
        desk = self.computer("admin1")
        self.computer("person")
        for session in Session.objects.all():
            data = session.get_decoded()
            if data.get("_auth_user_id") == str(self.user.pk):
                data["last_activity"] = time.time() - 10 * 60
                session.session_data = Session.objects.encode(data)
                session.save()
        row = next(r for r in self.board(desk)["sessions"] if r["user"]["username"] == "person")
        self.assertEqual(row["state"], "idle")
        self.assertIsNotNone(row["signs_out_at"])

    def test_an_administrator_signs_someone_out_on_one_computer(self):
        desk = self.computer("admin1")
        bench = self.computer("person")
        self.assertEqual(bench.get("/api/auth/me/").status_code, 200)
        sid = next(r["id"] for r in self.board(desk)["sessions"] if r["user"]["username"] == "person")
        r = desk.post(f"/api/auth/sessions/{sid}/end/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(bench.get("/api/auth/me/").status_code, 403, "that computer is signed out")
        event = AuditEvent.objects.get(action="SESSION_ENDED")
        self.assertEqual((event.actor_username, event.entity_id, event.details["device"]),
                         ("admin1", "person", "Edge on Windows"))
        self.assertEqual(desk.post(f"/api/auth/sessions/{sid}/end/").status_code, 404)
        self.assertTrue(User.objects.get(username="person").is_active, "the account itself is untouched")

    def test_your_own_session_is_ended_with_sign_out_instead(self):
        desk = self.computer("admin1")
        sid = next(r["id"] for r in self.board(desk)["sessions"] if r["current"])
        r = desk.post(f"/api/auth/sessions/{sid}/end/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Sign out", r.data["detail"])

    def test_a_lockout_is_shown_and_can_be_lifted(self):
        for _ in range(5):
            self.sign_in(password="wrong")
        desk = self.computer("admin1")
        listed = next(u for u in desk.get("/api/auth/users/?page_size=100").data["results"] if u["username"] == "person")
        self.assertIsNotNone(listed["locked_until"])
        self.assertEqual(self.board(desk)["summary"]["locked"], 1)
        r = desk.post(f"/api/auth/users/{self.user.pk}/unlock/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.sign_in().status_code, 200, "they can sign in again at once")
        self.assertEqual(desk.post(f"/api/auth/users/{self.user.pk}/unlock/").status_code, 400)
        labels = [e["label"] for e in self.board(desk)["recent"]]
        self.assertIn("Lockout lifted", labels)
        self.assertIn("Locked out after wrong passwords", labels)
        self.assertIn("Wrong username or password", labels)

    def test_recent_sign_ins_name_people(self):
        self.user.first_name, self.user.last_name = "Ahmed", "Raza"
        self.user.save()
        desk = self.computer("admin1")
        self.computer("person")
        first = self.board(desk)["recent"][0]
        self.assertEqual((first["label"], first["person"]), ("Signed in", "Ahmed Raza"))

    def test_devices_read_plainly(self):
        self.assertEqual(device_of(EDGE), "Edge on Windows")
        self.assertEqual(device_of(PHONE), "Chrome on Android")
        self.assertEqual(device_of(""), "")
