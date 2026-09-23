from microsoft_teams.api import Attachment, MessageActivityInput

from .cards_body import build_image_card_body
from .contracts import (
    AgentResponse,
    format_agent_response,
    format_turn_cost_line,
)
from .formatting import extract_answer_urls, open_url_action_title
from .settings import AgentSettings
from .source_links import CitationViewerContext, enrich_citation_urls

ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"

# Spec §14: feedback prompt and thumbs up/down copy.
FEEDBACK_PROMPT = "這個回答有解決你的問題嗎？"
FEEDBACK_UP_TITLE = "👍 已解決"
FEEDBACK_DOWN_TITLE = "👎 未解決"

# Marker key set on every feedback Action.Submit's data payload so
# teams_agent.agent can distinguish a feedback submission from a normal
# text message inside the same "message" activity handler.
FEEDBACK_ACTION_MARKER = "teamsAgentFeedback"

# Fallback issueId used when the Agent Service response doesn't break the
# answer down into individual issueResults (e.g. a very early / simplified
# response) but still asked for feedback. Most POC responses are
# single-issue, so `1` is a reasonable default; this is a deliberate
# degrade-gracefully choice, not a guess at real issue data.
_DEFAULT_FEEDBACK_ISSUE_ID = 1


def _cost_body_block(response: AgentResponse) -> dict[str, object] | None:
    cost_line = format_turn_cost_line(response)
    if not cost_line:
        return None
    return {
        "type": "TextBlock",
        "text": cost_line,
        "wrap": True,
        "spacing": "Medium",
        "isSubtle": True,
    }


def _feedback_issue_ids(response: AgentResponse) -> list[int]:
    if response.issueResults:
        return [
            issue_result.issueId
            for issue_result in response.issueResults
            if issue_result.feedback_eligible
        ]
    return [_DEFAULT_FEEDBACK_ISSUE_ID]


def _feedback_body_blocks(
    response: AgentResponse,
    conversation_id: str,
    issue_ids: list[int],
) -> list[dict[str, object]]:
    correlation_id = response.correlationId or response.traceId
    blocks: list[dict[str, object]] = []
    for issue_id in issue_ids:
        blocks.append(
            {
                "type": "TextBlock",
                "text": FEEDBACK_PROMPT,
                "wrap": True,
                "spacing": "Medium",
                "isSubtle": True,
            }
        )
        blocks.append(
            {
                "type": "ActionSet",
                "actions": [
                    _feedback_action(
                        FEEDBACK_UP_TITLE, "UP", correlation_id, conversation_id, issue_id
                    ),
                    _feedback_action(
                        FEEDBACK_DOWN_TITLE,
                        "DOWN",
                        correlation_id,
                        conversation_id,
                        issue_id,
                    ),
                ],
            }
        )
    return blocks


def _feedback_action(
    title: str,
    rating: str,
    correlation_id: str,
    conversation_id: str,
    issue_id: int,
) -> dict[str, object]:
    return {
        "type": "Action.Submit",
        "title": title,
        "data": {
            FEEDBACK_ACTION_MARKER: True,
            "correlationId": correlation_id,
            "conversationId": conversation_id,
            "issueId": issue_id,
            "rating": rating,
        },
    }


def _answer_open_url_actions(response: AgentResponse) -> list[dict[str, object]]:
    """OpenUrl buttons for http(s) links that appear in the answer body.

    Adaptive Card TextBlock markdown links are not reliably clickable in
    Agents Playground. Always surface answer-body URLs as ``Action.OpenUrl``
    so the host can open them.
    """
    return [
        {
            "type": "Action.OpenUrl",
            "title": open_url_action_title(url),
            "url": url,
        }
        for url in extract_answer_urls(response.answer)
    ]


def _source_open_actions(
    response: AgentResponse, *, enabled: bool
) -> list[dict[str, object]]:
    """Clickable source buttons.

    Adaptive Card markdown links are not reliably clickable in Agents
    Playground. ``Action.OpenUrl`` is rendered as a button the host actually
    opens. Prefer original-file actions when present; keep citation-paragraph
    actions as a secondary path.

    Controlled by ``TEAMS_CITATION_OPEN_ACTIONS`` (default off while originals
    delivery is being stabilized for local historical releases).
    """

    if not enabled:
        return []

    actions: list[dict[str, object]] = []
    for citation in response.citations:
        title = citation.title.strip() or "來源"
        if len(title) > 28:
            title = f"{title[:27]}…"
        if citation.originalUrl:
            actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": f"開啟原始檔案：{title}",
                    "url": citation.originalUrl,
                }
            )
        if citation.url:
            label = (
                f"查看引用段落：{title}"
                if citation.originalUrl
                else title or "開啟來源"
            )
            actions.append(
                {"type": "Action.OpenUrl", "title": label, "url": citation.url}
            )
    return actions


def _card_open_url_actions(
    response: AgentResponse, *, citation_open_actions_enabled: bool
) -> list[dict[str, object]]:
    """Answer-body URL actions first, then optional citation source actions."""
    return [
        *_answer_open_url_actions(response),
        *_source_open_actions(response, enabled=citation_open_actions_enabled),
    ]


def _card_activity(
    response: AgentResponse,
    body: list[dict[str, object]],
    *,
    citation_open_actions_enabled: bool,
) -> MessageActivityInput:
    # The card stays a plain dict rather than a `microsoft_teams.cards`
    # model tree: the Adaptive Card JSON here is fully determined by the
    # Agent Service response, and `Attachment.content` is passed through to
    # Teams verbatim. Keeping it as data avoids re-encoding every card
    # element as an SDK model for no behavioral gain.
    card: dict[str, object] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
    }
    open_url_actions = _card_open_url_actions(
        response, citation_open_actions_enabled=citation_open_actions_enabled
    )
    if open_url_actions:
        card["actions"] = open_url_actions
    return MessageActivityInput(
        summary=response.answer[:200],
        attachments=[
            Attachment(
                content_type=ADAPTIVE_CARD_CONTENT_TYPE,
                content=card,
            )
        ],
    )


def _text_only_activity(
    response: AgentResponse,
    *,
    conversation_id: str | None,
    feedback_issue_ids: list[int],
    citation_actions_enabled: bool,
) -> MessageActivityInput | str:
    has_open_url_actions = bool(
        _card_open_url_actions(
            response, citation_open_actions_enabled=citation_actions_enabled
        )
    )
    if not feedback_issue_ids and not has_open_url_actions:
        return format_agent_response(response)
    body: list[dict[str, object]] = [
        {
            "type": "TextBlock",
            "text": format_agent_response(response),
            "wrap": True,
        }
    ]
    if feedback_issue_ids:
        body.extend(
            _feedback_body_blocks(response, conversation_id, feedback_issue_ids)
        )
    return _card_activity(
        response,
        body,
        citation_open_actions_enabled=citation_actions_enabled,
    )


def build_agent_activity(
    response: AgentResponse,
    settings: AgentSettings,
    conversation_id: str | None = None,
    now: int | None = None,
    viewer: CitationViewerContext | None = None,
) -> MessageActivityInput | str:
    response = enrich_citation_urls(response, settings, now=now, viewer=viewer)
    feedback_issue_ids = (
        _feedback_issue_ids(response)
        if response.feedbackEnabled and conversation_id
        else []
    )
    citation_actions_enabled = bool(settings.citation_open_actions_enabled)

    if not response.images or not settings.images_ready:
        return _text_only_activity(
            response,
            conversation_id=conversation_id,
            feedback_issue_ids=feedback_issue_ids,
            citation_actions_enabled=citation_actions_enabled,
        )

    body = build_image_card_body(response, settings, now)
    if feedback_issue_ids:
        body.extend(
            _feedback_body_blocks(response, conversation_id, feedback_issue_ids)
        )
    cost_block = _cost_body_block(response)
    if cost_block is not None:
        body.append(cost_block)
    return _card_activity(
        response,
        body,
        citation_open_actions_enabled=citation_actions_enabled,
    )
