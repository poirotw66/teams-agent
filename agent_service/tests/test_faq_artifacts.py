"""FAQ activation artifacts are durable exports, not RAG sources."""

from __future__ import annotations

from pathlib import Path

from agent_service.operations.access import ActorContext
from ai_ops_backoffice.faq_domain import FaqContent, FaqDomainService, InMemoryFaqRepository
from ai_ops_backoffice.faq_domain.artifacts import write_faq_activation_artifact

from test_backoffice_faq_domain import AllowFaqAuthority, ActiveTaxonomy, approve, content


def test_activation_writes_versioned_faq_artifact_files(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "faq-artifacts"
    svc = FaqDomainService(
        InMemoryFaqRepository(),
        authorization=AllowFaqAuthority(),
        taxonomy=ActiveTaxonomy(),
        artifact_dir=artifact_dir,
    )
    writer = ActorContext("writer", "Writer", "KNOWLEDGE_ADMIN", ("it",))
    reviewer = ActorContext("reviewer", "Reviewer", "KNOWLEDGE_ADMIN", ("it",))
    created = svc.create(
        content=content(related_docs=("doc-vpn-sop",)),
        actor=writer,
    )
    approved = approve(svc, created["faq"], created["version"], writer, reviewer)
    activated = svc.activate(
        faq_id=approved["faq"]["faq_id"],
        version_id=approved["version"]["version_id"],
        actor=reviewer,
        expected_etag=approved["faq"]["etag"],
        reason="publish fixed answer",
    )

    key_dir = artifact_dir / "VPN_LOCKED"
    assert list(key_dir.glob("v*.md"))
    assert list(key_dir.glob("v*.json"))
    active = (key_dir / "ACTIVE.md").read_text(encoding="utf-8")
    assert "Fixed Answer" in active
    assert "not a Knowledge RAG source" in active
    assert "doc-vpn-sop" in active
    assert activated["faq"]["status"] == "ACTIVE"


def test_related_document_ids_round_trip_in_artifact(tmp_path: Path) -> None:
    linked = FaqContent(
        **{
            **content().model_dump(),
            "related_document_ids": ("doc-sop-1", "doc-sop-2"),
        }
    )
    path = write_faq_activation_artifact(
        tmp_path,
        faq={"faq_id": "faq-1", "faq_key": "VPN_LOCKED"},
        version={
            "version_id": "ver-1",
            "version_number": 1,
            "status": "ACTIVE",
            "content": linked.model_dump(mode="json"),
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "doc-sop-1" in text
    assert "indexedForRag" not in text  # markdown body; flag lives in sidecar JSON
    sidecar = path.with_suffix(".json").read_text(encoding="utf-8")
    assert '"indexedForRag": false' in sidecar
