import pytest
from httpx import AsyncClient
from pathlib import Path
from sqlalchemy import select
from unittest.mock import AsyncMock, patch

from app.db.session import SessionLocal
from app.models import Cookbook, Recipe, User
from app.services.recipe_tagging import (
    TagAssignment,
    assign_recipe_tags,
    tag_recipe_heuristic,
)


def test_heuristic_pasta_becomes_main_dish_with_dish_tag() -> None:
    result = tag_recipe_heuristic(
        title="Spaghetti Bolognese",
        ingredient_names=["spaghetti", "ground beef", "tomato", "parmesan cheese"],
        ingredient_categories=["Grains & Pasta", "Meat & Seafood", "Produce", "Dairy & Eggs"],
    )
    assert result.is_useful
    assert result.tag_source == "heuristic"
    assert "main dish" in result.tags
    assert "pasta" in result.tags
    assert "protein-foods" in result.tags
    assert "grains" in result.tags
    assert "dairy" in result.tags


def test_heuristic_soup_and_italian_cuisine() -> None:
    result = tag_recipe_heuristic(title="Italian Minestrone Soup")
    assert result.category == "soup"
    assert result.cuisine == "Italian"
    assert result.is_useful


def test_heuristic_other_title_without_ingredients_is_not_useful() -> None:
    result = tag_recipe_heuristic(title="Tuesday Special")
    assert not result.is_useful
    assert result.tag_source is None


@pytest.mark.asyncio
async def test_assign_falls_back_to_llm_when_heuristic_empty() -> None:
    llm_result = TagAssignment(
        cuisine="Mexican",
        tags=["main dish", "protein-foods"],
        tag_source="llm",
    )
    with patch(
        "app.services.recipe_tagging.tag_recipe_llm",
        new=AsyncMock(return_value=llm_result),
    ) as mocked:
        result = await assign_recipe_tags(title="Mystery Plate", prefer_existing=False)
    mocked.assert_awaited_once()
    assert result.tag_source == "llm"
    assert result.cuisine == "Mexican"
    assert "main dish" in result.tags


@pytest.mark.asyncio
async def test_assign_preserves_myplate_tags() -> None:
    result = await assign_recipe_tags(
        title="Apple Sandwiches",
        tags=["myplate", "main dish", "fruits", "protein-foods"],
        prefer_existing=True,
    )
    assert result.tag_source == "myplate"
    assert "main dish" in result.tags
    assert "fruits" in result.tags


@pytest.mark.asyncio
async def test_patch_recipe_tags_sets_manual_and_filters(
    client: AsyncClient,
) -> None:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "tags@example.com", "password": "password-123"},
    )
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "tags@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Tag Book",
            original_filename="tags.pdf",
            content_type="application/pdf",
            storage_path=str(Path("/tmp/tags.pdf")),
        )
        db.add(cookbook)
        await db.flush()
        recipe = Recipe(
            cookbook_id=cookbook.id,
            title="Plain Bowl",
            cuisine=None,
            tags=[],
            tag_source="heuristic",
        )
        db.add(recipe)
        await db.commit()
        recipe_id = str(recipe.id)

    patched = await client.patch(
        f"/api/v1/recipes/{recipe_id}",
        headers=headers,
        json={
            "cuisine": "Italian",
            "category": "main dish",
            "food_groups": ["protein-foods"],
            "dish_tags": ["pasta"],
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["cuisine"] == "Italian"
    assert body["tag_source"] == "manual"
    assert "main dish" in body["tags"]
    assert "protein-foods" in body["tags"]
    assert "pasta" in body["tags"]

    filtered = await client.get(
        "/api/v1/recipes",
        headers=headers,
        params={
            "cuisine": "Italian",
            "category": "main dish",
            "food_group": "protein-foods",
            "tag": "pasta",
        },
    )
    assert filtered.status_code == 200
    titles = [item["title"] for item in filtered.json()["items"]]
    assert titles == ["Plain Bowl"]
