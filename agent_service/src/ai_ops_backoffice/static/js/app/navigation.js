import { el } from "../api.js";
import {
  NAV_FILTERS_KEY,
  WORKSPACE_KEY,
  VIEW_TITLES,
  workspaces,
} from "./workspaces.js";

/** Avoid re-entrancy when we write location.hash from renderNav. */
let syncingLocationHash = false;
let knownViews = new Set();
let renderNavImpl = null;

export function isSyncingLocationHash() {
  return syncingLocationHash;
}

export function setKnownViews(views) {
  knownViews = new Set(views);
}

export function bindRenderNav(renderNav) {
  renderNavImpl = renderNav;
}

export function saveNavFilters(filters) {
  sessionStorage.setItem(NAV_FILTERS_KEY, JSON.stringify(filters));
}

export function loadNavFilters() {
  const raw = sessionStorage.getItem(NAV_FILTERS_KEY);
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export function clearNavFilters() {
  sessionStorage.removeItem(NAV_FILTERS_KEY);
}

export function workspaceForView(view) {
  for (const workspace of workspaces) {
    if (workspace.items.some(([id]) => id === view)) {
      return workspace.id;
    }
  }
  return null;
}

export function activeWorkspaceId() {
  return sessionStorage.getItem(WORKSPACE_KEY) || "knowledge_ops";
}

export function buildLocationHash(workspace, view, filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters || {})) {
    if (key === "view" || value == null || value === "" || value === false) {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return `#/${encodeURIComponent(workspace)}/${encodeURIComponent(view)}${
    query ? `?${query}` : ""
  }`;
}

export function parseLocationHash() {
  const raw = (location.hash || "").replace(/^#\/?/, "").trim();
  if (!raw) {
    return null;
  }
  const [pathPart, queryPart = ""] = raw.split("?");
  const parts = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  const filters = Object.fromEntries(new URLSearchParams(queryPart));
  if (parts.length >= 2) {
    return { workspace: parts[0], view: parts[1], filters };
  }
  if (parts.length === 1 && knownViews.has(parts[0])) {
    return {
      workspace: workspaceForView(parts[0]),
      view: parts[0],
      filters,
    };
  }
  return null;
}

export function syncLocationHash(view, filters = {}) {
  const workspace = activeWorkspaceId();
  const next = buildLocationHash(workspace, view, filters);
  if (location.hash === next) {
    return;
  }
  syncingLocationHash = true;
  location.hash = next;
  queueMicrotask(() => {
    syncingLocationHash = false;
  });
}

export function routeFiltersForHash(filters = {}) {
  const next = { ...filters };
  delete next.view;
  delete next.clear;
  return next;
}

export async function navigateTo(view, filters = {}) {
  if (typeof window.__isKnowledgeDirty === "function" && window.__isKnowledgeDirty()) {
    if (typeof window.__confirmKnowledgeDirty === "function") {
      const ok = await window.__confirmKnowledgeDirty();
      if (!ok) {
        return;
      }
      if (typeof window.__clearKnowledgeDirty === "function") {
        window.__clearKnowledgeDirty();
      }
    }
  }
  const workspace = workspaceForView(view);
  if (workspace) {
    sessionStorage.setItem(WORKSPACE_KEY, workspace);
  }
  if (filters.clear) {
    clearNavFilters();
    saveNavFilters({ view });
  } else {
    saveNavFilters({ view, ...routeFiltersForHash(filters) });
  }
  if (typeof renderNavImpl === "function") {
    renderNavImpl(view);
  }
}

export function drillLink(label, view, filters = {}) {
  const link = el("a", "drill-link", label);
  const workspace = workspaceForView(view) || activeWorkspaceId();
  link.href = buildLocationHash(workspace, view, routeFiltersForHash(filters));
  link.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
      return;
    }
    event.preventDefault();
    navigateTo(view, filters);
  });
  return link;
}

export function viewTitle(view) {
  return VIEW_TITLES[view] || view;
}
