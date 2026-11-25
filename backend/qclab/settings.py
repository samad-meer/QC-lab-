"""
QC Lab — Django settings.

Every environment runs on PostgreSQL: the database-level immutability triggers
(certificates migration 0002) exist nowhere else. The POSTGRES_* variables say
which server, from backend/.env on a developer's machine and deploy/qclab.env in
production. Without them the application refuses to start.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Off unless asked for. manage.py asks for it on a developer's machine; the web
# server (qclab/wsgi.py) never does, so a forgotten setting fails safe.
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# With debug off there is no default: Django refuses to start without a real key.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me" if DEBUG else "")

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "audit",
    "lims",
    "certificates",
    "execution",
    "batches",
    "standards",
    "notifications",
    "quality",
    "labrecords",
    "reports",
]

MIDDLEWARE = [
    "qclab.middleware.RequestSizeLimitMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # The lab's time zone, chosen on the Settings screen (TIME_ZONE below until it is).
    "accounts.middleware.LabTimeZoneMiddleware",
    # Makes the request available to the audit writer, so every recorded
    # action carries the address it came from.
    "audit.middleware.AuditContextMiddleware",
    # Idle timeout and a password that is due. After the audit context, so it is recorded.
    "accounts.middleware.SessionGuardMiddleware",
]

ROOT_URLCONF = "qclab.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "qclab.wsgi.application"

if not os.environ.get("POSTGRES_DB"):
    raise ImproperlyConfigured("POSTGRES_DB is not set. See 'Run it' in README.md.")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", "qclab"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # Opening a PostgreSQL connection takes 60 to 300 ms on Windows, and without a pool every
        # request opens one, so a page that makes six calls pays it six times before any work is done.
        # A pool keeps connections open and hands them out in under a millisecond. It also works with
        # the development server, which starts a new thread for every request and so cannot use
        # CONN_MAX_AGE. 16 covers waitress's 8 threads and a browser's parallel calls; a request
        # waits for a free one rather than failing. QCLAB_DB_POOL=0 turns it off.
        "OPTIONS": ({"pool": {"min_size": 2, "max_size": 16, "timeout": 20}}
                    if os.environ.get("QCLAB_DB_POOL", "1") == "1" else {}),
        # On Windows the default template is usually WIN1252, which refuses
        # characters the app stores, such as the arrow in a workflow name.
        "TEST": {"CHARSET": "UTF8", "TEMPLATE": "template0"},
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.LockoutBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "EXCEPTION_HANDLER": "audit.handlers.record_refusals",
}

# Change to your lab's local zone; all timestamps are stored in UTC.
TIME_ZONE = "Asia/Karachi"
USE_TZ = True

LANGUAGE_CODE = "en-us"
USE_I18N = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files (currently only profile photos). Deliberately no MEDIA_URL:
# photographs are personal data and are served through an authenticated view
# (/api/auth/users/<pk>/photo/), never from a publicly addressable path.
MEDIA_ROOT = Path(os.environ.get("QCLAB_MEDIA_ROOT", BASE_DIR / "media"))

# A profile photo is capped at 2 MB in accounts/photos.py; these are the
# outer limits that stop a request being buffered to disk or memory at size.
FILE_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The React dev server proxies /api to Django (same-origin), so no CORS
# machinery is needed. Trusted origins listed for direct-port access in dev.
# In production, DJANGO_CSRF_TRUSTED_ORIGINS holds the site's own https address.
CSRF_TRUSTED_ORIGINS = [
    origin for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin
] or ["http://localhost:5173", "http://127.0.0.1:5173"]
if DEBUG:
    # Another computer on the same network may open the screens at this machine's
    # own address (DEV_LAN=1, see frontend/vite.config.ts); its browser then signs
    # in from http://<this machine's IP>:5173. Looked up at every start, so a new
    # address from the router works.
    import socket

    try:
        _port = os.environ.get("FRONTEND_PORT", "5173")
        CSRF_TRUSTED_ORIGINS += [f"http://{ip}:{_port}" for ip in socket.gethostbyname_ex(socket.gethostname())[2]]
    except OSError:
        pass
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# A session ends after this much idle time, and at the end of the working day whatever happens.
QCLAB_IDLE_MINUTES = int(os.environ.get("QCLAB_IDLE_MINUTES", "15"))
SESSION_COOKIE_AGE = 12 * 60 * 60
QCLAB_PASSWORD_MAX_AGE_DAYS = int(os.environ.get("QCLAB_PASSWORD_MAX_AGE_DAYS", "180"))

# Email stays off until a mail server is named; alerts reach the bell in the app either way.
EMAIL_HOST = os.environ.get("QCLAB_EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("QCLAB_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("QCLAB_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("QCLAB_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("QCLAB_EMAIL_TLS", "1") == "1"
EMAIL_TIMEOUT = 8
DEFAULT_FROM_EMAIL = os.environ.get("QCLAB_EMAIL_FROM", "QC Lab <qclab@localhost>")
# How the links in an email begin, such as https://qclab.example.com. Blank leaves links out.
QCLAB_BASE_URL = os.environ.get("QCLAB_BASE_URL", "").rstrip("/")

# Only behind a proxy of ours are its headers worth believing. nginx/qclab.conf sets them.
QCLAB_BEHIND_PROXY = os.environ.get("QCLAB_BEHIND_PROXY", "0") == "1"
if QCLAB_BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# With debug off Django logs nowhere by default, so an error would leave no trace.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {"django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False}},
}
