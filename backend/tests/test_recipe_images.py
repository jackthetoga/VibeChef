"""Tests for recipe imagery classification, assets, and extraction."""

from pathlib import Path

import pytest
from ebooklib import epub

from app.services.recipe_images import (
    CATEGORY_SLUGS,
    assign_image_for_recipe,
    classify_recipe_category,
    ensure_category_assets,
    resolve_recipe_image_file,
    try_extract_recipe_image,
)

# Valid 64x64 PNG (not a 1x1 placeholder)
_PNG_64 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000040000000400802000000250b"
    "e86e000000097048597300000b1300000b1301009a9c180000001c49444154"
    "789c63600802820000080002010001ff02fe00e9cb2f5e0000000049454e44ae426082"
)


def _write_epub_with_recipe_image(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("recipe-image-test")
    book.set_title("Illustrated Cookbook")
    book.set_language("en")

    image = epub.EpubItem(
        uid="pasta_img",
        file_name="images/pasta.png",
        media_type="image/png",
        content=_PNG_64 * 40,  # inflate past MIN_EXTRACTED_BYTES
    )
    book.add_item(image)

    chapter = epub.EpubHtml(title="Tomato Pasta", file_name="pasta.xhtml", lang="en")
    chapter.content = """
    <html><body>
      <h1>Tomato Pasta</h1>
      <img src="images/pasta.png" alt="pasta"/>
      <h2>Ingredients</h2>
      <ul><li>2 cups tomatoes</li></ul>
      <h2>Instructions</h2>
      <ol><li>Simmer.</li></ol>
    </body></html>
    """
    book.add_item(chapter)
    book.toc = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(str(path), book)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Tomato Spaghetti", "pasta"),
        ("Chicken Noodle Soup", "soup"),
        ("Grilled Salmon", "seafood"),
        ("Chocolate Cake", "dessert"),
        ("Mystery Dish", "other"),
    ],
)
def test_classify_recipe_category(title: str, expected: str) -> None:
    assert classify_recipe_category(title) == expected


def test_ensure_category_assets_writes_svgs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import recipe_images

    monkeypatch.setattr(recipe_images, "CATEGORY_DIR", tmp_path)
    ensure_category_assets()
    for slug in CATEGORY_SLUGS:
        path = tmp_path / f"{slug}.svg"
        assert path.is_file()
        assert "<svg" in path.read_text(encoding="utf-8")


def test_resolve_category_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import recipe_images

    monkeypatch.setattr(recipe_images, "CATEGORY_DIR", tmp_path)
    ensure_category_assets()
    resolved = resolve_recipe_image_file("categories/pasta.svg")
    assert resolved == (tmp_path / "pasta.svg").resolve()


def test_epub_recipe_image_extraction(tmp_path: Path) -> None:
    epub_path = tmp_path / "book.epub"
    _write_epub_with_recipe_image(epub_path)
    assignment = try_extract_recipe_image(
        epub_path,
        cookbook_id="11111111-1111-1111-1111-111111111111",
        recipe_id="22222222-2222-2222-2222-222222222222",
        title="Tomato Pasta",
        source_page=None,
        dest_dir=tmp_path,
    )
    assert assignment is not None
    assert assignment.source.value == "extracted"
    assert (tmp_path / assignment.path).is_file()


def test_assign_falls_back_to_category(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import recipe_images

    monkeypatch.setattr(recipe_images, "CATEGORY_DIR", tmp_path / "categories")
    text_book = tmp_path / "plain.txt"
    text_book.write_text("no images here", encoding="utf-8")
    assignment = assign_image_for_recipe(
        text_book,
        cookbook_id="11111111-1111-1111-1111-111111111111",
        recipe_id="22222222-2222-2222-2222-222222222222",
        title="Tomato Spaghetti",
        cuisine="Italian",
        tags=[],
        source_page=None,
        dest_dir=tmp_path,
    )
    assert assignment.source.value == "category"
    assert assignment.path == "categories/pasta.svg"
    assert assignment.key == "category:pasta"
