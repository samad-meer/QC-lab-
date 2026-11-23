"""
Lists as Excel and PDF files: every page of what the screen lists, under the
same filters, headed by who exported it and how it was filtered, recorded, and
only for those who may export.
"""
import io

from django.utils import timezone
from openpyxl import load_workbook

from audit.describe import describe
from audit.models import AuditEvent
from labrecords.registers import REGISTERS
from qclab.testing import force_update
from lims.models import Sample
from . import export
from .tests import ReportTestBase


class ListExportTests(ReportTestBase):
    def download(self, path, file_format, query="", user=None):
        self.login(user or self.approver)
        return self.client.get(f"{path}?file={file_format}&{query}")

    def sheet(self, path, query="", user=None):
        response = self.download(path, "xlsx", query, user)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return load_workbook(io.BytesIO(response.content)).active

    def table(self, sheet, first_heading):
        """The rows under the heading row, as lists of values."""
        rows = [[c.value for c in row] for row in sheet.iter_rows()]
        start = next(i for i, row in enumerate(rows) if row[0] == first_heading)
        return rows[start], rows[start + 1:]

    def lines_above(self, sheet, first_heading):
        out = []
        for row in sheet.iter_rows():
            if row[0].value == first_heading:
                return out
            out.append(row[0].value or "")
        return out

    def test_every_list_exports_as_excel_and_pdf(self):
        sample, _ = self.released_sample()
        paths = ["/api/samples/", "/api/batches/", "/api/product-master/", "/api/auth/users/", "/api/auth/audit/",
                 *[f"/api/lab/{key}/" for key in REGISTERS]]
        for path in paths:
            for file_format, signature in (("xlsx", b"PK"), ("pdf", b"%PDF")):
                response = self.download(path, file_format, user=self.admin)
                self.assertEqual(response.status_code, 200, f"{path} {file_format}: {response.content[:300]}")
                self.assertTrue(response.content.startswith(signature), (path, file_format))
                self.assertIn(f".{file_format}", response["Content-Disposition"])

    def test_the_samples_file_holds_every_page_under_the_same_filters(self):
        first = self.register_sample()
        second = self.register_sample()
        force_update(Sample.objects.filter(pk=second.pk), batch_no="ZZ-9")
        heading, rows = self.table(self.sheet("/api/samples/", "status=ALL&page_size=1"), "Sample No")
        self.assertEqual(heading[:3], ["Sample No", "Product", "Code"])
        self.assertEqual({r[0] for r in rows}, {first.sample_no, second.sample_no})

        sheet = self.sheet("/api/samples/", "status=ALL&q=ZZ-9")
        _, rows = self.table(sheet, "Sample No")
        self.assertEqual([r[0] for r in rows], [second.sample_no])
        self.assertIn("Search: ZZ-9", self.lines_above(sheet, "Sample No"))

    def test_dates_are_real_dates_in_the_lab_time_zone(self):
        sample = self.register_sample()
        sheet = self.sheet("/api/samples/", "status=ALL")
        heading, _ = self.table(sheet, "Sample No")
        row = next(r for r in sheet.iter_rows() if r[0].value == sample.sample_no)
        received = row[heading.index("Received")]
        self.assertTrue(received.is_date)
        self.assertEqual(received.value.strftime("%Y-%m-%d %H:%M"),
                         timezone.localtime(sample.received_at).strftime("%Y-%m-%d %H:%M"))
        self.assertTrue(any("Asia/Karachi" in line for line in self.lines_above(sheet, "Sample No")))

    def test_a_person_gets_only_the_samples_they_can_see_and_is_told_so(self):
        mine = self.register_sample()
        other = self.register_sample()
        self.someone_elses(other)
        self.grant(self.analyst, "report.export")
        sheet = self.sheet("/api/samples/", "status=ALL", user=self.analyst)
        _, rows = self.table(sheet, "Sample No")
        numbers = {r[0] for r in rows}
        self.assertIn(mine.sample_no, numbers)
        self.assertNotIn(other.sample_no, numbers)
        self.assertTrue(any(line.startswith("Scope:") for line in self.lines_above(sheet, "Sample No")))

    def test_exporting_a_list_needs_the_permission(self):
        self.register_sample()
        response = self.download("/api/samples/", "xlsx", "status=ALL", user=self.analyst)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AuditEvent.objects.filter(action="LIST_EXPORTED").exists())
        # The list itself is still there for them.
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/samples/?status=ALL").status_code, 200)

    def test_only_excel_and_pdf_are_offered(self):
        for file_format in ("csv", "exe", ""):
            response = self.download("/api/samples/", file_format, "status=ALL")
            self.assertEqual(response.status_code, 400, file_format)

    def test_every_list_export_is_recorded_with_its_filters(self):
        self.register_sample()
        self.download("/api/samples/", "pdf", "status=ALL&q=PCM")
        event = AuditEvent.objects.get(action="LIST_EXPORTED")
        self.assertEqual(event.actor, self.approver)
        self.assertEqual(event.entity_id, "samples")
        self.assertEqual(event.details["format"], "PDF")
        self.assertEqual(event.details["rows"], 1)
        self.assertIn("Search: PCM", event.details["filters"])
        self.assertIn("exported the Samples list as PDF (1 rows)", describe(event)["sentence"])

    def test_a_pdf_over_the_limit_is_refused_rather_than_cut_short(self):
        self.register_sample()
        self.register_sample()
        original = export.ROW_LIMITS["pdf"]
        export.ROW_LIMITS["pdf"] = 1
        try:
            response = self.download("/api/samples/", "pdf", "status=ALL")
        finally:
            export.ROW_LIMITS["pdf"] = original
        self.assertEqual(response.status_code, 400)
        self.assertIn("Excel", response.data["detail"])
        self.assertFalse(AuditEvent.objects.filter(action="LIST_EXPORTED").exists())

    def test_a_typed_formula_arrives_as_text(self):
        sample = self.register_sample()
        force_update(Sample.objects.filter(pk=sample.pk), batch_no='=HYPERLINK("http://x","y")')
        sheet = self.sheet("/api/samples/", "status=ALL")
        found = [c for row in sheet.iter_rows() for c in row if isinstance(c.value, str) and "HYPERLINK" in c.value]
        self.assertEqual(found[0].data_type, "s")

    def test_the_batches_file_names_the_product_filter(self):
        sample = self.register_sample()
        sheet = self.sheet("/api/batches/", f"product={self.product.id}")
        heading, rows = self.table(sheet, "Official batch no")
        self.assertEqual(rows[0][heading.index("Product")], self.product.name)
        self.assertEqual(rows[0][heading.index("Samples")], 1)
        self.assertIn(f"Product: {self.product.name} ({self.product.code})", self.lines_above(sheet, "Official batch no"))
        self.assertEqual(rows[0][0], sample.batch.official_batch_no)

    def test_the_users_and_activity_log_files_need_their_own_screens_permission(self):
        self.assertEqual(self.download("/api/auth/users/", "xlsx").status_code, 403)
        self.assertEqual(self.download("/api/auth/users/", "xlsx", user=self.admin).status_code, 200)
        heading, rows = self.table(self.sheet("/api/auth/users/", user=self.admin), "Name")
        self.assertIn("Last sign-in", heading)
        self.assertIn("labhead", [r[heading.index("Username")] for r in rows])

    def test_the_activity_log_file_says_what_happened_in_words(self):
        self.register_sample()
        sheet = self.sheet("/api/auth/audit/", "", user=self.admin)
        heading, rows = self.table(sheet, "When")
        self.assertIn("What happened", heading)
        self.assertTrue(any("registered" in (r[heading.index("What happened")] or "") for r in rows))
        self.assertIn("When: This week", self.lines_above(sheet, "When"))

    def test_the_json_list_is_unchanged(self):
        self.register_sample()
        self.login(self.approver)
        data = self.client.get("/api/samples/?status=ALL").data
        self.assertEqual(data["count"], 1)
        self.assertIn("results", data)
