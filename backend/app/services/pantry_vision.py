from __future__ import annotations

import base64
import json
import logging
import re
from decimal import Decimal, InvalidOperation
from io import BytesIO

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import settings
from app.services.llm import chat_completion
from app.services.media_bounds import validate_image_dimensions

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "image/heic": {".heic"},
    "image/heif": {".heif"},
}
_HEIF_BRANDS = {
    b"heic",
    b"heix",
    b"hevc",
    b"hevx",
    b"heim",
    b"heis",
    b"hevm",
    b"hevs",
    b"mif1",
    b"msf1",
    b"heif",
}


class ScannedGrocery(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=80)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = " ".join(value.lower().split())
        if not name:
            raise ValueError("Ingredient name is required")
        return name

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.lower().split())
        return cleaned or None


class ScannedGroceryEnvelope(BaseModel):
    items: list[ScannedGrocery] = Field(default_factory=list)


def demo_scan_items() -> list[ScannedGrocery]:
    """Deterministic demo items when no API key is configured."""
    return [
        ScannedGrocery(name="tomatoes", quantity=Decimal("3"), unit="pieces", confidence=0.9),
        ScannedGrocery(name="milk", quantity=Decimal("1"), unit="l", confidence=0.85),
        ScannedGrocery(name="eggs", quantity=Decimal("12"), unit="pieces", confidence=0.8),
        ScannedGrocery(name="spinach", quantity=Decimal("1"), unit="bunch", confidence=0.75),
    ]


def demo_receipt_items() -> list[ScannedGrocery]:
    """Deterministic demo receipt line items when no API key is configured."""
    return [
        ScannedGrocery(name="milk", quantity=Decimal("1"), unit="l", confidence=0.9),
        ScannedGrocery(name="eggs", quantity=Decimal("12"), unit="pieces", confidence=0.88),
        ScannedGrocery(name="bread", quantity=Decimal("1"), unit="loaf", confidence=0.82),
        ScannedGrocery(name="bananas", quantity=Decimal("6"), unit="pieces", confidence=0.75),
    ]


def _looks_like_heif(content: bytes) -> bool:
    return len(content) >= 12 and content[4:8] == b"ftyp" and content[8:12] in _HEIF_BRANDS


def sniff_image_media_type(content: bytes, content_type: str | None, filename: str) -> str:
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared in ALLOWED_IMAGE_TYPES:
        return declared
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for media_type, suffixes in ALLOWED_IMAGE_TYPES.items():
        if suffix in suffixes:
            return media_type
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if _looks_like_heif(content):
        return "image/heic"
    raise ValueError("Only JPEG, PNG, WebP, HEIC, and HEIF images are supported")


def _heif_to_jpeg(content: bytes) -> tuple[bytes, str]:
    """Decode iPhone HEIC/HEIF into JPEG for vision APIs that do not accept HEIF."""
    try:
        import pillow_heif
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency is required in prod
        raise ValueError("HEIC/HEIF support is unavailable on this server") from exc

    pillow_heif.register_heif_opener()
    try:
        with Image.open(BytesIO(content)) as image:
            validate_image_dimensions(*image.size)
            image.load()
            rgb = image.convert("RGB")
            buffer = BytesIO()
            rgb.save(buffer, format="JPEG", quality=90)
            return buffer.getvalue(), "image/jpeg"
    except Exception as exc:
        logger.warning("Failed to decode HEIC/HEIF upload: %s", exc)
        raise ValueError("Could not decode HEIC/HEIF image. Try exporting as JPEG.") from exc


def normalize_pantry_image(
    content: bytes,
    content_type: str | None,
    filename: str,
) -> tuple[bytes, str]:
    media_type = sniff_image_media_type(content, content_type, filename)
    if media_type in {"image/heic", "image/heif"}:
        return _heif_to_jpeg(content)
    return content, media_type


def _parse_json_payload(raw: str) -> object:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    return json.loads(text)


def _coerce_items(payload: object) -> list[ScannedGrocery]:
    if isinstance(payload, list):
        payload = {"items": payload}
    envelope = ScannedGroceryEnvelope.model_validate(payload)
    # Dedupe by name, keep first (highest confidence after sort).
    sorted_items = sorted(
        envelope.items,
        key=lambda item: (-(item.confidence or 0), item.name),
    )
    seen: set[str] = set()
    unique: list[ScannedGrocery] = []
    for item in sorted_items:
        if item.name in seen:
            continue
        seen.add(item.name)
        unique.append(item)
    return unique


async def _scan_image_with_prompt(
    *,
    content: bytes,
    media_type: str,
    prompt: str,
    system: str,
    log_label: str,
) -> list[ScannedGrocery]:
    data_url = f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"
    user_content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    validation_error = ""
    for attempt in range(2):
        messages_user = user_content
        if validation_error:
            messages_user = [
                {
                    "type": "text",
                    "text": f"{prompt}\n\nPrevious output was invalid: {validation_error}",
                },
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        try:
            raw = await chat_completion(
                system=system,
                user=messages_user,
                temperature=0,
                max_tokens=2048,
                response_format={"type": "json_object"},
                timeout=90.0,
            )
            return _coerce_items(_parse_json_payload(raw))
        except (
            ValidationError,
            json.JSONDecodeError,
            InvalidOperation,
            KeyError,
            TypeError,
        ) as exc:
            validation_error = str(exc)
            if attempt:
                logger.exception("Failed to parse %s scan response", log_label)
                raise
        except Exception:
            logger.exception("%s vision request failed", log_label.capitalize())
            raise
    return []


async def scan_groceries_from_image(
    *,
    content: bytes,
    media_type: str,
) -> list[ScannedGrocery]:
    if not settings.llm_enabled:
        return demo_scan_items()

    schema = json.dumps(ScannedGroceryEnvelope.model_json_schema())
    prompt = (
        "Identify grocery items visible in this photo for a home pantry app.\n"
        "Return JSON only matching this schema:\n"
        f"{schema}\n\n"
        "Rules:\n"
        '- Use short lowercase ingredient names (e.g. "olive oil", "eggs", "tomatoes").\n'
        "- Include quantity and unit when clearly visible on packaging or countable;\n"
        "  otherwise set quantity and unit to null.\n"
        "- Prefer common cooking units (g, kg, ml, l, cup, tbsp, pieces, bunch).\n"
        "- Skip non-food objects, packaging brands as names, and duplicates.\n"
        "- confidence is 0-1 for how sure you are the item is present.\n"
        "- Never invent items that are not visible."
    )
    system = (
        "You extract grocery items from photos for a pantry app. "
        "Return strict JSON only. Never invent values."
    )
    return await _scan_image_with_prompt(
        content=content,
        media_type=media_type,
        prompt=prompt,
        system=system,
        log_label="grocery",
    )


async def scan_receipt_from_image(
    *,
    content: bytes,
    media_type: str,
) -> list[ScannedGrocery]:
    if not settings.llm_enabled:
        return demo_receipt_items()

    schema = json.dumps(ScannedGroceryEnvelope.model_json_schema())
    prompt = (
        "Parse grocery line items from this store receipt photo for a home pantry app.\n"
        "Return JSON only matching this schema:\n"
        f"{schema}\n\n"
        "Rules:\n"
        "- Read printed receipt line items only (not fridge contents or surrounding objects).\n"
        "- Map branded SKUs to short lowercase pantry names "
        '(e.g. "horizon organic whole milk" → "milk").\n'
        '- Prefer pack quantity when printed (e.g. "2 × eggs" → quantity 2, unit "pieces");\n'
        "  otherwise set quantity and unit to null.\n"
        "- Prefer common cooking units (g, kg, ml, l, cup, tbsp, pieces, bunch, loaf).\n"
        "- Skip tax, fees, bags, coupons, deposits, and non-food lines.\n"
        "- confidence is 0-1 for how sure you are the line is a food item.\n"
        "- Never invent lines that are not on the receipt."
    )
    system = (
        "You extract food line items from grocery receipt photos for a pantry app. "
        "Return strict JSON only. Never invent values."
    )
    return await _scan_image_with_prompt(
        content=content,
        media_type=media_type,
        prompt=prompt,
        system=system,
        log_label="receipt",
    )
