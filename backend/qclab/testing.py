"""Helpers for tests."""
from contextlib import contextmanager

from django.db import connection

from accounts.models import LabConfig


def relax_failure_rules():
    """
    Most tests are about something else, so they start without the quality unit's
    rules after a failure. quality/test_failure_path.py tests those as shipped.
    """
    LabConfig.objects.update_or_create(pk=1, defaults={
        "oos_investigation_required": False, "oos_max_retests": 99,
        "oos_second_analyst": False, "oos_batch_block": False,
    })


@contextmanager
def unlocked(model):
    """
    Set up a test's starting point on a table the database protects.

    On PostgreSQL the triggers would rightly stop a test backdating a sample, so
    they are switched off for this block. Never used outside tests.
    """
    if connection.vendor != "postgresql":
        yield
        return
    table = connection.ops.quote_name(model._meta.db_table)
    # ALTER TABLE is refused while foreign key checks are waiting on the table,
    # and the block itself queues more of them.
    connection.check_constraints()
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")
    try:
        yield
    finally:
        connection.check_constraints()
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")


def force_update(queryset, **fields):
    with unlocked(queryset.model):
        return queryset.update(**fields)
