"""Tests for whitespace-flex evidence token matching."""

from __future__ import annotations

from agent_service.retrieval_eval_metrics import evidence_fact_hit, evidence_token_in_text


def test_evidence_token_in_text_ignores_whitespace() -> None:
    assert evidence_token_in_text("並非AD", "該密碼並非 AD 密碼")
    assert evidence_token_in_text("AD帳號", "請先確認 AD 帳號是否被鎖定")
    assert evidence_token_in_text("海外VPN", "請申請海外 VPN 開通")


def test_evidence_token_in_text_allows_intervening_particle() -> None:
    assert evidence_token_in_text("帳號鎖定", "若您的 AD 帳號遭鎖定，可透過自助解鎖")


def test_evidence_fact_hit_flex_space_multi_token() -> None:
    assert evidence_fact_hit(
        retrieved_texts=["國泰員工入口網密碼連動為國泰金控網站帳密，並非 AD 密碼"],
        must_contain=["國泰金控網站帳密", "並非AD"],
    )
