"""
The Reports module, tested through its endpoints: who may open what, that
nobody sees past their own samples, that a tile and the list behind it agree,
and that an export says exactly what the screen says, and is recorded.
"""
import csv
import io
from datetime import timedelta

from django.utils import timezone
from openpyxl import load_workbook

from qclab.testing import force_update
from audit.describe import describe
from audit.models import AuditEvent
from batches.models import Batch, BatchDocument, DocumentType
from certificates.tests import PW, WorkflowTestBase, due
from execution.models import Assignment, RetestRequest
from lims.models import Sample, SampleType, Specification, SpecStatus, TestDefinition, TestResult
from standards.models import TestTemplate
from quality.models import Investigation
from . import export
from .engine import REPORTS, text_of


class ReportTestBase(WorkflowTestBase):
    def non_batch_sample(self):
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "from_batch": False, "reference": "Purified water, point WP-3",
            "quantity": "500 mL", "received_from": "Utilities", "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": self.analyst.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Sample.objects.get(pk=r.data["id"])

    def someone_elses(self, sample, **changes):
        """Move a sample away from the analyst, with the assignment that lets them see it."""
        force_update(Sample.objects.filter(pk=sample.pk), assigned_analyst=self.checker, **changes)
        force_update(Assignment.objects.filter(sample=sample), to_user=self.checker)

    def grant(self, user, permission):
        user.role.grants.create(permission=permission, reason="test")
        user._perm_cache = None

    def report(self, key, query="", user=None, code=200):
        self.login(user or self.approver)
        r = self.client.get(f"/api/reports/{key}/?{query}")
        self.assertEqual(r.status_code, code, r.content)
        return r.data

    def rows(self, key, query="", user=None):
        return self.report(key, query, user)["results"]

    def text(self, cell):
        return cell["text"] if isinstance(cell, dict) else cell

    def column(self, key, column, query="", user=None):
        return [self.text(row[column]) for row in self.rows(key, query, user)]

    def released_sample(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        sample.refresh_from_db()
        return sample, cert

    def failed_sample(self):
        sample = self.register_sample()
        self.enter_results(sample, assay="80.0")
        return sample

    def retested_sample(self, kind="RETEST", value="99.0"):
        sample = self.failed_sample()
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/retests/", {
            "test_definition_id": self.t_assay.id, "reason": "Dilution error on the worksheet", "kind": kind,
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        request = RetestRequest.objects.get(sample=sample)
        self.login(self.approver)
        r = self.client.post(f"/api/retests/{request.id}/decide/", {"action": "authorize"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/", {
            "test_definition_id": self.t_assay.id, "value_numeric": value,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return sample


class AccessTests(ReportTestBase):
    def test_every_report_opens_and_says_who_produced_it_and_when(self):
        self.released_sample()
        self.failed_sample()
        self.login(self.admin)
        for key in REPORTS:
            data = self.report(key, user=self.admin)
            self.assertIn("generated_at", data, key)
            self.assertEqual(data["generated_by"], self.admin.display_name(), key)
            self.assertEqual(data["timezone"], "Asia/Karachi", key)
            definition = self.client.get(f"/api/reports/{key}/definition/").data
            self.assertTrue(definition["columns"], key)

    def test_every_report_works_for_someone_who_sees_only_their_own_samples(self):
        self.released_sample()
        self.retested_sample()
        self.grant(self.analyst, "report.export")
        self.login(self.analyst)
        for key, report in REPORTS.items():
            expected = 200 if self.analyst.has_perm_key(report.permission) else 403
            self.assertEqual(self.client.get(f"/api/reports/{key}/").status_code, expected, key)
            self.assertEqual(self.client.get(f"/api/reports/{key}/export/?file=csv").status_code, expected, key)

    def test_a_role_without_the_permission_cannot_open_reports(self):
        self.roles["ANALYST"].grants.filter(permission="report.view").update(revoked_at=timezone.now())
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/reports/").status_code, 403)
        self.assertEqual(self.client.get("/api/reports/sample-register/").status_code, 403)
        self.assertEqual(self.client.get("/api/reports/dashboard/").status_code, 403)

    def test_workload_and_the_audit_trail_need_their_own_permission(self):
        self.report("analyst-workload", user=self.analyst, code=403)
        self.report("bottlenecks", user=self.frontdesk, code=403)
        self.report("audit-trail", user=self.analyst, code=403)
        self.report("analyst-workload", user=self.approver)

    def test_the_catalogue_does_not_mention_what_they_cannot_open(self):
        self.login(self.analyst)
        keys = {r["key"] for c in self.client.get("/api/reports/").data["categories"] for r in c["reports"]}
        self.assertIn("sample-register", keys)
        self.assertNotIn("analyst-workload", keys)
        self.assertNotIn("audit-trail", keys)

    def test_an_analyst_sees_only_their_own_samples_everywhere(self):
        mine = self.register_sample()
        other = self.register_sample()
        self.someone_elses(other)
        self.enter_results(mine, assay="80.0")
        self.assertEqual(self.column("sample-register", "sample", user=self.analyst), [mine.sample_no])
        self.assertEqual(self.column("pending-work", "task", user=self.analyst), [mine.sample_no])
        self.assertEqual(self.report("test-results", user=self.analyst)["count"], 2)

        self.login(self.analyst)
        self.assertEqual(self.client.get(f"/api/reports/documents/sample/{other.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/reports/documents/sample/{mine.id}/").status_code, 200)
        tiles = {t["key"]: t["value"] for t in self.client.get("/api/reports/dashboard/").data["now"]}
        self.assertEqual(tiles["UNDER_TESTING"], 1)

    def test_a_filter_cannot_see_past_what_the_person_may_see(self):
        other = self.register_sample()
        self.someone_elses(other)
        self.assertEqual(self.report("sample-register", f"q={other.sample_no}", user=self.analyst)["count"], 0)

    def test_a_filter_or_sort_that_makes_no_sense_is_refused_not_ignored(self):
        self.report("sample-register", "stage=NONSENSE", code=400)
        self.report("sample-register", "sort=nonsense", code=400)
        self.report("sample-register", "date_field=nonsense", code=400)
        self.report("sample-register", "from=2026-02-31", code=400)


class DashboardTests(ReportTestBase):
    def tile_matches_its_list(self, tile):
        path, _, query = tile["to"].partition("?")
        key = path.rsplit("/", 1)[1]
        self.assertEqual(self.report(key, query)["count"], tile["value"], tile["label"])

    def test_every_tile_opens_exactly_the_records_it_counts(self):
        self.register_sample()  # awaiting testing
        self.failed_sample()  # under testing, needs investigation
        late = self.register_sample()
        Sample.objects.filter(pk=late.pk).update(due_date=timezone.localdate() - timedelta(days=2))
        reviewing = self.register_sample()
        self.enter_results(reviewing)
        self.sign_analyst(reviewing)
        approving = self.register_sample()
        self.enter_results(approving)
        cert = self.sign_analyst(approving)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.released_sample()

        self.login(self.approver)
        data = self.client.get("/api/reports/dashboard/?period=month").data
        tiles = {t["key"]: t for t in data["now"] + data["period"]}
        self.assertEqual(tiles["AWAITING_TESTING"]["value"], 2)
        self.assertEqual(tiles["UNDER_TESTING"]["value"], 1)
        self.assertEqual(tiles["AWAITING_REVIEW"]["value"], 1)
        self.assertEqual(tiles["AWAITING_APPROVAL"]["value"], 1)
        self.assertEqual(tiles["INVESTIGATE"]["value"], 1)
        self.assertEqual(tiles["OVERDUE"]["value"], 1)
        self.assertEqual(tiles["RECEIVED"]["value"], 6)
        self.assertEqual(tiles["COMPLETED"]["value"], 1)
        for tile in data["now"] + data["period"][:2]:
            self.tile_matches_its_list(tile)

    def test_a_failed_test_a_failed_sample_and_a_batch_are_counted_apart(self):
        sample = self.failed_sample()
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/results/", {
            "test_definition_id": self.t_desc.id, "value_text": "Does not comply", "supersede_reason": "Rechecked",
        }, format="json")
        self.failed_sample()
        self.login(self.approver)
        failures = self.client.get("/api/reports/dashboard/?period=month").data["failures"]
        self.assertEqual(failures["tests"], 3)
        self.assertEqual(failures["samples"], 2)
        self.assertEqual(failures["batches"], 1)  # both samples are batch B-001

    def test_a_sample_stops_needing_investigation_only_when_one_closes(self):
        sample = self.retested_sample()  # the retest passed
        self.assertEqual(self.report("sample-register", "investigate=1")["count"], 1)

        inv = self.open_oos(sample)
        self.assertEqual(self.report("sample-register", "investigate=1")["count"], 1)
        Investigation.objects.filter(pk=inv.pk).update(status="CLOSED", closed_at=timezone.now())
        self.assertEqual(self.report("sample-register", "investigate=1")["count"], 0)

    def open_oos(self, sample):
        failed = sample.results.get(test_definition=self.t_assay, outcome="FAIL")
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "Assay below limit",
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Investigation.objects.get(pk=r.data["id"])

    def test_a_failure_after_a_closure_needs_looking_at_afresh(self):
        sample = self.retested_sample()
        inv = self.open_oos(sample)
        Investigation.objects.filter(pk=inv.pk).update(status="CLOSED", closed_at=timezone.now())
        self.assertEqual(self.report("sample-register", "investigate=1")["count"], 0)
        # A later result on the same test fails after the investigation closed.
        current = sample.results.get(test_definition=self.t_assay, is_superseded=False)
        force_update(TestResult.objects.filter(pk=current.pk), 
            outcome="FAIL", entered_at=timezone.now() + timedelta(minutes=1),
        )
        self.assertEqual(self.report("sample-register", "investigate=1")["count"], 1)

    def test_a_bar_for_an_analyst_opens_the_work_it_counts(self):
        self.register_sample()
        self.register_sample()
        self.login(self.approver)
        bar = self.client.get("/api/reports/dashboard/").data["charts"]["analysts"][0]
        self.assertEqual(bar["pending"], 2)
        path, _, query = bar["to"].partition("?")
        self.assertEqual(self.report(path.rsplit("/", 1)[1], query)["count"], 2)

    def test_a_period_with_no_activity_still_shows_every_day(self):
        self.login(self.approver)
        flow = self.client.get("/api/reports/dashboard/?period=week").data["charts"]["flow"]
        self.assertEqual(flow["unit"], "day")
        self.assertGreaterEqual(len(flow["points"]), 1)
        self.assertEqual(flow["series"], ["Received", "Completed"])

    def test_workload_on_the_dashboard_needs_the_permission(self):
        self.register_sample()
        self.login(self.approver)
        self.assertIn("analysts", self.client.get("/api/reports/dashboard/").data["charts"])
        self.login(self.frontdesk)
        self.assertNotIn("analysts", self.client.get("/api/reports/dashboard/").data["charts"])


class SampleReportTests(ReportTestBase):
    def test_the_register_shows_where_each_sample_is(self):
        sample, _ = self.released_sample()
        waiting = self.register_sample()
        rows = {self.text(r["sample"]): r for r in self.rows("sample-register")}
        self.assertEqual(self.text(rows[sample.sample_no]["stage"]), "Released")
        self.assertEqual(self.text(rows[sample.sample_no]["review"]), "Approved")
        self.assertEqual(self.text(rows[waiting.sample_no]["stage"]), "Received")
        self.assertEqual(self.text(rows[waiting.sample_no]["results"]), "No results yet")
        self.assertEqual(rows[waiting.sample_no]["turnaround"]["sub"], "so far")
        self.assertEqual(rows[sample.sample_no]["sample"]["to"], f"/reports/sample-history/{sample.id}")

    def test_the_register_filters_and_sorts(self):
        self.register_sample()
        second = self.register_sample()
        self.product.sample_type = SampleType.FINISHED_PRODUCT
        self.product.save()
        force_update(Sample.objects.filter(pk=second.pk), batch_no="ZZ-9")
        self.assertEqual(self.column("sample-register", "batch", "batch=zz"), ["ZZ-9"])
        self.assertEqual(self.report("sample-register", "sample_type=FINISHED_PRODUCT")["count"], 2)
        self.assertEqual(self.report("sample-register", "stage=COMPLETED")["count"], 0)
        self.assertEqual(self.report("sample-register", f"analyst={self.analyst.id}")["count"], 2)
        self.assertEqual(self.column("sample-register", "batch", "sort=batch"), ["B-001", "ZZ-9"])
        self.assertEqual(self.column("sample-register", "batch", "sort=-batch"), ["ZZ-9", "B-001"])

    def test_dates_read_the_same_for_everyone_in_the_labs_time_zone(self):
        sample = self.register_sample()
        moment = timezone.make_aware(timezone.datetime(2026, 10, 30, 23, 30, 5))
        force_update(Sample.objects.filter(pk=sample.pk), received_at=moment)
        self.assertEqual(self.column("sample-register", "received")[0], "30-Oct-2026 11:30:05 PM")

    def test_turnaround_runs_from_receipt_to_the_final_signature(self):
        sample, _ = self.released_sample()
        force_update(Sample.objects.filter(pk=sample.pk), received_at=timezone.now() - timedelta(days=3))
        data = self.report("turnaround", "period=all")
        self.assertEqual(self.text(data["results"][0]["days"]), "3.0")
        tiles = {t["label"]: t["value"] for t in data["summary"]}
        self.assertEqual(tiles["Released"], 1)
        self.assertEqual(tiles["Median"], "3.0d")

    def test_sample_history_holds_all_of_it(self):
        sample = self.retested_sample()
        self.login(self.approver)
        doc = self.client.get(f"/api/reports/documents/sample/{sample.id}/").data
        titles = [s["title"] for s in doc["sections"]]
        self.assertEqual(titles[0], "1. Registration and receipt")
        self.assertEqual(len(titles), 9)
        results = doc["sections"][2]["parts"][0]["rows"]
        values = [self.text(r["result"]) for r in results]
        self.assertIn("80.0 %", values)  # the failure is still there
        self.assertIn("99.0 %", values)
        retests = doc["sections"][5]["parts"][0]["rows"]
        self.assertEqual(self.text(retests[0]["kind"]), "Retest")


class FailureReportTests(ReportTestBase):
    def test_a_passing_retest_never_removes_the_failed_result(self):
        sample = self.retested_sample()
        rows = self.rows("oos")
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.text(rows[0]["original"]), "80.0 %")
        self.assertEqual(rows[0]["retest"]["text"], "Retest: 99.0 %")
        self.assertEqual(rows[0]["investigation"]["text"], "None opened")
        self.assertEqual(self.report("test-results", "outcome=FAIL")["count"], 1)
        self.assertEqual(self.report("test-results", "outcome=FAIL&current=1")["count"], 0)
        self.assertEqual(sample.results.filter(outcome="FAIL").count(), 1)

    def test_the_oos_report_shows_the_investigation_behind_a_failure(self):
        sample = self.failed_sample()
        failed = sample.results.get(outcome="FAIL")
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "Assay below limit",
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        rows = self.rows("oos")
        self.assertEqual(rows[0]["investigation"]["text"], r.data["reference"])
        self.assertEqual(rows[0]["status"]["text"], "Under investigation")
        self.assertEqual(self.report("oos", "state=NONE")["count"], 0)
        self.assertEqual(self.report("oos", "state=OPEN")["count"], 1)

    def test_only_someone_who_can_open_one_is_offered_the_link(self):
        self.failed_sample()
        self.assertTrue(self.rows("oos")[0]["investigation"]["to"].startswith("/investigations/new"))
        self.assertNotIn("to", self.rows("oos", user=self.analyst)[0]["investigation"])

    def test_a_result_shows_the_template_version_its_method_came_from(self):
        TestDefinition.objects.filter(pk=self.t_assay.pk).update(method="HPLC", source="ASSAY-HPLC v3")
        self.enter_results(self.register_sample())
        row = next(r for r in self.rows("test-results") if self.text(r["test"]) == "Assay")
        self.assertEqual(row["method"], {"text": "HPLC", "sub": "ASSAY-HPLC v3"})

    def test_repeat_retest_and_resample_are_kept_apart(self):
        self.retested_sample("RETEST")
        self.retested_sample("REPEAT")
        self.retested_sample("RESAMPLE")
        self.assertEqual(self.report("retests", "kind=REPEAT")["count"], 1)
        self.assertEqual(
            sorted(self.column("retests", "kind")), ["Repeat analysis", "Resample", "Retest"],
        )
        tiles = {t["label"]: t["value"] for t in self.report("retests")["summary"]}
        self.assertEqual((tiles["Retest"], tiles["Repeat analysis"], tiles["Resample"]), (1, 1, 1))

    def test_a_request_of_an_unknown_kind_is_refused(self):
        sample = self.failed_sample()
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/retests/", {
            "test_definition_id": self.t_assay.id, "reason": "Why", "kind": "GUESS",
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_retest_says_what_happened_without_claiming_the_failure_was_invalid(self):
        self.retested_sample()
        self.assertEqual(self.text(self.rows("retests")[0]["outcome"]), "No investigation on record")

    def test_the_oos_tiles_count_each_failed_test_once(self):
        sample = self.retested_sample(value="80.5")  # the retest failed as well
        data = self.report("oos")
        tiles = {t["label"]: t["value"] for t in data["summary"]}
        self.assertEqual(tiles["Failed results"], 2)
        self.assertEqual(tiles["No investigation"], 1)
        self.assertEqual(sample.results.filter(outcome="FAIL").count(), 2)

    def test_trends_keep_the_precision_of_their_test(self):
        # Built directly: a test of an approved specification is never edited.
        TestDefinition.objects.filter(pk=self.t_assay.pk).update(
            decimals=2, limit_type="NUMERIC_MAX", min_value=None, max_value="1",
        )
        for value in ("0.28", "0.31", "0.34"):
            sample = self.register_sample()
            self.enter_results(sample, assay=value)
        row = self.rows("oot")[0]
        self.assertEqual(self.text(row["low"]), "0.28")
        self.assertEqual(self.text(row["high"]), "0.34")
        self.assertEqual(self.text(row["mean"]), "0.31")
        self.assertEqual(self.text(row["sd"]), "0.03")

    def test_trends_keep_incomparable_results_apart(self):
        for value in ("96", "97"):
            sample = self.register_sample()
            self.enter_results(sample, assay=value)
        spec = Specification.objects.create(
            product=self.product, version=2, status=SpecStatus.EFFECTIVE, effective_date="2026-06-01",
        )
        test = self.t_assay
        changed = type(test).objects.create(
            specification=spec, order=1, name="Assay", method="New HPLC", unit="%", limit_type=test.limit_type,
            min_value=test.min_value, max_value=test.max_value, decimals=1, limit_text=test.limit_text,
        )
        sample = self.register_sample()
        force_update(Sample.objects.filter(pk=sample.pk), specification=spec)
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/results/", {
            "test_definition_id": changed.id, "value_numeric": "98",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        rows = self.rows("oot")
        self.assertEqual(sorted((r["method"], r["results"]) for r in rows), [("", "2"), ("New HPLC", "1")])


class BatchReportTests(ReportTestBase):
    def test_a_batch_is_listed_once_with_everything_behind_it(self):
        self.released_sample()
        self.failed_sample()
        rows = self.rows("batches")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["batch"]["text"], "B-001")
        self.assertEqual(self.text(rows[0]["samples"]), "2")
        self.assertEqual(self.text(rows[0]["tests"]), "4 of 4")
        self.assertEqual(self.text(rows[0]["failed"]), "1")
        self.assertEqual(self.text(rows[0]["certificates"]), "1")

    def test_a_sample_with_no_batch_is_not_a_batch(self):
        self.non_batch_sample()
        self.assertEqual(self.report("batches")["count"], 0)

    def test_a_sample_with_no_batch_says_what_it_is_instead(self):
        sample = self.non_batch_sample()
        self.enter_results(sample, assay="80.0")
        self.assertEqual(self.column("sample-register", "batch"), ["Purified water, point WP-3"])
        self.assertEqual(self.report("sample-register", "batch=water")["count"], 1)
        self.assertEqual(self.rows("oos")[0]["product"]["sub"], "Purified water, point WP-3")
        self.assertEqual(self.rows("pending-work")[0]["product"]["sub"], "Purified water, point WP-3")
        self.login(self.approver)
        doc = self.client.get(f"/api/reports/documents/sample/{sample.id}/").data
        self.assertIn("Purified water", doc["subtitle"])

    def test_a_failure_with_no_batch_is_no_failed_batch(self):
        self.enter_results(self.non_batch_sample(), assay="80.0")
        self.login(self.approver)
        failures = self.client.get("/api/reports/dashboard/?period=month").data["failures"]
        self.assertEqual((failures["tests"], failures["samples"], failures["batches"]), (1, 1, 0))

    def test_one_batch_is_one_row_however_its_number_was_typed(self):
        first = self.register_sample()
        self.login(self.frontdesk)
        r = self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "b-001", "quantity": "60 tablets",
            "received_from": "Production", "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": self.analyst.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["batch_id"], first.batch_id)
        rows = self.rows("batches")
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.text(rows[0]["samples"]), "2")

    def test_a_deviation_counts_on_its_batch_however_it_was_typed(self):
        sample = self.register_sample()
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "DEVIATION", "description": "Balance out of date", "batch_no": "b-001",
            "product_id": self.product.id, "responsible_id": self.checker.id,
            "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.text(self.rows("batches")[0]["investigations"]), "1")
        self.login(self.approver)
        doc = self.client.get(f"/api/reports/documents/batch/{sample.batch_id}/").data
        self.assertIn(r.data["reference"], str(doc))

    def test_the_batch_summary_reads_the_batch_record(self):
        sample = self.register_sample()
        Batch.objects.filter(pk=sample.batch_id).update(manufacturing_site="Plant 2, Karachi", batch_size="100,000")
        BatchDocument.objects.create(
            batch=sample.batch, doc_type=DocumentType.BATCH_RECORD, title="Batch record", file="x.pdf",
            original_name="x.pdf", extension="pdf", content_type="application/pdf", size=1, sha256="0" * 64,
            uploaded_by=self.approver,
        )
        self.login(self.approver)
        doc = self.client.get(f"/api/reports/documents/batch/{sample.batch_id}/").data
        facts = {f["label"]: f["value"] for f in doc["sections"][0]["parts"][0]["items"]}
        self.assertEqual(facts["Manufacturing site"], "Plant 2, Karachi")
        self.assertEqual(facts["Batch size"], "100,000")
        self.assertEqual(facts["Internal ID"], sample.batch.internal_id)
        self.assertIn("Batch record", str(doc["sections"][-1]))
        self.assertEqual(self.text(self.rows("batches")[0]["site"]), "Plant 2, Karachi")

    def test_the_batch_summary_says_when_no_disposition_has_been_decided(self):
        self.released_sample()
        self.login(self.approver)
        sample = Sample.objects.get(batch_no="B-001")
        r = self.client.get(f"/api/reports/documents/batch/{sample.batch_id}/")
        self.assertEqual(r.status_code, 200, r.content)
        facts = {f["label"]: f["value"] for f in r.data["sections"][0]["parts"][0]["items"]}
        self.assertEqual(facts["Batch disposition"], "Not decided")
        self.assertEqual(self.client.get("/api/reports/documents/batch/999999/").status_code, 404)

    def test_product_history_counts_a_failure_that_was_later_retested(self):
        self.retested_sample()
        self.released_sample()
        self.login(self.approver)
        doc = self.client.get(f"/api/reports/documents/product/{self.product.id}/").data
        rates = {self.text(r["test"]): r for r in doc["sections"][1]["parts"][0]["rows"]}
        self.assertEqual(self.text(rates["Assay"]["failed"]), "1")
        self.assertEqual(self.text(rates["Assay"]["graded"]), "3")
        trends = [p for p in doc["sections"][2]["parts"] if p["kind"] == "trend"]
        self.assertEqual([p["y"] for p in trends[0]["points"]], [99.0, 99.5])

    def test_documents_do_not_show_investigations_the_person_cannot_see(self):
        mine = self.register_sample()
        hidden = self.failed_sample()
        self.someone_elses(hidden)
        self.login(self.checker)
        failed = hidden.results.get(outcome="FAIL")
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "Below limit",
            "responsible_id": self.checker.id, "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        reference = r.data["reference"]

        self.login(self.analyst)
        batch = self.client.get(f"/api/reports/documents/batch/{mine.batch_id}/")
        self.assertEqual(batch.status_code, 200, batch.content)
        self.assertNotIn(reference, str(batch.data))
        product = self.client.get(f"/api/reports/documents/product/{self.product.id}/")
        self.assertNotIn(reference, str(product.data))
        self.assertEqual(self.text(self.rows("batches", user=self.analyst)[0]["investigations"]), "0")

        self.login(self.approver)
        batch = self.client.get(f"/api/reports/documents/batch/{mine.batch_id}/")
        self.assertIn(reference, str(batch.data))

    def test_a_batch_row_is_the_whole_batch_whatever_the_dates(self):
        first = self.register_sample()
        self.register_sample()
        force_update(Sample.objects.filter(pk=first.pk), received_at=timezone.now() - timedelta(days=200))
        rows = self.rows("batches", "period=month")
        self.assertEqual(self.text(rows[0]["samples"]), "2")
        self.assertEqual(self.text(rows[0]["tests"]), "0 of 4")

    def test_a_blank_batch_is_not_counted_as_a_batch_of_the_product(self):
        self.non_batch_sample()
        self.assertEqual(self.text(self.rows("product-history")[0]["batches"]), "0")

    def test_the_certificate_report_keeps_every_version(self):
        sample = self.register_sample()
        self.enter_results(sample)
        first = self.sign_analyst(sample)
        self.assertEqual(self.send_back(first, self.checker, "Wrong batch on worksheet").status_code, 200)
        self.login(self.analyst)
        second = self.sign_analyst(sample)
        self.assertEqual(self.sign(second, self.checker).status_code, 200)
        self.assertEqual(self.sign(second, self.approver).status_code, 200)
        rows = self.rows("certificates")
        by_number = {r["number"]["text"]: r for r in rows}
        self.assertEqual(set(by_number), {f"{sample.sample_no}/v1", f"{sample.sample_no}/v2"})
        self.assertIn("Wrong batch on worksheet", self.text(by_number[f"{sample.sample_no}/v1"]["history"]))
        self.assertEqual(self.text(by_number[f"{sample.sample_no}/v1"]["issued"]), "")
        self.assertRegex(self.text(by_number[f"{sample.sample_no}/v2"]["issued"]), r"^\d{2}-\w{3}-\d{4} \d{2}:\d{2}:\d{2} [AP]M$")
        self.assertEqual(self.report("certificates", f"number={sample.sample_no}/v2")["count"], 1)
        self.assertEqual(self.report("certificates", "status=SUPERSEDED")["count"], 1)


class WorkflowReportTests(ReportTestBase):
    def test_pending_work_puts_each_sample_in_its_queue(self):
        testing = self.register_sample()
        reviewing = self.register_sample()
        self.enter_results(reviewing)
        self.sign_analyst(reviewing)
        returned = self.register_sample()
        self.enter_results(returned)
        back = self.sign_analyst(returned)
        self.assertEqual(self.send_back(back, self.checker, "Recheck the assay").status_code, 200)

        rows = {self.text(r["task"]): self.text(r["queue"]) for r in self.rows("pending-work")}
        self.assertEqual(rows[testing.sample_no], "Tests awaiting execution")
        self.assertEqual(rows[reviewing.sample_no], "Work awaiting review")
        self.assertEqual(rows[returned.sample_no], "Returned for correction")
        self.assertEqual(self.report("pending-work", "queue=RETURNED")["count"], 1)

    def test_a_step_is_placed_as_late_as_it_comes_in_any_workflow(self):
        self.released_sample()
        short = self.make_workflow("Short", [("Approved", "Approved by", self.roles["APPROVER"])])
        self.product.workflow = short
        self.product.save()
        sample = self.register_sample()
        self.enter_results(sample)
        self.assertEqual(self.sign(self.sign_analyst(sample), self.approver).status_code, 200)
        self.assertEqual(self.column("bottlenecks", "stage", "period=all"), ["Testing", "Checked", "Approved"])

    def test_bottlenecks_count_signatures_stopped_by_something_missing(self):
        sample = self.register_sample()
        self.enter_results(sample, assay="80.0")
        self.login(self.analyst)
        r = self.client.post(f"/api/samples/{sample.id}/sign-analyst/", {"password": PW}, format="json")
        self.assertEqual(r.status_code, 400)
        rows = {self.text(r["stage"]): r for r in self.rows("bottlenecks", "period=all")}
        self.assertEqual(self.text(rows["Testing"]["blocked"]), "1")

    def test_overdue_work_counts_the_days_and_gives_the_hold_reason(self):
        sample = self.register_sample()
        Sample.objects.filter(pk=sample.pk).update(due_date=timezone.localdate() - timedelta(days=4))
        self.login(self.approver)
        r = self.client.post(f"/api/samples/{sample.id}/hold/", {"reason": "Waiting for a reference standard"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.content)
        rows = self.rows("overdue")
        self.assertEqual(self.text(rows[0]["overdue_days"]), "4")
        self.assertEqual(self.text(rows[0]["hold"]), "Waiting for a reference standard")

    def test_overdue_work_includes_investigations_and_actions(self):
        sample = self.failed_sample()
        failed = sample.results.get(outcome="FAIL")
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "OOS", "result_id": failed.id, "description": "Below limit", "responsible_id": self.checker.id,
            "due_date": (timezone.localdate() - timedelta(days=1)).isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        rows = self.rows("overdue")
        self.assertEqual(self.text(rows[0]["type"]), "Investigation")
        self.assertEqual(self.text(rows[0]["task"]), r.data["reference"])

    def test_workload_is_listed_by_name_not_by_volume(self):
        self.released_sample()
        self.register_sample()
        data = self.report("analyst-workload", "period=all")
        self.assertEqual(self.text(data["results"][0]["active"]), "1")
        self.assertEqual(self.text(data["results"][0]["pending"]), "2")
        self.assertEqual(self.text(data["results"][0]["completed"]), "2")
        definition = self.client.get("/api/reports/analyst-workload/definition/").data
        self.assertEqual(definition["default_sort"], "analyst")
        self.assertIn("not for ranking", definition["note"])

    def test_bottlenecks_show_each_step_and_what_came_back_from_it(self):
        self.released_sample()
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.send_back(cert, self.checker, "Recheck").status_code, 200)
        rows = {self.text(r["stage"]): r for r in self.rows("bottlenecks", "period=all")}
        self.assertEqual(list(rows)[0], "Testing")
        self.assertEqual(self.text(rows["Testing"]["completed"]), "2")
        self.assertEqual(self.text(rows["Testing"]["backlog"]), "1")
        self.assertEqual(self.text(rows["Checked"]["returned"]), "1")
        self.assertEqual(self.text(rows["Checked"]["completed"]), "2")
        self.assertEqual(self.text(rows["Approved"]["completed"]), "1")


class ComplianceReportTests(ReportTestBase):
    def test_the_audit_report_reads_the_protected_record(self):
        sample = self.register_sample()
        data = self.report("audit-trail", "period=all", user=self.admin)
        self.assertGreaterEqual(data["count"], 1)
        row = next(r for r in data["results"] if self.text(r["record"]) == sample.sample_no)
        self.assertIn("registered sample", self.text(row["what"]))
        self.assertEqual(self.report(
            "audit-trail", "period=all&action=SAMPLE_REGISTERED", user=self.admin)["count"], 1)

    def test_document_control_shows_what_is_current_and_what_is_superseded(self):
        self.register_sample()
        Specification.objects.create(
            product=self.product, version=9, status=SpecStatus.SUPERSEDED, effective_date="2025-01-01",
        )
        Specification.objects.create(
            product=self.product, version=10, status=SpecStatus.DRAFT, effective_date="2027-01-01",
            review_date=timezone.localdate() + timedelta(days=30),
        )
        rows = self.rows("document-control", "type=Specification")
        states = {self.text(r["version"]): self.text(r["status"]) for r in rows}
        self.assertEqual(states["v1"], "Current approved")
        self.assertEqual(states["v9"], "Superseded")
        self.assertEqual(states["v10"], "Awaiting approval")
        self.assertEqual(self.report("document-control", "reviewing=1")["count"], 1)
        linked = next(r for r in rows if self.text(r["version"]) == "v1")["linked"]
        self.assertEqual(linked["text"], "1")
        self.assertIn("spec=", linked["to"])

    def test_a_workflow_is_a_document_too(self):
        self.assertEqual(self.report("document-control", "type=Review%20workflow")["count"], 1)

    def test_a_specification_shows_who_approved_it(self):
        force_update(Specification.objects.filter(pk=self.spec.pk), approved_by=self.approver, approved_at=timezone.now())
        row = self.rows("document-control", "type=Specification")[0]
        self.assertEqual(row["approved"]["text"], self.approver.display_name())

    def test_a_test_template_is_listed_with_its_versions(self):
        for version, retired in ((1, False), (2, False)):
            TestTemplate.objects.create(
                code="ASSAY-HPLC", version=version, name="Assay by HPLC", limit_type="REPORT_ONLY",
                limit_text="Report", is_retired=retired, created_by=self.admin,
            )
        rows = self.rows("document-control", "type=Test%20template")
        states = {self.text(r["version"]): self.text(r["status"]) for r in rows}
        self.assertEqual(states, {"v1": "Superseded", "v2": "Current"})

    def test_the_register_lists_deviations_with_their_actions(self):
        self.login(self.checker)
        r = self.client.post("/api/investigations/", {
            "kind": "DEVIATION", "classification": "MINOR", "description": "Balance out of calibration",
            "responsible_id": self.checker.id, "due_date": (timezone.localdate() + timedelta(days=5)).isoformat(),
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        r2 = self.client.post(f"/api/investigations/{r.data['id']}/actions/", {
            "kind": "CORRECTIVE", "description": "Recalibrate", "owner_id": self.checker.id,
            "due_date": timezone.localdate().isoformat(),
        }, format="json")
        self.assertEqual(r2.status_code, 200, r2.content)
        data = self.report("deviations")
        self.assertEqual(data["results"][0]["capa"]["sub"], "1 of 1 open")
        tiles = {t["label"]: t["value"] for t in data["summary"]}
        self.assertEqual(tiles["Open actions"], 1)
        self.assertEqual(tiles["Under investigation"], 1)
        self.assertEqual(self.report("deviations", "kind=OOS")["count"], 0)


class ExportTests(ReportTestBase):
    def download(self, key, file_format, query="", user=None):
        self.login(user or self.approver)
        return self.client.get(f"/api/reports/{key}/export/?file={file_format}&{query}")

    def csv_rows(self, key, query=""):
        response = self.download(key, "csv", query)
        self.assertEqual(response.status_code, 200, response.content)
        return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

    def test_every_report_exports_in_every_format(self):
        self.released_sample()
        self.retested_sample()
        for key in REPORTS:
            for file_format, signature in (("csv", b""), ("xlsx", b"PK"), ("pdf", b"%PDF")):
                response = self.download(key, file_format, user=self.admin)
                self.assertEqual(response.status_code, 200, f"{key} {file_format}: {response.content[:200]}")
                self.assertTrue(response.content.startswith(signature), (key, file_format))
                self.assertIn(f".{file_format}", response["Content-Disposition"])

    def test_the_csv_says_exactly_what_the_screen_says(self):
        sample = self.register_sample()
        rows = self.csv_rows("sample-register")
        self.assertEqual(rows[0][0], "Sample ID")
        self.assertEqual(rows[1][0], sample.sample_no)
        on_screen = self.column("sample-register", "received")[0]
        self.assertEqual(rows[1][5], on_screen)

    def test_an_export_says_who_authorized_what_the_screen_shows_on_a_second_line(self):
        self.retested_sample()
        rows = self.csv_rows("retests")
        header, row = rows[0], rows[1]
        self.assertIn(self.approver.display_name(), row[header.index("Authorization")])
        self.assertIn(self.analyst.display_name(), row[header.index("Requested")])

    def test_turnaround_stays_a_plain_number_in_a_file(self):
        self.register_sample()
        rows = self.csv_rows("sample-register")
        self.assertEqual(rows[1][rows[0].index("Turnaround (days)")], "0.0")

    def test_an_export_covers_every_page_not_just_the_one_on_screen(self):
        for _ in range(3):
            self.register_sample()
        self.assertEqual(len(self.csv_rows("sample-register", "page_size=1")) - 1, 3)

    def test_an_export_keeps_to_the_filters_and_the_persons_samples(self):
        mine = self.register_sample()
        other = self.register_sample()
        self.someone_elses(other, batch_no="ZZ")
        self.grant(self.analyst, "report.export")
        response = self.download("sample-register", "csv", user=self.analyst)
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        self.assertIn(mine.sample_no, text)
        self.assertNotIn(other.sample_no, text)
        self.assertEqual(len(self.csv_rows("sample-register", "batch=ZZ")) - 1, 1)

    def test_exporting_needs_the_permission(self):
        self.assertEqual(self.download("sample-register", "csv", user=self.analyst).status_code, 403)
        self.assertEqual(self.download("audit-trail", "csv", user=self.analyst).status_code, 403)
        self.assertEqual(self.download("sample-register", "exe").status_code, 400)

    def test_every_export_is_recorded_with_its_filters(self):
        self.register_sample()
        self.download("sample-register", "pdf", "batch=B-001")
        event = AuditEvent.objects.get(action="REPORT_EXPORTED")
        self.assertEqual(event.actor, self.approver)
        self.assertEqual(event.details["format"], "PDF")
        self.assertEqual(event.details["rows"], 1)
        self.assertIn("B-001", event.details["filters"])

    def test_a_typed_formula_arrives_as_text(self):
        sample = self.register_sample()
        force_update(Sample.objects.filter(pk=sample.pk), batch_no='=HYPERLINK("http://x","y")')
        rows = self.csv_rows("sample-register")
        self.assertTrue(rows[1][2].startswith("'="))

        response = self.download("sample-register", "xlsx")
        sheet = load_workbook(io.BytesIO(response.content)).active
        found = [c for row in sheet.iter_rows() for c in row if isinstance(c.value, str) and "HYPERLINK" in c.value]
        self.assertEqual(found[0].data_type, "s")

    def test_a_negative_number_stays_a_number(self):
        self.assertEqual(export._csv_text("-0.5"), "-0.5")
        self.assertEqual(export._csv_text(-0.5), "-0.5")

    def test_excel_dates_are_real_dates(self):
        self.register_sample()
        response = self.download("sample-register", "xlsx")
        sheet = load_workbook(io.BytesIO(response.content)).active
        header = next(r for r in sheet.iter_rows() if r[0].value == "Sample ID")
        received = sheet.cell(header[0].row + 1, 6)
        self.assertEqual(received.is_date, True)

    def test_a_pdf_over_the_limit_is_refused_rather_than_cut_short(self):
        self.register_sample()
        self.register_sample()
        original = export.ROW_LIMITS["pdf"]
        export.ROW_LIMITS["pdf"] = 1
        try:
            response = self.download("sample-register", "pdf")
        finally:
            export.ROW_LIMITS["pdf"] = original
        self.assertEqual(response.status_code, 400)
        self.assertIn("limit", response.data["detail"])
        self.assertFalse(AuditEvent.objects.filter(action="REPORT_EXPORTED").exists())

    def test_the_sample_history_exports_as_a_pdf_and_is_recorded(self):
        sample = self.retested_sample()
        self.login(self.approver)
        response = self.client.get(f"/api/reports/documents/sample/{sample.id}/?file=pdf")
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertTrue(response.content.startswith(b"%PDF"))
        event = AuditEvent.objects.get(action="DOCUMENT_EXPORTED", entity_id=sample.sample_no)
        self.assertIn(f"Sample History Report for {sample.sample_no} as PDF", describe(event)["sentence"])

    def test_documents_need_the_export_permission_as_files_but_not_on_screen(self):
        sample = self.register_sample()
        self.login(self.analyst)
        self.assertEqual(self.client.get(f"/api/reports/documents/sample/{sample.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/reports/documents/sample/{sample.id}/?file=pdf").status_code, 403)

    def test_batch_and_product_documents_export(self):
        sample, _ = self.released_sample()
        self.login(self.approver)
        for url in (f"/api/reports/documents/batch/{sample.batch_id}/",
                    f"/api/reports/documents/product/{self.product.id}/"):
            response = self.client.get(f"{url}?file=pdf")
            self.assertEqual(response.status_code, 200, response.content[:200])
            self.assertTrue(response.content.startswith(b"%PDF"))

    def test_a_typed_batch_number_cannot_reach_the_download_header(self):
        sample = self.register_sample()
        Batch.objects.filter(pk=sample.batch_id).update(official_batch_no='B/1"; x=\\y')
        self.login(self.approver)
        response = self.client.get(f"/api/reports/documents/batch/{sample.batch_id}/?file=pdf")
        self.assertEqual(response.status_code, 200, response.content[:200])
        name = response["Content-Disposition"].split("filename=")[1].strip('"')
        self.assertRegex(name, r"^[A-Za-z0-9._-]+$")


class TextOfTests(ReportTestBase):
    def test_every_value_is_written_one_way(self):
        moment = timezone.make_aware(timezone.datetime(2026, 1, 2, 3, 4, 5))
        self.assertEqual(text_of(moment), "02-Jan-2026 03:04:05 AM")
        self.assertEqual(text_of(moment.date()), "02-Jan-2026")
        self.assertEqual(text_of(None), "")
        self.assertEqual(text_of(2.456), "2.5")
