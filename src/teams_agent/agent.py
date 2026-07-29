import logging
import re
from os import environ

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
from .cards import build_agent_activity
from .contracts import AgentRequest
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


@agent_app.activity("message")
async def on_message(context: TurnContext, _state: TurnState) -> None:
    message = clean_message_text(context.remove_recipient_mention(context.activity))

    if not message:
        await context.send_activity("我收到訊息了，但其中沒有可處理的文字。")
        return

    request = AgentRequest.from_activity(context.activity, message)
    logger.info(
        "Message received: request_id=%s channel=%s conversation=%s",
        request.requestId,
        request.channel,
        request.conversation.conversationId or "unknown",
    )

    try:
        response = await agent_gateway.answer(request)
    except AgentGatewayError:
        logger.exception("Agent Gateway failed: request_id=%s", request.requestId)
        await context.send_activity(
            "AI Agent 暫時無法回應，請稍後再試。"
            f"\n\n追蹤編號：`{request.requestId}`"
        )
        return

    await context.send_activity(build_agent_activity(response, agent_settings))


@agent_app.error
async def on_error(context: TurnContext, error: Exception) -> None:
    logger.exception("Unhandled error while processing an activity", exc_info=error)
    await context.send_activity("Bot 處理訊息時發生錯誤，請稍後再試。")
