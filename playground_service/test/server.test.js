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
