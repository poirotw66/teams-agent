from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from microsoft_agents.activity import Activity


def _nested_id(data: object, key: str) -> str | None:
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    if not isinstance(value, dict):
        return None
    identifier = value.get("id")
    return identifier if isinstance(identifier, str) else None


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

    @classmethod
    def from_activity(cls, activity: Activity, text: str) -> "AgentRequest":
        channel_data = activity.channel_data
        sender = activity.from_property
        conversation = activity.conversation

        tenant_id = _nested_id(channel_data, "tenant")
        if not tenant_id and sender:
            tenant_id = sender.tenant_id

        return cls(
            requestId=str(uuid4()),
            channel=activity.channel_id or "unknown",
            conversation=ConversationIdentity(
                tenantId=tenant_id,
                teamId=_nested_id(channel_data, "team"),
                channelId=_nested_id(channel_data, "channel"),
                conversationId=conversation.id if conversation else None,
            ),
            user=UserIdentity(
                teamsUserId=sender.id if sender else None,
                entraObjectId=sender.aad_object_id if sender else None,
                displayName=sender.name if sender else None,
            ),
            message=MessageContent(text=text, locale=activity.locale),
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Citation:
    title: str
    url: str
    chunkId: str | None = None


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    traceId: str
    citations: list[Citation] = field(default_factory=list)

    @classmethod
    def from_payload(
        cls,
        payload: object,
        fallback_trace_id: str,
    ) -> "AgentResponse":
        if not isinstance(payload, dict):
            raise TypeError("Agent API response must be a JSON object.")

        answer = payload.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Agent API response must contain a non-empty answer.")

        trace_id = payload.get("traceId")
        if not isinstance(trace_id, str) or not trace_id:
            trace_id = fallback_trace_id

        citations: list[Citation] = []
        raw_citations = payload.get("citations", [])
        if isinstance(raw_citations, list):
            for item in raw_citations:
                if not isinstance(item, dict):
                    continue
                title = item.get("title")
                url = item.get("url")
                chunk_id = item.get("chunkId")
                if isinstance(title, str) and isinstance(url, str):
                    citations.append(
                        Citation(
                            title=title,
                            url=url,
                            chunkId=chunk_id if isinstance(chunk_id, str) else None,
                        )
                    )

        return cls(answer=answer.strip(), traceId=trace_id, citations=citations)


def format_agent_response(response: AgentResponse) -> str:
    if not response.citations:
        return response.answer

    sources = "\n".join(
        f"- [{citation.title}]({citation.url})" for citation in response.citations
    )
    return f"{response.answer}\n\n**來源**\n{sources}"
