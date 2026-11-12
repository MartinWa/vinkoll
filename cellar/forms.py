import uuid
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .models import Bottle, InventoryEvent, Location, Review, Wine


class WineForm(forms.ModelForm):
    grapes_text = forms.CharField(
        label=_("Grapes (comma-separated)"), required=False, max_length=1000
    )

    class Meta:
        model = Wine
        fields = [
            "name",
            "producer",
            "wine_type",
            "country",
            "region",
            "grapes_text",
            "volume_ml",
            "article_number",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["grapes_text"].initial = ", ".join(self.instance.grapes)

    def clean_article_number(self):
        return self.cleaned_data["article_number"] or None

    def save(self, commit=True):
        self.instance.grapes = [
            value.strip() for value in self.cleaned_data["grapes_text"].split(",") if value.strip()
        ]
        instance = super().save(commit=False)
        if commit:
            if instance.pk:
                # A profile edit must not undo a concurrent archive or overwrite provider context.
                fields = [field for field in self.Meta.fields if field != "grapes_text"] + [
                    "grapes"
                ]
                instance.save(update_fields=fields)
            else:
                instance.save()
        return instance


class BottleFieldsForm(forms.Form):
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    location = forms.ModelChoiceField(
        label=_("Location"),
        queryset=Location.objects.none(),
        required=False,
        empty_label=_("Unassigned"),
    )
    vintage_kind = forms.ChoiceField(
        label=_("Vintage"), choices=Bottle.Vintage, initial=Bottle.Vintage.UNKNOWN
    )
    vintage_year = forms.IntegerField(
        label=_("Vintage year"), required=False, min_value=1800, max_value=2200
    )
    purchase_price = forms.DecimalField(
        label=_("Price paid per bottle (SEK)"),
        required=False,
        min_value=0,
        max_digits=10,
        decimal_places=2,
        help_text=_("Leave blank if unknown. Zero is a valid price."),
    )

    def __init__(self, *args, current_location=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.filter(
            Q(archived=False) | Q(pk=current_location)
        )

    def clean(self):
        data = super().clean()
        if data.get("vintage_kind") == Bottle.Vintage.YEAR:
            if data.get("vintage_year") is None:
                self.add_error("vintage_year", _("Enter a vintage year."))
        elif data.get("vintage_year") is not None:
            self.add_error("vintage_year", _("Only enter a year when Year is selected."))
        return data

    def service_data(self):
        data = self.cleaned_data.copy()
        location = data.pop("location")
        data["location_id"] = location.pk if location else None
        return data


class AddBottlesForm(BottleFieldsForm):
    wine = forms.ModelChoiceField(label=_("Wine"), queryset=Wine.objects.filter(archived=False))
    quantity = forms.IntegerField(
        label=_("Number of bottles"), min_value=1, max_value=1000, initial=1
    )
    field_order = ["wine", "location", "quantity", "vintage_kind", "vintage_year", "purchase_price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            # Replays must reach receipt validation even after a selection is archived.
            # The service checks active records inside the transaction for every new addition.
            self.fields["wine"].queryset = Wine.objects.all()
            self.fields["location"].queryset = Location.objects.all()
        locations = Location.objects.filter(archived=False)
        if locations.count() == 1:
            self.fields["location"].initial = locations.first()

    def service_data(self):
        data = super().service_data()
        data["wine_id"] = data.pop("wine").pk
        return data


class EditBottleForm(BottleFieldsForm):
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=0)


class ConsumeForm(forms.Form):
    token = forms.UUIDField(widget=forms.HiddenInput)
    bottle_id = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput)


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name"]

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            if instance.pk:
                # Renaming must preserve a concurrent archive or restore.
                instance.save(update_fields=["name"])
            else:
                instance.save()
        return instance


class ReviewForm(forms.ModelForm):
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    score = forms.DecimalField(
        label=_("Score"),
        required=False,
        max_digits=2,
        decimal_places=1,
        widget=forms.Select(
            choices=[("", _("Unrated"))]
            + [(str(Decimal(value) / 2), f"{Decimal(value) / 2:g}/5") for value in range(2, 11)],
            attrs={"data-score-control": ""},
        ),
        help_text=_("1–5 stars in half-star steps. A note can be saved without a score."),
    )

    class Meta:
        model = Review
        fields = ["date", "score", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_score(self):
        value = self.cleaned_data["score"]
        if value is not None and value not in [Decimal(n) / 2 for n in range(2, 11)]:
            raise forms.ValidationError(_("Choose 1–5 stars in half-star steps."))
        return value

    def clean(self):
        data = super().clean()
        if data.get("score") is None and not data.get("notes"):
            raise forms.ValidationError(_("Enter a score or a review note."))
        return data


class RemoveBottleForm(forms.Form):
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    version = forms.IntegerField(widget=forms.HiddenInput, min_value=0)
    reason = forms.ChoiceField(
        label=_("Removal reason"),
        choices=[
            (reason, label)
            for reason, label in InventoryEvent.Reason.choices
            if reason in {"gift", "loss", "adjustment"}
        ],
    )


class RetireLocationForm(forms.Form):
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    action = forms.ChoiceField(
        label=_("Action"),
        choices=[
            ("archive", _("Archive and leave bottles here")),
            ("reassign", _("Move available bottles and archive")),
        ],
    )
    target = forms.ModelChoiceField(
        label=_("Move bottles to"),
        queryset=Location.objects.none(),
        required=False,
        empty_label=_("Unassigned"),
    )

    def __init__(self, *args, location, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target"].queryset = Location.objects.filter(archived=False).exclude(
            pk=location.pk
        )
        if location.archived:
            self.fields["action"].choices = [
                ("restore", _("Restore location")),
                ("reassign", _("Move remaining bottles and keep archived")),
            ]
