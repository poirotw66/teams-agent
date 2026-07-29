from microsoft_agents.activity import Activity, Attachment

from .contracts import AgentResponse, format_agent_response
from .media import build_asset_url
from .settings import AgentSettings

ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"


def build_agent_activity(
    response: AgentResponse,
    settings: AgentSettings,
    now: int | None = None,
) -> Activity | str:
    if not response.images or not settings.images_ready:
        return format_agent_response(response)

    body: list[dict[str, object]] = [
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

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
    }
    return Activity(
        type="message",
        summary=response.answer[:200],
        attachments=[
            Attachment(
                content_type=ADAPTIVE_CARD_CONTENT_TYPE,
                content=card,
            )
        ],
    )
