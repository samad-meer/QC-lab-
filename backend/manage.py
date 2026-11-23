#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path


# The Vite dev server proxies to this port. Keep the two in step, or a plain
# `runserver` lands on Django's default 8000 and the frontend talks to nothing.
DEFAULT_PORT = os.environ.get("BACKEND_PORT", "8007")


def load_local_env():
    """
    This machine's database login, from backend/.env. Anything already set wins,
    which is how migrations run as the owner login. Tests use backend/test.env: a
    login that can create its own database and cannot reach the real one.
    """
    env_file = Path(__file__).resolve().parent / ("test.env" if sys.argv[1:2] == ["test"] else ".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip())


def main():
    load_local_env()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qclab.settings")
    # A developer's convenience. Production sets DJANGO_DEBUG=0, and the web
    # server does not come through here at all.
    os.environ.setdefault("DJANGO_DEBUG", "1")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # `runserver` with no address given → use our port, not Django's 8000.
    if len(sys.argv) > 1 and sys.argv[1] == "runserver":
        if not any(not a.startswith("-") for a in sys.argv[2:]):
            sys.argv.append(DEFAULT_PORT)

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
