"""Recipe imagery: category classification, asset paths, and book extraction."""

from __future__ import annotations

import logging
import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy import select

from app.core.config import settings
from app.models import ImageSource

logger = logging.getLogger(__name__)

CATEGORY_DIR = Path(__file__).resolve().parent.parent / "assets" / "recipe_categories"
MIN_EXTRACTED_BYTES = 2_500
MIN_IMAGE_DIMENSION = 80

CATEGORY_SLUGS = (
    "pasta",
    "soup",
    "salad",
    "seafood",
    "meat",
    "poultry",
    "vegetable",
    "dessert",
    "bread",
    "sauce",
    "breakfast",
    "grain",
    "stew",
    "drink",
    "other",
)

# Ordered rules: first match wins. Patterns match title, cuisine, and tags.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "soup",
        (
            r"\bsoup\b",
            r"\bbroth\b",
            r"\bbisque\b",
            r"\bchowder\b",
            r"\bconsomme\b",
            r"\bconsommé\b",
            r"\bpho\b",
            r"\bmiso\b",
        ),
    ),
    (
        "stew",
        (
            r"\bstew\b",
            r"\bcasserole\b",
            r"\brajout\b",
            r"\bgoulash\b",
            r"\bcurry\b",
            r"\bchili\b",
            r"\bchilli\b",
            r"\btagine\b",
            r"\bbraise",
        ),
    ),
    (
        "pasta",
        (
            r"\bpasta\b",
            r"\bspaghetti\b",
            r"\blinguine\b",
            r"\bfettuccine\b",
            r"\bpenne\b",
            r"\brigatoni\b",
            r"\blasagna\b",
            r"\blasagne\b",
            r"\bnoodle\b",
            r"\bramen\b",
            r"\budon\b",
            r"\bmacaroni\b",
            r"\bgnocchi\b",
        ),
    ),
    (
        "salad",
        (r"\bsalad\b", r"\bslaw\b", r"\bceviche\b"),
    ),
    (
        "seafood",
        (
            r"\bfish\b",
            r"\bsalmon\b",
            r"\btuna\b",
            r"\bcod\b",
            r"\bshrimp\b",
            r"\bprawn\b",
            r"\bcrab\b",
            r"\blobster\b",
            r"\bmussel\b",
            r"\bclam\b",
            r"\boyster\b",
            r"\bscallop\b",
            r"\bsquid\b",
            r"\bcalamari\b",
            r"\bseafood\b",
            r"\banchov",
        ),
    ),
    (
        "poultry",
        (
            r"\bchicken\b",
            r"\bturkey\b",
            r"\bduck\b",
            r"\bhen\b",
            r"\bpoultry\b",
            r"\bquail\b",
        ),
    ),
    (
        "meat",
        (
            r"\bbeef\b",
            r"\bsteak\b",
            r"\bpork\b",
            r"\blamb\b",
            r"\bveal\b",
            r"\bbacon\b",
            r"\bsausage\b",
            r"\bham\b",
            r"\bribs?\b",
            r"\bbrisket\b",
            r"\bmeatball",
            r"\bburger\b",
        ),
    ),
    (
        "dessert",
        (
            r"\bcake\b",
            r"\bcookie\b",
            r"\bbrownie\b",
            r"\bpie\b",
            r"\btart\b",
            r"\bpudding\b",
            r"\bicecream\b",
            r"\bice cream\b",
            r"\bchocolate\b",
            r"\bdessert\b",
            r"\bcustard\b",
            r"\bsorbet\b",
            r"\bmousse\b",
            r"\bbiscotti\b",
            r"\bcookies?\b",
            r"\bsweet\b",
        ),
    ),
    (
        "bread",
        (
            r"\bbread\b",
            r"\bbaguette\b",
            r"\bbiscuit\b",
            r"\bmuffin\b",
            r"\bscone\b",
            r"\broll\b",
            r"\bbun\b",
            r"\bfocaccia\b",
            r"\bciabatta\b",
            r"\bpizza\b",
            r"\bflatbread\b",
            r"\btortilla\b",
            r"\bpancake\b",
            r"\bwaffle\b",
            r"\bcrepe\b",
            r"\bcrêpe\b",
        ),
    ),
    (
        "breakfast",
        (
            r"\bbreakfast\b",
            r"\begg\b",
            r"\bombelet\b",
            r"\bfrittata\b",
            r"\bgranola\b",
            r"\boatmeal\b",
            r"\bporridge\b",
            r"\bbrunch\b",
        ),
    ),
    (
        "sauce",
        (
            r"\bsauce\b",
            r"\bdressing\b",
            r"\bvinaigrette\b",
            r"\bpesto\b",
            r"\baioli\b",
            r"\bgravy\b",
            r"\bmarinade\b",
            r"\brelish\b",
            r"\bchutney\b",
            r"\bsalsa\b",
        ),
    ),
    (
        "drink",
        (
            r"\bdrink\b",
            r"\bbeverage\b",
            r"\bcocktail\b",
            r"\bsmoothie\b",
            r"\bjuice\b",
            r"\btea\b",
            r"\bcoffee\b",
            r"\bwine\b",
            r"\blemonade\b",
            r"\bpunch\b",
        ),
    ),
    (
        "grain",
        (
            r"\brice\b",
            r"\brisotto\b",
            r"\bquinoa\b",
            r"\bcouscous\b",
            r"\bbarley\b",
            r"\bpolenta\b",
            r"\bgrain\b",
            r"\bbulgur\b",
            r"\bfarro\b",
        ),
    ),
    (
        "vegetable",
        (
            r"\bvegetable\b",
            r"\bveggie\b",
            r"\bvegetarian\b",
            r"\bvegan\b",
            r"\basparagus\b",
            r"\bbroccoli\b",
            r"\bcauliflower\b",
            r"\beggplant\b",
            r"\baubergine\b",
            r"\bzucchini\b",
            r"\bcourgette\b",
            r"\bspinach\b",
            r"\bkale\b",
            r"\btomato\b",
            r"\bmushroom\b",
            r"\bleek\b",
            r"\bfennel\b",
            r"\bpepper\b",
            r"\bcabbage\b",
            r"\bbean\b",
            r"\blentil\b",
            r"\bchickpea\b",
        ),
    ),
)

_COMPILED_RULES = tuple(
    (slug, tuple(re.compile(pattern, re.I) for pattern in patterns))
    for slug, patterns in _CATEGORY_RULES
)


@dataclass(frozen=True)
class ImageAssignment:
    path: str
    source: ImageSource
    key: str | None = None


def category_asset_path(slug: str) -> Path:
    return CATEGORY_DIR / f"{slug}.svg"


def ensure_category_assets() -> None:
    """Write packaged category SVGs if missing (idempotent)."""
    CATEGORY_DIR.mkdir(parents=True, exist_ok=True)
    for slug in CATEGORY_SLUGS:
        path = category_asset_path(slug)
        if not path.is_file():
            path.write_text(_category_svg(slug), encoding="utf-8")


def classify_recipe_category(
    title: str,
    cuisine: str | None = None,
    tags: list[str] | None = None,
) -> str:
    haystack = " ".join(
        part for part in [title, cuisine or "", " ".join(tags or [])] if part
    ).lower()
    for slug, patterns in _COMPILED_RULES:
        if any(pattern.search(haystack) for pattern in patterns):
            return slug
    return "other"


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

    if relative.startswith("categories/"):
        ensure_category_assets()
        candidate = (CATEGORY_DIR / Path(relative).name).resolve()
        try:
            candidate.relative_to(CATEGORY_DIR.resolve())
        except ValueError as exc:
            raise FileNotFoundError(image_path) from exc
        if not candidate.is_file():
            raise FileNotFoundError(image_path)
        return candidate

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
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"):
        if lower.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if content.startswith(b"\x89PNG"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return ".webp"
    if content[:256].lstrip().startswith(b"<svg") or b"<svg" in content[:512]:
        return ".svg"
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
    # Tiny 1x1 PNG / GIF placeholders
    if content.startswith(b"\x89PNG") and len(content) < 200:
        return True
    return False


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _extract_epub_images_by_title(path: Path) -> dict[str, tuple[bytes, str]]:
    """Map normalized recipe titles to (image_bytes, filename) from nearby <img> tags."""
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

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

            classes = {
                str(value).lower()
                for value in (node.get("class") or [])
            }
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
        if source_page > document.page_count:
            return None
        page = document[source_page - 1]
        # Prefer embedded images on the page.
        best: tuple[bytes, str] | None = None
        for image_info in page.get_images(full=True):
            xref = image_info[0]
            try:
                extracted = document.extract_image(xref)
            except Exception:
                continue
            content = extracted.get("image") or b""
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

        # Fallback: render the lower 55% of the page (common photo placement).
        rect = page.rect
        clip = fitz.Rect(rect.x0, rect.y0 + rect.height * 0.35, rect.x1, rect.y1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25), clip=clip, alpha=False)
        # Skip near-blank renders (mostly white text pages).
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
        # Soft match: title contained in key or vice versa
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


def category_assignment(title: str, cuisine: str | None, tags: list[str] | None) -> ImageAssignment:
    ensure_category_assets()
    slug = classify_recipe_category(title, cuisine, tags)
    return ImageAssignment(
        path=f"categories/{slug}.svg",
        source=ImageSource.category,
        key=f"category:{slug}",
    )


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
) -> ImageAssignment:
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
    return category_assignment(title, cuisine, tags)


async def assign_images_for_cookbook(cookbook_id: str, cookbook_path: Path) -> None:
    """Extract or classify images for every recipe in a cookbook."""
    from app.db.session import SessionLocal
    from app.models import Recipe

    ensure_category_assets()
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
                recipe.image_path = assignment.path
                recipe.image_source = assignment.source
                recipe.image_key = assignment.key
            except Exception as exc:
                logger.warning(
                    "Recipe image assignment failed for %s/%s: %s",
                    cookbook_id,
                    recipe.id,
                    exc,
                )
                fallback = category_assignment(recipe.title, recipe.cuisine, list(recipe.tags or []))
                recipe.image_path = fallback.path
                recipe.image_source = fallback.source
                recipe.image_key = fallback.key
        await db.commit()


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


def _category_svg(slug: str) -> str:
    """Original flat illustrations in the app cream/sage/terracotta palette."""
    motifs = {
        "pasta": (
            '<ellipse cx="400" cy="290" rx="190" ry="70" fill="#fff" stroke="#ddd7c9" stroke-width="6"/>'
            '<path d="M250 250c40 35 80 35 120 0s80-35 120 0 80 35 120 0" fill="none" '
            'stroke="#b65b3d" stroke-width="14" stroke-linecap="round"/>'
            '<path d="M250 280c40 35 80 35 120 0s80-35 120 0 80 35 120 0" fill="none" '
            'stroke="#7d9b78" stroke-width="12" stroke-linecap="round"/>'
        ),
        "soup": (
            '<ellipse cx="400" cy="320" rx="170" ry="48" fill="#ddd7c9"/>'
            '<path d="M230 250h340v70c0 55-76 100-170 100s-170-45-170-100z" fill="#7d9b78"/>'
            '<path d="M260 250c20-55 60-90 140-90s120 35 140 90" fill="none" stroke="#b65b3d" '
            'stroke-width="10" stroke-linecap="round"/>'
            '<circle cx="340" cy="285" r="10" fill="#f8f5ed"/><circle cx="400" cy="300" r="8" fill="#f8f5ed"/>'
            '<circle cx="455" cy="280" r="9" fill="#f8f5ed"/>'
        ),
        "salad": (
            '<ellipse cx="400" cy="330" rx="180" ry="50" fill="#eee9dc"/>'
            '<path d="M300 300c20-80 70-120 100-40 20-70 80-90 110-20 10-50 60-70 90 10 '
            'c-70 40-140 60-300 50z" fill="#7d9b78"/>'
            '<circle cx="360" cy="270" r="18" fill="#b65b3d"/>'
            '<circle cx="430" cy="255" r="14" fill="#f8f5ed" stroke="#b65b3d" stroke-width="4"/>'
            '<circle cx="470" cy="295" r="12" fill="#25312c"/>'
        ),
        "seafood": (
            '<ellipse cx="400" cy="300" rx="150" ry="70" fill="#7d9b78"/>'
            '<path d="M520 300c40-40 70-20 90 0-20 20-50 40-90 0z" fill="#b65b3d"/>'
            '<circle cx="340" cy="285" r="10" fill="#f8f5ed"/>'
            '<path d="M280 270c-20 10-30 30-20 45M270 310c20 10 40 5 55-10" fill="none" '
            'stroke="#25312c" stroke-width="6" stroke-linecap="round"/>'
        ),
        "meat": (
            '<path d="M290 220c80-70 220-70 300 10 40 40 30 120-20 150-90 55-220 40-280-20 '
            'c-40-40-35-100 0-140z" fill="#b65b3d"/>'
            '<path d="M340 250c50-20 120-15 160 25" fill="none" stroke="#f8f5ed" stroke-width="8" '
            'stroke-linecap="round" opacity=".5"/>'
            '<circle cx="520" cy="300" r="16" fill="#eee9dc"/>'
        ),
        "poultry": (
            '<ellipse cx="390" cy="300" rx="140" ry="90" fill="#eee9dc" stroke="#ddd7c9" stroke-width="6"/>'
            '<circle cx="500" cy="240" r="48" fill="#eee9dc" stroke="#ddd7c9" stroke-width="6"/>'
            '<path d="M540 245c30 5 45 25 35 45" fill="none" stroke="#b65b3d" stroke-width="10" '
            'stroke-linecap="round"/>'
            '<circle cx="515" cy="230" r="7" fill="#25312c"/>'
            '<path d="M300 320c-40 10-60 40-40 60h80" fill="#7d9b78"/>'
        ),
        "vegetable": (
            '<path d="M400 340c-90-10-140-80-120-150 50 20 90 20 120-10 30 30 70 30 120 10 '
            'c20 70-30 140-120 150z" fill="#7d9b78"/>'
            '<path d="M400 180c0-40 20-70 0-100" fill="none" stroke="#25312c" stroke-width="10" '
            'stroke-linecap="round"/>'
            '<ellipse cx="330" cy="260" rx="18" ry="28" fill="#b65b3d" opacity=".85"/>'
            '<ellipse cx="460" cy="250" rx="16" ry="24" fill="#f8f5ed" opacity=".9"/>'
        ),
        "dessert": (
            '<path d="M260 320h280l-30 80H290z" fill="#b65b3d"/>'
            '<path d="M250 320c20-90 80-140 150-140s130 50 150 140z" fill="#eee9dc" '
            'stroke="#ddd7c9" stroke-width="6"/>'
            '<circle cx="400" cy="230" r="22" fill="#7d9b78"/>'
            '<path d="M390 210c-5-30 20-45 35-25" fill="none" stroke="#25312c" stroke-width="5"/>'
        ),
        "bread": (
            '<ellipse cx="400" cy="300" rx="200" ry="90" fill="#b65b3d"/>'
            '<ellipse cx="400" cy="280" rx="180" ry="70" fill="#d9845f"/>'
            '<path d="M300 260c30-25 70-25 100 0M420 255c30-25 70-20 100 8" fill="none" '
            'stroke="#f8f5ed" stroke-width="8" stroke-linecap="round" opacity=".55"/>'
        ),
        "sauce": (
            '<path d="M340 200h120v40c40 10 60 40 60 80v80H280v-80c0-40 20-70 60-80z" fill="#7d9b78"/>'
            '<rect x="360" y="160" width="80" height="50" rx="8" fill="#b65b3d"/>'
            '<ellipse cx="400" cy="400" rx="90" ry="20" fill="#ddd7c9"/>'
        ),
        "breakfast": (
            '<ellipse cx="400" cy="300" rx="160" ry="100" fill="#f8f5ed" stroke="#ddd7c9" stroke-width="8"/>'
            '<circle cx="400" cy="300" r="70" fill="#eee9dc"/>'
            '<circle cx="400" cy="300" r="36" fill="#b65b3d"/>'
            '<path d="M250 250c20-40 40-40 60 0M530 250c20-40 40-40 60 0" fill="none" '
            'stroke="#7d9b78" stroke-width="12" stroke-linecap="round"/>'
        ),
        "grain": (
            '<ellipse cx="400" cy="340" rx="160" ry="45" fill="#ddd7c9"/>'
            '<g fill="#b65b3d">'
            '<ellipse cx="340" cy="300" rx="18" ry="10"/><ellipse cx="380" cy="285" rx="18" ry="10"/>'
            '<ellipse cx="420" cy="300" rx="18" ry="10"/><ellipse cx="460" cy="285" rx="18" ry="10"/>'
            '<ellipse cx="360" cy="320" rx="18" ry="10"/><ellipse cx="410" cy="325" rx="18" ry="10"/>'
            '<ellipse cx="450" cy="315" rx="18" ry="10"/>'
            "</g>"
            '<path d="M300 250c40-60 100-60 140 0" fill="none" stroke="#7d9b78" stroke-width="10"/>'
        ),
        "stew": (
            '<path d="M240 250h320l-30 160H270z" fill="#b65b3d"/>'
            '<ellipse cx="400" cy="250" rx="170" ry="40" fill="#7d9b78"/>'
            '<circle cx="360" cy="320" r="14" fill="#f8f5ed"/><circle cx="420" cy="340" r="12" fill="#eee9dc"/>'
            '<circle cx="455" cy="310" r="10" fill="#25312c" opacity=".35"/>'
        ),
        "drink": (
            '<path d="M330 180h140l-30 220H360z" fill="#7d9b78" opacity=".85"/>'
            '<path d="M340 180h120v30H340z" fill="#eee9dc" stroke="#ddd7c9" stroke-width="4"/>'
            '<ellipse cx="400" cy="420" rx="70" ry="18" fill="#ddd7c9"/>'
            '<path d="M470 220c40 20 50 70 20 100" fill="none" stroke="#b65b3d" stroke-width="8" '
            'stroke-linecap="round"/>'
        ),
        "other": (
            '<circle cx="400" cy="270" r="110" fill="#eee9dc" stroke="#ddd7c9" stroke-width="8"/>'
            '<path d="M350 250h100v80H350z" fill="#7d9b78"/>'
            '<path d="M370 230h60v25H370z" fill="#b65b3d"/>'
            '<circle cx="400" cy="290" r="14" fill="#f8f5ed"/>'
        ),
    }
    art = motifs.get(slug, motifs["other"])
    label = slug.replace("_", " ").title()
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" role="img" aria-label="{label}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8f5ed"/>
      <stop offset="100%" stop-color="#eee9dc"/>
    </linearGradient>
  </defs>
  <rect width="800" height="500" fill="url(#bg)"/>
  <circle cx="120" cy="90" r="70" fill="#fff" fill-opacity=".45"/>
  <circle cx="700" cy="420" r="90" fill="#7d9b78" fill-opacity=".12"/>
  {art}
</svg>
'''
