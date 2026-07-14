import json

import pytest

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Ingredient
from app.services import canonicalize as canonicalize_module
from app.services.canonicalize import canonicalize_ingredients


@pytest.mark.asyncio
async def test_canonicalize_batch_links_variants_and_preserves_compounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    captured_user = ""

    async def fake_chat_completion(**kwargs) -> str:
        nonlocal captured_user
        captured_user = kwargs["user"]
        return json.dumps(
            {
                "chopped parsley": "parsley",
                "coconut milk": "coconut milk",
                "extra virgin olive oil": "olive oil",
            }
        )

    monkeypatch.setattr(canonicalize_module, "chat_completion", fake_chat_completion)

    async with SessionLocal() as db:
        olive_oil = Ingredient(name="olive oil", category="Oils")
        extra_virgin = Ingredient(name="extra virgin olive oil", category="Oils")
        coconut_milk = Ingredient(name="coconut milk")
        chopped_parsley = Ingredient(name="chopped parsley")
        db.add_all([olive_oil, extra_virgin, coconut_milk, chopped_parsley])
        await db.flush()
        olive_oil.canonical_id = olive_oil.id
        await db.flush()

        await canonicalize_ingredients(
            db,
            [extra_virgin, coconut_milk, chopped_parsley],
        )
        await db.flush()

        assert extra_virgin.canonical_id == olive_oil.id
        assert coconut_milk.canonical_id == coconut_milk.id
        assert chopped_parsley.canonical_id is not None
        parsley = await db.get(Ingredient, chopped_parsley.canonical_id)
        assert parsley is not None
        assert parsley.name == "parsley"
        assert parsley.canonical_id == parsley.id
        assert "extra virgin olive oil" in olive_oil.aliases
        assert "olive oil" in captured_user
        assert "coconut milk is not milk" in captured_user


@pytest.mark.asyncio
async def test_canonicalize_ignores_missing_and_invalid_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    async def fake_chat_completion(**_kwargs) -> str:
        return '{"chopped basil": ["not", "a", "string"]}'

    monkeypatch.setattr(canonicalize_module, "chat_completion", fake_chat_completion)

    async with SessionLocal() as db:
        basil = Ingredient(name="chopped basil")
        thyme = Ingredient(name="fresh thyme")
        db.add_all([basil, thyme])
        await db.flush()

        await canonicalize_ingredients(db, [basil, thyme])

        assert basil.canonical_id is None
        assert thyme.canonical_id is None


@pytest.mark.asyncio
async def test_canonicalize_without_api_key_is_a_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)

    async def unexpected_chat_completion(**_kwargs) -> str:
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(
        canonicalize_module,
        "chat_completion",
        unexpected_chat_completion,
    )

    async with SessionLocal() as db:
        ingredient = Ingredient(name="light olive oil")
        db.add(ingredient)
        await db.flush()

        await canonicalize_ingredients(db, [ingredient])

        assert ingredient.canonical_id is None
