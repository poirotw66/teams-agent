"use strict";

const { randomUUID } = require("node:crypto");
const { rotateSessionCookie, rotatePlaygroundSessionId } = require("./auth");
const { securityHeaders } = require("./http");
const { injectPlaygroundEvaluation } = require("./knowledge-control");

function personalChatIdFromConfig(config) {
  return config?.config?.personalChat?.id || config?.personalChat?.id || null;
}

async function resetPlaygroundConversation(playgroundTarget) {
  const base = playgroundTarget.replace(/\/$/, "");
  const configResponse = await fetch(`${base}/_internal/v1/config`, {
    signal: AbortSignal.timeout(20000),
  });
  if (!configResponse.ok) {
    throw new Error(`playground config failed (${configResponse.status})`);
  }
  const config = await configResponse.json();
  const personalChatId = personalChatIdFromConfig(config);
  if (!personalChatId) {
    throw new Error("playground config missing personalChat.id");
  }

  // Mint a DirectLine conversation id locally. POST /v3/conversations lives under
  // /_connector and requires Bot JWT; the debug link API only needs a unique id.
  const conversationId = randomUUID();
  const linkResponse = await fetch(`${base}/_debug/conversation/addDirectLineConversationLink`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ directLineConversationId: conversationId, conversationId: personalChatId }),
    signal: AbortSignal.timeout(5000),
  });
  if (!linkResponse.ok) {
    throw new Error(`playground conversation link failed (${linkResponse.status})`);
  }

  return { personalChatId, conversationId };
}

async function handleNewConversationRequest(req, res, state, sessionSecret, secureCookie, playgroundTarget) {
  try {
    const created = await resetPlaygroundConversation(playgroundTarget);
    const playgroundSessionId = rotatePlaygroundSessionId(req, state);
    res.writeHead(200, {
      "content-type": "application/json; charset=utf-8",
      "set-cookie": rotateSessionCookie(req, state, sessionSecret, secureCookie),
      ...securityHeaders(),
    });
    res.end(
      JSON.stringify({
        ok: true,
        conversationId: created.conversationId,
        playgroundSessionId,
      }),
    );
  } catch (error) {
    res.writeHead(502, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify({ detail: error instanceof Error ? error.message : "無法重設 Playground 對話" }));
  }
}

async function proxyAdapterMessages(req, res, adapterTarget, evaluationBackend, playgroundSessionId) {
  if (!adapterTarget) {
    res.writeHead(503, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify({ detail: "Adapter proxy 尚未設定" }));
    return;
  }
  try {
    let body = "";
    req.setEncoding("utf8");
    for await (const chunk of req) {
      body += chunk;
      if (body.length > 1024 * 1024) {
        res.writeHead(413, { "content-type": "text/plain; charset=utf-8", ...securityHeaders() });
        res.end("Request body too large\n");
        return;
      }
    }
    let payload = body ? JSON.parse(body) : {};
    if (typeof payload === "object" && payload !== null) {
      payload = injectPlaygroundEvaluation(payload, evaluationBackend, playgroundSessionId);
      body = JSON.stringify(payload);
    }
    const headers = {
      accept: req.headers.accept || "application/json",
      "content-type": req.headers["content-type"] || "application/json",
    };
    for (const name of ["authorization", "x-ms-conversation-id", "x-ms-correlation-id"]) {
      const value = req.headers[name];
      if (typeof value === "string" && value) headers[name] = value;
    }
    const response = await fetch(`${adapterTarget.replace(/\/$/, "")}/api/messages`, {
      method: req.method,
      headers,
      body: body || undefined,
      signal: AbortSignal.timeout(30000),
    });
    const responseBody = await response.text();
    const responseHeaders = {
      "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
      ...securityHeaders(),
    };
    res.writeHead(response.status, responseHeaders);
    res.end(responseBody);
  } catch (_error) {
    res.writeHead(502, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify({ detail: "無法連線到 Teams Adapter" }));
  }
}

module.exports = {
  personalChatIdFromConfig,
  resetPlaygroundConversation,
  handleNewConversationRequest,
  proxyAdapterMessages,
};
