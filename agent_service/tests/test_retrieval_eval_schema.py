"""Tests for evidence-level eval schema (RAG v2.1)."""

from __future__ import annotations

from agent_service.retrieval_eval_schema import EvidenceLevelCase


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
