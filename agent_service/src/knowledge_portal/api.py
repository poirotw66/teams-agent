from __future__ import annotations

import hmac
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import PortalAuthError, draft_search_response, resolve_portal_actor
from .draft_assets import slug_from_title
from .models import (
    CreateDocumentRequest,
    CreateTestCaseRequest,
    BootstrapReleaseRequest,
    DraftSearchRequest,
    PortalActor,
    PortalErrorCode,
    PublishRequest,
    RemoveDocumentRequest,
    ReviewDecisionRequest,
    RollbackRequest,
    SubmitReviewRequest,
    UpdateDraftRequest,
    ValidationSummary,
)
from .rbac import PortalPermissionError
from .repository import PortalNotFoundError, VersionConflictError, build_repository
from .service import PortalService
from .settings import PortalSettings

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: PortalSettings | None = None) -> FastAPI:
    resolved_settings = settings or PortalSettings.from_env()
    repository = build_repository(resolved_settings)
    service = PortalService(resolved_settings, repository)

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = resolved_settings.service_token
        if not expected:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service token.")

    def current_actor(
        authorization: str | None = Header(default=None),
        x_portal_user_id: str | None = Header(default=None, alias="X-Portal-User-Id"),
        x_portal_user_name: str | None = Header(default=None, alias="X-Portal-User-Name"),
        x_portal_role: str | None = Header(default="CONTRIBUTOR", alias="X-Portal-Role"),
        x_portal_owner_units: str | None = Header(default="", alias="X-Portal-Owner-Units"),
    ) -> PortalActor:
        try:
            return resolve_portal_actor(
                settings=resolved_settings,
                authorization=authorization,
                header_user_id=x_portal_user_id,
                header_user_name=x_portal_user_name,
                header_role=x_portal_role,
                header_owner_units=x_portal_owner_units,
            )
        except PortalAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def correlation_id(request: Request) -> str:
        return request.headers.get("X-Correlation-Id") or uuid.uuid4().hex

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.release_artifact_dir.mkdir(parents=True, exist_ok=True)
        resolved_settings.drafts_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(
        title="Knowledge Operations Portal API",
        version="0.1.0",
        lifespan=lifespan,
    )

    def handle_errors(exc: Exception) -> HTTPException:
        if isinstance(exc, PortalNotFoundError):
            return HTTPException(
                status_code=404,
                detail={"code": PortalErrorCode.NOT_FOUND.value, "message": str(exc)},
            )
        if isinstance(exc, PortalPermissionError):
            return HTTPException(
                status_code=403,
                detail={"code": PortalErrorCode.FORBIDDEN.value, "message": str(exc)},
            )
        if isinstance(exc, VersionConflictError):
            return HTTPException(
                status_code=409,
                detail={"code": PortalErrorCode.CONFLICT.value, "message": str(exc)},
            )
        if isinstance(exc, ValidationSummary):
            return HTTPException(
                status_code=422,
                detail={
                    "code": PortalErrorCode.VALIDATION_FAILED.value,
                    "message": "Validation failed.",
                    "issues": [issue.model_dump(mode="json") for issue in exc.issues],
                },
            )
        if isinstance(exc, ValueError):
            message = str(exc)
            if hasattr(exc, "args") and exc.args and isinstance(exc.args[0], ValidationSummary):
                summary = exc.args[0]
                return HTTPException(
                    status_code=422,
                    detail={
                        "code": PortalErrorCode.VALIDATION_FAILED.value,
                        "message": "Validation failed.",
                        "issues": [issue.model_dump(mode="json") for issue in summary.issues],
                    },
                )
            return HTTPException(
                status_code=400,
                detail={"code": PortalErrorCode.INVALID_STATE.value, "message": message},
            )
        logger.exception("Unhandled portal error")
        return HTTPException(status_code=500, detail="Internal portal error.")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def portal_home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/dashboard")
    async def dashboard(
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.dashboard(actor)

    @app.get("/api/documents")
    async def list_documents(
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.list_documents(
            actor,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )

    @app.post("/api/documents/import-markdown")
    async def import_markdown(
        file: UploadFile = File(...),
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        raw = (await file.read()).decode("utf-8")
        return service.import_markdown(raw)

    @app.post("/api/documents/{document_id}/start-revision")
    async def start_revision(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.start_revision(
                actor, document_id, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}/draft/assets")
    async def list_draft_assets(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.list_draft_assets(actor, document_id)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/draft/assets")
    async def upload_draft_assets(
        document_id: str,
        files: list[UploadFile] = File(...),
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        uploads: list[tuple[str, bytes]] = []
        for upload in files:
            uploads.append((upload.filename or "image.png", await upload.read()))
        try:
            return await service.upload_draft_assets(
                actor,
                document_id,
                uploads,
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.delete("/api/documents/{document_id}/draft/assets/{filename}")
    async def delete_draft_asset(
        document_id: str,
        filename: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.delete_draft_asset(
                actor,
                document_id,
                filename,
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}/draft/assets/{filename}")
    async def get_draft_asset(
        document_id: str,
        filename: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        detail = await service.get_document(actor, document_id)
        if detail.draft_version is None:
            raise HTTPException(status_code=404, detail="Draft version not found.")
        slug = detail.draft_version.asset_slug or slug_from_title(
            detail.draft_version.title
        )
        try:
            path, media_type = service.read_draft_asset(
                document_id,
                detail.draft_version.version_id,
                slug,
                filename,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc
        return FileResponse(path, media_type=media_type)

    @app.post("/api/documents/{document_id}/draft/asset-ref")
    async def suggest_asset_ref(
        document_id: str,
        filename: str = "",
        alt_text: str = "",
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.suggest_asset_ref(
                actor, document_id, filename, alt_text
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents")
    async def create_document(
        request: CreateDocumentRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.create_document(actor, request, correlation_id_value)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}")
    async def get_document(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.get_document(actor, document_id)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/reviews/pending")
    async def list_pending_reviews(
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.list_pending_reviews(actor)

    @app.post("/api/documents/{document_id}/discard-draft")
    async def discard_draft(
        document_id: str,
        request: RemoveDocumentRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.discard_draft(
                actor,
                document_id,
                request,
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/unpublish")
    async def unpublish_document(
        document_id: str,
        request: RemoveDocumentRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.unpublish_document(
                actor,
                document_id,
                request,
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.delete("/api/documents/{document_id}")
    async def remove_document(
        document_id: str,
        reason: str = "Removed from the knowledge library.",
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.remove_document(
                actor,
                document_id,
                RemoveDocumentRequest(reason=reason),
                correlation_id_value,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.put("/api/documents/{document_id}/draft")
    async def update_draft(
        document_id: str,
        request: UpdateDraftRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.update_draft(
                actor, document_id, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/validate")
    async def validate_document(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            return await service.validate_document(actor, document_id)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/submit-review")
    async def submit_review(
        document_id: str,
        request: SubmitReviewRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.submit_for_review(
                actor, document_id, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/reviews/{review_id}/decision")
    async def review_decision(
        review_id: str,
        request: ReviewDecisionRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.decide_review(
                actor, review_id, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/publish")
    async def publish_document(
        document_id: str,
        request: PublishRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.publish_version(
                actor, document_id, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/releases/rollback")
    async def rollback_release(
        request: RollbackRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.rollback_release(
                actor, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/releases")
    async def list_releases(
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.list_releases(actor)

    @app.get("/api/audit-events")
    async def list_audit(
        limit: int = 100,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.list_audit(actor, limit=limit)

    @app.get("/api/documents/{document_id}/test-cases")
    async def list_test_cases(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.list_test_cases(actor, document_id)

    @app.post("/api/documents/{document_id}/test-cases")
    async def create_test_case(
        document_id: str,
        request: CreateTestCaseRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.add_test_case(
                actor, document_id, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.get("/api/documents/{document_id}/test-runs")
    async def list_test_runs(
        document_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        return await service.list_test_runs(actor, document_id)

    @app.post("/api/documents/{document_id}/draft-search")
    async def draft_search(
        document_id: str,
        request: DraftSearchRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            result = await service.search_draft(
                actor,
                document_id,
                request.query,
                request.groups,
                request.limit,
            )
            return draft_search_response(result)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/admin/bootstrap-release-0001")
    async def bootstrap_release_0001(
        request: BootstrapReleaseRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        sources_dir = Path(request.sources_dir) if request.sources_dir else (
            resolved_settings.data_dir / "sources"
        )
        if not sources_dir.exists():
            sources_dir = resolved_settings.data_dir / "sources.sample"
        try:
            return await service.bootstrap_release_0001(
                actor,
                sources_dir,
                correlation_id_value,
                release_id=request.release_id,
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/test-cases/{test_case_id}/run")
    async def run_test_case(
        document_id: str,
        test_case_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.run_test_case(
                actor, document_id, test_case_id, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
