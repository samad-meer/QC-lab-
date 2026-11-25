"""
The background worker: what it does each round, and the one place it is allowed to run.

It must run where requests are served (the development server and waitress), and nowhere else:
a test run, a migration or a shell that started a thread would sweep and send mail behind the
caller's back.
"""
import os
import sys
from unittest import mock

from django.test import SimpleTestCase

from . import worker


def serving(argv, **env):
    """worker.serving() as a process started with `argv` and these environment variables would see it."""
    kept = {k: v for k, v in os.environ.items() if k not in ("RUN_MAIN", "QCLAB_SERVING", "QCLAB_BACKGROUND")}
    with mock.patch.dict(os.environ, {**kept, **env}, clear=True), mock.patch.object(sys, "argv", argv):
        return worker.serving()


class RoundTests(SimpleTestCase):
    def test_it_sweeps_then_sends_email(self):
        order = []
        with mock.patch.object(worker, "sweep_if_due", lambda: order.append("sweep")), \
                mock.patch.object(worker, "flush_email", lambda: order.append("email")):
            worker.run_round()
        self.assertEqual(order, ["sweep", "email"])

    def test_a_failing_sweep_neither_stops_the_email_nor_raises(self):
        sent = []

        def broken():
            raise RuntimeError("the table is not there yet")

        with mock.patch.object(worker, "sweep_if_due", broken), \
                mock.patch.object(worker, "flush_email", lambda: sent.append(1)), \
                self.assertLogs("notifications.worker", "ERROR"):
            worker.run_round()
        self.assertEqual(sent, [1])


class WhereItRunsTests(SimpleTestCase):
    def test_not_in_a_test_run_a_migration_or_a_shell(self):
        for argv in (["manage.py", "test"], ["manage.py", "migrate"], ["manage.py", "shell"],
                     ["manage.py", "seed_demo"]):
            self.assertFalse(serving(argv), argv)

    def test_the_development_server_runs_the_site_in_a_child_process(self):
        self.assertTrue(serving(["manage.py", "runserver", "8007"], RUN_MAIN="true"))

    def test_the_parent_that_only_watches_for_changes_does_not_start_it(self):
        self.assertFalse(serving(["manage.py", "runserver", "8007"]))

    def test_without_the_reloader_the_one_process_serves(self):
        self.assertTrue(serving(["manage.py", "runserver", "8007", "--noreload"]))

    def test_the_production_server_says_so(self):
        self.assertTrue(serving(["deploy/run.py", "serve"], QCLAB_SERVING="1"))

    def test_it_can_be_switched_off_for_a_lab_that_uses_a_scheduler(self):
        self.assertFalse(serving(["deploy/run.py", "serve"], QCLAB_SERVING="1", QCLAB_BACKGROUND="0"))
        self.assertFalse(serving(["manage.py", "runserver", "--noreload"], QCLAB_BACKGROUND="0"))


class StartTests(SimpleTestCase):
    def tearDown(self):
        worker.stop()
        if worker._thread is not None:
            worker._thread.join(timeout=5)
        worker._thread = None

    def test_a_test_run_has_not_started_it(self):
        self.assertIsNone(worker._thread)

    def test_it_starts_once_and_never_holds_the_process_open(self):
        with mock.patch.object(worker, "FIRST_DELAY", 60):  # parked: nothing runs during the test
            first, second = worker.start(), worker.start()
        self.assertIs(first, second)
        self.assertTrue(first.is_alive())
        self.assertTrue(first.daemon, "a daemon thread, so stopping the server is never held up by it")
