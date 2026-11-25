"""
What the demo-data seeders share (seed_dashboard, seed_production).

They enter every record through the API, as the screens do, so each rule, password signature and
audit entry applies. The one thing they change is the clock. A lab that had been working for weeks has
records dated over those weeks, and a chart of one day's work is a single bar. So the seeders run their
steps in the order they would have happened, on a clock that moves forward from a few weeks ago to now.
Nothing is edited afterwards: each record was made when it is dated, and the audit trail reads in order.

The file starts with an underscore so Django does not list it as a command.
"""
import datetime as dt
import heapq
from unittest import mock

from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from .seed_demo import PASSWORD


def require_debug(name: str) -> None:
    if not settings.DEBUG:
        raise CommandError(f"{name} uses the demo accounts' published password and makes demo records, so it "
                           "never runs in production.")


def load_people(usernames) -> dict:
    """The demo accounts the seeders sign as. They must still have the published password."""
    people = {}
    for username in usernames:
        user = User.objects.filter(username=username, is_active=True).first()
        if user is None or not user.check_password(PASSWORD):
            raise CommandError(f"The demo account {username} is missing or its password was changed. "
                               "Run seed_demo first.")
        people[username] = user
    return people


class Api:
    """The app's own API, called as one of the demo accounts."""

    def __init__(self, people: dict):
        self.client = APIClient(SERVER_NAME="localhost", HTTP_HOST="localhost")
        self.people = people

    def __call__(self, method: str, url: str, who: str, body=None):
        self.client.force_authenticate(self.people[who])
        r = getattr(self.client, method)(url, body, format="json")
        if r.status_code >= 300:
            raise CommandError(f"{method.upper()} {url} as {who} was refused ({r.status_code}): "
                               f"{r.content.decode()[:700]}")
        return r.data


class _Clock:
    """Time as the seeder lives it: it only moves forward, a second at a time, and never passes the present."""

    def __init__(self, ceiling: dt.datetime):
        self.ceiling = ceiling
        self.now = None

    def to(self, moment: dt.datetime) -> None:
        self.now = moment if self.now is None else max(self.now, moment)

    def __call__(self) -> dt.datetime:
        self.now += dt.timedelta(seconds=1)
        if self.now > self.ceiling:
            raise CommandError("The simulated clock reached the present. A step was planned too close to now.")
        return self.now


class Timeline:
    """
    The seeding steps in the order they happened. A step may plan later ones once it knows what it made
    (a certificate with two review stages plans two signatures), so the plan grows as it runs.
    """

    def __init__(self):
        self.real_now = timezone.now()
        self.today = timezone.localdate()
        self._steps: list = []
        self._count = 0

    def at(self, days_ago: int, hhmm: str) -> dt.datetime:
        """A moment that many days ago, in the lab's time zone: at(21, "09:20")."""
        hour, minute = (int(p) for p in hhmm.split(":"))
        day = self.today - dt.timedelta(days=days_ago)
        return timezone.make_aware(dt.datetime(day.year, day.month, day.day, hour, minute))

    def add(self, when: dt.datetime, action) -> None:
        self._count += 1
        heapq.heappush(self._steps, (when, self._count, action))

    def run(self) -> None:
        clock = _Clock(ceiling=self.real_now - dt.timedelta(minutes=1))
        with mock.patch("django.utils.timezone.now", clock):
            while self._steps:
                when, _, action = heapq.heappop(self._steps)
                if when > clock.ceiling:
                    raise CommandError(f"A step was planned for {when:%d-%b %H:%M}, which is not in the past yet.")
                clock.to(when)
                action()

    @staticmethod
    def local(moment: dt.datetime) -> str:
        """A moment as a batch record writes it: 2026-11-04T09:20, in the lab's time zone."""
        return timezone.localtime(moment).strftime("%Y-%m-%dT%H:%M")


class DryRun(Exception):
    """Raised at the end of a dry run, so the transaction rolls back."""
