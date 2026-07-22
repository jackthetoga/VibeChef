from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

MAX_REVIEW_PHOTO_BYTES = 5 * 1024 * 1024
_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


def normalize_review_photo(content: bytes) -> tuple[bytes, str, str]:
    try:
        with Image.open(BytesIO(content)) as image:
            image_format = (image.format or "").upper()
            if image_format not in _FORMATS:
                raise ValueError("Only JPEG, PNG, and WebP photos are supported")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Animated or multi-frame photos are not supported")

            width, height = image.size
            if (
                width <= 0
                or height <= 0
                or width > settings.max_image_dimension
                or height > settings.max_image_dimension
                or width * height > settings.max_image_pixels
            ):
                raise ValueError("Photo dimensions exceed the configured limit")

            image.load()
            normalized = ImageOps.exif_transpose(image)
            media_type, suffix = _FORMATS[image_format]
            output = BytesIO()
            if image_format == "JPEG":
                normalized.convert("RGB").save(output, format="JPEG", quality=85, optimize=True)
            elif image_format == "PNG":
                mode = "RGBA" if "A" in normalized.getbands() else "RGB"
                normalized.convert(mode).save(output, format="PNG", optimize=True)
            else:
                mode = "RGBA" if "A" in normalized.getbands() else "RGB"
                normalized.convert(mode).save(output, format="WEBP", quality=85, method=4)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Could not decode the uploaded photo") from exc

    data = output.getvalue()
    if not data or len(data) > MAX_REVIEW_PHOTO_BYTES:
        raise ValueError("Processed photo exceeds the 5 MB limit")
    return data, media_type, suffix
