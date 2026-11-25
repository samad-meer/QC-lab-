"""
The one way to run QC Lab in production. It loads deploy/qclab.env, so the web
server and every command see the same settings.

    python deploy/run.py serve             the web server, behind nginx
    python deploy/run.py migrate           any manage.py command

Anything already set in the environment wins. That is how migrations run as the
owner login: set POSTGRES_USER and POSTGRES_PASSWORD for that one command.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
PORT = int(os.environ.get("QCLAB_PORT", "8007"))


def load_settings():
    env_file = HERE / "qclab.env"
    if not env_file.exists():
        sys.exit(f"{env_file} is missing. Copy qclab.env.example and fill it in.")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qclab.settings")
    if os.environ.get("DJANGO_DEBUG") != "0":
        sys.exit("DJANGO_DEBUG must be 0 in production.")
    sys.path.insert(0, str(BACKEND))


def serve():
    from waitress import serve as waitress_serve

    # Tells the app it is serving requests, so it starts its background worker (alerts and email).
    # Set before the application loads. A migration or a shell run through this file does not start it.
    os.environ["QCLAB_SERVING"] = "1"
    from qclab.wsgi import application

    # Waitress drops forwarded headers unless it is told who to believe. Only
    # nginx, on this machine, is believed, and it listens nowhere else.
    waitress_serve(
        application, host="127.0.0.1", port=PORT, threads=8,
        trusted_proxy="127.0.0.1", trusted_proxy_count=1,
        trusted_proxy_headers="x-forwarded-for x-forwarded-proto",
    )


def main():
    load_settings()
    if sys.argv[1:] == ["serve"]:
        serve()
        return
    from django.core.management import execute_from_command_line

    execute_from_command_line(["manage.py", *sys.argv[1:]])


if __name__ == "__main__":
    main()
