
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from checkins.models import Cafe, CheckIn
from .forms import ProfileForm, RegistrationForm
from .models import User


class RoleLoginView(LoginView):
    template_name = "login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse("dashboard")


@login_required
def dashboard(request):
    if request.user.role == User.Role.EXPLORER:
        return redirect("explorer_dashboard")

    if request.user.role == User.Role.OWNER:
        return redirect("owner_dashboard")

    raise PermissionDenied


@login_required
def explorer_dashboard(request):
    if request.user.role != User.Role.EXPLORER:
        raise PermissionDenied

    mine = CheckIn.objects.filter(user=request.user)

    return render(request, "explorer_dashboard.html", {
        "title": "Explorer dashboard",
        "recent": mine.select_related("cafe")[:3],
        "total": mine.count(),
        "cafes": mine.values("cafe").distinct().count(),
    })


@login_required
def owner_dashboard(request):
    if request.user.role != User.Role.OWNER:
        raise PermissionDenied

    cafes = Cafe.objects.filter(owner=request.user).annotate(
        checkin_count=Count("checkins"),
        avg_rating=Avg("checkins__rating"),
    )

    return render(request, "owner_dashboard.html", {
        "title": "Café Owner dashboard",
        "cafes": cafes,
    })


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(
        request.POST if request.method == "POST" else None,
        instance=request.user,
    )

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                form.save()

        except IntegrityError:
            if not User.objects.filter(
                email__iexact=form.cleaned_data["email"]
            ).exclude(pk=request.user.pk).exists():
                raise

            form.add_error(
                "email",
                "This email address is already registered.",
            )

        else:
            messages.success(request, "Your profile has been updated.")
            return redirect("profile")

    return render(request, "profile.html", {
        "form": form,
        "title": "My profile",
    })


@require_http_methods(["GET", "POST"])
def register(request):
    form = RegistrationForm(
        request.POST if request.method == "POST" else None
    )

    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()

        except IntegrityError as error:
            field = {
                "accounts_email_ci_unique": "email",
                "accounts_username_ci_unique": "username",
                "accounts_user_username_key": "username",
            }.get(error.__cause__.diag.constraint_name)

            if field is None:
                raise

            form.add_error(
                field,
                f"This {field} is already registered.",
            )

        else:
            messages.success(
                request,
                "Your Explorer account was created.",
            )
            return redirect("register")

    return render(request, "form.html", {
        "form": form,
        "title": "Create an Explorer account",
    })
