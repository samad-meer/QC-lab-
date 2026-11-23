"""
The events that send notifications, and how each one is configured. The
catalogue is code, because each event is sent from somewhere; which events are
on, and who else hears, is a NotificationRule row an administrator changes.

A notification of a kind listed nowhere here is always sent.
"""
from .models import NotificationRule

# event -> label, hint, the kinds it covers, and what can be set on it.
EVENTS: dict[str, dict] = {
    "WORK_ASSIGNED": {
        "label": "Work assigned or handed over",
        "hint": "To the person receiving it, and the answer back to whoever sent it.",
        "kinds": {"ASSIGNED", "REASSIGNED", "HANDOVER", "HANDOVER_ACCEPTED", "HANDOVER_DECLINED", "HANDOVER_CANCELLED"},
    },
    "READY_FOR_TESTING": {
        "label": "Sample ready for testing",
        "hint": "To the analyst, when the front desk completes the receipt checks.",
        "kinds": {"READY_FOR_TESTING"},
    },
    "REVIEW_NAMED": {
        "label": "Review reached a named person",
        "hint": "To the reviewer a stage is assigned to, when the sample reaches them.",
        "kinds": {"YOUR_TURN"},
    },
    "REVIEW_OPEN": {
        "label": "Review waiting, nobody named",
        "hint": "To everyone who could take the stage, when the sample reaches it and nobody is assigned.",
        "kinds": {"REVIEW_WAITING"},
    },
    "RETURNED": {
        "label": "Work sent back",
        "hint": "To the analyst, with the reviewer's reason.",
        "kinds": {"RETURNED"},
    },
    "HOLDS": {
        "label": "Sample put on hold or released",
        "hint": "To the analyst and whoever holds the current step.",
        "kinds": {"ON_HOLD", "RELEASED"},
    },
    "RETESTS": {
        "label": "Retest requested or decided",
        "hint": "To the people who may decide it, then to whoever asked.",
        "kinds": {"RETEST_REQUESTED", "RETEST_AUTHORIZED", "RETEST_DECLINED"},
    },
    "FAILED_RESULT": {
        "label": "Result out of specification",
        "hint": "To the people who may authorize a retest, the moment a failing result is entered.",
        "kinds": {"RESULT_FAILED"},
        "roles": True,
    },
    "DUE_SOON": {
        "label": "Sample due soon",
        "hint": "To whoever the sample is waiting for, before its due date.",
        "kinds": {"DUE_SOON"},
        "roles": True,
        "days_before": True,
    },
    "OVERDUE": {
        "label": "Sample overdue",
        "hint": "To whoever the sample is waiting for, once it passes its due date.",
        "kinds": {"OVERDUE"},
        "roles": True,
        "repeat": True,
    },
    "CERT_RELEASED": {
        "label": "Certificate released",
        "hint": "To the analyst, whoever registered the sample and the people who print, at the last signature.",
        "kinds": {"CERT_RELEASED"},
        "roles": True,
    },
    "CALIBRATION_DUE": {
        "label": "Instrument calibration due",
        "hint": "To the people who manage instruments, before the calibration runs out and once it has.",
        "kinds": {"CALIBRATION_DUE", "CALIBRATION_OVERDUE"},
        "roles": True,
        "days_before": True,
        "repeat": True,
        "default_days": 14,
    },
    "QUALIFICATION_DUE": {
        "label": "Analyst qualification expiring",
        "hint": "To the analyst and the people who grant qualifications, before it expires and once it has.",
        "kinds": {"QUALIFICATION_DUE", "QUALIFICATION_EXPIRED"},
        "roles": True,
        "days_before": True,
        "repeat": True,
        "default_days": 30,
    },
}

_EVENT_OF = {kind: event for event, spec in EVENTS.items() for kind in spec["kinds"]}


def rule_for(event: str) -> NotificationRule:
    days = EVENTS[event].get("default_days", 1)
    return NotificationRule.objects.get_or_create(event=event, defaults={"days_before": days})[0]


def is_enabled(kind: str) -> bool:
    event = _EVENT_OF.get(kind)
    return event is None or rule_for(event).enabled


def wants_email(kind: str) -> bool:
    event = _EVENT_OF.get(kind)
    return event is None or rule_for(event).email


def extra_people(rule: NotificationRule) -> list:
    """Active people in the roles an administrator added to this event."""
    from accounts.models import User

    return list(User.objects.filter(is_active=True, role__in=rule.roles.all()))
