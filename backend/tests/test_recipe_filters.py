from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Cookbook, Recipe, User


async def _seed_recipes(client: AsyncClient) -> dict[str, str]:
    registration = await client.post(
        "/api/v1/auth/register",
        json={"email": "filters@example.com", "password": "password-123"},
    )
    token = registration.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "filters@example.com"))
        cookbook = Cookbook(
            user_id=user.id,
            title="Filter Book",
            original_filename="filters.pdf",
            content_type="application/pdf",
            storage_path=str(Path("/tmp/filters.pdf")),
        )
        db.add(cookbook)
        await db.flush()
        db.add_all(
            [
                Recipe(
                    cookbook_id=cookbook.id,
                    title="Italian Pasta Bowl",
                    cuisine="Italian",
                    protein_grams=28,
                    rating=4.8,
                    rating_count=40,
                    tags=["main dish", "protein-foods", "grains", "pasta"],
                ),
                Recipe(
                    cookbook_id=cookbook.id,
                    title="Mexican Salad",
                    cuisine="Mexican",
                    protein_grams=12,
                    rating=4.2,
                    rating_count=18,
                    tags=["salad", "vegetables", "fruits"],
                ),
                Recipe(
                    cookbook_id=cookbook.id,
                    title="Chinese Soup",
                    cuisine="Chinese",
                    protein_grams=22,
                    rating=3.9,
                    rating_count=11,
                    tags=["soup", "protein foods", "vegetables"],
                ),
                Recipe(
                    cookbook_id=cookbook.id,
                    title="Unrated Side",
                    cuisine=None,
                    protein_grams=5,
                    tags=["side dish", "dairy"],
                ),
            ]
        )
        await db.commit()
    return headers


@pytest.mark.asyncio
async def test_category_food_group_and_protein_stack(client: AsyncClient) -> None:
    headers = await _seed_recipes(client)

    stacked = await client.get(
        "/api/v1/recipes",
        headers=headers,
        params={
            "category": "main dish",
            "food_group": "protein-foods",
            "min_protein": 20,
            "tag": "pasta",
        },
    )
    assert stacked.status_code == 200
    titles = [item["title"] for item in stacked.json()["items"]]
    assert titles == ["Italian Pasta Bowl"]


@pytest.mark.asyncio
async def test_cuisine_is_exclusive_single_value(client: AsyncClient) -> None:
    headers = await _seed_recipes(client)

    italian = await client.get(
        "/api/v1/recipes",
        headers=headers,
        params={"cuisine": "Italian"},
    )
    assert italian.status_code == 200
    assert [item["title"] for item in italian.json()["items"]] == ["Italian Pasta Bowl"]

    mexican = await client.get(
        "/api/v1/recipes",
        headers=headers,
        params={"cuisine": "Mexican"},
    )
    assert mexican.status_code == 200
    assert [item["title"] for item in mexican.json()["items"]] == ["Mexican Salad"]


@pytest.mark.asyncio
async def test_food_group_matches_label_or_key_aliases(client: AsyncClient) -> None:
    headers = await _seed_recipes(client)

    response = await client.get(
        "/api/v1/recipes",
        headers=headers,
        params={"food_group": "protein-foods", "sort": "title", "order": "asc"},
    )
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["Chinese Soup", "Italian Pasta Bowl"]


@pytest.mark.asyncio
async def test_sort_by_highest_rating(client: AsyncClient) -> None:
    headers = await _seed_recipes(client)

    response = await client.get(
        "/api/v1/recipes",
        headers=headers,
        params={"sort": "rating", "order": "desc"},
    )
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles[:3] == ["Italian Pasta Bowl", "Mexican Salad", "Chinese Soup"]
    assert titles[-1] == "Unrated Side"
