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

from .text import clean_message_text

logger = logging.getLogger(__name__)

load_dotenv()
agents_sdk_config = load_configuration_from_env(environ)

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
        "目前是 Echo 測試模式。傳送任意文字後，我會回覆「收到：你的訊息」。"
    )


@agent_app.activity("message")
async def on_message(context: TurnContext, _state: TurnState) -> None:
    message = clean_message_text(context.remove_recipient_mention(context.activity))

    if not message:
        await context.send_activity("我收到訊息了，但其中沒有可處理的文字。")
        return

    logger.info(
        "Message received: channel=%s conversation=%s",
        context.activity.channel_id,
        context.activity.conversation.id if context.activity.conversation else "unknown",
    )
    await context.send_activity(f"收到：{message}")


@agent_app.error
async def on_error(context: TurnContext, error: Exception) -> None:
    logger.exception("Unhandled error while processing an activity", exc_info=error)
    await context.send_activity("Bot 處理訊息時發生錯誤，請稍後再試。")
