"""Synthetic candidate case construction for evaluation generation jobs."""

from __future__ import annotations

from typing import Any

from .models import (
    CriterionItem,
    EvaluationCriteria,
    EvidenceItem,
    EvidenceRequirement,
    ProvenanceSpec,
)

_QUERY_PREFIX_BY_BEHAVIOR = {
    "ANSWER_WITH_CITATION": "請問關於",
    "CLARIFY": "如何申請",
    "REFUSE": "請提供外部非公開機密",
    "HANDOFF": "我需要人工專員處理",
    "TOOL_TASK": "查詢我的目前狀態",
}


def build_synthetic_candidate_case(
    *,
    index: int,
    source_ref: dict[str, Any],
    behavior: str,
) -> dict[str, Any]:
    s_type = source_ref.get("source_type", "FAQ")
    s_id = source_ref.get("source_id", "faq_unknown")
    s_version = source_ref.get("version_id", "v1")
    s_title = source_ref.get("title", f"Source {s_id}")
    query_prefix = _QUERY_PREFIX_BY_BEHAVIOR.get(behavior, "請問")
    query = f"{query_prefix}{s_title}的相關規範是什麼？（候選 #{index + 1}）"
    title = f"候選：{s_title} ({behavior})"

    evidence_item = EvidenceItem(
        evidence_id=f"ev_{index + 1}",
        source_type="FAQ" if s_type == "FAQ" else "DOCUMENT",
        source_id=s_id,
        version_id=s_version,
        text=f"來自 {s_title} 的內容依據",
    )
    evidence = (
        (EvidenceRequirement(group_id="primary", items=(evidence_item,)),)
        if behavior != "REFUSE"
        else ()
    )
    criteria = EvaluationCriteria(
        required_facts=(
            CriterionItem(
                criterion_id="crit_1",
                description=f"回答應說明 {s_title} 的核心規定",
                is_mandatory=True,
            ),
        )
        if behavior != "REFUSE"
        else (),
        reference_answer=(f"這是針對 {s_title} 的候選參考回答。" if behavior != "REFUSE" else None),
    )
    provenance = ProvenanceSpec(
        source_type="SYNTHETIC",
        source_id=s_id,
        source_version_id=s_version,
        generator_model="gemini-3.8-flash",
        generator_prompt_version="synth-eval-v1",
    )
    return {
        "title": title,
        "query": query,
        "behavior": behavior,
        "criteria": criteria,
        "evidence": evidence,
        "tags": ("synthetic", "candidate", behavior.lower()),
        "criticality": "NORMAL",
        "provenance": provenance,
    }
