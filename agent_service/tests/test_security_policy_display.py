from agent_service.contracts import Citation
from agent_service.security_policies import (
    PROXY_ADVISORY_TEXT,
    citation_for_policy,
    filter_display_citations,
    strip_policy_overlay_for_display,
)


def test_strip_policy_overlay_removes_markers_and_advisory_block() -> None:
    answer = (
        "請調整安全性設定 [S1]。\n"
        "變更前請向權責單位確認 [POLICY-SEC-003]。\n\n"
        f"{PROXY_ADVISORY_TEXT}"
    )

    displayed = strip_policy_overlay_for_display(answer)

    assert "[S1]" in displayed
    assert "向權責單位確認" in displayed
    assert "POLICY-SEC" not in displayed
    assert "系統資安政策提醒" not in displayed


def test_filter_display_citations_drops_policy_advisory_entries() -> None:
    knowledge = Citation(title="大州操作說明", chunkId="chunk-1")
    policy = citation_for_policy("POLICY-SEC-003", include_evidence=False)

    assert filter_display_citations([knowledge, policy]) == [knowledge]
