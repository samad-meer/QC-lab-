"""The lab's time zone and logo, set on the Settings screen."""
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from audit.models import AuditEvent
from certificates.tests import WorkflowTestBase, due
from lims.models import Sample
from .models import LabConfig


class LabTimeZoneTests(WorkflowTestBase):
    def set_zone(self, zone, user=None):
        self.login(user or self.admin)
        return self.client.patch("/api/auth/lab/", {"time_zone": zone}, format="json")

    def test_pakistan_unless_changed(self):
        self.assertEqual(LabConfig.get().time_zone, "Asia/Karachi")
        self.assertEqual(APIClient().get("/api/auth/config/").data["time_zone"], "Asia/Karachi")

    def test_an_administrator_changes_it_and_it_is_on_the_record(self):
        r = self.set_zone("Asia/Dubai")
        self.assertEqual((r.status_code, r.data["time_zone"]), (200, "Asia/Dubai"))
        self.assertEqual(APIClient().get("/api/auth/config/").data["time_zone"], "Asia/Dubai")
        event = AuditEvent.objects.get(action="LAB_CONFIG_UPDATED")
        self.assertEqual((event.details["time_zone"], event.details["was"]["time_zone"]), ("Asia/Dubai", "Asia/Karachi"))

    def test_a_zone_not_on_the_list_is_refused(self):
        for zone in ("Mars/Olympus", "", "PKT"):
            r = self.set_zone(zone)
            self.assertEqual(r.status_code, 400, zone)
        self.assertEqual(LabConfig.get().time_zone, "Asia/Karachi")

    def test_it_takes_the_settings_permission(self):
        self.assertEqual(self.set_zone("Asia/Dubai", user=self.analyst).status_code, 403)

    def test_a_time_typed_at_the_front_desk_is_read_in_the_lab_zone(self):
        """09:00 typed in Karachi is 04:00 UTC; after a change to Dubai, 09:00 is 05:00 UTC."""
        def register(typed):
            self.login(self.frontdesk)
            r = self.client.post("/api/samples/", {
                "product_id": self.product.id, "batch_no": f"B-{typed[-5:].replace(':', '')}", "quantity": "60 tablets",
                "received_from": "Production", "received_at": typed, "due_date": due(), "analyst_id": self.analyst.id,
            }, format="json")
            self.assertEqual(r.status_code, 201, r.content)
            return Sample.objects.get(pk=r.data["id"]).received_at.astimezone(dt_timezone.utc)

        # Yesterday: before 09:00, today's 09:00 is in the future, and is rightly refused.
        day = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertEqual(register(f"{day}T09:00").hour, 4)
        self.set_zone("Asia/Dubai")
        self.assertEqual(register(f"{day}T09:01").hour, 5)

    def test_a_recorded_moment_never_moves(self):
        sample = self.register_sample()
        before = Sample.objects.get(pk=sample.pk).received_at
        self.set_zone("Europe/London")
        self.assertEqual(Sample.objects.get(pk=sample.pk).received_at, before)
        self.assertEqual(before.tzinfo.utcoffset(before), datetime.now(dt_timezone.utc).utcoffset())


def png() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (40, 20), (13, 107, 99, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class LabLogoTests(WorkflowTestBase):
    def upload(self, content):
        self.login(self.admin)
        return self.client.post("/api/auth/lab/logo/upload/",
                                {"logo": SimpleUploadedFile("logo.png", content, "image/png")}, format="multipart")

    def test_a_damaged_image_is_refused_in_words(self):
        damaged = png()[:-20] + b"\x00" * 20
        r = self.upload(damaged[:40] + b"garbage" + damaged[47:])
        self.assertEqual(r.status_code, 400)
        self.assertIn("not an image", r.data["detail"])

    def test_the_sign_in_page_gets_the_logo_without_signing_in(self):
        self.assertIsNone(APIClient().get("/api/auth/config/").data["logo_url"])
        r = self.upload(png())
        self.assertEqual(r.status_code, 200, r.content)
        url = APIClient().get("/api/auth/config/").data["logo_url"]
        self.assertTrue(url.startswith("/api/auth/lab/logo/"))
        self.assertEqual(APIClient().get(url).status_code, 200)
