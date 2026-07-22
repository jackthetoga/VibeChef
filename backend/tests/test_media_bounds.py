from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.config import settings
from app.services.media_bounds import (
    validate_epub_archive,
    validate_image_dimensions,
    validate_pdf_document,
)


class FakeDocument:
    def __init__(self, page_count: int) -> None:
        self.page_count = page_count


def test_pdf_page_limit() -> None:
    validate_pdf_document(FakeDocument(settings.max_pdf_pages))
    with pytest.raises(ValueError, match="page limit"):
        validate_pdf_document(FakeDocument(settings.max_pdf_pages + 1))


def test_epub_rejects_traversal_entry(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.epub"
    with ZipFile(path, "w") as archive:
        archive.writestr("../outside.xhtml", "<p>unsafe</p>")

    with pytest.raises(ValueError, match="unsafe file path"):
        validate_epub_archive(path)


def test_image_dimension_and_pixel_limits() -> None:
    validate_image_dimensions(100, 100)
    with pytest.raises(ValueError, match="dimensions"):
        validate_image_dimensions(settings.max_image_dimension + 1, 1)
    with pytest.raises(ValueError, match="dimensions"):
        validate_image_dimensions(settings.max_image_pixels, 2)
