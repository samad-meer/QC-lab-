"""
Send due-soon and overdue alerts, then any email waiting. Safe to run as often
as you like: each person hears about each due date once, unless the rule
repeats. Schedule it hourly in production; without a schedule, the app does it
during the day.
"""
from django.core.management.base import BaseCommand

from accounts.lab_zone import activate_lab_zone
from notifications.alerts import send_due_alerts
from notifications.email import send_queued


class Command(BaseCommand):
    help = "Send due-soon and overdue alerts, and any email waiting."

    def handle(self, *args, **options):
        # "Due today" and "overdue" are counted from the lab's midnight, not the server's.
        activate_lab_zone()
        self.stdout.write(f"{send_due_alerts()} alert(s) sent, {send_queued()} email(s) sent.")
