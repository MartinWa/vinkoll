"""Independent pairing snapshots of local data. No provider requests or writes."""

import html
import re
from collections import Counter

from django.db import transaction
from django.utils import timezone

from .models import Bottle, Location, Wine


def text(value):
    """Escape inline Markdown, including table separators and multiline values."""
    value = html.escape(str(value), quote=False)
    value = re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value)
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def note(value):
    # Indentation keeps arbitrary multiline note text literal in Markdown.
    return "\n".join("    " + line for line in value.splitlines()) or "    —"


def score_label(score):
    return f"{score:g}/5" if score is not None else "Unrated"


def generated():
    now = timezone.localtime()
    return f"Generated: {now:%Y-%m-%d %H:%M:%S} {timezone.get_current_timezone_name()}"


@transaction.atomic
def all_wines_markdown():
    lines = [
        "# Vinkoll — all wines, scores and notes",
        "",
        generated(),
        "Scope: All saved wines, including archived profiles and wines with zero stock.",
        "Use Current bottles to determine which wines are available for pairing suggestions.",
        "",
    ]
    wines = Wine.objects.prefetch_related("reviews__author").all()
    for wine in wines:
        reviews = list(wine.reviews.all())
        lines += [
            f"## {text(wine.name)}" + (" [Archived]" if wine.archived else ""),
            "",
            f"Producer: {text(wine.producer or 'Unknown')}; "
            f"Type: {text(wine.get_wine_type_display())}; "
            f"Origin: {text(', '.join(filter(None, [wine.country, wine.region])) or 'Unknown')}; "
            f"Grapes: {text(', '.join(wine.grapes) or 'Unknown')}",
            f"Bottle size: {wine.volume_ml} ml; "
            f"Latest score: {score_label(reviews[0].score if reviews else None)}",
            "",
            "General notes:",
            "",
            note(wine.notes),
            "",
            "Reviews:",
            "",
        ]
        if not reviews:
            lines += ["No reviews recorded.", ""]
        for review in reviews:
            lines += [
                f"- {review.date:%Y-%m-%d} — {score_label(review.score)}; "
                f"Author: {text(review.author.username)}; "
                f"Recorded: {timezone.localtime(review.created_at):%Y-%m-%d %H:%M:%S}",
                "",
                note(review.notes),
                "",
            ]
    if not wines:
        lines += ["No saved wines.", ""]
    return "\n".join(lines)


@transaction.atomic
def current_bottles_markdown(scope="all"):
    bottles = Bottle.objects.filter(state=Bottle.State.AVAILABLE).select_related("wine", "location")
    label = "All locations"
    if scope == "unassigned":
        label = "Unassigned"
        bottles = bottles.filter(location__isnull=True)
    elif scope != "all":
        label = Location.objects.get(pk=scope).name
        bottles = bottles.filter(location_id=scope)
    rows = Counter()
    for bottle in bottles:
        wine = bottle.wine
        vintage = (
            str(bottle.vintage_year)
            if bottle.vintage_kind == "year"
            else {
                "unknown": "Unknown",
                "non_vintage": "Non-vintage",
            }[bottle.vintage_kind]
        )
        rows[
            (
                wine.name,
                wine.producer or "Unknown",
                vintage,
                wine.volume_ml,
                bottle.location.name if bottle.location else "Unassigned",
                wine.pk,
                bottle.location_id or 0,
            )
        ] += 1
    total = sum(rows.values())
    lines = [
        "# Vinkoll — current bottles",
        "",
        generated(),
        f"Location scope: {text(label)}",
        f"Available bottles in this scope: {total}",
        "Choose pairing suggestions only from the bottles below. "
        + (
            "This snapshot covers all locations."
            if scope == "all"
            else f"This snapshot covers {text(label)} only."
        ),
        "",
    ]
    if not total:
        lines += ["0 bottles available.", ""]
    else:
        lines += [
            "| Wine | Producer | Vintage | Size | Location | Quantity |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for row, count in sorted(rows.items()):
            name, producer, vintage, volume, location, *_ = row
            lines.append(
                f"| {text(name)} | {text(producer)} | {text(vintage)} | "
                f"{volume} ml | {text(location)} | {count} |"
            )
        lines.append("")
    return "\n".join(lines)
