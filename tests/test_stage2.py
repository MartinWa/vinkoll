from datetime import date
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import translation

from cellar.markdown import all_wines_markdown, current_bottles_markdown
from cellar.models import Bottle, InventoryEvent, InventoryOperation, Location, Review, Wine
from cellar.search import card_data, search_wines
from cellar.services import (
    add_bottles,
    append_review,
    consume_bottle,
    edit_bottle,
    remove_bottle,
    retire_location,
)
from core.models import CellarSettings

pytestmark = pytest.mark.django_db


def review_data(wine, **extra):
    return {
        "token": str(uuid4()),
        "date": "2026-11-10",
        "score": "3.5",
        "notes": "Bright acidity",
        **extra,
    }


def test_local_search_combines_unicode_location_and_archive_filters(client, actor, addition, wine):
    wine.name = "Årgång från Östra slottet"
    wine.country = "Frankrike"
    wine.region = "Alsace"
    wine.grapes = ["Riesling"]
    wine.article_number = "001234"
    wine.short_article_number = "0012"
    wine.save()
    add_bottles(**addition)
    elsewhere = Location.objects.create(name="Basement")
    add_bottles(**{**addition, "token": uuid4(), "location_id": elsewhere.pk, "quantity": 3})
    empty = Wine.objects.create(name="Årgång without bottles")
    archived = Wine.objects.create(name="Årgång archived", archived=True)
    client.force_login(actor)
    for query in ["ÅRGÅNG", "ÖSTRA", "frankrike", "alsace", "RIESLING", "001234", "0012"]:
        response = client.get("/", {"q": query, "location": elsewhere.pk})
        assert [item.pk for item in response.context["wines"]] == [wine.pk]
        assert response.context["bottle_count"] == 3
        assert response.context["wines"][0].available_count == 3
    assert {item.pk for item in client.get("/wines/", {"q": "årgång"}).context["wines"]} == {
        wine.pk,
        empty.pk,
    }
    assert [
        item.pk for item in client.get("/wines/", {"q": "årgång", "archived": 1}).context["wines"]
    ] == [archived.pk]
    assert client.get("/", {"q": "no match"}).context["bottle_count"] == 0
    assert not client.get("/", {"q": "no match"}).context["wines"]


def test_search_index_refresh_uses_persisted_fields(wine):
    wine.name = "Östra"
    wine.save()
    wine.producer = "Unsaved producer"
    wine.name = "Årgång"
    wine.save(update_fields=["name"])
    assert search_wines(Wine.objects.all(), "årgång").exists()
    assert not search_wines(Wine.objects.all(), "unsaved").exists()
    assert not search_wines(Wine.objects.all(), "östra").exists()


def test_list_context_survives_details_edits_consumption_and_catalogue(
    client, actor, stocked, wine, location
):
    client.force_login(actor)
    context = {"q": "Example Red", "location": location.pk}
    detail = client.get(f"/wines/{wine.pk}/", context)
    assert parse_qs(urlsplit(detail.context["back_url"]).query) == {
        "q": ["Example Red"],
        "location": [str(location.pk)],
    }
    suffix = detail.context["context_suffix"]
    edit = client.get(f"/bottles/{wine.bottles.first().pk}/edit/{suffix}")
    assert edit.context["back_url"].endswith(suffix)
    consumed = client.post(f"/wines/{wine.pk}/consume/{suffix}", {"token": str(uuid4())})
    assert parse_qs(urlsplit(consumed.url).query) == {
        "q": ["Example Red"],
        "location": [str(location.pk)],
    }
    catalogue = client.get(f"/wines/{wine.pk}/", {"from": "wines", "q": "Example", "archived": "1"})
    assert catalogue.context["back_url"] == "/wines/?archived=1&q=Example"
    assert (
        client.get(f"/wines/{wine.pk}/edit/", {"q": "Example", "archived": "1"}).context["back_url"]
        == "/wines/?archived=1&q=Example"
    )


@pytest.mark.parametrize("score", ["0", "0.5", "1.2", "3.7", "5.5", "6"])
def test_half_star_validation_in_form_and_database(client, actor, wine, score):
    client.force_login(actor)
    response = client.post(f"/wines/{wine.pk}/reviews/add/", review_data(wine, score=score))
    assert response.context["form"].errors and Review.objects.count() == 0
    operation = InventoryOperation.objects.create(actor=actor, kind="review", fingerprint="fixture")
    with pytest.raises(IntegrityError), transaction.atomic():
        Review.objects.create(wine=wine, author=actor, operation=operation, score=score)


def test_reviews_append_retry_safely_keep_history_and_show_latest_unrated(client, actor, wine):
    client.force_login(actor)
    url = f"/wines/{wine.pk}/reviews/add/"
    data = review_data(wine)
    assert client.post(url, data).status_code == 302
    assert client.post(url, data).status_code == 302
    assert wine.reviews.count() == 1
    assert card_data(Wine.objects.all()).get().latest_score == Decimal("3.5")
    assert (
        client.post(url, review_data(wine, score="", notes="A note without a score")).status_code
        == 302
    )
    assert card_data(Wine.objects.all()).get().latest_score is None
    wine.notes = "General notes edited"
    wine.save()
    assert wine.reviews.count() == 2
    original = wine.reviews.last()
    assert original.score == Decimal("3.5") and original.notes == "Bright acidity"
    timeline = client.get("/timeline/", {"wine": wine.pk, "action": "review"})
    assert len(timeline.context["operations"]) == 2
    assert "Bright acidity" in timeline.content.decode()
    assert client.post(url, review_data(wine, score="", notes="")).context["form"].errors
    assert client.get(f"/wines/{wine.pk}/retire/").context["action"] == "archive"


@pytest.mark.parametrize("reason", ["gift", "loss", "adjustment"])
def test_removal_is_separate_from_consumption_and_safe_to_retry(
    client, actor, stocked, wine, reason
):
    client.force_login(actor)
    bottle = wine.bottles.first()
    data = {"token": str(uuid4()), "version": bottle.version, "reason": reason}
    url = f"/bottles/{bottle.pk}/remove/"
    assert client.post(url, data).status_code == 302
    assert client.post(url, data).status_code == 302
    bottle.refresh_from_db()
    assert bottle.state == "removed" and wine.bottles.filter(state="available").count() == 1
    assert InventoryEvent.objects.filter(reason=reason).count() == 1
    assert not InventoryEvent.objects.filter(reason="consume").exists()
    assert client.post(url, {**data, "token": str(uuid4())}).context["stale_draft"]
    assert client.get("/timeline/", {"action": reason}).context["operations"].count() == 1


@pytest.mark.parametrize("change", ["move", "reassign", "unassign", "assign"])
def test_stale_scoped_removal_preserves_input_and_reloads_current_location(
    client, actor, addition, wine, location, django_user_model, change
):
    client.force_login(actor)
    initial_location = None if change == "assign" else location.pk
    add_bottles(**{**addition, "quantity": 1, "location_id": initial_location})
    bottle = wine.bottles.get()
    scope = str(initial_location) if initial_location else "unassigned"
    url = f"/bottles/{bottle.pk}/remove/?location={scope}&q=Example"
    opened = client.get(url)
    assert opened.status_code == 200
    data = {
        "token": str(uuid4()),
        "version": opened.context["form"].initial["version"],
        "reason": "gift",
    }
    other_actor = django_user_model.objects.create_user("other-cellar-user")
    target = None if change == "unassign" else Location.objects.create(name="New rack")
    target_id = target.pk if target else None
    if change == "reassign":
        retire_location(
            token=uuid4(),
            actor=other_actor,
            location_id=location.pk,
            action="reassign",
            target_id=target_id,
        )
    else:
        edit_bottle(
            token=uuid4(),
            actor=other_actor,
            bottle_id=bottle.pk,
            version=bottle.version,
            location_id=target_id,
            vintage_kind=bottle.vintage_kind,
            vintage_year=bottle.vintage_year,
            purchase_price=bottle.purchase_price,
        )

    response = client.post(url, data)
    assert response.status_code == 200 and response.context["stale_draft"]
    form = response.context["form"]
    assert form.non_field_errors()
    assert form.data["token"] == data["token"] and form.data["reason"] == "gift"
    assert form.data["version"] == str(data["version"])
    assert not InventoryOperation.objects.filter(token=data["token"]).exists()
    bottle.refresh_from_db()
    assert bottle.state == "available" and bottle.version == 1
    assert bottle.location_id == target_id
    assert client.get(url).status_code == 404

    reload_scope = str(target_id) if target_id else "unassigned"
    reload_url = f"/bottles/{bottle.pk}/remove/?location={reload_scope}&q=Example"
    assert f'href="{reload_url.replace("&", "&amp;")}" data-discard-draft' in (
        response.content.decode()
    )
    reloaded = client.get(reload_url)
    assert reloaded.status_code == 200 and not reloaded.context["stale_draft"]
    assert reloaded.context["form"].initial["version"] == 1
    assert client.post(reload_url, {**data, "token": str(uuid4()), "version": 1}).status_code == 302
    bottle.refresh_from_db()
    assert bottle.state == "removed" and bottle.version == 2


def test_scoped_removal_still_rejects_a_current_bottle_outside_the_location(
    client, actor, stocked, wine
):
    client.force_login(actor)
    bottle = wine.bottles.first()
    other_location = Location.objects.create(name="Other rack")
    url = f"/bottles/{bottle.pk}/remove/?location={other_location.pk}"
    data = {"token": str(uuid4()), "version": bottle.version, "reason": "gift"}
    assert client.get(url).status_code == 404
    response = client.post(url, data)
    assert response.status_code == 200 and response.context["form"].non_field_errors()
    assert not response.context["stale_draft"]
    assert not InventoryOperation.objects.filter(token=data["token"]).exists()
    bottle.refresh_from_db()
    assert bottle.state == "available" and bottle.version == 0


def test_removal_and_reassignment_failures_roll_back(stocked, actor, wine, location):
    bottle = wine.bottles.first()
    with patch("cellar.services.InventoryEvent.objects.create", side_effect=RuntimeError("disk")):
        with pytest.raises(RuntimeError):
            remove_bottle(token=uuid4(), actor=actor, bottle_id=bottle.pk, version=0, reason="gift")
        with pytest.raises(RuntimeError):
            retire_location(token=uuid4(), actor=actor, location_id=location.pk, action="reassign")
    bottle.refresh_from_db()
    location.refresh_from_db()
    assert bottle.state == "available" and bottle.location_id == location.pk
    assert not location.archived
    assert InventoryOperation.objects.count() == 1


def test_location_reassignment_preserves_historical_references_and_replays(
    client, actor, addition, wine, location
):
    add_bottles(**{**addition, "quantity": 3})
    consumed = wine.bottles.first()
    consume_bottle(token=uuid4(), actor=actor, wine_id=wine.pk, bottle_id=consumed.pk)
    target = Location.objects.create(name="New rack")
    client.force_login(actor)
    url = f"/settings/locations/{location.pk}/retire/"
    data = {"token": str(uuid4()), "action": "reassign", "target": target.pk}
    assert client.post(url, data).status_code == 302
    assert client.post(url, data).status_code == 302
    consumed.refresh_from_db()
    location.refresh_from_db()
    assert consumed.location_id == location.pk and location.archived
    assert wine.bottles.filter(state="available", location=target).count() == 2
    events = InventoryEvent.objects.filter(reason="move")
    assert events.count() == 2
    assert all(
        event.previous["location_name"] == "Wine rack"
        and event.current["location_name"] == "New rack"
        for event in events
    )
    assert client.get("/timeline/", {"action": "move"}).context["operations"].count() == 1
    assert client.post(url, {"token": str(uuid4()), "action": "restore"}).status_code == 302
    location.refresh_from_db()
    assert not location.archived


def test_cellar_filter_visibility_and_export_scope_are_independent(client, actor, location):
    client.force_login(actor)
    assert not client.get("/").context["show_locations"]
    assert 'id="export-location"' in client.get("/settings/").content.decode()
    Location.objects.create(name="Second location")
    assert client.get("/").context["show_locations"]


def test_shared_preferred_store_preserves_leading_zeroes(client, actor):
    client.force_login(actor)
    assert (
        client.post(
            "/settings/store/", {"store_id": "0012", "store_name": "Example store"}
        ).status_code
        == 302
    )
    assert CellarSettings.objects.get().store_id == "0012"
    assert (
        client.post("/settings/store/", {"store_id": "invalid", "store_name": "New name"})
        .context["store_form"]
        .errors
    )
    assert CellarSettings.objects.get().store_name == "Example store"


def test_markdown_catalogue_and_inventory_scopes_include_only_correct_records(
    client, actor, addition, wine, location
):
    wine.notes = "First line\nSecond line <script>"
    wine.grapes = ["Riesling"]
    wine.save()
    add_bottles(**{**addition, "quantity": 3})
    consume_bottle(token=uuid4(), actor=actor, wine_id=wine.pk)
    remove_bottle(
        token=uuid4(),
        actor=actor,
        bottle_id=wine.bottles.filter(state="available").first().pk,
        version=0,
        reason="loss",
    )
    add_bottles(
        **{
            **addition,
            "token": uuid4(),
            "location_id": None,
            "quantity": 2,
            "vintage_kind": "non_vintage",
            "vintage_year": None,
        }
    )
    empty_location = Location.objects.create(name="Empty shelf")
    empty_wine = Wine.objects.create(name="Empty profile")
    append_review(
        token=uuid4(),
        actor=actor,
        wine_id=wine.pk,
        date=date(2026, 11, 10),
        score=Decimal("3.5"),
        notes="Review one\nReview two",
    )
    append_review(
        token=uuid4(),
        actor=actor,
        wine_id=wine.pk,
        date=date(2026, 11, 11),
        score=None,
        notes="Unrated review",
    )
    wine.archived = True
    wine.save()
    retire_location(token=uuid4(), actor=actor, location_id=location.pk, action="archive")
    with (
        translation.override("en"),
        patch("socket.socket.connect", side_effect=AssertionError("No external service")),
    ):
        catalogue = all_wines_markdown()
        assert empty_wine.name in catalogue and "[Archived]" in catalogue
        assert "Latest score: Unrated" in catalogue and "3.5/5" in catalogue
        assert "2026-11-10" in catalogue and "2026-11-11" in catalogue
        assert "    First line\n    Second line <script>" in catalogue
        assert "    Review one\n    Review two" in catalogue
        for scope, total in [
            ("all", 3),
            (str(location.pk), 1),
            ("unassigned", 2),
            (str(empty_location.pk), 0),
        ]:
            output = current_bottles_markdown(scope)
            assert f"Available bottles in this scope: {total}" in output
            assert "Europe/Stockholm" in output
            assert "Empty profile" not in output
            if scope == "unassigned":
                assert "Non\\-vintage" in output and "Wine rack" not in output
            if total == 0:
                assert "0 bottles available." in output
        assert "2021" in current_bottles_markdown(str(location.pk))
        assert all_wines_markdown().splitlines()[4:] == catalogue.splitlines()[4:]
    client.force_login(actor)
    all_response = client.post(
        "/settings/markdown/wines/?q=missing&archived=0", {"location": empty_location.pk}
    )
    assert "Empty profile" in all_response.context["wines_markdown"]
    bottle_response = client.post("/settings/markdown/bottles/", {"location": empty_location.pk})
    assert "0 bottles available." in bottle_response.context["bottles_markdown"]
    assert "&lt;script&gt;" in all_response.content.decode()


def test_markdown_groups_by_identity_vintage_size_and_location(wine):
    # Equal names never merge different profiles, and prices do not split export groups.
    other = Wine.objects.create(name=wine.name, producer=wine.producer, volume_ml=375)
    Bottle.objects.create(wine=wine, purchase_price=0)
    Bottle.objects.create(wine=wine, purchase_price=100)
    Bottle.objects.create(wine=other)
    output = current_bottles_markdown()
    assert "Available bottles in this scope: 3" in output
    assert "750 ml | Unassigned | 2 |" in output
    assert "375 ml | Unassigned | 1 |" in output


@pytest.mark.parametrize(
    "url", ["/settings/markdown/wines/", "/settings/markdown/bottles/", "/settings/store/"]
)
def test_new_post_endpoints_are_private_csrf_protected_and_expire_to_settings(client, actor, url):
    from django.test import Client

    assert client.post(url).status_code == 401
    assert client.post(url).context["login_url"] == "/accounts/login/?next=%2Fsettings%2F"
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(actor)
    assert csrf_client.post(url).status_code == 403
    assert csrf_client.get(url).status_code == 405


def test_invalid_scopes_and_filters_never_crash(client, actor):
    client.force_login(actor)
    assert client.get("/", {"location": "bogus"}).status_code == 404
    assert client.post("/settings/markdown/bottles/", {"location": "999999999"}).status_code == 404
    assert client.get("/timeline/", {"action": "bogus"}).status_code == 404
    assert client.get("/timeline/", {"wine": "bogus"}).status_code == 404


@pytest.mark.parametrize(
    ("wine_id", "status"),
    [
        ("9223372036854775807", 200),
        ("9223372036854775808", 404),
        ("9999999999999999999", 404),
        ("10000000000000000000", 404),
    ],
)
def test_timeline_wine_filter_enforces_database_integer_range(
    client, actor, settings, wine_id, status
):
    settings.DEBUG = False
    client.force_login(actor)
    response = client.get("/timeline/", {"wine": wine_id})
    assert response.status_code == status
    if status == 200:
        assert not list(response.context["operations"])
