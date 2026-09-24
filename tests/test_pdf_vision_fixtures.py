"""Minimal Vertex Vision sample PDFs stay in-repo and keep their page contracts."""

from __future__ import annotations

import sys
from pathlib import Path

from pypdf import PdfReader

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "pdf-vision"
sys.path.insert(0, str(FIXTURE_DIR))
from build_vision_fixtures import (  # noqa: E402
    MIXED_TEXT,
    SCAN_MARKER,
    SELECTABLE_TEXT,
    TABLE_TITLE,
    write_fixtures,
)


def _page(name: str):
    reader = PdfReader(str(FIXTURE_DIR / name))
    assert len(reader.pages) == 1
    return reader.pages[0]


def _has_xobject(page) -> bool:
    resources = page.get("/Resources") or {}
    return resources.get("/XObject") is not None


def test_vision_fixtures_exist_with_expected_page_contracts() -> None:
    selectable = _page("selectable-text.pdf")
    scan = _page("scan-like.pdf")
    table = _page("simple-table.pdf")
    mixed = _page("mixed-text-image.pdf")

    assert SELECTABLE_TEXT in (selectable.extract_text() or "")
    assert not _has_xobject(selectable)

    assert (scan.extract_text() or "") == ""
    assert _has_xobject(scan)

    table_text = table.extract_text() or ""
    assert TABLE_TITLE in table_text
    assert "Priority" in table_text
    assert not _has_xobject(table)

    assert MIXED_TEXT in (mixed.extract_text() or "")
    assert _has_xobject(mixed)


def test_vision_fixture_builder_rewrites_the_same_four_files(tmp_path: Path) -> None:
    written = write_fixtures(tmp_path)
    assert set(written) == {
        "selectable-text.pdf",
        "scan-like.pdf",
        "simple-table.pdf",
        "mixed-text-image.pdf",
    }
    scan = PdfReader(str(written["scan-like.pdf"])).pages[0]
    assert (scan.extract_text() or "") == ""
    assert SCAN_MARKER  # marker is image-only; keep the constant imported and used
