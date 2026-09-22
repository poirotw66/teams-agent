"""Regression: v5 blind label adjudication for product-correct answers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BLIND_PATH = _REPO_ROOT / "data" / "eval" / "retrieval_eval_v3_blind.json"


def _load_eval_module():
    path = _REPO_ROOT / "scripts" / "run_rag_pipeline_eval.py"
    spec = importlib.util.spec_from_file_location("run_rag_pipeline_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _case_by_id(case_id: str) -> dict:
    payload = json.loads(_BLIND_PATH.read_text(encoding="utf-8"))
    for case in payload["cases"]:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"missing case {case_id}")


def _citation_precision(*, cited: set[str], expected: set[str]) -> float:
    if not cited or not expected:
        return 0.0
    return len(cited & expected) / len(cited)


def test_freeze_version_is_v5() -> None:
    payload = json.loads(_BLIND_PATH.read_text(encoding="utf-8"))
    assert payload["freezeVersion"] == 5


def test_ans_44_sibling_citation_is_precise() -> None:
    case = _case_by_id("v3-blind-ans-44")
    expected = set(case["expectedDocuments"])
    assert "內網筆電 VPN 連線問題" in expected
    assert "VPN常見Q&A問答" in expected
    cited = {"內網筆電 VPN 連線問題", "VPN常見Q&A問答"}
    assert _citation_precision(cited=cited, expected=expected) == 1.0


def test_hn_02_accepts_jinkong_sibling_not_ad() -> None:
    case = _case_by_id("v3-blind-hn-02")
    expected = set(case["expectedDocuments"])
    forbidden = set(case["forbiddenSourceTitles"])
    assert "金控入口網密碼變更方式" in expected
    assert "AD 帳號與系統解鎖 FAQ" in forbidden
    cited = {
        "國泰員工入口網、CTeam密碼、國泰e點名",
        "金控入口網密碼變更方式",
    }
    assert _citation_precision(cited=cited, expected=expected) == 1.0
    assert not (cited & forbidden)


def test_scope_summaries_cover_softened_must_contain() -> None:
    eval_mod = _load_eval_module()
    scope_02 = _case_by_id("v3-blind-scope-02")
    scope_03 = _case_by_id("v3-blind-scope-03")
    assert scope_02["expectedEvidence"][0]["mustContain"] == ["錯誤"]
    assert scope_03["expectedEvidence"][0]["mustContain"] == [
        "信件主旨格式",
        "提問所需資訊",
    ]

    short_scope_02 = (
        "「VPN常見Q&A問答」文件主要涵蓋 VPN 連線時常見的錯誤代碼、異常情況"
        "及其對應的處理方式 [S1]。"
    )
    short_scope_03 = (
        "「資訊問題的通報格式」文件主要規範客服人員應遵循的信件主旨格式"
        "與提問所需資訊 [S1]。"
    )
    assert eval_mod._answer_covers_evidence_fact(
        answer=short_scope_02,
        must_contain=scope_02["expectedEvidence"][0]["mustContain"],
        cited_titles=scope_02["expectedSourceTitles"],
    )
    assert eval_mod._answer_covers_evidence_fact(
        answer=short_scope_03,
        must_contain=scope_03["expectedEvidence"][0]["mustContain"],
        cited_titles=scope_03["expectedSourceTitles"],
    )
