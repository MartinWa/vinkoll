import uuid

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from core.models import CellarSettings

from .forms import (
    AddBottlesForm,
    ConsumeForm,
    EditBottleForm,
    LocationForm,
    RemoveBottleForm,
    RetireLocationForm,
    ReviewForm,
    StoreForm,
    WineForm,
)
from .images import delete_unused_wine, save_wine_form
from .markdown import all_wines_markdown, current_bottles_markdown
from .models import Bottle, InventoryEvent, InventoryOperation, Location, Wine, WineImage
from .search import card_data, search_wines
from .services import (
    ChooseBottleGroup,
    StaleBottleError,
    add_bottles,
    append_review,
    bottle_groups,
    consume_bottle,
    edit_bottle,
    remove_bottle,
    retire_location,
)


def location_options(scope="all"):
    choices = Q(archived=False) | Q(bottles__state=Bottle.State.AVAILABLE)
    if scope.isdigit():
        choices |= Q(pk=scope)
    return Location.objects.filter(choices).distinct()


def validate_scope(scope):
    if scope not in {"all", "unassigned"}:
        if (
            not scope.isascii()
            or not scope.isdecimal()
            or len(scope) > 19
            or not Location.objects.filter(pk=scope).exists()
        ):
            raise Http404
        scope = str(int(scope))
    return scope


def location_scope(request):
    return validate_scope(request.GET.get("location", "all"))


def scoped(bottles, scope):
    if scope == "all":
        return bottles
    return bottles.filter(location_id=None if scope == "unassigned" else int(scope))


def query_text(request):
    return request.GET.get("q", "").strip()[:200]


def with_query(url, values):
    values = {key: value for key, value in values.items() if value != ""}
    return url + ("?" + urlencode(values) if values else "")


def cellar_url(scope, query=""):
    return with_query(reverse("cellar"), {"location": scope if scope != "all" else "", "q": query})


def catalogue_url(request):
    return with_query(
        reverse("wines"),
        {
            "archived": "1" if request.GET.get("archived") == "1" else "",
            "q": query_text(request),
        },
    )


def context_suffix(request):
    values = {"location": location_scope(request), "q": query_text(request)}
    if request.GET.get("from") == "wines":
        values.update({"from": "wines", "archived": request.GET.get("archived", "")})
    return "?" + urlencode(values)


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
    query = query_text(request)
    bottles = scoped(Bottle.objects.filter(state=Bottle.State.AVAILABLE), scope)
    counts = dict(
        bottles.values("wine_id").annotate(total=Count("pk")).values_list("wine_id", "total")
    )
    wines = list(card_data(search_wines(Wine.objects.filter(pk__in=counts), query)))
    for wine in wines:
        wine.available_count = counts[wine.pk]
        wine.operation_token = uuid.uuid4()
    locations = list(location_options(scope))
    return render(
        request,
        "cellar/cellar.html",
        {
            "wines": wines,
            "bottle_count": sum(wine.available_count for wine in wines),
            "locations": locations,
            "show_locations": len(locations) > 1,
            "scope": scope,
            "cellar_url": cellar_url(scope, query),
            "clear_url": cellar_url(scope),
            "q": query,
            "context_suffix": context_suffix(request),
        },
    )


def wines(request):
    archived = request.GET.get("archived") == "1"
    return render(
        request,
        "cellar/wines.html",
        {
            "wines": card_data(
                search_wines(Wine.objects.filter(archived=archived), query_text(request))
            ),
            "archived": archived,
            "q": query_text(request),
            "clear_url": with_query(reverse("wines"), {"archived": "1" if archived else ""}),
            "active_url": with_query(reverse("wines"), {"q": query_text(request)}),
            "archived_url": with_query(
                reverse("wines"), {"q": query_text(request), "archived": "1"}
            ),
            "context_suffix": with_query(
                "", {"from": "wines", "q": query_text(request), "archived": "1" if archived else ""}
            ),
        },
    )


@require_http_methods(["GET", "POST"])
def wine_create(request):
    form = WineForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            save_wine_form(form)
        except (OSError, OperationalError, IntegrityError, ValidationError) as exc:
            wine_save_error(form, exc)
        else:
            saved(request, _("Wine saved. Add bottles from Cellar when you are ready."))
            return redirect(catalogue_url(request))
    return form_page(request, form, _("Add wine"), catalogue_url(request))


def wine_save_error(form, exc):
    if isinstance(exc, OSError):
        form.add_error(
            "photo", _("The photo could not be saved. Choose it again, or save without a photo.")
        )
    else:
        service_error(form, exc)


@require_http_methods(["GET", "POST"])
def wine_edit(request, pk):
    wine = get_object_or_404(Wine, pk=pk)
    form = WineForm(
        request.POST if request.method == "POST" else None, request.FILES or None, instance=wine
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_wine_form(form)
        except (OSError, OperationalError, IntegrityError, ValidationError) as exc:
            wine_save_error(form, exc)
        else:
            saved(request, _("Wine saved."))
            return redirect(catalogue_url(request))
    return form_page(
        request,
        form,
        _("Edit wine"),
        catalogue_url(request),
        wine=wine,
        context_suffix=context_suffix(request),
    )


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
                delete_unused_wine(wine)
            else:
                wine.archived = action != "restore"
                wine.save(update_fields=["archived"])
        saved(request, _("Catalogue updated."))
        return redirect(catalogue_url(request))
    action = "restore" if wine.archived else "archive" if used else "delete"
    return render(
        request,
        "cellar/retire.html",
        {"wine": wine, "used": used, "action": action, "back_url": catalogue_url(request)},
    )


def wine_detail(request, pk):
    wine = get_object_or_404(card_data(Wine.objects.all()), pk=pk)
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
            "back_url": catalogue_url(request)
            if request.GET.get("from") == "wines"
            else cellar_url(scope, query_text(request)),
            "from_wines": request.GET.get("from") == "wines",
            "context_suffix": context_suffix(request),
            "reviews": wine.reviews.select_related("author"),
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
            return redirect(cellar_url(scope, query_text(request)))
    return form_page(
        request,
        form,
        _("Add bottles"),
        cellar_url(scope, query_text(request)),
        no_wines=not form.is_bound and not Wine.objects.filter(archived=False).exists(),
    )


@require_http_methods(["GET", "POST"])
def bottle_edit(request, pk):
    bottle = get_object_or_404(Bottle.objects.select_related("wine", "location"), pk=pk)
    back_url = reverse("wine_detail", args=[bottle.wine_id]) + context_suffix(request)
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
            return redirect(cellar_url(scope, query_text(request)))
    return render(
        request,
        "cellar/consume.html",
        {
            "form": form,
            "groups": groups,
            "wine": wine,
            "back_url": cellar_url(scope, query_text(request)),
        },
    )


def timeline(request):
    wine_id = request.GET.get("wine", "")
    reason = request.GET.get("action", "")
    operations = InventoryOperation.objects.select_related(
        "actor", "review__wine"
    ).prefetch_related(
        Prefetch(
            "events",
            queryset=InventoryEvent.objects.select_related("bottle"),
        )
    )
    if wine_id:
        if (
            not wine_id.isascii()
            or not wine_id.isdecimal()
            or len(wine_id) > 19
            or int(wine_id) > 2**63 - 1
        ):
            raise Http404
        operations = operations.filter(
            Q(events__bottle__wine_id=wine_id) | Q(review__wine_id=wine_id)
        )
    if reason:
        if reason == "review":
            operations = operations.filter(kind="review")
        elif reason == "location":
            operations = operations.filter(kind="location")
        elif reason in InventoryEvent.Reason.values:
            operations = operations.filter(events__reason=reason)
        else:
            raise Http404
    return render(
        request,
        "cellar/timeline.html",
        {
            "operations": operations.distinct()[:100],
            "wines": Wine.objects.all(),
            "wine_filter": wine_id,
            "action_filter": reason,
            "actions": list(InventoryEvent.Reason.choices)
            + [("review", _("Review")), ("location", _("Location management"))],
        },
    )


def settings_context(**extra):
    preferences = CellarSettings.objects.filter(pk=1).first() or CellarSettings()
    return {
        "form": LocationForm(),
        "store_form": StoreForm(instance=preferences),
        "locations": Location.objects.all(),
        "export_locations": location_options(),
        "export_scope": "all",
        **extra,
    }


@require_http_methods(["GET", "POST"])
def settings_page(request):
    form = LocationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        saved(request, _("Location saved."))
        return redirect("settings")
    return render(request, "cellar/settings.html", settings_context(form=form))


@require_http_methods(["GET", "POST"])
def location_edit(request, pk):
    location = get_object_or_404(Location, pk=pk)
    form = LocationForm(request.POST if request.method == "POST" else None, instance=location)
    if request.method == "POST" and form.is_valid():
        form.save()
        saved(request, _("Location saved."))
        return redirect("settings")
    return form_page(request, form, _("Rename location"), reverse("settings"))


@require_http_methods(["GET", "POST"])
def bottle_remove(request, pk):
    bottle = get_object_or_404(Bottle.objects.select_related("wine", "location"), pk=pk)
    scope = location_scope(request)
    bottle_scope = str(bottle.location_id) if bottle.location_id else "unassigned"
    outside_scope = scope != "all" and bottle_scope != scope
    # Bound submissions must reach the service's version and scope checks.
    if request.method == "GET" and outside_scope:
        raise Http404
    reload_url = (
        with_query(request.path, {**request.GET.dict(), "location": bottle_scope})
        if outside_scope
        else request.get_full_path()
    )
    back_url = reverse("wine_detail", args=[bottle.wine_id]) + context_suffix(request)
    form = RemoveBottleForm(
        request.POST if request.method == "POST" else None, initial={"version": bottle.version}
    )
    stale_draft = False
    if request.method == "POST" and form.is_valid():
        try:
            operation = remove_bottle(
                actor=request.user, bottle_id=pk, location_scope=scope, **form.cleaned_data
            )
        except (ValidationError, ObjectDoesNotExist, OperationalError) as exc:
            service_error(form, exc)
            stale_draft = isinstance(exc, StaleBottleError)
        else:
            saved(request, _("Bottle removed. Its history is preserved."), operation.token)
            return redirect(back_url)
    return form_page(
        request,
        form,
        _("Remove bottle"),
        back_url,
        subtitle=bottle.wine.name,
        stale_draft=stale_draft,
        reload_url=reload_url,
    )


@require_http_methods(["GET", "POST"])
def review_add(request, pk):
    wine = get_object_or_404(Wine, pk=pk)
    back_url = reverse("wine_detail", args=[pk]) + context_suffix(request)
    form = ReviewForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            operation = append_review(actor=request.user, wine_id=pk, **form.cleaned_data)
        except (ValidationError, ObjectDoesNotExist, OperationalError) as exc:
            service_error(form, exc)
        else:
            saved(request, _("Review saved."), operation.token)
            return redirect(back_url)
    return form_page(request, form, _("Add review"), back_url, subtitle=wine.name)


@require_http_methods(["GET"])
def wine_image(request, pk, variant):
    if variant not in {"display", "thumbnail"}:
        raise Http404
    image = get_object_or_404(WineImage, pk=pk)
    try:
        file = getattr(image, variant).open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404 from exc
    return FileResponse(file, content_type="image/webp", filename=f"wine-{image.wine_id}.webp")


@require_http_methods(["GET", "POST"])
def location_retire(request, pk):
    location = get_object_or_404(Location, pk=pk)
    form = RetireLocationForm(request.POST if request.method == "POST" else None, location=location)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        target = data.pop("target")
        try:
            operation = retire_location(
                actor=request.user, location_id=pk, target_id=target.pk if target else None, **data
            )
        except (ValidationError, ObjectDoesNotExist, OperationalError) as exc:
            service_error(form, exc)
        else:
            saved(request, _("Location updated. Bottle history is preserved."), operation.token)
            return redirect("settings")
    return form_page(
        request, form, _("Manage location"), reverse("settings"), subtitle=location.name
    )


@require_http_methods(["POST"])
def store_save(request):
    preferences = CellarSettings.objects.filter(pk=1).first() or CellarSettings()
    form = StoreForm(request.POST, instance=preferences)
    if form.is_valid():
        form.save()
        saved(request, _("Preferred store saved."))
        return redirect("settings")
    return render(request, "cellar/settings.html", settings_context(store_form=form))


@require_http_methods(["POST"])
def markdown_generate(request, kind):
    if kind == "wines":
        extra = {"wines_markdown": all_wines_markdown()}
    elif kind == "bottles":
        scope = validate_scope(request.POST.get("location", "all"))
        extra = {
            "bottles_markdown": current_bottles_markdown(scope),
            "export_scope": scope,
            "export_locations": location_options(scope),
        }
    else:
        raise Http404
    return render(request, "cellar/settings.html", settings_context(**extra))
