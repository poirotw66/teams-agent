/**
 * BU AppShell rendering (flag-gated). Baseline: outputs/bu-ux-prototype-v1.
 */

import { el } from "../api.js";
import { actorHasCapability } from "./capabilities.js";
import {
  applyBuShellBodyClass,
  BU_PRIMARY_NAV,
  BU_SYSTEM_NAV,
  BU_VIEW_TITLES,
  isBuShellEnabled,
  setBuShellEnabled,
} from "./buShellConfig.js";
import {
  buildLocationHash,
  loadNavFilters,
  navigateTo,
  syncLocationHash,
  workspaceForView,
} from "./navigation.js";
import { WORKSPACE_KEY } from "./workspaces.js";
import { setCurrentActiveView } from "./activeView.js";
import { leaveActivePage } from "./lifecycle.js";
import { stopConversationPolling } from "../views/conversations.js";

function visiblePrimaryNav() {
  return BU_PRIMARY_NAV.filter(([, , capability]) => actorHasCapability(capability));
}

function visibleSystemNav() {
  return BU_SYSTEM_NAV.filter(([, , capability]) => actorHasCapability(capability));
}

function ensureWorkspaceForView(viewId) {
  const workspace = workspaceForView(viewId);
  if (workspace) {
    sessionStorage.setItem(WORKSPACE_KEY, workspace);
  }
  return workspace || sessionStorage.getItem(WORKSPACE_KEY) || "knowledge_ops";
}

function appendNavLink(container, viewId, label, active) {
  const link = el("a", active === viewId ? "active" : "", label);
  if (!link.dataset) {
    link.dataset = {};
  }
  link.dataset.viewId = viewId;
  const workspace = ensureWorkspaceForView(viewId);
  link.href = buildLocationHash(workspace, viewId);
  if (active === viewId) {
    link.setAttribute("aria-current", "page");
  }
  link.addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
      return;
    }
    event.preventDefault();
    ensureWorkspaceForView(viewId);
    navigateTo(viewId, {}, { workspace: workspaceForView(viewId) || undefined });
  });
  container.append(link);
}

/**
 * Render the BU left-rail shell and invoke the active route.
 */
export function renderBuNav(active, options = {}, routeRefs = {}) {
  const routesRef = routeRefs.routes || null;
  const lifecycleViewsRef = routeRefs.lifecycleViews || null;
  const storedRoute = loadNavFilters();
  const routeState = storedRoute.view === active ? storedRoute : {};
  applyBuShellBodyClass(true);
  setCurrentActiveView(active);
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  nav.setAttribute("aria-label", "主要導覽");

  const primary = el("div", "bu-nav-primary");
  const caption = el("div", "bu-nav-caption", "日常營運");
  primary.append(caption);
  const primaryList = el("div", "bu-nav-items");
  for (const [id, label] of visiblePrimaryNav()) {
    appendNavLink(primaryList, id, label, active);
  }
  primary.append(primaryList);
  nav.append(primary);

  const systemItems = visibleSystemNav();
  if (systemItems.length) {
    const system = el("details", "bu-nav-system");
    const summary = document.createElement("summary");
    summary.textContent = "系統管理";
    system.append(summary);
    const systemList = el("div", "bu-nav-items");
    for (const [id, label] of systemItems) {
      appendNavLink(systemList, id, label, active);
    }
    system.append(systemList);
    if (systemItems.some(([id]) => id === active)) {
      system.open = true;
    }
    nav.append(system);
  }

  const foot = el("div", "bu-nav-foot");
  foot.append(
    el("p", "bu-nav-note", "從問題到改善：查證回答、修正內容、驗證成效。"),
  );
  nav.append(foot);

  document.body.classList.toggle(
    "view-knowledge-portal",
    ["knowledgePortal", "knowledgeWork", "knowledgeReviews", "knowledgeReleases", "knowledgeAudit"].includes(active),
  );

  const title = BU_VIEW_TITLES[active] || active;
  document.title = `${title}｜資訊客服營運工作台`;

  if (!options.skipHashSync) {
    const { view: _view, ...filters } = routeState;
    ensureWorkspaceForView(active);
    syncLocationHash(active, filters);
  }

  if (active !== "conversations") {
    stopConversationPolling();
  }
  if (lifecycleViewsRef && !lifecycleViewsRef.has(active)) {
    void leaveActivePage();
  }

  if (typeof routesRef?.[active] === "function") {
    routesRef[active](routeState);
  } else {
    const fallback = visiblePrimaryNav()[0]?.[0];
    if (fallback && typeof routesRef?.[fallback] === "function") {
      routesRef[fallback]({});
    }
  }
}

/** Topbar control to toggle shell for local U1 validation. */
export function mountBuShellToggle(metaPanel, options = {}) {
  if (!metaPanel) {
    return;
  }
  const enabled = isBuShellEnabled();
  const button = el("button", "topbar-action bu-shell-toggle", enabled ? "經典介面" : "新介面");
  button.type = "button";
  button.title = enabled
    ? "切換回三工作區經典導覽"
    : "切換至 BU 任務導向新殼層（本機偏好）";
  button.addEventListener("click", () => {
    setBuShellEnabled(!isBuShellEnabled());
    location.reload();
  });
  if (options.prepend === false) {
    metaPanel.append(button);
  } else {
    metaPanel.prepend(button);
  }
}
