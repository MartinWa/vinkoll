import hashlib
import io
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from cellar.forms import WineForm
from cellar.images import prepare_image, save_wine_form
from cellar.models import Wine, WineImage
from cellar.search import card_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def private_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


def photo(format="JPEG", size=(120, 80), orientation=None):
    output = io.BytesIO()
    source = Image.new("RGB", size, (130, 70, 80))
    options = {}
    if orientation:
        exif = Image.Exif()
        exif[274] = orientation
        exif[315] = "Private phone metadata"
        options["exif"] = exif
    source.save(output, format=format, **options)
    return SimpleUploadedFile(
        "untrusted-name.photo", output.getvalue(), content_type="application/octet-stream"
    )


def wine_form(upload=None, instance=None, **extra):
    form = WineForm(
        {"name": "Photo wine", "wine_type": "red", "volume_ml": 750, **extra},
        {"photo": upload} if upload else None,
        instance=instance,
    )
    assert form.is_valid(), form.errors
    return form


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP", "HEIF"])
def test_supported_phone_formats_are_decoded_and_normalized(format):
    prepared = prepare_image(photo(format))
    assert (prepared.width, prepared.height) == (120, 80)
    assert prepared.format == format
    for data in [prepared.display, prepared.thumbnail]:
        with Image.open(io.BytesIO(data)) as decoded:
            assert decoded.format == "WEBP" and not decoded.getexif()


def test_orientation_thumbnail_limits_and_metadata_privacy():
    prepared = prepare_image(photo(size=(2000, 1000), orientation=6))
    assert (prepared.width, prepared.height) == (1000, 2000)
    with Image.open(io.BytesIO(prepared.original)) as original:
        assert original.getexif()[315] == "Private phone metadata"
    for data, dimensions in [(prepared.display, (800, 1600)), (prepared.thumbnail, (240, 480))]:
        with Image.open(io.BytesIO(data)) as derivative:
            assert derivative.size == dimensions and not derivative.getexif()
            assert not derivative.info.get("exif")


@pytest.mark.parametrize(
    "upload",
    [
        SimpleUploadedFile("photo.svg", b"<svg><script>alert(1)</script></svg>"),
        SimpleUploadedFile("photo.jpg", b"not a photo"),
        SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0"),
    ],
)
def test_invalid_images_preserve_form_and_write_nothing(client, actor, upload, private_media):
    client.force_login(actor)
    response = client.post(
        "/wines/add/",
        {
            "name": "Preserved name",
            "wine_type": "red",
            "volume_ml": 750,
            "notes": "Preserved notes",
            "photo": upload,
        },
    )
    assert response.status_code == 200 and response.context["form"].errors.get("photo")
    assert response.context["form"].data["notes"] == "Preserved notes"
    assert not Wine.objects.exists() and not WineImage.objects.exists()
    assert not private_media.exists()


def test_upload_bytes_and_decoded_dimensions_are_bounded():
    with patch("cellar.images.MAX_UPLOAD_BYTES", 10), pytest.raises(ValidationError):
        prepare_image(photo())
    with patch("cellar.images.MAX_PIXELS", 50), pytest.raises(ValidationError):
        prepare_image(photo())
    with patch("cellar.images.MAX_DIMENSION", 50), pytest.raises(ValidationError):
        prepare_image(photo())
    with patch("PIL.Image.MAX_IMAGE_PIXELS", 100), pytest.raises(ValidationError):
        prepare_image(photo())
    output = io.BytesIO()
    Image.new("RGB", (10, 10)).save(output, "GIF")
    with pytest.raises(ValidationError):
        prepare_image(SimpleUploadedFile("photo.gif", output.getvalue()))


def test_images_are_private_with_thumbnails_original_checksums_and_placeholder(
    client, actor, private_media
):
    wine = save_wine_form(wine_form(photo()))
    image = wine.images.get()
    assert image.width == 120 and image.original_format == "JPEG"
    for field in ["original", "display", "thumbnail"]:
        name = getattr(image, field).name
        path = private_media / name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == image.checksums[field]
        assert "untrusted-name" not in name
    url = f"/images/{image.pk}/thumbnail/"
    assert client.get(url).status_code == 302
    client.force_login(actor)
    response = client.get(url)
    assert response.status_code == 200 and response["Content-Type"] == "image/webp"
    assert response["Cache-Control"] == "no-store"
    assert (
        b"".join(response.streaming_content) == (private_media / image.thumbnail.name).read_bytes()
    )
    assert client.get(f"/images/{image.pk}/original/").status_code == 404
    assert client.get("/media/" + image.original.name).status_code == 404
    assert f"/images/{image.pk}/thumbnail/" in client.get("/wines/").content.decode()
    (private_media / image.thumbnail.name).unlink()
    assert client.get(url).status_code == 404
    assert "bottle-shape" in client.get("/wines/").content.decode()


def test_user_photo_precedes_imported_and_removal_restores_imported(wine):
    imported = WineImage.objects.create(
        wine=wine,
        source="imported",
        original="imported.jpg",
        display="imported.webp",
        thumbnail="imported-thumb.webp",
        original_format="JPEG",
        original_bytes=10,
        width=10,
        height=10,
    )
    wine = save_wine_form(wine_form(photo(), instance=wine))
    first = wine.images.get(source="user")
    assert card_data(Wine.objects.all()).get().image_id == first.pk
    wine = save_wine_form(wine_form(photo("PNG"), instance=wine))
    assert wine.images.filter(source="user", active=True).count() == 1
    assert wine.images.filter(source="user").count() == 2
    assert card_data(Wine.objects.all()).get().image_id != first.pk
    save_wine_form(wine_form(instance=wine, remove_photo="on"))
    assert card_data(Wine.objects.all()).get().image_id == imported.pk


def test_storage_failure_cleans_new_files_preserves_existing_wine_and_form(
    client, actor, wine, private_media
):
    from django.core.files.storage import default_storage

    client.force_login(actor)
    original_save = default_storage.save
    calls = 0

    def failing_save(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            original_save(*args, **kwargs)
            raise OSError("synthetic disk full")
        return original_save(*args, **kwargs)

    with patch("cellar.images.default_storage.save", side_effect=failing_save):
        response = client.post(
            f"/wines/{wine.pk}/edit/",
            {
                "name": "Unsaved name",
                "wine_type": "red",
                "volume_ml": 750,
                "notes": "Keep my notes",
                "photo": photo(),
            },
        )
    assert response.status_code == 200 and response.context["form"].errors.get("photo")
    assert response.context["form"].data["notes"] == "Keep my notes"
    wine.refresh_from_db()
    assert wine.name == "Example Red" and not WineImage.objects.exists()
    assert not list(private_media.rglob("*.*"))


def test_database_failure_cleans_files_and_keeps_previous_photo(wine, private_media):
    save_wine_form(wine_form(photo(), instance=wine))
    original = wine.images.get()
    initial_files = set(private_media.rglob("*.*"))
    form = wine_form(photo("PNG"), instance=wine, name="Unsaved name")
    with patch(
        "cellar.images.WineImage.objects.create",
        side_effect=RuntimeError("synthetic database error"),
    ):
        with pytest.raises(RuntimeError):
            save_wine_form(form)
    wine.refresh_from_db()
    original.refresh_from_db()
    assert wine.name == "Photo wine" and original.active
    assert set(private_media.rglob("*.*")) == initial_files


def test_unused_profile_deletion_removes_private_files_after_commit(
    client, actor, private_media, django_capture_on_commit_callbacks
):
    wine = save_wine_form(wine_form(photo()))
    client.force_login(actor)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/wines/{wine.pk}/retire/", {"action": "delete"}).status_code == 302
    assert not WineImage.objects.exists() and not Wine.objects.exists()
    assert not list(private_media.rglob("*.*"))
