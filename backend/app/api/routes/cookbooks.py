import hashlib
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.models import Cookbook, Recipe, UploadStatus
from app.schemas.api import CookbookOut, Message
from app.services.catalog import find_or_create_catalog_cookbook
from app.services.ingestion import cover_media_type, process_cookbook
from app.services.recipe_images import delete_cookbook_recipe_images

router = APIRouter(prefix="/cookbooks", tags=["cookbooks"])

MIME_BY_SUFFIX = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".epub": {"application/epub+zip", "application/zip", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
}

CONTENT_TYPE_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".epub": "application/epub+zip",
    ".txt": "text/plain",
}


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return True
    if b"\x00" in data:
        return False
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            data.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def recipe_count_expression():
    return (
        select(func.count(Recipe.id))
        .where(Recipe.cookbook_id == Cookbook.id)
        .correlate(Cookbook)
        .scalar_subquery()
    )


def cookbook_cover_url(cookbook: Cookbook) -> str | None:
    if not cookbook.cover_path:
        return None
    return f"{settings.api_prefix}/cookbooks/{cookbook.id}/cover"


def with_cover_url(cookbook: Cookbook) -> Cookbook:
    cookbook.cover_url = cookbook_cover_url(cookbook)
    return cookbook


async def with_recipe_count(db: DB, cookbook: Cookbook) -> Cookbook:
    count = await db.scalar(select(func.count(Recipe.id)).where(Recipe.cookbook_id == cookbook.id))
    cookbook.recipe_count = int(count or 0)
    return with_cover_url(cookbook)


async def owned_cookbook(db: DB, user_id: uuid.UUID, cookbook_id: uuid.UUID) -> Cookbook:
    cookbook = await db.scalar(
        select(Cookbook).where(Cookbook.id == cookbook_id, Cookbook.user_id == user_id)
    )
    if cookbook is None:
        raise HTTPException(status_code=404, detail="Cookbook not found")
    return cookbook


def resolve_cover_file(cover_path: str) -> Path:
    upload_root = settings.upload_dir.resolve()
    candidate = (settings.upload_dir / cover_path).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Cover not found") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Cover not found")
    return candidate


async def enqueue_ingestion(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DB,
    cookbook: Cookbook,
) -> Cookbook:
    arq_pool = getattr(request.app.state, "arq_pool", None)
    fallback_enabled = settings.dev_sync_ingestion and not settings.is_production
    if arq_pool is not None:
        try:
            await arq_pool.enqueue_job(
                "process_cookbook",
                str(cookbook.id),
                _job_id=f"cookbook:{cookbook.id}:{uuid.uuid4().hex}",
            )
            return cookbook
        except Exception:
            if not fallback_enabled:
                cookbook.status = UploadStatus.failed
                cookbook.error = "Ingestion queue is unavailable"
                await db.commit()
                raise HTTPException(
                    status_code=503,
                    detail="Ingestion queue is unavailable",
                ) from None
    if fallback_enabled:
        background_tasks.add_task(process_cookbook, str(cookbook.id))
        return cookbook
    cookbook.status = UploadStatus.failed
    cookbook.error = "No ingestion worker is configured"
    await db.commit()
    raise HTTPException(status_code=503, detail="Ingestion worker is unavailable")


@router.get("", response_model=list[CookbookOut])
async def list_cookbooks(db: DB, user: CurrentUser) -> list[Cookbook]:
    rows = (
        await db.execute(
            select(Cookbook, recipe_count_expression().label("recipe_count"))
            .where(Cookbook.user_id == user.id)
            .order_by(Cookbook.created_at.desc())
        )
    ).all()
    cookbooks: list[Cookbook] = []
    for cookbook, recipe_count in rows:
        cookbook.recipe_count = int(recipe_count or 0)
        cookbooks.append(with_cover_url(cookbook))
    return cookbooks


@router.post("", response_model=CookbookOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_cookbook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> Cookbook:
    original = Path(file.filename or "cookbook")
    suffix = original.suffix.lower()
    content_type = (file.content_type or "application/octet-stream").lower()
    if suffix not in MIME_BY_SUFFIX or content_type not in MIME_BY_SUFFIX[suffix]:
        raise HTTPException(
            status_code=415,
            detail="Only PDF, EPUB, and TXT uploads are supported",
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.upload_dir / f"{uuid.uuid4()}{suffix}"
    total = 0
    first = b""
    digest = hashlib.sha256()
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                if not first:
                    # Keep enough bytes for text sniffing and PDF/EPUB magic checks.
                    first = chunk[:4096]
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="Upload exceeds configured size limit",
                    )
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    signature_ok = (
        (suffix == ".pdf" and first.startswith(b"%PDF"))
        or (suffix == ".epub" and first.startswith(b"PK"))
        or (suffix == ".txt" and _looks_like_text(first))
    )
    if not signature_ok:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="File signature does not match its extension")

    content_sha256 = digest.hexdigest()
    cookbook_title = (title or original.stem).strip()[:255] or "Untitled cookbook"
    await find_or_create_catalog_cookbook(db, content_sha256=content_sha256, title=cookbook_title)

    cookbook = Cookbook(
        user_id=user.id,
        title=cookbook_title,
        original_filename=original.name[:255],
        content_type=CONTENT_TYPE_BY_SUFFIX[suffix],
        storage_path=str(destination.resolve()),
        content_sha256=content_sha256,
    )
    db.add(cookbook)
    await db.commit()
    await db.refresh(cookbook)
    cookbook.recipe_count = 0
    with_cover_url(cookbook)
    return await enqueue_ingestion(request, background_tasks, db, cookbook)


@router.post(
    "/{cookbook_id}/retry",
    response_model=CookbookOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_cookbook(
    cookbook_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DB,
    user: CurrentUser,
) -> Cookbook:
    cookbook = await owned_cookbook(db, user.id, cookbook_id)
    if cookbook.status in {UploadStatus.pending, UploadStatus.processing}:
        raise HTTPException(status_code=409, detail="Cookbook is already being processed")
    if not Path(cookbook.storage_path).is_file():
        raise HTTPException(status_code=409, detail="Original cookbook file is no longer available")

    cookbook.status = UploadStatus.pending
    cookbook.progress = 0
    cookbook.error = None
    await db.commit()
    await db.refresh(cookbook)
    enqueued = await enqueue_ingestion(request, background_tasks, db, cookbook)
    return await with_recipe_count(db, enqueued)


@router.get("/{cookbook_id}/cover")
async def cookbook_cover(cookbook_id: uuid.UUID, db: DB, user: CurrentUser) -> FileResponse:
    cookbook = await owned_cookbook(db, user.id, cookbook_id)
    if not cookbook.cover_path:
        raise HTTPException(status_code=404, detail="Cover not found")
    path = resolve_cover_file(cookbook.cover_path)
    return FileResponse(path, media_type=cover_media_type(cookbook.cover_path))


@router.get("/{cookbook_id}", response_model=CookbookOut)
async def get_cookbook(cookbook_id: uuid.UUID, db: DB, user: CurrentUser) -> Cookbook:
    cookbook = await owned_cookbook(db, user.id, cookbook_id)
    return await with_recipe_count(db, cookbook)


@router.get("/{cookbook_id}/status", response_model=CookbookOut)
async def cookbook_status(cookbook_id: uuid.UUID, db: DB, user: CurrentUser) -> Cookbook:
    cookbook = await owned_cookbook(db, user.id, cookbook_id)
    return await with_recipe_count(db, cookbook)


@router.delete("/{cookbook_id}", response_model=Message)
async def delete_cookbook(cookbook_id: uuid.UUID, db: DB, user: CurrentUser) -> Message:
    cookbook = await owned_cookbook(db, user.id, cookbook_id)
    storage_path = Path(cookbook.storage_path)
    cover_relative = cookbook.cover_path
    cookbook_id_str = str(cookbook.id)
    await db.delete(cookbook)
    await db.commit()
    storage_path.unlink(missing_ok=True)
    if cover_relative:
        try:
            resolve_cover_file(cover_relative).unlink(missing_ok=True)
        except HTTPException:
            pass
    delete_cookbook_recipe_images(cookbook_id_str)
    return Message(detail="Cookbook deleted")
