"use strict";

const assert = require("node:assert/strict");
const http = require("node:http");
const test = require("node:test");
const {
  createGateway,
  parseCookies,
  safeEqual,
  signSession,
  verifySession,
  injectPlaygroundEvaluation,
} = require("../server");
const { rewriteAdapterAssetUrls } = require("../lib/source-proxy");

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test("signed sessions validate before expiry", () => {
  const now = 1_700_000_000_000;
  const token = signSession("a sufficiently long test secret", now, 60);
  assert.equal(verifySession(token, "a sufficiently long test secret", now + 30_000), true);
});

test("signed sessions reject tampering and expiry", () => {
  const now = 1_700_000_000_000;
  const token = signSession("a sufficiently long test secret", now, 60);
  assert.equal(verifySession(`${token}x`, "a sufficiently long test secret", now), false);
  assert.equal(verifySession(token, "a sufficiently long test secret", now + 61_000), false);
  assert.equal(verifySession(token, "another secret", now), false);
});

test("cookie parser handles multiple cookies", () => {
  assert.deepEqual(parseCookies("one=1; playground_session=abc%2Edef"), {
    one: "1",
    playground_session: "abc.def",
  });
});

test("constant-time comparison handles differing lengths", () => {
  assert.equal(safeEqual("correct", "correct"), true);
  assert.equal(safeEqual("correct", "incorrect-and-longer"), false);
});

test("injectPlaygroundEvaluation sets playground channel and backend override", () => {
  const injected = injectPlaygroundEvaluation(
    { channelId: "msteams", channelData: { tenant: { id: "tenant-1" } }, text: "hello" },
    "GEMINI_FILE_SEARCH",
  );
  assert.equal(injected.channelId, "playground");
  assert.equal(injected.channelData.evaluationKnowledgeBackend, "GEMINI_FILE_SEARCH");
  assert.equal(injected.text, "hello");
});

test("injectPlaygroundEvaluation omits override for HYBRID", () => {
  const injected = injectPlaygroundEvaluation(
    { channelData: { evaluationKnowledgeBackend: "GEMINI_FILE_SEARCH" } },
    "HYBRID",
  );
  assert.equal(injected.channelId, "playground");
  assert.equal(injected.channelData.evaluationKnowledgeBackend, undefined);
});

test("gateway serves Playground static assets without a browser session cookie", async () => {
  const upstream = http.createServer((_req, res) => {
    res.writeHead(200, { "content-type": "application/javascript" });
    res.end("window.__playgroundStaticLoaded = true;");
  });
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${upstreamPort}`,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const asset = await fetch(`${baseUrl}/static/js/main.js`);
    assert.equal(asset.status, 200);
    assert.equal(await asset.text(), "window.__playgroundStaticLoaded = true;");
  } finally {
    await close(gateway);
    await close(upstream);
  }
});

test("gateway protects UI while allowing the JWT-protected connector callback", async () => {
  const upstream = http.createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end(`upstream:${req.url}`);
  });
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${upstreamPort}`,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const anonymous = await fetch(`${baseUrl}/`, { redirect: "manual" });
    assert.equal(anonymous.status, 303);
    assert.equal(anonymous.headers.get("location"), "/login");

    const connector = await fetch(`${baseUrl}/_connector/v3/conversations/example/activities`);
    assert.equal(connector.status, 200);
    assert.equal(await connector.text(), "upstream:/_connector/v3/conversations/example/activities");

    const login = await fetch(`${baseUrl}/login`, {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: "password=test-password",
    });
    assert.equal(login.status, 303);
    const cookie = login.headers.get("set-cookie").split(";", 1)[0];
    const authenticated = await fetch(`${baseUrl}/`, { headers: { cookie } });
    assert.equal(authenticated.status, 200);
    assert.equal(await authenticated.text(), "upstream:/");
  } finally {
    await close(gateway);
    await close(upstream);
  }
});

test("authenticated UI uses session-scoped knowledge backend control", async () => {
  const upstream = http.createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/html" });
    res.end("<!doctype html><html><body><div id=\"root\"></div></body></html>");
  });
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${upstreamPort}`,
    geminiFileSearchAvailable: true,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const login = await fetch(`${baseUrl}/login`, {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: "password=test-password",
    });
    const cookie = login.headers.get("set-cookie").split(";", 1)[0];
    const page = await fetch(`${baseUrl}/`, { headers: { cookie } });
    assert.match(await page.text(), /_knowledge-control\.js/);
    const controlScript = await fetch(`${baseUrl}/_knowledge-control.js`, {
      headers: { cookie },
    });
    const controlScriptText = await controlScript.text();
    assert.match(controlScriptText, /multi-window-warning/);
    assert.match(controlScriptText, /Playground 會將回覆同步顯示/);
    assert.match(controlScriptText, /測試時請只使用一個視窗/);
    assert.match(controlScriptText, /新對話/);
    assert.match(controlScriptText, /\/api\/new-conversation/);

    const status = await fetch(`${baseUrl}/api/knowledge-backend`, { headers: { cookie } });
    assert.equal((await status.json()).activeBackend, "HYBRID");

    const switched = await fetch(`${baseUrl}/api/knowledge-backend`, {
      method: "PUT",
      headers: { cookie, "content-type": "application/json" },
      body: JSON.stringify({ backend: "GEMINI_FILE_SEARCH" }),
    });
    assert.equal((await switched.json()).activeBackend, "GEMINI_FILE_SEARCH");
  } finally {
    await close(gateway);
    await close(upstream);
  }
});

test("adapter proxy exposes GET readiness for wait-on", async () => {
  const upstream = http.createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
  });
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${upstreamPort}`,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const ready = await fetch(`${baseUrl}/_adapter/api/messages`);
    assert.equal(ready.status, 200);
    assert.deepEqual(await ready.json(), { status: "ok" });
  } finally {
    await close(gateway);
    await close(upstream);
  }
});

test("adapter proxy injects evaluation backend without browser session cookie", async () => {
  let receivedBody = null;
  const adapter = http.createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    receivedBody = JSON.parse(body);
    res.writeHead(200, { "content-type": "application/json" });
    res.end('{"status":"accepted"}');
  });
  const upstream = http.createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
  });
  const adapterPort = await listen(adapter);
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${adapterPort}`,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const login = await fetch(`${baseUrl}/login`, {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: "password=test-password",
    });
    const cookie = login.headers.get("set-cookie").split(";", 1)[0];
    await fetch(`${baseUrl}/api/knowledge-backend`, {
      method: "PUT",
      headers: { cookie, "content-type": "application/json" },
      body: JSON.stringify({ backend: "GEMINI_FILE_SEARCH" }),
    });

    const proxied = await fetch(`${baseUrl}/_adapter/api/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        type: "message",
        channelId: "msteams",
        text: "VPN 問題",
        channelData: { tenant: { id: "tenant-1" } },
      }),
    });
    assert.equal(proxied.status, 200);
    assert.equal(receivedBody.channelId, "playground");
    assert.equal(receivedBody.channelData.evaluationKnowledgeBackend, "GEMINI_FILE_SEARCH");
    assert.equal(receivedBody.text, "VPN 問題");
  } finally {
    await close(gateway);
    await close(upstream);
    await close(adapter);
  }
});

test("new conversation resets playground direct line conversation and rotates session", async () => {
  let linkBody = null;
  const upstream = http.createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    if (req.url === "/_internal/v1/config" && req.method === "GET") {
      res.writeHead(200, { "content-type": "application/json" });
      // Match the live Agents Playground shape: personalChat is nested under config.
      res.end(
        JSON.stringify({
          config: { personalChat: { id: "personal-chat-1", name: "Personal" } },
          internalConfig: {},
        }),
      );
      return;
    }
    if (req.url === "/_debug/conversation/addDirectLineConversationLink" && req.method === "POST") {
      linkBody = JSON.parse(body);
      res.writeHead(200);
      res.end();
      return;
    }
    res.writeHead(404);
    res.end("not found");
  });
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${upstreamPort}`,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const login = await fetch(`${baseUrl}/login`, {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: "password=test-password",
    });
    const cookie = login.headers.get("set-cookie").split(";", 1)[0];

    const reset = await fetch(`${baseUrl}/api/new-conversation`, {
      method: "POST",
      headers: { cookie },
    });
    assert.equal(reset.status, 200);
    const payload = await reset.json();
    assert.equal(payload.ok, true);
    assert.equal(typeof payload.conversationId, "string");
    assert.match(payload.conversationId, /^[0-9a-f-]{36}$/i);
    assert.equal(typeof payload.playgroundSessionId, "string");
    assert.ok(payload.playgroundSessionId.length > 0);
    assert.deepEqual(linkBody, {
      conversationId: "personal-chat-1",
      directLineConversationId: payload.conversationId,
    });
    assert.match(reset.headers.get("set-cookie"), /playground_session=/);

    const resetAgain = await fetch(`${baseUrl}/api/new-conversation`, {
      method: "POST",
      headers: { cookie: reset.headers.get("set-cookie").split(";", 1)[0] },
    });
    assert.equal(resetAgain.status, 200);
    const again = await resetAgain.json();
    assert.notEqual(again.playgroundSessionId, payload.playgroundSessionId);
  } finally {
    await close(gateway);
    await close(upstream);
  }
});

test("adapter proxy injects playgroundSessionId for logical conversation reset", async () => {
  const receivedBodies = [];
  const adapter = http.createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    receivedBodies.push(JSON.parse(body));
    res.writeHead(200, { "content-type": "application/json" });
    res.end('{"status":"accepted"}');
  });
  const upstream = http.createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
  });
  const adapterPort = await listen(adapter);
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${adapterPort}`,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    // Bot Framework posts have no browser session cookie. Session id must stay
    // stable across turns so clarification / handoff context survives.
    for (const text of ["你好", "大州系統無法點選"]) {
      const proxied = await fetch(`${baseUrl}/_adapter/api/messages`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          type: "message",
          channelId: "msteams",
          text,
          channelData: { tenant: { id: "tenant-1" } },
        }),
      });
      assert.equal(proxied.status, 200);
    }
    assert.equal(receivedBodies.length, 2);
    assert.equal(receivedBodies[0].channelId, "playground");
    assert.equal(typeof receivedBodies[0].channelData.playgroundSessionId, "string");
    assert.equal(
      receivedBodies[0].channelData.playgroundSessionId,
      receivedBodies[1].channelData.playgroundSessionId,
    );
  } finally {
    await close(gateway);
    await close(upstream);
    await close(adapter);
  }
});

test("rewrites adapter source links to the current page and leaves images on the adapter", () => {
  const rewritten = rewriteAdapterAssetUrls(
    "see https://adapter.example/rag-sources/vpn.md?signature=abc and https://adapter.example/rag-assets/a.png and https://adapter.example/rag-originals/src-1?signature=xyz and https://adapter.example/rag-citations/src-1?signature=preview",
    "https://adapter.example",
  );
  assert.match(rewritten, /\/rag-sources\/vpn\.md\?signature=abc/);
  assert.doesNotMatch(rewritten, /https:\/\/adapter\.example\/rag-sources/);
  assert.match(rewritten, /\/rag-originals\/src-1\?signature=xyz/);
  assert.doesNotMatch(rewritten, /https:\/\/adapter\.example\/rag-originals/);
  assert.match(rewritten, /https:\/\/adapter\.example\/rag-assets\/a\.png/);
  assert.match(rewritten, /\/rag-citations\/src-1\?signature=preview/);
  assert.doesNotMatch(rewritten, /https:\/\/adapter\.example\/rag-citations/);
});

test("authenticated source links are proxied with the gateway viewer assertion", async () => {
  let seen = null;
  const adapter = http.createServer((req, res) => {
    seen = {
      url: req.url,
      subject: req.headers["x-viewer-subject"],
      secret: req.headers["x-gateway-secret"],
    };
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end("<p>VPN policy</p>");
  });
  const upstream = http.createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/html" });
    res.end("<html><head></head><body></body></html>");
  });
  const adapterPort = await listen(adapter);
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: `http://127.0.0.1:${adapterPort}`,
    publicBaseUrl: "https://playground.example",
    sourceGatewaySecret: "gateway-secret-value",
    secureCookie: false,
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const denied = await fetch(`${baseUrl}/rag-sources/vpn.md?subject=playground.user%40example.test`, { redirect: "manual" });
    assert.equal(denied.status, 303);
    assert.equal(denied.headers.get("location"), "/login");

    const login = await fetch(`${baseUrl}/login`, {
      method: "POST",
      redirect: "manual",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: "password=test-password",
    });
    const cookie = login.headers.get("set-cookie").split(";", 1)[0];
    const opened = await fetch(`${baseUrl}/rag-sources/vpn.md?subject=playground.user%40example.test&signature=abc`, {
      headers: { cookie, accept: "text/html" },
    });
    assert.equal(opened.status, 200);
    assert.equal(await opened.text(), "<p>VPN policy</p>");
    assert.equal(seen.subject, "playground.user@example.test");
    assert.equal(seen.secret, "gateway-secret-value");
    assert.equal(seen.url, "/rag-sources/vpn.md?subject=playground.user%40example.test&signature=abc");
    assert.equal(opened.headers.get("x-gateway-secret"), null);

    const rangedUpstream = http.createServer(async (req, res) => {
      assert.equal(req.headers.range, "bytes=0-3");
      res.writeHead(206, {
        "content-type": "application/pdf",
        "content-range": "bytes 0-3/12",
        "accept-ranges": "bytes",
        "content-length": "4",
        "content-disposition": 'inline; filename="vpn.pdf"',
      });
      res.end("VPN-");
    });
    const rangedPort = await listen(rangedUpstream);
    const rangedGateway = createGateway({
      password: "test-password",
      sessionSecret: "a sufficiently long test session secret",
      target: `http://127.0.0.1:${upstreamPort}`,
      adapterTarget: `http://127.0.0.1:${rangedPort}`,
      publicBaseUrl: "https://playground.example",
      sourceGatewaySecret: "gateway-secret-value",
      secureCookie: false,
    });
    const rangedGatewayPort = await listen(rangedGateway);
    const rangedBase = `http://127.0.0.1:${rangedGatewayPort}`;
    const ranged = await fetch(`${rangedBase}/rag-sources/vpn.pdf?subject=playground.user%40example.test&signature=abc`, {
      headers: { cookie, range: "bytes=0-3", accept: "application/pdf" },
    });
    assert.equal(ranged.status, 206);
    assert.equal(ranged.headers.get("content-range"), "bytes 0-3/12");
    assert.equal(ranged.headers.get("accept-ranges"), "bytes");
    assert.equal(ranged.headers.get("content-length"), "4");
    assert.equal(await ranged.text(), "VPN-");
    await close(rangedGateway);
    await close(rangedUpstream);

    const index = await fetch(`${baseUrl}/`, { headers: { cookie } });
    const html = await index.text();
    assert.match(html, /assetUrl/);
    assert.doesNotMatch(html, /gateway-secret-value/);
  } finally {
    await close(gateway);
    await close(upstream);
    await close(adapter);
  }
});

test("connector activities rewrite private adapter source links before the playground stores them", async () => {
  let stored = "";
  const upstream = http.createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    stored = body;
    res.writeHead(200, { "content-type": "application/json" });
    res.end('{"id":"activity-1"}');
  });
  const upstreamPort = await listen(upstream);
  const gateway = createGateway({
    password: "test-password",
    sessionSecret: "a sufficiently long test session secret",
    target: `http://127.0.0.1:${upstreamPort}`,
    adapterTarget: "https://adapter.example",
    publicBaseUrl: "https://playground.example",
  });
  const gatewayPort = await listen(gateway);
  const baseUrl = `http://127.0.0.1:${gatewayPort}`;

  try {
    const posted = await fetch(`${baseUrl}/_connector/v3/conversations/chat/activities`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer bot-token" },
      body: JSON.stringify({
        type: "message",
        text: "來源 [VPN](https://adapter.example/rag-sources/vpn.md?signature=abc)",
      }),
    });
    assert.equal(posted.status, 200);
    assert.match(stored, /\/rag-sources\/vpn\.md\?signature=abc/);
    assert.doesNotMatch(stored, /adapter\.example\/rag-sources/);
  } finally {
    await close(gateway);
    await close(upstream);
  }
});
