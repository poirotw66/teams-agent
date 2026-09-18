"""Unit tests for workbench citation building and shared policy catalog matching."""

from __future__ import annotations

from ai_ops_backoffice.application.workbench.citations import build_citations_for_turn
from operations_core.security_policies import (
    SECURITY_POLICIES,
    known_policy_ids_in_text,
)


def test_known_policy_ids_in_text_returns_only_catalogued_ids() -> None:
    text = "資料最小化 [POLICY-SEC-001]，未知 [POLICY-SEC-999]，重複 [POLICY-SEC-001]。"

    assert known_policy_ids_in_text(text) == ["POLICY-SEC-001"]


def test_build_citations_for_turn_appends_policy_from_answer_markers() -> None:
    turn = {"sourceRefs": [], "events": []}
    ai_text = "變更 Proxy 前請向權責單位確認 [POLICY-SEC-003]。"
    policy = SECURITY_POLICIES["POLICY-SEC-003"]

    citations = build_citations_for_turn(turn, ai_text, _UnusedResolver())

    assert len(citations) == 1
    citation = citations[0]
    assert citation["policy_id"] == policy.policy_id
    assert citation["chunk_id"] == policy.policy_id
    assert citation["source_type"] == "POLICY_ADVISORY"
    assert citation["is_policy"] is True
    assert citation["snippet"] == policy.summary
    assert citation["content"] == policy.body


class _UnusedResolver:
    def resolve_source_content_excerpt(
        self,
        source_ref_id: str,
        *,
        max_chars: int = 2400,
    ) -> str | None:
        raise AssertionError("source excerpt resolver should not be called")
