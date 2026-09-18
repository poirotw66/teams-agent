"""Composition adapters wrapping Agent runtime for Knowledge Portal ports.

Keeps knowledge_portal free of agent_service imports while preserving
HybridIndex, Document AI, Firestore, and release GCS behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_service.document_parsing import DocumentAiLayoutParser
from agent_service.knowledge_release_gcs import publish_release_directory
from agent_service.operations.stores.firestore_store import build_sync_firestore_client
from agent_service.retrieval import HybridIndex
from composition.portal_artifact_storage import build_portal_gcs_artifact_storage
from knowledge_core.document_models import DocumentChunk
from knowledge_portal.original_assets import configure_gcs_artifact_storage_provider
from knowledge_portal.ports.document_ai import (
    PdfLayoutParser,
    configure_pdf_layout_parser_factory,
)
from knowledge_portal.ports.firestore import configure_firestore_client_factory
from knowledge_portal.ports.release_publish import (
    PublishedReleaseInfo,
    configure_release_directory_publisher,
)
from knowledge_portal.ports.retrieval import (
    HybridIndexPort,
    configure_hybrid_index_factory,
)
from knowledge_portal.settings import PortalSettings


class AgentHybridIndexFactory:
    def create(
        self,
        chunks: list[DocumentChunk],
        embedding_model: str | None = None,
    ) -> HybridIndexPort:
        return HybridIndex(chunks, embedding_model)

    def load(
        self,
        index_path: Path,
        embedding_model: str | None = None,
    ) -> HybridIndexPort:
        return HybridIndex.load(index_path, embedding_model)


class AgentReleaseDirectoryPublisher:
    def publish(
        self,
        release_dir: Path,
        *,
        bucket_name: str,
        object_prefix: str,
        tenant_id: str,
        release_id: str,
    ) -> PublishedReleaseInfo:
        published = publish_release_directory(
            release_dir,
            bucket_name=bucket_name,
            object_prefix=object_prefix,
            tenant_id=tenant_id,
            release_id=release_id,
        )
        return PublishedReleaseInfo(
            bucket=published.bucket,
            object_prefix=published.object_prefix,
            manifest_generation=published.manifest_generation,
            index_generation=published.index_generation,
        )


class AgentPdfLayoutParserFactory:
    def create(self, processor_name: str) -> PdfLayoutParser:
        return DocumentAiLayoutParser(processor_name)


class AgentFirestoreClientFactory:
    def create(self, project_id: str | None, database_id: str | None) -> Any:
        return build_sync_firestore_client(project_id, database_id)


def configure_portal_agent_adapters() -> None:
    """Install Agent-backed Portal ports (safe to call repeatedly)."""

    configure_hybrid_index_factory(AgentHybridIndexFactory())
    configure_release_directory_publisher(AgentReleaseDirectoryPublisher())
    configure_pdf_layout_parser_factory(AgentPdfLayoutParserFactory())
    configure_firestore_client_factory(AgentFirestoreClientFactory())
    configure_gcs_artifact_storage_provider(build_portal_gcs_artifact_storage)


def build_portal_gcs_artifact_storage_for_settings(settings: PortalSettings) -> Any | None:
    """Compatibility alias used by portal_app wiring."""

    return build_portal_gcs_artifact_storage(settings)
