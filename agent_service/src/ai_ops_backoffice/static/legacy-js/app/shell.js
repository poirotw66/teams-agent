import { el } from "../api.js";
import {
  actorHasCapability,
} from "./capabilities.js";
import {
  WORKSPACE_KEY,
  VIEW_TITLES,
  workspaces,
} from "./workspaces.js";
import {
  activeWorkspaceId,
  bindRenderNav,
  buildLocationHash,
  clearNavFilters,
  loadNavFilters,
  navigateTo,
  syncLocationHash,
} from "./navigation.js";
import { setCurrentActiveView } from "./activeView.js";
import { leaveActivePage } from "./lifecycle.js";
import { stopConversationPolling } from "../views/conversations.js";
import { applyBuShellBodyClass, isBuShellEnabled } from "./buShellConfig.js";

let routesRef = null;
let lifecycleViewsRef = null;
let buNavRenderer = null;

export function bindShellRoutes({ routes, lifecycleViews }) {
  routesRef = routes;
  lifecycleViewsRef = lifecycleViews;
}

/** Register BU shell renderer from main.js (avoids shell↔buShell static cycle). */
export function registerBuNavRenderer(renderer) {
  buNavRenderer = renderer;
}

export function getShellRouteRefs() {
  return { routes: routesRef, lifecycleViews: lifecycleViewsRef };
}

export function visibleWorkspaces() {
  return workspaces
    .map((workspace) => ({
      ...workspace,
      items: workspace.items.filter(([, , capability]) => actorHasCapability(capability)),
    }))
    .filter((workspace) => workspace.items.length > 0);
}

export function firstVisibleView(workspaceId) {
  const workspace = visibleWorkspaces().find((item) => item.id === workspaceId);
  return workspace?.items[0]?.[0] || null;
}

export function renderNav(active, options = {}) {
  if (isBuShellEnabled() && typeof buNavRenderer === "function") {
    buNavRenderer(active, options, getShellRouteRefs());
    return;
  }
  applyBuShellBodyClass(false);
  setCurrentActiveView(active);
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  const visible = visibleWorkspaces();
  const storedRoute = loadNavFilters();
  const routeState = storedRoute.view === active ? storedRoute : {};
  let workspaceId = activeWorkspaceId();
  if (!visible.some((item) => item.id === workspaceId)) {
    workspaceId = visible[0]?.id || "platform";
    sessionStorage.setItem(WORKSPACE_KEY, workspaceId);
  }
  const workspace = visible.find((item) => item.id === workspaceId) || visible[0];

  const switcher = el("div", "workspace-switcher");
  for (const item of visible) {
    const button = el("button", item.id === workspaceId ? "workspace active" : "workspace", item.label);
    button.type = "button";
    button.title = item.hint;
    button.addEventListener("click", () => {
      const preferred = item.items[0]?.[0] || "overview";
      const nextView = item.items.some(([id]) => id === preferred)
        ? preferred
        : item.items[0]?.[0] || "overview";
      navigateTo(nextView, {}, { workspace: item.id });
    });
    switcher.append(button);
  }
  nav.append(switcher);

  if (workspace?.hint) {
    nav.append(el("p", "workspace-hint", workspace.hint));
  }

  const itemRow = el("div", "nav-items");
  for (const [id, label, capability] of workspace?.items || []) {
    if (!actorHasCapability(capability)) {
      continue;
    }
    const button = el("a", active === id ? "active" : "", label);
    button.href = buildLocationHash(workspaceId, id);
    if (active === id) button.setAttribute("aria-current", "page");
    button.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
        return;
      }
      event.preventDefault();
      clearNavFilters();
      navigateTo(id);
    });
    itemRow.append(button);
  }
  nav.append(itemRow);

  document.body.classList.toggle("view-knowledge-portal", ["knowledgePortal", "knowledgeWork", "knowledgeReviews", "knowledgeReleases", "knowledgeAudit"].includes(active));
  const title = VIEW_TITLES[active] || active;
  document.title = `${title}｜AI 資訊客服營運後台`;

  if (!options.skipHashSync) {
    const { view: _view, ...filters } = routeState;
    syncLocationHash(active, filters);
  }

  if (active !== "conversations") {
    stopConversationPolling();
  }
  if (!lifecycleViewsRef.has(active)) {
    void leaveActivePage();
  }

  if (typeof routesRef[active] === "function") {
    routesRef[active](routeState);
  } else if (workspace?.items[0]) {
    routesRef[workspace.items[0][0]]({});
  }
}

bindRenderNav(renderNav);
