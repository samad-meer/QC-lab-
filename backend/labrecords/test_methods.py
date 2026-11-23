"""The method master, what it means for a specification, and analyst qualification."""
from datetime import timedelta

from django.utils import timezone

from audit.models import AuditEvent
from certificates.tests import PW
from lims.models import SpecStatus, Specification, TestDefinition
from qclab.testing import force_update
from standards.api import _digest as spec_digest
from .models import Method, Qualification
from .test_base import LabTestBase


class MethodTests(LabTestBase):
    def test_a_draft_is_made_effective_by_someone_else_with_their_password(self):
        pk = self.draft_method(user=self.approver)["id"]
        self.refused(self.approve_method(pk, self.approver), "someone else")
        self.assertTrue(AuditEvent.objects.filter(action="METHOD_APPROVAL_REFUSED").exists())
        self.assertEqual(Method.objects.get(pk=pk).status, "DRAFT")

        pk = self.draft_method("KF-01")["id"]
        self.refused(self.approve_method(pk, password="wrong"), "Password")
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED", entity="method").exists())
        data = self.ok(self.approve_method(pk))
        self.assertEqual(data["status"]["text"], "Effective")
        method = Method.objects.get(pk=pk)
        self.assertEqual((method.approved_by, method.status), (self.approver, "EFFECTIVE"))
        self.assertTrue(method.approved_digest)

    def test_whoever_changed_a_draft_cannot_approve_it(self):
        pk = self.draft_method()["id"]
        self.ok(self.post(f"/api/lab/methods/{pk}/edit/", {"title": "Better title"}, self.approver))
        self.refused(self.approve_method(pk, self.approver), "someone else")

    def test_the_administrator_override_passes_it_and_is_flagged(self):
        pk = self.draft_method(user=self.admin)["id"]
        self.ok(self.approve_method(pk, self.admin))
        self.assertIn("override", AuditEvent.objects.get(action="METHOD_APPROVED").details)

    def test_approving_needs_the_permission(self):
        pk = self.draft_method()["id"]
        self.refused(self.approve_method(pk, self.analyst), "permission")

    def test_an_approval_is_tied_to_what_was_read(self):
        pk = self.draft_method()["id"]
        r = self.post(f"/api/lab/methods/{pk}/approve/", {"password": PW, "digest": "stale"})
        self.refused(r, "changed since you opened it")

    def test_a_new_version_supersedes_the_old_only_when_it_takes_effect(self):
        first = self.effective_method()
        second = self.ok(self.post(f"/api/lab/methods/{first.pk}/new-version/", {"comment": "New column"}, self.checker))
        self.assertEqual((second["id"] != first.pk, second["status"]["text"]), (True, "Draft"))
        first.refresh_from_db()
        self.assertEqual(first.status, "EFFECTIVE")
        self.ok(self.approve_method(second["id"]))
        first.refresh_from_db()
        self.assertEqual(first.status, "RETIRED")
        self.assertEqual(Method.objects.get(pk=second["id"]).version, 2)

    def test_only_one_draft_at_a_time_and_a_code_is_not_reused(self):
        first = self.effective_method()
        self.ok(self.post(f"/api/lab/methods/{first.pk}/new-version/", {"comment": "x"}, self.checker))
        self.refused(self.post(f"/api/lab/methods/{first.pk}/new-version/", {"comment": "x"}, self.checker), "already a draft")
        r = self.post("/api/lab/methods/", {
            "code": "hplc-04", "title": "x", "document_ref": "y", "validation_status": "VALIDATED",
        }, self.checker)
        self.refused(r, "already exists")

    def test_an_effective_method_is_never_edited(self):
        method = self.effective_method()
        self.refused(self.post(f"/api/lab/methods/{method.pk}/edit/", {"title": "x"}, self.checker), "not a draft")
        method.title = "Rewritten"
        with self.assertRaises(PermissionError):
            method.save()
        with self.assertRaises(PermissionError):
            method.delete()

    def test_retiring_a_method_in_use_takes_an_approver_and_a_reason(self):
        method = self.effective_method()
        self.refused(self.post(f"/api/lab/methods/{method.pk}/retire/", {"comment": "x"}, self.checker), "permission")
        self.refused(self.post(f"/api/lab/methods/{method.pk}/retire/", {}), "Say why")
        self.ok(self.post(f"/api/lab/methods/{method.pk}/retire/", {"comment": "Superseded by compendial"}))
        method.refresh_from_db()
        self.assertEqual(method.status, "RETIRED")
        with self.assertRaises(PermissionError):
            method.save()

    def test_an_abandoned_draft_is_retired_by_whoever_drafts(self):
        pk = self.draft_method()["id"]
        self.ok(self.post(f"/api/lab/methods/{pk}/retire/", {"comment": "No longer needed"}, self.checker))
        self.assertEqual(Method.objects.get(pk=pk).status, "RETIRED")


class SpecificationMethodTests(LabTestBase):
    def setUp(self):
        super().setUp()
        self.draft = Specification.objects.create(
            product=self.product, version=2, status=SpecStatus.DRAFT, effective_date=timezone.localdate(),
            created_by=self.checker,
        )

    def row(self, **extra):
        return {
            "name": "Assay", "limit_type": "NUMERIC_RANGE", "min_value": "95.0", "max_value": "105.0", "decimals": 1,
            "unit": "%", **extra,
        }

    def save(self, *rows):
        self.login(self.checker)
        return self.client.put(f"/api/specifications/{self.draft.id}/", {"tests": list(rows)}, format="json")

    def approve(self):
        self.login(self.approver)
        return self.client.post(f"/api/specifications/{self.draft.id}/approve/", {
            "password": PW, "digest": spec_digest(self.draft),
        }, format="json")

    def test_a_test_names_a_method_record_and_the_payload_says_so(self):
        method = self.effective_method()
        r = self.save(self.row(method_record_id=method.pk))
        self.assertEqual(r.status_code, 200, r.content)
        test = TestDefinition.objects.get(specification=self.draft)
        self.assertEqual(test.method_record, method)
        self.assertEqual(test.method, "HPLC-04 v1")  # what the certificate prints
        row = next(s for s in r.data["specifications"] if s["id"] == self.draft.id)["tests"][0]
        self.assertEqual((row["method_record_id"], row["method_record_label"]), (method.pk, "HPLC-04 v1"))

    def test_an_unknown_method_is_refused(self):
        r = self.save(self.row(method_record_id=99999))
        self.refused(r, "not in the method master")
        self.refused(self.save(self.row(method_record_id="abc")), "not in the method master")

    def test_a_template_does_not_carry_a_method_record(self):
        self.login(self.checker)
        r = self.client.post("/api/test-templates/", {"code": "ASSAY", **self.row(method_record_id=1)}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(r.data["method_record_id"])

    def test_a_new_draft_carries_the_method_forward(self):
        method = self.effective_method()
        self.save(self.row(method_record_id=method.pk))
        self.assertEqual(self.approve().status_code, 200)
        self.login(self.checker)
        r = self.client.post(f"/api/products/{self.product.id}/specifications/", {"reason": "Next"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        newest = self.product.specifications.order_by("-version").first()
        self.assertEqual(newest.tests.get().method_record, method)

    def test_it_cannot_be_approved_on_a_method_that_is_not_effective(self):
        pk = self.draft_method()["id"]
        self.save(self.row(method_record_id=pk))
        self.refused(self.approve(), "which is draft")
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, "DRAFT")
        self.assertTrue(AuditEvent.objects.filter(action="SPEC_APPROVAL_REFUSED_METHOD").exists())

    def test_it_cannot_be_approved_on_a_retired_method(self):
        method = self.effective_method()
        self.save(self.row(method_record_id=method.pk))
        self.ok(self.post(f"/api/lab/methods/{method.pk}/retire/", {"comment": "Withdrawn"}))
        self.refused(self.approve(), "which is retired")

    def test_it_cannot_be_approved_on_a_method_that_is_not_validated(self):
        method = self.effective_method(validation="NOT_VALIDATED")
        self.save(self.row(method_record_id=method.pk))
        self.refused(self.approve(), "not validated")

    def test_a_test_with_no_method_record_is_not_held_up(self):
        self.save(self.row(method="USP <711>"))
        self.assertEqual(self.approve().status_code, 200)

    def test_compendial_and_verified_methods_pass(self):
        for code, status in (("USP-1", "COMPENDIAL"), ("V-1", "VERIFIED")):
            method = self.effective_method(code, status)
            self.save(self.row(method_record_id=method.pk))
            r = self.approve()
            self.assertEqual(r.status_code, 200, r.content)
            self.draft = Specification.objects.create(
                product=self.product, version=self.draft.version + 1, status=SpecStatus.DRAFT,
                effective_date=timezone.localdate(), created_by=self.checker,
            )


class QualificationTests(LabTestBase):
    def setUp(self):
        super().setUp()
        self.method = self.effective_method()
        force_update(TestDefinition.objects.filter(pk=self.t_assay.pk), method_record=self.method)
        self.t_assay.refresh_from_db()
        self.sample = self.register_sample()

    def test_a_result_is_refused_without_a_qualification(self):
        r = self.enter(self.sample, value_numeric="99.0")
        self.refused(r, "not qualified on method HPLC-04")
        self.assertEqual(self.sample.results.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action="RESULT_REFUSED_UNQUALIFIED").exists())

    def test_a_test_with_no_method_record_needs_none(self):
        self.ok(self.enter(self.sample, self.t_desc, value_text="Complies"), 201)

    def test_a_current_qualification_lets_the_result_in(self):
        self.ok(self.qualify(self.analyst), 201)
        self.ok(self.enter(self.sample, value_numeric="99.0"), 201)

    def test_it_survives_a_new_version_of_the_method(self):
        self.ok(self.qualify(self.analyst), 201)
        draft = self.ok(self.post(f"/api/lab/methods/{self.method.pk}/new-version/", {"comment": "x"}, self.checker))
        self.ok(self.approve_method(draft["id"]))
        self.ok(self.enter(self.sample, value_numeric="99.0"), 201)

    def test_it_is_good_on_its_last_day_and_says_when_it_expired(self):
        self.ok(self.qualify(self.analyst, expires=0), 201)
        self.ok(self.enter(self.sample, value_numeric="99.0"), 201)
        yesterday = timezone.localdate() - timedelta(days=1)
        force_update(Qualification.objects.all(), expires_on=yesterday)
        r = self.enter(self.sample, value_numeric="99.0", supersede_reason="Typing mistake")
        self.refused(r, f"expired on {yesterday:%d-%b-%Y}")

    def test_a_revoked_one_is_refused_with_the_reason(self):
        pk = self.ok(self.qualify(self.analyst), 201)["id"]
        self.refused(self.post(f"/api/lab/qualifications/{pk}/revoke/", {"password": PW}), "Say why")
        r = self.post(f"/api/lab/qualifications/{pk}/revoke/", {"comment": "Failed the proficiency test", "password": "x"})
        self.refused(r, "Password")
        self.ok(self.post(f"/api/lab/qualifications/{pk}/revoke/", {"comment": "Failed the proficiency test", "password": PW}))
        self.refused(self.enter(self.sample, value_numeric="99.0"), "Failed the proficiency test")
        self.refused(self.post(f"/api/lab/qualifications/{pk}/revoke/", {"comment": "x", "password": PW}), "already")

    def test_revoking_the_latest_is_not_undone_by_an_earlier_grant_still_running(self):
        self.ok(self.qualify(self.analyst, expires=100), 201)
        pk = self.ok(self.qualify(self.analyst, expires=200), 201)["id"]
        self.ok(self.post(f"/api/lab/qualifications/{pk}/revoke/", {"comment": "Unsafe practice", "password": PW}))
        self.refused(self.enter(self.sample, value_numeric="99.0"), "Unsafe practice")
        self.ok(self.qualify(self.analyst), 201)
        self.ok(self.enter(self.sample, value_numeric="99.0"), 201)

    def test_a_renewal_after_a_lapse_lets_them_back_in(self):
        self.ok(self.qualify(self.analyst), 201)
        force_update(Qualification.objects.all(), expires_on=timezone.localdate() - timedelta(days=1))
        self.ok(self.qualify(self.analyst), 201)
        self.ok(self.enter(self.sample, value_numeric="99.0"), 201)

    def test_nobody_qualifies_themselves(self):
        self.refused(self.qualify(self.approver, by=self.approver), "cannot qualify yourself")
        self.assertTrue(AuditEvent.objects.filter(action="QUALIFICATION_REFUSED").exists())
        self.assertFalse(Qualification.objects.exists())

    def test_the_override_passes_who_may_qualify_and_who_may_enter_and_flags_both(self):
        self.ok(self.qualify(self.admin, by=self.admin), 201)
        self.assertIn("override", AuditEvent.objects.get(action="QUALIFICATION_GRANTED").details)
        sample = self.register_sample()
        self.ok(self.enter(sample, user=self.admin, value_numeric="99.0"), 201)

    def test_the_override_is_flagged_when_it_enters_without_one(self):
        self.ok(self.enter(self.sample, user=self.admin, value_numeric="99.0"), 201)
        self.assertIn("override", AuditEvent.objects.get(action="RESULT_ENTERED").details)

    def test_granting_is_signed_and_needs_the_permission(self):
        self.refused(self.qualify(self.analyst, by=self.checker), "permission")
        self.refused(self.qualify(self.analyst, password="wrong"), "Password")
        self.assertTrue(AuditEvent.objects.filter(action="SIGN_PASSWORD_FAILED", entity="qualification").exists())
        self.assertFalse(Qualification.objects.exists())

    def test_the_method_must_exist_and_the_dates_make_sense(self):
        self.refused(self.qualify(self.analyst, code="NOPE"), "no draft or effective method")
        self.refused(self.qualify(self.analyst, expires=-1), "expiry date")
        r = self.post("/api/lab/qualifications/", {
            "user_id": self.analyst.id, "method": "HPLC-04", "qualified_on": self.day(1), "expires_on": self.day(9),
            "password": PW,
        })
        self.refused(r, "future")

    def test_the_code_is_stored_as_the_method_has_it(self):
        pk = self.ok(self.qualify(self.analyst, code="hplc-04"), 201)["id"]
        self.assertEqual(Qualification.objects.get(pk=pk).method, "HPLC-04")

    def test_a_qualification_is_never_rewritten(self):
        pk = self.ok(self.qualify(self.analyst), 201)["id"]
        q = Qualification.objects.get(pk=pk)
        q.expires_on = timezone.localdate() + timedelta(days=3000)
        with self.assertRaises(PermissionError):
            q.save()
        with self.assertRaises(PermissionError):
            q.delete()

    def test_the_register_shows_who_is_current(self):
        pk = self.ok(self.qualify(self.analyst), 201)["id"]
        rows = self.ok(self.get("/api/lab/qualifications/?state=current"))["results"]
        self.assertEqual([r["id"] for r in rows], [pk])
        self.assertEqual(rows[0]["cells"]["state"]["text"], "Current")
        self.assertEqual(self.ok(self.get("/api/lab/qualifications/?state=revoked"))["results"], [])
