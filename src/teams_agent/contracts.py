import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
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

        tenant_id = _info_id(getattr(channel_data, "tenant", None))
        if not tenant_id and sender:
            tenant_id = account_field(sender, "tenant_id", "tenantId")

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


@dataclass(frozen=True)
class AgentImage:
    path: str
    title: str
    altText: str
    sourceChunkId: str


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
                source_path = item.get("sourcePath")
                source_ref_id = item.get("sourceRefId")
                release_id = item.get("releaseId")
                if isinstance(title, str) and (
                    isinstance(url, str) or url is None
                ):
                    citations.append(
                        Citation(
                            title=title,
                            url=url if isinstance(url, str) and url.strip() else None,
                            chunkId=chunk_id if isinstance(chunk_id, str) else None,
                            sourcePath=(
                                source_path
                                if isinstance(source_path, str) and source_path.strip()
                                else None
                            ),
                            sourceRefId=(
                                source_ref_id
                                if isinstance(source_ref_id, str) and source_ref_id.strip()
                                else None
                            ),
                            releaseId=(
                                release_id
                                if isinstance(release_id, str) and release_id.strip()
                                else None
                            ),
                        )
                    )

        images: list[AgentImage] = []
        raw_images = payload.get("images", [])
        if isinstance(raw_images, list):
            for item in raw_images:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                title = item.get("title")
                alt_text = item.get("altText")
                source_chunk_id = item.get("sourceChunkId")
                if not all(
                    isinstance(value, str) and value.strip()
                    for value in (path, title, alt_text, source_chunk_id)
                ):
                    continue
                pure_path = PurePosixPath(path)
                if pure_path.is_absolute() or ".." in pure_path.parts:
                    continue
                images.append(
                    AgentImage(
                        path=pure_path.as_posix(),
                        title=title.strip(),
                        altText=alt_text.strip(),
                        sourceChunkId=source_chunk_id.strip(),
                    )
                )

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

        estimated_cost_usd = payload.get("estimatedCostUsd")
        if estimated_cost_usd is not None and not isinstance(estimated_cost_usd, (int, float)):
            estimated_cost_usd = None
        elif isinstance(estimated_cost_usd, (int, float)):
            estimated_cost_usd = float(estimated_cost_usd)

        estimated_cost_twd = payload.get("estimatedCostTwd")
        if estimated_cost_twd is not None and not isinstance(estimated_cost_twd, (int, float)):
            estimated_cost_twd = None
        elif isinstance(estimated_cost_twd, (int, float)):
            estimated_cost_twd = float(estimated_cost_twd)

        cost_complete = payload.get("costComplete")
        if cost_complete is not None and not isinstance(cost_complete, bool):
            cost_complete = None

        issue_results: list[IssueResult] = []
        raw_issue_results = payload.get("issueResults", [])
        if isinstance(raw_issue_results, list):
            for item in raw_issue_results:
                if not isinstance(item, dict):
                    continue
                issue_id = item.get("issueId")
                result_type = item.get("resultType")
                if not isinstance(issue_id, int) or isinstance(issue_id, bool):
                    continue
                if not isinstance(result_type, str) or not result_type:
                    continue
                answer_text = item.get("answer", "")
                issue_results.append(
                    IssueResult(
                        issueId=issue_id,
                        resultType=result_type,
                        answer=answer_text if isinstance(answer_text, str) else "",
                    )
                )

        return cls(
            answer=answer.strip(),
            traceId=trace_id,
            citations=citations,
            images=images,
            correlationId=correlation_id,
            issueResults=issue_results,
            feedbackEnabled=feedback_enabled,
            estimatedCostUsd=estimated_cost_usd,
            estimatedCostTwd=estimated_cost_twd,
            costComplete=cost_complete,
        )


def format_turn_cost_line(response: AgentResponse) -> str | None:
    """Return a subtle cost footer when the Agent Service included cost metadata."""
    if response.costComplete is None:
        return None
    if response.estimatedCostUsd is not None and response.estimatedCostTwd is not None:
        return (
            f"_預估成本：${response.estimatedCostUsd:.8f} USD / "
            f"${response.estimatedCostTwd:.3f} TWD_"
        )
    return "_預估成本：無法估算（費率或用量資料不完整）_"


def _format_steps_and_citations(text: str) -> str:
    """Format sequential steps with ordered numbers and clean repetitive citations.

    When multiple consecutive list items or steps share the exact same citation marker
    (e.g. four consecutive lines all ending with `[S1]`), strips the citation from the
    intermediate items, keeping it only on the final step (or omitting if the lead-in
    already included it). Also automatically converts unnumbered sequential steps under
    a '流程如下' or '步驟如下' header into an ordered list.
    """
    lines = text.split("\n")
    new_lines: list[str] = []
    in_step_group = False
    step_num = 1
    lead_in_cite: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue

        if re.search(r"(?:流程|步驟)(?:如下)?.*[:：]\s*$", stripped):
            in_step_group = True
            step_num = 1
            cite_m = re.search(r"\[S\d+\]", stripped)
            lead_in_cite = cite_m.group(0) if cite_m else None
            new_lines.append(line)
            continue

        is_already_numbered = bool(re.match(r"^\d+\.\s+", stripped))
        is_bullet = bool(re.match(r"^[-*]\s+", stripped))
        is_note = stripped.startswith((">", "註：", "備註："))

        if is_note or stripped.startswith(("**", "#")):
            in_step_group = False
            lead_in_cite = None
            new_lines.append(line)
            continue

        if is_already_numbered or is_bullet:
            new_lines.append(line)
            continue

        if in_step_group:
            if len(stripped) < 60 and not stripped.startswith("一般權限") and not stripped.startswith("若您"):
                new_lines.append(f"{step_num}. {stripped}")
                step_num += 1
                continue
            else:
                in_step_group = False
                lead_in_cite = None
                new_lines.append("")

        new_lines.append(line)

    result_lines: list[str] = []
    n = len(new_lines)
    for idx, line in enumerate(new_lines):
        m = re.match(r"^(\s*(?:\d+\.|[-*])\s+.*?)(\s*\[S\d+\][。.]?)\s*$", line)
        if m:
            content, cite = m.groups()
            cite_marker_m = re.search(r"\[S\d+\]", cite)
            if cite_marker_m:
                cite_marker = cite_marker_m.group(0)
                has_next_same = False
                if idx + 1 < n:
                    next_line = new_lines[idx + 1].strip()
                    if re.match(r"^(?:\d+\.|[-*])\s+", next_line) and cite_marker in next_line:
                        has_next_same = True
                if has_next_same or (lead_in_cite and lead_in_cite == cite_marker):
                    result_lines.append(content)
                    continue
        result_lines.append(line)

    return "\n".join(result_lines)


def format_teams_answer(answer: str) -> str:
    """Format raw agent answer for optimal Microsoft Teams Markdown rendering.

    Fixes common Teams rendering issues:
    - Bolds '問題：' and '處理方式：' and ensures double newline separation so
      Teams Adaptive Card Markdown does not collapse headings into the text.
    - Formats special notes or remarks as blockquote callouts (`> 💡 **注意事項**：...`).
    - Ensures sequential steps are numbered cleanly without citation repetition spam.
    """
    if not answer or not answer.strip():
        return answer

    text = answer.strip()

    # 1. Bold "問題：" header
    text = re.sub(r"(?m)^(?<!\*\*)問題：\s*([^\n]+)", r"**問題：** \1", text)

    # 2. Bold "處理方式：" and ensure double newline separation
    text = re.sub(
        r"(?:\n\s*|\A)(?:\*\*)?處理方式：(?:\*\*)?\s*\n*",
        r"\n\n**處理方式：**\n\n",
        text,
    )

    # 3. Bold "來源：\n" if present (e.g. FAQ answers from response_builder)
    text = re.sub(
        r"(?:\n\s*|\A)(?:\*\*)?來源：(?:\*\*)?\s*\n*",
        r"\n\n**來源：**\n\n",
        text,
    )

    # 4. Format notes/remarks (e.g. 註：... or 備註：...) as blockquote callout
    text = re.sub(
        r"(?m)^(?:\*\*)?(?:註|備註)：(?:\*\*)?\s*(.+)$",
        r"> 💡 **注意事項**：\1",
        text,
    )

    # 5. Format step lists and clean citation repetition
    text = _format_steps_and_citations(text)

    # Clean up any excessive newlines (more than 2 consecutive newlines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_agent_response(response: AgentResponse) -> str:
    formatted_answer = format_teams_answer(response.answer)
    parts = [formatted_answer]
    if response.citations:
        has_citations_in_answer = bool(re.search(r"\[S\d+\]", formatted_answer))
        sources = "\n".join(
            (
                f"- [S{index}] [{citation.title}]({citation.url})"
                if citation.url
                else f"- [S{index}] {citation.title}"
            )
            if has_citations_in_answer
            else (
                f"- [{citation.title}]({citation.url})"
                if citation.url
                else f"- {citation.title}"
            )
            for index, citation in enumerate(response.citations, start=1)
        )
        parts.append(f"**來源**\n\n{sources}")
    cost_line = format_turn_cost_line(response)
    if cost_line:
        parts.append(cost_line)
    return "\n\n".join(parts)
