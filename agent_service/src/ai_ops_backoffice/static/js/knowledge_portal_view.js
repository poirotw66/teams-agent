/**
 * Native Knowledge Portal Component for AI Operations Console.
 * Directly mounts knowledge portal views into the Ops Console DOM without iframes.
 */

import { loadFluentComponents } from "/static/kp/js/fluent.js";
import { setCustomNavigator } from "/static/kp/js/router.js";
import { installBeforeUnloadGuard } from "/static/kp/js/dirty-state.js";
import { renderKnowledgeListView } from "/static/kp/js/views/knowledge-list.js";
import { renderDocumentDetailView } from "/static/kp/js/views/document-detail.js";
import { renderCreateView } from "/static/kp/js/views/create.js";
import { renderReviewsView } from "/static/kp/js/views/reviews.js";
import { renderReleasesView } from "/static/kp/js/views/releases.js";
import { renderAuditView } from "/static/kp/js/views/audit.js";
import { renderWorkView } from "/static/kp/js/views/work.js";
import { updateSession } from "/static/kp/js/session.js";
import { el } from "./api.js";

function portalCapabilities(knowledgeCaps) {
  const set = new Set(knowledgeCaps || []);
  return {
    create_document: set.has("knowledge.create"),
    import_markdown: set.has("knowledge.create"),
    list_pending_reviews: set.has("knowledge.review"),
    decide_review: set.has("knowledge.review"),
    publish: set.has("knowledge.publish"),
    list_releases: set.has("knowledge.read"),
    manage_releases: set.has("knowledge.rollback") || set.has("knowledge.publish"),
    view_audit: set.has("knowledge.audit.read") || set.has("knowledge.read"),
  };
}

function portalRole(knowledgeCaps, backofficeRole) {
  if (backofficeRole === "SYSTEM_ADMIN") return "PLATFORM";
  const set = new Set(knowledgeCaps || []);
  if (set.has("knowledge.publish") || set.has("knowledge.review")) return "MANAGER";
  if (set.has("knowledge.review")) return "REVIEWER";
  if (set.has("knowledge.audit.read") && !set.has("knowledge.create")) return "AUDITOR";
  return "CONTRIBUTOR";
}

function visibleNav(role) {
  const nav = ["work", "knowledge"];
  if (["REVIEWER", "MANAGER", "PLATFORM"].includes(role)) nav.push("reviews");
  if (["AUDITOR", "MANAGER", "PLATFORM"].includes(role)) nav.push("audit");
  if (["MANAGER", "PLATFORM"].includes(role)) nav.push("releases");
  return nav;
}

export async function initKnowledgePortalSession(capabilities, storedAuth = {}) {
  window.__AI_OPS_KNOWLEDGE_EMBED__ = true;
  window.__AI_OPS_STATIC_PREFIX__ = "/static/kp";

  const knowledgeCaps = capabilities?.knowledgeCapabilities || [];
  const role = portalRole(knowledgeCaps, capabilities?.role);

  const relaxedWorkflow =
    capabilities?.relaxedWorkflow !== undefined
      ? Boolean(capabilities.relaxedWorkflow)
      : false;
  const minTestCasesForReview =
    typeof capabilities?.minTestCasesForReview === "number"
      ? capabilities.minTestCasesForReview
      : (relaxedWorkflow ? 0 : 3);

  const userId = capabilities?.userId || storedAuth.userId || "ops.user";
  const userName =
    capabilities?.userName ||
    capabilities?.displayName ||
    storedAuth.userName ||
    "Ops User";
  const ownerUnits =
    (capabilities?.ownerUnitIds || []).join(",") ||
    storedAuth.ownerUnits ||
    "";

  const sessionData = {
    demoMode: false,
    portalProfile: "INTEGRATED",
    relaxedWorkflow,
    minTestCasesForReview,
    homeRoute: "#/knowledge",
    visibleNav: visibleNav(role),
    userId,
    userName,
    role,
    ownerUnits,
    capabilities: portalCapabilities(knowledgeCaps),
  };
  window.__AI_OPS_EMBED_SESSION__ = sessionData;
  updateSession(sessionData);
}

/**
 * Render the Native Knowledge Portal inside the provided container.
 *
 * @param {HTMLElement} app - The main container (#app).
 * @param {Object} capabilities - Backoffice capabilities.
 * @param {Function} navigateTo - Backoffice navigateTo function.
 * @param {Object} filters - Nav filters (e.g. { sub, k, caseId, ... }).
 */
export async function renderNativeKnowledgePortal(app, capabilities, navigateTo, filters = {}) {
  // Ensure session and web components are loaded
  await loadFluentComponents();
  installBeforeUnloadGuard();
  const storedAuth = JSON.parse(sessionStorage.getItem("ai_ops_backoffice_auth") || "{}");
  await initKnowledgePortalSession(capabilities, storedAuth);

  // Hook back-to-case helper
  window.__navigateCase = (caseId) => {
    navigateTo("quality", { caseId });
  };

  // Delegate knowledge portal router.navigate() to Backoffice navigateTo()
  setCustomNavigator((targetHash) => {
    const clean = targetHash.replace(/^#\/?/, "");
    const [subPart, queryPart] = clean.split("?");
    const extra = queryPart ? Object.fromEntries(new URLSearchParams(queryPart)) : {};
    navigateTo("knowledgePortal", { sub: subPart, ...extra });
  });

  // Determine current sub-route
  const rawSub = (filters.sub || filters.k || "knowledge")
    .replace(/^#\/?/, "")
    .replace(/^\/?/, "");
  const [pathPart, queryPart = ""] = rawSub.split("?");
  const segments = pathPart.split("/").filter(Boolean);
  const query = new URLSearchParams(queryPart);
  for (const [key, value] of Object.entries(filters)) {
    if (key !== "sub" && key !== "k" && key !== "view" && !query.has(key)) {
      query.set(key, String(value));
    }
  }

  const activeSection = segments[0] || "knowledge";
  const userCaps = window.__AI_OPS_EMBED_SESSION__.capabilities;

  // Render native shell
  const shell = el("div", "kp-native-shell");

  // Subnav bar
  const subnav = el("nav", "kp-subnav");
  subnav.setAttribute("aria-label", "知識營運子導覽");

  const navItems = [
    { id: "knowledge", label: "知識文件庫", visible: true },
    { id: "reviews", label: "待審清單", visible: userCaps.list_pending_reviews },
    { id: "releases", label: "發布紀錄", visible: userCaps.list_releases },
    { id: "audit", label: "稽核紀錄", visible: userCaps.view_audit },
    { id: "work", label: "我的工作", visible: true },
  ];

  const leftNav = el("div", "kp-subnav-left");
  for (const item of navItems) {
    if (!item.visible) continue;
    const btn = el(
      "button",
      `kp-subnav-btn${activeSection === item.id ? " active" : ""}`,
      item.label,
    );
    btn.type = "button";
    btn.addEventListener("click", () => {
      navigateTo("knowledgePortal", { sub: item.id });
    });
    leftNav.append(btn);
  }
  subnav.append(leftNav);

  if (userCaps.create_document) {
    const rightActions = el("div", "kp-subnav-right");
    const newDocBtn = el("button", "button button-primary kp-subnav-action", "＋ 新增文件");
    newDocBtn.type = "button";
    newDocBtn.addEventListener("click", () => {
      navigateTo("knowledgePortal", { sub: "knowledge/new" });
    });
    rightActions.append(newDocBtn);
    subnav.append(rightActions);
  }

  // Content host
  const hostWrap = el("fluent-design-system-provider", "kp-provider");
  hostWrap.setAttribute("use-default-config", "");
  const host = el("div", "kp-native-host");
  hostWrap.append(host);

  shell.append(subnav, hostWrap);
  app.replaceChildren(shell);

  // Mount the appropriate view
  try {
    if (segments[0] === "knowledge" && segments[1] === "new") {
      await renderCreateView(host);
    } else if (segments[0] === "knowledge" && segments[1]) {
      const docId = segments[1];
      const tab = segments[2] || "overview";
      await renderDocumentDetailView(host, docId, tab, query);
    } else if (segments[0] === "knowledge") {
      await renderKnowledgeListView(host, query);
    } else if (segments[0] === "reviews") {
      await renderReviewsView(host);
    } else if (segments[0] === "releases") {
      await renderReleasesView(host);
    } else if (segments[0] === "audit") {
      await renderAuditView(host);
    } else if (segments[0] === "work") {
      await renderWorkView(host);
    } else {
      await renderKnowledgeListView(host, query);
    }
  } catch (err) {
    host.innerHTML = `<div class="error" style="padding: 1.5rem;">知識模組載入失敗：${err.message || err}</div>`;
  }
}
