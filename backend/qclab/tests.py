"""
The one way lists work (qclab/listing.py), tested through the real endpoints:
date windows, which end of a range is included, refused input, and paging.
"""
from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.utils import timezone

from qclab.listing import period_window
from qclab.testing import force_update
from accounts.models import User
from audit.models import AuditEvent
from audit.services import record
from certificates.tests import PW, WorkflowTestBase
from lims.models import Sample


def lab_time(*args) -> datetime:
    return timezone.make_aware(datetime(*args))


class ListTestBase(WorkflowTestBase):
    def received_on(self, sample, moment):
        force_update(Sample.objects.filter(pk=sample.pk), received_at=moment)

    def listed(self, query="", user=None):
        self.login(user or self.frontdesk)
        r = self.client.get(f"/api/samples/?status=ALL&{query}")
        self.assertEqual(r.status_code, 200, r.content)
        return [s["id"] for s in r.data["results"]]

    def refused(self, query):
        self.login(self.frontdesk)
        r = self.client.get(f"/api/samples/?status=ALL&{query}")
        self.assertEqual(r.status_code, 400, r.content)
        return r.data["detail"]


class DateRangeTests(ListTestBase):
    def setUp(self):
        super().setUp()
        self.sample = self.register_sample()
        self.received_on(self.sample, lab_time(2026, 3, 10, 14, 5, 30))

    def test_a_custom_range_includes_the_whole_of_its_last_minute(self):
        self.assertEqual(self.listed("from=2026-03-10T14:05&to=2026-03-10T14:05"), [self.sample.id])
        self.assertEqual(self.listed("from=2026-03-10T14:06"), [])
        self.assertEqual(self.listed("to=2026-03-10T14:04"), [])

    def test_a_date_alone_covers_the_whole_day(self):
        self.assertEqual(self.listed("from=2026-03-10&to=2026-03-10"), [self.sample.id])
        self.assertEqual(self.listed("from=2026-03-11"), [])
        self.assertEqual(self.listed("to=2026-03-09"), [])

    def test_a_time_with_no_zone_is_the_labs_and_a_zone_is_respected(self):
        # 14:05:30 in Karachi is 09:05:30 UTC.
        self.assertEqual(self.listed("from=2026-03-10T14:05&to=2026-03-10T14:06"), [self.sample.id])
        self.assertEqual(self.listed("from=2026-03-10T09:05:00Z&to=2026-03-10T09:06:00Z"), [self.sample.id])
        self.assertEqual(self.listed("from=2026-03-10T10:00:00Z"), [])

    def test_the_named_periods_follow_the_labs_calendar(self):
        now = timezone.localtime()
        self.received_on(self.sample, now)
        for period in ("today", "week", "month", "quarter", "all"):
            self.assertEqual(self.listed(f"period={period}"), [self.sample.id], period)

        self.received_on(self.sample, now - timedelta(days=95))
        for period in ("today", "week", "month", "quarter"):
            self.assertEqual(self.listed(f"period={period}"), [], period)
        self.assertEqual(self.listed("period=all"), [self.sample.id])

    def test_last_week_and_last_month_are_the_ones_that_have_ended(self):
        # Wednesday 25 November 2026, 10:00 in the lab: this week began Monday the 23rd.
        wednesday = timezone.make_aware(datetime(2026, 11, 25, 10, 0))
        with patch("django.utils.timezone.now", return_value=wednesday):
            week = period_window("lastweek")
            month = period_window("lastmonth")
        self.assertEqual((week.label, month.label), ("Last week", "Last month"))
        self.assertEqual(timezone.localtime(week.start).date(), date(2026, 11, 16))
        self.assertEqual(timezone.localtime(week.stop).date(), date(2026, 11, 23), "up to this Monday, not into it")
        self.assertEqual(timezone.localtime(month.start).date(), date(2026, 10, 1))
        self.assertEqual(timezone.localtime(month.stop).date(), date(2026, 11, 1))
        # January looks back into the year before.
        january = timezone.make_aware(datetime(2027, 1, 5, 9, 0))
        with patch("django.utils.timezone.now", return_value=january):
            last = period_window("lastmonth")
        self.assertEqual((timezone.localtime(last.start).date(), timezone.localtime(last.stop).date()),
                         (date(2026, 12, 1), date(2027, 1, 1)))

    def test_something_from_last_week_is_in_last_week_and_not_this_one(self):
        now = timezone.localtime()
        this_monday = (now - timedelta(days=now.weekday())).replace(hour=12, minute=0)
        self.received_on(self.sample, this_monday - timedelta(days=3))
        self.assertEqual(self.listed("period=lastweek"), [self.sample.id])
        self.assertEqual(self.listed("period=week"), [])
        self.received_on(self.sample, this_monday + timedelta(minutes=1))
        self.assertEqual(self.listed("period=lastweek"), [])

    def test_a_list_can_filter_on_the_due_date_instead(self):
        Sample.objects.filter(pk=self.sample.pk).update(due_date="2026-04-20")
        self.assertEqual(self.listed("date_field=due&from=2026-04-20&to=2026-04-20"), [self.sample.id])
        self.assertEqual(self.listed("date_field=due&to=2026-04-19"), [])
        self.assertEqual(self.listed("date_field=received&from=2026-04-20"), [])

    def test_a_period_counts_what_is_due_later_in_it(self):
        Sample.objects.filter(pk=self.sample.pk).update(due_date=timezone.localdate() + timedelta(days=400))
        self.assertEqual(self.listed("date_field=due&period=week"), [])
        Sample.objects.filter(pk=self.sample.pk).update(due_date=timezone.localdate())
        self.assertEqual(self.listed("date_field=due&period=today"), [self.sample.id])

    def test_dates_that_make_no_sense_are_refused_not_ignored(self):
        self.assertIn("not a valid date", self.refused("from=yesterday"))
        self.assertIn("not a valid date", self.refused("to=2026-02-31"))
        self.assertIn("after its end", self.refused("from=2026-03-11&to=2026-03-10"))
        self.assertIn("cannot be filtered", self.refused("date_field=certificate&from=2026-03-10"))

    def test_an_unknown_period_falls_back_to_the_lists_default(self):
        self.assertEqual(self.listed("period=fortnight"), [self.sample.id])

    def test_the_tiles_above_a_list_follow_its_filter_and_the_nav_badges_do_not(self):
        self.login(self.frontdesk)
        self.assertEqual(self.client.get("/api/summary/?from=2026-03-10&to=2026-03-10").data["total"], 1)
        self.assertEqual(self.client.get("/api/summary/?from=2026-03-11").data["total"], 0)
        self.assertEqual(self.client.get("/api/summary/").data["total"], 1)

    def test_the_activity_log_and_analytics_use_the_same_range(self):
        self.login(self.admin)
        record(self.admin, "PRINTED", "certificate", 3, sample="S1")
        event = AuditEvent.objects.get(action="PRINTED")
        force_update(AuditEvent.objects.filter(pk=event.pk), at=lab_time(2026, 3, 10, 14, 5, 30))

        rows = self.client.get("/api/auth/audit/?from=2026-03-10T14:05&to=2026-03-10T14:05").data["results"]
        self.assertEqual([e["action"] for e in rows], ["PRINTED"])
        self.assertEqual(self.client.get("/api/auth/audit/?from=yesterday").status_code, 400)

        r = self.client.get("/api/auth/analytics/?from=2026-03-10&to=2026-03-10")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["period"], "custom")
        self.assertEqual(r.data["label"], "10 Mar 2026, 12:00 AM to 10 Mar 2026, 11:59 PM")


class PaginationTests(ListTestBase):
    def setUp(self):
        super().setUp()
        self.samples = [self.register_sample() for _ in range(5)]

    def page(self, query):
        self.login(self.frontdesk)
        return self.client.get(f"/api/samples/?status=ALL&{query}").data

    def test_every_page_says_where_it_is_and_nothing_is_missed_or_repeated(self):
        seen = []
        for number in (1, 2, 3):
            data = self.page(f"page_size=2&page={number}")
            self.assertEqual((data["count"], data["page"], data["page_size"], data["pages"]), (5, number, 2, 3))
            seen += [s["id"] for s in data["results"]]
        self.assertEqual(seen, [s.id for s in reversed(self.samples)])  # newest first

    def test_a_page_past_the_end_gives_the_last_page(self):
        data = self.page("page_size=2&page=9")
        self.assertEqual(data["page"], 3)
        self.assertEqual(len(data["results"]), 1)

    def test_bad_paging_values_fall_back_to_sensible_ones(self):
        data = self.page("page_size=lots&page=first")
        self.assertEqual((data["page"], data["page_size"]), (1, 25))
        self.assertEqual(self.page("page_size=0")["page_size"], 1)
        self.assertEqual(self.page("page_size=100000")["page_size"], 200)

    def test_an_empty_list_is_one_empty_page(self):
        data = self.page("from=2000-01-01&to=2000-01-02")
        self.assertEqual((data["results"], data["count"], data["page"], data["pages"]), ([], 0, 1, 1))

    def test_counts_never_include_what_the_person_cannot_see(self):
        other = User.objects.create_user(username="analyst2", password=PW, role=self.roles["ANALYST"])
        other.sections.set([self.section])
        self.login(other)
        data = self.client.get("/api/samples/?status=ALL").data
        self.assertEqual((data["count"], data["results"]), (0, []))

    def test_a_status_group_and_its_overdue_total_cover_every_page(self):
        Sample.objects.filter(pk=self.samples[0].pk).update(due_date=timezone.localdate() - timedelta(days=2))
        self.login(self.analyst)
        data = self.client.get("/api/samples/?status=RECEIVED,IN_TESTING&page_size=1").data
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["overdue"], 1)
        self.assertEqual(self.client.get("/api/samples/?status=IN_REVIEW,APPROVED").data["count"], 0)

    def test_the_activity_log_offers_each_action_once(self):
        for i in range(3):
            record(self.admin, "PRINTED", "certificate", i, sample="S1")
        self.login(self.admin)
        actions = self.client.get("/api/auth/audit/?period=all").data["actions"]
        self.assertEqual(actions.count("PRINTED"), 1)
        self.assertEqual(actions, sorted(actions))

    def test_the_users_list_is_paged_the_same_way(self):
        self.login(self.admin)
        data = self.client.get("/api/auth/users/?page_size=2").data
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["count"], User.objects.count())
        self.assertEqual(data["active"], User.objects.filter(is_active=True).count())
