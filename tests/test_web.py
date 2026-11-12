from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from cellar.forms import LocationForm, WineForm
from cellar.models import Bottle, InventoryEvent, InventoryOperation, Location, Wine
from cellar.services import add_bottles, append_review, edit_bottle, retire_location
from core.models import LoginAttempt

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "url", ["/", "/wines/", "/bottles/add/", "/timeline/", "/settings/", "/accounts/password/"]
)
def test_anonymous_features_require_login(client, url):
    response = client.get(url)
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/?next=")


def test_health_is_minimal_and_media_is_not_public(client):
    assert client.get("/healthz/").json() == {"status": "ok"}
    assert client.get("/media/private.jpg").status_code == 404


def test_login_rejects_unsafe_redirect(client, actor):
    response = client.post(
        "/accounts/login/?next=https://evil.invalid/",
        {
            "username": actor.username,
            "password": "test-password-for-fixtures",
            "next": "https://evil.invalid/",
        },
    )
    assert response.status_code == 302 and response.url == "/"


def test_login_throttles_and_window_expires(client, settings):
    settings.LOGIN_ATTEMPT_LIMIT = 2
    data = {"username": "missing", "password": "wrong"}
    assert client.post("/accounts/login/", data).status_code == 200
    assert client.post("/accounts/login/", data).status_code == 200
    assert client.post("/accounts/login/", data).status_code == 429
    LoginAttempt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.post("/accounts/login/", data).status_code == 200


def test_throttled_login_never_authenticates_blocked_passwords(client, actor, settings):
    settings.LOGIN_ATTEMPT_LIMIT = 1
    data = {"username": actor.username, "password": "wrong"}
    assert client.post("/accounts/login/", data).status_code == 200
    with patch("django.contrib.auth.forms.authenticate") as authenticate:
        for password in ("wrong", "test-password-for-fixtures"):
            response = client.post("/accounts/login/", {**data, "password": password})
            assert response.status_code == 429
            assert response["Retry-After"] == str(settings.LOGIN_ATTEMPT_WINDOW_SECONDS)
            assert not response.context["form"].is_bound
            assert not response.context["form"].errors
        authenticate.assert_not_called()
    assert "_auth_user_id" not in client.session


def test_logout_is_post_and_csrf_protected(actor):
    client = Client(enforce_csrf_checks=True)
    client.force_login(actor)
    assert client.get("/accounts/logout/").status_code == 405
    assert client.post("/accounts/logout/").status_code == 403
    client.get("/settings/")
    token = client.cookies["csrftoken"].value
    assert client.post("/accounts/logout/", {"csrfmiddlewaretoken": token}).status_code == 302
    assert client.get("/").status_code == 302


def test_expired_post_keeps_input_without_writing(actor, wine):
    client = Client(enforce_csrf_checks=True)
    client.force_login(actor)
    client.get("/bottles/add/")
    csrf = client.cookies["csrftoken"].value
    Session.objects.all().delete()
    response = client.post(
        "/bottles/add/",
        {
            "csrfmiddlewaretoken": csrf,
            "wine": wine.pk,
            "quantity": "2",
            "notes": "Keep this text",
        },
    )
    assert response.status_code == 401
    assert "Keep this text" in response.content.decode()
    assert "Cache-Control" in response and response["Cache-Control"] == "no-store"
    assert Bottle.objects.count() == 0
    hx = client.post("/bottles/add/", {"csrfmiddlewaretoken": csrf}, HTTP_HX_REQUEST="true")
    assert hx.status_code == 401 and hx["HX-Retarget"] == "body"


def test_manual_wine_and_bottle_add_are_separate(client, actor, location):
    client.force_login(actor)
    response = client.post(
        "/wines/add/",
        {
            "name": "Example White",
            "wine_type": "white",
            "volume_ml": 750,
            "grapes_text": "Riesling, Pinot blanc",
        },
    )
    assert response.status_code == 302
    wine = Wine.objects.get()
    assert wine.grapes == ["Riesling", "Pinot blanc"] and wine.article_number is None
    assert wine.bottles.count() == 0
    data = {
        "token": str(uuid4()),
        "wine": wine.pk,
        "location": location.pk,
        "quantity": 2,
        "vintage_kind": "unknown",
        "purchase_price": "0",
    }
    assert client.post("/bottles/add/", data).status_code == 302
    assert client.post("/bottles/add/", data).status_code == 302
    assert wine.bottles.count() == 2


def test_invalid_form_preserves_input(client, actor, wine):
    client.force_login(actor)
    response = client.post(
        "/bottles/add/",
        {
            "token": str(uuid4()),
            "wine": wine.pk,
            "quantity": -1,
            "vintage_kind": "year",
            "vintage_year": 2021,
            "purchase_price": "129.50",
        },
    )
    assert response.status_code == 200
    assert response.context["form"].data["purchase_price"] == "129.50"
    assert response.context["form"].errors and wine.bottles.count() == 0


def test_archive_keeps_cellar_stock_and_restore(client, actor, stocked, wine):
    client.force_login(actor)
    url = f"/wines/{wine.pk}/retire/"
    assert client.get(url).context["action"] == "archive"
    for _ in range(2):
        assert client.post(url, {"action": "archive"}).status_code == 302
    wine.refresh_from_db()
    assert wine.archived
    assert wine in client.get("/").context["wines"]
    assert wine not in client.get("/wines/").context["wines"]
    assert wine in client.get("/wines/?archived=1").context["wines"]
    assert client.get(url).context["action"] == "restore"
    for _ in range(2):
        assert client.post(url, {"action": "restore"}).status_code == 302
    wine.refresh_from_db()
    assert not wine.archived


def test_unused_profile_can_be_deleted(client, actor, wine):
    client.force_login(actor)
    url = f"/wines/{wine.pk}/retire/"
    assert client.get(url).context["action"] == "delete"
    assert client.post(url, {"action": "delete"}).status_code == 302
    assert not Wine.objects.exists()


@pytest.mark.parametrize("action", [None, "toggle", "unknown"])
def test_wine_retirement_requires_an_explicit_action(client, actor, stocked, wine, action):
    client.force_login(actor)
    data = {} if action is None else {"action": action}
    assert client.post(f"/wines/{wine.pk}/retire/", data).status_code == 400
    wine.refresh_from_db()
    assert not wine.archived and wine.bottles.count() == 2


@pytest.mark.parametrize("review_before_confirmation", [True, False])
def test_review_history_archives_a_zero_bottle_profile(
    client, actor, wine, review_before_confirmation
):
    client.force_login(actor)
    url = f"/wines/{wine.pk}/retire/"

    def review():
        return append_review(
            token=uuid4(),
            actor=actor,
            wine_id=wine.pk,
            date=timezone.localdate(),
            score=None,
            notes="Keep this tasting history",
        )

    if review_before_confirmation:
        operation = review()
    confirmation = client.get(url)
    assert confirmation.context["used"] == review_before_confirmation
    action = confirmation.context["action"]
    assert action == ("archive" if review_before_confirmation else "delete")
    if not review_before_confirmation:
        operation = review()
    for _ in range(2):
        assert client.post(url, {"action": action}).status_code == 302
    wine.refresh_from_db()
    assert wine.archived and wine.bottles.count() == 0
    assert wine.reviews.get().operation_id == operation.pk
    assert wine.reviews.get().notes == "Keep this tasting history"


def test_profile_edit_preserves_concurrent_archive(wine):
    form = WineForm({"name": "Edited", "wine_type": "red", "volume_ml": 750}, instance=wine)
    assert form.is_valid()
    Wine.objects.filter(pk=wine.pk).update(archived=True)
    form.save()
    wine.refresh_from_db()
    assert wine.archived and wine.name == "Edited"


@pytest.mark.parametrize("archived", [True, False])
def test_location_rename_preserves_concurrent_archive_or_restore(actor, location, archived):
    location.archived = not archived
    location.save(update_fields=["archived"])
    form = LocationForm({"name": "Renamed rack"}, instance=location)
    assert form.is_valid()
    retire_location(
        token=uuid4(),
        actor=actor,
        location_id=location.pk,
        action="archive" if archived else "restore",
    )
    form.save()
    location.refresh_from_db()
    assert location.archived == archived and location.name == "Renamed rack"


def test_stale_bottle_edit_offers_discard_and_reload(client, actor, stocked, wine, location):
    client.force_login(actor)
    bottle = wine.bottles.first()
    url = f"/bottles/{bottle.pk}/edit/?location={location.pk}"
    data = {
        "token": str(uuid4()),
        "version": 0,
        "location": location.pk,
        "vintage_kind": "year",
        "vintage_year": 2021,
        "purchase_price": "0",
    }
    edit_bottle(
        token=uuid4(),
        actor=actor,
        bottle_id=bottle.pk,
        version=0,
        location_id=location.pk,
        vintage_kind="year",
        vintage_year=2023,
        purchase_price=None,
    )
    response = client.post(url, data)
    assert response.status_code == 200 and response.context["stale_draft"]
    assert response.context["form"].data["purchase_price"] == "0"
    assert f'href="{url}" data-discard-draft' in response.content.decode()
    assert not InventoryOperation.objects.filter(token=data["token"]).exists()
    bottle.refresh_from_db()
    assert bottle.version == 1 and bottle.vintage_year == 2023 and bottle.purchase_price is None
    reloaded = client.get(url)
    assert reloaded.context["form"].initial["version"] == 1
    assert not reloaded.context["stale_draft"]
    assert client.post(url, {**data, "version": 1, "token": str(uuid4())}).status_code == 302
    bottle.refresh_from_db()
    assert bottle.version == 2 and bottle.purchase_price == 0


@pytest.mark.parametrize("action", ["consume", "move"])
def test_empty_archived_location_remains_valid_after_write_and_retry(
    client, actor, addition, wine, location, action
):
    client.force_login(actor)
    add_bottles(**{**addition, "quantity": 1})
    bottle = wine.bottles.get()
    retire_location(token=uuid4(), actor=actor, location_id=location.pk, action="archive")
    if action == "consume":
        url = f"/wines/{wine.pk}/consume/?location={location.pk}"
        data = {"token": str(uuid4()), "bottle_id": bottle.pk}
    else:
        target = Location.objects.create(name="Basement")
        url = f"/bottles/{bottle.pk}/edit/?location={location.pk}"
        data = {
            "token": str(uuid4()),
            "version": 0,
            "location": target.pk,
            "vintage_kind": "year",
            "vintage_year": 2021,
            "purchase_price": "129.50",
        }
    for _ in range(2):
        response = client.post(url, data, follow=True)
        assert response.status_code == 200
        assert response.context["scope"] == str(location.pk)
        assert response.redirect_chain
    assert InventoryOperation.objects.filter(token=data["token"]).get().events.count() == 1
    empty = client.get(f"/?location={location.pk}")
    assert empty.status_code == 200 and empty.context["bottle_count"] == 0
    assert location in empty.context["locations"]
    assert location not in client.get("/").context["locations"]
    assert client.get(f"/?location={location.pk + 1000}").status_code == 404


@pytest.mark.parametrize("archived_records", [("wine",), ("location",), ("wine", "location")])
def test_committed_addition_replays_after_archiving_choices(
    client, actor, wine, location, archived_records
):
    client.force_login(actor)
    data = {
        "token": str(uuid4()),
        "wine": wine.pk,
        "location": location.pk,
        "quantity": 2,
        "vintage_kind": "unknown",
        "purchase_price": "0",
    }
    assert client.post("/bottles/add/", data).status_code == 302
    if "wine" in archived_records:
        assert client.post(f"/wines/{wine.pk}/retire/", {"action": "archive"}).status_code == 302
    if "location" in archived_records:
        retire_location(token=uuid4(), actor=actor, location_id=location.pk, action="archive")
    assert client.post("/bottles/add/", data).status_code == 302
    new_addition = client.post("/bottles/add/", {**data, "token": str(uuid4())})
    assert new_addition.status_code == 200 and new_addition.context["form"].errors
    altered_replay = client.post("/bottles/add/", {**data, "quantity": 3})
    assert altered_replay.status_code == 200 and altered_replay.context["form"].non_field_errors()
    assert InventoryOperation.objects.filter(kind="add").count() == 1
    assert InventoryEvent.objects.filter(reason="add").count() == wine.bottles.count() == 2
    fresh_form = client.get("/bottles/add/").context["form"]
    if "wine" in archived_records:
        assert wine not in fresh_form.fields["wine"].queryset
    if "location" in archived_records:
        assert location not in fresh_form.fields["location"].queryset


def test_default_interface_is_swedish(client, actor):
    client.force_login(actor)
    page = client.get("/", HTTP_ACCEPT_LANGUAGE="en-US,en;q=0.9").content.decode()
    assert "Källare" in page and "Lägg till flaskor" in page


def test_expired_consumption_returns_to_a_get_page(client, actor, wine):
    client.force_login(actor)
    Session.objects.all().delete()
    response = client.post(f"/wines/{wine.pk}/consume/?location=all", {"token": str(uuid4())})
    assert response.status_code == 401
    assert response.context["login_url"] == "/accounts/login/?next=%2F%3Flocation%3Dall"


def test_two_accounts_share_inventory(client, django_user_model, stocked):
    other = django_user_model.objects.create_user("second-account")
    client.force_login(other)
    assert client.get("/").context["bottle_count"] == 2


def test_account_bootstrap_and_password_recovery(django_user_model):
    with patch(
        "core.management.commands.setup_account.getpass", return_value="valid-test-secret-91827"
    ):
        call_command("setup_account", "new-account")
    user = django_user_model.objects.get(username="new-account")
    assert user.check_password("valid-test-secret-91827") and not user.is_staff
    with patch(
        "core.management.commands.setup_account.getpass", return_value="recovery-secret-91827"
    ):
        call_command("setup_account", "new-account", reset=True)
    user.refresh_from_db()
    assert user.check_password("recovery-secret-91827")


def test_password_change_keeps_authenticated_session(client, actor):
    client.force_login(actor)
    response = client.post(
        "/accounts/password/",
        {
            "old_password": "test-password-for-fixtures",
            "new_password1": "replacement-secret-1928",
            "new_password2": "replacement-secret-1928",
        },
    )
    assert response.status_code == 302
    actor.refresh_from_db()
    assert actor.check_password("replacement-secret-1928")
    assert client.get("/").status_code == 200
