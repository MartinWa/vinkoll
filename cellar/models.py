import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Location(models.Model):
    name = models.CharField(_("Name"), max_length=100, unique=True)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


class Wine(models.Model):
    class Type(models.TextChoices):
        RED = "red", _("Red")
        WHITE = "white", _("White")
        ROSE = "rose", _("Rosé")
        SPARKLING = "sparkling", _("Sparkling")
        DESSERT = "dessert", _("Dessert wine")
        FORTIFIED = "fortified", _("Fortified wine")
        OTHER = "other", _("Other")

    name = models.CharField(_("Name"), max_length=200)
    producer = models.CharField(_("Producer"), max_length=200, blank=True)
    wine_type = models.CharField(_("Type"), max_length=20, choices=Type, default=Type.RED)
    country = models.CharField(_("Country"), max_length=100, blank=True)
    region = models.CharField(_("Region"), max_length=200, blank=True)
    grapes = models.JSONField(default=list, blank=True)
    volume_ml = models.PositiveIntegerField(
        _("Bottle size (ml)"), default=750, validators=[MinValueValidator(1)]
    )
    article_number = models.CharField(
        _("Full Systembolaget article number"),
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        validators=[RegexValidator(r"^\d+$", _("Use digits only."))],
    )
    short_article_number = models.CharField(max_length=20, blank=True)
    retail_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    retail_price_source = models.CharField(max_length=100, blank=True)
    retail_price_retrieved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(_("General notes"), blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    search_text = models.TextField(default="", editable=False)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(volume_ml__gt=0), name="wine_volume_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(retail_price__isnull=True) | models.Q(retail_price__gte=0),
                name="wine_price_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.name} · {self.volume_ml} ml"

    def save(self, *args, **kwargs):
        from .search import wine_search_text

        with transaction.atomic():
            super().save(*args, **kwargs)
            # Read persisted values: a partial save must not index stale provider fields.
            stored = type(self).objects.get(pk=self.pk)
            self.search_text = wine_search_text(stored)
            type(self).objects.filter(pk=self.pk).update(search_text=self.search_text)

    @property
    def product_url(self):
        if self.article_number:
            return f"https://www.systembolaget.se/produkt/vin/{self.article_number}/"
        return ""


class Bottle(models.Model):
    class Vintage(models.TextChoices):
        YEAR = "year", _("Year")
        UNKNOWN = "unknown", _("Unknown")
        NON_VINTAGE = "non_vintage", _("Non-vintage")

    class State(models.TextChoices):
        AVAILABLE = "available", _("Available")
        CONSUMED = "consumed", _("Consumed")
        REMOVED = "removed", _("Removed")

    wine = models.ForeignKey(Wine, on_delete=models.PROTECT, related_name="bottles")
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bottles",
        verbose_name=_("Location"),
    )
    vintage_kind = models.CharField(
        _("Vintage"), max_length=20, choices=Vintage, default=Vintage.UNKNOWN
    )
    vintage_year = models.PositiveSmallIntegerField(
        _("Vintage year"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1800), MaxValueValidator(2200)],
    )
    purchase_price = models.DecimalField(
        _("Price paid per bottle (SEK)"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    acquired_at = models.DateTimeField(default=timezone.now)
    state = models.CharField(max_length=20, choices=State, default=State.AVAILABLE)
    version = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["acquired_at", "pk"]
        indexes = [models.Index(fields=["wine", "state", "location"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(vintage_kind="year", vintage_year__gte=1800, vintage_year__lte=2200)
                    & models.Q(vintage_year__isnull=False)
                )
                | models.Q(vintage_kind__in=["unknown", "non_vintage"], vintage_year__isnull=True),
                name="bottle_vintage_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(purchase_price__isnull=True) | models.Q(purchase_price__gte=0),
                name="bottle_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["available", "consumed", "removed"]),
                name="bottle_state_valid",
            ),
        ]

    @property
    def vintage_label(self):
        return (
            self.vintage_year
            if self.vintage_kind == self.Vintage.YEAR
            else self.get_vintage_kind_display()
        )

    @property
    def location_label(self):
        return self.location.name if self.location else _("Unassigned")


class InventoryOperation(models.Model):
    token = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20)
    fingerprint = models.CharField(max_length=64)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "token"]


class InventoryEvent(models.Model):
    class Reason(models.TextChoices):
        ADD = "add", _("Added bottles")
        CONSUME = "consume", _("Consumed")
        CORRECT = "correct", _("Corrected bottle")
        MOVE = "move", _("Moved bottle")
        GIFT = "gift", _("Gift")
        LOSS = "loss", _("Loss")
        ADJUSTMENT = "adjustment", _("Inventory adjustment")

    bottle = models.ForeignKey(Bottle, on_delete=models.PROTECT, related_name="events")
    operation = models.ForeignKey(
        InventoryOperation, on_delete=models.PROTECT, related_name="events"
    )
    reason = models.CharField(max_length=20, choices=Reason)
    previous = models.JSONField(default=dict)
    current = models.JSONField(default=dict)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["bottle", "operation", "reason"], name="unique_bottle_operation_reason"
            )
        ]


class Review(models.Model):
    wine = models.ForeignKey(Wine, on_delete=models.PROTECT, related_name="reviews")
    operation = models.OneToOneField(InventoryOperation, on_delete=models.PROTECT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    date = models.DateField(_("Review date"), default=timezone.localdate)
    score = models.DecimalField(_("Score"), max_digits=2, decimal_places=1, null=True, blank=True)
    notes = models.TextField(_("Review notes"), blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score__isnull=True)
                | models.Q(score__in=[1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]),
                name="review_score_half_stars",
            )
        ]


class WineImage(models.Model):
    class Source(models.TextChoices):
        USER = "user", _("User photo")
        IMPORTED = "imported", _("Imported image")

    wine = models.ForeignKey(Wine, on_delete=models.CASCADE, related_name="images")
    source = models.CharField(max_length=10, choices=Source)
    source_url = models.URLField(max_length=1000, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)
    original = models.FileField(max_length=200)
    display = models.FileField(max_length=200)
    thumbnail = models.FileField(max_length=200)
    original_format = models.CharField(max_length=10)
    original_bytes = models.PositiveIntegerField()
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    checksums = models.JSONField(default=dict)

    class Meta:
        ordering = ["source", "-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["wine", "source"],
                condition=models.Q(active=True),
                name="one_active_image_per_source",
            )
        ]
