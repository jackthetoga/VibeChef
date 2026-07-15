"""Tests for recipe imagery extraction and photorealistic corpus matching."""

from pathlib import Path

import pytest
from ebooklib import epub

from app.services.recipe_images import (
    assign_image_for_recipe,
    clear_corpus_cache,
    corpus_assignment,
    match_corpus_entry,
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
        content=_PNG_64 * 40,
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

@pytest.fixture(autouse=True)
def _clear_corpus_cache() -> None:
    clear_corpus_cache()
    yield
    clear_corpus_cache()


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


def test_assign_without_corpus_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import recipe_images

    monkeypatch.setattr(recipe_images, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(recipe_images, "PHOTOS_DIR", tmp_path)
    (tmp_path / "manifest.json").write_text("[]", encoding="utf-8")
    clear_corpus_cache()

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
    assert assignment is None


def test_corpus_match_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import recipe_images

    photos = tmp_path / "photos"
    photos.mkdir()
    photo = photos / "risotto_01.jpg"
    photo.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    (tmp_path / "manifest.json").write_text(
        """
        [
          {
            "id": "risotto_01",
            "file": "photos/risotto_01.jpg",
            "tags": ["risotto", "rice", "arborio"],
            "cuisine": ["italian"]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(recipe_images, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(recipe_images, "PHOTOS_DIR", tmp_path)
    clear_corpus_cache()

    entry = match_corpus_entry("Mushroom Risotto", cuisine="Italian", tags=[])
    assert entry is not None
    assert entry.id == "risotto_01"

    assignment = corpus_assignment("Mushroom Risotto", "Italian", [])
    assert assignment is not None
    assert assignment.source.value == "corpus"
    assert assignment.path == "corpus/photos/risotto_01.jpg"
    assert assignment.key == "corpus:risotto_01"
    assert resolve_recipe_image_file(assignment.path) == photo.resolve()


def test_corpus_match_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import recipe_images

    (tmp_path / "manifest.json").write_text(
        """
        [
          {
            "id": "risotto_01",
            "file": "photos/risotto_01.jpg",
            "tags": ["risotto", "rice"],
            "cuisine": ["italian"]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(recipe_images, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(recipe_images, "PHOTOS_DIR", tmp_path)
    clear_corpus_cache()

    assert match_corpus_entry("Mystery Dish XYZ", cuisine=None, tags=[]) is None
    assert corpus_assignment("Mystery Dish XYZ") is None


def test_legacy_category_paths_are_rejected() -> None:
    with pytest.raises(FileNotFoundError):
        resolve_recipe_image_file("categories/pasta.svg")


def test_extract_wins_over_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import recipe_images

    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "pasta_01.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    (tmp_path / "manifest.json").write_text(
        """
        [
          {
            "id": "pasta_01",
            "file": "photos/pasta_01.jpg",
            "tags": ["pasta", "tomato", "spaghetti"],
            "cuisine": ["italian"]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(recipe_images, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(recipe_images, "PHOTOS_DIR", tmp_path)
    clear_corpus_cache()

    epub_path = tmp_path / "book.epub"
    _write_epub_with_recipe_image(epub_path)
    assignment = assign_image_for_recipe(
        epub_path,
        cookbook_id="11111111-1111-1111-1111-111111111111",
        recipe_id="22222222-2222-2222-2222-222222222222",
        title="Tomato Pasta",
        cuisine="Italian",
        tags=["pasta"],
        source_page=None,
        dest_dir=tmp_path,
    )
    assert assignment is not None
    assert assignment.source.value == "extracted"
