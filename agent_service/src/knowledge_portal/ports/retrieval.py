"""Hybrid retrieval port so Portal never imports Agent HybridIndex."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from knowledge_core.document_models import DocumentChunk

__all__ = [
    "HybridIndexFactory",
    "HybridIndexPort",
    "HybridSearchHit",
    "configure_hybrid_index_factory",
    "get_hybrid_index_factory",
]


@runtime_checkable
class HybridSearchHit(Protocol):
    chunk: DocumentChunk
    score: float


@runtime_checkable
class HybridIndexPort(Protocol):
    def search(
        self,
        query: str,
        limit: int,
        groups: set[str] | None = None,
    ) -> list[HybridSearchHit]:
        ...

    def save(self, index_path: Path) -> None:
        ...

    def add_embeddings(self, *, only_missing: bool = False) -> None:
        ...


@runtime_checkable
class HybridIndexFactory(Protocol):
    def create(
        self,
        chunks: list[DocumentChunk],
        embedding_model: str | None = None,
    ) -> HybridIndexPort:
        ...

    def load(
        self,
        index_path: Path,
        embedding_model: str | None = None,
    ) -> HybridIndexPort:
        ...


_hybrid_index_factory: HybridIndexFactory | None = None


def configure_hybrid_index_factory(factory: HybridIndexFactory | None) -> None:
    """Register composition-owned HybridIndex factory for Portal retrieval."""

    global _hybrid_index_factory
    _hybrid_index_factory = factory


def get_hybrid_index_factory() -> HybridIndexFactory:
    if _hybrid_index_factory is None:
        raise RuntimeError(
            "Hybrid index factory is not configured. "
            "Wire it through composition.portal_app."
        )
    return _hybrid_index_factory
