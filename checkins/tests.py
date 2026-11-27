from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.forms import ModelForm
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .forms import CheckInForm
from .models import Cafe, CheckIn


class CheckInTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.explorer = User.objects.create_user("explorer_test", "explorer@test.example")
        cls.other = User.objects.create_user("other_test", "other@test.example")
        cls.owner = User.objects.create_user(
            "owner_test", "owner@test.example", role=User.Role.OWNER,
        )
        cls.cafe = Cafe.objects.create(name="Test Cafe", owner=cls.owner)
        cls.other_cafe = Cafe.objects.create(name="Other Cafe")
        cls.inactive = Cafe.objects.create(name="Inactive Cafe", is_active=False)
        cls.visit = CheckIn.objects.create(
            user=cls.other, cafe=cls.cafe, drink_name="Other drink", rating=4,
        )
        cls.unowned = CheckIn.objects.create(
            user=cls.other, cafe=cls.other_cafe, drink_name="Private drink", rating=4,
        )

    def setUp(self):
        self.client.force_login(self.explorer)
        self.create_url = reverse("checkin_create")
        self.list_url = reverse("checkin_list")
        self.data = {
            "cafe": self.cafe.pk,
            "drink_name": "Matcha latte",
            "rating": 5,
            "visited_on": timezone.localdate().isoformat(),
            "notes": "Test note",
        }

    def create_own(self):
        return CheckIn.objects.create(
            user=self.explorer, cafe=self.cafe, drink_name="Own drink", rating=4,
        )

    def mutation_urls(self, pk):
        return (
            self.create_url,
            reverse("checkin_update", args=[pk]),
            reverse("checkin_delete", args=[pk]),
        )

    def checkin_snapshot(self):
        return list(CheckIn.objects.order_by("pk").values())

    def assert_invalid_create(self, data, field, error_code):
        before = self.checkin_snapshot()
        response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors.as_data()
        self.assertIn(error_code, [error.code for error in errors.get(field, [])])
        self.assertEqual(self.checkin_snapshot(), before)

    def test_create_valid(self):
        response = self.client.post(
            self.create_url, {**self.data, "user": self.other.pk}, follow=True,
        )
        self.assertRedirects(response, self.list_url)
        visit = CheckIn.objects.get(drink_name=self.data["drink_name"])
        self.assertEqual(visit.user, self.explorer)
        self.assertEqual(visit.cafe, self.cafe)
        self.assertEqual(visit.rating, self.data["rating"])
        self.assertEqual(visit.visited_on.isoformat(), self.data["visited_on"])
        self.assertEqual(visit.notes, self.data["notes"])
        self.assertContains(response, "Your check-in was added")

    def test_empty_create_and_update_display_required_errors(self):
        visit = self.create_own()
        before = self.checkin_snapshot()
        urls = (self.create_url, reverse("checkin_update", args=[visit.pk]))
        for url in urls:
            with self.subTest(url=url):
                response = self.client.post(url, {})
                self.assertEqual(response.status_code, 200)
                form = response.context["form"]
                self.assertTrue(form.is_bound)
                for field in ("cafe", "drink_name", "rating", "visited_on"):
                    self.assertTrue(form.has_error(field, "required"), field)
        self.assertEqual(self.checkin_snapshot(), before)

    def test_missing_required_fields(self):
        for field in ("cafe", "drink_name", "rating", "visited_on"):
            with self.subTest(field=field):
                data = self.data.copy()
                del data[field]
                self.assert_invalid_create(data, field, "required")

    def test_invalid_rating(self):
        for rating in (0, 6, "invalid"):
            with self.subTest(rating=rating):
                self.assert_invalid_create({**self.data, "rating": rating}, "rating", "invalid_choice")

    def test_future_date(self):
        future = timezone.localdate() + timedelta(days=1)
        self.assert_invalid_create({**self.data, "visited_on": future.isoformat()}, "visited_on", None)

    def test_duplicate(self):
        self.create_own()
        before = self.checkin_snapshot()
        response = self.client.post(self.create_url, self.data)
        self.assertContains(response, "Edit that check-in instead.")
        self.assertEqual(self.checkin_snapshot(), before)

    def test_invalid_or_inactive_cafe(self):
        for cafe in ("invalid", self.inactive.pk, 2**63):
            with self.subTest(cafe=cafe):
                self.assert_invalid_create({**self.data, "cafe": cafe}, "cafe", "invalid_choice")

    def test_login_required(self):
        self.client.logout()
        before = self.checkin_snapshot()
        for url in (self.list_url, *self.mutation_urls(self.visit.pk)):
            with self.subTest(url=url):
                target = f"{reverse('login')}?next={url}"
                self.assertRedirects(self.client.get(url), target, fetch_redirect_response=False)
                self.assertRedirects(
                    self.client.post(url, self.data), target, fetch_redirect_response=False,
                )
        self.assertEqual(self.checkin_snapshot(), before)

    def test_other_record_blocked(self):
        before = self.checkin_snapshot()
        for url in self.mutation_urls(self.visit.pk)[1:]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, self.data).status_code, 404)
        self.assertEqual(self.checkin_snapshot(), before)

    def test_edit_own(self):
        visit = self.create_own()
        url = reverse("checkin_update", args=[visit.pk])
        data = {**self.data, "cafe": self.other_cafe.pk, "user": self.other.pk}
        original_ids = set(CheckIn.objects.values_list("pk", flat=True))
        response = self.client.post(url, data, follow=True)
        self.assertRedirects(response, self.list_url)
        visit.refresh_from_db()
        self.assertEqual(visit.user, self.explorer)
        self.assertEqual(visit.cafe, self.other_cafe)
        self.assertEqual(visit.drink_name, data["drink_name"])
        self.assertEqual(visit.rating, data["rating"])
        self.assertEqual(set(CheckIn.objects.values_list("pk", flat=True)), original_ids)
        self.assertContains(response, "Your check-in was updated")

    def test_delete_confirmation_and_post(self):
        visit = self.create_own()
        url = reverse("checkin_delete", args=[visit.pk])
        before = self.checkin_snapshot()
        self.assertContains(self.client.get(url, self.data), "Delete this check-in?")
        self.assertEqual(self.checkin_snapshot(), before)
        response = self.client.post(url, follow=True)
        self.assertRedirects(response, self.list_url)
        self.assertEqual(
            self.checkin_snapshot(), [row for row in before if row["id"] != visit.pk],
        )
        self.assertContains(response, "The check-in was removed from your passport.")
        self.assertContains(response, '<span class="notice-label">Removed</span>', html=True)

    def test_owner_cannot_mutate(self):
        self.client.force_login(self.owner)
        before = self.checkin_snapshot()
        for url in self.mutation_urls(self.visit.pk):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.data).status_code, 403)
        self.assertEqual(self.checkin_snapshot(), before)

    def test_owner_list_scope(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.list_url)
        self.assertContains(response, self.visit.drink_name)
        self.assertNotContains(response, self.unowned.drink_name)
        self.assertEqual(list(response.context["checkins"]), [self.visit])
        dashboard = self.client.get(reverse("owner_dashboard"))
        self.assertContains(dashboard, self.cafe.name)
        self.assertNotContains(dashboard, self.other_cafe.name)

    def test_explorer_list_scope(self):
        own = self.create_own()
        response = self.client.get(self.list_url)
        self.assertContains(response, own.drink_name)
        self.assertNotContains(response, self.visit.drink_name)
        self.assertEqual(list(response.context["checkins"]), [own])

    def test_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.explorer)
        visit = self.create_own()
        before = self.checkin_snapshot()
        for url in self.mutation_urls(visit.pk):
            with self.subTest(url=url):
                self.assertContains(client.get(url), 'name="csrfmiddlewaretoken"')
                self.assertEqual(client.post(url, self.data).status_code, 403)
        self.assertEqual(self.checkin_snapshot(), before)
        url = reverse("checkin_update", args=[visit.pk])
        token = client.cookies["csrftoken"].value
        self.assertRedirects(
            client.post(url, self.data, HTTP_X_CSRFTOKEN=token), self.list_url,
        )
        visit.refresh_from_db()
        self.assertEqual(visit.drink_name, self.data["drink_name"])

    @override_settings(DEBUG=False)
    def test_custom_404(self):
        update = reverse("checkin_update", args=[self.visit.pk])
        before = self.checkin_snapshot()
        for url in (
            "/missing-pd3-page/",
            "/checkins/abc/edit/",
            reverse("checkin_update", args=[2**63]),
            reverse("checkin_delete", args=[self.visit.pk + self.unowned.pk]),
            update,
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "This trail ends here.", status_code=404)
                self.assertTemplateUsed(response, "404.html")
        self.assertEqual(self.checkin_snapshot(), before)

    def test_database_duplicate_constraint(self):
        self.create_own()
        before = self.checkin_snapshot()
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            self.create_own()
        if connection.vendor == "postgresql":
            self.assertEqual(
                caught.exception.__cause__.diag.constraint_name, "checkins_one_per_cafe_per_day",
            )
        self.assertEqual(self.checkin_snapshot(), before)

    def test_postgresql_duplicate_is_reported_after_database_rejection(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL constraint diagnostics are required.")
        self.create_own()
        before = self.checkin_snapshot()
        # Bypass the pre-save duplicate query to exercise PostgreSQL's constraint path.
        with patch.object(CheckInForm, "clean", ModelForm.clean):
            response = self.client.post(self.create_url, self.data)
        self.assertContains(response, "You already checked in")
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertEqual(self.checkin_snapshot(), before)

    def test_database_rating_constraint(self):
        before = self.checkin_snapshot()
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            CheckIn.objects.create(user=self.explorer, cafe=self.cafe, drink_name="Invalid", rating=6)
        if connection.vendor == "postgresql":
            self.assertEqual(caught.exception.__cause__.diag.constraint_name, "checkins_rating_1_to_5")
        self.assertEqual(self.checkin_snapshot(), before)

    def test_get_edit_does_not_mutate(self):
        visit = self.create_own()
        before = self.checkin_snapshot()
        response = self.client.get(reverse("checkin_update", args=[visit.pk]), self.data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_bound)
        self.assertEqual(self.checkin_snapshot(), before)

    @override_settings(DEBUG=False)
    def test_unexpected_integrity_error_rolls_back_and_renders_custom_500(self):
        before = self.checkin_snapshot()
        save = CheckInForm.save

        def save_then_fail(form):
            visit = save(form)
            CheckIn.objects.filter(pk=visit.pk).update(rating=6)

        self.client.raise_request_exception = False
        with patch.object(CheckInForm, "save", save_then_fail):
            response = self.client.post(self.create_url, self.data)
        self.assertContains(response, "Something went wrong.", status_code=500)
        self.assertTemplateUsed(response, "500.html")
        self.assertNotContains(response, "checkins_rating_1_to_5", status_code=500)
        self.assertNotContains(response, "already checked in", status_code=500)
        self.assertEqual(self.checkin_snapshot(), before)

    def test_user_content_is_escaped_for_explorer_and_owner(self):
        submitted = "<em>Matcha</em>"
        data = {**self.data, "drink_name": submitted, "notes": submitted}
        self.assertRedirects(self.client.post(self.create_url, data), self.list_url)
        visit = CheckIn.objects.get(user=self.explorer)
        self.assertEqual(visit.drink_name, submitted)
        self.assertEqual(visit.notes, submitted)
        for user in (self.explorer, self.owner):
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(self.list_url)
                self.assertContains(response, "&lt;em&gt;Matcha&lt;/em&gt;", count=2)
                self.assertNotContains(response, submitted)

    def test_unsupported_methods_do_not_mutate(self):
        visit = self.create_own()
        before = self.checkin_snapshot()
        self.assertEqual(self.client.head(self.list_url).status_code, 200)
        self.assertEqual(self.client.post(self.list_url, self.data).status_code, 405)
        for url in self.mutation_urls(visit.pk):
            for method in ("PUT", "PATCH", "DELETE"):
                with self.subTest(url=url, method=method):
                    self.assertEqual(self.client.generic(method, url).status_code, 405)
        self.assertEqual(self.checkin_snapshot(), before)
