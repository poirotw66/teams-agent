"""Unit tests for the pure scoring layer of scripts/retrieval_ab_test.py (spec §18.7).

``scripts/retrieval_ab_test.py`` lives outside the ``agent_service`` package
(it is a standalone CLI, never imported by pytest as a package module) and
is not on ``testpaths``, so it is loaded here by file path via
``importlib.util``. Only the pure, I/O-free functions declared before the
"# --- I/O layer" marker in that file are exercised -- no network, no LLM,
no filesystem beyond loading the module itself.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "retrieval_ab_test.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("retrieval_ab_test", _SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ab = _load_module()


def make_case(**overrides) -> ab.EvalCase:
    defaults = {
        "id": "c1",
        "categories": ("answerable",),
        "query": "VPN 密碼被鎖怎麼辦？",
        "expected_found": True,
        "expected_source_titles": ("VPN常見Q&A問答",),
        "expected_keywords": ("密碼",),
        "expected_image_paths": (),
        "groups": (),
        "notes": "",
    }
    defaults.update(overrides)
    return ab.EvalCase(**defaults)


def make_run(**overrides) -> ab.CaseRun:
    defaults = {
        "case_id": "c1",
        "found": True,
        "answer": "請確認密碼是否過期 [S1]",
        "citation_titles": ("VPN常見Q&A問答",),
        "image_paths": (),
        "retrieved_titles": ("VPN常見Q&A問答",),
        "latency_seconds": 0.5,
        "llm_calls": 2,
        "cost_usd": 0.0001,
        "error": None,
    }
    defaults.update(overrides)
    return ab.CaseRun(**defaults)


# --- score_answer_accuracy ---------------------------------------------------


def test_answer_accuracy_true_when_found_and_keyword_present():
    case = make_case()
    run = make_run()
    assert ab.score_answer_accuracy(case, run) is True


def test_answer_accuracy_false_when_keyword_missing():
    case = make_case(expected_keywords=("Fortinet 授權",))
    run = make_run(answer="請確認密碼是否過期")
    assert ab.score_answer_accuracy(case, run) is False


def test_answer_accuracy_false_when_not_found():
    case = make_case()
    run = make_run(found=False, answer="")
    assert ab.score_answer_accuracy(case, run) is False


def test_answer_accuracy_false_on_error():
    case = make_case()
    run = make_run(error="timeout")
    assert ab.score_answer_accuracy(case, run) is False


def test_answer_accuracy_not_applicable_for_no_answer_case():
    case = make_case(expected_found=False, expected_source_titles=(), expected_keywords=())
    run = make_run(found=False, answer="")
    assert ab.score_answer_accuracy(case, run) is None


def test_answer_accuracy_case_insensitive_keyword_match():
    case = make_case(expected_keywords=("FortiClient",))
    run = make_run(answer="請更新 fortિclient".replace("ి", ""))
    # sanity: plain ascii case-insensitivity
    run = make_run(answer="請更新 fortclient 版本")
    case = make_case(expected_keywords=("FORTCLIENT",))
    assert ab.score_answer_accuracy(case, run) is True


# --- score_recall_at_k --------------------------------------------------------


def test_recall_at_k_true_when_expected_title_retrieved():
    case = make_case()
    run = make_run(retrieved_titles=("其他文件", "VPN常見Q&A問答"))
    assert ab.score_recall_at_k(case, run) is True


def test_recall_at_k_false_when_expected_title_missing():
    case = make_case()
    run = make_run(retrieved_titles=("其他文件",))
    assert ab.score_recall_at_k(case, run) is False


def test_recall_at_k_not_applicable_without_expected_titles():
    case = make_case(expected_source_titles=())
    run = make_run()
    assert ab.score_recall_at_k(case, run) is None


# --- score_groundedness --------------------------------------------------------


def test_groundedness_true_when_all_citations_known():
    run = make_run(citation_titles=("VPN常見Q&A問答",))
    assert ab.score_groundedness(run, frozenset({"VPN常見Q&A問答", "XQ問題"})) is True


def test_groundedness_false_when_citation_is_fabricated():
    run = make_run(citation_titles=("不存在的文件",))
    assert ab.score_groundedness(run, frozenset({"VPN常見Q&A問答"})) is False


def test_groundedness_false_when_found_with_no_citations():
    run = make_run(citation_titles=())
    assert ab.score_groundedness(run, frozenset({"VPN常見Q&A問答"})) is False


def test_groundedness_not_applicable_when_not_found():
    run = make_run(found=False, citation_titles=())
    assert ab.score_groundedness(run, frozenset()) is None


def test_groundedness_not_applicable_on_error():
    run = make_run(error="boom")
    assert ab.score_groundedness(run, frozenset({"VPN常見Q&A問答"})) is None


# --- score_citation_accuracy ---------------------------------------------------


def test_citation_accuracy_true_when_citation_matches_expected():
    case = make_case()
    run = make_run(citation_titles=("VPN常見Q&A問答",))
    assert ab.score_citation_accuracy(case, run) is True


def test_citation_accuracy_false_when_citation_wrong_doc():
    case = make_case()
    run = make_run(citation_titles=("XQ問題",))
    assert ab.score_citation_accuracy(case, run) is False


def test_citation_accuracy_false_when_no_citations():
    case = make_case()
    run = make_run(citation_titles=())
    assert ab.score_citation_accuracy(case, run) is False


def test_citation_accuracy_not_applicable_for_no_answer_case():
    case = make_case(expected_found=False, expected_source_titles=())
    run = make_run(found=False, citation_titles=())
    assert ab.score_citation_accuracy(case, run) is None


# --- score_no_answer_accuracy --------------------------------------------------


def test_no_answer_accuracy_true_when_not_found():
    case = make_case(expected_found=False, expected_source_titles=(), expected_keywords=())
    run = make_run(found=False, answer="")
    assert ab.score_no_answer_accuracy(case, run) is True


def test_no_answer_accuracy_true_when_answer_explicitly_declines():
    case = make_case(expected_found=False, expected_source_titles=(), expected_keywords=())
    run = make_run(found=True, answer="目前知識庫沒有足夠資訊可以回答這個問題。")
    assert ab.score_no_answer_accuracy(case, run) is True


def test_no_answer_accuracy_false_when_it_fabricates_an_answer():
    case = make_case(expected_found=False, expected_source_titles=(), expected_keywords=())
    run = make_run(found=True, answer="請重置 SAP 密碼並聯繫管理員。")
    assert ab.score_no_answer_accuracy(case, run) is False


def test_no_answer_accuracy_not_applicable_for_answerable_case():
    case = make_case()
    run = make_run()
    assert ab.score_no_answer_accuracy(case, run) is None


# --- score_error_code_accuracy -------------------------------------------------


def test_error_code_accuracy_uses_answer_accuracy_when_expected_found():
    case = make_case(categories=("answerable", "error_code"))
    run = make_run()
    assert ab.score_error_code_accuracy(case, run) is True


def test_error_code_accuracy_uses_no_answer_accuracy_when_undocumented():
    case = make_case(
        categories=("no_answer", "error_code"),
        expected_found=False,
        expected_source_titles=(),
        expected_keywords=(),
    )
    run = make_run(found=False, answer="")
    assert ab.score_error_code_accuracy(case, run) is True


def test_error_code_accuracy_not_applicable_without_category():
    case = make_case(categories=("answerable",))
    run = make_run()
    assert ab.score_error_code_accuracy(case, run) is None


# --- score_acl_accuracy ---------------------------------------------------------


def test_acl_accuracy_true_when_visibility_matches():
    case = make_case(categories=("answerable", "acl"), expected_found=True)
    run = make_run(found=True)
    assert ab.score_acl_accuracy(case, run) is True


def test_acl_accuracy_false_when_visibility_mismatched():
    case = make_case(categories=("acl",), expected_found=False)
    run = make_run(found=True)
    assert ab.score_acl_accuracy(case, run) is False


def test_acl_accuracy_not_applicable_without_category():
    case = make_case(categories=("answerable",))
    run = make_run()
    assert ab.score_acl_accuracy(case, run) is None


# --- score_image_match_accuracy --------------------------------------------------


def test_image_match_true_when_expected_image_present():
    case = make_case(expected_image_paths=("doc/p01.png",))
    run = make_run(image_paths=("doc/p01.png", "doc/p02.png"))
    assert ab.score_image_match_accuracy(case, run) is True


def test_image_match_false_when_expected_image_missing():
    case = make_case(expected_image_paths=("doc/p01.png",))
    run = make_run(image_paths=("doc/p02.png",))
    assert ab.score_image_match_accuracy(case, run) is False


def test_image_match_not_applicable_without_expected_images():
    case = make_case(expected_image_paths=())
    run = make_run()
    assert ab.score_image_match_accuracy(case, run) is None


# --- percentile -----------------------------------------------------------------


def test_percentile_empty_is_none():
    assert ab.percentile([], 0.95) is None


def test_percentile_single_value():
    assert ab.percentile([3.0], 0.95) == 3.0


def test_percentile_p50_matches_median_for_odd_length():
    assert ab.percentile([1.0, 2.0, 3.0], 0.5) == 2.0


def test_percentile_p95_of_uniform_sequence():
    values = [float(i) for i in range(1, 101)]  # 1..100
    result = ab.percentile(values, 0.95)
    assert result == pytest.approx(95.05, abs=0.01)


# --- aggregate --------------------------------------------------------------------


def test_aggregate_computes_accuracy_and_latency_across_cases():
    cases = [
        make_case(id="a", expected_found=True, expected_source_titles=("Doc1",)),
        make_case(
            id="b",
            categories=("no_answer",),
            expected_found=False,
            expected_source_titles=(),
            expected_keywords=(),
        ),
    ]
    runs = {
        "a": make_run(
            case_id="a",
            found=True,
            citation_titles=("Doc1",),
            retrieved_titles=("Doc1",),
            latency_seconds=1.0,
            llm_calls=2,
            cost_usd=0.001,
        ),
        "b": make_run(
            case_id="b", found=False, answer="", citation_titles=(), latency_seconds=0.2,
            llm_calls=1, cost_usd=0.0002,
        ),
    }
    report = ab.aggregate(cases, runs, frozenset({"Doc1"}))

    assert report["total_cases"] == 2
    assert report["errors"] == 0
    assert report["answer_accuracy"]["applicable_cases"] == 1
    assert report["answer_accuracy"]["accuracy"] == 1.0
    assert report["no_answer_accuracy"]["applicable_cases"] == 1
    assert report["no_answer_accuracy"]["accuracy"] == 1.0
    assert report["p50_latency_seconds"] is not None
    assert report["avg_llm_calls_per_query"] == 1.5
    assert report["cost_complete"] is True


def test_aggregate_marks_cost_incomplete_when_some_costs_missing():
    cases = [make_case(id="a")]
    runs = {"a": make_run(case_id="a", cost_usd=None)}
    report = ab.aggregate(cases, runs, frozenset({"VPN常見Q&A問答"}))
    assert report["cost_complete"] is False


def test_aggregate_skips_cases_with_no_matching_run():
    cases = [make_case(id="a"), make_case(id="missing")]
    runs = {"a": make_run(case_id="a")}
    report = ab.aggregate(cases, runs, frozenset({"VPN常見Q&A問答"}))
    assert report["total_cases"] == 2
    assert report["answer_accuracy"]["applicable_cases"] == 1


# --- EvalCase.from_dict / load_eval_set ------------------------------------------


def test_eval_case_from_dict_roundtrip():
    case = ab.EvalCase.from_dict(
        {
            "id": "x1",
            "categories": ["answerable", "error_code"],
            "query": "VPN -14 錯誤",
            "expectedFound": True,
            "expectedSourceTitles": ["VPN常見Q&A問答"],
            "expectedKeywords": ["FortiClient"],
            "expectedImagePaths": [],
            "groups": ["G1"],
            "notes": "n",
        }
    )
    assert case.id == "x1"
    assert case.categories == ("answerable", "error_code")
    assert case.expected_found is True
    assert case.expected_source_titles == ("VPN常見Q&A問答",)
    assert case.groups == ("G1",)


def test_load_eval_set_reads_real_fixture():
    eval_set_path = (
        Path(__file__).resolve().parents[2] / "data" / "eval" / "retrieval_eval_set.json"
    )
    cases = ab.load_eval_set(eval_set_path)
    assert len(cases) >= 20
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids)), "eval case ids must be unique"
    categories_seen = {category for case in cases for category in case.categories}
    assert {"answerable", "no_answer", "error_code", "acl", "image"} <= categories_seen
