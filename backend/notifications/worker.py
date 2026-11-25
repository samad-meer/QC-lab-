"""
Work that has to happen, but that nobody is waiting for.

The due-date sweep and queued email used to ride on the bell's poll, which every open page makes on
every page change and every 30 seconds. So whoever's page happened to trigger them waited: the sweep
walks every open sample, and an email waits on a mail server that can take its full 8-second timeout
to answer. They now run here, on a thread of the web process, and the bell only reads.

No broker is needed. The queue is the database. Email rows are claimed with SKIP LOCKED and the sweep
records its own last run in one atomic UPDATE, so a second process, or `manage.py send_due_alerts` on a
schedule beside this, can never send anything twice.

It starts only where requests are served: the development server and `deploy/run.py serve`. A test
run, a migration or a shell never starts it. QCLAB_BACKGROUND=0 turns it off, for a lab that runs
`send_due_alerts` from a scheduler instead.
"""
import logging
import os
import sys
import threading

from django.db import connections

from .alerts import flush_email, sweep_if_due

logger = logging.getLogger(__name__)

INTERVAL = 30      # seconds between rounds: the same pace the bell used to set
FIRST_DELAY = 10   # seconds after start, so the server has finished starting (and migrating) first

_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None


def serving() -> bool:
    """Is this process answering web requests, as opposed to a test, a migration or a shell?"""
    if os.environ.get("QCLAB_BACKGROUND", "1") != "1":
        return False
    if os.environ.get("QCLAB_SERVING") == "1":  # set by deploy/run.py before it starts the web server
        return True
    # The development server runs the site in a child process marked RUN_MAIN, or in itself with --noreload.
    return "runserver" in sys.argv and (os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv)


def run_round():
    """One round: the hourly due-date sweep if it is due, then any email that is waiting.
    Each part guards itself, so a mail problem cannot stop the sweep, nor the sweep the mail."""
    for task in (sweep_if_due, flush_email):
        try:
            task()
        except Exception:
            logger.exception("Background %s failed", task.__name__)


def _loop():
    if _stop.wait(FIRST_DELAY):
        return
    while True:
        run_round()
        connections.close_all()  # hand this thread's connection back to the pool between rounds
        if _stop.wait(INTERVAL):
            return


def start() -> threading.Thread:
    """Start the worker once for this process; calling it again returns the running one."""
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _stop.clear()
            _thread = threading.Thread(target=_loop, name="qclab-worker", daemon=True)
            _thread.start()
        return _thread


def stop():
    _stop.set()
