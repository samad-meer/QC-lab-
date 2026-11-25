"""
A sample in a list or on a card shows how far along its journey it is: the steps its
workflow has (received, tested, each review, printed) and how many are behind it.
"""
from certificates.tests import WorkflowTestBase
from .models import SampleStatus


class SampleJourneyTests(WorkflowTestBase):
    def journey(self, sample, user=None):
        self.login(user or self.admin)
        r = self.client.get("/api/samples/")
        self.assertEqual(r.status_code, 200, r.content)
        return next(s for s in r.data["results"] if s["id"] == sample.id)["journey"]

    def test_a_sample_shows_its_place_on_the_journey_to_release(self):
        sample = self.register_sample()
        total = 3 + sample.workflow_version.stages.count()
        self.assertGreaterEqual(total, 4)
        self.assertEqual(self.journey(sample), {"done": 1, "total": total})  # received; testing is next

        self.login(self.analyst)
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.journey(sample), {"done": 2, "total": total})  # tested; the first review is next

        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.journey(sample), {"done": 3, "total": total})
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        sample.refresh_from_db()
        self.assertEqual(sample.status, SampleStatus.APPROVED)
        self.assertEqual(self.journey(sample), {"done": total, "total": total})  # nothing left to wait for

    def test_the_page_costs_one_query_for_all_its_samples(self):
        for _ in range(4):
            self.register_sample()
        self.login(self.admin)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as q:
            r = self.client.get("/api/samples/")
        self.assertEqual(len(r.data["results"]), 4)
        counting = [x for x in q.captured_queries if 'COUNT("lims_workflowstage"' in x["sql"]]
        self.assertEqual(len(counting), 1, "the journey must not cost a query per sample")
