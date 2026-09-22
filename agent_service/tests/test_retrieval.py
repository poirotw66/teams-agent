from agent_service.documents import DocumentChunk
from agent_service.retrieval import (
    HybridIndex,
    _embedding_models_compatible,
    tokenize,
)
from agent_service.retrieval_acl import is_chunk_visible_to_groups


def test_chinese_tokenizer_creates_bigrams() -> None:
    tokens = tokenize("VPN密碼問題")

    assert "密碼" in tokens
    assert "問題" in tokens
    assert "vpn" in tokens


def test_embedding_model_ids_compatible_with_or_without_provider() -> None:
    assert _embedding_models_compatible("google_genai:gemini-embedding-2", "gemini-embedding-2")
    assert _embedding_models_compatible(
        "google_genai:gemini-embedding-2", "google_genai:gemini-embedding-2"
    )
    assert not _embedding_models_compatible(
        "google_genai:gemini-embedding-2", "openai:text-embedding-3-small"
    )


def test_search_finds_relevant_chinese_document() -> None:
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="vpn",
                title="VPN 常見問題",
                source_path="sources/vpn.md",
                content="VPN 密碼錯誤時，請確認 AD 帳號是否被鎖定。",
            ),
            DocumentChunk(
                chunk_id="phone",
                title="IP 話機",
                source_path="sources/phone.md",
                content="外線撥號請先按 0。",
            ),
        ]
    )

    results = index.search("VPN 密碼被鎖怎麼辦", limit=2)

    assert results[0].chunk.chunk_id == "vpn"
    assert results[0].fusion_rank == 1
    assert results[0].sparse_score == 1.0


def test_search_fusion_mode_override_does_not_mutate_index() -> None:
    chunks = [
        DocumentChunk(
            chunk_id="a",
            title="A",
            source_path="a.md",
            content="alpha token unique",
        ),
        DocumentChunk(
            chunk_id="b",
            title="B",
            source_path="b.md",
            content="beta token unique",
        ),
    ]
    index = HybridIndex(chunks, fusion_mode="WEIGHTED")
    _ = index.search("alpha token", limit=2, fusion_mode="RRF")
    # Override must not mutate the index default mode.
    assert index.fusion_mode == "WEIGHTED"


def test_sparse_search_indexes_title_alias_and_section_identity() -> None:
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="portal-error",
                title="企業入口網站排錯",
                source_path="sources/portal.md",
                content="請先重新啟動應用程式。",
                source_aliases=["PortalX"],
                section_path="登入 > Error 12029",
            ),
            DocumentChunk(
                chunk_id="unrelated",
                title="VPN 操作",
                source_path="sources/vpn.md",
                content="VPN 連線說明。",
            ),
        ]
    )

    results = index.search("PortalX Error 12029", limit=2)

    assert results[0].chunk.chunk_id == "portal-error"
    assert results[0].sparse_score == 1.0


def test_search_enforces_document_groups() -> None:
    index = HybridIndex(
        [
            DocumentChunk(
                chunk_id="restricted",
                title="限制文件",
                source_path="sources/restricted.md",
                content="VPN 特殊權限",
                allowed_groups=["IT"],
            )
        ]
    )

    assert index.search("VPN", limit=1, groups={"HR"}) == []
    assert index.search("VPN", limit=1, groups={"IT"})


def test_is_chunk_visible_to_groups_matches_hybrid_acl() -> None:
    public = DocumentChunk(
        chunk_id="public",
        title="公開",
        source_path="sources/public.md",
        content="公開內容",
        allowed_groups=[],
    )
    public_sentinel = DocumentChunk(
        chunk_id="public-sentinel",
        title="全員公開",
        source_path="sources/public-sentinel.md",
        content="全員公開內容",
        allowed_groups=["grp_public"],
    )
    restricted = DocumentChunk(
        chunk_id="restricted",
        title="限制",
        source_path="sources/restricted.md",
        content="限制內容",
        allowed_groups=["IT"],
    )

    assert is_chunk_visible_to_groups(public, set()) is True
    assert is_chunk_visible_to_groups(public, {"HR"}) is True
    assert is_chunk_visible_to_groups(public_sentinel, set()) is True
    assert is_chunk_visible_to_groups(public_sentinel, {"HR"}) is True
    assert is_chunk_visible_to_groups(restricted, set()) is False
    assert is_chunk_visible_to_groups(restricted, {"HR"}) is False
    assert is_chunk_visible_to_groups(restricted, {"IT"}) is True


def test_search_with_timings_reports_acl_filtered_chunk_count() -> None:
    public = DocumentChunk(
        chunk_id="public",
        title="公開",
        source_path="sources/public.md",
        content="VPN 密碼重設",
        allowed_groups=[],
    )
    restricted = DocumentChunk(
        chunk_id="restricted",
        title="限制",
        source_path="sources/restricted.md",
        content="VPN 內部流程",
        allowed_groups=["IT"],
    )
    index = HybridIndex([public, restricted])
    _results, timings = index.search_with_timings("VPN", limit=5, groups={"HR"})
    assert timings["aclVisibleChunks"] == 1.0
    assert timings["aclFilteredChunks"] == 1.0
