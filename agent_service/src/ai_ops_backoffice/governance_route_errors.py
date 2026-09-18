"""Governance domain exception handlers for FastAPI."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .governance_domain import (
    GovernanceAuthorizationError,
    GovernanceConflictError,
    GovernanceError,
    GovernanceNotFoundError,
    GovernanceTransitionError,
    GovernanceValidationError,
)

__all__ = ["register_governance_exception_handlers"]


def register_governance_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(GovernanceAuthorizationError)
    async def governance_authorization_handler(
        _request, exc: GovernanceAuthorizationError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(GovernanceNotFoundError)
    async def governance_not_found_handler(_request, exc: GovernanceNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(GovernanceConflictError)
    @app.exception_handler(GovernanceTransitionError)
    async def governance_conflict_handler(_request, exc: GovernanceError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(GovernanceValidationError)
    async def governance_validation_handler(
        _request, exc: GovernanceValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
