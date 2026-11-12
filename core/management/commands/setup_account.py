from getpass import getpass

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Interactively create a shared-cellar account or reset an existing account's password."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--reset", action="store_true", help="Reset an existing account.")

    def handle(self, username, reset, **options):
        user_model = get_user_model()
        user = user_model.objects.filter(username=username).first()
        if reset and not user:
            raise CommandError("No such account.")
        if user and not reset:
            raise CommandError("Account exists. Use --reset for password recovery.")
        user = user or user_model(username=username)
        try:
            user.full_clean(exclude=["password"])
            password = getpass("Password: ")
            if password != getpass("Password again: "):
                raise CommandError("Passwords do not match.")
            password_validation.validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        with transaction.atomic():
            user.set_password(password)
            user.is_active = True
            user.save()
        self.stdout.write(
            self.style.SUCCESS("Account ready. All active accounts share the cellar.")
        )
