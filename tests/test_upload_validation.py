from __future__ import annotations

import io

from PIL import Image
import pytest

import app.upload_validation as upload_validation
from app.upload_validation import ImageUploadError, validate_image_upload


def png_bytes(width: int = 2, height: int = 2) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_valid_png_is_decoded_before_acceptance() -> None:
    assert validate_image_upload(png_bytes(), "image/png") == "image/png"


def test_reported_image_with_invalid_signature_is_rejected() -> None:
    with pytest.raises(ImageUploadError, match="image_signature_invalid"):
        validate_image_upload(b"not-an-image", "image/png")


def test_decoded_pixel_limit_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload_validation, "MAX_IMAGE_PIXELS", 1)

    with pytest.raises(ImageUploadError, match="image_dimensions_too_large"):
        validate_image_upload(png_bytes(), "image/png")


@pytest.mark.parametrize("mime_type", ["image/webp", "image/bmp", "image/heic"])
def test_unapproved_image_formats_are_rejected(mime_type: str) -> None:
    with pytest.raises(ImageUploadError, match="unsupported_image_type"):
        validate_image_upload(b"untrusted", mime_type)
