"""Tests for Layer-3 answer soft evidence token matching."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_eval_module():
    path = _REPO_ROOT / "scripts" / "run_rag_pipeline_eval.py"
    spec = importlib.util.spec_from_file_location("run_rag_pipeline_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_soft_match_accepts_portal_password_paraphrase_not_same_as_ad() -> None:
    eval_mod = _load_eval_module()
    answer = "不是，國泰員工入口網的密碼與 AD 密碼並非同一組，其密碼連動為國泰金控網站帳密 [S1]。"
    assert eval_mod._soft_evidence_token_in_answer("並非AD", answer)
    assert eval_mod._answer_covers_evidence_fact(
        answer=answer,
        must_contain=["國泰金控網站帳密"],
        cited_titles=["國泰員工入口網、CTeam密碼、國泰e點名"],
    )


def test_soft_match_accepts_parenthesized_error_code_without_parens() -> None:
    eval_mod = _load_eval_module()
    answer = "若出現 VPN 錯誤碼 -455，請確認網路狀態與密碼。"
    assert eval_mod._soft_evidence_token_in_answer("(-455)", answer)


def test_soft_match_accepts_overseas_vpn_as_foreign_connection() -> None:
    eval_mod = _load_eval_module()
    answer = "若員工有國外連線需求，請寄信 CC 雙方主管，再由網路組開通。"
    assert eval_mod._soft_evidence_token_in_answer("海外VPN", answer)


def test_soft_match_accepts_change_password_paraphrase() -> None:
    eval_mod = _load_eval_module()
    answer = (
        "若 VPN 密碼到期，請直接變更密碼，請勿前往金控入口網同步開機密碼（AD）。"
        "請插上實體網路線，並使用 Ctrl + Alt + Delete 變更公司電腦開機密碼。"
    )
    assert eval_mod._soft_evidence_token_in_answer("改密碼", answer)
    assert eval_mod._answer_covers_evidence_fact(
        answer=answer,
        must_contain=["密碼到期", "改密碼"],
        cited_titles=["VPN常見Q&A問答", "登入 FortiClient 出現錯訊"],
    )


def test_soft_match_accepts_short_cjk_token_covered_by_cited_title() -> None:
    eval_mod = _load_eval_module()
    answer = "若要進行直接轉接，請在通話中按下 Transfer 鍵後輸入分機號碼 [S1]。"
    assert eval_mod._answer_covers_evidence_fact(
        answer=answer,
        must_contain=["話機"],
        cited_titles=["總公司IP話機操作"],
    )
