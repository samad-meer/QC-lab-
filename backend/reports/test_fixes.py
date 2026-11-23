"""Regressions from the October 2026 audit. Each of these once gave a wrong answer."""
from django.utils import timezone

from execution.models import RetestRequest
from lims.models import Outcome, TestResult
from qclab.testing import force_update
from quality.models import Investigation
from .tests import ReportTestBase


class FailureReportFixes(ReportTestBase):
    def open_oos(self, sample):
        failed = sample.results.get(test_definition=self.t_assay, outcome="FAIL")
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "Assay below limit",
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Investigation.objects.get(pk=r.data["id"])

    def test_an_old_closed_investigation_is_not_shown_against_a_newer_failure(self):
        sample = self.failed_sample()
        inv = self.open_oos(sample)
        before = timezone.now() - timezone.timedelta(days=2)
        force_update(Investigation.objects.filter(pk=inv.pk), status="CLOSED", closed_at=before, root_cause="Old cause")
        self.login(self.approver)
        row = self.rows("oos")[0]
        self.assertEqual(self.text(row["investigation"]), "None opened")
        self.assertEqual(row["root_cause"], "")
        self.assertEqual(len(self.rows("oos", "state=NONE")), 1)

    def test_the_retest_shown_is_the_latest_one(self):
        sample = self.failed_sample()
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/retests/", {
            "test_definition_id": self.t_assay.id, "reason": "First", "kind": "RETEST",
        }, format="json")
        first = RetestRequest.objects.get(sample=sample)
        self.login(self.approver)
        self.client.post(f"/api/retests/{first.id}/decide/", {"action": "decline", "comment": "No"}, format="json")
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/retests/", {
            "test_definition_id": self.t_assay.id, "reason": "Second", "kind": "RESAMPLE",
        }, format="json")
        second = RetestRequest.objects.exclude(pk=first.pk).get()
        self.login(self.approver)
        self.client.post(f"/api/retests/{second.id}/decide/", {"action": "authorize"}, format="json")
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/results/",
                         {"test_definition_id": self.t_assay.id, "value_numeric": "99.0"}, format="json")
        self.login(self.approver)
        self.assertIn("Resample", self.text(self.rows("oos")[0]["retest"]))

    def test_the_samples_and_batches_figures_on_the_dashboard_are_on_the_list_they_open(self):
        self.failed_sample()
        self.failed_sample()
        self.login(self.approver)
        board = self.client.get("/api/reports/dashboard/").data["failures"]
        tiles = {t["label"]: t["value"] for t in self.report("oos")["summary"]}
        self.assertEqual((tiles["Samples"], tiles["Batches"]), (board["samples"], board["batches"]))

    def test_a_sample_that_failed_never_reads_as_clean(self):
        sample = self.retested_sample()
        self.login(self.approver)
        cell = next(r["results"] for r in self.rows("sample-register") if self.text(r["sample"]) == sample.sample_no)
        self.assertEqual(cell["text"], "Within limits after a failure")
        self.assertEqual(cell["tone"], "warn")

    def test_the_results_register_lists_superseded_failures_unless_asked_not_to(self):
        self.retested_sample()
        self.login(self.approver)
        everything = [r for r in self.rows("test-results") if self.text(r["test"]) == "Assay"]
        current = [r for r in self.rows("test-results", "current=1") if self.text(r["test"]) == "Assay"]
        self.assertEqual((len(everything), len(current)), (2, 1))


class ExportFixes(ReportTestBase):
    def test_a_long_entry_runs_on_to_the_next_page_rather_than_failing_the_pdf(self):
        sample = self.failed_sample()
        failed = sample.results.get(outcome="FAIL")
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "x", "root_cause": "y",
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.client.patch(f"/api/investigations/{r.data['id']}/", {"root_cause": "Word " * 800}, format="json")
        self.login(self.approver)
        self.assertEqual(self.client.get("/api/reports/oos/export/?file=pdf").status_code, 200)
        self.assertEqual(self.client.get(f"/api/reports/documents/sample/{sample.id}/?file=pdf").status_code, 200)

    def test_greek_and_subscripts_are_in_the_pdf_font(self):
        from reportlab.pdfbase import pdfmetrics
        from .export import _FONT, _fonts
        _fonts()
        widths = pdfmetrics.getFont(_FONT).face.charToGlyph
        for character in "αβµ°≥≤₁₂":
            with self.subTest(character):
                self.assertIn(ord(character), widths)

    def test_a_restricted_reader_is_told_the_report_is_partial(self):
        self.register_sample()
        self.grant(self.analyst, "report.export")
        self.assertTrue(self.report("sample-register", user=self.analyst)["partial"])
        self.assertFalse(self.report("sample-register", user=self.approver)["partial"])


class ReportedResultsTest(ReportTestBase):
    def test_a_superseded_failure_is_counted_where_it_belongs(self):
        self.retested_sample()
        self.assertEqual(TestResult.objects.filter(outcome=Outcome.FAIL, is_superseded=True).count(), 1)
