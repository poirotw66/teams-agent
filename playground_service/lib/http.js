"use strict";

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
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

function clientAddress(req) {
  const forwarded = req.headers["x-forwarded-for"];
  return (typeof forwarded === "string" ? forwarded.split(",")[0].trim() : "") || req.socket.remoteAddress || "unknown";
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

module.exports = {
  requiredEnv,
  securityHeaders,
  clientAddress,
  readForm,
  readJson,
};
