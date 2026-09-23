"""Tests for eval conversation seeding helpers."""

from __future__ import annotations

import pytest

from agent_service.eval_conversation import (
    create_eval_conversation,
    resolve_follow_up_retrieval_query,
    seed_prior_turn,
)
from agent_service.settings import RagSettings


@pytest.mark.asyncio
async def test_seed_prior_turn_records_user_and_assistant_messages(
    tmp_path,
) -> None:
    settings = RagSettings.from_env()
    handles = await create_eval_conversation(case_id="mt-1", settings=settings)
    await seed_prior_turn(
        handles,
        prior_turn="員工入口網登不進去",
        request_id="rag-eval-mt-1",
    )
    history = await handles.service.get_history(handles.conversation.conversationId)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].text == "員工入口網登不進去"
    assert history[1].role == "assistant"


@pytest.mark.asyncio
async def test_resolve_follow_up_requires_extractor() -> None:
    settings = RagSettings.from_env()
    handles = await create_eval_conversation(case_id="mt-2", settings=settings)
    await seed_prior_turn(
        handles,
        prior_turn="員工入口網登不進去",
        request_id="rag-eval-mt-2",
    )
    with pytest.raises(RuntimeError, match="IssueExtractor"):
        await resolve_follow_up_retrieval_query(
            handles=handles,
            query="那密碼不是 AD？",
            extractor=None,
        )
