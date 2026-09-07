"""Feedback ingestion route."""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from ..contracts import FeedbackRequest
from ..operations.emitter import OperationalEventReplayConflict
from ..operations.masking import mask_text, pseudonymous_actor_id

logger = logging.getLogger(__name__)


def register_feedback_routes(
    app: FastAPI,
    *,
    authorize: Callable[..., None],
) -> None:
    @app.post(
        "/feedback",
        dependencies=[Depends(authorize)],
    )
    async def feedback(payload: FeedbackRequest, request: Request) -> dict[str, str]:
        masked_reason = mask_text(payload.reason).text if payload.reason else None
        pseudo_user = pseudonymous_actor_id(payload.userId) if payload.userId else None
        logger.info(
            "Feedback recorded: correlation_id=%s conversation_id=%s issue_id=%s "
            "rating=%s user_id=%s reason=%s resolved=%s",
            payload.correlationId,
            payload.conversationId,
            payload.issueId,
            payload.rating,
            pseudo_user,
            masked_reason,
            payload.resolvedStatus,
        )
        ops_runtime = getattr(request.app.state, "ops_runtime", None)
        if ops_runtime is not None:
            try:
                await ops_runtime.emitter.emit_feedback(payload)
            except (OperationalEventReplayConflict, ValueError) as error:
                raise HTTPException(
                    status_code=409,
                    detail="Feedback provenance could not be verified.",
                ) from error
            except Exception as error:
                raise HTTPException(
                    status_code=503,
                    detail="Feedback persistence is temporarily unavailable.",
                ) from error
        return {"status": "recorded"}
