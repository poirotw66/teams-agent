from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from microsoft_teams.api import MessageActivity


def _info_id(info: object) -> str | None:
    """Read `.id` off a Teams SDK channel-data info model (team/channel/tenant).

    The Microsoft Teams SDK parses `channelData` into typed pydantic models
    (`TeamInfo`, `ChannelInfo`, `TenantInfo`), but every field on them is
    optional and Teams omits whole sections depending on the scope -- a 1:1
    personal chat carries no team or channel at all. Reading defensively keeps
    `from_activity` total over every conversation scope.
    """
    identifier = getattr(info, "id", None)
    return identifier if isinstance(identifier, str) and identifier else None


def account_field(account: object, snake_case: str, camel_case: str) -> str | None:
    """Read a Teams `Account` field that may not be modelled by this SDK version.

    `microsoft-teams-api` 2.0.x does not declare `tenantId` or `email` on
    `Account`, but its models are configured with `extra="allow"`, so Teams
    still delivers them -- under their raw camelCase key. Later SDK versions
    promote them to real snake_case fields. Checking both keeps the adapter
    working across either without pinning to one.
    """
    for name in (snake_case, camel_case):
        value = getattr(account, name, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def activity_tenant_id(activity: MessageActivity) -> str | None:
    """Resolve tenant id from channelData.tenant, then from.sender tenant claims."""
    channel_data = activity.channel_data
    tenant_id = _info_id(getattr(channel_data, "tenant", None))
    if tenant_id:
        return tenant_id
    sender = activity.from_
    if not sender:
        return None
    return account_field(sender, "tenant_id", "tenantId")


@dataclass(frozen=True)
class ConversationIdentity:
    tenantId: str | None = None
    teamId: str | None = None
    channelId: str | None = None
    conversationId: str | None = None


@dataclass(frozen=True)
class UserIdentity:
    teamsUserId: str | None = None
    entraObjectId: str | None = None
    displayName: str | None = None
    email: str | None = None
    groups: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MessageContent:
    text: str
    locale: str | None = None


@dataclass(frozen=True)
class AgentRequest:
    requestId: str
    channel: str
    conversation: ConversationIdentity
    user: UserIdentity
    message: MessageContent
    # Spec §15.1: one Correlation ID per Teams activity, threaded through every
    # downstream node without being regenerated. The adapter deliberately uses
    # the same value for `requestId` (the adapter's own request identifier,
    # used historically as the user-facing tracking id) and `correlationId`
    # (the wire field the Agent Service and its downstream nodes propagate) —
    # see docstring in `teams_agent.agent` for the full rationale.
    correlationId: str | None = None
    evaluationKnowledgeBackend: str | None = None

    @classmethod
    def from_activity(
        cls,
        activity: MessageActivity,
        text: str,
        correlation_id: str | None = None,
        email: str | None = None,
        groups: list[str] | None = None,
    ) -> "AgentRequest":
        channel_data = activity.channel_data
        sender = activity.from_
        conversation = activity.conversation
        tenant_id = activity_tenant_id(activity)

        # Generate a correlation id only if the caller didn't already mint one
        # for this activity. Callers (teams_agent.agent) should always pass
        # one explicitly so the id is stable across the whole turn, including
        # retries; the fallback here exists only to keep this a self-contained
        # constructor for direct/test usage.
        resolved_correlation_id = correlation_id or str(uuid4())
        evaluation_backend = getattr(channel_data, "evaluationKnowledgeBackend", None)
        if evaluation_backend not in {"HYBRID", "GEMINI_FILE_SEARCH"}:
            evaluation_backend = None

        conversation_id = conversation.id if conversation else None
        playground_session = getattr(channel_data, "playgroundSessionId", None)
        if (
            isinstance(playground_session, str)
            and playground_session.strip()
            and (activity.channel_id or "").casefold() == "playground"
            and conversation_id
        ):
            # Playground "新對話" keeps the same personal-chat id; rotate the
            # logical conversation key so handoff + history do not stick.
            conversation_id = f"{conversation_id}::{playground_session.strip()}"

        return cls(
            requestId=resolved_correlation_id,
            correlationId=resolved_correlation_id,
            channel=activity.channel_id or "unknown",
            conversation=ConversationIdentity(
                tenantId=tenant_id,
                teamId=_info_id(getattr(channel_data, "team", None)),
                channelId=_info_id(getattr(channel_data, "channel", None)),
                conversationId=conversation_id,
            ),
            user=UserIdentity(
                teamsUserId=sender.id if sender else None,
                entraObjectId=sender.aad_object_id if sender else None,
                displayName=sender.name if sender else None,
                email=email,
                groups=list(groups) if groups else [],
            ),
            message=MessageContent(text=text, locale=activity.locale),
            evaluationKnowledgeBackend=evaluation_backend,
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeedbackRequest:
    """Spec §14: thumbs up/down feedback tied to one issue in one response."""

    correlationId: str
    conversationId: str
    issueId: int
    rating: str  # "UP" | "DOWN"
    userId: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Citation:
    title: str
    url: str | None = None
    chunkId: str | None = None
    sourcePath: str | None = None
    sourceRefId: str | None = None
    releaseId: str | None = None
    originalUrl: str | None = None


@dataclass(frozen=True)
class AgentImage:
    path: str
    title: str
    altText: str
    sourceChunkId: str
    releaseId: str | None = None


# Result types where the Agent Service considers the issue "answered" and
# feedback is meaningful (spec §4.3, §14). Kept adapter-local and minimal:
# the adapter only needs this to decide which issues get a feedback prompt,
# not to reproduce the full Issue/IssueResult domain model owned by the
# Agent Service.
_FEEDBACK_ELIGIBLE_RESULT_TYPES = {"FAQ_ANSWERED", "KNOWLEDGE_ANSWERED"}


@dataclass(frozen=True)
class IssueResult:
    issueId: int
    resultType: str
    answer: str = ""

    @property
    def feedback_eligible(self) -> bool:
        return self.resultType in _FEEDBACK_ELIGIBLE_RESULT_TYPES


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    traceId: str
    citations: list[Citation] = field(default_factory=list)
    images: list[AgentImage] = field(default_factory=list)
    correlationId: str | None = None
    issueResults: list[IssueResult] = field(default_factory=list)
    feedbackEnabled: bool = False
    estimatedCostUsd: float | None = None
    estimatedCostTwd: float | None = None
    costComplete: bool | None = None

    @classmethod
    def from_payload(
        cls,
        payload: object,
        fallback_trace_id: str,
    ) -> "AgentResponse":
        from .contracts_parse import (
            parse_citations,
            parse_images,
            parse_issue_results,
            parse_optional_cost,
        )

        if not isinstance(payload, dict):
            raise TypeError("Agent API response must be a JSON object.")

        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Agent API response must contain a non-empty answer.")

        trace_id = payload.get("traceId")
        if not isinstance(trace_id, str) or not trace_id:
            trace_id = fallback_trace_id

        citations = parse_citations(payload.get("citations", []))
        images = parse_images(payload.get("images", []))

        # correlationId (spec §15.1): degrade to the same fallback used for
        # traceId rather than raising, so a malformed/missing field never
        # breaks the turn. By convention (see AgentRequest.from_activity) the
        # adapter's requestId and correlationId are minted as the same value,
        # so this fallback still yields the correct id when the Agent Service
        # simply echoes nothing back.
        correlation_id = payload.get("correlationId")
        if not isinstance(correlation_id, str) or not correlation_id:
            correlation_id = fallback_trace_id

        feedback_enabled = payload.get("feedbackEnabled")
        if not isinstance(feedback_enabled, bool):
            feedback_enabled = False

        estimated_cost_usd = parse_optional_cost(payload, "estimatedCostUsd")
        estimated_cost_twd = parse_optional_cost(payload, "estimatedCostTwd")

        cost_complete = payload.get("costComplete")
        if cost_complete is not None and not isinstance(cost_complete, bool):
            cost_complete = None

        return cls(
            answer=answer.strip(),
            traceId=trace_id,
            citations=citations,
            images=images,
            correlationId=correlation_id,
            issueResults=parse_issue_results(payload.get("issueResults", [])),
            feedbackEnabled=feedback_enabled,
            estimatedCostUsd=estimated_cost_usd,
            estimatedCostTwd=estimated_cost_twd,
            costComplete=cost_complete,
        )


from .formatting import (
    format_agent_response,
    format_teams_answer,
    format_turn_cost_line,
)

__all__ = [
    "AgentRequest",
    "AgentResponse",
    "Citation",
    "ConversationIdentity",
    "FeedbackRequest",
    "IssueResult",
    "MessageActivity",
    "UserIdentity",
    "account_field",
    "activity_tenant_id",
    "format_agent_response",
    "format_teams_answer",
    "format_turn_cost_line",
]

