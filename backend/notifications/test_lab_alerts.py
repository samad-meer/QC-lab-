"""
Telling people what they need to know without being asked: a certificate
released, calibrations and qualifications coming due, and email for all of it.
"""
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from audit.models import AuditEvent
from execution.tests import ExecutionTestBase
from labrecords.models import CalibrationEvent, CalibrationKind, CalibrationOutcome, Instrument, InstrumentStatus, Qualification
from .alerts import send_due_alerts
from .email import MAX_ATTEMPTS, send_queued
from .worker import run_round
from .models import EmailOutbox, Notification
from .rules import rule_for
from .services import notify


def told(kind):
    return set(Notification.objects.filter(kind=kind).values_list("recipient__username", flat=True))


class ReleaseTests(ExecutionTestBase):
    def release(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.assertEqual(self.sign(cert, self.checker).status_code, 200)
        self.assertEqual(self.sign(cert, self.approver).status_code, 200)
        return sample, cert

    def test_the_last_signature_tells_who_did_the_work_and_who_prints(self):
        sample, cert = self.release()
        people = told("CERT_RELEASED")
        self.assertLessEqual({"analyst", "frontdesk"}, people)
        self.assertNotIn("labhead", people)  # they signed it, so they know
        row = Notification.objects.filter(kind="CERT_RELEASED", recipient=self.analyst).get()
        self.assertEqual(row.link, f"/certificates/{cert.id}")
        self.assertIn(sample.sample_no, row.title)

    def test_an_earlier_signature_tells_nobody_it_is_released(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.sign(cert, self.checker)
        self.assertEqual(told("CERT_RELEASED"), set())

    def test_it_can_be_switched_off(self):
        rule = rule_for("CERT_RELEASED")
        rule.enabled = False
        rule.save()
        self.release()
        self.assertEqual(told("CERT_RELEASED"), set())


class DueDateBase(ExecutionTestBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.instrument = Instrument.objects.create(
            code="HPLC-1", name="HPLC", type="HPLC", location="Lab 2", created_by=self.approver,
        )

    def calibrate(self, next_due, performed_at=None):
        return CalibrationEvent.objects.create(
            instrument=self.instrument, kind=CalibrationKind.CALIBRATION, outcome=CalibrationOutcome.PASS,
            performed_at=performed_at or timezone.now(), performed_by=self.approver, reference="CAL-1",
            next_due=next_due, recorded_by=self.approver,
        )

    def qualify(self, expires_on, user=None, method="M-1"):
        return Qualification.objects.create(
            user=user or self.analyst, method=method, qualified_on=self.today - timedelta(days=300),
            expires_on=expires_on, qualified_by=self.approver,
        )


class CalibrationAlertTests(DueDateBase):
    def test_the_people_who_manage_instruments_hear_before_it_runs_out(self):
        self.calibrate(self.today + timedelta(days=5))
        send_due_alerts()
        self.assertIn("labhead", told("CALIBRATION_DUE"))
        row = Notification.objects.filter(kind="CALIBRATION_DUE", recipient=self.approver).get()
        self.assertIn("in 5 days", row.title)
        self.assertEqual(row.link, f"/lab/instruments/{self.instrument.pk}")

    def test_nothing_is_said_before_the_warning_period(self):
        self.calibrate(self.today + timedelta(days=rule_for("CALIBRATION_DUE").days_before + 1))
        send_due_alerts()
        self.assertEqual(told("CALIBRATION_DUE"), set())

    def test_each_person_hears_once(self):
        self.calibrate(self.today + timedelta(days=5))
        send_due_alerts()
        first = Notification.objects.filter(kind="CALIBRATION_DUE").count()
        send_due_alerts()
        self.assertEqual(Notification.objects.filter(kind="CALIBRATION_DUE").count(), first)

    def test_once_it_has_run_out_they_hear_again(self):
        self.calibrate(self.today + timedelta(days=2))
        send_due_alerts()
        send_due_alerts(today=self.today + timedelta(days=5))
        self.assertIn("labhead", told("CALIBRATION_OVERDUE"))

    def test_an_overdue_reminder_repeats_when_the_rule_says(self):
        rule = rule_for("CALIBRATION_DUE")
        rule.repeat_days = 7
        rule.save()
        self.calibrate(self.today - timedelta(days=1))
        send_due_alerts()
        count = Notification.objects.filter(kind="CALIBRATION_OVERDUE").count()
        send_due_alerts()
        self.assertEqual(Notification.objects.filter(kind="CALIBRATION_OVERDUE").count(), count)
        Notification.objects.filter(kind="CALIBRATION_OVERDUE").update(created_at=timezone.now() - timedelta(days=8))
        send_due_alerts()
        self.assertEqual(Notification.objects.filter(kind="CALIBRATION_OVERDUE").count(), count * 2)

    def test_a_new_calibration_warns_again_next_time_round(self):
        self.calibrate(self.today + timedelta(days=2))
        send_due_alerts()
        count = Notification.objects.filter(kind="CALIBRATION_DUE").count()
        Notification.objects.filter(kind="CALIBRATION_DUE").update(created_at=timezone.now() - timedelta(days=200))
        self.calibrate(self.today + timedelta(days=3), performed_at=timezone.now() + timedelta(minutes=1))
        send_due_alerts()
        self.assertEqual(Notification.objects.filter(kind="CALIBRATION_DUE").count(), count * 2)

    def test_a_retired_instrument_is_left_alone(self):
        self.calibrate(self.today + timedelta(days=2))
        Instrument.objects.filter(pk=self.instrument.pk).update(status=InstrumentStatus.RETIRED)
        send_due_alerts()
        self.assertEqual(told("CALIBRATION_DUE"), set())

    def test_it_can_be_switched_off(self):
        rule = rule_for("CALIBRATION_DUE")
        rule.enabled = False
        rule.save()
        self.calibrate(self.today + timedelta(days=2))
        send_due_alerts()
        self.assertEqual(told("CALIBRATION_DUE"), set())


class QualificationAlertTests(DueDateBase):
    def test_the_analyst_and_whoever_grants_them_hear(self):
        q = self.qualify(self.today + timedelta(days=10))
        send_due_alerts()
        self.assertLessEqual({"analyst", "labhead"}, told("QUALIFICATION_DUE"))
        row = Notification.objects.filter(kind="QUALIFICATION_DUE", recipient=self.analyst).get()
        self.assertEqual(row.link, f"/lab/qualifications/{q.pk}")

    def test_an_expired_qualification_says_so(self):
        self.qualify(self.today - timedelta(days=3))
        send_due_alerts()
        self.assertIn("analyst", told("QUALIFICATION_EXPIRED"))
        self.assertEqual(told("QUALIFICATION_DUE"), set())

    def test_a_renewal_stops_the_warning(self):
        self.qualify(self.today + timedelta(days=5))
        self.qualify(self.today + timedelta(days=300))
        send_due_alerts()
        self.assertEqual(told("QUALIFICATION_DUE"), set())

    def test_a_revoked_qualification_is_left_alone(self):
        q = self.qualify(self.today + timedelta(days=5))
        Qualification.objects.filter(pk=q.pk).update(revoked_at=timezone.now(), revoked_by=self.approver)
        send_due_alerts()
        self.assertEqual(told("QUALIFICATION_DUE"), set())

    def test_someone_who_has_left_is_left_alone(self):
        self.qualify(self.today + timedelta(days=5))
        type(self.analyst).objects.filter(pk=self.analyst.pk).update(is_active=False)
        send_due_alerts()
        self.assertEqual(told("QUALIFICATION_DUE"), set())


@override_settings(EMAIL_HOST="smtp.test", QCLAB_BASE_URL="https://lab.test")
class EmailTests(ExecutionTestBase):
    def setUp(self):
        super().setUp()
        type(self.analyst).objects.filter(pk=self.analyst.pk).update(email="analyst@lab.test")
        self.analyst.refresh_from_db()

    def alert(self):
        return notify(self.analyst, "CERT_RELEASED", "Released", body="Details", link="/certificates/1")

    def test_it_waits_in_the_queue_then_goes_out(self):
        self.alert()
        self.assertEqual(mail.outbox, [])
        self.assertEqual(send_queued(), 1)
        message = mail.outbox[0]
        self.assertEqual((message.to, message.subject), (["analyst@lab.test"], "Released"))
        self.assertIn("https://lab.test/certificates/1", message.body)
        self.assertIsNotNone(EmailOutbox.objects.get().sent_at)

    def test_it_goes_out_once(self):
        self.alert()
        send_queued()
        self.assertEqual(send_queued(), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_an_action_that_rolls_back_sends_nothing(self):
        try:
            with transaction.atomic():
                self.alert()
                raise ValueError("the action failed")
        except ValueError:
            pass
        self.assertEqual(send_queued(), 0)
        self.assertEqual(mail.outbox, [])

    def test_the_next_round_of_the_background_worker_sends_it(self):
        self.alert()
        run_round()
        self.assertEqual(len(mail.outbox), 1)

    def test_looking_at_the_bell_sends_nothing(self):
        """The mail server can take 8 seconds to answer. Nobody's page waits for it."""
        self.alert()
        self.login(self.frontdesk)
        self.assertEqual(self.client.get("/api/notifications/").status_code, 200)
        self.assertEqual(mail.outbox, [])
        self.assertIsNone(EmailOutbox.objects.get().sent_at)

    def test_nothing_is_queued_without_an_address(self):
        notify(self.frontdesk, "CERT_RELEASED", "Released")
        self.assertFalse(EmailOutbox.objects.exists())

    def test_a_rule_can_keep_to_the_bell(self):
        rule = rule_for("CERT_RELEASED")
        rule.email = False
        rule.save()
        self.alert()
        self.assertTrue(told("CERT_RELEASED"))
        self.assertFalse(EmailOutbox.objects.exists())

    @override_settings(EMAIL_HOST="")
    def test_without_a_mail_server_nothing_is_queued_and_the_bell_still_works(self):
        self.alert()
        self.assertTrue(told("CERT_RELEASED"))
        self.assertFalse(EmailOutbox.objects.exists())
        self.assertEqual(send_queued(), 0)

    def test_a_failure_waits_and_tries_again(self):
        self.alert()
        with patch("django.core.mail.EmailMessage.send", side_effect=OSError("no route to host")):
            self.assertEqual(send_queued(), 0)
        row = EmailOutbox.objects.get()
        self.assertEqual(row.attempts, 1)
        self.assertIn("no route", row.last_error)
        self.assertGreater(row.next_try, timezone.now())
        self.assertEqual(send_queued(), 0)  # not yet
        EmailOutbox.objects.update(next_try=timezone.now())
        self.assertEqual(send_queued(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_giving_up_is_recorded(self):
        self.alert()
        with patch("django.core.mail.EmailMessage.send", side_effect=OSError("refused")):
            for _ in range(MAX_ATTEMPTS):
                EmailOutbox.objects.update(next_try=timezone.now())
                send_queued()
        self.assertTrue(AuditEvent.objects.filter(action="EMAIL_FAILED").exists())
        EmailOutbox.objects.update(next_try=timezone.now())
        self.assertEqual(send_queued(), 0)

    def test_one_mail_failure_stops_the_batch_not_the_action(self):
        self.alert()
        self.alert()
        with patch("django.core.mail.EmailMessage.send", side_effect=OSError("down")) as send:
            send_queued()
        self.assertEqual(send.call_count, 1)

    def test_the_rules_screen_says_whether_email_is_ready_and_saves_the_choice(self):
        self.login(self.admin)
        r = self.client.get("/api/notification-rules/")
        self.assertTrue(r.data["email_ready"])
        rule = next(x for x in r.data["rules"] if x["event"] == "CERT_RELEASED")
        r = self.client.put("/api/notification-rules/CERT_RELEASED/", {**rule, "email": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(rule_for("CERT_RELEASED").email)

    def test_a_test_email_goes_to_the_person_asking_and_is_recorded(self):
        type(self.admin).objects.filter(pk=self.admin.pk).update(email="admin@lab.test")
        self.admin.refresh_from_db()
        self.login(self.admin)
        r = self.client.post("/api/notification-rules/test-email/", format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(mail.outbox[0].to, ["admin@lab.test"])
        self.assertTrue(AuditEvent.objects.filter(action="EMAIL_TEST_SENT").exists())

    def test_a_test_email_says_what_went_wrong(self):
        type(self.admin).objects.filter(pk=self.admin.pk).update(email="admin@lab.test")
        self.admin.refresh_from_db()
        self.login(self.admin)
        with patch("django.core.mail.EmailMessage.send", side_effect=OSError("connection refused")):
            r = self.client.post("/api/notification-rules/test-email/", format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("connection refused", r.data["detail"])

    def test_a_test_email_needs_an_address(self):
        self.login(self.admin)
        r = self.client.post("/api/notification-rules/test-email/", format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no email address", r.data["detail"])
