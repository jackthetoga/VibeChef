from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Ingredient, IngredientFamily
from app.services.ingestion import _ingredient_is_valid, demo_ingredient
from app.services.ingredient_quality import (
    assign_ingredient_metadata,
    ingredient_quality_flags,
    parse_status_for_flags,
    shopping_family_name,
)


def test_quality_flags_reject_fragments_and_dimension_leaks() -> None:
    assert ingredient_quality_flags("choice") == ["descriptor_only"]
    assert ingredient_quality_flags("fine") == ["descriptor_only"]
    flags = ingredient_quality_flags("1 1/2-inch-thick slices of veal hind shank")
    assert "numeric_prefix" in flags
    assert "dimensional_name" in flags
    assert parse_status_for_flags(flags) == "suspect"
    assert not _ingredient_is_valid(demo_ingredient("Fine"))
    repaired = demo_ingredient("1 1/2-inch-thick slices of veal hind shank")
    assert repaired.canonical_name == "veal hind shank"


def test_shopping_family_preserves_exact_meat_cut() -> None:
    assert shopping_family_name("veal") == "veal"
    assert shopping_family_name("boned veal shoulder") == "veal"
    assert shopping_family_name("veal shank") == "veal"
    assert shopping_family_name("coconut milk") == "coconut milk"


async def test_assign_metadata_links_variants_to_family() -> None:
    async with SessionLocal() as db:
        veal = Ingredient(name="veal")
        shoulder = Ingredient(name="boned veal shoulder")
        db.add_all([veal, shoulder])
        await db.flush()
        veal.canonical_id = veal.id
        shoulder.canonical_id = shoulder.id

        await assign_ingredient_metadata(db, [veal, shoulder])
        await db.commit()

        family = await db.scalar(
            select(IngredientFamily).where(IngredientFamily.name == "veal")
        )
        assert family is not None
        assert veal.family_id == family.id
        assert shoulder.family_id == family.id
