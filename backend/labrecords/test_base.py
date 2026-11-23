"""What the tests of the lab records have in common. Everything goes through the API."""
from datetime import timedelta

from django.utils import timezone

from certificates.tests import PW, WorkflowTestBase
from .models import Method
from .services import method_digest


class LabTestBase(WorkflowTestBase):
    def post(self, url, body=None, user=None):
        self.login(user or self.approver)
        return self.client.post(url, body or {}, format="json")

    def get(self, url, user=None):
        self.login(user or self.approver)
        return self.client.get(url)

    def ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.content)
        return response.data

    def refused(self, response, words: str):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(words, response.data["detail"])

    def day(self, days=0) -> str:
        return (timezone.localdate() + timedelta(days=days)).isoformat()

    def moment(self, days=0) -> str:
        return (timezone.localtime() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")

    def add_instrument(self, code="HPLC-01"):
        return self.ok(self.post("/api/lab/instruments/", {
            "code": code, "name": "Agilent 1260", "type": "HPLC", "location": "Lab 2", "serial_number": "SN-1",
        }), 201)["id"]

    def calibrate(self, pk, days=-1, due=30, outcome="PASS", kind="CALIBRATION", user=None):
        return self.post(f"/api/lab/instruments/{pk}/calibrate/", {
            "kind": kind, "outcome": outcome, "performed_at": self.moment(days), "reference": "CAL-2026-17",
            "next_due": self.day(due) if due is not None else "", "comment": "Within tolerance",
        }, user)

    def usable_instrument(self, code="HPLC-01"):
        pk = self.add_instrument(code)
        self.ok(self.calibrate(pk))
        return pk

    def add_material(self, lot="L-1", status="AVAILABLE", expiry=90, code="RS-PCM"):
        return self.ok(self.post("/api/lab/materials/", {
            "kind": "REFERENCE_STANDARD", "code": code, "name": "Paracetamol RS", "lot": lot, "supplier": "USP",
            "potency": "99.8", "received_on": self.day(-30), "expiry_date": self.day(expiry), "status": status,
        }), 201)["id"]

    def draft_method(self, code="HPLC-04", validation="VALIDATED", user=None):
        return self.ok(self.post("/api/lab/methods/", {
            "code": code, "title": "Assay by HPLC", "document_ref": "QC-M-004", "validation_status": validation,
        }, user or self.checker), 201)

    def approve_method(self, pk, user=None, password=PW):
        digest = method_digest(Method.objects.get(pk=pk))
        return self.post(f"/api/lab/methods/{pk}/approve/", {"password": password, "digest": digest}, user)

    def effective_method(self, code="HPLC-04", validation="VALIDATED"):
        pk = self.draft_method(code, validation)["id"]
        self.ok(self.approve_method(pk))
        return Method.objects.get(pk=pk)

    def qualify(self, person, code="HPLC-04", expires=365, by=None, password=PW):
        return self.post("/api/lab/qualifications/", {
            "user_id": person.id, "method": code, "qualified_on": self.day(-10), "expires_on": self.day(expires),
            "password": password,
        }, by)

    def enter(self, sample, test=None, user=None, **body):
        self.login(user or self.analyst)
        return self.client.post(f"/api/samples/{sample.id}/results/", {
            "test_definition_id": (test or self.t_assay).id, **body,
        }, format="json")
