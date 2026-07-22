from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol
from zipfile import BadZipFile, ZipFile

from app.core.config import settings


class PDFDocument(Protocol):
    page_count: int


def validate_pdf_document(document: PDFDocument) -> None:
    if document.page_count > settings.max_pdf_pages:
        raise ValueError(f"PDF exceeds the {settings.max_pdf_pages}-page limit")


def validate_epub_archive(path: Path) -> None:
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > settings.max_epub_entries:
                raise ValueError("EPUB contains too many files")
            total_size = 0
            for entry in entries:
                pure_path = PurePosixPath(entry.filename)
                if pure_path.is_absolute() or ".." in pure_path.parts:
                    raise ValueError("EPUB contains an unsafe file path")
                if entry.flag_bits & 0x1:
                    raise ValueError("Encrypted EPUB files are not supported")
                if entry.file_size > settings.max_epub_entry_bytes:
                    raise ValueError("EPUB contains an oversized file")
                total_size += entry.file_size
                if total_size > settings.max_epub_uncompressed_bytes:
                    raise ValueError("EPUB expands beyond the configured size limit")
    except BadZipFile as exc:
        raise ValueError("EPUB archive is invalid") from exc


def validate_image_dimensions(width: int, height: int) -> None:
    if (
        width <= 0
        or height <= 0
        or width > settings.max_image_dimension
        or height > settings.max_image_dimension
        or width * height > settings.max_image_pixels
    ):
        raise ValueError("Image dimensions exceed the configured limit")
