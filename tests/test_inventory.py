from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, transaction
from django.db.models.deletion import ProtectedError

from cellar.models import Bottle, InventoryEvent, InventoryOperation, Location
from cellar.services import (
    ChooseBottleGroup,
    InventoryError,
    add_bottles,
    consume_bottle,
    edit_bottle,
)

pytestmark = pytest.mark.django_db


def test_profile_creation_has_no_inventory(wine):
    assert wine.bottles.count() == 0


def test_addition_creates_individual_bottles_and_history(addition):
    operation = add_bottles(**addition)
    bottles = list(Bottle.objects.all())
    assert len(bottles) == 2
    assert bottles[0].pk != bottles[1].pk
    assert all(b.vintage_year == 2021 and b.purchase_price == Decimal("129.50") for b in bottles)
    assert {b.location_id for b in bottles} == {addition["location_id"]}
    assert operation.events.count() == 2
    assert {e.current["vintage_year"] for e in operation.events.all()} == {2021}


def test_lost_response_retry_returns_original_operation(addition):
    first = add_bottles(**addition)
    assert add_bottles(**addition).pk == first.pk
    assert Bottle.objects.count() == 2
    assert InventoryEvent.objects.count() == 2


def test_token_cannot_be_reused_for_other_payload_or_actor(addition, django_user_model):
    add_bottles(**addition)
    with pytest.raises(InventoryError):
        add_bottles(**{**addition, "quantity": 3})
    other = django_user_model.objects.create_user("another")
    with pytest.raises(InventoryError):
        add_bottles(**{**addition, "actor": other})
    assert Bottle.objects.count() == 2


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, 1001])
def test_invalid_quantity_never_writes(addition, quantity):
    with pytest.raises(InventoryError):
        add_bottles(**{**addition, "quantity": quantity})
    assert Bottle.objects.count() == InventoryOperation.objects.count() == 0


@pytest.mark.parametrize(
    "kind,year,price",
    [
        ("year", None, None),
        ("unknown", 2020, None),
        ("non_vintage", 2020, None),
        ("unknown", None, Decimal("-0.01")),
    ],
)
def test_invalid_bottle_details_never_write(addition, kind, year, price):
    with pytest.raises(ValidationError):
        add_bottles(
            **{**addition, "vintage_kind": kind, "vintage_year": year, "purchase_price": price}
        )
    assert Bottle.objects.count() == 0


def test_zero_and_unknown_prices_are_distinct(addition):
    add_bottles(**{**addition, "purchase_price": Decimal("0"), "quantity": 1})
    add_bottles(**{**addition, "token": uuid4(), "purchase_price": None, "quantity": 1})
    assert list(Bottle.objects.values_list("purchase_price", flat=True)) == [Decimal("0"), None]


def test_history_failure_rolls_back_all_bottles(addition):
    with patch("cellar.services.InventoryEvent.objects.create", side_effect=RuntimeError("disk")):
        with pytest.raises(RuntimeError):
            add_bottles(**addition)
    assert Bottle.objects.count() == InventoryOperation.objects.count() == 0


def test_consumption_retry_never_consumes_second_bottle(stocked, actor, wine):
    args = {"token": uuid4(), "actor": actor, "wine_id": wine.pk}
    first = consume_bottle(**args)
    assert consume_bottle(**args).pk == first.pk
    assert wine.bottles.filter(state=Bottle.State.AVAILABLE).count() == 1
    assert wine.bottles.filter(state=Bottle.State.CONSUMED).count() == 1
    assert InventoryEvent.objects.filter(reason="consume").count() == 1


def test_consumed_bottle_cannot_be_consumed_again(stocked, actor, wine):
    bottle = wine.bottles.first()
    consume_bottle(token=uuid4(), actor=actor, wine_id=wine.pk, bottle_id=bottle.pk)
    with pytest.raises(InventoryError):
        consume_bottle(token=uuid4(), actor=actor, wine_id=wine.pk, bottle_id=bottle.pk)


def test_different_vintages_require_group_selection(addition, actor, wine):
    add_bottles(**addition)
    add_bottles(**{**addition, "token": uuid4(), "vintage_year": 2023})
    with pytest.raises(ChooseBottleGroup) as exc:
        consume_bottle(token=uuid4(), actor=actor, wine_id=wine.pk)
    assert {group["bottle"].vintage_year for group in exc.value.groups} == {2021, 2023}
    assert wine.bottles.filter(state=Bottle.State.AVAILABLE).count() == 4


def test_consumption_respects_location_filter(addition, actor, wine):
    add_bottles(**addition)
    other = Location.objects.create(name="Basement")
    add_bottles(**{**addition, "token": uuid4(), "location_id": other.pk})
    selected = wine.bottles.filter(location=other).first()
    with pytest.raises(InventoryError):
        consume_bottle(
            token=uuid4(),
            actor=actor,
            wine_id=wine.pk,
            bottle_id=selected.pk,
            location_scope=str(addition["location_id"]),
        )
    consume_bottle(
        token=uuid4(), actor=actor, wine_id=wine.pk, location_scope=str(addition["location_id"])
    )
    assert wine.bottles.filter(location=other, state=Bottle.State.AVAILABLE).count() == 2


def test_edit_changes_one_bottle_and_move_preserves_count(stocked, actor, wine):
    first, second = list(wine.bottles.all())
    other = Location.objects.create(name="Basement")
    args = {
        "token": uuid4(),
        "actor": actor,
        "bottle_id": first.pk,
        "version": 0,
        "location_id": other.pk,
        "vintage_kind": "year",
        "vintage_year": 2023,
        "purchase_price": Decimal("0.00"),
    }
    operation = edit_bottle(**args)
    assert edit_bottle(**args).pk == operation.pk
    second.refresh_from_db()
    first.refresh_from_db()
    assert (first.vintage_year, first.location_id, first.purchase_price) == (2023, other.pk, 0)
    assert (second.vintage_year, second.location_id) == (
        2021,
        stocked.events.first().current["location_id"],
    )
    assert wine.bottles.filter(state=Bottle.State.AVAILABLE).count() == 2
    assert set(operation.events.values_list("reason", flat=True)) == {"move", "correct"}
    assert operation.events.first().previous["vintage_year"] == 2021
    with pytest.raises(InventoryError):
        edit_bottle(**{**args, "token": uuid4()})


def test_history_protects_bottle_wine_location(stocked, wine, location):
    with pytest.raises(ProtectedError):
        wine.delete()
    with pytest.raises(ProtectedError):
        location.delete()
    with pytest.raises(ProtectedError):
        wine.bottles.first().delete()


def test_archived_profile_keeps_stock_but_refuses_additions(stocked, addition, wine):
    wine.archived = True
    wine.save()
    with pytest.raises(InventoryError):
        add_bottles(**{**addition, "token": uuid4()})
    assert wine.bottles.filter(state=Bottle.State.AVAILABLE).count() == 2
    # A replay remains successful even if the profile was later archived.
    assert add_bottles(**addition).pk == stocked.pk


@pytest.mark.parametrize(
    "values",
    [
        {"vintage_kind": "year", "vintage_year": None},
        {"vintage_kind": "unknown", "vintage_year": 2020},
        {"vintage_kind": "other"},
        {"purchase_price": Decimal("-1")},
        {"state": "other"},
    ],
)
def test_database_constraints_reject_invalid_bottles(wine, values):
    with pytest.raises(IntegrityError), transaction.atomic():
        Bottle.objects.create(wine=wine, **values)


@pytest.mark.django_db(transaction=True)
def test_concurrent_last_bottle_consumption_has_one_winner(addition, actor, wine):
    add_bottles(**{**addition, "quantity": 1})
    barrier = Barrier(2)

    def consume():
        try:
            barrier.wait(timeout=5)
            consume_bottle(token=uuid4(), actor=actor, wine_id=wine.pk)
            return "consumed"
        except InventoryError:
            return "unavailable"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(results) == ["consumed", "unavailable"]
    assert InventoryEvent.objects.filter(reason="consume").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_retry_of_same_addition_creates_once(addition):
    barrier = Barrier(2)

    def add():
        try:
            barrier.wait(timeout=5)
            return add_bottles(**addition).pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: add(), range(2)))
    assert results[0] == results[1]
    assert Bottle.objects.count() == InventoryEvent.objects.count() == 2
