"""Feedback-trace assembly helpers."""

from __future__ import annotations

from typing import Any

from operations_core.contracts import OperationalEvent


def empty_feedback_trace(feedback_event: OperationalEvent) -> dict[str, Any]:
    return {
        "turnId": feedback_event.turn_id,
        "issueTypeId": None,
        "issueDescriptionMasked": None,
        "classificationSource": None,
        "faqKey": None,
        "documentIds": [],
        "releaseIds": [],
        "sourceRefs": [],
        "handoffOccurred": False,
        "handoffStatus": None,
        "route": None,
        "model": None,
    }


def collect_feedback_trace_signals(
    scoped: list[OperationalEvent],
    *,
    issue_id: Any,
) -> dict[str, Any]:
    issue_extracted = None
    issue_classified = None
    faq_key = None
    document_ids: list[str] = []
    release_ids: list[str] = []
    handoff_status = None
    handoff_occurred = False
    detected_route = None
    detected_model = None

    for event in scoped:
        if event.event_type == "route.selected" and event.payload.get("route"):
            detected_route = str(event.payload.get("route"))
        elif event.event_type == "issue.extracted":
            payload_issue_id = event.payload.get("issueId")
            if issue_id is None or payload_issue_id == issue_id:
                issue_extracted = event
            if event.payload.get("route") and not detected_route:
                detected_route = str(event.payload.get("route"))
        if (
            event.event_type == "issue.classified"
            and issue_extracted
            and event.issue_occurrence_id == issue_extracted.issue_occurrence_id
        ):
            issue_classified = event
        if (event.event_type == "usage.recorded" and event.payload.get("model")) or (
            "model" in event.payload and not detected_model
        ):
            detected_model = str(event.payload.get("model"))
        if event.event_type == "faq.answered":
            faq_key = event.payload.get("faqKey") or faq_key
        if event.event_type in {"knowledge.retrieved", "knowledge.answered"}:
            document_id = event.payload.get("documentId")
            if document_id and document_id not in document_ids:
                document_ids.append(str(document_id))
            release_id = event.payload.get("releaseId")
            if release_id and release_id not in release_ids:
                release_ids.append(str(release_id))
            for citation in event.payload.get("citations") or []:
                if not isinstance(citation, dict):
                    continue
                citation_doc = citation.get("documentId")
                if citation_doc and citation_doc not in document_ids:
                    document_ids.append(str(citation_doc))
        if event.event_type.startswith("handoff."):
            handoff_occurred = True
            handoff_status = event.payload.get("status") or event.event_type

    if not detected_route:
        if faq_key:
            detected_route = "FAQ"
        elif document_ids:
            detected_route = "KNOWLEDGE"
        elif handoff_occurred:
            detected_route = "ESCALATE"

    return {
        "issue_extracted": issue_extracted,
        "issue_classified": issue_classified,
        "faq_key": faq_key,
        "document_ids": document_ids,
        "release_ids": release_ids,
        "handoff_status": handoff_status,
        "handoff_occurred": handoff_occurred,
        "detected_route": detected_route,
        "detected_model": detected_model,
    }
