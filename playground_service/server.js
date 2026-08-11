"use strict";

const crypto = require("node:crypto");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");
const httpProxy = require("http-proxy");

const SESSION_COOKIE = "playground_session";
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const MAX_LOGIN_ATTEMPTS = 5;
const attempts = new Map();

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

function digest(value) {
  return crypto.createHash("sha256").update(value).digest();
}

function safeEqual(left, right) {
  return crypto.timingSafeEqual(digest(left), digest(right));
}

function signSession(secret, now = Date.now(), ttlSeconds = 8 * 60 * 60) {
  const expiresAt = Math.floor(now / 1000) + ttlSeconds;
  const nonce = crypto.randomBytes(18).toString("base64url");
  const payload = `${expiresAt}.${nonce}`;
  const signature = crypto.createHmac("sha256", secret).update(payload).digest("base64url");
  return `${payload}.${signature}`;
}

function verifySession(token, secret, now = Date.now()) {
  if (!token) return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [expiresAt, nonce, signature] = parts;
  if (!/^\d+$/.test(expiresAt) || !nonce || !signature) return false;
  if (Number(expiresAt) <= Math.floor(now / 1000)) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(`${expiresAt}.${nonce}`)
    .digest("base64url");
  return safeEqual(signature, expected);
}

function parseCookies(header = "") {
  return Object.fromEntries(
    header
      .split(";")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => {
        const separator = item.indexOf("=");
        if (separator < 0) return [item, ""];
        return [item.slice(0, separator), decodeURIComponent(item.slice(separator + 1))];
      }),
  );
}

function securityHeaders() {
  return {
    "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
  };
}

function loginPage(error = "") {
  const message = error ? `<p class="error">${error}</p>` : "";
  return `<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Microsoft 365 Agents Playground 測試登入</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f6fb; color: #242424; }
    main { width: min(88vw, 390px); padding: 32px; background: white; border-radius: 14px; box-shadow: 0 12px 34px #0002; }
    h1 { margin: 0 0 10px; font-size: 22px; }
    p { color: #616161; line-height: 1.5; }
    label { display: block; margin: 24px 0 8px; font-weight: 600; }
    input, button { width: 100%; box-sizing: border-box; border-radius: 7px; font: inherit; }
    input { padding: 11px 12px; border: 1px solid #8a8886; }
    button { margin-top: 16px; padding: 11px; border: 0; background: #5b5fc7; color: white; font-weight: 700; cursor: pointer; }
    .error { color: #a4262c; font-weight: 600; }
  </style>
</head>
<body><main>
  <h1>Agents Playground 測試環境</h1>
  <p>此環境僅供短期驗收。請輸入測試密碼。</p>
  ${message}
  <form method="post" action="/login">
    <label for="password">密碼</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
    <button type="submit">進入測試</button>
  </form>
</main></body></html>`;
}

function clientAddress(req) {
  const forwarded = req.headers["x-forwarded-for"];
  return (typeof forwarded === "string" ? forwarded.split(",")[0].trim() : "") || req.socket.remoteAddress || "unknown";
}

function isRateLimited(address, now = Date.now()) {
  const entry = attempts.get(address);
  if (!entry || now - entry.startedAt >= LOGIN_WINDOW_MS) {
    attempts.set(address, { count: 0, startedAt: now });
    return false;
  }
  return entry.count >= MAX_LOGIN_ATTEMPTS;
}

function recordFailure(address, now = Date.now()) {
  const entry = attempts.get(address);
  if (!entry || now - entry.startedAt >= LOGIN_WINDOW_MS) {
    attempts.set(address, { count: 1, startedAt: now });
  } else {
    entry.count += 1;
  }
}

function readForm(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.setEncoding("utf8");
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 4096) reject(new Error("Request body too large"));
    });
    req.on("end", () => resolve(new URLSearchParams(body)));
    req.on("error", reject);
  });
}

function knowledgeControlScript() {
  return `"use strict";
(function () {
  const host = document.createElement("aside");
  host.id = "knowledge-backend-control";
  host.innerHTML = '<strong>知識後端</strong><select aria-label="知識後端"></select><button type="button">套用</button><span role="status">載入中…</span>';
  const style = document.createElement("style");
  style.textContent = '#knowledge-backend-control{position:fixed;z-index:2147483647;top:10px;right:16px;display:flex;gap:8px;align-items:center;padding:9px 12px;border:1px solid #d1d1d1;border-radius:8px;background:#fff;box-shadow:0 4px 14px #0002;font:13px system-ui,-apple-system,"Segoe UI",sans-serif;color:#242424}#knowledge-backend-control select,#knowledge-backend-control button{font:inherit;padding:5px 8px;border:1px solid #8a8886;border-radius:5px;background:#fff}#knowledge-backend-control button{border-color:#5b5fc7;background:#5b5fc7;color:#fff;cursor:pointer}#knowledge-backend-control button:disabled{opacity:.55;cursor:wait}#knowledge-backend-control span{max-width:230px;color:#616161}';
  document.head.appendChild(style);
  document.body.appendChild(host);
  const select = host.querySelector("select");
  const button = host.querySelector("button");
  const status = host.querySelector("span");

  function render(data) {
    select.replaceChildren(...data.options.map(function (option) {
      const node = document.createElement("option");
      node.value = option.id;
      node.textContent = option.available ? option.label : option.label + "（未設定）";
      node.disabled = !option.available;
      node.title = option.reason || "";
      node.selected = option.id === data.activeBackend;
      return node;
    }));
    status.textContent = "目前：" + (select.selectedOptions[0] ? select.selectedOptions[0].textContent : data.activeBackend);
  }

  async function load() {
    try {
      const response = await fetch("/api/knowledge-backend", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      render(await response.json());
    } catch (error) {
      status.textContent = "無法讀取後端狀態";
      button.disabled = true;
    }
  }

  button.addEventListener("click", async function () {
    button.disabled = true;
    status.textContent = "切換中…";
    try {
      const response = await fetch("/api/knowledge-backend", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ backend: select.value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "切換失敗");
      render(data);
    } catch (error) {
      status.textContent = error.message || "切換失敗";
    } finally {
      button.disabled = false;
    }
  });
  load();
})();`;
}

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

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.setEncoding("utf8");
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 4096) reject(new Error("Request body too large"));
    });
    req.on("end", () => {
      try { resolve(JSON.parse(body || "{}")); } catch (error) { reject(error); }
    });
    req.on("error", reject);
  });
}

async function proxyIndex(res, target) {
  try {
    const response = await fetch(`${target}/`);
    let body = await response.text();
    body = body.replace("</body>", '<script src="/_knowledge-control.js"></script></body>');
    const headers = { "content-type": response.headers.get("content-type") || "text/html; charset=utf-8", "cache-control": "no-store" };
    res.writeHead(response.status, headers);
    res.end(body);
  } catch (_error) {
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end("Agents Playground 尚未就緒，請稍後重試。\n");
  }
}

function createGateway({ password, sessionSecret, target = "http://127.0.0.1:56150", knowledgeControlUrl, knowledgeControlToken, knowledgeControlAuthMode = "none", knowledgeControlAudience, secureCookie = true }) {
  const proxy = httpProxy.createProxyServer({ target, ws: true, xfwd: true });
  proxy.on("error", (_error, _req, res) => {
    if (res && !res.headersSent) {
      res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      res.end("Agents Playground 尚未就緒，請稍後重試。\n");
    }
  });

  const authenticated = (req) => {
    const token = parseCookies(req.headers.cookie)[SESSION_COOKIE];
    return verifySession(token, sessionSecret);
  };

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://gateway.local");

    if (url.pathname === "/healthz") {
      res.writeHead(200, { "content-type": "application/json", ...securityHeaders() });
      res.end('{"status":"ok"}\n');
      return;
    }

    if (url.pathname === "/login" && req.method === "GET") {
      if (authenticated(req)) {
        res.writeHead(303, { location: "/" });
        res.end();
        return;
      }
      res.writeHead(200, { "content-type": "text/html; charset=utf-8", ...securityHeaders() });
      res.end(loginPage());
      return;
    }

    if (url.pathname === "/login" && req.method === "POST") {
      const address = clientAddress(req);
      if (isRateLimited(address)) {
        res.writeHead(429, { "content-type": "text/html; charset=utf-8", "retry-after": "900", ...securityHeaders() });
        res.end(loginPage("嘗試次數過多，請於 15 分鐘後再試。"));
        return;
      }
      try {
        const form = await readForm(req);
        if (!safeEqual(form.get("password") || "", password)) {
          recordFailure(address);
          res.writeHead(401, { "content-type": "text/html; charset=utf-8", ...securityHeaders() });
          res.end(loginPage("密碼錯誤。"));
          return;
        }
        attempts.delete(address);
        const token = signSession(sessionSecret);
        res.writeHead(303, {
          location: "/",
          "set-cookie": `${SESSION_COOKIE}=${encodeURIComponent(token)}; Path=/; Max-Age=28800; HttpOnly;${secureCookie ? " Secure;" : ""} SameSite=Lax`,
          ...securityHeaders(),
        });
        res.end();
      } catch (_error) {
        res.writeHead(400, { "content-type": "text/plain; charset=utf-8", ...securityHeaders() });
        res.end("無效的登入請求。\n");
      }
      return;
    }

    if (url.pathname === "/logout") {
      res.writeHead(303, {
        location: "/login",
        "set-cookie": `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly;${secureCookie ? " Secure;" : ""} SameSite=Lax`,
        ...securityHeaders(),
      });
      res.end();
      return;
    }

    // Bot replies are sent server-to-server to the mocked connector service
    // and therefore do not carry the browser session cookie. The Playground
    // connector validates the Bot JWT; expose only this callback namespace.
    if (url.pathname === "/_connector" || url.pathname.startsWith("/_connector/")) {
      proxy.web(req, res);
      return;
    }

    if (!authenticated(req)) {
      res.writeHead(303, { location: "/login", ...securityHeaders() });
      res.end();
      return;
    }

    if (url.pathname === "/_knowledge-control.js" && req.method === "GET") {
      res.writeHead(200, { "content-type": "application/javascript; charset=utf-8", ...securityHeaders() });
      res.end(knowledgeControlScript());
      return;
    }

    if (url.pathname === "/api/knowledge-backend" && ["GET", "PUT"].includes(req.method)) {
      await proxyKnowledgeControl(
        req,
        res,
        knowledgeControlUrl,
        knowledgeControlToken,
        knowledgeControlAuthMode,
        knowledgeControlAudience,
      );
      return;
    }

    if (url.pathname === "/" && req.method === "GET") {
      await proxyIndex(res, target);
      return;
    }

    proxy.web(req, res);
  });

  server.on("upgrade", (req, socket, head) => {
    if (!authenticated(req)) {
      socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
      socket.destroy();
      return;
    }
    proxy.ws(req, socket, head);
  });

  return server;
}

function start() {
  const password = requiredEnv("PLAYGROUND_PASSWORD");
  const sessionSecret = requiredEnv("SESSION_SECRET");
  requiredEnv("BOT_ENDPOINT");
  const publicBaseUrl = requiredEnv("PLAYGROUND_PUBLIC_BASE_URL").replace(/\/$/, "");
  const isLocal = /^http:\/\/(localhost|127\.0\.0\.1)(:|$)/.test(publicBaseUrl);
  if (!isLocal) {
    requiredEnv("AUTH_CLIENT_ID");
    requiredEnv("AUTH_CLIENT_SECRET");
    requiredEnv("AUTH_TENANT_ID");
  }

  const internalPort = Number(process.env.PLAYGROUND_INTERNAL_PORT || 56150);
  const playgroundBinary = path.join(__dirname, "node_modules", ".bin", "agentsplayground");
  const child = spawn(
    playgroundBinary,
    [
      "--port",
      String(internalPort),
      "--service-url",
      `${publicBaseUrl}/_connector`,
      "--disable-telemetry",
    ],
    {
    env: {
      ...process.env,
      // This package uses its legacy environment name to suppress launching a
      // desktop browser. Cloud Run containers do not include xdg-open.
      TEAMSAPPTESTER_BROWSER: "none",
      DEFAULT_CHANNEL_ID: process.env.DEFAULT_CHANNEL_ID || "msteams",
    },
      stdio: "inherit",
    },
  );

  child.on("exit", (code, signal) => {
    console.error(`Agents Playground exited (code=${code}, signal=${signal})`);
    process.exit(code || 1);
  });

  const port = Number(process.env.PORT || 8080);
  const server = createGateway({
    password,
    sessionSecret,
    target: `http://127.0.0.1:${internalPort}`,
    knowledgeControlUrl: process.env.KNOWLEDGE_CONTROL_URL,
    knowledgeControlToken: process.env.KNOWLEDGE_CONTROL_TOKEN,
    knowledgeControlAuthMode: process.env.KNOWLEDGE_CONTROL_AUTH_MODE || "none",
    knowledgeControlAudience: process.env.KNOWLEDGE_CONTROL_AUDIENCE,
    secureCookie: publicBaseUrl.startsWith("https://"),
  });
  server.listen(port, "0.0.0.0", () => console.log(`Password gateway listening on 0.0.0.0:${port}`));

  const shutdown = () => {
    server.close(() => process.exit(0));
    child.kill("SIGTERM");
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

if (require.main === module) start();

module.exports = { createGateway, parseCookies, safeEqual, signSession, verifySession };
