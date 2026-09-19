"""Deterministic contextual retrieval text (RAG v2 Milestone 2).

Builds ``retrieval_context`` / ``retrieval_text`` without LLM generation.
Generation and citation must keep using raw ``chunk.content``.
"""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_core.document_models import DocumentChunk

CONTEXTUALIZATION_VERSION = "contextual-v1"


@dataclass(frozen=True)
class ContextualRepresentation:
    context: str
    retrieval_text: str
    version: str = CONTEXTUALIZATION_VERSION


def build_contextual_representation(chunk: DocumentChunk) -> ContextualRepresentation:
    """Compose a deterministic retrieval prefix from safe chunk metadata."""
    lines: list[str] = []
    title = (chunk.metadata.title if chunk.metadata and chunk.metadata.title else None) or chunk.title
    if title:
        lines.append(f"文件：{title}")
    aliases = [alias for alias in chunk.source_aliases if alias and alias != title]
    if aliases:
        lines.append(f"別名：{' / '.join(aliases)}")
    category = chunk.metadata.category if chunk.metadata else None
    if category:
        lines.append(f"分類：{category}")
    heading = " > ".join(part for part in chunk.heading_path if part)
    section = chunk.section_path or chunk.section or ""
    if heading:
        lines.append(f"章節：{heading}")
    elif section:
        lines.append(f"章節：{section}")
    if chunk.source_type:
        lines.append(f"來源類型：{chunk.source_type}")
    version = chunk.metadata.version if chunk.metadata else None
    if version:
        lines.append(f"版本：{version}")
    effective = None
    if chunk.metadata and chunk.metadata.effective_date:
        effective = chunk.metadata.effective_date
    elif chunk.effective_at:
        effective = chunk.effective_at
    if effective:
        lines.append(f"生效：{effective}")

    context = "\n".join(lines).strip()
    content = chunk.content.strip()
    if context and content:
        retrieval_text = f"{context}\n\n{content}"
    else:
        retrieval_text = context or content or f"{chunk.title}\n{chunk.content}".strip()
    return ContextualRepresentation(context=context, retrieval_text=retrieval_text)


def apply_contextual_representation(chunk: DocumentChunk) -> DocumentChunk:
    """Return a chunk copy with ``retrieval_context`` / ``retrieval_text`` filled."""
    built = build_contextual_representation(chunk)
    chunk.retrieval_context = built.context
    chunk.retrieval_text = built.retrieval_text
    chunk.contextualization_version = built.version
    return chunk


def effective_retrieval_text(chunk: DocumentChunk) -> str:
    """Prefer stored retrieval_text; fall back to v1 title+content."""
    stored = (chunk.retrieval_text or "").strip()
    if stored:
        return stored
    title = (chunk.title or "").strip()
    content = (chunk.content or "").strip()
    if title and content:
        return f"{title}\n{content}"
    return title or content


__all__ = [
    "CONTEXTUALIZATION_VERSION",
    "ContextualRepresentation",
    "apply_contextual_representation",
    "build_contextual_representation",
    "effective_retrieval_text",
]
