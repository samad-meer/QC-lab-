"""
The menu badge and the dashboard ask the task center for its counts only (?counts=1). Those counts are
the same as the full answer's, for everyone, and the short answer costs fewer queries.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext

from certificates.tests import WorkflowTestBase


class TaskCountTests(WorkflowTestBase):
    def answer(self, user, query=""):
        self.login(user)
        with CaptureQueriesContext(connection) as queries:
            r = self.client.get(f"/api/tasks/{query}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data, len(queries)

    def some_work(self):
        self.register_sample()  # waiting for the analyst's testing
        tested = self.register_sample()
        self.enter_results(tested)  # tested, not yet signed
        review = self.register_sample()
        self.enter_results(review)
        self.login(self.analyst)
        self.sign_analyst(review)  # waiting for the checker's review

    def test_the_counts_are_the_same_with_or_without_the_detail(self):
        self.some_work()
        for user in (self.analyst, self.checker, self.approver, self.frontdesk, self.admin):
            full, _ = self.answer(user)
            short, _ = self.answer(user, "?counts=1")
            self.assertEqual(short["counts"], full["counts"], user.username)
            self.assertEqual(short["actionable"], full["actionable"], user.username)
        full, _ = self.answer(self.analyst)
        self.assertGreater(full["counts"]["my_testing"], 0)

    def test_the_short_answer_leaves_out_what_each_sample_still_needs(self):
        self.some_work()
        full, _ = self.answer(self.analyst)
        short, _ = self.answer(self.analyst, "?counts=1")
        self.assertIn("blockers", full["my_testing"][0])
        self.assertNotIn("blockers", short["my_testing"][0])
        self.assertEqual([r["sample"]["id"] for r in short["my_testing"]], [r["sample"]["id"] for r in full["my_testing"]])

    def test_the_short_answer_costs_fewer_queries(self):
        self.some_work()
        _, full = self.answer(self.analyst)
        _, short = self.answer(self.analyst, "?counts=1")
        self.assertLess(short, full)
