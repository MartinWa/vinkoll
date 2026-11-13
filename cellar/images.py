"""Bounded, private photo storage. Display derivatives never contain EXIF metadata."""

import hashlib
import io
import logging
import warnings
from dataclasses import dataclass
from uuid import uuid4

import pillow_heif
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import WineImage

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_DIMENSION = 16_000
FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "HEIF": "heic"}
pillow_heif.register_heif_opener()
logger = logging.getLogger(__name__)


@dataclass
class PreparedImage:
    original: bytes
    display: bytes
    thumbnail: bytes
    format: str
    width: int
    height: int


def prepare_image(upload):
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError(_("Choose a photo no larger than 20 MB."))
    upload.seek(0)
    raw = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValidationError(_("Choose a photo no larger than 20 MB."))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in FORMATS:
                    raise ValidationError(_("Use a JPEG, PNG, WebP or HEIC photo."))
                if source.width * source.height > MAX_PIXELS or max(source.size) > MAX_DIMENSION:
                    raise ValidationError(_("Choose a photo of at most 40 megapixels."))
                if getattr(source, "n_frames", 1) != 1:
                    raise ValidationError(_("Choose a still photo instead of an animation."))
                original_format = source.format
                source.load()
                normalized = ImageOps.exif_transpose(source).convert("RGBA")
                width, height = normalized.size
                normalized.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                # Copy pixels onto a fresh image to drop EXIF/GPS and other source metadata.
                clean = Image.new("RGBA", normalized.size)
                clean.paste(normalized)
                outputs = []
                for size in (1600, 480):
                    derivative = clean.copy()
                    derivative.thumbnail((size, size), Image.Resampling.LANCZOS)
                    output = io.BytesIO()
                    derivative.save(output, "WEBP", quality=85)
                    outputs.append(output.getvalue())
        return PreparedImage(raw, *outputs, original_format, width, height)
    except ValidationError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValidationError(
            _("The photo could not be read. Choose another photo or save without it.")
        ) from exc


def save_wine_form(form):
    """Clean up every new file if storage or the database fails; retain the old photo."""
    files = []
    attempted = []
    try:
        prepared = form.cleaned_data.get("photo")
        if prepared:
            prefix = f"wines/{uuid4().hex}"
            for field, data, extension in (
                ("original", prepared.original, FORMATS[prepared.format]),
                ("display", prepared.display, "webp"),
                ("thumbnail", prepared.thumbnail, "webp"),
            ):
                path = f"{prefix}/{field}.{extension}"
                attempted.append(path)
                name = default_storage.save(path, ContentFile(data))
                if name != path:
                    attempted.append(name)
                files.append((field, name, hashlib.sha256(data).hexdigest()))
        with transaction.atomic():
            wine = form.save()
            if prepared or form.cleaned_data.get("remove_photo"):
                WineImage.objects.filter(wine=wine, source="user", active=True).update(active=False)
            if prepared:
                WineImage.objects.create(
                    wine=wine,
                    source="user",
                    original_format=prepared.format,
                    original_bytes=len(prepared.original),
                    width=prepared.width,
                    height=prepared.height,
                    checksums={field: checksum for field, _, checksum in files},
                    **{field: name for field, name, _ in files},
                )
        return wine
    except Exception:
        delete_files(attempted)
        raise


def delete_files(names):
    for name in names:
        try:
            default_storage.delete(name)
        except OSError:
            logger.exception("Could not remove private image file %s", name)


def delete_unused_wine(wine):
    names = [
        getattr(image, field).name
        for image in wine.images.all()
        for field in ("original", "display", "thumbnail")
    ]
    wine.delete()
    # A failed catalogue transaction must leave all existing photo files intact.
    transaction.on_commit(lambda: delete_files(names))
