"""
For `manage.py test` only, chosen by backend/test.env. Real password hashing is
slow on purpose, and over this many sign-ins it adds up to half an hour.
The web server and deploy/run.py always use qclab.settings.
"""
from .settings import *  # noqa: F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
