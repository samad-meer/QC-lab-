"""A record says what was signed, and anything that changes behind the application shows."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from accounts.models import LabConfig
from audit.models import AuditEvent
from qclab.testing import force_update
from .models import Certificate, PrintEvent, Signature
from .services import integrity_problems
from .tests import WorkflowTestBase


class IntegrityTests(WorkflowTestBase):
    def released(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        self.sign(cert, self.approver)
        cert.refresh_from_db()
        return cert

    def tamper(self, cert, value="1.0"):
        content = dict(cert.content)
        content["tests"] = [{**t, "value": value} for t in content["tests"]]
        force_update(Certificate.objects.filter(pk=cert.pk), content=content)
        cert.refresh_from_db()

    def print_first_copy(self, cert):
        self.login(self.approver)
        return self.client.post(f"/api/certificates/{cert.id}/print/", {}, format="json")

    def test_a_sound_certificate_has_no_problems(self):
        self.assertEqual(integrity_problems(self.released()), [])

    def test_changed_content_is_caught_on_the_public_page(self):
        cert = self.released()
        self.tamper(cert)
        page = self.client.get(f"/verify/{cert.verification_uuid}/").content.decode()
        self.assertIn("no longer matches", page)
        self.assertNotIn("genuine and current", page)
        self.assertTrue(AuditEvent.objects.filter(action="CERT_INTEGRITY_FAILED").exists())

    def test_changed_content_cannot_be_printed(self):
        cert = self.released()
        self.tamper(cert)
        self.assertEqual(self.print_first_copy(cert).status_code, 400)
        self.assertFalse(PrintEvent.objects.exists())

    def test_a_signature_cannot_be_reattributed(self):
        cert = self.released()
        force_update(Signature.objects.filter(certificate=cert, meaning="ANALYSED"), name_snapshot="Someone Else")
        self.assertTrue(any("altered" in p for p in integrity_problems(cert)))

    def test_the_public_page_shows_what_was_signed(self):
        cert = self.released()
        page = self.client.get(f"/verify/{cert.verification_uuid}/").content.decode()
        self.assertIn(cert.content_hash, page)
        self.assertIn(cert.content["tests"][0]["name"], page)

    def test_the_nightly_check_reports_a_change(self):
        call_command("verify_integrity", stdout=StringIO())
        cert = self.released()
        call_command("verify_integrity", stdout=StringIO())
        self.tamper(cert)
        with self.assertRaises(CommandError):
            call_command("verify_integrity", stdout=StringIO())


class TrueCopyTests(IntegrityTests):
    def test_a_reprint_keeps_the_letterhead_it_was_signed_with(self):
        LabConfig.objects.update_or_create(pk=1, defaults={"licence_no": "OLD-123"})
        cert = self.released()
        LabConfig.objects.filter(pk=1).update(licence_no="NEW-999")
        self.print_first_copy(cert)
        page = self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=1").content.decode()
        self.assertIn("OLD-123", page)
        self.assertNotIn("NEW-999", page)

    def test_a_recorded_copy_opens_once(self):
        cert = self.released()
        self.print_first_copy(cert)
        self.assertEqual(self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=1").status_code, 200)
        r = self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Print a new numbered copy", r.data["detail"])

    def test_printing_needs_the_permission_at_every_step(self):
        cert = self.released()
        self.print_first_copy(cert)
        self.login(self.analyst)
        self.assertEqual(self.client.get(f"/api/certificates/{cert.id}/print-view/?copy=1").status_code, 403)


class DatabaseLockTests(WorkflowTestBase):
    """Direct SQL, as someone with the database login but not the application would try it."""

    def refused(self, sql):
        if connection.vendor != "postgresql":
            self.skipTest("The locks are PostgreSQL triggers.")
        from django.db import DatabaseError, transaction
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)

    def test_the_audit_trail_cannot_be_emptied(self):
        self.refused("TRUNCATE audit_auditevent")

    def test_an_approved_specification_cannot_be_changed(self):
        self.refused(f"UPDATE lims_specification SET version = 99 WHERE id = {self.spec.id}")
        self.refused(f"DELETE FROM lims_specification WHERE id = {self.spec.id}")

    def test_limits_in_use_cannot_be_changed(self):
        self.register_sample()
        self.refused(f"UPDATE lims_testdefinition SET max_value = 500 WHERE id = {self.t_assay.id}")

    def test_a_grant_cannot_be_deleted(self):
        grant = self.analyst.role.grants.first()
        self.refused(f"DELETE FROM accounts_rolepermissiongrant WHERE id = {grant.id}")

    def test_a_released_certificate_cannot_go_back(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        self.sign(cert, self.approver)
        self.refused(f"UPDATE certificates_certificate SET status = 'IN_REVIEW' WHERE id = {cert.id}")
