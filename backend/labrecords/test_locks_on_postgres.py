"""Direct SQL, as someone with the application's database login would try it."""
from datetime import timedelta

from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from batches.models import BatchDisposition
from .models import CalibrationEvent, ChangeRecord, CustodyEvent, Instrument
from .test_base import LabTestBase


class DatabaseLockTests(LabTestBase):
    def refused(self, sql):
        if connection.vendor != "postgresql":
            self.skipTest("The locks are PostgreSQL triggers.")
        with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)

    def instrument(self):
        instrument = Instrument.objects.create(
            code="HPLC-1", name="HPLC", type="HPLC", location="Lab 1", created_by=self.checker,
        )
        event = CalibrationEvent.objects.create(
            instrument=instrument, kind="CALIBRATION", performed_at=timezone.now(), performed_by=self.checker,
            outcome="PASS", reference="CAL-1", next_due=timezone.localdate() + timedelta(days=30),
            recorded_by=self.checker,
        )
        return event

    def test_a_calibration_record_cannot_be_rewritten(self):
        event = self.instrument()
        self.refused(f"UPDATE labrecords_calibrationevent SET outcome = 'PASS', next_due = '2099-01-01' WHERE id = {event.id}")

    def test_a_calibration_record_cannot_be_deleted(self):
        self.refused(f"DELETE FROM labrecords_calibrationevent WHERE id = {self.instrument().id}")

    def test_custody_cannot_be_rewritten(self):
        sample = self.register_sample()
        event = CustodyEvent.objects.create(sample=sample, action="STORED", location="Cold room", by=self.analyst)
        self.refused(f"UPDATE labrecords_custodyevent SET location = 'Elsewhere' WHERE id = {event.id}")

    def test_a_batch_decision_cannot_be_rewritten(self):
        sample = self.register_sample()
        decision = BatchDisposition.objects.create(
            batch=sample.batch, decision="QUARANTINED", reason="Pending", decided_by=self.approver,
            basis_hash="x" * 64, basis={},
        )
        self.refused(f"UPDATE batches_batchdisposition SET decision = 'RELEASED' WHERE id = {decision.id}")
        self.refused(f"DELETE FROM batches_batchdisposition WHERE id = {decision.id}")

    def test_the_lab_record_tables_cannot_be_emptied(self):
        for table in ("labrecords_calibrationevent", "labrecords_custodyevent", "labrecords_changerecord",
                      "batches_batchdisposition"):
            self.refused(f"TRUNCATE {table} CASCADE")
        self.assertTrue(ChangeRecord.objects.count() >= 0)
