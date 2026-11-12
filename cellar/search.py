"""Unicode-aware local search; SQLite's built-in NOCASE is ASCII-only."""

import unicodedata

from django.db.models import OuterRef, Subquery

from .models import Review, WineImage


def normalize(value):
    return unicodedata.normalize("NFKC", value).casefold()


def wine_search_text(wine):
    return normalize(
        "\n".join(
            [
                wine.name,
                wine.producer,
                wine.country,
                wine.region,
                *wine.grapes,
                wine.article_number or "",
                wine.short_article_number,
            ]
        )
    )


def search_wines(wines, query):
    for word in normalize(query).split():
        wines = wines.filter(search_text__contains=word)
    return wines


def card_data(wines):
    latest = Review.objects.filter(wine_id=OuterRef("pk"))
    # User photos sort before imported images, irrespective of retrieval time.
    images = WineImage.objects.filter(wine_id=OuterRef("pk"), active=True).order_by(
        "-source", "-created_at", "-pk"
    )
    return wines.annotate(
        latest_score=Subquery(latest.values("score")[:1]),
        image_id=Subquery(images.values("pk")[:1]),
    )
