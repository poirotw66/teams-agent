"use strict";

const ASSET_PREFIXES = [
  "/rag-sources/",
  "/rag-assets/",
  "/rag-originals/",
  "/rag-citations/",
];
const MAX_BODY_BYTES = 2 * 1024 * 1024;
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
]);
const PASSTHROUGH_RESPONSE_HEADERS = [
  "content-type",
  "content-length",
  "content-range",
  "accept-ranges",
  "content-disposition",
  "cache-control",
  "etag",
  "last-modified",
  "location",
];

function adapterOrigin(adapterTarget) {
  const value = String(adapterTarget || "").replace(/\/$/, "");
  if (!value) return "";
  try {
    return new URL(value).origin;
  } catch (_error) {
    return "";
  }
}

function isSourceAssetPath(pathname) {
  return ASSET_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function rewriteAdapterAssetUrls(text, adapterTarget) {
  const adapter = adapterOrigin(adapterTarget);
  if (!text || !adapter) return text;
  // Image URLs stay on the public adapter. Rewriting them onto a playground
  // hostname drops the session cookie and the picture fails to load.
  // Source links become root-relative so they open on whichever hostname the
  // tester is actually viewing.
  let rewritten = text;
  for (const prefix of ["/rag-sources/", "/rag-originals/", "/rag-citations/"]) {
    rewritten = rewritten
      .split(`${adapter}${prefix}`).join(prefix)
      .split(`${adapter}${prefix}`.replaceAll("/", "\\/")).join(prefix.replaceAll("/", "\\/"));
  }
  return rewritten;
}

function linkOpenerScript() {
  return `"use strict";
(function () {
  const prefixes = ["/rag-sources/", "/rag-assets/", "/rag-originals/", "/rag-citations/"];
  function assetUrl(raw) {
    if (!raw) return null;
    let url;
    try { url = new URL(raw, window.location.href); } catch (_error) { return null; }
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (!prefixes.some(function (prefix) { return url.pathname.startsWith(prefix); })) return null;
    return window.location.origin + url.pathname + url.search + url.hash;
  }
  function retarget(node) {
    if (!node || node.nodeType !== 1) return;
    const anchors = node.matches && node.matches("a[href]") ? [node] : [];
    if (node.querySelectorAll) anchors.push.apply(anchors, node.querySelectorAll("a[href]"));
    anchors.forEach(function (anchor) {
      const next = assetUrl(anchor.getAttribute("href"));
      if (!next || anchor.getAttribute("href") === next) return;
      anchor.setAttribute("href", next);
      anchor.setAttribute("target", "_blank");
      anchor.setAttribute("rel", "noopener noreferrer");
    });
  }
  const nativeOpen = window.open.bind(window);
  window.open = function (url, target, features) {
    if (typeof url !== "string" || !url) return nativeOpen(url, target, features);
    const next = assetUrl(url);
    if (!next) return nativeOpen(url, target, features);
    return nativeOpen(next, target || "_blank", features || "noopener,noreferrer");
  };
  document.addEventListener("click", function (event) {
    const anchor = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!anchor) return;
    const next = assetUrl(anchor.getAttribute("href"));
    if (!next) return;
    event.preventDefault();
    event.stopPropagation();
    window.open(next, "_blank", "noopener,noreferrer");
  }, true);
  function start() {
    retarget(document.body);
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        retarget(record.target);
        record.addedNodes.forEach(retarget);
      });
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
  }
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);
})();`;
}

async function readLimitedBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > MAX_BODY_BYTES) {
      const error = new Error("Request body too large");
      error.statusCode = 413;
      throw error;
    }
    chunks.push(buffer);
  }
  return Buffer.concat(chunks);
}

function collectPassthroughHeaders(response) {
  const headers = {
    "x-content-type-options": "nosniff",
  };
  for (const name of PASSTHROUGH_RESPONSE_HEADERS) {
    const value = response.headers.get(name);
    if (value) headers[name] = value;
  }
  if (!headers["cache-control"]) {
    headers["cache-control"] = "private, no-store";
  }
  if (!headers["content-type"]) {
    headers["content-type"] = "application/octet-stream";
  }
  return headers;
}

async function proxyConnector(req, res, playgroundTarget, adapterTarget, publicBaseUrl) {
  const destination = `${playgroundTarget.replace(/\/$/, "")}${req.url}`;
  const headers = {};
  for (const name of ["authorization", "content-type", "accept"]) {
    if (typeof req.headers[name] === "string" && req.headers[name]) headers[name] = req.headers[name];
  }
  let body;
  if (req.method !== "GET" && req.method !== "HEAD") {
    const raw = await readLimitedBody(req);
    const type = String(req.headers["content-type"] || "");
    const text = raw.toString("utf8");
    const looksRewritable = type.includes("json") || type.includes("text") || text.startsWith("{") || text.startsWith("[");
    body = looksRewritable
      ? Buffer.from(rewriteAdapterAssetUrls(text, adapterTarget))
      : raw;
  }
  const response = await fetch(destination, {
    method: req.method,
    headers,
    body,
    redirect: "manual",
    signal: AbortSignal.timeout(30000),
  });
  const responseBody = Buffer.from(await response.arrayBuffer());
  const responseHeaders = {
    "content-type": response.headers.get("content-type") || "application/json; charset=utf-8",
  };
  const location = response.headers.get("location");
  if (location) responseHeaders.location = location;
  res.writeHead(response.status, responseHeaders);
  if (req.method === "HEAD") res.end();
  else res.end(responseBody);
}

async function proxySourceAsset(req, res, adapterTarget, gatewaySecret) {
  const incoming = new URL(req.url, "http://gateway.local");
  if (req.method !== "GET" && req.method !== "HEAD") {
    res.writeHead(405, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
    res.end("Method Not Allowed\n");
    return;
  }
  const destination = `${adapterTarget.replace(/\/$/, "")}${incoming.pathname}${incoming.search}`;
  const headers = { accept: req.headers.accept || "*/*" };
  if (typeof req.headers.range === "string" && req.headers.range) {
    headers.range = req.headers.range;
  }
  const subject = incoming.searchParams.get("subject");
  if (gatewaySecret && subject) {
    headers["x-viewer-subject"] = subject;
    headers["x-gateway-secret"] = gatewaySecret;
  }
  const response = await fetch(destination, {
    method: req.method,
    headers,
    redirect: "manual",
    signal: AbortSignal.timeout(20000),
  });
  const responseHeaders = collectPassthroughHeaders(response);
  for (const name of Object.keys(responseHeaders)) {
    if (HOP_BY_HOP.has(name.toLowerCase())) {
      delete responseHeaders[name];
    }
  }
  res.writeHead(response.status, responseHeaders);
  if (req.method === "HEAD" || !response.body) {
    res.end();
    return;
  }
  const reader = response.body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!res.write(Buffer.from(value))) {
        await new Promise((resolve) => res.once("drain", resolve));
      }
    }
    res.end();
  } catch (error) {
    try {
      await reader.cancel();
    } catch (_cancelError) {
      // Best-effort cancel when the client aborts mid-stream.
    }
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
    }
    res.end();
    throw error;
  }
}

module.exports = {
  adapterOrigin,
  isSourceAssetPath,
  linkOpenerScript,
  proxyConnector,
  proxySourceAsset,
  rewriteAdapterAssetUrls,
};
