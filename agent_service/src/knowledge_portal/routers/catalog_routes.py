"""Knowledge Portal HTTP routes for independent service-catalog governance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from knowledge_portal.models import PortalActor
from knowledge_portal.rbac import (
    PortalPermissionError,
    ensure_can_approve_catalog,
    ensure_can_review,
    require_minimum_role,
)
from knowledge_portal.service import PortalService
from knowledge_portal.service_catalog_draft_store import (
    CatalogDraftStore,
    build_catalog_draft_store,
)
from knowledge_portal.service_catalog_governance import (
    ServiceCatalogGovernanceError,
    load_catalog_draft,
    save_catalog_draft,
    transition_catalog_draft,
)
from knowledge_portal.settings import PortalSettings


class CatalogServiceRow(BaseModel):
    serviceId: str = Field(min_length=1)
    officialName: str | None = None
    aliases: list[str] = Field(default_factory=list)
    documentId: str = Field(min_length=1)
    versionId: str | None = None
    sourcePath: str | None = None
    aclGroups: list[str] = Field(default_factory=list)
    ownerUnitId: str | None = None


class CatalogDraftUpsertRequest(BaseModel):
    services: list[CatalogServiceRow] = Field(min_length=1)
    tenantId: str | None = None


class CatalogTransitionRequest(BaseModel):
    reason: str | None = None
    tenantId: str | None = None


async def _published_document_ids(service: PortalService, actor: PortalActor) -> set[str]:
    documents = await service._ctx.repository.list_documents(
        actor=actor,
        status="PUBLISHED",
    )
    return {
        document.document_id
        for document in documents
        if getattr(document, "current_published_version_id", None)
    }


async def ensure_catalog_approver_not_document_publisher(
    service: PortalService,
    actor: PortalActor,
    services: list[dict[str, Any]],
    *,
    relaxed_workflow: bool,
) -> None:
    """Block catalog approve when the actor last published a linked document.

    Versions lack ``published_by``; publish sets ``document.updated_by`` to the
    publisher, which is the durable identity used here.
    """
    if relaxed_workflow or actor.role == "PLATFORM":
        return
    for index, row in enumerate(services):
        if not isinstance(row, dict):
            continue
        document_id = str(row.get("documentId") or "").strip()
        if not document_id:
            continue
        document = await service._ctx.repository.get_document(document_id)
        if document is None:
            continue
        publisher = str(getattr(document, "updated_by", "") or "").strip()
        if publisher and publisher == actor.user_id:
            raise PortalPermissionError(
                "Catalog approvers cannot approve entries whose linked "
                f"document they last published (services[{index}] "
                f"documentId='{document_id}')."
            )


def register_catalog_routes(
    app: FastAPI,
    *,
    settings: PortalSettings,
    service: PortalService,
    pdf_job_store: Any,
    authorize: Callable[..., None],
    current_actor: Callable[..., PortalActor],
    correlation_id: Callable[..., str],
    idempotency_key: Callable[..., str | None],
    handle_errors: Callable[[Exception], HTTPException],
) -> None:
    del pdf_job_store, idempotency_key  # unused in this slice

    store: CatalogDraftStore = build_catalog_draft_store(settings)

    def _tenant(actor: PortalActor, explicit: str | None) -> str:
        return (explicit or actor.tenant_id or settings.default_tenant_id or "default").strip()

    def _governance_http(exc: ServiceCatalogGovernanceError) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        )

    def _remaining_gaps() -> list[str]:
        gaps = [
            "live GCS publish/sync verification when bucket/tenant configured",
        ]
        if store.backend_name != "FIRESTORE":
            gaps.insert(
                0,
                "set KNOWLEDGE_PORTAL_REPOSITORY_MODE=FIRESTORE for multi-instance "
                "catalog draft authority (FILE is local-dev fallback)",
            )
        return gaps

    @app.get("/api/catalog")
    async def get_catalog_draft(
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            require_minimum_role(actor, "CONTRIBUTOR")
            draft = load_catalog_draft(
                settings.data_dir,
                tenant_id=_tenant(actor, tenant_id),
                store=store,
            )
            return {
                "draft": draft,
                "governance": store.backend_name,
                # Submitter≠approver via ensure_can_review; catalog approver≠
                # document.updated_by (last publisher) when not relaxed/PLATFORM.
                "remainingGaps": _remaining_gaps(),
            }
        except ServiceCatalogGovernanceError as exc:
            raise _governance_http(exc) from exc
        except PortalPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.put("/api/catalog/draft")
    async def upsert_catalog_draft(
        request: CatalogDraftUpsertRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ) -> dict[str, Any]:
        del correlation_id_value
        try:
            require_minimum_role(actor, "CONTRIBUTOR")
            tenant = _tenant(actor, request.tenantId)
            payload = save_catalog_draft(
                settings.data_dir,
                tenant_id=tenant,
                services=[row.model_dump(mode="python") for row in request.services],
                status="DRAFT",
                actor_id=actor.user_id,
                store=store,
            )
            return {"draft": payload}
        except ServiceCatalogGovernanceError as exc:
            raise _governance_http(exc) from exc
        except PortalPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/catalog/submit-review")
    async def submit_catalog_review(
        request: CatalogTransitionRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ) -> dict[str, Any]:
        try:
            require_minimum_role(actor, "CONTRIBUTOR")
            payload = transition_catalog_draft(
                settings.data_dir,
                tenant_id=_tenant(actor, request.tenantId),
                target_status="IN_REVIEW",
                actor_id=actor.user_id,
                reason=request.reason,
                store=store,
            )
            return {"draft": payload}
        except ServiceCatalogGovernanceError as exc:
            raise _governance_http(exc) from exc
        except PortalPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/catalog/approve")
    async def approve_catalog(
        request: CatalogTransitionRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ) -> dict[str, Any]:
        try:
            draft = load_catalog_draft(
                settings.data_dir,
                tenant_id=_tenant(actor, request.tenantId),
                store=store,
            )
            submitter = str((draft or {}).get("updatedBy") or "").strip()
            relaxed = settings.effective_relaxed_workflow()
            # Distinct from document/release publish (ensure_can_publish).
            ensure_can_approve_catalog(actor, submitter, relaxed_workflow=relaxed)
            services = list((draft or {}).get("services") or [])
            await ensure_catalog_approver_not_document_publisher(
                service,
                actor,
                [item for item in services if isinstance(item, dict)],
                relaxed_workflow=relaxed,
            )
            published_ids = await _published_document_ids(service, actor)
            payload = transition_catalog_draft(
                settings.data_dir,
                tenant_id=_tenant(actor, request.tenantId),
                target_status="APPROVED",
                actor_id=actor.user_id,
                reason=request.reason,
                published_document_ids=published_ids,
                store=store,
            )
            return {"draft": payload}
        except ServiceCatalogGovernanceError as exc:
            raise _governance_http(exc) from exc
        except PortalPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/catalog/reject")
    async def reject_catalog(
        request: CatalogTransitionRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ) -> dict[str, Any]:
        try:
            draft = load_catalog_draft(
                settings.data_dir,
                tenant_id=_tenant(actor, request.tenantId),
                store=store,
            )
            submitter = str((draft or {}).get("updatedBy") or "").strip()
            ensure_can_review(
                actor,
                submitter,
                relaxed_workflow=settings.effective_relaxed_workflow(),
            )
            payload = transition_catalog_draft(
                settings.data_dir,
                tenant_id=_tenant(actor, request.tenantId),
                target_status="REJECTED",
                actor_id=actor.user_id,
                reason=request.reason,
                store=store,
            )
            return {"draft": payload}
        except ServiceCatalogGovernanceError as exc:
            raise _governance_http(exc) from exc
        except PortalPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise handle_errors(exc) from exc
