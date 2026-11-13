from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class LoginAttempt(models.Model):
    # Only hashed username/IP buckets are retained; no raw addresses or credentials.
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class CellarSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    store_id = models.CharField(
        _("Store ID"),
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^[0-9]+$", _("Use digits only."))],
        help_text=_("Leading zeroes are preserved."),
    )
    store_name = models.CharField(_("Store name"), max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="single_cellar_settings")
        ]
