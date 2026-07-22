"""Recipe imagery: cookbook extraction and photorealistic corpus matching."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import select

from app.core.config import settings
from app.models import ImageSource
from app.services.media_bounds import validate_epub_archive, validate_pdf_document

logger = logging.getLogger(__name__)

PHOTOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "recipe_photos"
MANIFEST_PATH = PHOTOS_DIR / "manifest.json"
MIN_EXTRACTED_BYTES = 2_500
MIN_IMAGE_DIMENSION = 80
MIN_CORPUS_SCORE = 3.0
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "or",
        "the",
        "with",
        "without",
        "for",
        "of",
        "in",
        "on",
        "to",
        "from",
        "style",
        "recipe",
        "homemade",
        "classic",
        "easy",
        "best",
        "simple",
        "variation",
    }
)


@dataclass(frozen=True)
class ImageAssignment:
    path: str
    source: ImageSource
    key: str | None = None


@dataclass(frozen=True)
class CorpusEntry:
    id: str
    file: str
    tags: frozenset[str]
    cuisine: frozenset[str]


def recipe_image_url(recipe_id: uuid.UUID, image_path: str | None) -> str | None:
    if not image_path:
        return None
    return f"{settings.api_prefix}/recipes/{recipe_id}/image"


def recipe_image_media_type(image_path: str) -> str:
    guessed, _ = mimetypes.guess_type(image_path)
    return guessed or "application/octet-stream"


def resolve_recipe_image_file(image_path: str) -> Path:
    """Resolve a stored image_path to an on-disk file."""
    relative = image_path.replace("\\", "/").lstrip("/")
    if ".." in relative.split("/"):
        raise FileNotFoundError(image_path)

    if relative.startswith("corpus/"):
        candidate = (PHOTOS_DIR / relative.removeprefix("corpus/")).resolve()
        try:
            candidate.relative_to(PHOTOS_DIR.resolve())
        except ValueError as exc:
            raise FileNotFoundError(image_path) from exc
        if not candidate.is_file():
            raise FileNotFoundError(image_path)
        return candidate

    # Legacy category SVG paths — no longer served.
    if relative.startswith("categories/"):
        raise FileNotFoundError(image_path)

    upload_root = settings.upload_dir.resolve()
    candidate = (settings.upload_dir / relative).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise FileNotFoundError(image_path) from exc
    if not candidate.is_file():
        raise FileNotFoundError(image_path)
    return candidate


def _guess_extension(name: str, content: bytes) -> str:
    lower = name.lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if lower.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if content.startswith(b"\x89PNG"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return ".webp"
    return ".bin"


def _save_extracted_image(
    content: bytes,
    dest_dir: Path,
    cookbook_id: str,
    recipe_id: str,
    name: str,
) -> str:
    extension = _guess_extension(name, content)
    relative = f"recipes/{cookbook_id}/{recipe_id}{extension}"
    target = dest_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return relative


def _image_too_small(content: bytes) -> bool:
    if len(content) < MIN_EXTRACTED_BYTES:
        return True
    if content.startswith(b"\x89PNG") and len(content) < 200:
        return True
    return False


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        if raw in _STOPWORDS or len(raw) < 3:
            continue
        token = raw[:-1] if len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss") else raw
        tokens.add(token)
    return tokens


def clear_corpus_cache() -> None:
    load_corpus_manifest.cache_clear()


@lru_cache(maxsize=1)
def load_corpus_manifest() -> tuple[CorpusEntry, ...]:
    if not MANIFEST_PATH.is_file():
        return ()
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load photo corpus manifest: %s", exc)
        return ()
    if not isinstance(raw, list):
        return ()
    entries: list[CorpusEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry_id = str(item.get("id") or "").strip()
        file_name = str(item.get("file") or "").strip().replace("\\", "/")
        if not entry_id or not file_name or ".." in file_name.split("/"):
            continue
        tags = _tokenize(" ".join(str(tag) for tag in (item.get("tags") or [])))
        cuisine = _tokenize(" ".join(str(c) for c in (item.get("cuisine") or [])))
        if not tags and not cuisine:
            continue
        entries.append(
            CorpusEntry(
                id=entry_id,
                file=file_name.lstrip("/"),
                tags=frozenset(tags),
                cuisine=frozenset(cuisine),
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.id))


def match_corpus_entry(
    title: str,
    cuisine: str | None = None,
    tags: list[str] | None = None,
) -> CorpusEntry | None:
    catalog = load_corpus_manifest()
    if not catalog:
        return None
    title_tokens = _tokenize(title)
    tag_tokens = _tokenize(" ".join(tags or []))
    cuisine_tokens = _tokenize(cuisine or "")
    if not title_tokens and not tag_tokens and not cuisine_tokens:
        return None

    best: CorpusEntry | None = None
    best_score = -1.0
    for entry in catalog:
        score = 0.0
        score += 3.0 * len(title_tokens & entry.tags)
        score += 2.0 * len(tag_tokens & entry.tags)
        score += 1.5 * len(cuisine_tokens & entry.cuisine)
        score += 1.0 * len(title_tokens & entry.cuisine)
        if score > best_score or (score == best_score and best is not None and entry.id < best.id):
            best = entry
            best_score = score
    if best is None or best_score < MIN_CORPUS_SCORE:
        return None
    return best


def corpus_assignment(
    title: str,
    cuisine: str | None = None,
    tags: list[str] | None = None,
) -> ImageAssignment | None:
    entry = match_corpus_entry(title, cuisine, tags)
    if entry is None:
        return None
    relative_file = entry.file
    disk_path = PHOTOS_DIR / relative_file
    if not disk_path.is_file():
        logger.warning("Corpus entry %s missing file %s", entry.id, relative_file)
        return None
    return ImageAssignment(
        path=f"corpus/{relative_file}",
        source=ImageSource.corpus,
        key=f"corpus:{entry.id}",
    )


def _extract_epub_images_by_title(path: Path) -> dict[str, tuple[bytes, str]]:
    """Map normalized recipe titles to (image_bytes, filename) from nearby <img> tags."""
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    validate_epub_archive(path)
    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    items_by_name: dict[str, object] = {}
    for item in book.get_items():
        name = (item.get_name() or "").replace("\\", "/")
        if name:
            items_by_name[name] = item
            items_by_name[name.split("/")[-1]] = item

    def resolve_image(src: str, doc_name: str) -> tuple[bytes, str] | None:
        raw = unquote(src.strip())
        if not raw or raw.startswith("data:"):
            return None
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"}:
            return None
        href = parsed.path or raw
        candidates = [href.lstrip("/")]
        doc_dir = str(Path(doc_name).parent).replace("\\", "/")
        if doc_dir and doc_dir != ".":
            candidates.append(f"{doc_dir}/{href}".replace("//", "/"))
        candidates.append(Path(href).name)
        for candidate in candidates:
            item = items_by_name.get(candidate) or items_by_name.get(candidate.split("/")[-1])
            if item is None:
                continue
            content = item.get_content()
            if not content or _image_too_small(content):
                continue
            name = getattr(item, "get_name", lambda: candidate)() or candidate
            lower = name.lower()
            if "cover" in lower or "icon" in lower or "logo" in lower:
                continue
            return content, name
        return None

    found: dict[str, tuple[bytes, str]] = {}
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        doc_name = item.get_name() or ""
        soup = BeautifulSoup(item.get_content(), "html.parser")
        current_title: str | None = None
        best_for_title: tuple[bytes, str] | None = None

        def flush() -> None:
            nonlocal current_title, best_for_title
            if current_title and best_for_title:
                key = _normalize_title(current_title)
                existing = found.get(key)
                if existing is None or len(best_for_title[0]) > len(existing[0]):
                    found[key] = best_for_title
            current_title = None
            best_for_title = None

        for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "img", "figure"]):
            if node.name == "img" or (node.name == "figure" and node.find("img")):
                img = node if node.name == "img" else node.find("img")
                if img is None or current_title is None:
                    continue
                src = img.get("src") or img.get("data-src")
                if not src:
                    continue
                resolved = resolve_image(src, doc_name)
                if resolved is None:
                    continue
                if best_for_title is None or len(resolved[0]) > len(best_for_title[0]):
                    best_for_title = resolved
                continue

            classes = {str(value).lower() for value in (node.get("class") or [])}
            text = " ".join(node.get_text(" ", strip=True).split())
            if not text:
                continue
            is_title = node.name in {"h1", "h2", "h3"} or bool(
                classes & {"rt", "rtaft", "rvh", "title", "recipe-title"}
            )
            if is_title and len(text) < 180:
                flush()
                current_title = text
        flush()
    return found


def _extract_pdf_page_image(path: Path, source_page: int | None) -> tuple[bytes, str] | None:
    if source_page is None or source_page < 1:
        return None
    import fitz

    with fitz.open(path) as document:
        validate_pdf_document(document)
        if source_page > document.page_count:
            return None
        page = document[source_page - 1]
        best: tuple[bytes, str] | None = None
        for image_info in page.get_images(full=True):
            xref = image_info[0]
            try:
                extracted = document.extract_image(xref)
            except Exception:
                continue
            content = extracted.get("image") or b""
            if len(content) > settings.max_epub_entry_bytes:
                continue
            if _image_too_small(content):
                continue
            width = int(extracted.get("width") or 0)
            height = int(extracted.get("height") or 0)
            if width and height and min(width, height) < MIN_IMAGE_DIMENSION:
                continue
            ext = extracted.get("ext") or "png"
            if best is None or len(content) > len(best[0]):
                best = (content, f"page{source_page}.{ext}")
        if best is not None:
            return best

        rect = page.rect
        clip = fitz.Rect(rect.x0, rect.y0 + rect.height * 0.35, rect.x1, rect.y1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), clip=clip, alpha=False)
        if pixmap.width * pixmap.height < 20_000:
            return None
        content = pixmap.tobytes("png")
        if _image_too_small(content):
            return None
        return content, f"page{source_page}.png"


def try_extract_recipe_image(
    cookbook_path: Path,
    *,
    cookbook_id: str,
    recipe_id: str,
    title: str,
    source_page: int | None,
    epub_images: dict[str, tuple[bytes, str]] | None = None,
    dest_dir: Path | None = None,
) -> ImageAssignment | None:
    dest = dest_dir or settings.upload_dir
    suffix = cookbook_path.suffix.lower()
    content_name: tuple[bytes, str] | None = None

    if suffix == ".epub":
        images = epub_images
        if images is None:
            try:
                images = _extract_epub_images_by_title(cookbook_path)
            except Exception as exc:
                logger.warning("EPUB image index failed for %s: %s", cookbook_id, exc)
                images = {}
        content_name = images.get(_normalize_title(title))
        if content_name is None:
            needle = _normalize_title(title)
            for key, value in images.items():
                if needle in key or key in needle:
                    content_name = value
                    break
    elif suffix == ".pdf":
        try:
            content_name = _extract_pdf_page_image(cookbook_path, source_page)
        except Exception as exc:
            logger.warning("PDF image extract failed for %s: %s", cookbook_id, exc)

    if content_name is None:
        return None
    content, name = content_name
    if _image_too_small(content):
        return None
    relative = _save_extracted_image(content, dest, cookbook_id, recipe_id, name)
    return ImageAssignment(path=relative, source=ImageSource.extracted)


def assign_image_for_recipe(
    cookbook_path: Path,
    *,
    cookbook_id: str,
    recipe_id: str,
    title: str,
    cuisine: str | None,
    tags: list[str] | None,
    source_page: int | None,
    epub_images: dict[str, tuple[bytes, str]] | None = None,
    dest_dir: Path | None = None,
) -> ImageAssignment | None:
    extracted = try_extract_recipe_image(
        cookbook_path,
        cookbook_id=cookbook_id,
        recipe_id=recipe_id,
        title=title,
        source_page=source_page,
        epub_images=epub_images,
        dest_dir=dest_dir,
    )
    if extracted is not None:
        return extracted
    return corpus_assignment(title, cuisine, tags)


def apply_assignment(recipe, assignment: ImageAssignment | None) -> None:
    """Set or clear image fields on a Recipe ORM instance."""
    if assignment is None:
        recipe.image_path = None
        recipe.image_source = None
        recipe.image_key = None
        return
    recipe.image_path = assignment.path
    recipe.image_source = assignment.source
    recipe.image_key = assignment.key


async def assign_images_for_cookbook(cookbook_id: str, cookbook_path: Path) -> None:
    """Extract or corpus-match images for every recipe in a cookbook."""
    from app.db.session import SessionLocal
    from app.models import Recipe

    epub_images: dict[str, tuple[bytes, str]] | None = None
    if cookbook_path.suffix.lower() == ".epub":
        try:
            epub_images = _extract_epub_images_by_title(cookbook_path)
        except Exception as exc:
            logger.warning("EPUB image index failed for %s: %s", cookbook_id, exc)
            epub_images = {}

    async with SessionLocal() as db:
        recipes = list(
            await db.scalars(select(Recipe).where(Recipe.cookbook_id == uuid.UUID(cookbook_id)))
        )
        for recipe in recipes:
            try:
                assignment = assign_image_for_recipe(
                    cookbook_path,
                    cookbook_id=cookbook_id,
                    recipe_id=str(recipe.id),
                    title=recipe.title,
                    cuisine=recipe.cuisine,
                    tags=list(recipe.tags or []),
                    source_page=recipe.source_page,
                    epub_images=epub_images,
                )
                apply_assignment(recipe, assignment)
            except Exception as exc:
                logger.warning(
                    "Recipe image assignment failed for %s/%s: %s",
                    cookbook_id,
                    recipe.id,
                    exc,
                )
                apply_assignment(
                    recipe, corpus_assignment(recipe.title, recipe.cuisine, list(recipe.tags or []))
                )
        await db.commit()


async def backfill_recipe_images(
    *, cookbook_id: str | None = None, force: bool = False
) -> dict[str, int]:
    """Reassign images: preserve extracted unless force; clear legacy category; try corpus."""
    from app.db.session import SessionLocal
    from app.models import Cookbook, Recipe

    cleared = 0
    corpus_hits = 0
    extracted_kept = 0
    async with SessionLocal() as db:
        statement = select(Recipe)
        if cookbook_id:
            statement = statement.where(Recipe.cookbook_id == uuid.UUID(cookbook_id))
        recipes = list(await db.scalars(statement))

        cookbook_paths: dict[uuid.UUID, Path] = {}
        if force:
            for cookbook in await db.scalars(select(Cookbook)):
                cookbook_paths[cookbook.id] = Path(cookbook.storage_path)

        for recipe in recipes:
            if recipe.image_source == ImageSource.extracted and not force:
                extracted_kept += 1
                continue

            if force:
                path = cookbook_paths.get(recipe.cookbook_id)
                if path is not None and path.is_file():
                    try:
                        assignment = assign_image_for_recipe(
                            path,
                            cookbook_id=str(recipe.cookbook_id),
                            recipe_id=str(recipe.id),
                            title=recipe.title,
                            cuisine=recipe.cuisine,
                            tags=list(recipe.tags or []),
                            source_page=recipe.source_page,
                        )
                        if recipe.image_source == ImageSource.category or (
                            recipe.image_path and str(recipe.image_path).startswith("categories/")
                        ):
                            cleared += 1
                        apply_assignment(recipe, assignment)
                        if assignment and assignment.source == ImageSource.corpus:
                            corpus_hits += 1
                        elif assignment and assignment.source == ImageSource.extracted:
                            extracted_kept += 1
                        continue
                    except Exception as exc:
                        logger.warning("Force reassign failed for %s: %s", recipe.id, exc)

            was_category = recipe.image_source == ImageSource.category or (
                recipe.image_path and str(recipe.image_path).startswith("categories/")
            )
            assignment = corpus_assignment(recipe.title, recipe.cuisine, list(recipe.tags or []))
            if assignment is not None:
                apply_assignment(recipe, assignment)
                corpus_hits += 1
                if was_category:
                    cleared += 1
            else:
                if was_category or recipe.image_path:
                    cleared += 1
                apply_assignment(recipe, None)
        await db.commit()
    return {
        "cleared": cleared,
        "corpus_hits": corpus_hits,
        "extracted_kept": extracted_kept,
    }


def delete_cookbook_recipe_images(cookbook_id: str) -> None:
    folder = settings.upload_dir / "recipes" / cookbook_id
    if folder.is_dir():
        for child in folder.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
