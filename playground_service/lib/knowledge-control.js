"use strict";

const crypto = require("node:crypto");
const { SESSION_COOKIE, parseCookies } = require("./auth");
const { securityHeaders, readJson } = require("./http");

async function googleIdentityToken(audience) {
  if (!audience || !audience.startsWith("https://")) {
    throw new Error("KNOWLEDGE_CONTROL_AUDIENCE must be an HTTPS URL");
  }
  const url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity" +
    `?audience=${encodeURIComponent(audience)}&format=full`;
  const response = await fetch(url, {
    headers: { "metadata-flavor": "Google" },
    signal: AbortSignal.timeout(3000),
  });
  if (!response.ok) throw new Error(`Metadata identity endpoint returned ${response.status}`);
  return (await response.text()).trim();
}

function knowledgeBackendOptions(geminiAvailable, geminiReason) {
  return [
    { id: "HYBRID", label: "HYBRID（本機索引）", available: true, reason: null },
    {
      id: "GEMINI_FILE_SEARCH",
      label: "Gemini File Search",
      available: geminiAvailable,
      reason: geminiReason,
    },
  ];
}

function createKnowledgeBackendState({ defaultBackend = "HYBRID", geminiAvailable = true, geminiReason = null } = {}) {
  return {
    defaultBackend,
    sessionBackends: new Map(),
    sessionPlaygroundIds: new Map(),
    // Bot Framework posts to /_adapter have no browser cookie. Keep one
    // process-wide session so multi-turn handoff/clarification stay stable
    // until the user clicks「新對話」.
    playgroundSessionId: crypto.randomUUID(),
    options: knowledgeBackendOptions(geminiAvailable, geminiReason),
  };
}

function resolveEvaluationBackend(req, state) {
  const token = parseCookies(req.headers.cookie)[SESSION_COOKIE];
  if (token && state.sessionBackends.has(token)) {
    return state.sessionBackends.get(token);
  }
  return state.defaultBackend;
}

function buildKnowledgeBackendStatus(state, activeBackend) {
  return {
    activeBackend,
    options: state.options,
  };
}

async function handleKnowledgeBackendRequest(req, res, state) {
  if (req.method === "GET") {
    const activeBackend = resolveEvaluationBackend(req, state);
    res.writeHead(200, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify(buildKnowledgeBackendStatus(state, activeBackend)));
    return;
  }

  const form = await readJson(req);
  if (!["HYBRID", "GEMINI_FILE_SEARCH"].includes(form.backend)) {
    res.writeHead(400, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify({ detail: "不支援的知識後端" }));
    return;
  }
  const selected = state.options.find((option) => option.id === form.backend);
  if (!selected?.available) {
    res.writeHead(409, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify({ detail: selected?.reason || "知識後端尚未設定" }));
    return;
  }

  state.defaultBackend = form.backend;
  const token = parseCookies(req.headers.cookie)[SESSION_COOKIE];
  if (token) state.sessionBackends.set(token, form.backend);

  res.writeHead(200, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
  res.end(JSON.stringify(buildKnowledgeBackendStatus(state, form.backend)));
}

function injectPlaygroundEvaluation(activity, backend, playgroundSessionId) {
  if (!activity || typeof activity !== "object" || Array.isArray(activity)) {
    return activity;
  }
  const next = { ...activity, channelId: "playground" };
  const channelData = {
    ...(activity.channelData && typeof activity.channelData === "object" && !Array.isArray(activity.channelData)
      ? activity.channelData
      : {}),
  };
  if (backend === "GEMINI_FILE_SEARCH") {
    channelData.evaluationKnowledgeBackend = backend;
  } else {
    delete channelData.evaluationKnowledgeBackend;
  }
  if (typeof playgroundSessionId === "string" && playgroundSessionId.trim()) {
    channelData.playgroundSessionId = playgroundSessionId.trim();
  } else {
    delete channelData.playgroundSessionId;
  }
  next.channelData = channelData;
  return next;
}

async function proxyKnowledgeControl(req, res, controlUrl, controlToken, controlAuthMode, controlAudience) {
  if (!controlUrl) {
    res.writeHead(503, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify({ detail: "知識後端控制尚未設定" }));
    return;
  }
  try {
    let body;
    if (req.method === "PUT") {
      const form = await readJson(req);
      if (!["HYBRID", "GEMINI_FILE_SEARCH"].includes(form.backend)) {
        res.writeHead(400, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
        res.end(JSON.stringify({ detail: "不支援的知識後端" }));
        return;
      }
      body = JSON.stringify({ backend: form.backend });
    }
    const headers = { accept: "application/json" };
    if (body) headers["content-type"] = "application/json";
    if (controlAuthMode === "google_id_token") {
      headers.authorization = `Bearer ${await googleIdentityToken(controlAudience)}`;
    } else if (controlToken) {
      headers.authorization = `Bearer ${controlToken}`;
    }
    const response = await fetch(controlUrl, {
      method: req.method,
      headers,
      body,
      signal: AbortSignal.timeout(5000),
    });
    const responseBody = await response.text();
    res.writeHead(response.status, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(responseBody);
  } catch (_error) {
    res.writeHead(502, { "content-type": "application/json; charset=utf-8", ...securityHeaders() });
    res.end(JSON.stringify({ detail: "無法連線到 Agent 知識後端" }));
  }
}

module.exports = {
  createKnowledgeBackendState,
  buildKnowledgeBackendStatus,
  handleKnowledgeBackendRequest,
  injectPlaygroundEvaluation,
  proxyKnowledgeControl,
  resolveEvaluationBackend,
};
