from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models import UploadStatus

TINY_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


async def _auth_headers(client: AsyncClient, email: str = "library@example.com") -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password-123", "display_name": "Library"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_delete_cookbook_removes_it_from_library(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    monkeypatch.setattr(settings, "dev_sync_ingestion", False)
    headers = await _auth_headers(client)

    upload = await client.post(
        "/api/v1/cookbooks",
        headers=headers,
        files={"file": ("demo.pdf", TINY_PDF, "application/pdf")},
    )
    # Without a worker and with sync disabled, upload fails configuration after create —
    # seed a completed cookbook through a second path instead.
    if upload.status_code == 503:
        from uuid import uuid4

        from sqlalchemy import select

        from app.db.session import SessionLocal
        from app.models import Cookbook, User

        async with SessionLocal() as db:
            user = await db.scalar(select(User).where(User.email == "library@example.com"))
            assert user is not None
            storage = tmp_path / f"{uuid4()}.pdf"
            storage.write_bytes(TINY_PDF)
            book = Cookbook(
                user_id=user.id,
                title="Demo Book",
                original_filename="demo.pdf",
                content_type="application/pdf",
                storage_path=str(storage),
                status=UploadStatus.failed,
                progress=0,
                error="No recipes could be identified",
            )
            db.add(book)
            await db.commit()
            await db.refresh(book)
            cookbook_id = str(book.id)
    else:
        cookbook_id = upload.json()["id"]

    listed = await client.get("/api/v1/cookbooks", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == cookbook_id for item in listed.json())

    deleted = await client.delete(f"/api/v1/cookbooks/{cookbook_id}", headers=headers)
    assert deleted.status_code == 200

    listed_after = await client.get("/api/v1/cookbooks", headers=headers)
    assert listed_after.status_code == 200
    assert all(item["id"] != cookbook_id for item in listed_after.json())


@pytest.mark.asyncio
async def test_retry_failed_cookbook(client: AsyncClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    monkeypatch.setattr(settings, "dev_sync_ingestion", True)

    async def fake_process(cookbook_id: str) -> None:
        from uuid import UUID

        from app.db.session import SessionLocal
        from app.models import Cookbook

        async with SessionLocal() as db:
            cookbook = await db.get(Cookbook, UUID(cookbook_id))
            if cookbook:
                cookbook.status = UploadStatus.completed
                cookbook.progress = 100
                cookbook.error = None
                await db.commit()

    monkeypatch.setattr("app.api.routes.cookbooks.process_cookbook", fake_process)
    headers = await _auth_headers(client, email="retry@example.com")

    from uuid import uuid4

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Cookbook, User

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "retry@example.com"))
        assert user is not None
        storage = tmp_path / f"{uuid4()}.pdf"
        storage.write_bytes(TINY_PDF)
        book = Cookbook(
            user_id=user.id,
            title="Retry Book",
            original_filename="retry.pdf",
            content_type="application/pdf",
            storage_path=str(storage),
            status=UploadStatus.failed,
            progress=40,
            error="No recipes could be identified",
        )
        db.add(book)
        await db.commit()
        await db.refresh(book)
        cookbook_id = str(book.id)

    retried = await client.post(f"/api/v1/cookbooks/{cookbook_id}/retry", headers=headers)
    assert retried.status_code == 202
    body = retried.json()
    assert body["id"] == cookbook_id
    assert body["error"] is None

    status = await client.get(f"/api/v1/cookbooks/{cookbook_id}", headers=headers)
    assert status.status_code == 200
    assert status.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_update_cookbook_enabled_state(client: AsyncClient) -> None:
    headers = await _auth_headers(client, email="enabled@example.com")

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Cookbook, User

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "enabled@example.com"))
        assert user is not None
        book = Cookbook(
            user_id=user.id,
            title="Toggle Book",
            original_filename="toggle.pdf",
            content_type="application/pdf",
            storage_path="/tmp/toggle.pdf",
            status=UploadStatus.completed,
        )
        db.add(book)
        await db.commit()
        await db.refresh(book)
        cookbook_id = str(book.id)

    updated = await client.patch(
        f"/api/v1/cookbooks/{cookbook_id}",
        headers=headers,
        json={"enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    listed = await client.get("/api/v1/cookbooks", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["enabled"] is False


@pytest.mark.asyncio
async def test_upload_cleans_file_when_database_setup_fails(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "upload_dir", tmp_path)

    async def fail_catalog(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        "app.api.routes.cookbooks.find_or_create_catalog_cookbook",
        fail_catalog,
    )
    headers = await _auth_headers(client, email="cleanup@example.com")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await client.post(
            "/api/v1/cookbooks",
            headers=headers,
            files={"file": ("cleanup.pdf", TINY_PDF, "application/pdf")},
        )

    assert list(tmp_path.glob("*.pdf")) == []
