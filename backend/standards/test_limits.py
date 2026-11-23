"""The limit a certificate prints is the limit results are judged against."""
from .tests import ASSAY, StandardsTestBase


class LimitWordingTests(StandardsTestBase):
    def refused(self, test):
        self.draft()
        spec = self.the_draft()
        r = self.edit(spec, [test])
        self.assertEqual(r.status_code, 400)
        return r.data["detail"]

    def test_a_printed_limit_cannot_differ_from_the_judged_limit(self):
        message = self.refused({**ASSAY, "min_value": "90", "max_value": "110",
                                "limit_text": "95.0 – 105.0 %"})
        self.assertIn("must state 90", message)

    def test_wording_may_differ_as_long_as_the_numbers_agree(self):
        self.draft()
        spec = self.the_draft()
        r = self.edit(spec, [{**ASSAY, "min_value": "95", "max_value": "105",
                              "limit_text": "95.0% to 105.0% of label claim"}])
        self.assertEqual(r.status_code, 200, r.content)

    def test_results_cannot_be_rounded_more_coarsely_than_the_limit(self):
        message = self.refused({"name": "Impurity", "limit_type": "NUMERIC_MAX", "max_value": "0.10", "decimals": 0})
        self.assertIn("written to 1 decimal place", message)

    def test_a_limit_can_be_written_to_more_places_than_it_needs(self):
        self.draft()
        spec = self.the_draft()
        r = self.edit(spec, [{"name": "Impurity", "limit_type": "NUMERIC_MAX", "max_value": "0.10",
                              "decimals": 2, "unit": "%"}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(spec.tests.get().limit_text, "NMT 0.10 %")
