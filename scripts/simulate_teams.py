#!/usr/bin/env python
"""Drive the Teams Adapter locally, with no Teams and no Azure.

Stage 1 of the two-stage local acceptance (see docs/teams-app-setup.md §7):
protocol and round-trip. This runs the real adapter behind a real uvicorn
server, posts real Bot Framework activities at `POST /api/messages`, and
captures what the bot sends *back* -- so unlike a unit test, the outbound
half of the turn is exercised too.

How the capture works: `ActivitySender` builds its API client from the
inbound activity's own `serviceUrl`, so pointing that field at a local sink
is enough to intercept everything the bot sends, including the PUT-based
updates that streaming uses. Nothing is stubbed inside the adapter.

    # Echo mode -- adapter only, nothing else needs to be running
    uv run python scripts/simulate_teams.py

    # Full RAG path, against a running Agent Service (`uv run rag-agent`)
    uv run python scripts/simulate_teams.py \
        --agent-url http://localhost:8000/agent/chat

    # Streaming is 1:1 only; --scope channel takes the plain-reply path
    uv run python scripts/simulate_teams.py \
        --agent-url http://localhost:8000/agent/chat --scope channel

What this does NOT cover, and why stage 2 (sideloading into real Teams)
still exists: how Teams *renders* an Adaptive Card, whether images resolve,
and whether streamed progress actually animates in the client. Those are
Teams client behaviours; this harness only proves the adapter emits the
right activities in the right order.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
from contextlib import closing
from typing import Any

# Imported at module level on purpose. This file uses postponed annotation
# evaluation, so FastAPI resolves a handler's `Request` annotation through
# the module globals -- importing it inside the factory below leaves the
# annotation unresolvable and FastAPI silently demotes `request` to a query
# parameter, answering every capture with HTTP 422.
import aiohttp
import uvicorn
from fastapi import FastAPI, Request

SCOPES = {"personal": "personal", "channel": "channel", "group": "groupChat"}


def free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_sink(captured: list[tuple[str, dict[str, Any]]]):
    """A stand-in for the Bot Framework service the adapter replies to."""
    app = FastAPI()

    @app.post("/v3/conversations/{conversation_id}/activities")
    async def create(conversation_id: str, request: Request):
        captured.append(("send", await request.json()))
        return {"id": f"sent-{len(captured)}"}

    @app.post("/v3/conversations/{conversation_id}/activities/{activity_id}")
    async def reply(conversation_id: str, activity_id: str, request: Request):
        captured.append(("send", await request.json()))
        return {"id": f"sent-{len(captured)}"}

    @app.put("/v3/conversations/{conversation_id}/activities/{activity_id}")
    async def update(conversation_id: str, activity_id: str, request: Request):
        # Streaming updates the same message in place, so these arrive as PUT.
        captured.append(("update", await request.json()))
        return {"id": activity_id}

    return app


async def serve(app, port: int):
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    return server, asyncio.create_task(server.serve())


def activity(
    text: str,
    *,
    service_url: str,
    scope: str,
    activity_id: str,
    value: dict[str, Any] | None = None,
    activity_type: str = "message",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": activity_type,
        "id": activity_id,
        "channelId": "msteams",
        "serviceUrl": service_url,
        "from": {"id": "user-1", "name": "Justin", "aadObjectId": "entra-user-1"},
        "recipient": {"id": "bot-1", "name": "TeamsAgent"},
        "conversation": {"id": "conversation-1", "conversationType": scope},
        "channelData": {"tenant": {"id": "tenant-1"}},
        "locale": "zh-TW",
        "text": text,
    }
    if scope != "personal":
        payload["channelData"]["team"] = {"id": "team-1"}
        payload["channelData"]["channel"] = {"id": "channel-1"}
        # In a channel the user @mentions the bot; the adapter must strip it.
        payload["text"] = f"<at>TeamsAgent</at> {text}"
        payload["entities"] = [
            {
                "type": "mention",
                "text": "<at>TeamsAgent</at>",
                "mentioned": {"id": "bot-1", "name": "TeamsAgent"},
            }
        ]
    if value is not None:
        payload["value"] = value
        payload["text"] = ""
    return payload


def describe(kind: str, body: dict[str, Any]) -> str:
    attachments = body.get("attachments") or []
    if attachments:
        card = attachments[0].get("content") or {}
        blocks = card.get("body") or []
        kinds = [block.get("type") for block in blocks]
        actions = [
            action.get("title")
            for block in blocks
            if block.get("type") == "ActionSet"
            for action in block.get("actions", [])
        ]
        summary = f"AdaptiveCard blocks={kinds}"
        if actions:
            summary += f" actions={actions}"
        return summary
    text = (body.get("text") or "").replace("\n", " ")
    if body.get("type") == "typing":
        return f"[typing] {text}"
    return text[:160]


async def drive(args) -> int:
    captured: list[tuple[str, dict[str, Any]]] = []
    sink_port = free_port()
    bot_port = free_port()
    service_url = f"http://127.0.0.1:{sink_port}"

    sink_server, sink_task = await serve(build_sink(captured), sink_port)

    # Imported only now: teams_agent.agent reads its settings at import time.
    from teams_agent.agent import agent_app, agent_settings

    print(f"mode={agent_settings.mode} scope={args.scope} streaming="
          f"{agent_settings.streaming_ready and args.scope == 'personal'}")

    await agent_app.initialize()
    bot_server, bot_task = await serve(agent_app.server.adapter.app, bot_port)
    await asyncio.sleep(1.0)

    turns: list[tuple[str, dict[str, Any]]] = [
        ("問題", activity(args.message, service_url=service_url, scope=args.scope,
                          activity_id="activity-1")),
        ("/help", activity("/help", service_url=service_url, scope=args.scope,
                           activity_id="activity-2")),
        ("空白訊息", activity("", service_url=service_url, scope=args.scope,
                              activity_id="activity-3")),
        ("👍 回饋", activity("", service_url=service_url, scope=args.scope,
                             activity_id="activity-4",
                             value={"teamsAgentFeedback": True,
                                    "correlationId": "sim-correlation-1",
                                    "conversationId": "conversation-1",
                                    "issueId": 1, "rating": "UP"})),
    ]

    failures = 0
    try:
        async with aiohttp.ClientSession() as session:
            for label, payload in turns:
                start = len(captured)
                print(f"\n--- {label} ---")
                try:
                    async with session.post(
                        f"http://127.0.0.1:{bot_port}/api/messages",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=args.timeout),
                    ) as response:
                        status = response.status
                except TimeoutError:
                    print(f"  TIMEOUT after {args.timeout}s")
                    failures += 1
                    continue

                await asyncio.sleep(0.4)
                sent = captured[start:]
                print(f"  POST /api/messages -> {status}, {len(sent)} activity(ies) out")
                for kind, body in sent:
                    marker = "  update" if kind == "update" else "  send  "
                    print(f"{marker} {describe(kind, body)}")

                if status != 200:
                    failures += 1
                elif not sent:
                    print("  NOTHING SENT -- the user would see no reply")
                    failures += 1
    finally:
        sink_server.should_exit = True
        bot_server.should_exit = True
        await asyncio.gather(sink_task, bot_task, return_exceptions=True)

    print(f"\n{'FAILED' if failures else 'OK'}: {len(captured)} activities captured, "
          f"{failures} problem(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=sorted(SCOPES), default="personal")
    parser.add_argument("--message", default="VPN 密碼被鎖住了怎麼辦？")
    parser.add_argument(
        "--agent-url",
        help="Agent Service /agent/chat URL. Omit to stay in Echo mode.",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    args.scope = SCOPES[args.scope]

    # The adapter reads all of this at import time, so it must be set first.
    os.environ["DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS"] = "true"
    if args.agent_url:
        os.environ["AGENT_MODE"] = "api"
        os.environ["AGENT_API_URL"] = args.agent_url
    else:
        os.environ["AGENT_MODE"] = "echo"

    return asyncio.run(drive(args))


if __name__ == "__main__":
    sys.exit(main())
