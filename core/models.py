from django.db import models


class LoginAttempt(models.Model):
    # Only hashed username/IP buckets are retained; no raw addresses or credentials.
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
