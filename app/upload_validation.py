"""Bounded image validation before source bytes reach OCR or storage."""

from __future__ import annotations

import io
import warnings

from PIL import Image, UnidentifiedImageError


MAX_IMAGE_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

_FORMATS = {
    "image/png": (b"\x89PNG\r\n\x1a\n", "PNG"),
    "image/jpeg": (b"\xff\xd8\xff", "JPEG"),
    "image/jpg": (b"\xff\xd8\xff", "JPEG"),
}


class ImageUploadError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_image_upload(content: bytes, reported_mime_type: str) -> str:
    """Validate signature, decoder result and pixel count; return canonical MIME."""

    expected = _FORMATS.get(reported_mime_type)
    if expected is None:
        raise ImageUploadError("unsupported_image_type")
    signature, expected_format = expected
    if not content.startswith(signature):
        raise ImageUploadError("image_signature_invalid")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format != expected_format:
                    raise ImageUploadError("image_signature_invalid")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ImageUploadError("image_dimensions_too_large")
                image.verify()
    except ImageUploadError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageUploadError("image_dimensions_too_large") from None
    except (OSError, UnidentifiedImageError):
        raise ImageUploadError("image_decode_failed") from None
    return "image/jpeg" if expected_format == "JPEG" else "image/png"
