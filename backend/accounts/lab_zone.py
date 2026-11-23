"""
The lab's time zone and clock, chosen on the Settings screen: Pakistan, and a
12-hour clock, unless changed.

Every recorded moment is stored in UTC. The zone decides where "today" begins (due
dates, overdue alerts, report periods) and how a date and time is written on a
screen, a report or a certificate. A signed certificate keeps the times it was
signed with.
"""
from contextvars import ContextVar
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

from django.conf import settings
from django.utils import timezone


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def is_zone(name) -> bool:
    return isinstance(name, str) and name in _zones()


def lab_zone_name() -> str:
    from .models import LabConfig

    name = LabConfig.get().time_zone
    return name if is_zone(name) else settings.TIME_ZONE


# The lab's clock, set with its zone for each request, command or job.
_hour12: ContextVar[bool] = ContextVar("lab_hour12", default=True)


def activate_lab_zone() -> str:
    """For a request, a command or a job: work in the lab's zone, and write times its way, from here on."""
    from .models import LabConfig

    cfg = LabConfig.get()
    name = cfg.time_zone if is_zone(cfg.time_zone) else settings.TIME_ZONE
    timezone.activate(ZoneInfo(name))
    _hour12.set(cfg.time_format != "24h")
    return name


def deactivate_lab_zone() -> None:
    """After a request: back to the default zone and the default clock, so nothing carries over."""
    timezone.deactivate()
    _hour12.set(True)


def hour12() -> bool:
    """Does the lab write times on a 12-hour clock (02:05 PM) rather than 24 hours (14:05)?"""
    return _hour12.get()


def clock(seconds: bool = True) -> str:
    """The strftime pattern for a time of day, as the lab writes it: 02:05:12 PM, or 14:05:12."""
    if hour12():
        return "%I:%M:%S %p" if seconds else "%I:%M %p"
    return "%H:%M:%S" if seconds else "%H:%M"
