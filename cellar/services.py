"""Short, atomic inventory writes. SQLite IMMEDIATE serializes competing writers.

Operation receipts are permanent: a lost-response retry returns the same operation.
Tokens are bound to the actor and canonical input, so they cannot be reused for another change.
"""

import hashlib
import json
from itertools import groupby

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from .models import Bottle, InventoryEvent, InventoryOperation, Location, Review, Wine


class InventoryError(ValidationError):
    pass


class StaleBottleError(InventoryError):
    pass


class ChooseBottleGroup(InventoryError):
    def __init__(self, groups):
        self.groups = groups
        super().__init__(_("Choose which bottle group to consume from."))


def bottle_groups(bottles):
    def key(bottle):
        return (
            bottle.vintage_kind,
            bottle.vintage_year or 0,
            bottle.location_id or 0,
            str(bottle.purchase_price) if bottle.purchase_price is not None else "",
        )

    return [
        {"bottle": rows[0], "bottles": rows, "count": len(rows)}
        for _, items in groupby(sorted(bottles, key=key), key=key)
        if (rows := list(items))
    ]


def snapshot(bottle):
    return {
        "wine_id": bottle.wine_id,
        "wine_name": bottle.wine.name,
        "vintage_kind": bottle.vintage_kind,
        "vintage_year": bottle.vintage_year,
        "location_id": bottle.location_id,
        "location_name": bottle.location.name if bottle.location else None,
        "purchase_price": str(bottle.purchase_price) if bottle.purchase_price is not None else None,
        "state": bottle.state,
        "version": bottle.version,
    }


def receipt(token, actor, kind, payload):
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    existing = InventoryOperation.objects.filter(token=token).first()
    if existing and (
        existing.actor_id != actor.pk
        or existing.kind != kind
        or existing.fingerprint != fingerprint
    ):
        raise InventoryError(_("This operation token has already been used for another change."))
    return existing, fingerprint


def new_operation(token, actor, kind, fingerprint):
    if not actor.is_authenticated or not actor.is_active:
        raise InventoryError(_("Sign in to change the cellar."))
    return InventoryOperation.objects.create(
        token=token, actor=actor, kind=kind, fingerprint=fingerprint
    )


def chosen_location(location_id, previous_id=None):
    if location_id is None:
        return None
    location = Location.objects.get(pk=location_id)
    if location.archived and location.pk != previous_id:
        raise InventoryError(_("Choose an active location."))
    return location


@transaction.atomic
def add_bottles(
    *, token, actor, wine_id, location_id, quantity, vintage_kind, vintage_year, purchase_price
):
    payload = {
        "wine": wine_id,
        "location": location_id,
        "quantity": quantity,
        "vintage_kind": vintage_kind,
        "vintage_year": vintage_year,
        "price": purchase_price,
    }
    existing, fingerprint = receipt(token, actor, "add", payload)
    if existing:
        return existing
    if type(quantity) is not int or not 1 <= quantity <= 1000:
        raise InventoryError(_("Enter between 1 and 1000 bottles per addition."))
    wine = Wine.objects.get(pk=wine_id)
    if wine.archived:
        raise InventoryError(_("Restore this wine in Wines before adding bottles."))
    bottle = Bottle(
        wine=wine,
        location=chosen_location(location_id),
        vintage_kind=vintage_kind,
        vintage_year=vintage_year,
        purchase_price=purchase_price,
    )
    bottle.full_clean()
    operation = new_operation(token, actor, "add", fingerprint)
    for _index in range(quantity):
        bottle.pk = None
        bottle.save(force_insert=True)
        InventoryEvent.objects.create(
            bottle=bottle,
            operation=operation,
            reason=InventoryEvent.Reason.ADD,
            current=snapshot(bottle),
        )
    return operation


@transaction.atomic
def consume_bottle(*, token, actor, wine_id, bottle_id=None, location_scope="all"):
    existing, fingerprint = receipt(
        token,
        actor,
        "consume",
        {
            "wine": wine_id,
            "bottle": bottle_id,
            "location_scope": location_scope,
        },
    )
    if existing:
        return existing
    eligible = Bottle.objects.filter(wine_id=wine_id, state=Bottle.State.AVAILABLE)
    if location_scope != "all":
        eligible = eligible.filter(
            location_id=None if location_scope == "unassigned" else int(location_scope)
        )
    eligible = list(eligible.select_related("wine", "location"))
    if bottle_id is not None:
        eligible = [bottle for bottle in eligible if bottle.pk == bottle_id]
    if not eligible:
        raise InventoryError(_("That bottle is no longer available. Nothing was changed."))
    groups = bottle_groups(eligible)
    if len(groups) > 1:
        raise ChooseBottleGroup(groups)
    bottle = groups[0]["bottle"]
    previous = snapshot(bottle)
    bottle.state = Bottle.State.CONSUMED
    bottle.version += 1
    bottle.save(update_fields=["state", "version"])
    operation = new_operation(token, actor, "consume", fingerprint)
    InventoryEvent.objects.create(
        bottle=bottle,
        operation=operation,
        reason=InventoryEvent.Reason.CONSUME,
        previous=previous,
        current=snapshot(bottle),
    )
    return operation


@transaction.atomic
def edit_bottle(
    *, token, actor, bottle_id, version, location_id, vintage_kind, vintage_year, purchase_price
):
    existing, fingerprint = receipt(
        token,
        actor,
        "edit",
        {
            "bottle": bottle_id,
            "version": version,
            "location": location_id,
            "vintage_kind": vintage_kind,
            "vintage_year": vintage_year,
            "price": purchase_price,
        },
    )
    if existing:
        return existing
    bottle = Bottle.objects.select_related("wine", "location").get(pk=bottle_id)
    if bottle.state != Bottle.State.AVAILABLE or bottle.version != version:
        raise StaleBottleError(_("This bottle has changed. Reload its details before editing."))
    previous = snapshot(bottle)
    moved = bottle.location_id != location_id
    corrected = (bottle.vintage_kind, bottle.vintage_year, bottle.purchase_price) != (
        vintage_kind,
        vintage_year,
        purchase_price,
    )
    bottle.location = chosen_location(location_id, bottle.location_id)
    bottle.vintage_kind = vintage_kind
    bottle.vintage_year = vintage_year
    bottle.purchase_price = purchase_price
    bottle.version += 1
    bottle.full_clean()
    bottle.save()
    operation = new_operation(token, actor, "edit", fingerprint)
    for reason in ([InventoryEvent.Reason.MOVE] if moved else []) + (
        [InventoryEvent.Reason.CORRECT] if corrected or not moved else []
    ):
        InventoryEvent.objects.create(
            bottle=bottle,
            operation=operation,
            reason=reason,
            previous=previous,
            current=snapshot(bottle),
        )
    return operation


@transaction.atomic
def remove_bottle(*, token, actor, bottle_id, version, reason, location_scope="all"):
    existing, fingerprint = receipt(
        token,
        actor,
        "remove",
        {
            "bottle": bottle_id,
            "version": version,
            "reason": reason,
            "location_scope": location_scope,
        },
    )
    if existing:
        return existing
    if reason not in {
        InventoryEvent.Reason.GIFT,
        InventoryEvent.Reason.LOSS,
        InventoryEvent.Reason.ADJUSTMENT,
    }:
        raise InventoryError(_("Choose a non-consumption removal reason."))
    bottle = Bottle.objects.select_related("wine", "location").get(pk=bottle_id)
    if bottle.state != Bottle.State.AVAILABLE or bottle.version != version:
        raise StaleBottleError(_("This bottle has changed. Reload its details before editing."))
    if (
        location_scope != "all"
        and (str(bottle.location_id) if bottle.location_id else "unassigned") != location_scope
    ):
        raise InventoryError(_("That bottle is outside the selected location."))
    previous = snapshot(bottle)
    bottle.state = Bottle.State.REMOVED
    bottle.version += 1
    bottle.save(update_fields=["state", "version"])
    operation = new_operation(token, actor, "remove", fingerprint)
    InventoryEvent.objects.create(
        bottle=bottle,
        operation=operation,
        reason=reason,
        previous=previous,
        current=snapshot(bottle),
    )
    return operation


@transaction.atomic
def append_review(*, token, actor, wine_id, date, score, notes):
    existing, fingerprint = receipt(
        token,
        actor,
        "review",
        {
            "wine": wine_id,
            "date": date,
            "score": score,
            "notes": notes,
        },
    )
    if existing:
        return existing
    operation = new_operation(token, actor, "review", fingerprint)
    review = Review(
        wine_id=wine_id, operation=operation, author=actor, date=date, score=score, notes=notes
    )
    if score is None and not notes.strip():
        raise InventoryError(_("Enter a score or a review note."))
    review.full_clean()
    review.save()
    return operation


@transaction.atomic
def retire_location(*, token, actor, location_id, action, target_id=None):
    existing, fingerprint = receipt(
        token,
        actor,
        "location",
        {
            "location": location_id,
            "action": action,
            "target": target_id,
        },
    )
    if existing:
        return existing
    if action not in {"archive", "reassign", "restore"}:
        raise InventoryError(_("Choose a location action."))
    location = Location.objects.get(pk=location_id)
    operation = new_operation(token, actor, "location", fingerprint)
    if action == "reassign":
        if target_id == location_id:
            raise InventoryError(_("Choose a different location."))
        target = chosen_location(target_id)
        bottles = Bottle.objects.filter(
            location=location, state=Bottle.State.AVAILABLE
        ).select_related("wine", "location")
        for bottle in bottles:
            previous = snapshot(bottle)
            bottle.location = target
            bottle.version += 1
            bottle.save(update_fields=["location", "version"])
            InventoryEvent.objects.create(
                bottle=bottle,
                operation=operation,
                reason=InventoryEvent.Reason.MOVE,
                previous=previous,
                current=snapshot(bottle),
            )
    location.archived = action != "restore"
    location.save(update_fields=["archived"])
    return operation
