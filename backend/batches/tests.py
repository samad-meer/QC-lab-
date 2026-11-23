"""
Traceability, through the API: the product master, batches and their two
identifiers, samples with and without a batch, and batch documents.
"""
import importlib
import shutil
import tempfile

from django.apps import apps as global_apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from accounts.models import RolePermissionGrant, User
from audit.models import AuditEvent
from certificates.tests import PW, WorkflowTestBase
from lims.models import Product, Sample, SampleStatus
from .models import Batch, BatchCounter, BatchDocument, BatchNumberRule
from .numbering import next_internal_id

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class TraceTestBase(WorkflowTestBase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)
        super().tearDown()

    def post_sample(self, **extra):
        self.login(self.frontdesk)
        return self.client.post("/api/samples/", {
            "product_id": self.product.id, "batch_no": "B260015", "quantity": "60 tablets",
            "received_from": "Production", "received_at": "2026-01-10T09:00:00Z", "due_date": "2026-12-20",
            "analyst_id": self.analyst.id, **extra,
        }, format="json")

    def registered(self, **extra):
        r = self.post_sample(**extra)
        self.assertEqual(r.status_code, 201, r.content)
        return Sample.objects.get(pk=r.data["id"])

    def patch_batch(self, batch, user=None, **fields):
        self.login(user or self.frontdesk)
        return self.client.patch(f"/api/batches/{batch.id}/", fields, format="json")


class BatchRegistrationTests(TraceTestBase):
    def test_the_official_number_is_kept_exactly_and_an_internal_id_is_issued(self):
        sample = self.registered(batch_no="  B260015/a ")
        batch = sample.batch
        self.assertEqual(batch.official_batch_no, "B260015/a")
        self.assertEqual(batch.internal_id, "BATCH-000001")
        self.assertEqual(sample.batch_no, "B260015/a")
        self.assertEqual(batch.created_by_id, self.frontdesk.id)
        self.assertTrue(AuditEvent.objects.filter(action="BATCH_CREATED", entity_id=batch.internal_id).exists())

    def test_more_samples_of_a_batch_join_it(self):
        first = self.registered()
        second = self.registered(batch_no="b260015")
        self.assertEqual(first.batch_id, second.batch_id)
        self.assertEqual(Batch.objects.count(), 1)
        self.assertEqual(second.batch_no, "B260015")  # the batch's own spelling

    def test_the_same_number_on_another_product_is_another_batch(self):
        first = self.registered()
        other = Product.objects.create(code="OTHER", name="Other", section=self.section)
        batch = Batch.objects.create(internal_id="X-1", product=other, official_batch_no="B260015")
        self.assertNotEqual(first.batch_id, batch.id)

    def test_what_the_batch_records_stands(self):
        self.registered(expiry_date="2027-01-31")
        r = self.post_sample(expiry_date="2027-02-28")
        self.assertEqual(r.status_code, 400)
        self.assertIn("recorded with expiry date 2027-01-31", r.data["batch_no"][0])
        self.assertEqual(Sample.objects.count(), 1)

    def test_a_later_sample_can_fill_in_what_the_batch_lacks(self):
        first = self.registered()
        second = self.registered(manufacturing_date="2026-01-01", manufacturing_site="Lahore")
        batch = Batch.objects.get(pk=first.batch_id)
        self.assertEqual(str(batch.manufacturing_date), "2026-01-01")
        self.assertEqual(batch.manufacturing_site, "Lahore")
        self.assertEqual(str(second.manufacturing_date), "2026-01-01")

    def test_a_sample_starts_from_the_products_storage_condition(self):
        Product.objects.filter(pk=self.product.pk).update(storage_condition="Below 25 °C")
        self.assertEqual(self.registered().storage_condition, "Below 25 °C")
        self.assertEqual(self.registered(batch_no="B2", storage_condition="2–8 °C").storage_condition, "2–8 °C")

    def test_a_batch_sample_needs_its_number(self):
        r = self.post_sample(batch_no="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("batch or lot number", str(r.data["batch_no"]))


class NonBatchSampleTests(TraceTestBase):
    def test_a_sample_need_not_belong_to_a_batch(self):
        sample = self.registered(from_batch=False, batch_no="", reference="Purified water, point WP-3")
        self.assertIsNone(sample.batch)
        self.assertEqual(sample.batch_no, "")
        self.assertEqual(sample.batch_label, "Purified water, point WP-3")
        self.assertFalse(Batch.objects.exists())

    def test_it_must_say_what_it_is(self):
        r = self.post_sample(from_batch=False, batch_no="", reference=" ")
        self.assertEqual(r.status_code, 400)
        self.assertIn("what this sample is", str(r.data["reference"]))

    def test_it_runs_the_whole_journey_and_its_certificate_says_what_it_was(self):
        sample = self.registered(from_batch=False, batch_no="", reference="Swab, line 2")
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(cert.content["batch_no"], "")
        self.assertEqual(cert.content["reference"], "Swab, line 2")
        self.assertEqual(cert.content["internal_batch_id"], "")

    def test_the_certificate_of_a_batch_sample_carries_the_trace(self):
        Product.objects.filter(pk=self.product.pk).update(dosage_form="Tablet", strength="500 mg")
        sample = self.registered(manufacturing_site="Lahore")
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(cert.content["internal_batch_id"], sample.batch.internal_id)
        self.assertEqual(cert.content["manufacturing_site"], "Lahore")
        self.assertEqual(cert.content["dosage_form"], "Tablet")
        self.assertEqual(cert.content["strength"], "500 mg")


class NumberRuleTests(TraceTestBase):
    def rule(self, **fields):
        self.login(self.admin)
        return self.client.put("/api/batch-numbering/", fields, format="json")

    def test_the_rule_builds_the_id_and_never_touches_the_official_number(self):
        r = self.rule(prefix="QC", separator="/", digits=4, include_year=True, include_product=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["example"], "QC/2026/PCM-500/0123")
        sample = self.registered()
        self.assertTrue(sample.batch.internal_id.startswith("QC/"))
        self.assertTrue(sample.batch.internal_id.endswith(f"/{self.product.code}/0001"))
        self.assertEqual(sample.batch.official_batch_no, "B260015")
        self.assertTrue(AuditEvent.objects.filter(action="BATCH_RULE_CHANGED").exists())

    def test_bad_rules_are_refused(self):
        for bad, message in [
            ({"prefix": ""}, "1 to 12 letters"),
            ({"prefix": "A B"}, "1 to 12 letters"),
            ({"prefix": "A", "separator": "x"}, "separator"),
            ({"prefix": "A", "digits": 1}, "between 3 and 10"),
        ]:
            r = self.rule(**bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn(message, r.data["detail"])

    def test_a_number_is_never_issued_twice_even_after_the_rule_changes(self):
        first = next_internal_id(self.product)
        Batch.objects.create(internal_id=first, product=self.product, official_batch_no="A")
        rule = BatchNumberRule.get()
        rule.digits = 3
        rule.save()
        Batch.objects.create(internal_id="BATCH-002", product=self.product, official_batch_no="B")
        self.assertEqual(next_internal_id(self.product), "BATCH-003")  # 002 was already taken

    def test_only_config_managers_change_it(self):
        self.login(self.frontdesk)
        self.assertEqual(self.client.get("/api/batch-numbering/").status_code, 403)


class BatchCorrectionTests(TraceTestBase):
    def test_a_correction_needs_a_reason_and_keeps_what_it_replaced(self):
        batch = self.registered().batch
        self.assertEqual(self.patch_batch(batch, manufacturing_site="Lahore").status_code, 400)
        r = self.patch_batch(batch, manufacturing_site="Lahore", reason="Site was left off")
        self.assertEqual(r.status_code, 200, r.content)
        event = AuditEvent.objects.get(action="BATCH_UPDATED")
        self.assertEqual(event.details["before"], {"manufacturing_site": "—"})
        self.assertEqual(event.details["after"], {"manufacturing_site": "Lahore"})
        self.assertEqual(r.data["history"][0]["sentence"].count("Site was left off"), 1)

    def test_the_official_number_is_fixed_once_a_certificate_exists(self):
        sample = self.registered()
        r = self.patch_batch(sample.batch, official_batch_no="B999", reason="Typo")
        self.assertEqual(r.status_code, 200, r.content)
        sample.refresh_from_db()
        self.assertEqual(sample.batch_no, "B999")  # open work follows the correction

        self.enter_results(sample)
        self.sign_analyst(sample)
        r = self.patch_batch(sample.batch, official_batch_no="B111", reason="Typo")
        self.assertEqual(r.status_code, 400)
        self.assertIn("certificate has been signed", r.data["detail"])

    def test_a_correction_cannot_land_on_another_batch(self):
        first = self.registered().batch
        self.registered(batch_no="B2")
        r = self.patch_batch(first, official_batch_no="b2", reason="Typo")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already has batch", r.data["detail"])

    def test_an_expiry_before_manufacture_is_refused(self):
        batch = self.registered(manufacturing_date="2026-06-01").batch
        r = self.patch_batch(batch, expiry_date="2026-01-01", reason="Dates")
        self.assertEqual(r.status_code, 400)
        self.assertIn("before the date of manufacture", r.data["detail"])

    def test_a_released_sample_keeps_what_it_was_released_with(self):
        sample = self.registered(expiry_date="2027-01-31")
        Sample.objects.filter(pk=sample.pk).update(status=SampleStatus.APPROVED)
        self.patch_batch(sample.batch, expiry_date="2027-03-31", reason="Corrected")
        sample.refresh_from_db()
        self.assertEqual(str(sample.expiry_date), "2027-01-31")

    def test_batches_are_never_deleted(self):
        with self.assertRaises(PermissionError):
            self.registered().batch.delete()

    def test_correcting_or_creating_needs_the_permission(self):
        batch = self.registered().batch
        self.assertEqual(self.patch_batch(batch, self.analyst, notes="x", reason="y").status_code, 403)
        self.login(self.analyst)
        r = self.client.post("/api/batches/", {"product_id": self.product.id, "official_batch_no": "N"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_a_batch_can_be_recorded_before_any_sample_arrives(self):
        self.login(self.frontdesk)
        r = self.client.post("/api/batches/", {
            "product_id": self.product.id, "official_batch_no": "B777", "manufacturing_site": "Lahore",
            "batch_size": "100,000 tablets",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["sample_count"], 0)
        self.assertEqual(self.registered(batch_no="B777").batch.manufacturing_site, "Lahore")
        again = self.client.post("/api/batches/", {"product_id": self.product.id, "official_batch_no": "b777"},
                                 format="json")
        self.assertEqual(again.status_code, 400)


class BatchViewTests(TraceTestBase):
    def test_one_batch_shows_its_samples_results_and_certificates(self):
        sample = self.registered()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.login(self.checker)
        r = self.client.get(f"/api/batches/{sample.batch_id}/")
        self.assertEqual([s["id"] for s in r.data["samples"]], [sample.id])
        self.assertEqual(len(r.data["results"]), sample.current_results().count())
        self.assertEqual(r.data["certificates"][0]["id"], cert.id)
        self.assertEqual(r.data["certificates"][0]["overall"], "COMPLIES")

    def test_the_list_filters_and_searches(self):
        first = self.registered().batch
        self.registered(batch_no="ZZ9")
        self.login(self.frontdesk)
        rows = self.client.get("/api/batches/?q=zz9").data["results"]
        self.assertEqual([b["official_batch_no"] for b in rows], ["ZZ9"])
        data = self.client.get(f"/api/batches/?q={first.internal_id}").data
        self.assertEqual((data["count"], data["results"][0]["sample_count"]), (1, 1))
        self.assertEqual(self.client.get("/api/batches/?from=2000-01-01&to=2000-01-02").data["count"], 0)

    def test_people_see_only_the_batches_behind_samples_they_can_see(self):
        batch = self.registered().batch
        other = User.objects.create_user(username="analyst2", password=PW, role=self.roles["ANALYST"])
        other.sections.set([self.section])
        self.login(other)
        self.assertEqual(self.client.get("/api/batches/").data["count"], 0)
        self.assertEqual(self.client.get(f"/api/batches/{batch.id}/").status_code, 404)
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/batches/").data["count"], 1)

    def test_the_front_desk_can_ask_if_a_number_is_known(self):
        self.registered()
        self.login(self.frontdesk)
        url = f"/api/batches/lookup/?product={self.product.id}&official_no="
        self.assertEqual(self.client.get(url + "b260015").data["batch"]["sample_count"], 1)
        self.assertIsNone(self.client.get(url + "NEW").data["batch"])
        self.login(self.analyst)
        self.assertEqual(self.client.get(url + "NEW").status_code, 403)

    def test_a_sample_list_can_be_searched_by_batch(self):
        sample = self.registered()
        self.registered(batch_no="OTHER", from_batch=True)
        self.login(self.frontdesk)
        rows = self.client.get(f"/api/samples/?status=ALL&q={sample.batch.internal_id}").data["results"]
        self.assertEqual([s["id"] for s in rows], [sample.id])
        self.assertEqual(rows[0]["batch_id"], sample.batch_id)


class BatchDocumentTests(TraceTestBase):
    def upload(self, batch, content=PDF, name="record.pdf", **extra):
        self.login(self.frontdesk)
        return self.client.post(f"/api/batches/{batch.id}/documents/", {
            "file": SimpleUploadedFile(name, content), "doc_type": "BATCH_RECORD", "title": "Batch record", **extra,
        }, format="multipart")

    def test_a_new_version_replaces_and_the_old_one_stays(self):
        batch = self.registered().batch
        self.assertEqual(self.upload(batch).status_code, 200)
        first = BatchDocument.objects.get()
        r = self.upload(batch, replaces_id=first.id)
        self.assertEqual(r.status_code, 200, r.content)
        first.refresh_from_db()
        self.assertFalse(first.is_current)
        current = BatchDocument.objects.exclude(pk=first.pk).get()
        self.assertEqual((current.version, current.replaces_id), (2, first.id))
        self.assertEqual(len(r.data["documents"]), 2)

    def test_a_file_that_is_not_what_it_says_is_refused(self):
        batch = self.registered().batch
        r = self.upload(batch, content=b"<html>not a pdf</html>")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(BatchDocument.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action="ATTACHMENT_REFUSED", entity="batch").exists())

    def test_withdrawing_needs_a_reason_and_nothing_is_deleted(self):
        batch = self.registered().batch
        self.upload(batch)
        doc = BatchDocument.objects.get()
        self.login(self.frontdesk)
        self.assertEqual(self.client.post(f"/api/batch-documents/{doc.id}/withdraw/", {}, format="json").status_code, 400)
        r = self.client.post(f"/api/batch-documents/{doc.id}/withdraw/", {"reason": "Wrong batch"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        doc.refresh_from_db()
        self.assertFalse(doc.is_current)
        with self.assertRaises(PermissionError):
            doc.delete()
        doc.title = "edited"
        with self.assertRaises(PermissionError):
            doc.save()

    def test_a_document_is_served_only_to_people_who_can_see_the_batch(self):
        batch = self.registered().batch
        self.upload(batch)
        doc = BatchDocument.objects.get()
        self.login(self.frontdesk)
        r = self.client.get(f"/api/batch-documents/{doc.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        other = User.objects.create_user(username="analyst2", password=PW, role=self.roles["ANALYST"])
        self.login(other)
        self.assertEqual(self.client.get(f"/api/batch-documents/{doc.id}/").status_code, 404)

    def test_uploading_needs_the_permission(self):
        batch = self.registered().batch
        self.login(self.analyst)
        r = self.client.post(f"/api/batches/{batch.id}/documents/", {
            "file": SimpleUploadedFile("a.pdf", PDF), "doc_type": "OTHER"}, format="multipart")
        self.assertEqual(r.status_code, 403)


class ProductMasterTests(TraceTestBase):
    def create(self, user=None, **extra):
        self.login(user or self.admin)
        return self.client.post("/api/product-master/", {
            "code": "MED-001", "name": "Medicine", "section_id": self.section.id, "dosage_form": "Tablet",
            "strength": "500 mg", "sample_type": "FINISHED_PRODUCT", **extra,
        }, format="json")

    def test_a_product_is_added_with_its_details(self):
        r = self.create(shelf_life_months=24, storage_condition="Below 25 °C")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.data["dosage_form"], r.data["strength"]), ("Tablet", "500 mg"))
        self.assertEqual(r.data["sample_type_label"], "Finished product")
        self.assertTrue(AuditEvent.objects.filter(action="PRODUCT_CREATED", entity_id="MED-001").exists())

    def test_codes_are_unique_and_required_fields_are_checked(self):
        self.create()
        self.assertEqual(self.create(code="med-001").status_code, 400)
        self.assertEqual(self.create(code="NEW", name=" ").status_code, 400)
        self.assertEqual(self.create(code="NEW", section_id=0).status_code, 400)
        self.assertEqual(self.create(code="NEW", sample_type="POTION").status_code, 400)
        self.assertEqual(self.create(code="NEW", shelf_life_months=0).status_code, 400)

    def test_a_change_needs_a_reason_and_is_recorded(self):
        product = Product.objects.get(pk=self.create().data["id"])
        self.assertEqual(self.client.patch(f"/api/product-master/{product.id}/", {"strength": "250 mg"},
                                           format="json").status_code, 400)
        r = self.client.patch(f"/api/product-master/{product.id}/", {"strength": "250 mg", "reason": "New strength"},
                              format="json")
        self.assertEqual(r.data["strength"], "250 mg")
        event = AuditEvent.objects.get(action="PRODUCT_UPDATED")
        self.assertEqual(event.details["before"], {"strength": "500 mg"})

    def test_the_code_and_section_are_not_changed_here(self):
        product = Product.objects.get(pk=self.create().data["id"])
        self.client.patch(f"/api/product-master/{product.id}/", {"code": "X", "reason": "r"}, format="json")
        product.refresh_from_db()
        self.assertEqual(product.code, "MED-001")

    def test_an_inactive_product_stops_being_offered_and_cannot_be_registered(self):
        self.login(self.admin)
        self.client.patch(f"/api/product-master/{self.product.id}/", {"is_active": False, "reason": "Discontinued"},
                          format="json")
        self.login(self.frontdesk)
        self.assertEqual(self.client.get("/api/products/").data, [])
        r = self.post_sample()
        self.assertEqual(r.status_code, 400)
        self.assertIn("no longer active", r.data["detail"])

    def test_managing_needs_the_permission_but_anyone_can_read(self):
        self.assertEqual(self.create(self.analyst).status_code, 403)
        self.login(self.analyst)
        data = self.client.get("/api/product-master/?q=" + self.product.code).data
        self.assertEqual(data["count"], 1)
        self.assertFalse(data["can_manage"])


class BackfillTests(TraceTestBase):
    def test_existing_samples_become_batches_without_losing_anything(self):
        old = self.registered()
        twin = self.registered(batch_no="b260015")
        # As they stood before batches existed: numbers on samples, and nothing else.
        Sample.objects.update(batch=None)
        Sample.objects.filter(pk=old.pk).update(manufacturing_date="2026-01-01")
        Sample.objects.filter(pk=twin.pk).update(expiry_date="2027-01-01")
        Batch.objects.update(internal_id="OLD", official_batch_no="OLD")
        BatchCounter.objects.all().delete()

        importlib.import_module("batches.migrations.0002_backfill_and_lockdown").backfill(global_apps, None)

        old.refresh_from_db()
        twin.refresh_from_db()
        self.assertEqual(old.batch_id, twin.batch_id)
        self.assertEqual(old.batch.official_batch_no, "B260015")
        self.assertEqual(str(old.batch.manufacturing_date), "2026-01-01")
        self.assertEqual(str(old.batch.expiry_date), "2027-01-01")
        self.assertEqual(old.batch.internal_id, "BATCH-000001")
        self.assertEqual(BatchCounter.objects.get(scope="BATCH|||").last_no, 1)


class PermissionDefaultsTests(TraceTestBase):
    def test_the_shipped_roles_get_their_new_permissions(self):
        self.assertIn("batch.manage", self.roles["FRONT_DESK"].permissions())
        self.assertIn("spec.manage", self.roles["CHECKER"].permissions())
        self.assertIn("spec.approve", self.roles["APPROVER"].permissions())
        self.assertLessEqual(
            {"product.manage", "template.manage", "notification.manage"}, self.roles["ADMIN"].permissions()
        )
        self.assertFalse(RolePermissionGrant.objects.filter(role=self.roles["ANALYST"], permission="spec.approve").exists())
