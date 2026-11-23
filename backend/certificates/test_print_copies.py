"""A numbered copy is never lost, and no old copy can be printed again."""
from datetime import timedelta

from django.utils import timezone

from audit.models import AuditEvent
from qclab.testing import unlocked
from .models import PrintEvent
from .tests import WorkflowTestBase


class CopyTests(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        sample = self.register_sample()
        self.enter_results(sample)
        self.cert = self.sign_analyst(sample)
        self.sign(self.cert, self.checker)
        self.sign(self.cert, self.approver)

    def printed(self, user):
        self.login(user)
        r = self.client.post(f"/api/certificates/{self.cert.id}/print/", format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data["copy_number"]

    def open_copy(self, copy, user):
        self.login(user)
        return self.client.get(f"/api/certificates/{self.cert.id}/print-view/?copy={copy}")

    def shown(self, user):
        self.login(user)
        return self.client.get(f"/api/certificates/{self.cert.id}/").data["prints"]

    def test_a_copy_whose_window_closed_can_still_be_opened_by_whoever_printed_it(self):
        copy = self.printed(self.frontdesk)
        self.assertTrue(self.shown(self.frontdesk)[0]["can_open"])
        self.assertEqual(self.open_copy(copy, self.frontdesk).status_code, 200)

    def test_opening_it_uses_it_up(self):
        copy = self.printed(self.frontdesk)
        self.open_copy(copy, self.frontdesk)
        self.assertFalse(self.shown(self.frontdesk)[0]["can_open"])
        r = self.open_copy(copy, self.frontdesk)
        self.assertEqual(r.status_code, 400)
        self.assertIn("already been opened", r.data["detail"])

    def test_nobody_else_can_open_it(self):
        copy = self.printed(self.frontdesk)
        self.assertFalse(self.shown(self.approver)[0]["can_open"])
        r = self.open_copy(copy, self.approver)
        self.assertEqual(r.status_code, 400)
        self.assertIn("whoever printed it", r.data["detail"])
        self.assertFalse(AuditEvent.objects.filter(action="CERT_COPY_OPENED").exists())

    def test_an_old_copy_with_no_record_of_opening_stays_closed(self):
        """Prints from before copies were tracked look unopened. An old original must not print again."""
        copy = self.printed(self.frontdesk)
        with unlocked(PrintEvent):
            PrintEvent.objects.filter(certificate=self.cert).update(printed_at=timezone.now() - timedelta(hours=25))
        self.assertFalse(self.shown(self.frontdesk)[0]["can_open"])
        self.assertEqual(self.open_copy(copy, self.frontdesk).status_code, 400)
        self.assertFalse(AuditEvent.objects.filter(action="CERT_COPY_OPENED").exists())

    def test_the_next_copy_is_still_numbered_after_one_that_was_never_opened(self):
        self.assertEqual(self.printed(self.frontdesk), 1)
        self.assertEqual(self.printed(self.frontdesk), 2)
