"use strict";

const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");
const httpProxy = require("http-proxy");

const {
  safeEqual,
  signSession,
  verifySession,
  parseCookies,
  isPublicAssetPath,
  isRateLimited,
  recordFailure,
  clearLoginAttempts,
  buildSessionCookie,
  clearSessionCookie,
  isAuthenticated,
  resolvePlaygroundSessionId,
} = require("./lib/auth");
const { requiredEnv, securityHeaders, clientAddress, readForm } = require("./lib/http");
const { loginPage, knowledgeControlScript, proxyIndex } = require("./lib/pages");
const {
  createKnowledgeBackendState,
  buildKnowledgeBackendStatus,
  handleKnowledgeBackendRequest,
  injectPlaygroundEvaluation,
  proxyKnowledgeControl,
  resolveEvaluationBackend,
} = require("./lib/knowledge-control");
const {
  resetPlaygroundConversation,
  handleNewConversationRequest,
  proxyAdapterMessages,
} = require("./lib/proxy");

function createGateway({
  password,
  sessionSecret,
  target = "http://127.0.0.1:56150",
  adapterTarget = null,
  geminiFileSearchAvailable = true,
  geminiFileSearchReason = "GEMINI_FILE_SEARCH_STORE 尚未設定",
  knowledgeControlUrl,
  knowledgeControlToken,
  knowledgeControlAuthMode = "none",
  knowledgeControlAudience,
  secureCookie = true,
}) {
  const proxy = httpProxy.createProxyServer({ target, ws: true, xfwd: true, changeOrigin: true });
  const knowledgeState = createKnowledgeBackendState({
    geminiAvailable: geminiFileSearchAvailable,
    geminiReason: geminiFileSearchAvailable ? null : geminiFileSearchReason,
  });
  proxy.on("error", (_error, _req, res) => {
    if (res && !res.headersSent) {
      res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      res.end("Agents Playground 尚未就緒，請稍後重試。\n");
    }
  });

  const authenticated = (req) => isAuthenticated(req, sessionSecret);

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
        clearLoginAttempts(address);
        const token = signSession(sessionSecret);
        res.writeHead(303, {
          location: "/",
          "set-cookie": buildSessionCookie(token, secureCookie),
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
        "set-cookie": clearSessionCookie(secureCookie),
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

    if (url.pathname === "/_adapter/api/messages") {
      // agentsplayground uses wait-on against BOT_ENDPOINT with GET; only POST
      // carries Bot Framework activities and needs the adapter proxy.
      if (req.method === "GET" || req.method === "HEAD") {
        res.writeHead(200, { "content-type": "application/json", ...securityHeaders() });
        if (req.method !== "HEAD") res.end('{"status":"ok"}\n');
        else res.end();
        return;
      }
      if (req.method === "POST") {
        await proxyAdapterMessages(
          req,
          res,
          adapterTarget,
          resolveEvaluationBackend(req, knowledgeState),
          resolvePlaygroundSessionId(req, knowledgeState),
        );
        return;
      }
      res.writeHead(405, { "content-type": "text/plain; charset=utf-8", ...securityHeaders() });
      res.end("Method Not Allowed\n");
      return;
    }

    if (isPublicAssetPath(url.pathname)) {
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
      if (knowledgeControlUrl) {
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
      await handleKnowledgeBackendRequest(req, res, knowledgeState);
      return;
    }

    if (url.pathname === "/api/new-conversation" && req.method === "POST") {
      await handleNewConversationRequest(
        req,
        res,
        knowledgeState,
        sessionSecret,
        secureCookie,
        target,
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
  const publicBaseUrl = requiredEnv("PLAYGROUND_PUBLIC_BASE_URL").replace(/\/$/, "");
  const adapterTarget =
    process.env.ADAPTER_TARGET_URL ||
    (process.env.BOT_ENDPOINT || "").replace(/\/api\/messages\/?$/, "") ||
    null;
  if (!adapterTarget) {
    throw new Error("Missing ADAPTER_TARGET_URL (or BOT_ENDPOINT ending in /api/messages)");
  }
  const isLocal = /^http:\/\/(localhost|127\.0\.0\.1)(:|$)/.test(publicBaseUrl);
  if (!isLocal) {
    requiredEnv("AUTH_CLIENT_ID");
    requiredEnv("AUTH_CLIENT_SECRET");
    requiredEnv("AUTH_TENANT_ID");
  }

  const internalPort = Number(process.env.PLAYGROUND_INTERNAL_PORT || 56150);
  const playgroundBinary = path.join(__dirname, "node_modules", ".bin", "agentsplayground");
  const botEndpoint = `${publicBaseUrl}/_adapter/api/messages`;
  const port = Number(process.env.PORT || 8080);
  const server = createGateway({
    password,
    sessionSecret,
    target: `http://127.0.0.1:${internalPort}`,
    adapterTarget,
    geminiFileSearchAvailable: process.env.GEMINI_FILE_SEARCH_AVAILABLE !== "false",
    knowledgeControlUrl: process.env.KNOWLEDGE_CONTROL_URL,
    knowledgeControlToken: process.env.KNOWLEDGE_CONTROL_TOKEN,
    knowledgeControlAuthMode: process.env.KNOWLEDGE_CONTROL_AUTH_MODE || "none",
    knowledgeControlAudience: process.env.KNOWLEDGE_CONTROL_AUDIENCE,
    secureCookie: publicBaseUrl.startsWith("https://"),
  });

  let child = null;
  const shutdown = () => {
    server.close(() => process.exit(0));
    if (child) child.kill("SIGTERM");
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);

  // Listen before spawning agentsplayground: its startup runs wait-on against
  // BOT_ENDPOINT (/_adapter/api/messages). If the gateway is not listening yet,
  // wait-on fails and the UI websocket never stabilizes.
  server.listen(port, "0.0.0.0", () => {
    console.log(`Password gateway listening on 0.0.0.0:${port}`);
    child = spawn(
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
          BOT_ENDPOINT: botEndpoint,
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
  });
}

if (require.main === module) start();

module.exports = {
  createGateway,
  isPublicAssetPath,
  parseCookies,
  resetPlaygroundConversation,
  safeEqual,
  signSession,
  verifySession,
  injectPlaygroundEvaluation,
  buildKnowledgeBackendStatus,
  createKnowledgeBackendState,
};
