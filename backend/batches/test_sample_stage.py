"""
A sample's page shows where its batch stands in its QC stages, with its own stage marked:
the sample says which stage it was taken for, and whoever sees the sample sees its batch.
"""
from .test_qc_stages import StageBase


class SampleStageTests(StageBase):
    def test_the_sample_says_which_qc_stage_it_was_taken_for(self):
        ids = self.set_up_stages()
        sample = self.registered(ids["Final grain"])
        self.login(self.admin)
        r = self.client.get(f"/api/samples/{sample.id}/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.data["qc_stage_id"], r.data["qc_stage_name"]), (ids["Final grain"], "Final grain"))

    def test_a_sample_taken_for_no_stage_says_so(self):
        r = self.register()
        self.assertEqual(r.status_code, 201, r.content)
        self.login(self.admin)
        r = self.client.get(f"/api/samples/{r.data['id']}/")
        self.assertIsNone(r.data["qc_stage_id"])
        self.assertEqual(r.data["qc_stage_name"], "")

    def test_the_analyst_who_sees_the_sample_sees_its_batch_stages(self):
        ids = self.set_up_stages()
        sample = self.registered(ids["Final grain"])
        self.login(self.analyst)
        r = self.client.get(f"/api/batches/{sample.batch_id}/")
        self.assertEqual(r.status_code, 200, r.content)
        stages = {s["id"]: s for s in r.data["qc_stages"]["stages"]}
        self.assertEqual(stages[ids["Final grain"]]["name"], "Final grain")
        self.assertEqual(len(stages), len(ids))
