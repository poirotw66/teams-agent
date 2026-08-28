from microsoft_teams.api import Attachment, MessageActivityInput

from .contracts import AgentResponse, format_agent_response
from .media import build_asset_url
from .settings import AgentSettings

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


def _card_activity(
    response: AgentResponse, body: list[dict[str, object]]
) -> MessageActivityInput:
    # The card stays a plain dict rather than a `microsoft_teams.cards`
    # model tree: the Adaptive Card JSON here is fully determined by the
    # Agent Service response, and `Attachment.content` is passed through to
    # Teams verbatim. Keeping it as data avoids re-encoding every card
    # element as an SDK model for no behavioral gain.
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
    }
    return MessageActivityInput(
        summary=response.answer[:200],
        attachments=[
            Attachment(
                content_type=ADAPTIVE_CARD_CONTENT_TYPE,
                content=card,
            )
        ],
    )


def build_agent_activity(
    response: AgentResponse,
    settings: AgentSettings,
    conversation_id: str | None = None,
    now: int | None = None,
) -> MessageActivityInput | str:
    feedback_issue_ids = (
        _feedback_issue_ids(response)
        if response.feedbackEnabled and conversation_id
        else []
    )

    if not response.images or not settings.images_ready:
        if not feedback_issue_ids:
            return format_agent_response(response)
        body: list[dict[str, object]] = [
            {
                "type": "TextBlock",
                "text": format_agent_response(response),
                "wrap": True,
            }
        ]
        body.extend(
            _feedback_body_blocks(response, conversation_id, feedback_issue_ids)
        )
        return _card_activity(response, body)

    body = [
        {
            "type": "TextBlock",
            "text": response.answer,
            "wrap": True,
        }
    ]
    for image in response.images:
        url = build_asset_url(image.path, settings, now)
        if not url:
            continue
        body.extend(
            [
                {
                    "type": "TextBlock",
                    "text": image.title,
                    "weight": "Bolder",
                    "wrap": True,
                    "spacing": "Medium",
                },
                {
                    "type": "Image",
                    "url": url,
                    "altText": image.altText,
                    "size": "Stretch",
                },
            ]
        )

    if response.citations:
        sources = "\n".join(
            f"- [{citation.title}]({citation.url})"
            if citation.url
            else f"- {citation.title}"
            for citation in response.citations
        )
        body.append(
            {
                "type": "TextBlock",
                "text": f"**來源**\n{sources}",
                "wrap": True,
                "spacing": "Medium",
                "isSubtle": True,
            }
        )

    if feedback_issue_ids:
        body.extend(
            _feedback_body_blocks(response, conversation_id, feedback_issue_ids)
        )

    return _card_activity(response, body)
