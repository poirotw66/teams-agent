"""Map portal domain exceptions to HTTPException responses."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from knowledge_portal.models import PortalErrorCode, ValidationSummary
from knowledge_portal.pdf_converter_client import PdfConverterError
from knowledge_portal.pdf_text import ScannedPdfError
from knowledge_portal.rbac import PortalPermissionError
from knowledge_portal.repository import PortalNotFoundError, VersionConflictError
from knowledge_portal.services.context import IdempotencyConflictError

logger = logging.getLogger("knowledge_portal.api")


def portal_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, PortalNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": PortalErrorCode.NOT_FOUND.value, "message": str(exc)},
        )
    if isinstance(exc, (PortalPermissionError, PermissionError)):
        code = (
            "RELEASE_GATE_BLOCKED"
            if "gate" in str(exc).lower()
            else PortalErrorCode.FORBIDDEN.value
        )
        return HTTPException(
            status_code=403,
            detail={"code": code, "message": str(exc)},
        )
    if isinstance(exc, (VersionConflictError, IdempotencyConflictError)):
        return HTTPException(
            status_code=409,
            detail={"code": PortalErrorCode.CONFLICT.value, "message": str(exc)},
        )
    if isinstance(exc, ValidationSummary):
        return HTTPException(
            status_code=422,
            detail={
                "code": PortalErrorCode.VALIDATION_FAILED.value,
                "message": "內容檢查未通過，請修正標示的問題後再試。",
                "issues": [issue.model_dump(mode="json") for issue in exc.issues],
            },
        )
    if isinstance(exc, ScannedPdfError):
        return HTTPException(
            status_code=422,
            detail={
                "code": PortalErrorCode.VALIDATION_FAILED.value,
                "message": str(exc),
            },
        )
    if isinstance(exc, PdfConverterError):
        return HTTPException(
            status_code=502,
            detail={
                "code": PortalErrorCode.INVALID_STATE.value,
                "message": str(exc),
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
                    "message": "內容檢查未通過，請修正標示的問題後再試。",
                    "issues": [issue.model_dump(mode="json") for issue in summary.issues],
                },
            )
        return HTTPException(
            status_code=400,
            detail={"code": PortalErrorCode.INVALID_STATE.value, "message": message},
        )
    logger.exception("Unhandled portal error")
    return HTTPException(status_code=500, detail="Internal portal error.")
