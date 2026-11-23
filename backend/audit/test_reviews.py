"""Reviewing the trail is a signed record, and nobody reviews their own overrides."""
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from .models import AuditReview
from .services import record

PW = "correct-horse-battery"


class AuditReviewTests(TestCase):
    def setUp(self):
        self.reviewer = User.objects.create_user("head", password=PW, role=Role.objects.get(code="APPROVER"))
        self.client = APIClient()
        self.client.force_authenticate(self.reviewer)

    def review(self, findings="Read every refusal. Nothing to raise.", password=PW):
        return self.client.post("/api/auth/audit/reviews/", {"findings": findings, "password": password}, format="json")

    def test_a_review_is_recorded_and_the_next_picks_up_from_it(self):
        record(self.reviewer, "LOGIN", "auth", "head")
        r = self.review()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["latest"]["name"], self.reviewer.display_name())
        self.assertEqual(AuditReview.objects.count(), 1)
        record(self.reviewer, "LOGIN", "auth", "head")
        self.assertGreaterEqual(self.client.get("/api/auth/audit/reviews/").data["unreviewed"], 1)

    def test_it_needs_findings_and_a_password(self):
        self.assertEqual(self.review(findings=" ").status_code, 400)
        self.assertEqual(self.review(password="wrong").status_code, 400)
        self.assertFalse(AuditReview.objects.exists())

    def test_nobody_signs_off_a_period_holding_their_own_overrides(self):
        record(self.reviewer, "RESULT_ENTERED", "sample", "GF-1", override="Stood in for the analyst")
        r = self.review()
        self.assertEqual(r.status_code, 400)
        self.assertIn("someone else must review", r.data["detail"])

    def test_someone_else_can(self):
        other = User.objects.create_user("other", password=PW, role=Role.objects.get(code="ADMIN"))
        record(other, "RESULT_ENTERED", "sample", "GF-1", override="Stood in for the analyst")
        self.assertEqual(self.review().status_code, 200)

    def test_a_review_is_never_changed(self):
        self.review()
        with self.assertRaises(PermissionError):
            AuditReview.objects.get().delete()
