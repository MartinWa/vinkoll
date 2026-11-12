import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("development"):  # noqa: F405
    raise ImproperlyConfigured(
        "Set VINKOLL_SECRET_KEY to a private random key of at least 50 chars."
    )
ALLOWED_HOSTS = [
    x.strip() for x in os.environ.get("VINKOLL_ALLOWED_HOSTS", "").split(",") if x.strip()
]
CSRF_TRUSTED_ORIGINS = [
    x.strip() for x in os.environ.get("VINKOLL_CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()
]
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set exact VINKOLL_ALLOWED_HOSTS.")
if not CSRF_TRUSTED_ORIGINS or any(not x.startswith("https://") for x in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("Set VINKOLL_CSRF_TRUSTED_ORIGINS to the public HTTPS origin.")
# Only Caddy may reach the production listener. Do not publish its port on the host.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
SECURE_HSTS_SECONDS = 31536000
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
