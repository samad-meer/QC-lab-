"""The Lab records overview: what each register is for, and how much it holds."""
from accounts.models import User
from certificates.tests import PW
from .test_base import LabTestBase


class OverviewTests(LabTestBase):
    def registers(self, user=None) -> dict:
        return {r["key"]: r for r in self.ok(self.get("/api/lab/registers/", user))["registers"]}

    def test_every_register_says_where_it_reaches_daily_work(self):
        for key, entry in self.registers().items():
            self.assertTrue(entry["purpose"], key)

    def test_each_register_counts_its_records(self):
        self.assertEqual(self.registers()["instruments"]["count"], 0)
        self.add_instrument("HPLC-01")
        self.add_instrument("HPLC-02")
        self.assertEqual(self.registers()["instruments"]["count"], 2)

    def test_a_count_holds_only_what_the_person_can_see(self):
        sample = self.register_sample()
        self.ok(self.post(f"/api/lab/samples/{sample.id}/custody/", {
            "action": "RETAINED", "location": "Retain room", "retain_until": self.day(30),
        }, self.frontdesk))
        stranger = User.objects.create_user(username="analyst2", password=PW, role=self.roles["ANALYST"])
        stranger.sections.set([self.section])
        self.assertEqual(self.registers()["retained"]["count"], 1)
        self.assertEqual(self.registers(stranger)["retained"]["count"], 0)
