from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from cellar.models import Location, Wine
from cellar.services import add_bottles


class Command(BaseCommand):
    help = "Create optional synthetic demo records and a demo account in development only."

    def handle(self, **options):
        if not settings.DEBUG:
            raise CommandError("Demo records are only permitted with development settings.")
        actor, _ = get_user_model().objects.get_or_create(username="demo")
        if not actor.check_password("demo") or not actor.is_active:
            actor.set_password("demo")
            actor.is_active = True
            actor.save(update_fields=["password", "is_active"])
        location, _ = Location.objects.get_or_create(name="Vinställ")
        examples = [
            ("Exempel · Pinot noir", "red", "Frankrike", "Pinot noir", 2021, 3),
            ("Exempel · Riesling", "white", "Tyskland", "Riesling", 2023, 2),
            ("Exempel · Mousserande", "sparkling", "Italien", "Glera", None, 1),
        ]
        for name, wine_type, country, grape, year, count in examples:
            wine, _ = Wine.objects.get_or_create(
                name=name,
                defaults={
                    "producer": "Exempelproducent",
                    "wine_type": wine_type,
                    "country": country,
                    "grapes": [grape],
                },
            )
            add_bottles(
                token=uuid5(NAMESPACE_URL, "vinkoll:synthetic-demo:" + name),
                actor=actor,
                wine_id=wine.pk,
                location_id=location.pk,
                quantity=count,
                vintage_kind="year" if year else "non_vintage",
                vintage_year=year,
                purchase_price=Decimal("149.00"),
            )
        self.stdout.write("Synthetic demo ready. Account: demo / demo (development only).")
