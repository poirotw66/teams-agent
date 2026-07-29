from agent_service.documents import DocumentChunk
from agent_service.retrieval import HybridIndex, tokenize


def test_chinese_tokenizer_creates_bigrams() -> None:
    tokens = tokenize("VPN密碼問題")

    assert "密碼" in tokens
    assert "問題" in tokens
    assert "vpn" in tokens


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
    assert results[0].score == 1.0


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

