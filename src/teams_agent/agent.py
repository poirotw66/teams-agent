import logging
import re
from os import environ
from uuid import uuid4

from dotenv import load_dotenv
from microsoft_agents.activity import load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import (
    AgentApplication,
    Authorization,
    MemoryStorage,
    TurnContext,
    TurnState,
)

from .agent_gateway import AgentGateway, AgentGatewayError
from .cards import FEEDBACK_ACTION_MARKER, build_agent_activity
from .contracts import AgentRequest, FeedbackRequest
from .directory import GRAPH_DEFAULT_SCOPES, build_user_directory_service
from .settings import AgentSettings
from .text import clean_message_text

logger = logging.getLogger(__name__)

load_dotenv()
agents_sdk_config = load_configuration_from_env(environ)
agent_settings = AgentSettings.from_env()
agent_gateway = AgentGateway(agent_settings)

storage = MemoryStorage()
connection_manager = MsalConnectionManager(**agents_sdk_config)
adapter = CloudAdapter(connection_manager=connection_manager)
authorization = Authorization(storage, connection_manager, **agents_sdk_config)

agent_app = AgentApplication[TurnState](
    storage=storage,
    adapter=adapter,
    authorization=authorization,
    **agents_sdk_config,
)


async def _graph_token_provider() -> str:
    """Acquire an app-only Graph token via the SDK's own MSAL connection.

    Reuses `MsalConnectionManager`'s default Service Connection (the same
    connection the adapter already builds for Bot Framework auth) instead of
    inventing a separate auth flow. `AccessTokenProviderBase.get_access_token`
    runs MSAL's confidential-client-credentials flow and caches the result
    internally, so repeated calls are cheap.
    """
    connection = connection_manager.get_default_connection()
    return await connection.get_access_token(
        "https://graph.microsoft.com", GRAPH_DEFAULT_SCOPES
    )


user_directory_service = build_user_directory_service(
    agent_settings.user_directory_mode,
    _graph_token_provider if agent_settings.user_directory_mode == "graph" else None,
    agent_settings.user_directory_cache_ttl_seconds,
)


@agent_app.conversation_update("membersAdded")
async def on_members_added(context: TurnContext, _state: TurnState) -> bool:
    await context.send_activity(
        "你好，我是 Teams AI Agent 測試 Bot。請傳送訊息，我會先用 Echo 模式回覆。"
    )
    return True


@agent_app.message(re.compile(r"^/help$", re.IGNORECASE))
async def on_help(context: TurnContext, _state: TurnState) -> None:
    await context.send_activity(
        f"目前模式：`{agent_settings.mode}`。傳送任意文字即可開始測試。"
    )


async def _handle_feedback(context: TurnContext, data: dict) -> None:
    """Handle a feedback Action.Submit payload (spec §14).

    Failures are logged and always degrade silently for the user (§17):
    the user gets the same brief acknowledgement whether or not the
    feedback actually made it to the Agent Service, and never sees a stack
    trace.
    """
    correlation_id = data.get("correlationId")
    try:
        rating = data.get("rating")
        conversation_id = data.get("conversationId")
        issue_id = data.get("issueId")
        sender = context.activity.from_property
        user_id = sender.id if sender else None

        if (
            rating not in {"UP", "DOWN"}
            or not isinstance(correlation_id, str)
            or not correlation_id
            or not isinstance(conversation_id, str)
            or not conversation_id
            or not isinstance(issue_id, int)
            or isinstance(issue_id, bool)
            or not user_id
        ):
            logger.warning(
                "Ignoring malformed feedback submission: correlation_id=%s",
                correlation_id,
            )
        else:
            await agent_gateway.send_feedback(
                FeedbackRequest(
                    correlationId=correlation_id,
                    conversationId=conversation_id,
                    issueId=issue_id,
                    rating=rating,
                    userId=user_id,
                )
            )
    except AgentGatewayError:
        logger.exception(
            "Feedback submission failed: correlation_id=%s", correlation_id
        )
    except Exception:
        logger.exception(
            "Unexpected error while handling feedback: correlation_id=%s",
            correlation_id,
        )

    await context.send_activity("感謝你的回饋！")


@agent_app.activity("message")
async def on_message(context: TurnContext, _state: TurnState) -> None:
    value = context.activity.value
    if isinstance(value, dict) and value.get(FEEDBACK_ACTION_MARKER):
        await _handle_feedback(context, value)
        return

    message = clean_message_text(context.remove_recipient_mention(context.activity))

    if not message:
        await context.send_activity("我收到訊息了，但其中沒有可處理的文字。")
        return

    # Spec §15.1: one Correlation ID per Teams activity, generated once here
    # and never regenerated for retries within this turn. The adapter uses
    # this same value as both AgentRequest.requestId (the adapter's own
    # tracking id, historically surfaced to the user in error messages) and
    # AgentRequest.correlationId (the id propagated through the Agent
    # Service / LangGraph / downstream nodes). Keeping them identical avoids
    # tracking two ids for what is, from the Teams Adapter's perspective,
    # a single request.
    correlation_id = str(uuid4())

    sender = context.activity.from_property
    entra_object_id = sender.aad_object_id if sender else None
    email = await user_directory_service.get_email(entra_object_id)

    request = AgentRequest.from_activity(
        context.activity,
        message,
        correlation_id=correlation_id,
        email=email,
    )
    logger.info(
        "Message received: correlation_id=%s channel=%s conversation=%s",
        correlation_id,
        request.channel,
        request.conversation.conversationId or "unknown",
    )

    try:
        response = await agent_gateway.answer(request)
    except AgentGatewayError:
        logger.exception("Agent Gateway failed: correlation_id=%s", correlation_id)
        await context.send_activity(
            "AI Agent 暫時無法回應，請稍後再試。"
            f"\n\n追蹤編號：`{correlation_id}`"
        )
        return

    activity = build_agent_activity(
        response,
        agent_settings,
        conversation_id=request.conversation.conversationId,
    )
    await context.send_activity(activity)


@agent_app.error
async def on_error(context: TurnContext, error: Exception) -> None:
    logger.exception("Unhandled error while processing an activity", exc_info=error)
    await context.send_activity("Bot 處理訊息時發生錯誤，請稍後再試。")
