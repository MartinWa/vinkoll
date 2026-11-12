import uuid

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import OperationalError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from .forms import AddBottlesForm, ConsumeForm, EditBottleForm, LocationForm, WineForm
from .models import Bottle, InventoryEvent, InventoryOperation, Location, Wine
from .services import (
    ChooseBottleGroup,
    StaleBottleError,
    add_bottles,
    bottle_groups,
    consume_bottle,
    edit_bottle,
)


def location_options(scope="all"):
    choices = Q(archived=False) | Q(bottles__state=Bottle.State.AVAILABLE)
    if scope.isdigit():
        choices |= Q(pk=scope)
    return Location.objects.filter(choices).distinct()


def location_scope(request):
    scope = request.GET.get("location", "all")
    if scope not in {"all", "unassigned"}:
        if not scope.isdigit() or not Location.objects.filter(pk=scope).exists():
            raise Http404
        scope = str(int(scope))
    return scope


def scoped(bottles, scope):
    if scope == "all":
        return bottles
    return bottles.filter(location_id=None if scope == "unassigned" else int(scope))


def cellar_url(scope):
    return reverse("cellar") + ("?" + urlencode({"location": scope}) if scope != "all" else "")


def saved(request, text, token=None):
    messages.success(request, text)
    messages.info(request, request.get_full_path(), extra_tags="completed-draft")
    if token:
        # The browser only clears the matching saved form after the server confirms success.
        messages.info(request, str(token), extra_tags="completed-operation")


def form_page(request, form, title, back_url, **extra):
    return render(
        request,
        "cellar/form.html",
        {
            "form": form,
            "title": title,
            "back_url": back_url,
            **extra,
        },
    )


def service_error(form, exc):
    if isinstance(exc, ValidationError):
        form.add_error(None, "; ".join(exc.messages))
    elif isinstance(exc, ObjectDoesNotExist):
        form.add_error(None, _("The selected record no longer exists. Review your choices."))
    else:
        form.add_error(None, _("The cellar is busy. Your input is preserved; try saving again."))


def cellar(request):
    scope = location_scope(request)
    bottles = scoped(Bottle.objects.filter(state=Bottle.State.AVAILABLE), scope)
    counts = dict(
        bottles.values("wine_id").annotate(total=Count("pk")).values_list("wine_id", "total")
    )
    wines = list(Wine.objects.filter(pk__in=counts))
    for wine in wines:
        wine.available_count = counts[wine.pk]
        wine.operation_token = uuid.uuid4()
    locations = list(location_options(scope))
    return render(
        request,
        "cellar/cellar.html",
        {
            "wines": wines,
            "bottle_count": sum(counts.values()),
            "locations": locations,
            "show_locations": len(locations) > 1,
            "scope": scope,
            "cellar_url": cellar_url(scope),
        },
    )


def wines(request):
    archived = request.GET.get("archived") == "1"
    return render(
        request,
        "cellar/wines.html",
        {
            "wines": Wine.objects.filter(archived=archived),
            "archived": archived,
        },
    )


@require_http_methods(["GET", "POST"])
def wine_create(request):
    form = WineForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        saved(request, _("Wine saved. Add bottles from Cellar when you are ready."))
        return redirect("wines")
    return form_page(request, form, _("Add wine"), reverse("wines"))


@require_http_methods(["GET", "POST"])
def wine_edit(request, pk):
    wine = get_object_or_404(Wine, pk=pk)
    form = WineForm(request.POST if request.method == "POST" else None, instance=wine)
    if request.method == "POST" and form.is_valid():
        form.save()
        saved(request, _("Wine saved."))
        return redirect("wines")
    return form_page(request, form, _("Edit wine"), reverse("wines"))


@require_http_methods(["GET", "POST"])
def wine_retire(request, pk):
    wine = get_object_or_404(Wine, pk=pk)
    used = wine.bottles.exists() or wine.reviews.exists()
    if request.method == "POST":
        action = request.POST.get("action")
        if action not in {"archive", "restore", "delete"}:
            return HttpResponseBadRequest(_("Choose a wine action."))
        with transaction.atomic():
            wine = get_object_or_404(Wine, pk=pk)
            used = wine.bottles.exists() or wine.reviews.exists()
            if action == "delete" and not used:
                wine.delete()
            else:
                wine.archived = action != "restore"
                wine.save(update_fields=["archived"])
        saved(request, _("Catalogue updated."))
        return redirect("wines")
    action = "restore" if wine.archived else "archive" if used else "delete"
    return render(request, "cellar/retire.html", {"wine": wine, "used": used, "action": action})


def wine_detail(request, pk):
    wine = get_object_or_404(Wine, pk=pk)
    scope = location_scope(request)
    available = wine.bottles.filter(state=Bottle.State.AVAILABLE).select_related("wine", "location")
    return render(
        request,
        "cellar/detail.html",
        {
            "wine": wine,
            "groups": bottle_groups(list(scoped(available, scope))),
            "total": available.count(),
            "scope": scope,
            "back_url": cellar_url(scope),
        },
    )


@require_http_methods(["GET", "POST"])
def bottle_add(request):
    scope = location_scope(request)
    form = AddBottlesForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            operation = add_bottles(actor=request.user, **form.service_data())
        except (ValidationError, ObjectDoesNotExist, OperationalError) as exc:
            service_error(form, exc)
        else:
            saved(request, _("Bottles added."), operation.token)
            return redirect(cellar_url(scope))
    return form_page(
        request,
        form,
        _("Add bottles"),
        cellar_url(scope),
        no_wines=not form.is_bound and not Wine.objects.filter(archived=False).exists(),
    )


@require_http_methods(["GET", "POST"])
def bottle_edit(request, pk):
    bottle = get_object_or_404(Bottle.objects.select_related("wine", "location"), pk=pk)
    scope = location_scope(request)
    back_url = reverse("wine_detail", args=[bottle.wine_id]) + "?" + urlencode({"location": scope})
    initial = {
        "location": bottle.location,
        "vintage_kind": bottle.vintage_kind,
        "vintage_year": bottle.vintage_year,
        "purchase_price": bottle.purchase_price,
        "version": bottle.version,
    }
    form = EditBottleForm(
        request.POST if request.method == "POST" else None,
        initial=initial,
        current_location=bottle.location_id,
    )
    stale_draft = False
    if request.method == "POST" and form.is_valid():
        try:
            operation = edit_bottle(actor=request.user, bottle_id=pk, **form.service_data())
        except (ValidationError, ObjectDoesNotExist, OperationalError) as exc:
            service_error(form, exc)
            stale_draft = isinstance(exc, StaleBottleError)
        else:
            saved(request, _("Bottle saved."), operation.token)
            return redirect(back_url)
    return form_page(
        request,
        form,
        _("Edit bottle"),
        back_url,
        subtitle=bottle.wine.name,
        stale_draft=stale_draft,
    )


@require_http_methods(["POST"])
def consume(request, pk):
    wine = get_object_or_404(Wine, pk=pk)
    scope = location_scope(request)
    form = ConsumeForm(request.POST)
    groups = []
    if form.is_valid():
        try:
            operation = consume_bottle(
                actor=request.user, wine_id=pk, location_scope=scope, **form.cleaned_data
            )
        except ChooseBottleGroup as exc:
            groups = exc.groups
        except (ValidationError, ObjectDoesNotExist, OperationalError) as exc:
            service_error(form, exc)
        else:
            saved(request, _("One bottle consumed."), operation.token)
            return redirect(cellar_url(scope))
    return render(
        request,
        "cellar/consume.html",
        {
            "form": form,
            "groups": groups,
            "wine": wine,
            "back_url": cellar_url(scope),
        },
    )


def timeline(request):
    operations = InventoryOperation.objects.select_related("actor").prefetch_related(
        Prefetch(
            "events",
            queryset=InventoryEvent.objects.select_related("bottle"),
        )
    )[:100]
    return render(request, "cellar/timeline.html", {"operations": operations})


@require_http_methods(["GET", "POST"])
def settings_page(request):
    form = LocationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        saved(request, _("Location saved."))
        return redirect("settings")
    return render(
        request, "cellar/settings.html", {"form": form, "locations": Location.objects.all()}
    )


@require_http_methods(["GET", "POST"])
def location_edit(request, pk):
    location = get_object_or_404(Location, pk=pk)
    form = LocationForm(request.POST if request.method == "POST" else None, instance=location)
    if request.method == "POST" and form.is_valid():
        form.save()
        saved(request, _("Location saved."))
        return redirect("settings")
    return form_page(request, form, _("Rename location"), reverse("settings"))
