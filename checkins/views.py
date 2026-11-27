from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import User

from .forms import CheckInForm
from .models import CheckIn


def explorer_required(view):
    """Login is enforced first; then only Explorers may continue (others get HTTP 403)."""
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.role != User.Role.EXPLORER:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper


@login_required
@require_http_methods(["GET", "HEAD"])
def checkin_list(request):
    """Explorers see their own check-ins; Café Owners see check-ins at their own cafés (read-only)."""
    if request.user.role == User.Role.OWNER:
        checkins = CheckIn.objects.filter(cafe__owner=request.user).select_related("cafe", "user")
        stats = checkins.aggregate(total=Count("id"), average=Avg("rating"))
        template = "checkins/owner_list.html"
    elif request.user.role == User.Role.EXPLORER:
        checkins = CheckIn.objects.filter(user=request.user).select_related("cafe")
        stats = checkins.aggregate(total=Count("id"), cafes=Count("cafe", distinct=True))
        template = "checkins/list.html"
    else:
        raise PermissionDenied
    return render(request, template, {"checkins": checkins, "stats": stats, "title": "Check-ins"})


def _save_checkin(request, form, success_message):
    if form.is_valid():
        try:
            with transaction.atomic():
                form.instance.user = request.user  # always the signed-in user, never client data
                form.save()
        except IntegrityError as error:
            if getattr(getattr(error.__cause__, "diag", None), "constraint_name", None) != "checkins_one_per_cafe_per_day":
                raise
            form.add_error(None, "You already checked in at this café on that date.")
        else:
            messages.success(request, success_message, extra_tags="Saved")
            return True
    return False


@explorer_required
@require_http_methods(["GET", "POST"])
def checkin_create(request):
    form = CheckInForm(request.POST if request.method == "POST" else None, user=request.user)
    if request.method == "POST" and _save_checkin(request, form, "Your check-in was added to your passport."):
        return redirect("checkin_list")
    return render(request, "checkins/form.html", {"form": form, "title": "New check-in", "editing": False})


@explorer_required
@require_http_methods(["GET", "POST"])
def checkin_update(request, pk):
    checkin = get_object_or_404(CheckIn, pk=pk, user=request.user)  # others' records are a 404
    form = CheckInForm(request.POST if request.method == "POST" else None, instance=checkin, user=request.user)
    if request.method == "POST" and _save_checkin(request, form, "Your check-in was updated."):
        return redirect("checkin_list")
    return render(request, "checkins/form.html",
                  {"form": form, "title": "Edit check-in", "editing": True, "checkin": checkin})


@explorer_required
@require_http_methods(["GET", "POST"])
def checkin_delete(request, pk):
    checkin = get_object_or_404(CheckIn, pk=pk, user=request.user)
    if request.method == "POST":
        checkin.delete()
        messages.success(request, "The check-in was removed from your passport.", extra_tags="Removed")
        return redirect("checkin_list")
    return render(request, "checkins/confirm_delete.html", {"checkin": checkin, "title": "Delete check-in"})
