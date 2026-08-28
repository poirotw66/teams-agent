import pytest

from agent_service.contracts import AgentRequest, ConversationIdentity, MessageContent, UserIdentity
from agent_service.knowledge import KnowledgeResult
from agent_service.knowledge_backends import KnowledgeBackendRouter


class FakeKnowledgeService:
    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.last_request = None

    async def search(
        self,
        query,
        user_context,
        *,
        correlation_id=None,
        call_counter=None,
        request=None,
    ):
        self.last_request = request
        return KnowledgeResult(found=True, answer=query, backend=self.backend)


@pytest.mark.asyncio
async def test_evaluation_backend_is_scoped_to_allowed_channels() -> None:
    router = KnowledgeBackendRouter(
        {
            "HYBRID": FakeKnowledgeService("HYBRID"),
            "GEMINI_FILE_SEARCH": FakeKnowledgeService("GEMINI_FILE_SEARCH"),
        },
        "HYBRID",
    )
    request = AgentRequest(
        requestId="req-1",
        channel="playground",
        conversation=ConversationIdentity(tenantId="tenant-1"),
        user=UserIdentity(teamsUserId="user-1"),
        message=MessageContent(text="VPN issue"),
        evaluationKnowledgeBackend="GEMINI_FILE_SEARCH",
    )

    backend = await router.resolve_backend(request)
    assert backend == "GEMINI_FILE_SEARCH"

    teams_request = request.model_copy(
        update={"channel": "msteams-prod", "evaluationKnowledgeBackend": None}
    )
    backend = await router.resolve_backend(teams_request)
    assert backend == "HYBRID"
