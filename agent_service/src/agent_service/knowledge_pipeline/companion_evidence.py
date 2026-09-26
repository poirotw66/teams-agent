from __future__ import annotations

from collections.abc import Sequence

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult

from .document_selection import (
    inject_employee_portal_password_evidence,
    inject_enterprise_app_evidence,
    inject_same_doc_discrimination_evidence,
    inject_shu_channel_evidence,
    inject_ticket_intake_checklist,
    inject_vpn_password_expiry_howto,
)


def inject_companion_evidence(
    query: str,
    results: list[SearchResult],
    *,
    index_chunks: Sequence[DocumentChunk],
    groups: set[str],
    environment: str,
) -> list[SearchResult]:
    boosted = inject_enterprise_app_evidence(
        query,
        results,
        index_chunks=index_chunks,
        groups=groups,
        environment=environment,
    )
    boosted = inject_employee_portal_password_evidence(
        query,
        boosted,
        index_chunks=index_chunks,
        groups=groups,
        environment=environment,
    )
    boosted = inject_vpn_password_expiry_howto(
        query,
        boosted,
        index_chunks=index_chunks,
        groups=groups,
        environment=environment,
    )
    boosted = inject_shu_channel_evidence(
        query,
        boosted,
        index_chunks=index_chunks,
        groups=groups,
        environment=environment,
    )
    boosted = inject_ticket_intake_checklist(
        query,
        boosted,
        index_chunks=index_chunks,
        groups=groups,
        environment=environment,
    )
    return inject_same_doc_discrimination_evidence(
        query,
        boosted,
        index_chunks=index_chunks,
        groups=groups,
        environment=environment,
    )
