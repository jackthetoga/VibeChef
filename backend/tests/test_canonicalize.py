import json

import pytest

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Ingredient
from app.services import canonicalize as canonicalize_module
from app.services.canonicalize import (
    canonicalize_ingredients,
    heuristic_canonical_name,
    ingredient_match_key,
)


@pytest.mark.asyncio
async def test_canonicalize_batch_links_variants_and_preserves_compounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "external_ai_enabled", True)
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
    monkeypatch.setattr(settings, "external_ai_enabled", True)

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


def test_match_keys_for_cooking_onions_and_pork_sausage() -> None:
    assert ingredient_match_key("yellow onion") == "onion"
    assert ingredient_match_key("white onion") == "onion"
    assert ingredient_match_key("onion") == "onion"
    assert ingredient_match_key("red onion") == "red onion"
    assert ingredient_match_key("pork sausage") == "sausage"
    assert ingredient_match_key("sausage") == "sausage"
    assert ingredient_match_key("italian sausage") == "italian sausage"


def test_heuristic_canonical_name_maps_onion_and_sausage_variants() -> None:
    assert heuristic_canonical_name("yellow onion") == "onion"
    assert heuristic_canonical_name("white onions") == "onion"
    assert heuristic_canonical_name("pork sausage") == "sausage"
    assert heuristic_canonical_name("red onion") is None
    assert heuristic_canonical_name("onion") is None
    assert heuristic_canonical_name("italian sausage") is None


@pytest.mark.asyncio
async def test_canonicalize_without_api_key_applies_heuristics_only(
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
        oil = Ingredient(name="light olive oil")
        zest = Ingredient(name="lemon zest")
        canned = Ingredient(name="canned imported italian plum tomatoes")
        yellow_onion = Ingredient(name="yellow onion")
        pork_sausage = Ingredient(name="pork sausage")
        red_onion = Ingredient(name="red onion")
        db.add_all([oil, zest, canned, yellow_onion, pork_sausage, red_onion])
        await db.flush()

        await canonicalize_ingredients(
            db, [oil, zest, canned, yellow_onion, pork_sausage, red_onion]
        )

        assert oil.canonical_id is None
        assert zest.canonical_id is not None
        lemon = await db.get(Ingredient, zest.canonical_id)
        assert lemon is not None
        assert lemon.name == "lemon"
        assert canned.canonical_id is not None
        root = await db.get(Ingredient, canned.canonical_id)
        assert root is not None
        assert root.name == "canned tomatoes"
        assert yellow_onion.canonical_id is not None
        onion = await db.get(Ingredient, yellow_onion.canonical_id)
        assert onion is not None
        assert onion.name == "onion"
        assert pork_sausage.canonical_id is not None
        sausage = await db.get(Ingredient, pork_sausage.canonical_id)
        assert sausage is not None
        assert sausage.name == "sausage"
        assert red_onion.canonical_id is None
