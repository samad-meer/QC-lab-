"""The lab's clock, set on the Settings screen: 12-hour (02:05 PM) unless changed to 24 hours."""
import io
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.template.loader import render_to_string
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from audit.models import AuditEvent
from certificates.services import signature_chain
from certificates.tests import WorkflowTestBase
from reports.engine import text_of
from .lab_zone import activate_lab_zone, clock, deactivate_lab_zone, hour12
from .models import LabConfig

# 09:05:07 UTC is 02:05:07 PM in Karachi.
MOMENT = datetime(2026, 11, 17, 9, 5, 7, tzinfo=dt_timezone.utc)


class LabClockTests(WorkflowTestBase):
    def tearDown(self):
        deactivate_lab_zone()

    def set_clock(self, value, user=None):
        self.login(user or self.admin)
        return self.client.patch("/api/auth/lab/", {"time_format": value}, format="json")

    def test_a_12_hour_clock_unless_changed(self):
        self.assertEqual(LabConfig.get().time_format, "12h")
        self.assertEqual(APIClient().get("/api/auth/config/").data["time_format"], "12h")
        activate_lab_zone()
        self.assertTrue(hour12())
        self.assertEqual(text_of(MOMENT), "17-Nov-2026 02:05:07 PM")

    def test_an_administrator_changes_it_on_the_record(self):
        r = self.set_clock("24h")
        self.assertEqual((r.status_code, r.data["time_format"]), (200, "24h"))
        self.assertEqual(APIClient().get("/api/auth/config/").data["time_format"], "24h")
        event = AuditEvent.objects.get(action="LAB_CONFIG_UPDATED")
        self.assertEqual((event.details["time_format"], event.details["was"]["time_format"]), ("24h", "12h"))
        activate_lab_zone()
        self.assertEqual((hour12(), clock()), (False, "%H:%M:%S"))
        self.assertEqual(text_of(MOMENT), "17-Nov-2026 14:05:07")

    def test_only_the_two_clocks_and_only_with_the_permission(self):
        for value in ("13h", "", "am/pm"):
            self.assertEqual(self.set_clock(value).status_code, 400, value)
        self.assertEqual(self.set_clock("24h", user=self.analyst).status_code, 403)
        self.assertEqual(LabConfig.get().time_format, "12h")

    def test_excel_shows_times_on_the_lab_clock(self):
        self.register_sample()
        self.login(self.approver)
        for value, fmt in (("12h", "dd-mmm-yyyy hh:mm:ss AM/PM"), ("24h", "dd-mmm-yyyy hh:mm:ss")):
            LabConfig.objects.filter(pk=1).update(time_format=value)
            r = self.client.get("/api/samples/?status=ALL&file=xlsx")
            self.assertEqual(r.status_code, 200)
            sheet = load_workbook(io.BytesIO(r.content)).active
            formats = {c.number_format for row in sheet.iter_rows() for c in row if c.is_date}
            self.assertIn(fmt, formats, value)

    def test_the_certificate_signature_time_follows_the_clock(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        signed = timezone.localtime(cert.signatures.get().signed_at, timezone=ZoneInfo("Asia/Karachi"))
        for flag, words in ((True, signed.strftime("%I:%M %p")), (False, signed.strftime("%H:%M"))):
            with timezone.override("Asia/Karachi"):
                html = render_to_string("certificates/coa.html", {
                    "lh": LabConfig.get(), "c": cert.content, "cert": cert, "chain": signature_chain(cert),
                    "copy_number": 1, "is_original": True, "qr": "", "logo": "", "hour12": flag,
                })
            self.assertIn(f"{signed:%d %b %Y} {words}", html, flag)
