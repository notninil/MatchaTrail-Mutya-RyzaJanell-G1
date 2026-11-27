import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import User
from checkins.models import Cafe


class SeedDemoTests(TestCase):
    owner_variable = "MATCHATRAIL_DEMO_OWNER_PASSWORD"
    explorer_variable = "MATCHATRAIL_DEMO_EXPLORER_PASSWORD"

    def setUp(self):
        self.owner_password = "Juniper^Window29"
        self.explorer_password = "Evening^Kettle42"
        environment = patch.dict(
            os.environ,
            {
                self.owner_variable: self.owner_password,
                self.explorer_variable: self.explorer_password,
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        noninteractive = patch("checkins.management.commands.seed_demo.sys.stdin")
        self.stdin = noninteractive.start()
        self.stdin.isatty.return_value = False
        self.addCleanup(noninteractive.stop)

    def seed(self, **options):
        output = StringIO()
        call_command("seed_demo", stdout=output, stderr=output, **options)
        return output.getvalue()

    def test_creates_separate_credentials_without_printing_them(self):
        output = self.seed()
        owner = User.objects.get(username="owner_demo", role=User.Role.OWNER)
        explorer = User.objects.get(username="explorer_demo", role=User.Role.EXPLORER)
        self.assertTrue(owner.check_password(self.owner_password))
        self.assertTrue(explorer.check_password(self.explorer_password))
        self.assertFalse(owner.check_password(self.explorer_password))
        self.assertFalse(explorer.check_password(self.owner_password))
        self.assertNotIn(self.owner_password, output)
        self.assertNotIn(self.explorer_password, output)
        self.assertEqual(Cafe.objects.count(), 15)
        self.assertEqual(Cafe.objects.filter(owner=owner).count(), 2)

    def test_rerun_preserves_password_hashes_without_supplied_passwords(self):
        self.seed()
        before = dict(User.objects.values_list("username", "password"))
        for key in (self.owner_variable, self.explorer_variable):
            del os.environ[key]
        self.seed()
        self.assertEqual(dict(User.objects.values_list("username", "password")), before)
        self.assertEqual(Cafe.objects.count(), 15)

    def test_missing_second_password_does_not_create_users_or_cafes(self):
        del os.environ[self.explorer_variable]
        with self.assertRaisesMessage(CommandError, self.explorer_variable):
            self.seed()
        self.assertFalse(User.objects.exists())
        self.assertFalse(Cafe.objects.exists())

    def test_invalid_password_is_rejected_without_echo_or_writes(self):
        os.environ[self.explorer_variable] = "123456"
        with self.assertRaises(CommandError) as caught:
            self.seed()
        self.assertIn("validation", str(caught.exception))
        self.assertNotIn(os.environ[self.explorer_variable], str(caught.exception))
        self.assertFalse(User.objects.exists())
        self.assertFalse(Cafe.objects.exists())

    def test_interactive_passwords_use_hidden_input(self):
        self.stdin.isatty.return_value = True
        for key in (self.owner_variable, self.explorer_variable):
            del os.environ[key]
        with patch(
            "checkins.management.commands.seed_demo.getpass",
            side_effect=[self.owner_password, self.explorer_password],
        ) as prompt:
            output = self.seed()
        self.assertEqual(prompt.call_count, 2)
        self.assertNotIn(self.owner_password, output)
        self.assertNotIn(self.explorer_password, output)
        self.assertTrue(User.objects.get(username="owner_demo").check_password(self.owner_password))
        self.assertTrue(
            User.objects.get(username="explorer_demo").check_password(self.explorer_password),
        )

    def test_rotation_requires_both_passwords_and_explicit_option(self):
        self.seed()
        before = dict(User.objects.values_list("username", "password"))
        new_owner = "Alpine^Lantern39"
        new_explorer = "Summer^Clover83"
        os.environ[self.owner_variable] = new_owner
        del os.environ[self.explorer_variable]
        with self.assertRaisesMessage(CommandError, self.explorer_variable):
            self.seed(rotate_passwords=True)
        self.assertEqual(dict(User.objects.values_list("username", "password")), before)
        os.environ[self.explorer_variable] = new_explorer
        self.seed()
        self.assertEqual(dict(User.objects.values_list("username", "password")), before)
        output = self.seed(rotate_passwords=True)
        for username, password in (("owner_demo", new_owner), ("explorer_demo", new_explorer)):
            user = User.objects.get(username=username)
            self.assertTrue(user.check_password(password))
            self.assertNotIn(password, output)
            self.assertNotEqual(user.password, before[username])

    def test_database_failure_rolls_back_account_and_cafe_writes(self):
        update_cafe = Cafe.objects.update_or_create

        def fail_on_second_cafe(**kwargs):
            if Cafe.objects.exists():
                raise IntegrityError("Controlled seed failure")
            return update_cafe(**kwargs)

        with patch.object(Cafe.objects, "update_or_create", side_effect=fail_on_second_cafe):
            with self.assertRaisesMessage(IntegrityError, "Controlled seed failure"):
                self.seed()
        self.assertFalse(User.objects.exists())
        self.assertFalse(Cafe.objects.exists())
