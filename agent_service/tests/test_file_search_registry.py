"""Tests for the Gemini File Search document registry (spec §8.3, Task 15)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from agent_service.contracts import AgentImage
from agent_service.documents import DocumentChunk, DocumentImage
from agent_service.file_search_registry import FileSearchDocumentRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_SCRIPT = REPO_ROOT / "scripts" / "gemini_file_search_spike.py"
SOURCES_DIR = REPO_ROOT / "data" / "sources"
REAL_INDEX_PATH = REPO_ROOT / "data" / "index" / "chunks.json"


def make_chunk(
    chunk_id: str,
    title: str,
    source_path: str,
    images: list[DocumentImage] | None = None,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title=title,
        source_path=source_path,
        content="content",
        images=images or [],
    )


# --- slug round-trip ---------------------------------------------------


def test_slug_for_chinese_filename_keeps_ascii_symbols():
    slug = FileSearchDocumentRegistry.slug_for("sources/VPN常見Q&A問答.md")
    assert slug == "VPNQ&A.md"


def test_slug_for_ascii_filename_is_unchanged():
    slug = FileSearchDocumentRegistry.slug_for("sources/PowerPivot.md")
    assert slug == "PowerPivot.md"


def test_slug_for_fully_non_ascii_filename_falls_back_to_hash():
    slug = FileSearchDocumentRegistry.slug_for("sources/報表教學.md")
    assert slug.startswith("doc-")
    assert slug.endswith(".md")
    # Stable across calls (content hash, not random).
    assert slug == FileSearchDocumentRegistry.slug_for("sources/報表教學.md")


def test_slug_for_different_non_ascii_filenames_do_not_collide():
    a = FileSearchDocumentRegistry.slug_for("sources/報表教學.md")
    b = FileSearchDocumentRegistry.slug_for("sources/教學報表.md")
    assert a != b


def test_registry_auto_disambiguates_provisional_slug_collisions():
    from agent_service.file_search_slugs import assign_unique_ascii_slugs

    paths = [
        "sources/VPN國外連線短暫申請.md",
        "sources/VPN跳板機連線異常.md",
        "sources/內網筆電VPN連線問題.md",
    ]
    assert FileSearchDocumentRegistry.slug_for(paths[0]) == "VPN.md"
    assert FileSearchDocumentRegistry.slug_for(paths[1]) == "VPN.md"
    chunks = [
        make_chunk("c1", "國外", paths[0]),
        make_chunk("c2", "跳板", paths[1]),
        make_chunk("c3", "內網", paths[2]),
    ]
    registry = FileSearchDocumentRegistry.from_chunks(chunks)
    unique = assign_unique_ascii_slugs(paths)
    assert len(set(unique.values())) == 3
    assert registry.title_for(unique[paths[0]]) == "國外"
    assert registry.title_for(unique[paths[1]]) == "跳板"
    assert registry.title_for(unique[paths[2]]) == "內網"


def test_ensure_unique_file_search_slugs_strict_raises():
    from agent_service.file_search_slugs import (
        FileSearchSlugCollisionError,
        ensure_unique_file_search_slugs,
    )

    with pytest.raises(FileSearchSlugCollisionError, match="VPN.md"):
        ensure_unique_file_search_slugs(
            [
                "sources/VPN國外連線短暫申請.md",
                "sources/VPN跳板機連線異常.md",
            ],
            strict=True,
        )


def test_indexer_rejects_slug_collisions(tmp_path: Path):
    from agent_service.file_search_slugs import FileSearchSlugCollisionError
    from agent_service.indexer import build_index
    from agent_service.settings import RagSettings

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "VPN甲.md").write_text("# A\n\nhello\n", encoding="utf-8")
    (sources / "VPN乙.md").write_text("# B\n\nworld\n", encoding="utf-8")
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
        embedding_model=None,
    )
    with pytest.raises(FileSearchSlugCollisionError, match="VPN.md"):
        build_index(settings)


# --- title_for -----------------------------------------------------------


def test_title_for_returns_real_chinese_title():
    chunk = make_chunk("c1", "VPN常見Q&A問答", "sources/VPN常見Q&A問答.md")
    registry = FileSearchDocumentRegistry.from_chunks([chunk])
    slug = FileSearchDocumentRegistry.slug_for(chunk.source_path)
    assert registry.title_for(slug) == "VPN常見Q&A問答"


def test_title_for_falls_back_to_filename_stem_when_chunk_title_empty():
    chunk = make_chunk("c1", "", "sources/PowerPivot.md")
    registry = FileSearchDocumentRegistry.from_chunks([chunk])
    slug = FileSearchDocumentRegistry.slug_for(chunk.source_path)
    assert registry.title_for(slug) == "PowerPivot"


# --- images_for ------------------------------------------------------------


def test_images_for_deduplicates_across_chunks_and_preserves_order():
    img1 = DocumentImage(path="doc/p01.png", title="第一張", alt_text="第一張")
    img2 = DocumentImage(path="doc/p02.png", title="第二張", alt_text="第二張")
    chunk_a = make_chunk("c1", "大州首次使用設定", "sources/大州首次使用設定.md", [img1])
    chunk_b = make_chunk(
        "c2", "大州首次使用設定", "sources/大州首次使用設定.md", [img1, img2]
    )
    registry = FileSearchDocumentRegistry.from_chunks([chunk_a, chunk_b])
    slug = FileSearchDocumentRegistry.slug_for(chunk_a.source_path)

    images = registry.images_for(slug)

    assert images == [
        AgentImage(path="doc/p01.png", title="第一張", altText="第一張", sourceChunkId="c1"),
        AgentImage(path="doc/p02.png", title="第二張", altText="第二張", sourceChunkId="c2"),
    ]


def test_images_for_empty_when_document_has_no_images():
    chunk = make_chunk("c1", "Gitlab帳號解鎖跟重置", "sources/Gitlab帳號解鎖跟重置.md")
    registry = FileSearchDocumentRegistry.from_chunks([chunk])
    slug = FileSearchDocumentRegistry.slug_for(chunk.source_path)
    assert registry.images_for(slug) == []


# --- collisions --------------------------------------------------------


def test_collision_auto_disambiguates_same_basename_paths():
    from agent_service.file_search_slugs import assign_unique_ascii_slugs

    chunk_a = make_chunk("c1", "A", "sources/foo.md")
    chunk_b = make_chunk("c2", "B", "other/foo.md")
    registry = FileSearchDocumentRegistry.from_chunks([chunk_a, chunk_b])
    unique = assign_unique_ascii_slugs(
        ["sources/foo.md", "other/foo.md"]
    )
    assert unique["sources/foo.md"] != unique["other/foo.md"]
    assert registry.title_for(unique["sources/foo.md"]) == "A"
    assert registry.title_for(unique["other/foo.md"]) == "B"


# --- unknown slug --------------------------------------------------------


def test_unknown_slug_degrades_to_none_and_empty_list():
    registry = FileSearchDocumentRegistry.from_chunks([])
    assert registry.title_for("nonexistent.md") is None
    assert registry.images_for("nonexistent.md") == []
    assert registry.source_path_for("nonexistent.md") is None


def test_source_path_for_known_slug():
    chunk = make_chunk("c1", "PowerPivot", "sources/PowerPivot.md")
    registry = FileSearchDocumentRegistry.from_chunks([chunk])
    slug = FileSearchDocumentRegistry.slug_for(chunk.source_path)
    assert registry.source_path_for(slug) == "sources/PowerPivot.md"


def test_legacy_helpdesk_slug_resolves_portal_release_document_by_title():
    image = DocumentImage(
        path="總公司IP話機操作/p02.png",
        title="總公司 IP 話機面板說明",
        alt_text="總公司 IP 話機面板說明",
    )
    text_chunk = make_chunk(
        "phone-text",
        "總公司IP話機操作",
        "sources/doc-ip-ceb794956f.md",
    )
    panel_chunk = make_chunk(
        "phone-panel",
        "總公司IP話機操作",
        "sources/doc-ip-ceb794956f.md",
        images=[image],
    )
    registry = FileSearchDocumentRegistry.from_chunks([text_chunk, panel_chunk])

    assert registry.title_for("head-office-ip-phone-guide.md") == "總公司IP話機操作"
    assert [item.path for item in registry.images_for("head-office-ip-phone-guide.md")] == [
        "總公司IP話機操作/p02.png"
    ]


# --- parity with the spike script's slug algorithm ------------------------


def _load_spike_module():
    spec = importlib.util.spec_from_file_location(
        "gemini_file_search_spike", SPIKE_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module: a plain exec_module
    # without registration breaks dataclass resolution for any dataclasses
    # defined inside the module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not SOURCES_DIR.is_dir(), reason="data/sources/ not present")
def test_slug_matches_spike_script_for_every_real_source_file():
    spike = _load_spike_module()
    mismatches = []
    for path in sorted(SOURCES_DIR.iterdir()):
        if not path.is_file():
            continue
        expected = spike._ascii_display_name(path)
        actual = FileSearchDocumentRegistry.slug_for(f"sources/{path.name}")
        if expected != actual:
            mismatches.append((path.name, expected, actual))
    assert mismatches == []


# --- real index.json -------------------------------------------------------


@pytest.mark.skipif(not REAL_INDEX_PATH.is_file(), reason="data/index/chunks.json not present")
def test_real_index_resolves_known_image_bearing_documents():
    registry = FileSearchDocumentRegistry.from_index_path(REAL_INDEX_PATH)

    cases = {
        "doc-f8da1df6e202.md": ("大州系統_功能無法點選", 1),
        "doc-be7ba83c6fee.md": ("大州首次使用設定", 2),
        "IP.md": ("總公司IP話機操作", 1),
    }
    for slug, (expected_title, expected_image_count) in cases.items():
        assert registry.title_for(slug) == expected_title
        images = registry.images_for(slug)
        assert len(images) == expected_image_count
        assert all(isinstance(image, AgentImage) for image in images)
        assert all(image.sourceChunkId for image in images)


@pytest.mark.skipif(not REAL_INDEX_PATH.is_file(), reason="data/index/chunks.json not present")
def test_legacy_helpdesk_store_names_resolve_chinese_titles_and_images():
    registry = FileSearchDocumentRegistry.from_index_path(REAL_INDEX_PATH)

    cases = {
        "xiaozhou-feature-not-clickable.md": ("大州系統_功能無法點選", 1),
        "xiaozhou-first-time-setup.md": ("大州首次使用設定", 2),
        "head-office-ip-phone-guide.md": ("總公司IP話機操作", 1),
    }
    for legacy_name, (expected_title, expected_image_count) in cases.items():
        assert registry.title_for(legacy_name) == expected_title
        assert len(registry.images_for(legacy_name)) == expected_image_count


@pytest.mark.skipif(not REAL_INDEX_PATH.is_file(), reason="data/index/chunks.json not present")
def test_real_index_has_no_slug_collisions():
    from agent_service.file_search_slugs import slug_collision_groups

    value = json.loads(REAL_INDEX_PATH.read_text(encoding="utf-8"))
    chunks = [DocumentChunk.from_dict(item) for item in value["chunks"]]
    paths = sorted({chunk.source_path for chunk in chunks})
    assert slug_collision_groups(paths) == {}
    registry = FileSearchDocumentRegistry.from_chunks(chunks)
    assert registry is not None
