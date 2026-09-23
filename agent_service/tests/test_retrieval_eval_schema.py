"""Tests for evidence-level eval schema (RAG v2.1)."""

from __future__ import annotations

from agent_service.retrieval_eval_schema import (
    EvidenceLevelCase,
    compose_follow_up_retrieval_query,
)


def test_evidence_case_prefers_chunk_ids_over_titles() -> None:
    case = EvidenceLevelCase.from_dict(
        {
            "id": "vpn-455",
            "query": "VPN -455 怎麼辦",
            "expectedFound": True,
            "expectedDocuments": ["VPN常見Q&A問答"],
            "expectedChunkIds": ["vpn-455-chunk"],
            "expectedEvidence": [
                {
                    "section": "Permission denied (-455)",
                    "mustContain": ["-455", "密碼"],
                }
            ],
        }
    )
    assert case.primary_relevant_ids() == ("vpn-455-chunk",)
    assert case.expected_evidence[0].must_contain == ("-455", "密碼")


def test_evidence_case_falls_back_to_documents() -> None:
    case = EvidenceLevelCase.from_dict(
        {
            "id": "legacy",
            "query": "vpn",
            "expectedFound": True,
            "expectedSourceTitles": ["VPN常見Q&A問答"],
        }
    )
    assert case.primary_relevant_ids() == ("VPN常見Q&A問答",)


def test_evidence_case_parses_prior_turn_and_hard_negatives() -> None:
    case = EvidenceLevelCase.from_dict(
        {
            "id": "conv-01",
            "query": "那密碼不是 AD 的話要去哪改？",
            "priorTurn": "員工入口網登不進去",
            "expectedFound": True,
            "expectedDocuments": ["國泰員工入口網、CTeam密碼、國泰e點名"],
            "hardNegatives": ["AD 帳號與系統解鎖 FAQ", {"title": "VPN常見Q&A問答"}],
            "groups": ["grp_it"],
            "categories": ["conversational", "answerable"],
        }
    )
    assert case.prior_turn == "員工入口網登不進去"
    assert case.is_multi_turn is True
    assert case.hard_negative_ids == (
        "AD 帳號與系統解鎖 FAQ",
        "VPN常見Q&A問答",
    )
    assert case.groups == ("grp_it",)
    assert case.categories == ("conversational", "answerable")


def test_compose_follow_up_retrieval_query_matches_clarification_merge() -> None:
    composed = compose_follow_up_retrieval_query(
        "員工入口網登不進去",
        "那密碼不是 AD 的話要去哪改？",
    )
    assert composed == "員工入口網登不進去 那密碼不是 AD 的話要去哪改"
