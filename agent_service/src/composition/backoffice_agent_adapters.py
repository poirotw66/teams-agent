"""Composition adapters wrapping Agent runtime for Backoffice ports.

Keeps ai_ops_backoffice free of agent_service imports while preserving
ops runtime, GCS artifacts, chat models, REAL_RAG retrieval, and eval harnesses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_service.artifact_storage import GcsArtifactStorage, build_gcs_storage_client
from agent_service.graph import build_chat_model
from agent_service.knowledge import ANSWER_PROMPT
from agent_service.operations.policy_runtime import (
    PolicyRuntime,
    configure_policy_runtime,
    get_policy_runtime,
)
from agent_service.operations.runtime import build_ops_runtime
from agent_service.retrieval import HybridIndex
from agent_service.settings import RagSettings
from ai_ops_backoffice.ports.answer_prompt import configure_default_answer_prompt
from ai_ops_backoffice.ports.chat_model import configure_chat_model_factory
from ai_ops_backoffice.ports.default_chat_model import configure_default_chat_model_id
from ai_ops_backoffice.ports.eval_agent import configure_eval_agent_bindings
from ai_ops_backoffice.ports.governance_policy import configure_governance_policy_configurer
from ai_ops_backoffice.ports.retrieval import (
    HybridIndexPort,
    configure_hybrid_index_factory,
)
from ai_ops_backoffice.services.freshness_service import FreshnessTracker
from ai_ops_backoffice.services.query_collaborators import (
    configure_query_service_collaborators,
)
from ai_ops_backoffice.settings import BackofficeSettings
from composition.backoffice_eval_agent_factory import AgentEvalBindings
from knowledge_core.artifact_ports import ArtifactStorage, LocalFileArtifactStorage
from knowledge_core.document_models import DocumentChunk
from operations_core.settings import OpsSettings

__all__ = [
    "configure_backoffice_agent_adapters",
]


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


def build_backoffice_ops_runtime(
    settings: OpsSettings,
    *,
    freshness_recorder: FreshnessTracker | None = None,
) -> object | None:
    return build_ops_runtime(settings, freshness_recorder=freshness_recorder)


def build_backoffice_artifact_storage(settings: BackofficeSettings) -> ArtifactStorage:
    artifact_backend = (getattr(settings, "artifact_storage_backend", None) or "FILE").upper()
    if artifact_backend == "GCS":
        bucket = getattr(settings, "artifact_gcs_bucket", None)
        if not bucket:
            raise ValueError(
                "AI_OPS_ARTIFACT_GCS_BUCKET (or AI_OPS_EXPORT_GCS_BUCKET) is required "
                "for GCS artifact storage."
            )
        return GcsArtifactStorage(
            bucket_name=bucket,
            client=build_gcs_storage_client(),
            allow_memory_fallback=False,
        )
    artifact_path = getattr(settings, "artifact_storage_path", None) or (
        settings.ops_store_path.parent / "sources" / "artifacts"
    )
    return LocalFileArtifactStorage(artifact_path)


def _install_governance_policy_runtime(
    query_service: Any,
    governance_service: Any,
) -> None:
    existing_runtime = get_policy_runtime()
    policy_settings = (
        existing_runtime.settings
        if existing_runtime is not None
        else query_service.runtime_settings
    )
    configure_policy_runtime(
        PolicyRuntime(settings=policy_settings, governance=governance_service)
    )


def configure_backoffice_agent_adapters() -> None:
    """Install Agent-backed Backoffice ports (safe to call repeatedly)."""

    configure_chat_model_factory(build_chat_model)
    configure_default_answer_prompt(lambda: ANSWER_PROMPT)
    configure_default_chat_model_id(lambda: RagSettings.from_env().model)
    configure_hybrid_index_factory(AgentHybridIndexFactory())
    configure_governance_policy_configurer(_install_governance_policy_runtime)
    configure_query_service_collaborators(
        ops_runtime_builder=build_backoffice_ops_runtime,
        artifact_storage_builder=build_backoffice_artifact_storage,
    )
    configure_eval_agent_bindings(AgentEvalBindings())
