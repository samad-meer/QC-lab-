"""
The first administrator of a real installation. seed_demo is for demonstrations
only and refuses to run in production.
"""
from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, User
from accounts.passwords import remember_first_password, set_temporary_password


class Command(BaseCommand):
    help = "Create an administrator. They choose their own password the first time they sign in."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")

    def handle(self, *args, **options):
        username = options["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise CommandError(f"The username {username} is already taken.")
        role = Role.objects.filter(code="ADMIN").first()
        if role is None:
            raise CommandError("The Administrator role is missing. Run migrate first.")
        user = User(username=username, first_name=options["first_name"], last_name=options["last_name"],
                    role=role, is_staff=True, is_superuser=True)
        password = getpass("Temporary password: ")
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        set_temporary_password(user, password)
        user.save()
        remember_first_password(user)
        self.stdout.write(f"Created {username}. They will be asked for a new password when they sign in.")
