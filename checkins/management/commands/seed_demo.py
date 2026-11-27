import os
import sys
import warnings
from getpass import GetPassWarning, getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from checkins.models import Cafe

# Clearly labeled DEMO data (fictional cafés) for development and grading.
# (name, area, price range). Areas in Mandaue City / Lapu-Lapu City are listed under their own city.
DEMO_CAFES = [
    ("Demo Matcha House", "Lahug", "2"), ("Demo Whisk & Leaf", "IT Park", "2"),
    ("Demo Green Ceremony", "Banilad", "3"), ("Demo Usucha Corner", "Mabolo", "1"),
    ("Demo Kyoto Kettle", "Ayala Center", "3"), ("Demo Sip & Stir Matcha", "Mandaue", "1"),
    ("Demo Hojicha & Co.", "Capitol Site", "2"), ("Demo Chasen Studio", "Guadalupe", "2"),
    ("Demo Tencha Table", "Talamban", "2"), ("Demo Emerald Cup", "Escario", "1"),
    ("Demo Jade Bowl", "Colon", "1"), ("Demo Uji Lane", "Lapu-Lapu City", "2"),
    ("Demo Matcha Mornings", "Basak", "1"), ("Demo Shizuoka Bar", "Kasambagan", "3"),
    ("Demo Verdant Brew", "Apas", "2"),
]
CITY_OVERRIDES = {"Mandaue": "Mandaue City", "Lapu-Lapu City": "Lapu-Lapu City"}
DEMO_ACCOUNTS = (
    ("owner_demo", User.Role.OWNER, "MATCHATRAIL_DEMO_OWNER_PASSWORD"),
    ("explorer_demo", User.Role.EXPLORER, "MATCHATRAIL_DEMO_EXPLORER_PASSWORD"),
)


class Command(BaseCommand):
    help = "Seed 15 demo cafés and two test accounts (explorer_demo, owner_demo). Safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rotate-passwords",
            action="store_true",
            help="Replace both demo account passwords with explicitly supplied values.",
        )

    def get_password(self, user, variable):
        password = os.environ.get(variable)
        if password is None:
            if not sys.stdin.isatty():
                raise CommandError(f"Supply {variable} to set the password for {user.username}.")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", GetPassWarning)
                    password = getpass(f"New password for {user.username}: ")
            except (EOFError, GetPassWarning):
                raise CommandError(f"Supply {variable} to set the password for {user.username}.") from None
        if not password.strip():
            raise CommandError(f"The password for {user.username} cannot be blank.")
        try:
            validate_password(password, user)
        except ValidationError:
            raise CommandError(f"The password for {user.username} did not pass Django's password validation.") from None
        return password

    @transaction.atomic
    def handle(self, *args, **options):
        accounts = {}
        pending = []
        for username, role, variable in DEMO_ACCOUNTS:
            user = User.objects.select_for_update().filter(username=username).first()
            if user is not None and user.role != role:
                raise CommandError(f"{username} has an unexpected role. Review the account before seeding.")
            if user is None:
                user = User(username=username, email=f"{username}@example.com", role=role)
            if user.pk is None or options["rotate_passwords"]:
                pending.append((user, self.get_password(user, variable)))
            accounts[role] = user

        for user, password in pending:
            user.set_password(password)
            user.save()

        for index, (name, area, price) in enumerate(DEMO_CAFES):
            Cafe.objects.update_or_create(name=name, defaults={
                "address": area, "city": CITY_OVERRIDES.get(area, "Cebu City"),
                "price_range": price, "description": "Demo listing for development.",
                "owner": accounts[User.Role.OWNER] if index < 2 else None,
            })
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(DEMO_CAFES)} cafés. Demo accounts: explorer_demo and owner_demo."
        ))
