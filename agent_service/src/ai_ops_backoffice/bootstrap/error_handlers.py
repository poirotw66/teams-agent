"""FastAPI exception handlers for AI Ops Backoffice."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agent_service.operations.audit_errors import AuditWriteError
from ai_ops_backoffice.evaluation_domain import (
    EvaluationAuditWriteError,
    EvaluationAuthorizationError,
    EvaluationDomainError,
    EvaluationIdempotencyConflictError,
    EvaluationNotFoundError,
    EvaluationTransitionError,
    EvaluationValidationError,
    EvaluationVersionConflictError,
    GateBlockedError,
)
from ai_ops_backoffice.faq_domain import (
    FaqAuthorizationError,
    FaqDomainError,
    FaqIdempotencyConflictError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)
from ai_ops_backoffice.knowledge_bridge.errors import KnowledgeBridgeError
from ai_ops_backoffice.services.periods import PeriodPolicyError
from ai_ops_backoffice.services.rate_limit import RateLimitExceeded


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(PeriodPolicyError)
    async def period_policy_handler(_request, exc: PeriodPolicyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(_request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.exception_handler(AuditWriteError)
    async def audit_write_handler(_request, exc: AuditWriteError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(FaqAuthorizationError)
    async def faq_authorization_handler(_request, exc: FaqAuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(FaqNotFoundError)
    async def faq_not_found_handler(_request, exc: FaqNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(FaqVersionConflictError)
    @app.exception_handler(FaqIdempotencyConflictError)
    @app.exception_handler(FaqTransitionError)
    async def faq_conflict_handler(_request, exc: FaqDomainError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(FaqValidationError)
    async def faq_validation_handler(_request, exc: FaqValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(KnowledgeBridgeError)
    async def knowledge_bridge_error_handler(
        _request, exc: KnowledgeBridgeError
    ) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.as_response())

    @app.exception_handler(EvaluationAuthorizationError)
    async def evaluation_authorization_handler(
        _request, exc: EvaluationAuthorizationError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(EvaluationNotFoundError)
    async def evaluation_not_found_handler(
        _request, exc: EvaluationNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(EvaluationVersionConflictError)
    @app.exception_handler(EvaluationIdempotencyConflictError)
    @app.exception_handler(EvaluationTransitionError)
    async def evaluation_conflict_handler(
        _request, exc: EvaluationDomainError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(EvaluationValidationError)
    async def evaluation_validation_handler(
        _request, exc: EvaluationValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(EvaluationAuditWriteError)
    async def evaluation_audit_write_handler(
        _request, exc: EvaluationAuditWriteError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(GateBlockedError)
    async def gate_blocked_handler(_request, exc: GateBlockedError) -> JSONResponse:
        return JSONResponse(status_code=412, content={"detail": str(exc)})
