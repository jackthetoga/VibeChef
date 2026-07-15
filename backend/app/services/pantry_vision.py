from __future__ import annotations

import base64
import json
import logging
import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import settings
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
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
    raise ValueError("Only JPEG, PNG, and WebP images are supported")


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


async def scan_groceries_from_image(
    *,
    content: bytes,
    media_type: str,
) -> list[ScannedGrocery]:
    if not settings.openai_api_key:
        return demo_scan_items()

    schema = json.dumps(ScannedGroceryEnvelope.model_json_schema())
    prompt = (
        "Identify grocery items visible in this photo for a home pantry app.\n"
        "Return JSON only matching this schema:\n"
        f"{schema}\n\n"
        "Rules:\n"
        "- Use short lowercase ingredient names (e.g. \"olive oil\", \"eggs\", \"tomatoes\").\n"
        "- Include quantity and unit when clearly visible on packaging or countable;\n"
        "  otherwise set quantity and unit to null.\n"
        "- Prefer common cooking units (g, kg, ml, l, cup, tbsp, pieces, bunch).\n"
        "- Skip non-food objects, packaging brands as names, and duplicates.\n"
        "- confidence is 0-1 for how sure you are the item is present.\n"
        "- Never invent items that are not visible."
    )
    data_url = f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}"
    user_content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    system = (
        "You extract grocery items from photos for a pantry app. "
        "Return strict JSON only. Never invent values."
    )
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
                logger.exception("Failed to parse grocery scan response")
                raise
        except Exception:
            logger.exception("Grocery vision request failed")
            raise
    return []
