"use strict";

const crypto = require("node:crypto");

const SESSION_COOKIE = "playground_session";
const LOGIN_WINDOW_MS = 15 * 60 * 1000;
const MAX_LOGIN_ATTEMPTS = 5;
const attempts = new Map();

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

function isPublicAssetPath(pathname) {
  // ponytail: SPA bundles are not secret; gating them breaks boot when a browser
  // omits the session cookie on the first script request after login.
  return pathname.startsWith("/static/") || pathname === "/favicon.ico";
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

function clearLoginAttempts(address) {
  attempts.delete(address);
}

function buildSessionCookie(token, secureCookie) {
  return `${SESSION_COOKIE}=${encodeURIComponent(token)}; Path=/; Max-Age=28800; HttpOnly;${secureCookie ? " Secure;" : ""} SameSite=Lax`;
}

function clearSessionCookie(secureCookie) {
  return `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly;${secureCookie ? " Secure;" : ""} SameSite=Lax`;
}

function rotateSessionCookie(req, state, sessionSecret, secureCookie) {
  const oldToken = parseCookies(req.headers.cookie)[SESSION_COOKIE];
  const backend = oldToken ? state.sessionBackends.get(oldToken) : undefined;
  const playgroundSessionId =
    (oldToken ? state.sessionPlaygroundIds.get(oldToken) : undefined) ||
    state.playgroundSessionId;
  const token = signSession(sessionSecret);
  if (backend) {
    state.sessionBackends.set(token, backend);
  }
  if (playgroundSessionId) {
    state.sessionPlaygroundIds.set(token, playgroundSessionId);
  }
  if (oldToken) {
    state.sessionBackends.delete(oldToken);
    state.sessionPlaygroundIds.delete(oldToken);
  }
  return buildSessionCookie(token, secureCookie);
}

function resolvePlaygroundSessionId(req, state) {
  const token = parseCookies(req.headers.cookie)[SESSION_COOKIE];
  if (token && state.sessionPlaygroundIds.has(token)) {
    return state.sessionPlaygroundIds.get(token);
  }
  // Bot→adapter traffic has no cookie; reuse the process-wide session.
  return state.playgroundSessionId;
}

function rotatePlaygroundSessionId(req, state) {
  const sessionId = crypto.randomUUID();
  state.playgroundSessionId = sessionId;
  const token = parseCookies(req.headers.cookie)[SESSION_COOKIE];
  if (token) {
    state.sessionPlaygroundIds.set(token, sessionId);
  }
  return sessionId;
}

function isAuthenticated(req, sessionSecret) {
  const token = parseCookies(req.headers.cookie)[SESSION_COOKIE];
  return verifySession(token, sessionSecret);
}

module.exports = {
  SESSION_COOKIE,
  attempts,
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
  rotateSessionCookie,
  resolvePlaygroundSessionId,
  rotatePlaygroundSessionId,
  isAuthenticated,
};
