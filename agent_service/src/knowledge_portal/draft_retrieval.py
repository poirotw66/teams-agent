from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from agent_service.documents import load_source_chunks
from agent_service.knowledge_release import read_active_release_id, release_index_path
from agent_service.retrieval import HybridIndex

from .draft_assets import DraftAssetStore
from .models import KnowledgeVersionRecord
from .settings import PortalSettings
from .validation import build_front_matter_markdown


@dataclass(frozen=True)
class DraftSearchHit:
    chunk_id: str
    title: str
    source_path: str
    content: str
    score: float


@dataclass(frozen=True)
class DraftSearchResult:
    hits: list[DraftSearchHit]
    matched_draft: bool
    leaked_from_active_release: bool


def _write_version_source(version: KnowledgeVersionRecord, sources_dir: Path) -> None:
    body = version.canonical_content
    if not body.lstrip().startswith("---"):
        body = build_front_matter_markdown(
            title=version.title,
            owner_unit_id=version.owner_unit_id,
            effective_at=version.effective_at,
            review_due_at=version.review_due_at,
            audience_type=version.audience_type,
            audience_group_ids=version.audience_group_ids,
            version_number=version.version_number,
            body=body,
        )
    target = sources_dir / f"{version.document_id}.md"
    target.write_text(body, encoding="utf-8")


def build_draft_index(
    version: KnowledgeVersionRecord,
    settings: PortalSettings,
) -> HybridIndex:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        store = DraftAssetStore(settings)
        store.materialize_workspace(
            temp_root,
            version=version,
            source_filename=f"{version.document_id}.md",
        )
        chunks = load_source_chunks(
            temp_root,
            settings.chunk_size,
            settings.chunk_overlap,
        )
        if not chunks:
            raise ValueError("Draft content produced zero searchable segments.")
        return HybridIndex(chunks, settings.embedding_model)


def search_draft_version(
    *,
    version: KnowledgeVersionRecord,
    query: str,
    groups: list[str],
    settings: PortalSettings,
    limit: int = 4,
) -> DraftSearchResult:
    index = build_draft_index(version, settings)
    raw_hits = index.search(query, limit, set(groups))
    hits = [
        DraftSearchHit(
            chunk_id=result.chunk.chunk_id,
            title=result.chunk.title,
            source_path=result.chunk.source_path,
            content=result.chunk.content,
            score=result.score,
        )
        for result in raw_hits
    ]
    matched_draft = any(
        hit.title == version.title or version.document_id in hit.source_path
        for hit in hits
    )
    leaked = False
    active_release_id = read_active_release_id(settings.release_artifact_dir)
    if active_release_id:
        active_index_path = release_index_path(
            settings.release_artifact_dir,
            active_release_id,
        )
        if active_index_path.is_file():
            active_index = HybridIndex.load(active_index_path, settings.embedding_model)
            active_hits = active_index.search(query, limit, set(groups))
            leaked = any(
                hit.chunk.title != version.title for hit in active_hits
            ) and bool(active_hits)
    return DraftSearchResult(
        hits=hits,
        matched_draft=matched_draft,
        leaked_from_active_release=leaked,
    )


def evaluate_test_case(
    *,
    version: KnowledgeVersionRecord,
    question: str,
    simulated_audience: list[str],
    settings: PortalSettings,
) -> tuple[str, str, list[str], str]:
    if len(question.strip()) < 4:
        return "FAIL", "", [], "Question is too short."

    result = search_draft_version(
        version=version,
        query=question,
        groups=simulated_audience,
        settings=settings,
    )
    cited_titles = [hit.title for hit in result.hits]
    answer_excerpt = result.hits[0].content[:240] if result.hits else ""

    if not result.hits:
        return "FAIL", answer_excerpt, cited_titles, "Draft index returned no hits."
    if result.leaked_from_active_release and not result.matched_draft:
        return (
            "FAIL",
            answer_excerpt,
            cited_titles,
            "Active release answers this question with a different document.",
        )
    if result.matched_draft:
        return "PASS", answer_excerpt, cited_titles, ""
    return (
        "NEEDS_REVIEW",
        answer_excerpt,
        cited_titles,
        "Draft did not rank as the top matched document.",
    )
