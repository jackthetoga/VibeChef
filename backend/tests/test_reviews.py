"""Catalog identity and shared recipe reviews."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Cookbook, Recipe, UploadStatus, User
from app.services.catalog import (
    find_or_create_catalog_cookbook,
    recipe_fingerprint,
    upsert_catalog_recipe,
)
from app.services.ingestion import ExtractedIngredient, ExtractedRecipe

TINY_PDF_A = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
TINY_PDF_B = b"%PDF-1.4\n2 0 obj<< /Type /Catalog >>endobj\ntrailer<<>>\n%%EOF\n"


def _fingerprint_for(title: str = "Tomato Soup") -> str:
    fingerprint = recipe_fingerprint(
        title=title,
        ingredient_raw_texts=["2 cups tomatoes", "1 tsp salt"],
        steps=["Simmer the tomatoes.", "Season and serve."],
    )
    assert fingerprint is not None
    return fingerprint


async def _register(client: AsyncClient, email: str, name: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password-123", "display_name": name},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_linked_recipe(
    *,
    email: str,
    content_sha256: str,
    title: str = "Tomato Soup",
    cookbook_title: str = "Shared Book",
) -> tuple[str, str]:
    """Create a private recipe linked to a catalog recipe and return both IDs."""
    fingerprint = _fingerprint_for(title)
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        assert user is not None
        catalog_cookbook = await find_or_create_catalog_cookbook(
            db, content_sha256=content_sha256, title=cookbook_title
        )
        catalog_recipe = await upsert_catalog_recipe(
            db,
            catalog_cookbook=catalog_cookbook,
            fingerprint=fingerprint,
            title=title,
        )
        storage = settings.upload_dir / f"{uuid4()}.pdf"
        storage.parent.mkdir(parents=True, exist_ok=True)
        storage.write_bytes(TINY_PDF_A)
        cookbook = Cookbook(
            user_id=user.id,
            title=cookbook_title,
            original_filename="shared.pdf",
            content_type="application/pdf",
            storage_path=str(storage),
            content_sha256=content_sha256,
            status=UploadStatus.completed,
            progress=100,
        )
        db.add(cookbook)
        await db.flush()
        recipe = Recipe(
            cookbook_id=cookbook.id,
            catalog_recipe_id=catalog_recipe.id,
            title=title,
            steps=["Simmer the tomatoes.", "Season and serve."],
            tags=[],
            parse_warnings=[],
        )
        db.add(recipe)
        await db.commit()
        await db.refresh(recipe)
        return str(recipe.id), str(catalog_recipe.id)


def test_recipe_fingerprint_stable_and_excludes_page() -> None:
    first = recipe_fingerprint(
        title="Tomato Soup",
        ingredient_raw_texts=["2 cups tomatoes", "1 tsp salt"],
        steps=["Simmer.", "Serve."],
    )
    second = recipe_fingerprint(
        title="  tomato   soup ",
        ingredient_raw_texts=["2 Cups Tomatoes", "1 TSP salt"],
        steps=["Simmer.", "Serve."],
    )
    assert first == second
    assert recipe_fingerprint(title="x", ingredient_raw_texts=[], steps=["a"]) is None


@pytest.mark.asyncio
async def test_same_content_sha_merges_reviews(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    headers_a = await _register(client, "alice@example.com", "Alice")
    headers_b = await _register(client, "bob@example.com", "Bob")
    content_sha = "a" * 64

    recipe_a, catalog_id_a = await _seed_linked_recipe(
        email="alice@example.com", content_sha256=content_sha
    )
    recipe_b, catalog_id_b = await _seed_linked_recipe(
        email="bob@example.com", content_sha256=content_sha
    )
    assert catalog_id_a == catalog_id_b

    created = await client.post(
        f"/api/v1/catalog/recipes/{catalog_id_a}/reviews",
        headers=headers_a,
        json={"rating": 5, "body": "Excellent soup"},
    )
    assert created.status_code == 201

    listed_for_b = await client.get(
        f"/api/v1/catalog/recipes/{catalog_id_b}/reviews",
        headers=headers_b,
    )
    assert listed_for_b.status_code == 200
    items = listed_for_b.json()["items"]
    assert len(items) == 1
    assert items[0]["body"] == "Excellent soup"
    assert items[0]["display_name"] == "Alice"

    detail_b = await client.get(f"/api/v1/recipes/{recipe_b}", headers=headers_b)
    assert detail_b.status_code == 200
    payload = detail_b.json()
    assert payload["catalog_recipe_id"] == catalog_id_a
    assert float(payload["user_rating_avg"]) == 5.0
    assert payload["user_rating_count"] == 1
    # Source rating remains independent / unset here.
    assert payload["rating"] is None

    detail_a = await client.get(f"/api/v1/recipes/{recipe_a}", headers=headers_a)
    assert detail_a.json()["user_rating_count"] == 1


@pytest.mark.asyncio
async def test_different_content_sha_isolates_reviews(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    headers_a = await _register(client, "carol@example.com", "Carol")
    headers_b = await _register(client, "dave@example.com", "Dave")

    _, catalog_a = await _seed_linked_recipe(email="carol@example.com", content_sha256="b" * 64)
    _, catalog_b = await _seed_linked_recipe(email="dave@example.com", content_sha256="c" * 64)
    assert catalog_a != catalog_b

    created = await client.post(
        f"/api/v1/catalog/recipes/{catalog_a}/reviews",
        headers=headers_a,
        json={"rating": 4, "body": "Only on book B"},
    )
    assert created.status_code == 201

    listed_b = await client.get(
        f"/api/v1/catalog/recipes/{catalog_b}/reviews",
        headers=headers_b,
    )
    assert listed_b.json()["items"] == []


@pytest.mark.asyncio
async def test_reingest_preserves_catalog_recipe_id(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    headers = await _register(client, "erin@example.com", "Erin")
    content_sha = "d" * 64
    fingerprint = _fingerprint_for()

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "erin@example.com"))
        assert user is not None
        catalog_cookbook = await find_or_create_catalog_cookbook(
            db, content_sha256=content_sha, title="Retry Book"
        )
        catalog_recipe = await upsert_catalog_recipe(
            db,
            catalog_cookbook=catalog_cookbook,
            fingerprint=fingerprint,
            title="Tomato Soup",
        )
        catalog_id = catalog_recipe.id
        storage = tmp_path / f"{uuid4()}.pdf"
        storage.write_bytes(TINY_PDF_A)
        cookbook = Cookbook(
            user_id=user.id,
            title="Retry Book",
            original_filename="retry.pdf",
            content_type="application/pdf",
            storage_path=str(storage),
            content_sha256=content_sha,
            status=UploadStatus.completed,
            progress=100,
        )
        db.add(cookbook)
        await db.flush()
        first = Recipe(
            cookbook_id=cookbook.id,
            catalog_recipe_id=catalog_id,
            title="Tomato Soup",
            steps=["Simmer the tomatoes.", "Season and serve."],
            tags=[],
            parse_warnings=[],
        )
        db.add(first)
        await db.commit()
        cookbook_id = cookbook.id
        first_recipe_id = first.id

    review = await client.post(
        f"/api/v1/catalog/recipes/{catalog_id}/reviews",
        headers=headers,
        json={"rating": 5, "body": "Keep me"},
    )
    assert review.status_code == 201

    # Simulate wipe-and-replace re-ingest linking to the same catalog fingerprint.
    async with SessionLocal() as db:
        cookbook = await db.get(Cookbook, cookbook_id)
        assert cookbook is not None
        from sqlalchemy import delete

        await db.execute(delete(Recipe).where(Recipe.cookbook_id == cookbook.id))
        catalog_cookbook = await find_or_create_catalog_cookbook(
            db, content_sha256=content_sha, title=cookbook.title
        )
        catalog_recipe = await upsert_catalog_recipe(
            db,
            catalog_cookbook=catalog_cookbook,
            fingerprint=fingerprint,
            title="Tomato Soup",
        )
        assert catalog_recipe.id == catalog_id
        replacement = Recipe(
            cookbook_id=cookbook.id,
            catalog_recipe_id=catalog_recipe.id,
            title="Tomato Soup",
            steps=["Simmer the tomatoes.", "Season and serve."],
            tags=[],
            parse_warnings=[],
        )
        db.add(replacement)
        await db.commit()
        await db.refresh(replacement)
        new_recipe_id = replacement.id

    assert new_recipe_id != first_recipe_id
    listed = await client.get(
        f"/api/v1/catalog/recipes/{catalog_id}/reviews",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["body"] == "Keep me"

    detail = await client.get(f"/api/v1/recipes/{new_recipe_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["catalog_recipe_id"] == str(catalog_id)
    assert detail.json()["user_rating_count"] == 1


@pytest.mark.asyncio
async def test_upload_stores_content_sha256(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    monkeypatch.setattr(settings, "dev_sync_ingestion", False)

    async def fake_process(cookbook_id: str) -> None:
        async with SessionLocal() as db:
            cookbook = await db.get(Cookbook, __import__("uuid").UUID(cookbook_id))
            if cookbook:
                cookbook.status = UploadStatus.completed
                cookbook.progress = 100
                cookbook.error = None
                await db.commit()

    monkeypatch.setattr("app.api.routes.cookbooks.process_cookbook", fake_process)
    headers = await _register(client, "frank@example.com", "Frank")
    upload = await client.post(
        "/api/v1/cookbooks",
        headers=headers,
        files={"file": ("demo.pdf", TINY_PDF_A, "application/pdf")},
    )
    assert upload.status_code in {202, 503}
    if upload.status_code == 503:
        pytest.skip("Ingestion worker unavailable in this environment")

    cookbook_id = upload.json()["id"]
    async with SessionLocal() as db:
        cookbook = await db.get(Cookbook, __import__("uuid").UUID(cookbook_id))
        assert cookbook is not None
        assert cookbook.content_sha256
        assert len(cookbook.content_sha256) == 64
        catalog = await find_or_create_catalog_cookbook(db, content_sha256=cookbook.content_sha256)
        assert catalog.content_sha256 == cookbook.content_sha256


@pytest.mark.asyncio
async def test_review_photo_upload(client: AsyncClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    headers = await _register(client, "gina@example.com", "Gina")
    _, catalog_id = await _seed_linked_recipe(email="gina@example.com", content_sha256="e" * 64)
    created = await client.post(
        f"/api/v1/catalog/recipes/{catalog_id}/reviews",
        headers=headers,
        json={"rating": 3, "body": "With photo"},
    )
    assert created.status_code == 201

    # Minimal valid-ish JPEG header bytes (not decoded by server beyond content-type).
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
    photo = await client.post(
        f"/api/v1/catalog/recipes/{catalog_id}/reviews/me/photos",
        headers=headers,
        files={"file": ("plate.jpg", jpeg, "image/jpeg")},
    )
    assert photo.status_code == 201
    payload = photo.json()
    assert len(payload["photos"]) == 1
    photo_url = payload["photos"][0]["url"]
    fetched = await client.get(photo_url)
    assert fetched.status_code == 200


def test_extracted_recipe_fingerprint_matches_helper() -> None:
    extracted = ExtractedRecipe(
        title="Tomato Soup",
        ingredients=[
            ExtractedIngredient(canonical_name="tomatoes", raw_text="2 cups tomatoes"),
            ExtractedIngredient(canonical_name="salt", raw_text="1 tsp salt"),
        ],
        steps=["Simmer the tomatoes.", "Season and serve."],
        source_page=12,
    )
    assert (
        recipe_fingerprint(
            title=extracted.title,
            ingredient_raw_texts=[item.raw_text for item in extracted.ingredients],
            steps=extracted.steps,
        )
        == _fingerprint_for()
    )
