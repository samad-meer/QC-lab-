"""The Received from list: kept by an administrator, chosen at the front desk."""
import importlib

from django.apps import apps
from django.utils import timezone

from audit.models import AuditEvent
from certificates.tests import WorkflowTestBase, due
from lims.models import Sample, SampleSource
from qclab.testing import force_update

MASTER = "/api/sample-source-master/"


class SourceListTests(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.login(self.admin)

    def add(self, name):
        return self.client.post(MASTER, {"name": name}, format="json")

    def test_a_name_can_be_added_renamed_deactivated_and_reactivated_and_each_is_recorded(self):
        r = self.add("Ali Raza")
        self.assertEqual(r.status_code, 201, r.content)
        url = f"{MASTER}{r.data['id']}/"
        self.assertEqual(self.client.patch(url, {"name": "Ali Raza (Store)"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"is_active": False}, format="json").data["is_active"], False)
        self.assertEqual(self.client.patch(url, {"is_active": True}, format="json").data["is_active"], True)
        self.assertEqual(
            sorted(AuditEvent.objects.filter(action__startswith="SAMPLE_SOURCE_").values_list("action", flat=True)),
            ["SAMPLE_SOURCE_ADDED", "SAMPLE_SOURCE_DEACTIVATED", "SAMPLE_SOURCE_REACTIVATED", "SAMPLE_SOURCE_RENAMED"],
        )

    def test_one_source_is_never_spelled_two_ways(self):
        self.assertEqual(self.add("  Ali   Raza ").data["name"], "Ali Raza")
        for twin in ("ali raza", "ALI RAZA", "Ali  Raza"):
            r = self.add(twin)
            self.assertEqual(r.status_code, 400, twin)
            self.assertIn("already on the list", r.data["detail"])

    def test_a_rename_may_fix_the_case_but_not_take_another_name(self):
        pk = self.add("ali raza").data["id"]
        r = self.client.patch(f"{MASTER}{pk}/", {"name": "Ali Raza"}, format="json")
        self.assertEqual(r.data["name"], "Ali Raza")
        r = self.client.patch(f"{MASTER}{pk}/", {"name": "production"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_an_inactive_twin_is_pointed_out(self):
        pk = self.add("Ali Raza").data["id"]
        self.client.patch(f"{MASTER}{pk}/", {"is_active": False}, format="json")
        self.assertIn("reactivate", self.add("ali raza").data["detail"])

    def test_the_front_desk_is_offered_only_active_names_in_order(self):
        self.add("store")
        pk = self.add("Ali Raza").data["id"]
        self.client.patch(f"{MASTER}{pk}/", {"is_active": False}, format="json")
        self.login(self.frontdesk)
        names = [s["name"] for s in self.client.get("/api/sample-sources/").data]
        self.assertEqual(names, ["Production", "store", "Utilities"])

    def test_managing_the_list_needs_the_permission(self):
        self.login(self.frontdesk)
        self.assertEqual(self.client.get(MASTER).status_code, 403)
        self.assertEqual(self.add("Anyone").status_code, 403)
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/sample-sources/").status_code, 403)

    def test_malformed_requests_are_refused(self):
        self.assertEqual(self.client.post(MASTER, [1, 2], format="json").status_code, 400)
        self.assertEqual(self.add({"x": 1}).status_code, 400)
        self.assertEqual(self.add(" ").status_code, 400)
        self.assertEqual(self.add("x" * 201).status_code, 400)
        pk = SampleSource.objects.get(name="Production").pk
        self.assertEqual(self.client.patch(f"{MASTER}{pk}/", {"is_active": "no"}, format="json").status_code, 400)
        self.assertTrue(SampleSource.objects.get(pk=pk).is_active)


class RegistrationTests(WorkflowTestBase):
    def register(self, received_from):
        self.login(self.frontdesk)
        return self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "B-77", "quantity": "60 tablets",
            "received_from": received_from, "received_at": timezone.now().isoformat(),
            "due_date": due(), "analyst_id": self.analyst.id,
        }, format="json")

    def test_a_listed_name_is_stored_as_the_list_spells_it(self):
        r = self.register("  PRODUCTION ")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Sample.objects.get(pk=r.data["id"]).received_from, "Production")

    def test_a_name_not_on_the_list_is_refused_on_its_field(self):
        r = self.register("ali")
        self.assertEqual(r.status_code, 400)
        self.assertIn("received_from", r.data)
        self.assertFalse(Sample.objects.exists())

    def test_an_inactive_name_is_refused(self):
        SampleSource.objects.filter(name="Production").update(is_active=False)
        self.assertEqual(self.register("Production").status_code, 400)

    def test_a_rename_never_rewrites_what_was_received(self):
        sample = Sample.objects.get(pk=self.register("Production").data["id"])
        source = SampleSource.objects.get(name="Production")
        self.login(self.admin)
        self.client.patch(f"{MASTER}{source.pk}/", {"name": "Production Floor 2"}, format="json")
        sample.refresh_from_db()
        self.assertEqual(sample.received_from, "Production")


class SeedTests(WorkflowTestBase):
    def test_the_list_starts_from_the_names_already_received_under(self):
        a = self.register_sample()
        b = self.register_sample()
        c = self.register_sample()
        self.register_sample()  # stays "Production", so that spelling is the one used most
        force_update(Sample.objects.filter(pk=a.pk), received_from="production")
        force_update(Sample.objects.filter(pk=b.pk), received_from=" Production  ")
        force_update(Sample.objects.filter(pk=c.pk), received_from="Store")
        SampleSource.objects.all().delete()
        migration = importlib.import_module("lims.migrations.0018_samplesource")
        migration.seed_from_samples(apps, None)
        self.assertEqual(sorted(SampleSource.objects.values_list("name", flat=True)), ["Production", "Store"])
