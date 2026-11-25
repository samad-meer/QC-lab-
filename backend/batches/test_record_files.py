"""
A photo or file on a batch record: a check point the lab defines, required or optional, that
takes a picture or a PDF. What it must be, that it is kept with who added it and what it
was, that it can be replaced only with a reason and never once the stage is signed, who may
fetch it, and that the integrity check notices a file changed behind the application.
"""
import hashlib
import json
import tempfile
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from audit.describe import describe
from audit.models import AuditEvent
from .models import BatchCheckpointEntry
from .test_batch_records import RecordBase

JPEG = b"\xff\xd8\xff\xe0" + b"a photograph of the balance printout " * 40
OTHER_JPEG = b"\xff\xd8\xff\xe0" + b"a second photograph, taken again " * 40
PDF = b"%PDF-1.4\n" + b"a scanned printout\n" * 40
STAGE = "Bulking (Lot-C)"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="qclab-test-record-files-"))
class RecordFileBase(RecordBase):
    FILE_REQUIRED = True

    def printout_stage(self):
        stage = self.bulking()
        stage["steps"][0]["checkpoints"].append(
            {"label": "Balance printout", "kind": "FILE", "required": self.FILE_REQUIRED})
        return stage

    def setUp(self):
        super().setUp()
        self.batch, ids = self.batch_with(self.printout_stage())
        self.sid = ids[STAGE]

    def record_for(self, user):
        """The stage as this person sees it, which is what says what they may sign."""
        return next(s for s in self.stages_of(self.batch.id, user)["stages"] if s["name"] == STAGE)["record"]

    def point(self, label="Balance printout"):
        return self.points(self.batch.id)[label]

    def upload(self, name="printout.jpg", data=JPEG, correction="", user=None, content_type="image/jpeg"):
        point = self.point()  # asking for it signs in as someone else, so sign in after
        self.login(user or self.operator)
        item = {"checkpoint_id": point["id"], **({"correction": correction} if correction else {})}
        return self.client.post(
            f"/api/batches/{self.batch.id}/qc-stages/{self.sid}/entries/",
            {"entries": json.dumps([item]), f"file_{point['id']}": SimpleUploadedFile(name, data, content_type)},
            format="multipart",
        )

    def refused(self, response, *words):
        self.assertEqual(response.status_code, 400, response.content)
        for word in words:
            self.assertIn(word, response.data["detail"])


class KeepingTheFileTests(RecordFileBase):
    def test_a_photo_is_kept_with_its_name_its_fingerprint_and_who_added_it(self):
        self.assertEqual(self.upload().status_code, 200)
        entry = BatchCheckpointEntry.objects.get(checkpoint_id=self.point()["id"])
        self.assertEqual((entry.text, entry.extension, entry.content_type), ("printout.jpg", "jpg", "image/jpeg"))
        self.assertEqual((entry.size, entry.sha256), (len(JPEG), hashlib.sha256(JPEG).hexdigest()))
        self.assertEqual(entry.entered_by, self.operator)
        shown = self.point()["entry"]
        self.assertEqual(shown["shown"], "printout.jpg")
        self.assertEqual(shown["file"], {
            "url": f"/api/batch-record-files/{entry.id}/", "name": "printout.jpg", "type": "image/jpeg",
            "size": len(JPEG), "image": True,
        })
        said = describe(AuditEvent.objects.filter(action="BATCH_RECORD_WRITTEN").latest("id"))["sentence"]
        self.assertIn("Balance printout printout.jpg", said)
        self.assertIn(entry.sha256, str(AuditEvent.objects.filter(action="BATCH_RECORD_WRITTEN").latest("id").details))

    def test_a_pdf_is_kept_too_and_is_not_shown_as_a_picture(self):
        self.assertEqual(self.upload("printout.pdf", PDF, content_type="application/pdf").status_code, 200)
        shown = self.point()["entry"]["file"]
        self.assertEqual((shown["type"], shown["image"]), ("application/pdf", False))

    def test_a_required_one_is_missing_until_it_is_added_and_stops_signing(self):
        self.fill_all(self.batch, self.sid)
        record = self.record_for(self.operator)
        self.assertEqual(record["missing"], ["Balance printout"])
        done_by = record["signoffs"][0]
        self.assertIn("Balance printout", done_by["blocked"])
        self.assertEqual(self.sign(self.batch.id, self.sid, done_by["id"], self.operator).status_code, 400)
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.record_for(self.operator)["missing"], [])
        self.assertEqual(self.sign(self.batch.id, self.sid, done_by["id"], self.operator).status_code, 200)

    def test_a_file_written_into_the_values_is_never_taken_as_one(self):
        point = self.point()
        self.login(self.operator)
        r = self.client.post(f"/api/batches/{self.batch.id}/qc-stages/{self.sid}/entries/", {
            "entries": [{"checkpoint_id": point["id"], "file": "C:\\secrets.jpg"}],
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(BatchCheckpointEntry.objects.exclude(file="").exists())


class OptionalFileTests(RecordFileBase):
    FILE_REQUIRED = False

    def test_an_optional_one_may_be_left_out(self):
        self.fill_all(self.batch, self.sid)
        record = self.record_for(self.operator)
        self.assertEqual(record["missing"], [])
        self.assertEqual(self.sign(self.batch.id, self.sid, record["signoffs"][0]["id"], self.operator).status_code, 200)
        self.assertFalse(BatchCheckpointEntry.objects.exclude(file="").exists())


class WhatIsAcceptedTests(RecordFileBase):
    def test_only_pictures_and_pdfs_are_taken(self):
        self.refused(self.upload("run.exe", b"MZ" + b"\x00" * 100, content_type="application/octet-stream"),
                     "Balance printout", "Upload one of", "PDF", "JPEG")
        self.refused(self.upload("sheet.csv", b"a,b\n1,2\n", content_type="text/csv"), "must be")

    def test_a_file_is_what_its_name_says_it_is(self):
        self.refused(self.upload("photo.jpg", b"<html><script>alert(1)</script></html>"), "not a genuine JPEG image")
        self.refused(self.upload("scan.pdf", JPEG, content_type="application/pdf"), "not a genuine PDF")

    def test_an_empty_or_oversized_file_is_refused(self):
        self.refused(self.upload("empty.jpg", b""), "empty")
        self.refused(self.upload("huge.jpg", b"\xff\xd8\xff" + b"0" * (10 * 1024 * 1024 + 1)), "limit here is 10 MB")
        self.assertFalse(BatchCheckpointEntry.objects.exclude(file="").exists())

    def test_nothing_is_kept_when_one_value_of_several_is_refused(self):
        point, other = self.point(), self.point("Ciprofloxacin HCl")
        self.login(self.operator)
        r = self.client.post(f"/api/batches/{self.batch.id}/qc-stages/{self.sid}/entries/", {
            "entries": json.dumps([{"checkpoint_id": other["id"], "number": "17.887"},
                                   {"checkpoint_id": point["id"]}]),
            f"file_{point['id']}": SimpleUploadedFile("photo.jpg", b"not a picture", "image/jpeg"),
        }, format="multipart")
        self.refused(r, "not a genuine JPEG image")
        self.assertFalse(BatchCheckpointEntry.objects.filter(batch=self.batch).exists())


class ChangingItTests(RecordFileBase):
    def test_replacing_it_needs_a_reason_and_keeps_the_first(self):
        self.assertEqual(self.upload().status_code, 200)
        self.refused(self.upload("again.jpg", OTHER_JPEG), "already reads printout.jpg", "Say why")
        r = self.upload("again.jpg", OTHER_JPEG, correction="The first photo was blurred")
        self.assertEqual(r.status_code, 200, r.content)
        point = self.point()
        self.assertEqual(point["entry"]["file"]["name"], "again.jpg")
        self.assertEqual([h["shown"] for h in point["history"]], ["printout.jpg"])
        self.assertEqual(BatchCheckpointEntry.objects.exclude(file="").count(), 2, "the first stays on the record")
        self.assertEqual(point["entry"]["correction"], "The first photo was blurred")

    def test_the_same_file_again_changes_nothing(self):
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.upload("renamed.jpg", JPEG).status_code, 200)
        self.assertEqual(BatchCheckpointEntry.objects.exclude(file="").count(), 1)
        self.assertEqual(self.point()["entry"]["file"]["name"], "printout.jpg")

    def test_once_the_first_column_is_signed_the_file_is_final(self):
        self.fill_all(self.batch, self.sid)
        self.assertEqual(self.upload().status_code, 200)
        first = self.stage(self.batch.id, STAGE)["record"]["signoffs"][0]
        self.assertEqual(self.sign(self.batch.id, self.sid, first["id"], self.operator).status_code, 200)
        self.refused(self.upload("later.jpg", OTHER_JPEG, correction="Wrong one"), "final")
        self.assertEqual(self.point()["entry"]["file"]["name"], "printout.jpg")

    def test_only_someone_who_may_fill_the_record_adds_one(self):
        self.refused(self.upload(user=self.approver), "permission to fill batch records")
        self.assertFalse(BatchCheckpointEntry.objects.exclude(file="").exists())


class WhoMayFetchItTests(RecordFileBase):
    def url(self):
        self.assertEqual(self.upload().status_code, 200)
        return self.point()["entry"]["file"]["url"]

    def test_people_who_can_see_the_batch_get_it_with_its_checked_type(self):
        url = self.url()
        for person in (self.operator, self.approver, self.admin):
            self.login(person)
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, person.username)
            self.assertEqual(b"".join(r.streaming_content), JPEG)
            self.assertEqual(r["Content-Type"], "image/jpeg")
            self.assertEqual(r["X-Content-Type-Options"], "nosniff")
            self.assertIn("no-store", r["Cache-Control"])
            self.assertIn("inline", r["Content-Disposition"])

    def test_it_can_be_asked_for_as_a_download(self):
        url = self.url()
        self.login(self.operator)
        r = self.client.get(f"{url}?download=1")
        self.assertIn("attachment", r["Content-Disposition"])

    def test_someone_who_cannot_see_the_batch_is_told_there_is_no_such_file(self):
        url = self.url()
        self.login(self.analyst)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_a_check_point_without_a_file_has_nothing_to_fetch(self):
        self.url()
        self.login(self.operator)
        plain = BatchCheckpointEntry.objects.create(
            batch=self.batch, checkpoint_id=self.point("Ciprofloxacin HCl")["id"], number=1, entered_by=self.operator)
        self.assertEqual(self.client.get(f"/api/batch-record-files/{plain.id}/").status_code, 404)


class DefiningItTests(RecordFileBase):
    def test_the_lab_can_make_its_own_kind_of_value_from_it(self):
        self.login(self.admin)
        r = self.client.post("/api/checkpoint-kinds/", {"name": "Chromatogram", "kind": "FILE"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.data["name"], r.data["kind"]), ("Chromatogram", "FILE"))

    def test_a_file_check_point_has_no_unit_limits_or_options(self):
        shown = self.point()
        self.assertEqual((shown["kind"], shown["unit"], shown["limit_text"], shown["choices"]), ("FILE", "", "", []))
        self.assertTrue(shown["required"])


class IntegrityTests(RecordFileBase):
    def check(self):
        out = StringIO()
        call_command("verify_integrity", stdout=out)
        return out.getvalue()

    def test_the_check_covers_the_file_and_notices_one_changed_behind_the_application(self):
        self.assertEqual(self.upload().status_code, 200)
        self.assertIn("1 files match", self.check())
        entry = BatchCheckpointEntry.objects.exclude(file="").get()
        with open(entry.file.path, "wb") as handle:
            handle.write(OTHER_JPEG)
        with self.assertRaises(CommandError) as caught:
            self.check()
        self.assertIn(f"batch record file {entry.pk}: the file has changed", str(caught.exception))
