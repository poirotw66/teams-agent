/**
 * Safe in-app returnTo for BU task continuity.
 * Only allowlisted views + filter keys; never encode free-text payloads.
 */

import { navigateTo, loadNavFilters } from "./navigation.js";

const ALLOWED_VIEWS = new Set([
  "workHub",
  "quality",
  "contentLists",
  "conversations",
  "evaluations",
  "overview",
  "issues",
  "routes",
  "costs",
  "knowledgePortal",
  "knowledgeWork",
  "knowledgeReviews",
  "knowledgeReleases",
  "faq",
  "examples",
  "contentHub",
]);

const ALLOWED_FILTER_KEYS = new Set([
  "tab",
  "caseId",
  "conversationId",
  "issueTypeId",
  "issueType",
  "rating",
  "preset",
  "start",
  "end",
  "documentId",
  "q",
  "sub",
  "k",
  "owner",
  "status",
  "runId",
  "turnId",
  "reason",
  "resolved",
  "handoff",
  "model",
  "route",
  "channelScope",
  "query",
  "source",
  "actorRef",
  "hasFeedback",
]);

function sanitizeFilters(filters = {}) {
  const safe = {};
  for (const [key, value] of Object.entries(filters || {})) {
    if (!ALLOWED_FILTER_KEYS.has(key)) continue;
    if (value == null || value === "" || value === false) continue;
    const text = String(value);
    if (text.length > 240) continue;
    if (/[\r\n]/.test(text)) continue;
    safe[key] = text;
  }
  return safe;
}

export function encodeReturnTo(view, filters = {}) {
  const resolved = String(view || "").trim();
  if (!ALLOWED_VIEWS.has(resolved)) {
    return null;
  }
  if (resolved.includes("://") || resolved.startsWith("//") || resolved.includes("..")) {
    return null;
  }
  const query = new URLSearchParams(sanitizeFilters(filters)).toString();
  return query ? `${resolved}|${query}` : resolved;
}

export function parseReturnTo(raw) {
  if (raw == null || raw === "") {
    return null;
  }
  const text = String(raw);
  if (text.length > 500) {
    return null;
  }
  if (text.includes("://") || text.includes("..")) {
    return null;
  }
  const pipe = text.indexOf("|");
  const view = pipe >= 0 ? text.slice(0, pipe) : text;
  const query = pipe >= 0 ? text.slice(pipe + 1) : "";
  if (!ALLOWED_VIEWS.has(view)) {
    return null;
  }
  const filters = sanitizeFilters(Object.fromEntries(new URLSearchParams(query)));
  return { view, filters };
}

export function withReturnTo(filters = {}, returnView, returnFilters = {}) {
  const token = encodeReturnTo(returnView, returnFilters);
  if (!token) {
    return { ...filters };
  }
  return { ...filters, returnTo: token };
}

export function navigateReturnTo(fallbackView = "workHub", fallbackFilters = {}) {
  const nav = loadNavFilters();
  const parsed = parseReturnTo(nav.returnTo);
  if (parsed) {
    void navigateTo(parsed.view, parsed.filters);
    return true;
  }
  void navigateTo(fallbackView, fallbackFilters);
  return false;
}

export function isAllowedReturnView(view) {
  return ALLOWED_VIEWS.has(view);
}
