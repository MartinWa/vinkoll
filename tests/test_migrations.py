from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from cellar.models import Wine, WineImage
from cellar.search import search_wines
from cellar.services import append_review


@pytest.mark.django_db(transaction=True)
def test_wine_schema_upgrade_preserves_existing_profiles_and_bottles(actor):
    old = [("cellar", "0001_initial")]
    new = [("cellar", "0002_wine_search_reviews_images")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(old)
        old_apps = executor.loader.project_state(old).apps
        wine = old_apps.get_model("cellar", "Wine").objects.create(
            name="Årgång",
            producer="Östra slottet",
            grapes=["Riesling"],
            article_number="123456",
        )
        old_apps.get_model("cellar", "Bottle").objects.create(
            wine=wine,
            vintage_kind="year",
            vintage_year=2021,
        )
        MigrationExecutor(connection).migrate(new)
        upgraded = search_wines(Wine.objects.all(), "ÅRGÅNG östra riesling 123456").get()
        assert upgraded.pk == wine.pk and upgraded.bottles.get().vintage_year == 2021
        operation = append_review(
            token=uuid4(),
            actor=actor,
            wine_id=wine.pk,
            date=timezone.localdate(),
            score=None,
            notes="Schema upgrade review",
        )
        assert upgraded.reviews.get().operation_id == operation.pk
        image = WineImage.objects.create(
            wine=upgraded,
            source="user",
            original="original.jpg",
            display="display.webp",
            thumbnail="thumbnail.webp",
            original_format="JPEG",
            original_bytes=100,
            width=10,
            height=10,
        )
        assert upgraded.images.get().pk == image.pk
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
