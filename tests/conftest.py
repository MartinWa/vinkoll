from decimal import Decimal
from uuid import uuid4

import pytest

from cellar.models import Bottle, Location, Wine
from cellar.services import add_bottles


@pytest.fixture
def actor(django_user_model):
    return django_user_model.objects.create_user(
        "cellar-user", password="test-password-for-fixtures"
    )


@pytest.fixture
def wine():
    return Wine.objects.create(name="Example Red", producer="Example Estate")


@pytest.fixture
def location():
    return Location.objects.create(name="Wine rack")


@pytest.fixture
def addition(actor, wine, location):
    return {
        "token": uuid4(),
        "actor": actor,
        "wine_id": wine.pk,
        "location_id": location.pk,
        "quantity": 2,
        "vintage_kind": Bottle.Vintage.YEAR,
        "vintage_year": 2021,
        "purchase_price": Decimal("129.50"),
    }


@pytest.fixture
def stocked(addition):
    return add_bottles(**addition)
