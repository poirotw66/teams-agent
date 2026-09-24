import logging
import re
import time
from typing import Any
from uuid import uuid4

from microsoft_teams.api import ConversationUpdateActivity, MessageActivity
from microsoft_teams.api.activities.utils import StripMentionsTextOptions
from microsoft_teams.apps import ActivityContext, App, ErrorEvent
from microsoft_teams.apps.plugins import StreamNotAllowedError, TerminalStreamError

from .agent_gateway import AgentGateway, AgentGatewayError
from .agent_message_delivery import deliver_gateway_answer
from .cards import FEEDBACK_ACTION_MARKER, build_agent_activity
from .contracts import (
    AgentRequest,
    AgentResponse,
    FeedbackRequest,
    account_field,
    activity_tenant_id,
)
from .directory import EntraAppTokenProvider, build_user_directory_service
from .health_telemetry import AdapterHealthReporter, classify_gateway_status
from .server import build_http_adapter
from .settings import AgentSettings
from .source_links import (
    CitationViewerContext,
    citation_source_groups,
    citation_source_tenant_id,
    register_viewer_membership,
)
from .text import clean_message_text

logger = logging.getLogger(__name__)

_GEMINI_DOTENV_KEY_NAMES = frozenset(
    {
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_EVAL_API_KEY",
        "GOOGLE_EVAL_API_KEY",
    }
)


def _load_adapter_dotenv() -> None:
    """Load adapter secrets without importing Gemini API keys.

    The adapter never constructs Gemini clients. Keys stay in the Agent
    process so a shared ``.env`` cannot inject them into this one.
    """
    from os import environ

    from dotenv import dotenv_values

    for key, value in dotenv_values().items():
        if not key or value is None or key in _GEMINI_DOTENV_KEY_NAMES:
            continue
        if key in environ:
            continue
        environ[key] = value.replace("\r", "") if "\r" in value else value


_load_adapter_dotenv()
agent_settings = AgentSettings.from_env()
agent_gateway = AgentGateway(agent_settings)
adapter_health = AdapterHealthReporter(agent_settings, agent_gateway)


def _service_unavailable_message(correlation_id: str) -> str:
    """Standard user-facing reply when the agent path cannot complete."""
    return (
        "服務暫時無法使用，請稍後再試。"
        f"\n\n追蹤編號：`{correlation_id}`"
    )

# The Microsoft Teams SDK reads CLIENT_ID / CLIENT_SECRET / TENANT_ID from the
# environment itself and validates the inbound Bot Framework JWT on
# `POST /api/messages`. `build_http_adapter` hands it the same FastAPI app
# that serves `/healthz`, `/readyz` and `/rag-assets/`, so one uvicorn
# process serves everything.
agent_app = App(http_server_adapter=build_http_adapter(agent_settings))

# Graph lookups reuse the app's own Entra app registration (app-only client
# credentials). Built only when Graph mode is on *and* a full credential set
# exists; otherwise the User Directory Service falls back to disabled and the
# adapter simply forwards no email (spec §11.4).
_graph_token_provider = (
    EntraAppTokenProvider(
        agent_settings.client_id or "",
        agent_settings.client_secret or "",
        agent_settings.tenant_id or "",
    )
    if agent_settings.user_directory_mode == "graph"
    and agent_settings.graph_credentials_ready
    else None
)

user_directory_service = build_user_directory_service(
    agent_settings.user_directory_mode,
    _graph_token_provider,
    agent_settings.user_directory_cache_ttl_seconds,
)


def _welcome_message(mode: str) -> str:
    if mode == "echo":
        return "你好，我是 Teams AI Agent 測試 Bot。目前為 Echo 測試模式，會原樣回覆訊息。"
    return (
        "你好，我是 Teams AI Agent 測試 Bot。"
        "請描述公司 IT 問題，我會查詢企業知識庫並協助處理。"
    )


def resolve_request_groups(activity: MessageActivity) -> list[str]:
    """Resolve retrieval ACL groups for an inbound Teams activity.

    Agents Playground identities do not carry Graph group membership. Reuse
    ``citation_source_groups`` so retrieval and citation viewers agree on the
    public corpus group for the synthetic playground tenant.
    """
    return list(
        citation_source_groups(
            activity.channel_id or "unknown",
            activity_tenant_id(activity),
            (),
        )
    )


@agent_app.on_conversation_update
async def on_conversation_update(
    ctx: ActivityContext[ConversationUpdateActivity],
) -> None:
    if not ctx.activity.members_added:
        return
    await ctx.send(_welcome_message(agent_settings.mode))


# Commands are matched after the bot's @mention is stripped, not by
# `on_message_pattern`. That decorator tests the regex against the raw
# `activity.text`, which in a channel is "<at>TeamsAgent</at> /help" -- so an
# anchored pattern never matches there. This app installs to a team by
# default and advertises /help for both scopes in the manifest, so command
# matching has to survive being @mentioned.
_HELP_COMMAND = re.compile(r"^/help$", re.IGNORECASE)


async def _handle_feedback(ctx: ActivityContext[MessageActivity], data: dict) -> None:
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
        sender = ctx.activity.from_
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

    await ctx.send("感謝你的回饋！")


@agent_app.on_message
async def on_message(ctx: ActivityContext[MessageActivity]) -> None:
    """Entry point for every inbound Teams message.

    The Teams SDK reports handler exceptions through its `error` event but
    does not reply to the user on its own, so the turn is wrapped here to
    keep the adapter's contract from the Agents SDK version: the user always
    gets a reply, never a stack trace (spec §17).
    """
    started_at = time.perf_counter()
    correlation_id = str(uuid4())
    try:
        await _handle_message(ctx, started_at=started_at)
    except Exception as error:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        logger.exception(
            "Unhandled error while processing a message activity: "
            "correlation_id=%s",
            correlation_id,
        )
        adapter_health.schedule_reply(
            status="FAILED",
            elapsed_ms=elapsed_ms,
            correlation_id=correlation_id,
            error_type=type(error).__name__,
        )
        await ctx.send(_service_unavailable_message(correlation_id))


async def _resolve_sender_email(sender: Any) -> str | None:
    # Teams populates `from.email` on some channels; the User Directory
    # Service only has to call Graph when the activity didn't carry one (spec §12).
    email = account_field(sender, "email", "email") if sender else None
    if not email:
        entra_object_id = sender.aad_object_id if sender else None
        email = await user_directory_service.get_email(entra_object_id)
    if not email and agent_settings.uses_playground_identity_fallback:
        email = agent_settings.playground_test_user_email
    return email


async def _handle_message(
    ctx: ActivityContext[MessageActivity],
    *,
    started_at: float | None = None,
) -> None:
    if started_at is None:
        started_at = time.perf_counter()
    value = ctx.activity.value
    if isinstance(value, dict) and value.get(FEEDBACK_ACTION_MARKER):
        await _handle_feedback(ctx, value)
        return

    # Strip the bot's own @mention on a copy so the original activity keeps
    # the text Teams actually delivered (the SDK's `strip_mentions_text`
    # rewrites in place).
    recipient = ctx.activity.recipient
    stripped = ctx.activity.model_copy().strip_mentions_text(
        StripMentionsTextOptions(account_id=recipient.id) if recipient else None
    )
    message = clean_message_text(stripped.text)

    if not message:
        await ctx.send("我收到訊息了，但其中沒有可處理的文字。")
        return

    if _HELP_COMMAND.match(message):
        await ctx.send(
            f"目前模式：`{agent_settings.mode}`。傳送任意文字即可開始測試。"
        )
        return

    # Spec §15.1: one Correlation ID per Teams activity, generated once here
    # and never regenerated for retries within this turn.
    correlation_id = str(uuid4())
    email = await _resolve_sender_email(ctx.activity.from_)


    # Playground synthetic identities have no Graph groups; mirror
    # citation_source_groups so Hybrid ACL can see grp_public corpus chunks.
    request_groups = resolve_request_groups(ctx.activity)
    request = AgentRequest.from_activity(
        ctx.activity,
        message,
        correlation_id=correlation_id,
        email=email,
        groups=request_groups,
    )
    logger.info(
        "Message received: correlation_id=%s channel=%s conversation=%s",
        correlation_id,
        request.channel,
        request.conversation.conversationId or "unknown",
    )

    if _streaming_supported(ctx):
        delivered = await _answer_streaming(
            ctx, request, correlation_id, started_at=started_at
        )
        if delivered:
            return
        # Streaming was refused by Teams before any answer reached the user.
        # Fall through to the plain request/response path rather than leaving
        # the turn unanswered.

    await deliver_gateway_answer(
        ctx=ctx,
        request=request,
        correlation_id=correlation_id,
        started_at=started_at,
        agent_gateway=agent_gateway,
        adapter_health=adapter_health,
        build_activity=_build_activity,
        service_unavailable_message=_service_unavailable_message,
    )

def _build_activity(response: AgentResponse, request: AgentRequest):
    subject = (
        request.user.entraObjectId
        or request.user.teamsUserId
        or request.user.email
        or "anonymous"
    )
    source_groups = citation_source_groups(
        request.channel,
        request.conversation.tenantId,
        tuple(request.user.groups or ()),
    )
    viewer = CitationViewerContext(
        subject=subject,
        groups=source_groups,
        tenant_id=citation_source_tenant_id(
            request.channel,
            request.conversation.tenantId,
        ),
    )
    # Refresh live membership on every authenticated turn so citation opens
    # re-authorize against current groups rather than signed URL claims.
    register_viewer_membership(viewer, agent_settings)
    return build_agent_activity(
        response,
        agent_settings,
        conversation_id=request.conversation.conversationId,
        viewer=viewer,
    )


def _streaming_supported(ctx: ActivityContext[MessageActivity]) -> bool:
    """Whether this turn may stream progress.

    Teams only renders streamed messages in 1:1 personal chats; in a channel
    or group chat the service answers the first stream activity with HTTP 403
    (surfacing as `StreamNotAllowedError`). This bot installs to a team by
    default, so most turns take the plain path -- checking the scope up front
    keeps them from paying a failed round-trip to find that out.
    """
    if not agent_settings.streaming_ready:
        return False
    conversation = ctx.activity.conversation
    return bool(conversation) and conversation.conversation_type == "personal"


async def _answer_streaming(
    ctx: ActivityContext[MessageActivity],
    request: AgentRequest,
    correlation_id: str,
    *,
    started_at: float | None = None,
) -> bool:
    if started_at is None:
        started_at = time.perf_counter()
    """Stream workflow progress, then finalize with the answer.

    Returns True when the user has been given something -- an answer or an
    error message -- and False only when nothing was delivered and the caller
    should retry on the non-streaming path.

    The final Adaptive Card is emitted as the stream's closing activity
    because Teams only accepts an attachment on the last message of a stream;
    `clear_text` first drops the accumulated progress text so the card
    replaces it rather than appearing under it.
    """
    try:
        async for kind, value in agent_gateway.answer_stream(request):
            if kind == "stage":
                ctx.stream.update(value)
            elif kind == "response":
                ctx.stream.clear_text()
                ctx.stream.emit(_build_activity(value, request))
        await ctx.stream.close()
        adapter_health.schedule_reply(
            status="SUCCESS",
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 1),
            correlation_id=correlation_id,
            channel=request.channel,
        )
        return True
    except StreamNotAllowedError:
        # Teams refused mid-flight despite the scope check (e.g. a policy the
        # adapter cannot see). Nothing was rendered, so the caller retries
        # without streaming.
        logger.warning(
            "Teams refused streaming; falling back to a plain reply: "
            "correlation_id=%s",
            correlation_id,
        )
        return False
    except AgentGatewayError as error:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        status, error_type = classify_gateway_status(error)
        logger.exception(
            "Agent Gateway streaming failed: correlation_id=%s", correlation_id
        )
        adapter_health.schedule_reply(
            status=status,
            elapsed_ms=elapsed_ms,
            correlation_id=correlation_id,
            channel=request.channel,
            error_type=error_type,
        )
        await _fail_stream(ctx, correlation_id)
        return True
    except TerminalStreamError as error:
        # Cancelled by the user or past Teams' two-minute streaming limit.
        # Partial progress is already on screen, so a plain re-answer would
        # duplicate it; report the turn as delivered.
        logger.warning(
            "Teams ended the stream before completion: correlation_id=%s",
            correlation_id,
        )
        adapter_health.schedule_reply(
            status="TIMEOUT",
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 1),
            correlation_id=correlation_id,
            channel=request.channel,
            error_type=type(error).__name__,
        )
        return True


async def _fail_stream(
    ctx: ActivityContext[MessageActivity], correlation_id: str
) -> None:
    """Turn a half-streamed turn into the standard error reply."""
    text = _service_unavailable_message(correlation_id)
    try:
        ctx.stream.clear_text()
        ctx.stream.emit(text)
        await ctx.stream.close()
    except TerminalStreamError:
        # The stream itself is unusable; deliver the error as a normal message.
        await ctx.send(text)


@agent_app.event("error")
async def on_error(event: ErrorEvent) -> None:
    logger.exception(
        "Unhandled error while processing an activity", exc_info=event.error
    )
