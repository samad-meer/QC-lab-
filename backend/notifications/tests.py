"""Who is told what, when work changes hands — and that nobody else can read it."""
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from audit.models import AuditEvent
from execution.models import TESTING, Assignment, AssignmentStatus
from execution.tests import ExecutionTestBase
from lims.models import Sample
from .alerts import SWEEP_EVERY, send_due_alerts, sweep_if_due
from .models import AlertSweep, Notification
from .rules import EVENTS, rule_for


class NotificationTests(ExecutionTestBase):
    def inbox(self, user):
        self.login(user)
        r = self.client.get("/api/notifications/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def test_the_analyst_is_told_when_a_sample_is_assigned_at_registration(self):
        sample = self.register_sample()
        n = Notification.objects.get(recipient=self.analyst)
        self.assertEqual(n.kind, "ASSIGNED")
        self.assertIn(sample.sample_no, n.title)
        self.assertEqual(n.link, f"/samples/{sample.id}")
        self.assertEqual(n.actor_id, self.frontdesk.id)
        # Nobody is notified of their own action.
        self.assertFalse(Notification.objects.filter(recipient=self.frontdesk).exists())

    def test_assignments_and_handovers_reach_the_assignee_and_answers_reach_the_sender(self):
        sample = self.register_sample()
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/assignments/",
                         {"mode": "handover", "step": TESTING, "user_id": self.analyst2.id,
                          "note": "HPLC run 3 still to inject"}, format="json")
        data = self.inbox(self.analyst2)
        self.assertEqual(data["unread"], 1)
        self.assertEqual(data["items"][0]["kind"], "HANDOVER")
        self.assertIn("HPLC run 3", data["items"][0]["body"])

        a = Assignment.objects.get(status=AssignmentStatus.PENDING)
        self.client.post(f"/api/assignments/{a.id}/respond/", {"action": "reject", "reason": "On leave tomorrow"},
                         format="json")
        reply = Notification.objects.filter(recipient=self.analyst, kind="HANDOVER_DECLINED").get()
        self.assertIn("On leave tomorrow", reply.body)

        # The lab head names a reviewer in advance; they are told when it reaches them.
        self.login(self.approver)
        self.client.post(f"/api/samples/{sample.id}/assignments/",
                         {"mode": "assign", "step": "CHECKED", "user_id": self.checker2.id}, format="json")
        self.assertTrue(Notification.objects.filter(recipient=self.checker2, kind="ASSIGNED").exists())
        self.assertEqual(self.inbox(self.checker2)["unread"], 1)
        self.enter_results(sample)
        self.sign_analyst(sample)
        turn = Notification.objects.get(recipient=self.checker2, kind="YOUR_TURN")
        self.assertEqual(turn.link, f"/samples/{sample.id}/review")

    def test_returns_retests_and_holds_notify_the_people_concerned(self):
        sample = self.register_sample()
        self.enter_results(sample, assay="90.0")
        self.login(self.analyst)
        self.client.post(f"/api/samples/{sample.id}/retests/",
                         {"test_definition_id": self.t_assay.id, "reason": "Dilution error"}, format="json")
        # The lab head may authorize; the checker may not, so is not told.
        self.assertTrue(Notification.objects.filter(recipient=self.approver, kind="RETEST_REQUESTED").exists())
        self.assertFalse(Notification.objects.filter(recipient=self.checker, kind="RETEST_REQUESTED").exists())

        self.login(self.checker)
        self.client.post(f"/api/samples/{sample.id}/hold/", {"reason": "Balance out of calibration"}, format="json")
        self.assertTrue(Notification.objects.filter(recipient=self.analyst, kind="ON_HOLD").exists())

    def test_a_return_tells_the_analyst_why(self):
        sample = self.register_sample()
        self.enter_results(sample)
        cert = self.sign_analyst(sample)
        self.send_back(cert, self.checker, "Attach the balance printout")
        n = Notification.objects.get(recipient=self.analyst, kind="RETURNED")
        self.assertIn("Attach the balance printout", n.body)

    def test_people_only_ever_read_and_mark_their_own(self):
        self.register_sample()
        n = Notification.objects.get(recipient=self.analyst)
        self.login(self.checker)
        self.assertEqual(self.client.post(f"/api/notifications/{n.id}/read/").status_code, 404)
        self.assertEqual(self.inbox(self.checker)["items"], [])

        self.login(self.analyst)
        r = self.client.post(f"/api/notifications/{n.id}/read/")
        self.assertEqual(r.data["unread"], 0)
        n.refresh_from_db()
        self.assertIsNotNone(n.read_at)
        n.title = "edited"
        with self.assertRaises(PermissionError):
            n.save()
        with self.assertRaises(PermissionError):
            n.delete()


class AlertTests(ExecutionTestBase):
    def due_in(self, sample, days):
        Sample.objects.filter(pk=sample.pk).update(due_date=timezone.localdate() + timedelta(days=days))

    def test_a_failing_result_reaches_those_who_can_decide_at_once(self):
        sample = self.register_sample()
        self.enter_results(sample, assay="90.0")
        alert = Notification.objects.get(recipient=self.approver, kind="RESULT_FAILED")
        self.assertIn(sample.sample_no, alert.title)
        self.assertIn("90.0", alert.body)
        self.assertFalse(Notification.objects.filter(recipient=self.analyst, kind="RESULT_FAILED").exists())

    def test_a_passing_result_tells_nobody(self):
        self.enter_results(self.register_sample())
        self.assertFalse(Notification.objects.filter(kind="RESULT_FAILED").exists())

    def test_a_review_with_nobody_named_reaches_everyone_who_could_take_it(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)
        told = set(Notification.objects.filter(kind="REVIEW_WAITING").values_list("recipient__username", flat=True))
        self.assertEqual(told, {self.checker.username, self.checker2.username})
        alert = Notification.objects.filter(kind="REVIEW_WAITING").first()
        self.assertEqual(alert.link, f"/samples/{sample.id}/review")

    def test_a_named_reviewer_hears_alone(self):
        sample = self.register_sample()
        self.login(self.approver)
        self.client.post(f"/api/samples/{sample.id}/assignments/",
                         {"mode": "assign", "step": "CHECKED", "user_id": self.checker2.id}, format="json")
        self.enter_results(sample)
        self.sign_analyst(sample)
        self.assertTrue(Notification.objects.filter(recipient=self.checker2, kind="YOUR_TURN").exists())
        self.assertFalse(Notification.objects.filter(kind="REVIEW_WAITING").exists())

    def test_overdue_and_due_soon_reach_whoever_the_sample_waits_for_once(self):
        late, soon, later = self.register_sample(), self.register_sample(), self.register_sample()
        self.due_in(late, -2)
        self.due_in(soon, 1)
        self.due_in(later, 30)
        self.assertEqual(send_due_alerts(), 2)
        overdue = Notification.objects.get(recipient=self.analyst, kind="OVERDUE")
        self.assertIn("2 days overdue", overdue.title)
        self.assertIn("due tomorrow", Notification.objects.get(recipient=self.analyst, kind="DUE_SOON").title)
        self.assertEqual(send_due_alerts(), 0)

    def test_an_overdue_reminder_repeats_only_if_the_rule_says_so(self):
        sample = self.register_sample()
        self.due_in(sample, -1)
        send_due_alerts()
        first = Notification.objects.get(kind="OVERDUE")
        Notification.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=4))
        self.assertEqual(send_due_alerts(), 0)
        rule = rule_for("OVERDUE")
        rule.repeat_days = 3
        rule.save()
        self.assertEqual(send_due_alerts(), 1)

    def test_a_released_sample_never_alerts(self):
        sample = self.register_sample()
        self.due_in(sample, -5)
        Sample.objects.filter(pk=sample.pk).update(status="APPROVED")
        self.assertEqual(send_due_alerts(), 0)

    def test_a_review_overdue_with_nobody_named_reaches_the_stage_role(self):
        sample = self.register_sample()
        self.enter_results(sample)
        self.sign_analyst(sample)
        self.due_in(sample, -1)
        send_due_alerts()
        told = set(Notification.objects.filter(kind="OVERDUE").values_list("recipient__username", flat=True))
        self.assertEqual(told, {self.checker.username, self.checker2.username})

    def test_the_sweep_runs_at_most_once_an_hour(self):
        sample = self.register_sample()
        self.due_in(sample, -1)
        sweep_if_due()  # the background worker's job: the bell only reads
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/notifications/").data["items"][0]["kind"], "OVERDUE")
        Notification.objects.filter(kind="OVERDUE").update(read_at=None)
        Sample.objects.filter(pk=sample.pk).update(due_date=timezone.localdate() - timedelta(days=1))
        second = self.register_sample()
        self.due_in(second, -1)
        sweep_if_due()
        self.assertEqual(Notification.objects.filter(kind="OVERDUE", sample=second).count(), 0)
        AlertSweep.objects.update(last_run=timezone.now() - SWEEP_EVERY - timedelta(minutes=1))
        sweep_if_due()
        self.assertEqual(Notification.objects.filter(kind="OVERDUE", sample=second).count(), 1)

    def test_opening_the_bell_does_no_background_work(self):
        """Every open page asks the bell every 30 seconds. The sweep walks every open sample, so it must
        not run inside that request: someone's page would wait for it."""
        self.due_in(self.register_sample(), -1)
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/notifications/").status_code, 200)
        self.assertFalse(Notification.objects.filter(kind="OVERDUE").exists())
        self.assertFalse(AlertSweep.objects.exists(), "the poll must not even take the sweep's turn")

    def test_the_command_does_the_same(self):
        self.due_in(self.register_sample(), -1)
        call_command("send_due_alerts", verbosity=0)
        self.assertTrue(Notification.objects.filter(kind="OVERDUE").exists())


class RuleTests(ExecutionTestBase):
    def put(self, event, **fields):
        self.login(self.admin)
        return self.client.put(f"/api/notification-rules/{event}/", fields, format="json")

    def test_a_rule_turned_off_stops_that_alert_and_nothing_else(self):
        self.assertEqual(self.put("FAILED_RESULT", enabled=False).status_code, 200)
        sample = self.register_sample()
        self.enter_results(sample, assay="90.0")
        self.assertFalse(Notification.objects.filter(kind="RESULT_FAILED").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.analyst, kind="ASSIGNED").exists())
        self.assertTrue(AuditEvent.objects.filter(action="NOTIFICATION_RULE_CHANGED").exists())

    def test_a_rule_can_add_a_role(self):
        self.put("FAILED_RESULT", role_ids=[self.roles["CHECKER"].id])
        self.enter_results(self.register_sample(), assay="90.0")
        self.assertTrue(Notification.objects.filter(recipient=self.checker, kind="RESULT_FAILED").exists())

    def test_the_warning_window_is_configurable(self):
        sample = self.register_sample()
        Sample.objects.filter(pk=sample.pk).update(due_date=timezone.localdate() + timedelta(days=3))
        self.assertEqual(send_due_alerts(), 0)
        self.put("DUE_SOON", days_before=3)
        self.assertEqual(send_due_alerts(), 1)

    def test_turning_overdue_off_stops_the_sweep_sending_it(self):
        sample = self.register_sample()
        Sample.objects.filter(pk=sample.pk).update(due_date=timezone.localdate() - timedelta(days=1))
        self.put("OVERDUE", enabled=False)
        self.assertEqual(send_due_alerts(), 0)

    def test_bad_values_and_unknown_events_are_refused(self):
        self.assertEqual(self.put("DUE_SOON", days_before=999).status_code, 400)
        self.assertEqual(self.put("DUE_SOON", days_before="soon").status_code, 400)
        self.assertEqual(self.put("NOPE", enabled=False).status_code, 404)

    def test_only_rule_managers_see_them(self):
        self.login(self.analyst)
        self.assertEqual(self.client.get("/api/notification-rules/").status_code, 403)
        self.login(self.admin)
        self.assertEqual(len(self.client.get("/api/notification-rules/").data["rules"]), len(EVENTS))

    def test_a_notification_outside_the_catalogue_is_always_sent(self):
        from .services import notify

        self.assertIsNotNone(notify(self.analyst, "INVESTIGATION", "Opened"))
