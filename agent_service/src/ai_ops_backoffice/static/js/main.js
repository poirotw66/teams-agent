import {
  api,
  el,
  metric,
  ensureAuth,
  authHeaders,
  saveAuthHeaders,
  loadAuthHeaders,
  clearAuthHeaders,
  logout,
  getTokenExpiryDetails,
  showEntraLoginModal,
} from "./api.js";
import { renderNativeKnowledgePortal } from "./knowledge_portal_view.js";

const routes = {
  overview: renderOverview,
  conversations: renderConversations,
  issues: renderIssues,
  routes: renderRoutes,
  costs: renderCosts,
  budgets: renderBudgets,
  health: renderHealth,
  knowledge: renderKnowledge,
  knowledgeDocument: renderKnowledgeDocument,
  knowledgePortal: renderKnowledgePortalEntry,
  examples: renderExamples,
  quality: renderQuality,
  prompts: renderPrompts,
  models: renderModels,
  flags: renderFlags,
  roles: renderRoles,
  retention: renderRetention,
  masking: renderMasking,
  search: renderGovernanceSearch,
  audit: renderAudit,
};

/** Role workspaces focused on completing work, not module catalogs. */
const workspaces = [
  {
    id: "knowledge_ops",
    label: "知識營運",
    hint: "待辦 → 知識文件庫 → 審核發布 → 驗證 → 結案",
    items: [
      ["quality", "我的待辦／品質案件", "ops.feedback.read"],
      ["knowledgePortal", "知識文件庫", "knowledge.ui"],
      ["knowledge", "FAQ／成效", "ops.knowledge.read"],
      ["examples", "案例集驗證", "ops.examples.read"],
      ["conversations", "回答驗證", "ops.conversations.read"],
    ],
  },
  {
    id: "ai_ops",
    label: "AI 管理",
    hint: "資料集、評測、Prompt、模型與發布",
    items: [
      ["examples", "資料集／案例", "ops.examples.read"],
      ["prompts", "Prompt 與評測", "ops.prompts.read"],
      ["models", "模型設定", "ops.models.read"],
      ["flags", "Feature Flag", "ops.flags.read"],
    ],
  },
  {
    id: "platform",
    label: "平台管理",
    hint: "權限、背景工作、稽核、保存與告警",
    items: [
      ["overview", "營運總覽", "ops.summary.read"],
      ["issues", "Issue 分析", "ops.issues.read"],
      ["routes", "路由來源", "ops.issues.read"],
      ["costs", "成本分析", "ops.cost.read"],
      ["budgets", "預算與告警", "ops.budget.read"],
      ["health", "系統健康度", "ops.health.read"],
      ["roles", "權限／角色", "ops.roles.read"],
      ["retention", "保存政策", "ops.retention.read"],
      ["masking", "遮罩政策", "ops.retention.read"],
      ["search", "全域搜尋", "ops.search.read"],
      ["audit", "稽核紀錄", "ops.audit.read"],
    ],
  },
];

const ROLE_DEFAULT_WORKSPACE = {
  KNOWLEDGE_ADMIN: "knowledge_ops",
  SERVICE_OWNER: "knowledge_ops",
  AI_ADMIN: "ai_ops",
  SYSTEM_ADMIN: "platform",
  ANALYST: "platform",
  AUDITOR: "platform",
};

const NAV_FILTERS_KEY = "ai_ops_nav_filters";
const WORKSPACE_KEY = "ai_ops_active_workspace";

/** Avoid re-entrancy when we write location.hash from renderNav. */
let syncingLocationHash = false;

const VIEW_TITLES = Object.fromEntries(
  workspaces.flatMap((workspace) =>
    workspace.items.map(([id, label]) => [id, label]),
  ),
);

function saveNavFilters(filters) {
  sessionStorage.setItem(NAV_FILTERS_KEY, JSON.stringify(filters));
}

function loadNavFilters() {
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

function clearNavFilters() {
  sessionStorage.removeItem(NAV_FILTERS_KEY);
}

function workspaceForView(view) {
  for (const workspace of workspaces) {
    if (workspace.items.some(([id]) => id === view)) {
      return workspace.id;
    }
  }
  return null;
}

function buildLocationHash(workspace, view, filters = {}) {
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

function parseLocationHash() {
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
  if (parts.length === 1 && routes[parts[0]]) {
    return {
      workspace: workspaceForView(parts[0]),
      view: parts[0],
      filters,
    };
  }
  return null;
}

function syncLocationHash(view, filters = {}) {
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

function routeFiltersForHash(filters = {}) {
  const next = { ...filters };
  delete next.view;
  delete next.clear;
  return next;
}

async function navigateTo(view, filters = {}) {
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
  renderNav(view);
}

function drillLink(label, view, filters = {}) {
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

function periodSelect(current = "7d") {
  const select = el("select", "");
  select.innerHTML = `
    <option value="today">今天</option>
    <option value="7d">最近 7 天</option>
    <option value="30d">最近 30 天</option>
    <option value="month">本月</option>
    <option value="6m">最近 6 個月</option>
    <option value="1y">最近 1 年</option>
    <option value="custom">自訂期間</option>
  `;
  select.value = current;
  return select;
}

function intervalSelect(current = "DAY") {
  const select = el("select", "");
  select.innerHTML = `
    <option value="DAY">依日</option>
    <option value="WEEK">依週</option>
    <option value="MONTH">依月</option>
  `;
  select.value = ["DAY", "WEEK", "MONTH"].includes(current) ? current : "DAY";
  select.setAttribute("aria-label", "趨勢粒度");
  return select;
}

function formatLocalClock(isoValue, timeZone = "Asia/Taipei") {
  if (!isoValue) return "-";
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString("zh-TW", {
    timeZone,
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function customPeriodInputs(startValue = "", endValue = "") {
  const wrap = el("div", "filter-bar");
  const start = el("input");
  start.type = "date";
  start.id = "custom-start-date";
  start.value = startValue;
  const end = el("input");
  end.type = "date";
  end.id = "custom-end-date";
  end.value = endValue;
  wrap.append(el("label", "", "開始"), start, el("label", "", "結束"), end);
  return wrap;
}

function buildPeriodQuery(prefix = "", period = null) {
  if (period) {
    return periodParams(period).toString();
  }
  const presetEl = document.getElementById(`${prefix}overview-preset`);
  const preset = presetEl?.value || currentOverviewPreset || "7d";
  if (preset === "custom") {
    const start = document.getElementById(`${prefix}custom-start-date`)?.value;
    const end = document.getElementById(`${prefix}custom-end-date`)?.value;
    return periodParams({ preset, start, end }).toString();
  }
  return periodParams({ preset }).toString();
}

function periodParams(state = { preset: "30d" }) {
  const params = new URLSearchParams();
  if (state.preset === "custom") {
    if (state.start) params.set("start_date", `${state.start}T00:00:00+08:00`);
    if (state.end) params.set("end_date", `${state.end}T23:59:59+08:00`);
  } else {
    params.set("preset", state.preset || "30d");
  }
  return params;
}

function createPeriodControls(state, onApply) {
  const controls = el("div", "filter-bar");
  const select = periodSelect(state.preset || "30d");
  select.setAttribute("aria-label", "分析期間");
  const custom = customPeriodInputs(state.start || "", state.end || "");
  custom.hidden = select.value !== "custom";
  select.addEventListener("change", () => {
    custom.hidden = select.value !== "custom";
  });
  const apply = el("button", "", "套用期間");
  apply.addEventListener("click", () => {
    const inputs = custom.querySelectorAll("input");
    onApply({
      preset: select.value,
      start: inputs[0]?.value || "",
      end: inputs[1]?.value || "",
    });
  });
  controls.append(select, custom, apply);
  return controls;
}

function attributionText(attribution = {}) {
  const labels = {
    faqKeys: "FAQ",
    documentIds: "Document",
    versionIds: "Version",
    releaseIds: "Release",
  };
  const parts = [];
  for (const [key, label] of Object.entries(labels)) {
    const values = (attribution[key] || []).map((item) => `${item.id} (${item.count})`);
    if (values.length) parts.push(`${label}: ${values.join(", ")}`);
  }
  return parts.join(" | ") || "-";
}

function badge(text, variant = "neutral") {
  return el("span", `badge badge-${variant}`, String(text ?? ""));
}

function statusBadge(status) {
  const s = String(status || "").toUpperCase();
  let variant = "neutral";
  if (["ACTIVE", "APPROVED", "RESOLVED", "OK", "HEALTHY", "ENABLED", "SUCCESS", "TRUE"].includes(s)) {
    variant = "success";
  } else if (["REQUESTED", "CANDIDATE", "OBSERVING", "IN_PROGRESS", "TRIAGED", "WAITING_REVIEW", "DEGRADED", "WARNING"].includes(s)) {
    variant = "warning";
  } else if (["FAILED", "ERROR", "CRITICAL", "REJECTED", "WONT_FIX", "LOCKED", "YES"].includes(s)) {
    variant = "danger";
  } else if (["NEW", "DISABLED", "DUPLICATE", "FALSE", "UNLOCKED", "NO"].includes(s)) {
    variant = "neutral";
  }
  return badge(status, variant);
}

function showContentModal(title, content) {
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  root.onclick = (e) => {
    if (e.target === root) {
      root.hidden = true;
      root.replaceChildren();
    }
  };
  const modal = el("section", "modal");
  const header = el("div", "modal-header");
  header.style.display = "flex";
  header.style.justifyContent = "space-between";
  header.style.alignItems = "center";
  header.style.marginBottom = "1rem";
  header.style.paddingBottom = "0.75rem";
  header.style.borderBottom = "1px solid var(--border-subtle, #e2e8f0)";

  const heading = el("h2", "", title);
  heading.style.margin = "0";

  const close = el("button", "btn-modal-close", "✕ 關閉");
  close.addEventListener("click", () => {
    root.hidden = true;
    root.replaceChildren();
  });
  header.append(heading, close);
  modal.append(header, content);
  root.append(modal);
}

function showConversationModal(detail, conversationId = detail.conversationId) {
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  root.onclick = (e) => {
    if (e.target === root) {
      root.hidden = true;
      root.replaceChildren();
    }
  };
  const modal = el("section", "modal");
  const header = el("div", "modal-header");
  header.style.display = "flex";
  header.style.justifyContent = "space-between";
  header.style.alignItems = "center";
  header.style.marginBottom = "1rem";
  header.style.paddingBottom = "0.75rem";
  header.style.borderBottom = "1px solid var(--border-subtle, #e2e8f0)";

  const heading = el("h2", "", `對話記錄 Conversation ${conversationId}`);
  heading.style.margin = "0";

  const headerActions = el("div");
  headerActions.style.display = "flex";
  headerActions.style.gap = "0.5rem";
  headerActions.style.alignItems = "center";

  const refreshBtn = el("button", "", "🔄 重新整理");
  refreshBtn.type = "button";
  refreshBtn.title = "重新整理此對話最新內容";
  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "載入中…";
    try {
      const refreshed = await api(`/api/conversations/${encodeURIComponent(conversationId)}?refresh=true`);
      showConversationModal(refreshed, conversationId);
    } catch (e) {
      alert("重新整理失敗: " + e.message);
      refreshBtn.disabled = false;
      refreshBtn.textContent = "🔄 重新整理";
    }
  });

  const close = el("button", "btn-modal-close", "✕ 關閉");
  close.addEventListener("click", () => {
    root.hidden = true;
    root.replaceChildren();
  });
  headerActions.append(refreshBtn, close);
  header.append(heading, headerActions);
  modal.append(header);
  const allowed = new Set(capabilities?.capabilities || []);
  if (allowed.has("ops.conversations.unmasked") && !detail.unmaskAuthorized) {
    const unmaskButton = el("button", "", "查看未遮罩內容");
    unmaskButton.addEventListener("click", async () => {
      const reason = window.prompt("請輸入查看未遮罩內容的原因（至少 3 字）：");
      if (!reason || reason.trim().length < 3) {
        return;
      }
      const refreshed = await api(
        `/api/conversations/${encodeURIComponent(conversationId)}?${new URLSearchParams({ unmask_reason: reason.trim() })}`,
      );
      showConversationModal(refreshed, conversationId);
    });
    modal.append(unmaskButton);
  }
  for (const turn of detail.turns || []) {
    const block = el("div", "panel");
    block.append(el("h3", "", turn.occurredAt));
    block.append(
      el(
        "p",
        "",
        `Issue: ${turn.issueTypeId || "-"}｜Route: ${turn.route || "-"}｜Model: ${turn.model || "-"}｜Result: ${turn.resultType || "-"}`,
      ),
    );
    if (turn.faqKey || (turn.documentIds || []).length) {
      block.append(
        el(
          "p",
          "",
          `FAQ: ${turn.faqKey || "-"}｜Documents: ${(turn.documentIds || []).join(", ") || "-"}`,
        ),
      );
    }
    block.append(
      el(
        "p",
        "",
        `Feedback: ${turn.feedbackRating || "-"}｜Resolved: ${turn.resolvedStatus || "-"}｜Handoff: ${turn.handoffStatus || "-"}｜Masked: ${turn.masked !== false}`,
      ),
    );
    if (turn.answerMasked) {
      block.append(el("p", "", `AI：${turn.answerMasked}`));
    }
    block.append(el("p", "", `使用者：${turn.messageMasked || ""}`));
    const events = el("pre", "", JSON.stringify(turn.events, null, 2));
    block.append(events);
    modal.append(block);
  }
  root.append(modal);
}

let capabilities = null;

function canUseKnowledgeUi() {
  if (!capabilities?.knowledgeBridgeEnabled) {
    return false;
  }
  return (capabilities.knowledgeCapabilities || []).includes("knowledge.read");
}

function actorHasCapability(capability) {
  if (!capability) {
    return true;
  }
  if (capability === "knowledge.ui") {
    return canUseKnowledgeUi();
  }
  return (capabilities?.capabilities || []).includes(capability);
}

async function boot() {
  const authConfig = await fetch("/api/auth/config").then((response) => response.json());
  await ensureAuth(authConfig);
  capabilities = await api("/api/capabilities");
  const defaultWorkspace =
    ROLE_DEFAULT_WORKSPACE[capabilities.role] || visibleWorkspaces()[0]?.id || "platform";
  if (!sessionStorage.getItem(WORKSPACE_KEY)) {
    sessionStorage.setItem(WORKSPACE_KEY, defaultWorkspace);
  }
  renderTopbarActions();
  window.addEventListener("hashchange", async () => {
    if (syncingLocationHash) {
      return;
    }
    if (typeof window.__isKnowledgeDirty === "function" && window.__isKnowledgeDirty()) {
      if (typeof window.__confirmKnowledgeDirty === "function") {
        const ok = await window.__confirmKnowledgeDirty();
        if (!ok) {
          const stored = loadNavFilters();
          syncLocationHash(stored.view || "knowledgePortal", stored);
          return;
        }
        if (typeof window.__clearKnowledgeDirty === "function") {
          window.__clearKnowledgeDirty();
        }
      }
    }
    applyLocationRoute();
  });
  if (!applyLocationRoute()) {
    const firstView = firstVisibleView(activeWorkspaceId()) || "overview";
    renderNav(firstView);
  }
}

function applyLocationRoute() {
  const parsed = parseLocationHash();
  if (!parsed?.view || typeof routes[parsed.view] !== "function") {
    return false;
  }
  if (parsed.workspace) {
    sessionStorage.setItem(WORKSPACE_KEY, parsed.workspace);
  } else {
    const inferred = workspaceForView(parsed.view);
    if (inferred) {
      sessionStorage.setItem(WORKSPACE_KEY, inferred);
    }
  }
  saveNavFilters({ view: parsed.view, ...parsed.filters });
  renderNav(parsed.view, { skipHashSync: true });
  return true;
}

function renderTopbarActions() {
  const meta = document.getElementById("meta-panel");
  if (!meta) {
    return;
  }
  meta.replaceChildren();
  if (canUseKnowledgeUi()) {
    const knowledgeLink = el("a", "topbar-action", "知識文件庫");
    knowledgeLink.href = buildLocationHash("knowledge_ops", "knowledgePortal");
    knowledgeLink.title = "在營運後台內開啟知識編輯／審核／發布";
    knowledgeLink.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
        return;
      }
      event.preventDefault();
      navigateTo("knowledgePortal");
    });
    meta.append(knowledgeLink);
  }
  if (capabilities.authMode === "ENTRA") {
    const userChip = el(
      "span",
      "meta-chip",
      `👤 ${capabilities.displayName || capabilities.userName || capabilities.userId || "使用者"}`
    );
    const roleBadge = el("span", "meta-chip");
    const roleStrong = document.createElement("strong");
    roleStrong.textContent = capabilities.role;
    roleBadge.append(document.createTextNode("角色 "), roleStrong);
    meta.append(userChip, roleBadge);

    const stored = loadAuthHeaders();
    if (stored.bearerToken) {
      const details = getTokenExpiryDetails(stored.bearerToken);
      if (details) {
        const expiryBadge = el(
          "span",
          `meta-chip ${details.isExpired ? "is-warning" : "is-ok"}`,
          details.isExpired
            ? `⚠️ 憑證已於 ${details.formatted} 過期`
            : `⏰ 憑證至 ${details.formatted}`
        );
        expiryBadge.title = `憑證到期時間：${details.expiryDate.toLocaleString("zh-TW")}`;
        meta.append(expiryBadge);
      }
    }

    const logoutBtn = el("button", "meta-chip is-button", "登出 ⎋");
    logoutBtn.type = "button";
    logoutBtn.title = "登出 Entra 身分並清除憑證";
    logoutBtn.addEventListener("click", () => {
      logout();
    });
    meta.append(logoutBtn);
  } else {
    const roleChip = el("button", "meta-chip is-button");
    roleChip.type = "button";
    roleChip.title = "點擊切換開發測試身分與角色";
    const roleStrong = document.createElement("strong");
    roleStrong.textContent = capabilities.role;
    roleChip.append(document.createTextNode("角色 "), roleStrong, document.createTextNode(" ▾"));
    roleChip.addEventListener("click", showRoleSwitcherModal);
    meta.append(roleChip);

    const logoutBtn = el("button", "meta-chip is-button", "重設身分");
    logoutBtn.type = "button";
    logoutBtn.title = "清除目前暫存身分";
    logoutBtn.addEventListener("click", () => {
      clearAuthHeaders();
      window.location.reload();
    });
    meta.append(logoutBtn);
  }
  meta.append(el("span", "meta-chip", `驗證 ${capabilities.authMode}`));
  if (capabilities.knowledgeBridgeEnabled) {
    meta.append(el("span", "meta-chip is-ok", "知識整合已啟用"));
  }
}

function showRoleSwitcherModal() {
  const stored = loadAuthHeaders();
  const currentRole = stored.role || capabilities.role || "SYSTEM_ADMIN";
  const currentUserId = stored.userId || "ops.admin";
  const currentUserName = stored.userName || "System Administrator";
  const currentOwnerUnits = stored.ownerUnits || "IT Service Desk";

  const container = el("div");
  container.style.display = "flex";
  container.style.flexDirection = "column";
  container.style.gap = "1rem";
  container.style.maxWidth = "560px";

  const desc = el(
    "p",
    "muted",
    "本機開發模式預設啟用最高權限（SYSTEM_ADMIN）。若需驗證各項功能在不同角色下的權限邊界，可點選下方身分快速切換，或透過自訂表單調整："
  );
  container.append(desc);

  const presets = [
    {
      role: "SYSTEM_ADMIN",
      title: "最高系統管理員 (預設)",
      userId: "ops.admin",
      userName: "System Administrator",
      ownerUnits: "IT Service Desk",
      desc: "營運後台全功能 + 知識庫 PLATFORM 最高管理權限",
    },
    {
      role: "KNOWLEDGE_ADMIN",
      title: "知識管理員",
      userId: "ops.knowledge",
      userName: "Knowledge Administrator",
      ownerUnits: "IT Service Desk",
      desc: "知識庫全生命週期、審核與發布 (Portal PLATFORM/MANAGER)",
    },
    {
      role: "SERVICE_OWNER",
      title: "服務負責人",
      userId: "ops.owner",
      userName: "Service Owner",
      ownerUnits: "IT Service Desk",
      desc: "管理品質案例、FAQ 與範例庫",
    },
    {
      role: "AI_ADMIN",
      title: "AI 管理員",
      userId: "ops.ai",
      userName: "AI Administrator",
      ownerUnits: "IT Service Desk",
      desc: "提示詞工程、模型註冊與評估管理",
    },
    {
      role: "AUDITOR",
      title: "稽核人員",
      userId: "ops.auditor",
      userName: "Auditor",
      ownerUnits: "IT Service Desk",
      desc: "唯讀稽核日誌與安全脫敏查詢",
    },
    {
      role: "ANALYST",
      title: "分析人員",
      userId: "ops.analyst",
      userName: "Analyst",
      ownerUnits: "IT Service Desk",
      desc: "檢視對話紀錄、議題與營運指標",
    },
  ];

  const presetList = el("div");
  presetList.style.display = "flex";
  presetList.style.flexDirection = "column";
  presetList.style.gap = "0.5rem";

  for (const p of presets) {
    const isCurrent = p.role === currentRole;
    const itemBtn = el("button");
    itemBtn.type = "button";
    itemBtn.style.textAlign = "left";
    itemBtn.style.padding = "0.65rem 0.85rem";
    itemBtn.style.display = "flex";
    itemBtn.style.flexDirection = "column";
    itemBtn.style.gap = "0.25rem";
    itemBtn.style.borderRadius = "8px";
    itemBtn.style.border = isCurrent
      ? "2px solid var(--accent, #0f6cbd)"
      : "1px solid var(--border, #cbd5e1)";
    itemBtn.style.background = isCurrent
      ? "var(--accent-soft, #eff6fc)"
      : "var(--panel, #ffffff)";
    itemBtn.style.cursor = "pointer";

    const headerRow = el("div");
    headerRow.style.display = "flex";
    headerRow.style.justifyContent = "space-between";
    headerRow.style.alignItems = "center";

    const titleStrong = el("strong", "", p.title);
    titleStrong.style.color = isCurrent ? "var(--accent, #0f6cbd)" : "var(--text, #1e293b)";

    const badge = el("span", "badge", isCurrent ? `${p.role} (目前使用中)` : p.role);
    if (isCurrent) {
      badge.style.background = "var(--accent, #0f6cbd)";
      badge.style.color = "#ffffff";
    }
    headerRow.append(titleStrong, badge);

    const descSpan = el("span", "muted", p.desc);
    descSpan.style.fontSize = "0.82rem";

    itemBtn.append(headerRow, descSpan);
    itemBtn.addEventListener("click", () => {
      saveAuthHeaders({
        userId: p.userId,
        userName: p.userName,
        role: p.role,
        ownerUnits: p.ownerUnits,
      });
      window.location.reload();
    });
    presetList.append(itemBtn);
  }

  container.append(presetList);

  const customDetails = document.createElement("details");
  customDetails.style.border = "1px solid var(--border, #e2e8f0)";
  customDetails.style.borderRadius = "8px";
  customDetails.style.padding = "0.65rem 0.85rem";

  const summary = document.createElement("summary");
  summary.textContent = "自訂身分與權限單位 (進階)";
  summary.style.cursor = "pointer";
  summary.style.fontWeight = "600";
  customDetails.append(summary);

  const customForm = el("form");
  customForm.style.display = "flex";
  customForm.style.flexDirection = "column";
  customForm.style.gap = "0.55rem";
  customForm.style.marginTop = "0.75rem";

  const userIdGroup = el("div", "form-field");
  userIdGroup.append(el("label", "", "使用者代號 (User ID):"));
  const userIdInput = el("input");
  userIdInput.type = "text";
  userIdInput.value = currentUserId;
  userIdInput.required = true;
  userIdGroup.append(userIdInput);

  const userNameGroup = el("div", "form-field");
  userNameGroup.append(el("label", "", "使用者名稱 (User Name):"));
  const userNameInput = el("input");
  userNameInput.type = "text";
  userNameInput.value = currentUserName;
  userNameGroup.append(userNameInput);

  const roleGroup = el("div", "form-field");
  roleGroup.append(el("label", "", "角色 (Role):"));
  const roleSelect = el("select");
  for (const r of [
    "SYSTEM_ADMIN",
    "KNOWLEDGE_ADMIN",
    "SERVICE_OWNER",
    "AI_ADMIN",
    "AUDITOR",
    "ANALYST",
  ]) {
    const opt = document.createElement("option");
    opt.value = r;
    opt.textContent = r;
    if (r === currentRole) opt.selected = true;
    roleSelect.append(opt);
  }
  roleGroup.append(roleSelect);

  const unitsGroup = el("div", "form-field");
  unitsGroup.append(el("label", "", "所屬單位 (Owner Units, 逗號分隔):"));
  const unitsInput = el("input");
  unitsInput.type = "text";
  unitsInput.value = currentOwnerUnits;
  unitsGroup.append(unitsInput);

  const submitCustomBtn = el("button", "", "套用自訂身分並重新整理");
  submitCustomBtn.type = "submit";
  submitCustomBtn.style.marginTop = "0.35rem";

  customForm.append(userIdGroup, userNameGroup, roleGroup, unitsGroup, submitCustomBtn);
  customForm.addEventListener("submit", (e) => {
    e.preventDefault();
    saveAuthHeaders({
      userId: userIdInput.value.trim() || "ops.admin",
      userName: userNameInput.value.trim() || "System Administrator",
      role: roleSelect.value,
      ownerUnits: unitsInput.value.trim() || "IT Service Desk",
    });
    window.location.reload();
  });

  customDetails.append(customForm);
  container.append(customDetails);

  showContentModal("切換身分與權限（開發測試）", container);
}

function activeWorkspaceId() {
  return sessionStorage.getItem(WORKSPACE_KEY) || "knowledge_ops";
}

function visibleWorkspaces() {
  return workspaces
    .map((workspace) => ({
      ...workspace,
      items: workspace.items.filter(([, , capability]) => actorHasCapability(capability)),
    }))
    .filter((workspace) => workspace.items.length > 0);
}

function firstVisibleView(workspaceId) {
  const workspace = visibleWorkspaces().find((item) => item.id === workspaceId);
  return workspace?.items[0]?.[0] || null;
}

let currentActiveView = "overview";

function renderNav(active, options = {}) {
  currentActiveView = active;
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  const visible = visibleWorkspaces();
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
      const preferred =
        item.id === "knowledge_ops" && canUseKnowledgeUi()
          ? "knowledgePortal"
          : item.items[0]?.[0] || "overview";
      const nextView = item.items.some(([id]) => id === preferred)
        ? preferred
        : item.items[0]?.[0] || "overview";
      navigateTo(nextView);
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

  document.body.classList.toggle("view-knowledge-portal", active === "knowledgePortal");
  const title = VIEW_TITLES[active] || active;
  document.title = `${title}｜AI 資訊客服營運後台`;

  if (!options.skipHashSync) {
    const stored = loadNavFilters();
    const { view: _view, ...filters } = stored.view === active ? stored : { view: active };
    syncLocationHash(active, filters);
  }

  if (active !== "conversations") {
    stopConversationPolling();
  }

  if (typeof routes[active] === "function") {
    routes[active]();
  } else if (workspace?.items[0]) {
    routes[workspace.items[0][0]]();
  }
}

let currentOverviewPreset = "7d";
let currentOverviewTrendTab = "conv";
let currentOverviewInterval = "DAY";
let currentOverviewModel = "";
let currentOverviewIssueTypeId = "";

const OVERVIEW_ISSUE_NAMES = {
  "vpn.connection_failed": "VPN 連線異常與斷線",
  "other.unclassified": "一般未分類問題",
  "password.account_locked": "密碼鎖定與重設需求",
  "other.greeting": "問候與引導交談",
  "email.outlook_sync": "Outlook 信件同步失敗",
  "hardware.laptop_battery": "筆記型電腦電池與電源問題",
  "software.teams_login": "Teams 登入與授權問題",
};

const OVERVIEW_METRIC_TRANSLATIONS = {
  conversation_count: "總對話數 (Conversation Count)",
  turn_count: "總對話輪次 (Turn Count)",
  active_user_count: "活躍使用者數 (Active Users)",
  issue_occurrence_count: "問題提取次數 (Issue Occurrences)",
  knowledge_hit_rate: "知識庫命中解答率 (Knowledge Hit Rate)",
  faq_hit_rate: "FAQ 直接命中率 (FAQ Hit Rate)",
  no_answer_count: "無答案兜底次數 (No Answer Count)",
  clarification_count: "需澄清確認次數 (Clarification Count)",
  handoff_count: "真人客服轉接數 (Handoff Count)",
  handoff_rate: "真人客服轉接率 (Handoff Rate)",
  ticket_count: "自動建立派工單數 (Ticket Count)",
  positive_feedback_count: "正面好評數 (Positive Feedback)",
  negative_feedback_count: "負面差評數 (Negative Feedback)",
  resolved_feedback_count: "已標記解決回饋數 (Resolved Feedback)",
  total_tokens: "總模型權杖消耗 (Total Tokens)",
  estimated_cost_usd: "預估模型成本 USD (Estimated Cost)",
  cost_coverage: "成本可追蹤覆蓋率 (Cost Tracking Coverage)",
  error_rate: "系統調用錯誤率 (System Error Rate)",
  p50_latency_ms: "中位數回應延遲 P50 (ms)",
  p95_latency_ms: "95 百分位回應延遲 P95 (ms)",
};

function exportOverviewCsv(data) {
  const rows = [];
  rows.push(["=== 平台營運總覽摘要報告 ==="]);
  rows.push(["統計期間", data.periodPreset || "7d", `開始時間: ${data.periodStart || "-"}`, `結束時間: ${data.periodEnd || "-"}`]);
  rows.push(["資料更新時間", data.updatedAt || "-", `時區: ${data.timezone || "Asia/Taipei"}`]);
  rows.push([]);
  rows.push(["指標名稱", "數值", "計算備註"]);
  rows.push(["總處理對話數 (Conversations)", data.conversationCount ?? 0, "期間至少有一次進線交談的獨立對話"]);
  rows.push(["總對話輪次 (Turns)", data.turnCount ?? 0, "使用者進線發言總輪次"]);
  rows.push(["活躍使用者數 (Active Users)", data.activeUserCount ?? 0, "期間內提出請求之獨立使用者數"]);
  rows.push(["問題提取總數 (Issues)", data.issueOccurrenceCount ?? 0, "系統自對話中成功識別提取之 IT 問題次數"]);
  rows.push(["知識庫解答數", data.knowledgeAnswerCount ?? 0, "成功自企業知識庫命中解答"]);
  rows.push(["FAQ 解答數", data.faqAnswerCount ?? 0, "成功自 FAQ 知識點直答"]);
  rows.push(["需澄清問答數", data.clarificationCount ?? 0, "意圖不明需反問澄清"]);
  rows.push(["無解答兜底數", data.noAnswerCount ?? 0, "無法確認解答或超出知識庫範圍"]);
  rows.push(["真人客服轉接數", data.handoffCount ?? 0, `轉單率: ${((data.handoffRate ?? 0) * 100).toFixed(1)}%`]);
  rows.push(["建立派工單數", data.ticketCount ?? 0, "自動派發至工單系統"]);
  rows.push(["正面滿意回饋", data.positiveFeedbackCount ?? 0, "使用者評為滿意/有幫助"]);
  rows.push(["負面待改善回饋", data.negativeFeedbackCount ?? 0, "使用者反饋無幫助/待改善"]);
  rows.push(["總權杖消耗 (Tokens)", data.totalTokens ?? 0, "LLM Prompt 與 Completion 合計 Tokens"]);
  rows.push(["預估費用 (USD)", `$${(data.estimatedCostUsd ?? 0).toFixed(4)}`, `成本完整追蹤率: ${((data.costCoverage ?? 0) * 100).toFixed(1)}%`]);
  rows.push(["系統錯誤率", `${((data.errorRate ?? 0) * 100).toFixed(3)}%`, "包含超時與異常失敗"]);
  rows.push(["延遲 P50 / P95 (ms)", `${data.p50LatencyMs ?? "-"} ms / ${data.p95LatencyMs ?? "-"} ms`, "系統回應延遲指標"]);
  rows.push([]);
  rows.push(["=== 每日營運趨勢 (Daily Trends) ==="]);
  rows.push(["日期", "對話數", "輪次數", "活躍使用者", "問題量", "總 Tokens", "估算成本 USD"]);
  for (const t of data.trends || []) {
    rows.push([t.period, t.conversationCount ?? 0, t.turnCount ?? 0, t.activeUserCount ?? 0, t.issueOccurrenceCount ?? 0, t.totalTokens ?? 0, t.estimatedCostUsd ?? 0]);
  }
  rows.push([]);
  rows.push(["=== Top 問題分類排行 ==="]);
  rows.push(["排名", "問題代碼", "中文名稱", "發生次數", "佔比"]);
  const totalIssues = data.issueOccurrenceCount || 1;
  (data.topIssueTypes || []).forEach((item, idx) => {
    const friendlyName = OVERVIEW_ISSUE_NAMES[item.issueTypeId] || item.issueTypeId;
    rows.push([idx + 1, item.issueTypeId, friendlyName, item.count, `${((item.count / totalIssues) * 100).toFixed(1)}%`]);
  });

  const csvText = "\uFEFF" + rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `teams-agent-operations-summary-${data.periodPreset || "period"}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function renderOverviewTrendChart(trends, activeTab) {
  const container = el("div", "trend-svg-container");
  if (!trends || trends.length === 0) {
    container.append(el("div", "empty", "目前選定期間內尚無趨勢數據"));
    return container;
  }

  let s1Label = "對話數";
  let s1Color = "#2563eb";
  let s1Unit = "次";
  let s2Label = "輪次數";
  let s2Color = "#059669";
  let s2Unit = "次";
  let getS1 = (d) => d.conversationCount ?? 0;
  let getS2 = (d) => d.turnCount ?? 0;
  let formatVal = (v, isS2) => Number(v).toLocaleString();

  if (activeTab === "issues") {
    s1Label = "問題提取量";
    s1Color = "#d97706";
    s1Unit = "件";
    s2Label = "活躍使用者";
    s2Color = "#2563eb";
    s2Unit = "人";
    getS1 = (d) => d.issueOccurrenceCount ?? 0;
    getS2 = (d) => d.activeUserCount ?? 0;
  } else if (activeTab === "cost") {
    s1Label = "Token 消耗";
    s1Color = "#7c3aed";
    s1Unit = "tokens";
    s2Label = "估算成本";
    s2Color = "#059669";
    s2Unit = "USD";
    getS1 = (d) => d.totalTokens ?? 0;
    getS2 = (d) => d.estimatedCostUsd ?? 0;
    formatVal = (v, isS2) => (isS2 ? `$${Number(v).toFixed(4)}` : Number(v).toLocaleString());
  }

  const s1Values = trends.map(getS1);
  const s2Values = trends.map(getS2);
  const maxS1 = Math.max(...s1Values, 1);
  const maxS2 = Math.max(...s2Values, activeTab === "cost" ? 0.0001 : 1);

  const W = 800;
  const H = 220;
  const padL = 55;
  const padR = 40;
  const padT = 20;
  const padB = 35;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const N = trends.length;

  const getX = (idx) => (N === 1 ? padL + plotW / 2 : padL + (idx * plotW) / (N - 1));
  const getY1 = (v) => padT + plotH - (v / maxS1) * plotH;
  const getY2 = (v) => padT + plotH - (v / maxS2) * plotH;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "trend-svg");

  const defs = `
    <defs>
      <linearGradient id="trendGradS1" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${s1Color}" stop-opacity="0.22"/>
        <stop offset="100%" stop-color="${s1Color}" stop-opacity="0.0"/>
      </linearGradient>
    </defs>
  `;

  let gridLines = "";
  for (let step = 0; step <= 4; step++) {
    const yVal = padT + (plotH * step) / 4;
    const s1Tick = Math.round(maxS1 * (1 - step / 4));
    gridLines += `
      <line x1="${padL}" y1="${yVal}" x2="${W - padR}" y2="${yVal}" stroke="var(--border)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="${padL - 8}" y="${yVal + 3}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="var(--mono)">${s1Tick.toLocaleString()}</text>
    `;
  }

  let xLabels = "";
  trends.forEach((t, i) => {
    if (N > 10 && i % 2 !== 0 && i !== N - 1) return;
    const x = getX(i);
    const shortDate = (t.period || "").length > 5 ? t.period.slice(5) : t.period;
    xLabels += `<text x="${x}" y="${H - 12}" text-anchor="middle" font-size="10" fill="var(--muted)" font-family="var(--mono)">${shortDate}</text>`;
  });

  let s1AreaPath = "";
  let s1LinePath = "";
  let s2LinePath = "";
  let s1Circles = "";
  let s2Circles = "";

  if (N === 1) {
    const cx = getX(0);
    const cy1 = getY1(s1Values[0]);
    const cy2 = getY2(s2Values[0]);
    s1Circles = `<circle cx="${cx}" cy="${cy1}" r="6" fill="${s1Color}" stroke="#ffffff" stroke-width="2.5"/>`;
    s2Circles = `<circle cx="${cx}" cy="${cy2}" r="5" fill="${s2Color}" stroke="#ffffff" stroke-width="2"/>`;
  } else {
    const pts1 = trends.map((_, i) => `${getX(i)},${getY1(s1Values[i])}`);
    const pts2 = trends.map((_, i) => `${getX(i)},${getY2(s2Values[i])}`);
    s1LinePath = `<polyline points="${pts1.join(" ")}" fill="none" stroke="${s1Color}" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"/>`;
    s2LinePath = `<polyline points="${pts2.join(" ")}" fill="none" stroke="${s2Color}" stroke-width="2" stroke-dasharray="4 3" stroke-linecap="round" stroke-linejoin="round"/>`;
    s1AreaPath = `<polygon points="${padL},${padT + plotH} ${pts1.join(" ")} ${padL + plotW},${padT + plotH}" fill="url(#trendGradS1)"/>`;
    trends.forEach((_, i) => {
      s1Circles += `<circle cx="${getX(i)}" cy="${getY1(s1Values[i])}" r="3.5" fill="${s1Color}" stroke="#ffffff" stroke-width="1.5"/>`;
      s2Circles += `<circle cx="${getX(i)}" cy="${getY2(s2Values[i])}" r="3" fill="${s2Color}" stroke="#ffffff" stroke-width="1.5"/>`;
    });
  }

  const guideLine = `<line id="trendGuideLine" x1="0" y1="${padT}" x2="0" y2="${padT + plotH}" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="3 3" opacity="0"/>`;
  const activeDot1 = `<circle id="trendActiveDot1" cx="0" cy="0" r="5.5" fill="${s1Color}" stroke="#ffffff" stroke-width="2.5" opacity="0"/>`;
  const activeDot2 = `<circle id="trendActiveDot2" cx="0" cy="0" r="4.5" fill="${s2Color}" stroke="#ffffff" stroke-width="2" opacity="0"/>`;

  svg.innerHTML = `
    ${defs}
    ${gridLines}
    ${xLabels}
    ${s1AreaPath}
    ${s1LinePath}
    ${s2LinePath}
    ${guideLine}
    ${s1Circles}
    ${s2Circles}
    ${activeDot1}
    ${activeDot2}
    <rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="transparent" style="cursor: crosshair;" id="trendInteractiveOverlay"/>
  `;

  const tooltip = el("div", "trend-tooltip");
  tooltip.style.opacity = "0";

  container.append(svg, tooltip);

  const overlay = svg.querySelector("#trendInteractiveOverlay");
  const guide = svg.querySelector("#trendGuideLine");
  const dot1 = svg.querySelector("#trendActiveDot1");
  const dot2 = svg.querySelector("#trendActiveDot2");

  if (overlay) {
    overlay.addEventListener("pointermove", (evt) => {
      const rect = svg.getBoundingClientRect();
      const clientX = evt.clientX - rect.left;
      const svgX = (clientX / rect.width) * W;
      let nearestIdx = 0;
      let nearestDist = Infinity;
      trends.forEach((_, i) => {
        const x = getX(i);
        const dist = Math.abs(x - svgX);
        if (dist < nearestDist) {
          nearestDist = dist;
          nearestIdx = i;
        }
      });

      const d = trends[nearestIdx];
      const ptX = getX(nearestIdx);
      const ptY1 = getY1(s1Values[nearestIdx]);
      const ptY2 = getY2(s2Values[nearestIdx]);

      guide.setAttribute("x1", ptX);
      guide.setAttribute("x2", ptX);
      guide.setAttribute("opacity", "0.75");

      dot1.setAttribute("cx", ptX);
      dot1.setAttribute("cy", ptY1);
      dot1.setAttribute("opacity", "1");

      dot2.setAttribute("cx", ptX);
      dot2.setAttribute("cy", ptY2);
      dot2.setAttribute("opacity", "1");

      const s1Display = formatVal(s1Values[nearestIdx], false);
      const s2Display = formatVal(s2Values[nearestIdx], true);

      tooltip.innerHTML = `
        <div style="font-weight: 800; font-family: var(--mono); margin-bottom: 4px; color: #cbd5e1;">${d.period}</div>
        <div style="display: flex; align-items: center; gap: 6px; color: #ffffff;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${s1Color};"></span>
          <span>${s1Label}:</span> <strong style="font-family: var(--mono);">${s1Display} ${s1Unit}</strong>
        </div>
        <div style="display: flex; align-items: center; gap: 6px; color: #ffffff;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${s2Color};"></span>
          <span>${s2Label}:</span> <strong style="font-family: var(--mono);">${s2Display} ${s2Unit}</strong>
        </div>
      `;

      const tipX = (ptX / W) * rect.width;
      const tipY = Math.min((ptY1 / H) * rect.height, rect.height - 70);
      tooltip.style.transform = `translate(${tipX > rect.width - 160 ? tipX - 170 : tipX + 15}px, ${Math.max(10, tipY - 20)}px)`;
      tooltip.style.opacity = "1";
    });

    overlay.addEventListener("pointerleave", () => {
      guide.setAttribute("opacity", "0");
      dot1.setAttribute("opacity", "0");
      dot2.setAttribute("opacity", "0");
      tooltip.style.opacity = "0";
    });
  }

  return container;
}

async function renderOverview(forceRefresh = false) {
  const app = document.getElementById("app");
  const presetEl = document.getElementById("overview-preset");
  const preset = presetEl?.value || currentOverviewPreset || "7d";
  currentOverviewPreset = preset;

  const startEl = document.getElementById("custom-start-date");
  const endEl = document.getElementById("custom-end-date");
  const savedStart = startEl?.value || "";
  const savedEnd = endEl?.value || "";

  const intervalEl = document.getElementById("overview-interval");
  const interval = (intervalEl?.value || currentOverviewInterval || "DAY").toUpperCase();
  currentOverviewInterval = ["DAY", "WEEK", "MONTH"].includes(interval) ? interval : "DAY";

  const modelEl = document.getElementById("overview-model");
  const issueEl = document.getElementById("overview-issue-type");
  const model = (modelEl?.value || currentOverviewModel || "").trim();
  const issueTypeId = (issueEl?.value || currentOverviewIssueTypeId || "").trim();
  currentOverviewModel = model;
  currentOverviewIssueTypeId = issueTypeId;

  // Capture period before clearing the DOM — buildPeriodQuery must not read
  // controls that replaceChildren is about to remove.
  const query = new URLSearchParams(buildPeriodQuery("", {
    preset,
    start: savedStart,
    end: savedEnd,
  }));
  query.set("interval", currentOverviewInterval);
  if (model) query.set("model", model);
  if (issueTypeId) query.set("issue_type_id", issueTypeId);
  if (forceRefresh) query.set("refresh", "true");

  app.replaceChildren(el("div", "empty", "載入營運數據中…"));

  try {
    const data = await api(`/api/operations/summary?${query.toString()}`);

    const dashboard = el("div", "overview-dashboard");

    // 1. Header & Controls Bar
    const header = el("header", "overview-header-bar");
    const titleGroup = el("div", "overview-title-group");

    const badgeRow = el("div", "overview-badge-row");
    const statusPill = el("span", "overview-status-pill");
    statusPill.innerHTML = '<span class="live-dot pulse"></span> 平台即時營運中控';

    const tz = data.timezone || "Asia/Taipei";
    const updateTimeStr = formatLocalClock(data.updatedAt, tz);
    const freshnessChip = el("span", "overview-freshness-chip", `摘要更新：${updateTimeStr}（時區：${tz}）`);
    freshnessChip.title = "本次營運摘要 API 產生時間（非事件管線最後寫入時間）";
    badgeRow.append(statusPill, freshnessChip);

    if (data.dataFreshnessMinutes != null) {
      const idleMinutes = data.dataFreshnessMinutes;
      const latestEventHint = data.latestEventAt
        ? `期間內最近一筆營運事件時間：${formatLocalClock(data.latestEventAt, tz)}（${tz}）。此指標反映「多久沒有新事件」，不代表批次管線故障。`
        : "此指標反映期間內多久沒有新營運事件，不代表批次管線故障。";
      if (idleMinutes > 15) {
        const idleChip = el(
          "span",
          "overview-warning-chip",
          `⚠️ 最近事件：${idleMinutes} 分鐘前`,
        );
        idleChip.title = latestEventHint;
        badgeRow.append(idleChip);
      } else {
        const idleChip = el(
          "span",
          "overview-freshness-chip",
          `🟢 最近事件：${idleMinutes} 分鐘前`,
        );
        idleChip.title = latestEventHint;
        badgeRow.append(idleChip);
      }
    }
    titleGroup.append(
      badgeRow,
      el("h2", "overview-main-heading", "平台營運總覽"),
      el("p", "overview-sub-heading", "即時監控企業知識庫問答、對話輪次、真人轉單分流與 AI Token 預算消耗"),
    );

    const actionsGroup = el("div", "overview-actions-group");
    const periodControl = el("div", "overview-period-control");
    const select = periodSelect(preset);
    select.id = "overview-preset";

    const customPeriod = customPeriodInputs(savedStart, savedEnd);
    customPeriod.id = "overview-custom-period";
    customPeriod.hidden = preset !== "custom";

    const intervalControl = intervalSelect(currentOverviewInterval);
    intervalControl.id = "overview-interval";

    const modelInput = el("input");
    modelInput.type = "text";
    modelInput.id = "overview-model";
    modelInput.placeholder = "Model（選填）";
    modelInput.value = model;
    modelInput.setAttribute("aria-label", "模型篩選");

    const issueInput = el("input");
    issueInput.type = "text";
    issueInput.id = "overview-issue-type";
    issueInput.placeholder = "Issue Type（選填）";
    issueInput.value = issueTypeId;
    issueInput.setAttribute("aria-label", "Issue 篩選");

    select.addEventListener("change", () => {
      currentOverviewPreset = select.value;
      customPeriod.hidden = select.value !== "custom";
      if (select.value !== "custom") {
        currentOverviewModel = modelInput.value.trim();
        currentOverviewIssueTypeId = issueInput.value.trim();
        currentOverviewInterval = intervalControl.value;
        renderOverview(false);
      }
    });

    intervalControl.addEventListener("change", () => {
      currentOverviewInterval = intervalControl.value;
      currentOverviewModel = modelInput.value.trim();
      currentOverviewIssueTypeId = issueInput.value.trim();
      renderOverview(false);
    });

    const apply = el("button", "btn", "套用");
    apply.type = "button";
    apply.addEventListener("click", () => {
      currentOverviewModel = modelInput.value.trim();
      currentOverviewIssueTypeId = issueInput.value.trim();
      currentOverviewInterval = intervalControl.value;
      renderOverview(false);
    });

    const refresh = el("button", "btn button-primary", "🔄 重新整理");
    refresh.type = "button";
    refresh.title = "即刻向後端取得最新營運數據（繞過快取）";
    refresh.addEventListener("click", () => {
      currentOverviewModel = modelInput.value.trim();
      currentOverviewIssueTypeId = issueInput.value.trim();
      currentOverviewInterval = intervalControl.value;
      renderOverview(true);
    });

    const exportBtn = el("button", "btn", "📥 匯出 CSV");
    exportBtn.type = "button";
    exportBtn.title = "下載本期營運摘要與趨勢報表";
    exportBtn.addEventListener("click", () => exportOverviewCsv(data));

    periodControl.append(
      select,
      customPeriod,
      intervalControl,
      modelInput,
      issueInput,
      apply,
      refresh,
      exportBtn,
    );
    actionsGroup.append(periodControl);
    header.append(titleGroup, actionsGroup);
    dashboard.append(header);

    if (data.dataFreshnessMinutes != null && data.dataFreshnessMinutes > 15) {
      const warnBox = el(
        "div",
        "warning",
        `期間內最近一筆營運事件已是 ${data.dataFreshnessMinutes} 分鐘前；若這段時間本來就沒有新對話，屬正常閒置，不代表查詢管線故障。`,
      );
      warnBox.style.margin = "0";
      dashboard.append(warnBox);
    }

    // 2. SLA & Health Strip
    const slaStrip = el("div", "sla-health-strip");

    const availVal = ((1 - (data.errorRate ?? 0)) * 100).toFixed(2);
    const slaItem1 = el("div", "sla-strip-item");
    slaItem1.innerHTML = `
      <div class="sla-strip-dot emerald"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">系統可用性 (SLA)</span>
        <span class="sla-strip-val">${availVal}% <span class="badge badge-success">正常</span></span>
      </div>
    `;

    const p50 = data.p50LatencyMs != null ? `${data.p50LatencyMs}ms` : "-";
    const p95 = data.p95LatencyMs != null ? `${data.p95LatencyMs}ms` : "-";
    const slaItem2 = el("div", "sla-strip-item");
    slaItem2.innerHTML = `
      <div class="sla-strip-dot sapphire"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">延遲 P50 / P95</span>
        <span class="sla-strip-val">${p50} / ${p95} <span class="badge badge-accent">達標</span></span>
      </div>
    `;

    const totalAnswered = (data.knowledgeAnswerCount ?? 0) + (data.faqAnswerCount ?? 0);
    const autoResolutionRate = data.conversationCount ? ((totalAnswered / data.conversationCount) * 100).toFixed(1) : "0.0";
    const slaItem3 = el("div", "sla-strip-item");
    slaItem3.innerHTML = `
      <div class="sla-strip-dot emerald"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">自動解答涵蓋率</span>
        <span class="sla-strip-val">${autoResolutionRate}% <span class="badge badge-success">${totalAnswered.toLocaleString()} 件</span></span>
      </div>
    `;

    const totalFeedback = (data.positiveFeedbackCount ?? 0) + (data.negativeFeedbackCount ?? 0);
    const csatPercent = totalFeedback > 0 ? ((data.positiveFeedbackCount / totalFeedback) * 100).toFixed(1) : "100.0";
    const slaItem4 = el("div", "sla-strip-item");
    slaItem4.innerHTML = `
      <div class="sla-strip-dot sapphire"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">滿意度 (CSAT)</span>
        <span class="sla-strip-val">${csatPercent}% <span class="badge badge-success">${data.positiveFeedbackCount ?? 0} 正評</span></span>
      </div>
    `;

    const costCov = ((data.costCoverage ?? 1) * 100).toFixed(1);
    const slaItem5 = el("div", "sla-strip-item");
    slaItem5.innerHTML = `
      <div class="sla-strip-dot emerald"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">成本追蹤涵蓋</span>
        <span class="sla-strip-val">${costCov}% <span class="badge badge-neutral">可審核</span></span>
      </div>
    `;

    slaStrip.append(slaItem1, slaItem2, slaItem3, slaItem4, slaItem5);
    dashboard.append(slaStrip);

    // 3. Hero KPI 4 Cards Grid
    const heroGrid = el("div", "hero-kpi-grid");

    // Card 1: 服務量能
    const convCount = data.conversationCount ?? 0;
    const turnCount = data.turnCount ?? 0;
    const avgTurns = convCount > 0 ? (turnCount / convCount).toFixed(1) : "-";
    const cardTraffic = el("div", "hero-kpi-card card-traffic");
    cardTraffic.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">對話服務量能</span>
        <span class="hero-icon-badge">💬</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${convCount.toLocaleString()}</div>
        <div class="hero-stat-caption">總處理對話數 (Conversations)</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">總對話輪次</span>
          <span class="hero-subval">${turnCount.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">平均輪次</span>
          <span class="hero-subval">${avgTurns} 輪/次</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">活躍使用者</span>
          <span class="hero-subval">${(data.activeUserCount ?? 0).toLocaleString()} 人</span>
        </div>
      </div>
    `;

    // Card 2: 自動化解答
    const kAns = data.knowledgeAnswerCount ?? 0;
    const fAns = data.faqAnswerCount ?? 0;
    const clarCount = data.clarificationCount ?? 0;
    const cardResolution = el("div", "hero-kpi-card card-resolution");
    cardResolution.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">AI 自動化解答</span>
        <span class="badge badge-success">${autoResolutionRate}% 涵蓋</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${(kAns + fAns).toLocaleString()}</div>
        <div class="hero-stat-caption">自主成功解答 (Knowledge & FAQ)</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">知識庫直答</span>
          <span class="hero-subval">${kAns.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">FAQ 命中</span>
          <span class="hero-subval">${fAns.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">需澄清問答</span>
          <span class="hero-subval">${clarCount.toLocaleString()}</span>
        </div>
      </div>
    `;

    // Card 3: 真人轉單與異常
    const hCount = data.handoffCount ?? 0;
    const hRate = ((data.handoffRate ?? 0) * 100).toFixed(1);
    const noAnsCount = data.noAnswerCount ?? 0;
    const cardHandoff = el("div", "hero-kpi-card card-handoff");
    cardHandoff.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">真人轉單與異常</span>
        <span class="badge badge-warning">${hRate}% 轉接率</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${hCount.toLocaleString()}</div>
        <div class="hero-stat-caption">轉接真人客服處理 (Handoffs)</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">建立派工單</span>
          <span class="hero-subval">${(data.ticketCount ?? 0).toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">無答案兜底</span>
          <span class="hero-subval">${noAnsCount.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">系統失敗次數</span>
          <span class="hero-subval">${(data.requestFailureCount ?? 0).toLocaleString()}</span>
        </div>
      </div>
    `;

    // Card 4: 模型耗用與成本
    const costUsd = data.estimatedCostUsd ?? 0;
    const totalToks = data.totalTokens ?? 0;
    const avgCostPerConv = convCount > 0 ? (costUsd / convCount).toFixed(4) : "0.0000";
    const cardCost = el("div", "hero-kpi-card card-cost");
    cardCost.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">模型耗用與成本</span>
        <span class="badge badge-accent">${costCov}% 覆蓋率</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${data.costDisplayEnabled === false ? "已關閉" : `$${costUsd.toFixed(4)}`}</div>
        <div class="hero-stat-caption">預估模型總費用 USD</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">Total Tokens</span>
          <span class="hero-subval">${totalToks.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">平均對話成本</span>
          <span class="hero-subval">$${avgCostPerConv}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">錯誤異常率</span>
          <span class="hero-subval">${((data.errorRate ?? 0) * 100).toFixed(2)}%</span>
        </div>
      </div>
    `;

    heroGrid.append(cardTraffic, cardResolution, cardHandoff, cardCost);
    dashboard.append(heroGrid);

    // 4. Trend Chart Section
    const trendPanel = el("div", "trend-chart-panel");
    const trendHeader = el("div", "trend-panel-header");
    const trendTitleCol = el("div", "trend-title-col");
    const intervalLabel =
      currentOverviewInterval === "WEEK" ? "每週" :
      currentOverviewInterval === "MONTH" ? "每月" : "每日";
    trendTitleCol.append(
      el("h3", "trend-title", "營運趨勢走勢分析"),
      el("p", "trend-desc", `追蹤${intervalLabel}對話進線量、問題發生頻率與 Token / 成本消耗曲線`),
    );

    const tabGroup = el("div", "trend-tab-group");
    const tabConv = el("button", `trend-tab-btn ${currentOverviewTrendTab === "conv" ? "active" : ""}`, "對話與輪次");
    const tabIssues = el("button", `trend-tab-btn ${currentOverviewTrendTab === "issues" ? "active" : ""}`, "問題發生量");
    const tabCost = el("button", `trend-tab-btn ${currentOverviewTrendTab === "cost" ? "active" : ""}`, "Token 與成本");
    tabGroup.append(tabConv, tabIssues, tabCost);
    trendHeader.append(trendTitleCol, tabGroup);

    // Dynamic Callout Banner
    const calloutBanner = el("div", "trend-stats-callout");
    function updateTrendCallouts(tabKey) {
      const trends = data.trends || [];
      let totalVal = 0;
      let peakVal = 0;
      let peakPeriod = "-";
      let unit = "次";

      if (tabKey === "conv") {
        unit = "次";
        totalVal = trends.reduce((acc, cur) => acc + (cur.conversationCount || 0), 0);
        trends.forEach((t) => {
          if ((t.conversationCount || 0) >= peakVal) {
            peakVal = t.conversationCount || 0;
            peakPeriod = t.period;
          }
        });
      } else if (tabKey === "issues") {
        unit = "件";
        totalVal = trends.reduce((acc, cur) => acc + (cur.issueOccurrenceCount || 0), 0);
        trends.forEach((t) => {
          if ((t.issueOccurrenceCount || 0) >= peakVal) {
            peakVal = t.issueOccurrenceCount || 0;
            peakPeriod = t.period;
          }
        });
      } else if (tabKey === "cost") {
        unit = "tokens";
        totalVal = trends.reduce((acc, cur) => acc + (cur.totalTokens || 0), 0);
        trends.forEach((t) => {
          if ((t.totalTokens || 0) >= peakVal) {
            peakVal = t.totalTokens || 0;
            peakPeriod = t.period;
          }
        });
      }

      const avgVal = trends.length > 0 ? (totalVal / trends.length).toFixed(1) : "0";
      calloutBanner.innerHTML = `
        <div class="trend-callout-item">
          <span class="trend-callout-label">統計區間總計:</span>
          <span class="trend-callout-val">${totalVal.toLocaleString()} ${unit}</span>
        </div>
        <div class="trend-callout-item">
          <span class="trend-callout-label">日最高峰值:</span>
          <span class="trend-callout-val">${peakVal.toLocaleString()} ${unit} (${peakPeriod})</span>
        </div>
        <div class="trend-callout-item">
          <span class="trend-callout-label">每日平均量:</span>
          <span class="trend-callout-val">${Number(avgVal).toLocaleString()} ${unit}/日</span>
        </div>
      `;
    }

    updateTrendCallouts(currentOverviewTrendTab);

    // Trend Chart container
    let chartSlot = renderOverviewTrendChart(data.trends, currentOverviewTrendTab);

    function switchTrendTab(nextTab) {
      currentOverviewTrendTab = nextTab;
      tabConv.className = `trend-tab-btn ${nextTab === "conv" ? "active" : ""}`;
      tabIssues.className = `trend-tab-btn ${nextTab === "issues" ? "active" : ""}`;
      tabCost.className = `trend-tab-btn ${nextTab === "cost" ? "active" : ""}`;
      updateTrendCallouts(nextTab);
      const newChart = renderOverviewTrendChart(data.trends, nextTab);
      chartSlot.replaceWith(newChart);
      chartSlot = newChart;
    }

    tabConv.addEventListener("click", () => switchTrendTab("conv"));
    tabIssues.addEventListener("click", () => switchTrendTab("issues"));
    tabCost.addEventListener("click", () => switchTrendTab("cost"));

    const legendRow = el("div", "trend-legend-row");
    legendRow.innerHTML = `
      <div class="trend-legend-item">
        <span class="trend-legend-mark" style="background: #2563eb;"></span>
        <span>主指標 (實線)</span>
      </div>
      <div class="trend-legend-item">
        <span class="trend-legend-mark" style="background: #059669; border-top: 1px dashed #059669;"></span>
        <span>次指標 (虛線)</span>
      </div>
      <div class="trend-legend-item" style="margin-left: auto; color: var(--subtle); font-size: 0.725rem;">
        * 可將滑鼠移至圖表上方檢視每日詳細數值
      </div>
    `;

    trendPanel.append(trendHeader, calloutBanner, chartSlot, legendRow);
    dashboard.append(trendPanel);

    // 5. Split Analytics Grid: Service Resolution Funnel & Top Issues
    const splitGrid = el("div", "split-analytics-grid");

    // Left: Service Resolution Funnel
    const funnelCard = el("div", "analytics-card");
    const funnelHeader = el("div", "analytics-card-header");
    const funnelTitleGroup = el("div");
    funnelTitleGroup.append(
      el("h3", "analytics-card-title", "服務處置分流 (Resolution Breakdown)"),
      el("p", "analytics-card-subtitle", "依各類回覆處置結果評估 AI 解答成效與轉單比例"),
    );
    const totalIssues = data.issueOccurrenceCount || data.conversationCount || 1;
    funnelHeader.append(funnelTitleGroup, badge(`共 ${(data.issueOccurrenceCount || convCount).toLocaleString()} 次處理`, "neutral"));

    const funnelBars = el("div", "funnel-bars-container");
    const funnelStages = [
      {
        title: "企業知識庫直答 (Knowledge)",
        count: kAns,
        color: "emerald",
      },
      {
        title: "真人客服轉接 (Live Agent)",
        count: hCount,
        color: "sapphire",
      },
      {
        title: "無確認答案 (No Knowledge)",
        count: noAnsCount,
        color: "rose",
      },
      {
        title: "需反問澄清 (Clarification)",
        count: clarCount,
        color: "amber",
      },
      {
        title: "FAQ 命中直答 (FAQ Hit)",
        count: fAns,
        color: "purple",
      },
    ];

    for (const stage of funnelStages) {
      const stageRow = el("div", "funnel-stage-row");
      const pct = ((stage.count / totalIssues) * 100).toFixed(1);
      stageRow.innerHTML = `
        <div class="funnel-stage-meta">
          <span class="funnel-stage-title">${stage.title}</span>
          <span class="funnel-stage-stat">${stage.count.toLocaleString()} 次 (${pct}%)</span>
        </div>
        <div class="funnel-bar-track">
          <div class="funnel-bar-fill ${stage.color}" style="width: ${Math.min(100, Math.max(stage.count > 0 ? 3 : 0, Number(pct)))}%;"></div>
        </div>
      `;
      funnelBars.append(stageRow);
    }
    funnelCard.append(funnelHeader, funnelBars);

    // Right: Top Issues Ranking
    const issuesCard = el("div", "analytics-card");
    const issuesHeader = el("div", "analytics-card-header");
    const issuesTitleGroup = el("div");
    issuesTitleGroup.append(
      el("h3", "analytics-card-title", "Top 問題類型排行 (Top Issues)"),
      el("p", "analytics-card-subtitle", "進線高頻問題統計，點選可直接進入鑽取診斷"),
    );
    const issuesAllLink = drillLink("查看全部 Issue →", "issues");
    issuesHeader.append(issuesTitleGroup, issuesAllLink);

    const issuesList = el("div", "issues-list-container");
    const topIssues = data.topIssueTypes || [];
    if (topIssues.length === 0) {
      issuesList.append(el("div", "empty", "目前無問題分類紀錄"));
    } else {
      topIssues.slice(0, 5).forEach((item, idx) => {
        const itemRow = el("div", "issue-rank-item");
        const rankClass = idx === 0 ? "top1" : idx === 1 ? "top2" : idx === 2 ? "top3" : "";
        const friendlyName = OVERVIEW_ISSUE_NAMES[item.issueTypeId] || item.issueTypeId;
        const sharePct = ((item.count / totalIssues) * 100).toFixed(1);

        const head = el("div", "issue-rank-head");
        const titleWrap = el("div", "issue-rank-title-group");
        titleWrap.append(el("span", `issue-rank-badge ${rankClass}`, `#${idx + 1}`), el("span", "issue-rank-name", friendlyName));
        const valSpan = el("span", "issue-rank-val", `${item.count.toLocaleString()} 件 (${sharePct}%)`);
        head.append(titleWrap, valSpan);

        const barWrap = el("div", "issue-rank-bar-wrap");
        barWrap.innerHTML = `
          <div class="issue-rank-track">
            <div class="issue-rank-fill" style="width: ${Math.min(100, Math.max(4, Number(sharePct)))}%;"></div>
          </div>
        `;

        const actions = el("div", "issue-rank-actions");
        actions.append(
          drillLink("🔍 查看 Issue 分析", "issues", { issueTypeId: item.issueTypeId }),
          drillLink("🔀 路由規則", "routes", { issueTypeId: item.issueTypeId }),
        );

        itemRow.append(head, barWrap, actions);
        issuesList.append(itemRow);
      });
    }
    issuesCard.append(issuesHeader, issuesList);

    splitGrid.append(funnelCard, issuesCard);
    dashboard.append(splitGrid);

    // 6. Quick Action Navigation Hub
    const quickNavPanel = el("div", "quick-nav-panel");
    quickNavPanel.append(el("h3", "quick-nav-title", "⚡ 常用營運功能導航"));
    const quickNavGrid = el("div", "quick-nav-grid");

    const quickActions = [
      {
        icon: "🔍",
        title: "Issue 深入分析",
        desc: "檢視各類問題發生趨勢、對話樣本與解答分佈",
        view: "issues",
        filters: {},
      },
      {
        icon: "🔀",
        title: "路由來源管理",
        desc: "檢查與配置各業務分類的 AI / 人工轉派分流策略",
        view: "routes",
        filters: {},
      },
      {
        icon: "⭐",
        title: "品質與負評案件",
        desc: "追蹤使用者差評、澄清未果與回饋已解決標記",
        view: "quality",
        filters: { rating: "DOWN" },
      },
      {
        icon: "💰",
        title: "成本與費用分析",
        desc: "監控各模型 Token 消耗、預估花費與預算告警",
        view: "costs",
        filters: {},
      },
      {
        icon: "📚",
        title: "知識文件庫",
        desc: "檢視企業知識文件覆蓋度、命中解答率與待補缺口",
        view: "knowledgePortal",
        filters: {},
      },
    ];

    for (const qa of quickActions) {
      const card = el("a", "quick-nav-card");
      card.href = buildLocationHash(workspaceForView(qa.view) || activeWorkspaceId(), qa.view, qa.filters);
      card.addEventListener("click", (evt) => {
        if (evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey || evt.button !== 0) return;
        evt.preventDefault();
        navigateTo(qa.view, qa.filters);
      });
      card.innerHTML = `
        <div class="quick-nav-head">
          <div class="quick-nav-icon-title">
            <span>${qa.icon}</span>
            <span>${qa.title}</span>
          </div>
          <span class="quick-nav-arrow">&rarr;</span>
        </div>
        <p class="quick-nav-desc">${qa.desc}</p>
      `;
      quickNavGrid.append(card);
    }
    quickNavPanel.append(quickNavGrid);
    dashboard.append(quickNavPanel);

    // 7. Collapsible Metrics Glossary
    const definitions = data.metricDefinitions || {};
    if (Object.keys(definitions).length) {
      const details = el("details", "overview-glossary");
      const summary = el("summary", "glossary-summary");
      summary.innerHTML = `
        <span class="glossary-summary-title">📖 指標計算定義與公式說明 (點擊展開 ${Object.keys(definitions).length} 項指標)</span>
        <span class="glossary-toggle-icon">▾</span>
      `;
      details.append(summary);

      const content = el("div", "glossary-content");
      const table = el("table");
      table.innerHTML = "<thead><tr><th>指標代碼</th><th>中文指標名稱</th><th>計算公式與說明</th></tr></thead>";
      const tbody = el("tbody");
      for (const [key, value] of Object.entries(definitions)) {
        const row = el("tr");
        const codeTd = el("td", "");
        codeTd.append(el("code", "", key));
        row.append(codeTd);
        row.append(el("td", "", OVERVIEW_METRIC_TRANSLATIONS[key] || key));
        row.append(el("td", "", String(value)));
        tbody.append(row);
      }
      table.append(tbody);
      const tableScroll = el("div", "table-responsive");
      tableScroll.append(table);
      content.append(tableScroll);
      details.append(content);
      dashboard.append(details);
    }

    app.replaceChildren(dashboard);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

let conversationPollTimer = null;
let conversationAutoRefresh = false;
let conversationPollInFlight = false;
let currentConversationState = {
  period: { preset: "30d" },
  filters: {},
  cursor: "",
  history: [],
};

function stopConversationPolling() {
  if (conversationPollTimer) {
    clearInterval(conversationPollTimer);
    conversationPollTimer = null;
  }
}

function startConversationPolling() {
  stopConversationPolling();
  if (!conversationAutoRefresh) return;
  conversationPollTimer = setInterval(async () => {
    if (document.hidden || conversationPollInFlight || currentActiveView !== "conversations") return;
    try {
      conversationPollInFlight = true;
      await renderConversations({
        ...currentConversationState,
        forceRefresh: true,
        isPolling: true,
      });
    } finally {
      conversationPollInFlight = false;
    }
  }, 5000);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopConversationPolling();
  } else if (conversationAutoRefresh && currentActiveView === "conversations") {
    startConversationPolling();
    if (!conversationPollInFlight) {
      renderConversations({
        ...currentConversationState,
        forceRefresh: true,
        isPolling: true,
      });
    }
  }
});

async function renderConversations(state = {}) {
  const app = document.getElementById("app");
  if (!state.isPolling) {
    app.replaceChildren(el("div", "empty", "載入中…"));
  }
  try {
    const navFilters = loadNavFilters();
    const period = state.period || currentConversationState.period || { preset: "30d" };
    const savedFilters = state.filters || currentConversationState.filters || {};
    const cursor = state.cursor !== undefined ? state.cursor : currentConversationState.cursor;
    const history = state.history !== undefined ? state.history : currentConversationState.history;

    currentConversationState = {
      period,
      filters: savedFilters,
      cursor,
      history,
    };

    const filters = periodParams(period);
    filters.set("limit", "25");
    if (cursor) filters.set("cursor", cursor);
    const issueTypeId =
      savedFilters.issueTypeId ||
      (navFilters.view === "conversations" ? navFilters.issueTypeId : "");
    const route = savedFilters.route || "";
    const model = savedFilters.model || "";
    const actorRef = savedFilters.actorRef || "";
    const hasFeedback = savedFilters.hasFeedback || "";
    const handoff = savedFilters.handoff || "";
    const channelScope = savedFilters.channelScope || "";
    if (issueTypeId) filters.set("issue_type_id", issueTypeId);
    if (route) filters.set("route", route);
    if (model) filters.set("model", model);
    if (actorRef) filters.set("actor_ref", actorRef);
    if (hasFeedback) filters.set("has_feedback", hasFeedback);
    if (handoff) filters.set("handoff", handoff);
    if (channelScope) filters.set("channel_scope", channelScope);
    if (state.forceRefresh) filters.set("refresh", "true");

    const data = await api(`/api/conversations?${filters.toString()}`);

    if (state.isPolling) {
      const activeId = document.activeElement?.id;
      if (activeId && activeId.startsWith("conversation-")) {
        const badge = document.getElementById("conversations-freshness");
        if (badge) {
          const nowTime = new Date().toLocaleTimeString("zh-TW", { hour12: false });
          badge.textContent = `最後更新：${nowTime}`;
        }
        return;
      }
    }

    const panel = el("section", "panel");

    // Header with Title & Real-time Live Controls
    const headerRow = el("div", "split");
    headerRow.style.display = "flex";
    headerRow.style.justifyContent = "space-between";
    headerRow.style.alignItems = "center";
    headerRow.style.marginBottom = "0.75rem";
    headerRow.style.flexWrap = "wrap";
    headerRow.style.gap = "0.75rem";

    const heading = el("h2", "", "對話紀錄（遮罩摘要）");
    heading.style.margin = "0";

    const liveControls = el("div", "meta-group");
    liveControls.style.display = "flex";
    liveControls.style.alignItems = "center";
    liveControls.style.gap = "0.6rem";

    const nowTime = new Date().toLocaleTimeString("zh-TW", { hour12: false });
    const freshnessBadge = el("span", "meta-chip", `最後更新：${nowTime}`);
    freshnessBadge.id = "conversations-freshness";
    freshnessBadge.title = "目前對話清單資料抓取時間點";

    const autoRefreshLabel = el(
      "label",
      `meta-chip is-button ${conversationAutoRefresh ? "is-ok" : ""}`
    );
    autoRefreshLabel.style.cursor = "pointer";
    autoRefreshLabel.style.display = "inline-flex";
    autoRefreshLabel.style.alignItems = "center";
    autoRefreshLabel.style.gap = "0.35rem";
    autoRefreshLabel.title = "每 5 秒自動重新整理對話清單，即時呈現最新對話紀錄";

    const autoRefreshCheckbox = el("input");
    autoRefreshCheckbox.type = "checkbox";
    autoRefreshCheckbox.checked = conversationAutoRefresh;
    autoRefreshCheckbox.style.margin = "0";
    autoRefreshCheckbox.style.cursor = "pointer";

    const autoRefreshText = el(
      "span",
      "",
      conversationAutoRefresh ? "🟢 即時自動更新（5s）" : "⚡ 即時自動更新"
    );
    autoRefreshLabel.append(autoRefreshCheckbox, autoRefreshText);

    autoRefreshCheckbox.addEventListener("change", () => {
      conversationAutoRefresh = autoRefreshCheckbox.checked;
      if (conversationAutoRefresh) {
        startConversationPolling();
      } else {
        stopConversationPolling();
      }
      renderConversations({
        ...currentConversationState,
        forceRefresh: true,
      });
    });

    const refreshButton = el("button", "button-primary", "🔄 立即重新整理");
    refreshButton.type = "button";
    refreshButton.title = "即刻向後端取得最新對話記錄（繞過暫存）";
    refreshButton.addEventListener("click", () => {
      renderConversations({
        ...currentConversationState,
        forceRefresh: true,
      });
    });

    liveControls.append(freshnessBadge, autoRefreshLabel, refreshButton);
    headerRow.append(heading, liveControls);
    panel.append(headerRow);

    const filterBar = el("div", "filter-bar");
    const channelSelect = el("select", "");
    channelSelect.id = "conversation-channel-scope";
    channelSelect.innerHTML =
      '<option value="">全部通道</option><option value="playground">Playground 測試</option><option value="personal">Teams 個人 (1:1)</option><option value="channel">Teams 頻道</option><option value="group_chat">群組對話</option>';
    if (channelScope) channelSelect.value = channelScope;

    const issueInput = el("input");
    issueInput.id = "conversation-issue-type";
    issueInput.placeholder = "Issue Type ID";
    issueInput.value = issueTypeId || "";
    const routeInput = el("input");
    routeInput.id = "conversation-route";
    routeInput.placeholder = "Route";
    routeInput.value = route;
    const modelInput = el("input");
    modelInput.id = "conversation-model";
    modelInput.placeholder = "Model";
    modelInput.value = model;
    const actorRefInput = el("input");
    actorRefInput.id = "conversation-actor-ref";
    actorRefInput.placeholder = "Actor Ref";
    actorRefInput.value = actorRef || "";
    const feedbackSelect = el("select", "");
    feedbackSelect.id = "conversation-has-feedback";
    feedbackSelect.innerHTML =
      '<option value="">全部回饋</option><option value="true">有回饋</option><option value="false">無回饋</option>';
    if (hasFeedback) feedbackSelect.value = hasFeedback;
    const handoffSelect = el("select", "");
    handoffSelect.id = "conversation-handoff";
    handoffSelect.innerHTML =
      '<option value="">全部 Handoff</option><option value="true">有 Handoff</option><option value="false">無 Handoff</option>';
    if (handoff) handoffSelect.value = handoff;
    const currentFilters = () => ({
      channelScope: channelSelect.value,
      issueTypeId: issueInput.value.trim(),
      route: routeInput.value.trim(),
      model: modelInput.value.trim(),
      actorRef: actorRefInput.value.trim(),
      hasFeedback: feedbackSelect.value,
      handoff: handoffSelect.value,
    });
    const applyFilters = el("button", "", "套用篩選");
    applyFilters.addEventListener("click", () =>
      renderConversations({ period, filters: currentFilters(), cursor: "", history: [] }),
    );
    const exportButton = el("button", "", "匯出 CSV");
    exportButton.addEventListener("click", async () => {
      exportButton.disabled = true;
      exportButton.textContent = "匯出中…";
      const queryFilters = {
        channel_scope: channelSelect.value || undefined,
        issue_type_id: issueInput.value || undefined,
        route: routeInput.value || undefined,
        model: modelInput.value || undefined,
        actor_ref: actorRefInput.value || undefined,
        has_feedback: feedbackSelect.value ? feedbackSelect.value === "true" : undefined,
        handoff: handoffSelect.value ? handoffSelect.value === "true" : undefined,
        ...Object.fromEntries(periodParams(period)),
      };
      try {
        await runExport("csv", "conversations", 30, queryFilters);
      } catch (error) {
        showContentModal("匯出失敗", el("div", "error", error.message));
      } finally {
        exportButton.disabled = false;
        exportButton.textContent = "匯出 CSV";
      }
    });
    filterBar.append(
      channelSelect,
      issueInput,
      routeInput,
      modelInput,
      actorRefInput,
      feedbackSelect,
      handoffSelect,
      applyFilters,
      exportButton,
    );
    panel.append(filterBar);
    panel.append(
      createPeriodControls(period, (nextPeriod) =>
        renderConversations({
          period: nextPeriod,
          filters: currentFilters(),
          cursor: "",
          history: [],
        }),
      ),
    );

    if (!data.items.length) {
      panel.append(el("p", "empty", "目前沒有符合條件的對話事件。"));
      app.replaceChildren(panel);
      return;
    }
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Conversation</th><th>Turns</th><th>Actor</th><th>Channel</th><th>Routes</th><th>Last Seen</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      const link = el("a", "", item.conversationId);
      link.href = "#";
      link.addEventListener("click", async (event) => {
        event.preventDefault();
        const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}?refresh=true`);
        showConversationModal(detail, item.conversationId);
      });
      const conversationCell = el("td");
      conversationCell.append(link);
      row.append(conversationCell);
      row.append(el("td", "", String(item.turnCount)));
      row.append(el("td", "", item.actorRef || "-"));

      const channelCell = el("td");
      const channelTag = el("span", "meta-chip");
      if (item.channelScope === "playground") {
        channelTag.className = "meta-chip is-ok";
        channelTag.textContent = "Playground";
      } else if (item.channelScope === "personal") {
        channelTag.textContent = "Teams 個人";
      } else if (item.channelScope === "channel") {
        channelTag.textContent = "Teams 頻道";
      } else if (item.channelScope === "group_chat" || item.channelScope === "groupchat") {
        channelTag.textContent = "群組";
      } else {
        channelTag.textContent = item.channelScope || "-";
      }
      channelCell.append(channelTag);
      row.append(channelCell);

      row.append(el("td", "", (item.routes || []).join(", ") || "-"));
      row.append(el("td", "", item.lastOccurredAt));
      body.append(row);
    }
    table.append(body);
    const convScroll = el("div", "table-responsive");
    convScroll.append(table);
    panel.append(convScroll);
    const pager = el("div", "filter-bar");
    if (history.length) {
      const previous = el("button", "", "上一頁");
      previous.addEventListener("click", () =>
        renderConversations({
          period,
          filters: currentFilters(),
          cursor: history.at(-1),
          history: history.slice(0, -1),
        }),
      );
      pager.append(previous);
    }
    if (data.nextCursor) {
      const next = el("button", "", "下一頁");
      next.addEventListener("click", () =>
        renderConversations({
          period,
          filters: currentFilters(),
          cursor: data.nextCursor,
          history: [...history, state.cursor || ""],
        }),
      );
      pager.append(next);
    }
    if (pager.childElementCount) panel.append(pager);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderRoutes(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api(`/api/routes/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "路由來源分析"));
    panel.append(createPeriodControls(period, renderRoutes));
    panel.append(createExportButton("routes_summary", period));
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Route</th><th>Count</th><th>實際來源</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.routeDistribution || []) {
      const row = el("tr");
      row.append(el("td", "", item.route));
      row.append(el("td", "", String(item.count)));
      row.append(el("td", "", attributionText(item.attribution)));
      body.append(row);
    }
    table.append(body);
    const routeScroll = el("div", "table-responsive");
    routeScroll.append(table);
    panel.append(routeScroll);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderIssues(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  const filters = loadNavFilters();
  if (filters.clear) {
    clearNavFilters();
  } else if (filters.view === "issues" && filters.issueTypeId) {
    try {
      const data = await api(
        `/api/issues/${encodeURIComponent(filters.issueTypeId)}/routes?${periodParams(period).toString()}`,
      );
      const panel = el("section", "panel");
      panel.append(el("h2", "", `${data.displayName} 路由分布`));
      panel.append(createPeriodControls(period, renderIssues));
      panel.append(drillLink("返回 Issue 總覽", "issues", { clear: true }));
      panel.append(
        createExportButton("routes_summary", period, {
          issue_type_id: data.issueTypeId,
        }),
      );
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Route</th><th>Count</th><th>實際來源</th><th>動作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.routes || []) {
        const row = el("tr");
        row.append(el("td", "", item.route));
        row.append(el("td", "", String(item.count)));
        row.append(el("td", "", attributionText(item.attribution)));
        const actions = el("td", "");
        actions.append(
          drillLink("對話", "conversations"),
          document.createTextNode(" "),
          drillLink("回饋", "quality", { issueTypeId: data.issueTypeId }),
        );
        row.append(actions);
        body.append(row);
      }
      table.append(body);
      const issueRouteScroll = el("div", "table-responsive");
      issueRouteScroll.append(table);
      panel.append(issueRouteScroll);
      app.replaceChildren(panel);
      return;
    } catch (error) {
      app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
      return;
    }
  }
  try {
    const data = await api(`/api/issues/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", `Issue 分析 (${data.taxonomyVersion})`));
    panel.append(createPeriodControls(period, renderIssues));
    panel.append(createExportButton("issues_summary", period));
    panel.append(el("p", "", `未分類：${data.unclassifiedCount}`));
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Count</th><th>Share</th><th>負評率</th><th>Handoff</th><th>成本 USD</th><th>動作</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", item.displayName));
      row.append(el("td", "", String(item.count)));
      row.append(el("td", "", String(item.share)));
      row.append(el("td", "", String(item.negativeFeedbackRate ?? 0)));
      row.append(el("td", "", String(item.handoffRate ?? 0)));
      row.append(el("td", "", String(item.estimatedCostUsd ?? 0)));
      const actions = el("td", "");
      actions.append(
        drillLink("路由", "issues", { issueTypeId: item.issueTypeId }),
        document.createTextNode(" "),
        drillLink("回饋", "quality", { rating: "DOWN", issueTypeId: item.issueTypeId }),
      );
      row.append(actions);
      body.append(row);
    }
    table.append(body);
    const issuesScroll = el("div", "table-responsive");
    issuesScroll.append(table);
    panel.append(issuesScroll);

    if (data.hierarchy?.length) {
      panel.append(el("h3", "", "Taxonomy 階層"));
      const tree = el("ul", "issue-tree");
      for (const node of data.hierarchy) {
        tree.append(renderIssueTreeNode(node));
      }
      panel.append(tree);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

function renderIssueTreeNode(node, depth = 0) {
  const item = el("li", "");
  const label = `${"  ".repeat(depth)}${node.displayName} (${node.aggregateCount ?? node.count})`;
  item.append(el("span", "", label));
  item.append(
    drillLink(" 路由", "issues", { issueTypeId: node.issueTypeId }),
  );
  if (node.children?.length) {
    const children = el("ul", "");
    for (const child of node.children) {
      children.append(renderIssueTreeNode(child, depth + 1));
    }
    item.append(children);
  }
  return item;
}

async function renderCosts(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api(`/api/costs/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "成本分析"));
    panel.append(createPeriodControls(period, renderCosts));

    const grid = el("div", "grid");
    grid.append(
      metric("預估總成本 USD", (data.totalEstimatedCostUsd ?? 0).toFixed(4)),
      metric("預估總成本 TWD", data.totalEstimatedCostTwd != null ? Number(data.totalEstimatedCostTwd).toFixed(2) : "-"),
      metric("Input Tokens", (data.inputTokens ?? 0).toLocaleString()),
      metric("Output Tokens", (data.outputTokens ?? 0).toLocaleString()),
      metric("未歸屬成本事件", data.missingCostEventCount ?? 0),
    );
    panel.append(grid);

    const metaRow = el("div", "filter-bar");
    if (data.usdTwdExchangeRate) metaRow.append(el("span", "metric-label", `匯率：${data.usdTwdExchangeRate} TWD/USD`));
    if (data.embeddingTokens != null || data.toolContextTokens != null) {
      metaRow.append(el("span", "metric-label", `Embedding：${(data.embeddingTokens ?? 0).toLocaleString()} tokens｜Tool Context：${(data.toolContextTokens ?? 0).toLocaleString()} tokens`));
    }
    metaRow.append(el("span", "metric-label", `定價版本：${data.pricingVersion || "v1"}`));
    panel.append(metaRow);

    const table = el("table");
    table.innerHTML = "<thead><tr><th>Date</th><th>Estimated USD</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.byDay || []) {
      const row = el("tr");
      row.append(el("td", "", item.date));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      body.append(row);
    }
    table.append(body);
    const dateScroll = el("div", "table-responsive");
    dateScroll.append(table);
    panel.append(el("h3", "", "依日期"), dateScroll);

    const routeTable = el("table");
    routeTable.innerHTML = "<thead><tr><th>Route</th><th>Estimated USD</th></tr></thead>";
    const routeBody = el("tbody");
    for (const item of data.byRoute || []) {
      const row = el("tr");
      row.append(el("td", "", item.route));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      routeBody.append(row);
    }
    routeTable.append(routeBody);
    const routeScroll = el("div", "table-responsive");
    routeScroll.append(routeTable);
    panel.append(el("h3", "", "依 Route"), routeScroll);

    const issueTable = el("table");
    issueTable.innerHTML =
      "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Estimated USD</th></tr></thead>";
    const issueBody = el("tbody");
    for (const item of data.byIssueType || []) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", item.displayName || "-"));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      issueBody.append(row);
    }
    issueTable.append(issueBody);
    const issueScroll = el("div", "table-responsive");
    issueScroll.append(issueTable);
    panel.append(el("h3", "", "依 Issue Type"), issueScroll);

    for (const [heading, items, key] of [
      ["依 Model", data.byModel, "model"],
      ["依 Provider", data.byProvider, "provider"],
      ["依 Component", data.byComponent, "component"],
      ["依 Knowledge Backend", data.byBackend, "backend"],
    ]) {
      const dimensionTable = el("table");
      dimensionTable.innerHTML = `<thead><tr><th>${heading.replace("依 ", "")}</th><th>Events</th><th>Estimated USD</th></tr></thead>`;
      const dimensionBody = el("tbody");
      for (const item of items || []) {
        const row = el("tr");
        row.append(el("td", "", item[key] || "unknown"));
        row.append(el("td", "", String(item.eventCount ?? 0)));
        row.append(el("td", "", String(item.estimatedCostUsd ?? "-")));
        dimensionBody.append(row);
      }
      dimensionTable.append(dimensionBody);
      const dimScroll = el("div", "table-responsive");
      dimScroll.append(dimensionTable);
      panel.append(el("h3", "", heading), dimScroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderHealth() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api("/api/health/summary");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "系統健康度"));

    const components = data.components || [];
    const healthyCount = components.filter((c) => ["READY", "AVAILABLE", "OK"].includes(c.status?.toUpperCase())).length;
    const abnormalCount = components.length - healthyCount;

    const grid = el("div", "grid");
    grid.append(
      metric("監控元件總數", components.length),
      metric("運作正常", healthyCount),
      metric("異常／降級", abnormalCount),
      metric("遙測視窗", `${data.telemetryWindowHours || 24} 小時`),
    );
    panel.append(grid);

    if (data.simulatedAnomalies) {
      panel.append(
        el("div", "warning", "目前為模擬異常模式，部分元件狀態為測試用途。"),
      );
    }
    if (data.monitoringLinks?.cloudMonitoring) {
      const links = el("div", "filter-bar");
      const monitoringLink = el("a", "button-link", "Cloud Monitoring");
      monitoringLink.href = data.monitoringLinks.cloudMonitoring;
      monitoringLink.target = "_blank";
      const loggingLink = el("a", "button-link", "Cloud Logging");
      loggingLink.href = data.monitoringLinks.cloudLogging;
      loggingLink.target = "_blank";
      links.append(monitoringLink, loggingLink);
      panel.append(links);
    }
    const table = el("table");
    table.innerHTML = [
      "<thead><tr><th>Component</th><th>Status</th><th>24h Requests</th>",
      "<th>Availability</th><th>Error</th><th>Timeout</th>",
      "<th>P50 ms</th><th>P95 ms</th><th>Note</th></tr></thead>",
    ].join("");
    const body = el("tbody");
    for (const item of components) {
      const row = el("tr");
      row.append(el("td", "", item.id));
      const statusCell = el("td");
      const isOk = ["READY", "AVAILABLE", "OK"].includes(item.status?.toUpperCase());
      const statusBadge = el("span", "badge", item.status);
      if (!isOk) {
        statusBadge.style.background = "var(--danger-soft)";
        statusBadge.style.borderColor = "var(--danger-border)";
        statusBadge.style.color = "var(--danger)";
      }
      statusCell.append(statusBadge);
      row.append(statusCell);
      row.append(
        el(
          "td",
          "",
          item.telemetryStatus === "AVAILABLE" ? String(item.requestCount) : "NO DATA",
        ),
      );
      for (const value of [item.availabilityRate, item.errorRate, item.timeoutRate]) {
        row.append(el("td", "", value == null ? "-" : `${(value * 100).toFixed(1)}%`));
      }
      row.append(el("td", "", item.p50LatencyMs == null ? "-" : String(item.p50LatencyMs)));
      row.append(el("td", "", item.p95LatencyMs == null ? "-" : String(item.p95LatencyMs)));
      row.append(el("td", "", item.note || item.url || ""));
      body.append(row);
    }
    table.append(body);
    const tableScroll = el("div", "table-responsive");
    tableScroll.append(table);
    panel.append(tableScroll);

    if ((data.recentAnomalies || []).length) {
      const anomalyTable = el("table");
      anomalyTable.innerHTML = "<thead><tr><th>時間</th><th>Component</th><th>Status</th><th>Error Type</th><th>Correlation</th></tr></thead>";
      const anomalyBody = el("tbody");
      for (const item of data.recentAnomalies) {
        const row = el("tr");
        row.append(el("td", "", item.occurredAt));
        row.append(el("td", "", item.component));
        row.append(el("td", "", item.status));
        row.append(el("td", "", item.errorType));
        row.append(el("td", "", item.correlationId || "-"));
        anomalyBody.append(row);
      }
      anomalyTable.append(anomalyBody);
      const anomalyScroll = el("div", "table-responsive");
      anomalyScroll.append(anomalyTable);
      panel.append(el("h3", "", "最近異常"), anomalyScroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function renderKnowledgePortalEntry() {
  const app = document.getElementById("app");
  if (!canUseKnowledgeUi()) {
    app.replaceChildren(
      el(
        "div",
        "error",
        "知識文件庫尚未啟用，或目前角色沒有 knowledge.read。請用 KNOWLEDGE_ADMIN 登入，並確認 start.sh 已啟用 knowledge bridge。",
      ),
    );
    return;
  }

  const filters = loadNavFilters();
  await renderNativeKnowledgePortal(app, capabilities, navigateTo, filters);
}

async function renderKnowledgeDocument() {
  const app = document.getElementById("app");
  const filters = loadNavFilters();
  const documentId = filters.documentId;
  const caseId = filters.caseId;
  if (!documentId) {
    app.replaceChildren(el("div", "error", "缺少文件 ID。請從品質案件或文件清單進入。"));
    return;
  }
  if (!capabilities?.knowledgeBridgeEnabled) {
    app.replaceChildren(
      el("div", "error", "知識整合尚未啟用。請聯絡平台管理員開啟 knowledge bridge。"),
    );
    return;
  }
  try {
    const payload = await api(`/api/knowledge/documents/${encodeURIComponent(documentId)}`);
    const document = payload.document || payload;
    const panel = el("section", "panel");
    panel.append(el("h2", "", document.title || documentId));
    panel.append(
      el("p", "metric-label", `知識營運／文件／${document.title || documentId}`),
    );
    if (caseId) {
      const back = el("button", "", "返回品質案件");
      back.addEventListener("click", () => navigateTo("quality", { caseId }));
      panel.append(back);
    }
    panel.append(
      el("p", "", `狀態：${document.lifecycle_status || document.status || "-"}`),
      el("p", "", `負責單位：${(document.owner_unit_ids || []).join(", ") || "-"}`),
      el(
        "p",
        "metric-label",
        `文件 ID（進階）：${document.document_id || documentId}`,
      ),
    );
    const draft = document.draft || document.current_draft;
    if (draft?.markdown || draft?.content) {
      const pre = el("pre");
      pre.textContent = String(draft.markdown || draft.content).slice(0, 8000);
      panel.append(el("h3", "", "草稿內容預覽"), pre);
    } else if (payload.draft_markdown) {
      const pre = el("pre");
      pre.textContent = String(payload.draft_markdown).slice(0, 8000);
      panel.append(el("h3", "", "草稿內容預覽"), pre);
    } else {
      panel.append(el("p", "", "目前沒有可預覽的草稿正文（可能尚未建立修訂）。"));
    }
    app.replaceChildren(panel);
  } catch (error) {
    const message =
      error.message === "FORBIDDEN"
        ? "沒有知識讀取權限（knowledge.read）。"
        : error.message;
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", message));
  }
}

async function renderKnowledge() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  const faqPanel = el("section", "panel");
  const syncPanel = el("section", "panel");
  panel.append(el("h2", "", "知識營運"));
  if (capabilities?.knowledgeBridgeEnabled) {
    panel.append(
      el(
        "p",
        "",
        "文件編輯、審核與發布請使用上方「知識文件庫」分頁（內嵌於營運後台）。本頁保留 FAQ 與成效查詢。",
      ),
    );
    const openPortal = el("a", "button-link", "開啟知識文件庫");
    openPortal.href = buildLocationHash("knowledge_ops", "knowledgePortal");
    openPortal.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
        return;
      }
      event.preventDefault();
      navigateTo("knowledgePortal");
    });
    openPortal.style.marginRight = "0.5rem";
    panel.append(openPortal);
  } else {
    panel.append(
      el(
        "p",
        "",
        "文件維護、審核、發布與測試仍由 Knowledge Portal 提供。下方可查看文件成效。",
      ),
    );
    const link = el("a", "button-link", "開啟 Knowledge Portal");
    link.href = capabilities?.knowledgePortalUrl || "http://127.0.0.1:8091";
    link.target = "_blank";
    panel.append(link);
  }
  const exportButton = el("button", "", "匯出 CSV");
  exportButton.style.marginLeft = "0.5rem";
  panel.append(exportButton);

  const filters = el("form", "filter-bar knowledge-filters");
  filters.style.marginTop = "1rem";
  const query = el("input");
  query.style.minWidth = "280px";
  query.placeholder = "搜尋標題或文件 ID";
  query.setAttribute("aria-label", "搜尋知識文件");
  const status = el("select");
  status.setAttribute("aria-label", "生命週期狀態");
  for (const [value, label] of [
    ["", "所有狀態"],
    ["DRAFT", "草稿"],
    ["IN_REVIEW", "審核中"],
    ["APPROVED", "已核准"],
    ["PUBLISHED", "已發布"],
    ["ARCHIVED", "已封存"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    status.append(option);
  }
  const submit = el("button", "", "套用篩選");
  submit.type = "submit";
  filters.append(query, status, submit);
  const result = el("div", "");
  panel.append(filters, result);
  app.replaceChildren(panel, faqPanel, syncPanel);

  async function loadDocuments(cursor = "") {
    result.replaceChildren(el("p", "empty", "載入中…"));
    try {
      const params = new URLSearchParams({ days: "30", limit: "50" });
      if (query.value.trim()) params.set("query", query.value.trim());
      if (status.value) params.set("status", status.value);
      if (cursor) params.set("cursor", cursor);
      const data = await api(`/api/knowledge?${params.toString()}`);
      result.replaceChildren(renderKnowledgeInventory(data, loadDocuments));
    } catch (error) {
      result.replaceChildren(el("div", "error", error.message));
    }
  }

  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    loadDocuments();
  });
  exportButton.addEventListener("click", async () => {
    exportButton.disabled = true;
    exportButton.textContent = "匯出中…";
    try {
      await runExport("csv", "knowledge_performance", 30);
    } catch (error) {
      result.prepend(el("div", "error", error.message));
    } finally {
      exportButton.disabled = false;
      exportButton.textContent = "匯出 CSV";
    }
  });
  await Promise.all([
    loadDocuments(),
    renderFaqManagement(faqPanel),
    renderSyncManagement(syncPanel),
  ]);
}

async function showSyncDetail(jobId, panel) {
  try {
    const detail = await api(`/api/sync-jobs/${encodeURIComponent(jobId)}`);
    const job = detail.job;
    const allowed = new Set(capabilities?.capabilities || []);
    const content = el("div");
    content.append(
      el("p", "", `${job.status}｜階段 ${job.current_stage}｜進度 ${job.progress_percent}%｜ETag ${job.etag}`),
      el("p", "", `範圍：${job.scope_type} ${job.scope_ids.join(", ") || "全部"}`),
      el("p", "", `文件數：${job.document_count}｜Target release：${job.target_release || "未切換"}`),
      el("p", "", `Checkpoint：${job.checkpoint_stage || "-"}｜Retry checkpoint：${job.retry_checkpoint_stage || "-"}`),
    );
    if (job.error_summary) content.append(el("div", "error", job.error_summary));
    if (job.warnings.length) content.append(el("p", "warning", job.warnings.join("；")));
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.sync.write") && ["FAILED", "CANCELLED"].includes(job.status)) {
      const retry = el("button", "", "重試");
      retry.addEventListener("click", async () => {
        const reason = window.prompt("重試原因");
        if (!reason?.trim()) return;
        await api(`/api/sync-jobs/${jobId}/retry`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ reason: reason.trim() }),
        });
        await renderSyncManagement(panel);
      });
      actions.append(retry);
    }
    if (allowed.has("ops.sync.write") && ["QUEUED", "VALIDATING", "BUILDING", "VERIFYING"].includes(job.status)) {
      const cancel = el("button", "", "取消");
      cancel.addEventListener("click", async () => {
        const reason = window.prompt("取消原因");
        if (!reason?.trim()) return;
        await api(`/api/sync-jobs/${jobId}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: reason.trim(), expected_etag: job.etag }),
        });
        await renderSyncManagement(panel);
      });
      actions.append(cancel);
    }
    content.append(actions, el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) {
      content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    }
    showContentModal(`Sync Job ${job.job_id}`, content);
  } catch (error) {
    showContentModal("Sync Job", el("div", "error", error.message));
  }
}

async function renderSyncManagement(panel) {
  panel.replaceChildren(el("h2", "", "重新同步 / 索引"), el("p", "empty", "載入中…"));
  const allowed = new Set(capabilities?.capabilities || []);
  try {
    const data = await api("/api/sync-jobs");
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.sync.write")) {
      const create = el("button", "", "建立全量 Sync");
      create.addEventListener("click", async () => {
        const reason = window.prompt("Sync 原因");
        if (!reason?.trim()) return;
        try {
          await api("/api/sync-jobs", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
            body: JSON.stringify({ scope_type: "ALL", scope_ids: [], reason: reason.trim() }),
          });
          await renderSyncManagement(panel);
        } catch (error) {
          showContentModal("建立 Sync 失敗", el("div", "error", error.message));
        }
      });
      actions.append(create);
    }
    const result = el("div");
    if (!(data.items || []).length) {
      result.append(el("p", "empty", "目前沒有 Sync Job。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>時間</th><th>範圍</th><th>狀態</th><th>進度</th><th>錯誤 / 警告</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const job of data.items) {
        const action = el("td");
        const detail = el("button", "", "查看");
        detail.addEventListener("click", () => showSyncDetail(job.job_id, panel));
        action.append(detail);
        const progress = `${job.progress_percent}% / ${job.checkpoint_stage || "尚無 checkpoint"}`;
        const row = el("tr");
        row.append(
          el("td", "", job.requested_at),
          el("td", "", `${job.scope_type} ${job.scope_ids.join(", ")}`),
          el("td", "", job.status),
          el("td", "", progress),
          el("td", "", job.error_summary || job.warnings.join("；") || "-"),
          action,
        );
        body.append(row);
      }
      table.append(body);
      const scrollWrapper = el("div", "table-responsive");
      scrollWrapper.append(table);
      result.append(scrollWrapper);
    }
    panel.replaceChildren(el("h2", "", "重新同步 / 索引"), actions, result);
  } catch (error) {
    panel.replaceChildren(el("h2", "", "重新同步 / 索引"), el("div", "error", error.message));
  }
}

async function renderFaqManagement(panel) {
  panel.replaceChildren(el("h2", "", "FAQ 治理"), el("p", "empty", "載入中…"));
  const allowed = new Set(capabilities?.capabilities || []);
  if (!allowed.has("ops.faq.read")) {
    panel.replaceChildren(el("h2", "", "FAQ 治理"), el("div", "forbidden", "FORBIDDEN"));
    return;
  }
  try {
    const heading = el("h2", "", "FAQ 治理");
    const actions = el("div", "filter-bar");
    const query = el("input");
    query.placeholder = "搜尋 FAQ Key 或問題";
    const status = el("select");
    status.innerHTML = `
      <option value="">全部狀態</option>
      <option value="DRAFT">DRAFT</option>
      <option value="IN_REVIEW">IN_REVIEW</option>
      <option value="CHANGES_REQUESTED">CHANGES_REQUESTED</option>
      <option value="APPROVED">APPROVED</option>
      <option value="ACTIVE">ACTIVE</option>
      <option value="DISABLED">DISABLED</option>
    `;
    const result = el("div");
    const load = async () => {
      const params = new URLSearchParams();
      if (query.value.trim()) params.set("query", query.value.trim());
      if (status.value) params.set("status", status.value);
      const data = await api(`/api/faqs?${params}`);
      result.replaceChildren();
      summary.textContent = `共 ${data.total || 0} 筆`;
      if (!(data.items || []).length) {
        result.append(el("p", "empty", "沒有符合條件的 FAQ。"));
        return;
      }
      const table = el("table");
      table.innerHTML = "<thead><tr><th>FAQ</th><th>狀態</th><th>Owner</th><th>版本</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const row = el("tr");
        const name = el("td");
        name.append(
          el("strong", "", item.version.content.question),
          el("div", "metric-label", item.faq.faq_key),
        );
        const action = el("td");
        const detail = el("button", "", "查看與處理");
        detail.addEventListener("click", () => showFaqDetail(item.faq.faq_id, panel));
        action.append(detail);
        row.append(
          name,
          el("td", "", item.faq.status),
          el("td", "", item.version.content.owner_unit_id),
          el("td", "", `v${item.version.version_number}`),
          action,
        );
        body.append(row);
      }
      table.append(body);
      const scrollWrapper = el("div", "table-responsive");
      scrollWrapper.append(table);
      result.append(scrollWrapper);
    };
    const searchButton = el("button", "", "套用篩選");
    searchButton.addEventListener("click", load);
    query.addEventListener("keydown", (event) => {
      if (event.key === "Enter") load();
    });
    if (allowed.has("ops.faq.write")) {
      const createButton = el("button", "", "新增 FAQ");
      createButton.addEventListener("click", () => showFaqCreateModal(panel));
      actions.append(createButton);
    }
    const summary = el("span", "metric-label", "");
    actions.append(query, status, searchButton, summary);
    panel.replaceChildren(heading, actions, result);
    await load();
  } catch (error) {
    panel.replaceChildren(el("h2", "", "FAQ 治理"), el("div", "error", error.message));
  }
}

function faqField(label, name, value = "", multiline = false, required = true) {
  const wrap = el("label", "form-field");
  wrap.append(el("span", "metric-label", label));
  const input = el(multiline ? "textarea" : "input");
  input.name = name;
  input.value = value;
  input.required = required;
  wrap.append(input);
  return wrap;
}

function buildFaqForm(content = {}) {
  const form = el("form", "form-grid");
  form.append(
    faqField("FAQ Key", "faq_key", content.faq_key || ""),
    faqField("問題", "question", content.question || ""),
    faqField("固定答案", "answer", content.answer || "", true),
    faqField("分類", "category", content.category || ""),
    faqField("關鍵字（逗號分隔）", "keywords", (content.keywords || []).join(",")),
    faqField("Owner Unit", "owner_unit_id", content.owner_unit_id || "IT Service Desk"),
    faqField("Business Contact", "business_contact", content.business_contact || "IT Service Desk"),
    faqField("Issue Type IDs（逗號分隔）", "issue_type_ids", (content.issue_type_ids || []).join(",")),
    faqField(
      "Audience Groups（逗號分隔；空白代表 ALL）",
      "audience_group_ids",
      (content.audience_group_ids || []).join(","),
      false,
      false,
    ),
  );
  return form;
}

function faqPayload(form) {
  const values = new FormData(form);
  const split = (name) => String(values.get(name) || "").split(",").map((item) => item.trim()).filter(Boolean);
  const groups = split("audience_group_ids");
  return {
    faq_key: values.get("faq_key"), question: values.get("question"),
    answer: values.get("answer"), category: values.get("category"),
    keywords: split("keywords"), owner_unit_id: values.get("owner_unit_id"),
    business_contact: values.get("business_contact"), issue_type_ids: split("issue_type_ids"),
    audience_type: groups.length ? "GROUPS" : "ALL", audience_group_ids: groups,
  };
}

function showFaqCreateModal(panel) {
  const form = buildFaqForm();
  const message = el("div");
  const submit = el("button", "", "建立草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    try {
      const created = await api("/api/faqs", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(faqPayload(form)),
      });
      document.getElementById("modal-root").hidden = true;
      await renderFaqManagement(panel);
      showFaqDetail(created.faq.faq_id, panel);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("新增 FAQ 草稿", form);
}

function showFaqEditModal(faq, version, panel) {
  const form = buildFaqForm(version.content);
  const message = el("div");
  const submit = el("button", "", "建立新版本");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    try {
      await api(`/api/faqs/${encodeURIComponent(faq.faq_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ ...faqPayload(form), expected_etag: faq.etag }),
      });
      await renderFaqManagement(panel);
      await showFaqDetail(faq.faq_id, panel);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal(`編輯 FAQ v${version.version_number}`, form);
}

async function showFaqDetail(faqId, panel) {
  try {
    const detail = await api(`/api/faqs/${encodeURIComponent(faqId)}`);
    const allowed = new Set(capabilities?.capabilities || []);
    const faq = detail.faq;
    const current = detail.versions.find((version) => version.version_id === faq.draft_version_id)
      || detail.versions.find((version) => version.version_id === faq.published_version_id)
      || detail.versions.at(-1);
    const content = el("div");
    content.append(
      el("p", "", `FAQ：${faq.status}｜工作版本：v${current.version_number} ${current.status}｜ETag：${faq.etag}`),
      el("p", "", `問題：${current.content.question}`),
      el("p", "", `答案：${current.content.answer}`),
      el("p", "", `Owner：${current.content.owner_unit_id}｜Issue：${current.content.issue_type_ids.join(", ")}`),
    );
    const actions = el("div", "filter-bar");
    const run = async (path, payload) => {
      try {
        await api(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(payload),
        });
        await renderFaqManagement(panel);
        await showFaqDetail(faqId, panel);
      } catch (error) {
        showContentModal("FAQ 操作失敗", el("div", "error", error.message));
      }
    };
    if (allowed.has("ops.faq.write") && current.status !== "IN_REVIEW") {
      const edit = el("button", "", "建立修訂版本");
      edit.addEventListener("click", () => showFaqEditModal(faq, current, panel));
      actions.append(edit);
    }
    if (allowed.has("ops.faq.write") && ["DRAFT", "CHANGES_REQUESTED"].includes(current.status)) {
      for (const [kind, label] of [["POSITIVE", "新增正例"], ["NEGATIVE", "新增反例"]]) {
        const button = el("button", "", label);
        button.addEventListener("click", async () => {
          const utterance = window.prompt(`${label}問法`);
          if (!utterance) return;
          await run(`/api/faqs/${faqId}/versions/${current.version_id}/tests`, {
            expected_etag: faq.etag, kind, utterance,
            expected_audience_group_ids: current.content.audience_group_ids,
          });
        });
        actions.append(button);
      }
      const submit = el("button", "", "送審");
      submit.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/submit`, { expected_etag: faq.etag },
      ));
      actions.append(submit);
    }
    if (allowed.has("ops.faq.review") && current.status === "IN_REVIEW") {
      const approve = el("button", "", "核准");
      approve.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/review`,
        { expected_etag: faq.etag, approve: true, reason: "管理員已審閱內容與正反例" },
      ));
      const reject = el("button", "", "退回修改");
      reject.addEventListener("click", () => {
        const reason = window.prompt("請輸入退回原因");
        if (!reason?.trim()) return;
        run(`/api/faqs/${faqId}/versions/${current.version_id}/review`, {
          expected_etag: faq.etag, approve: false, reason: reason.trim(),
        });
      });
      actions.append(approve, reject);
    }
    if (allowed.has("ops.faq.activate") && current.status === "APPROVED") {
      const activate = el("button", "", "啟用");
      activate.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/activate`,
        { expected_etag: faq.etag, reason: "管理員核准啟用" },
      ));
      actions.append(activate);
    }
    if (allowed.has("ops.faq.disable") && faq.status === "ACTIVE") {
      const disable = el("button", "", "停用");
      disable.addEventListener("click", () => run(
        `/api/faqs/${faqId}/disable`, { expected_etag: faq.etag, reason: "管理員停用" },
      ));
      actions.append(disable);
    }
    const performance = el("button", "", "查看命中成效");
    performance.addEventListener("click", async () => {
      try {
        const data = await api(`/api/faqs/${faqId}/performance`);
        const result = el("div");
        result.append(el("p", "", `總命中：${data.totalHitCount}`));
        const versions = el("table");
        versions.innerHTML = "<thead><tr><th>Version</th><th>Hits</th></tr></thead>";
        const versionRows = el("tbody");
        for (const item of data.byVersion || []) {
          const row = el("tr");
          row.append(el("td", "", item.versionId), el("td", "", String(item.hitCount)));
          versionRows.append(row);
        }
        versions.append(versionRows);
        const recent = el("table");
        recent.innerHTML = "<thead><tr><th>時間</th><th>Conversation</th><th>Turn</th><th>Version</th></tr></thead>";
        const recentRows = el("tbody");
        for (const item of data.recentHits || []) {
          const row = el("tr");
          row.append(
            el("td", "", item.occurredAt), el("td", "", item.conversationId || "-"),
            el("td", "", item.turnId || "-"), el("td", "", item.versionId || "legacy-unattributed"),
          );
          recentRows.append(row);
        }
        recent.append(recentRows);
        result.append(el("h3", "", "版本歸因"), versions, el("h3", "", "最近命中"), recent);
        showContentModal("FAQ 命中成效", result);
      } catch (error) {
        showContentModal("FAQ 命中成效", el("div", "error", error.message));
      }
    });
    actions.append(performance);
    content.append(actions, el("h3", "", `測試案例（${detail.tests.length}）`));
    for (const test of detail.tests) content.append(el("p", "", `${test.kind}｜${test.utterance}`));
    content.append(el("h3", "", `版本歷史（${detail.versions.length}）`));
    const versions = el("table");
    versions.innerHTML = "<thead><tr><th>版本</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
    const versionRows = el("tbody");
    for (const version of [...detail.versions].reverse()) {
      const action = el("td");
      const canRollback = allowed.has("ops.faq.activate")
        && version.version_id !== faq.published_version_id
        && ["SUPERSEDED", "DISABLED"].includes(version.status)
        && version.approved_by;
      if (canRollback) {
        const rollback = el("button", "", "回復此版本");
        rollback.addEventListener("click", () => {
          const reason = window.prompt(`請輸入回復 v${version.version_number} 的原因`);
          if (!reason?.trim()) return;
          run(`/api/faqs/${faqId}/versions/${version.version_id}/rollback`, {
            expected_etag: faq.etag,
            reason: reason.trim(),
          });
        });
        action.append(rollback);
      } else {
        action.textContent = version.version_id === faq.published_version_id ? "目前發布" : "-";
      }
      const row = el("tr");
      row.append(
        el("td", "", `v${version.version_number}`),
        el("td", "", version.status),
        el("td", "", version.created_by),
        action,
      );
      versionRows.append(row);
    }
    versions.append(versionRows);
    content.append(versions);
    content.append(el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    showContentModal(current.content.question, content);
  } catch (error) {
    showContentModal("FAQ", el("div", "error", error.message));
  }
}

function exampleSelect(label, name, options, value = "") {
  const wrap = el("label", "form-field");
  wrap.append(el("span", "metric-label", label));
  const select = el("select");
  select.name = name;
  for (const [optionValue, optionLabel] of options) {
    const option = el("option", "", optionLabel);
    option.value = optionValue;
    select.append(option);
  }
  select.value = value;
  wrap.append(select);
  return wrap;
}

function buildExampleForm(record = null) {
  const form = el("form", "form-grid");
  if (!record) {
    form.append(
      exampleSelect("來源", "source_type", [
        ["MANUAL", "手動建立"], ["FAQ", "FAQ 版本"], ["DOCUMENT", "文件版本"],
      ]),
      faqField("Source ID", "source_id", "", false, false),
      faqField("Source Version ID", "source_version_id", "", false, false),
    );
  }
  form.append(
    faqField("案例文字", "text", record?.text || "", true),
    faqField("Expected Issue Type ID", "expected_issue_type_id", record?.expected_issue_type_id || ""),
    exampleSelect("Expected Route", "expected_route", [
      ["FAQ", "FAQ"], ["KNOWLEDGE", "KNOWLEDGE"],
      ["TICKET", "TICKET"], ["HANDOFF", "HANDOFF"],
    ], record?.expected_route || "FAQ"),
    exampleSelect("標籤", "label", [
      ["POSITIVE", "正例"], ["NEGATIVE", "反例"],
    ], record?.label || "POSITIVE"),
    faqField("原因（反例必填）", "reason", record?.reason || "", true, false),
  );
  return form;
}

function examplePayload(form) {
  const values = new FormData(form);
  return {
    text: values.get("text"),
    expected_issue_type_id: values.get("expected_issue_type_id"),
    expected_route: values.get("expected_route"),
    label: values.get("label"),
    reason: values.get("reason") || null,
  };
}

function showExampleCreateModal() {
  const form = buildExampleForm();
  const message = el("div");
  const submit = el("button", "", "建立草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    const values = new FormData(form);
    const sourceType = values.get("source_type");
    const sourceId = String(values.get("source_id") || "").trim();
    const versionId = String(values.get("source_version_id") || "").trim();
    let path = "/api/examples/manual";
    if (["FAQ", "DOCUMENT", "CONVERSATION"].includes(sourceType)) {
      if (!sourceId || (sourceType !== "CONVERSATION" && !versionId)) {
        message.replaceChildren(el("div", "error", "來源 ID 必填；FAQ/文件來源也需要 Version ID。"));
        submit.disabled = false;
        return;
      }
      if (sourceType === "CONVERSATION") {
        path = `/api/conversations/${encodeURIComponent(sourceId)}/examples`;
      } else {
        const prefix = sourceType === "FAQ" ? "/api/faqs" : "/api/knowledge";
        path = `${prefix}/${encodeURIComponent(sourceId)}/versions/${encodeURIComponent(versionId)}/examples`;
      }
    }
    try {
      const created = await api(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(examplePayload(form)),
      });
      document.getElementById("modal-root").hidden = true;
      await renderExamples();
      await showExampleDetail(created.example.example_id);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("新增品質案例", form);
}

function showExampleEditModal(record) {
  const form = buildExampleForm(record);
  const message = el("div");
  const submit = el("button", "", "儲存為草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      await api(`/api/examples/${encodeURIComponent(record.example_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ ...examplePayload(form), expected_etag: record.etag }),
      });
      await renderExamples();
      await showExampleDetail(record.example_id);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("編輯品質案例", form);
}

async function showExampleDetail(exampleId) {
  try {
    const detail = await api(`/api/examples/${encodeURIComponent(exampleId)}`);
    const record = detail.example;
    const allowed = new Set(capabilities?.capabilities || []);
    const content = el("div");
    content.append(
      el("p", "", `${record.status}｜${record.source_type}:${record.source_id}｜ETag ${record.etag}`),
      el("p", "", record.text),
      el("p", "", `Expected：${record.expected_issue_type_id} → ${record.expected_route}`),
      el("p", "", `標籤：${record.label}｜Owner：${record.owner_unit_id}`),
    );
    if (record.reason) content.append(el("p", "", `原因：${record.reason}`));
    if (record.dataset_version) content.append(el("p", "", `Dataset：${record.dataset_version}`));
    const actions = el("div", "filter-bar");
    const run = async (path, payload) => {
      try {
        await api(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(payload),
        });
        await renderExamples();
        await showExampleDetail(exampleId);
      } catch (error) {
        showContentModal("案例操作失敗", el("div", "error", error.message));
      }
    };
    if (allowed.has("ops.examples.write") && record.status !== "RETIRED") {
      const edit = el("button", "", "編輯");
      edit.addEventListener("click", () => showExampleEditModal(record));
      actions.append(edit);
    }
    if (allowed.has("ops.examples.verify") && ["DRAFT", "REJECTED"].includes(record.status)) {
      const verify = el("button", "", "驗證通過");
      verify.addEventListener("click", () => run(`/api/examples/${exampleId}/review`, {
        expected_etag: record.etag, approve: true, reason: "SYSTEM_ADMIN 已驗證標籤與預期結果",
      }));
      const reject = el("button", "", "拒絕");
      reject.addEventListener("click", () => {
        const reason = window.prompt("請輸入拒絕原因");
        if (reason?.trim()) run(`/api/examples/${exampleId}/review`, {
          expected_etag: record.etag, approve: false, reason: reason.trim(),
        });
      });
      actions.append(verify, reject);
    }
    if (allowed.has("ops.examples.retire") && record.status !== "RETIRED") {
      const retire = el("button", "", "退役");
      retire.addEventListener("click", () => {
        const reason = window.prompt("請輸入退役原因");
        if (reason?.trim()) run(`/api/examples/${exampleId}/retire`, {
          expected_etag: record.etag, reason: reason.trim(),
        });
      });
      actions.append(retire);
    }
    content.append(actions, el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) {
      content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    }
    showContentModal(`品質案例 ${record.example_id}`, content);
  } catch (error) {
    showContentModal("品質案例", el("div", "error", error.message));
  }
}

async function renderExamples() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  const allowed = new Set(capabilities?.capabilities || []);
  const actions = el("div", "filter-bar");
  const sourceType = el("select");
  sourceType.innerHTML = `
    <option value="">全部來源</option><option value="FAQ">FAQ</option>
    <option value="DOCUMENT">DOCUMENT</option><option value="CONVERSATION">CONVERSATION</option>
    <option value="MANUAL">MANUAL</option>`;
  const status = el("select");
  status.innerHTML = `
    <option value="">全部狀態</option><option value="DRAFT">DRAFT</option>
    <option value="VERIFIED">VERIFIED</option><option value="REJECTED">REJECTED</option>
    <option value="RETIRED">RETIRED</option>`;
  const sourceId = el("input");
  sourceId.placeholder = "Source ID";
  const apply = el("button", "", "套用篩選");
  const result = el("div");
  const summary = el("span", "metric-label");
  const load = async () => {
    try {
      const params = new URLSearchParams();
      if (sourceType.value) params.set("source_type", sourceType.value);
      if (status.value) params.set("status", status.value);
      if (sourceId.value.trim()) params.set("source_id", sourceId.value.trim());
      const data = await api(`/api/examples?${params}`);
      result.replaceChildren();
      summary.textContent = `共 ${data.total || 0} 筆`;
      if (!(data.items || []).length) {
        result.append(el("p", "empty", "沒有符合條件的品質案例。"));
        return;
      }
      const table = el("table");
      table.innerHTML = "<thead><tr><th>案例</th><th>來源</th><th>預期</th><th>狀態</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const action = el("td");
        const detail = el("button", "", "查看與處理");
        detail.addEventListener("click", () => showExampleDetail(item.example_id));
        action.append(detail);
        const row = el("tr");
        row.append(
          el("td", "", item.text),
          el("td", "", `${item.source_type}:${item.source_id}`),
          el("td", "", `${item.expected_issue_type_id} → ${item.expected_route}`),
          el("td", "", item.status),
          action,
        );
        body.append(row);
      }
      table.append(body);
      const examplesScroll = el("div", "table-responsive");
      examplesScroll.append(table);
      result.append(examplesScroll);
    } catch (error) {
      result.replaceChildren(el("div", "error", error.message));
    }
  };
  apply.addEventListener("click", load);
  if (allowed.has("ops.examples.write")) {
    const create = el("button", "", "新增案例");
    create.addEventListener("click", showExampleCreateModal);
    actions.append(create);
  }
  actions.append(sourceType, status, sourceId, apply, summary);
  panel.append(el("h2", "", "品質案例集"), actions, result);
  app.replaceChildren(panel);
  await load();
}

function renderKnowledgeInventory(data, loadDocuments) {
  const container = el("div");
  if (data.warning) container.append(el("p", "warning", data.warning));
  const summary = el(
    "p",
    "",
    `共 ${data.total || 0} 份文件｜績效期間 ${data.periodDays || 30} 天`,
  );
  container.append(summary);
  if (!(data.items || []).length) {
    container.append(el("p", "empty", "沒有符合條件的知識文件。"));
    return container;
  }
  const table = el("table");
  table.innerHTML = [
    "<thead><tr>",
    "<th>文件</th><th>Owner</th><th>生命週期</th><th>解析 / 索引</th>",
    "<th style=\"text-align:right;\">命中</th><th style=\"text-align:right;\">對話</th><th style=\"text-align:right;\">負面回饋</th><th>操作</th>",
    "</tr></thead>",
  ].join("");
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    const documentCell = el("td");
    documentCell.append(
      el("strong", "", item.title || item.documentId),
      el("div", "metric-label", item.documentId),
    );
    const detailButton = el("button", "", "查看成效");
    detailButton.addEventListener("click", async () => {
      detailButton.disabled = true;
      try {
        const detail = await api(
          `/api/knowledge/${encodeURIComponent(item.documentId)}/performance?days=30`,
        );
        showContentModal(item.title || item.documentId, renderDocumentPerformance(detail));
      } catch (error) {
        showContentModal("知識文件成效", el("div", "error", error.message));
      } finally {
        detailButton.disabled = false;
      }
    });
    const actionCell = el("td");
    actionCell.append(detailButton);
    const hitCell = el("td", "", String(item.hitCount || 0));
    hitCell.style.textAlign = "right";
    hitCell.style.fontVariantNumeric = "tabular-nums";
    const convCell = el("td", "", String(item.conversationCount || 0));
    convCell.style.textAlign = "right";
    convCell.style.fontVariantNumeric = "tabular-nums";
    const negCell = el("td", "", String(item.negativeFeedbackCount || 0));
    negCell.style.textAlign = "right";
    negCell.style.fontVariantNumeric = "tabular-nums";
    row.append(
      documentCell,
      el("td", "", item.ownerUnitId || "-"),
      el("td", "", item.lifecycleStatus || "UNKNOWN"),
      el("td", "", `${item.parseStatus || "UNKNOWN"} / ${item.indexStatus || "UNKNOWN"}`),
      hitCell,
      convCell,
      negCell,
      actionCell,
    );
    body.append(row);
  }
  table.append(body);
  const scrollWrapper = el("div", "table-responsive");
  scrollWrapper.append(table);
  container.append(scrollWrapper);
  if (data.nextCursor) {
    const next = el("button", "", "下一頁");
    next.style.marginTop = "1rem";
    next.addEventListener("click", () => loadDocuments(data.nextCursor));
    container.append(next);
  }
  return container;
}

function renderDocumentPerformance(data) {
  const container = el("div", "panel");
  container.style.marginTop = "1rem";
  const grid = el("div", "grid");
  grid.append(
    metric("命中次數", data.hitCount),
    metric("對話數", data.conversationCount),
    metric("正面回饋", data.positiveFeedbackCount),
    metric("負面回饋", data.negativeFeedbackCount),
  );
  container.append(grid);

  if (data.governance) {
    const governance = data.governance;
    const govPanel = el("div", "panel");
    govPanel.append(el("h3", "", "文件治理狀態"));
    if (governance.status === "available") {
      govPanel.append(
        el(
          "p",
          "",
          `生命週期：${governance.lifecycleStatus}｜格式：${governance.formatType}｜解析：${governance.parseStatus}｜索引：${governance.indexStatus}`,
        ),
      );
      if (governance.portalUrl) {
        if (capabilities?.knowledgeBridgeEnabled) {
          const openDoc = el("a", "button-link", "在知識文件庫開啟");
          const documentId = data.documentId || governance.documentId;
          openDoc.href = buildLocationHash("knowledge_ops", "knowledgePortal", {
            k: `/knowledge/${documentId}`,
          });
          openDoc.addEventListener("click", (event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
              return;
            }
            event.preventDefault();
            navigateTo("knowledgePortal", { k: `/knowledge/${documentId}` });
          });
          govPanel.append(openDoc);
        } else {
          const portalLink = el("a", "button-link", "在 Knowledge Portal 開啟");
          portalLink.href = governance.portalUrl;
          portalLink.target = "_blank";
          govPanel.append(portalLink);
        }
      }
    } else {
      govPanel.append(el("p", "", governance.note || `狀態：${governance.status}`));
    }
    container.append(govPanel);
  }

  const issueTable = el("table");
  issueTable.innerHTML =
    "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Count</th></tr></thead>";
  const issueBody = el("tbody");
  for (const item of data.issueTypeDistribution || []) {
    const row = el("tr");
    row.append(el("td", "", item.issueTypeId));
    row.append(el("td", "", item.displayName || "-"));
    row.append(el("td", "", String(item.count)));
    issueBody.append(row);
  }
  issueTable.append(issueBody);
  container.append(el("h3", "", "Issue 分布"), issueTable);

  const releaseTable = el("table");
  releaseTable.innerHTML = "<thead><tr><th>Release</th><th>Hits</th></tr></thead>";
  const releaseBody = el("tbody");
  for (const item of data.releaseAttribution || []) {
    const row = el("tr");
    row.append(el("td", "", item.releaseId));
    row.append(el("td", "", String(item.hitCount)));
    releaseBody.append(row);
  }
  releaseTable.append(releaseBody);
  container.append(el("h3", "", "版本歸因"), releaseTable);

  const recentTable = el("table");
  recentTable.innerHTML = "<thead><tr><th>時間</th><th>Conversation</th><th>Issue</th><th>Release</th><th>Chunk</th></tr></thead>";
  const recentBody = el("tbody");
  for (const item of data.recentHits || []) {
    const row = el("tr");
    row.append(el("td", "", item.occurredAt));
    const conversation = el("a", "", item.conversationId || "-");
    conversation.href = "#";
    conversation.addEventListener("click", async (event) => {
      event.preventDefault();
      const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}`);
      showConversationModal(detail);
    });
    const conversationCell = el("td");
    conversationCell.append(conversation);
    row.append(conversationCell);
    row.append(el("td", "", item.issueTypeId || "-"));
    row.append(el("td", "", item.releaseId || "-"));
    row.append(el("td", "", item.chunkId || "-"));
    recentBody.append(row);
  }
  recentTable.append(recentBody);
  container.append(el("h3", "", "最近命中對話"), recentTable);
  return container;
}

async function showQualityCaseDetail(caseId) {
  try {
    const detail = await api(`/api/quality-cases/${encodeURIComponent(caseId)}`);
    const qualityCase = detail.case;
    const allowed = new Set(capabilities?.capabilities || []);
    const statusLabels = {
      NEW: "新建",
      TRIAGED: "已分派",
      IN_PROGRESS: "修正中",
      WAITING_REVIEW: "待審核發布",
      OBSERVING: "觀察成效",
      RESOLVED: "已結案",
      WONT_FIX: "不處理",
      DUPLICATE: "重複案件",
    };
    const transitionLabels = {
      TRIAGED: "分派處理",
      IN_PROGRESS: "開始修正知識",
      WAITING_REVIEW: "送審／待發布",
      OBSERVING: "進入觀察",
      RESOLVED: "驗證通過並結案",
      WONT_FIX: "標記不處理",
      DUPLICATE: "標記重複",
    };
    const content = el("div");

    const headerRow = el("div", "meta-panel");
    headerRow.style.justifyContent = "flex-start";
    headerRow.style.marginBottom = "1rem";
    headerRow.style.gap = "0.6rem";
    const statusPill = statusBadge(statusLabels[qualityCase.status] || qualityCase.status);
    const prioPill = badge(`優先級 P${qualityCase.priority}`, qualityCase.priority <= 2 ? "danger" : "neutral");
    const caseIdPill = badge(`ID: ${caseId.slice(0, 8)}`, "neutral");
    headerRow.append(statusPill, prioPill, caseIdPill);

    const metricsGrid = el("div", "grid");
    metricsGrid.style.marginBottom = "1rem";
    metricsGrid.append(
      metric("發生頻率", (qualityCase.frequency || 0).toLocaleString()),
      metric("負評率", `${((qualityCase.negative_rate || 0) * 100).toFixed(1)}%`),
      metric("轉人工率", `${((qualityCase.handoff_rate || 0) * 100).toFixed(1)}%`),
      metric("預估成本影響", qualityCase.cost_impact_usd != null ? `$${Number(qualityCase.cost_impact_usd).toFixed(3)}` : "USD 0.00"),
    );

    const infoPanel = el("div");
    infoPanel.style.padding = "0.85rem 1.1rem";
    infoPanel.style.borderRadius = "var(--radius-sm)";
    infoPanel.style.background = "var(--panel-muted)";
    infoPanel.style.border = "1px solid var(--border-subtle)";
    infoPanel.style.marginBottom = "1rem";

    if (qualityCase.description) {
      const descP = el("p", "", qualityCase.description);
      descP.style.margin = "0 0 0.6rem 0";
      descP.style.fontWeight = "550";
      infoPanel.append(descP);
    }

    const metaGrid = el("div", "filter-bar");
    metaGrid.style.gap = "1.2rem";
    metaGrid.style.fontSize = "0.825rem";
    metaGrid.append(
      el("span", "", `負責單位：${qualityCase.owner_unit_id}`),
      el("span", "", `承辦人：${qualityCase.assignee_id || "未指派"}`),
      el("span", "", `問題類型：${qualityCase.issue_type_display_name || qualityCase.issue_type_id || "未指定"}`),
    );
    infoPanel.append(metaGrid);

    const relBox = el("div", "filter-bar");
    relBox.style.marginTop = "0.5rem";
    relBox.style.gap = "0.5rem";
    relBox.append(el("span", "metric-label", "關聯 FAQ:"));
    if (qualityCase.faq_ids && qualityCase.faq_ids.length) {
      for (const fid of qualityCase.faq_ids) {
        relBox.append(badge(fid, "neutral"));
      }
    } else {
      relBox.append(el("span", "muted", "無"));
    }

    relBox.append(el("span", "metric-label", "關聯文件:"));
    if (qualityCase.document_ids && qualityCase.document_ids.length) {
      for (const did of qualityCase.document_ids) {
        relBox.append(badge(did, "accent"));
      }
    } else {
      relBox.append(el("span", "muted", "無"));
    }
    infoPanel.append(relBox);

    const loopHints = el("div", "filter-bar");
    loopHints.style.marginBottom = "1rem";
    loopHints.append(
      el("span", "metric-label", "閉環捷徑："),
      drillLink("修正文件／FAQ", "knowledge"),
      drillLink("案例驗證", "examples"),
      drillLink("對話驗證", "conversations", {
        issueTypeId: qualityCase.issue_type_id || "",
      }),
    );
    if (capabilities?.knowledgeBridgeEnabled) {
      for (const documentId of qualityCase.document_ids || []) {
        loopHints.append(
          drillLink("開啟關聯文件", "knowledgePortal", {
            k: `/knowledge/${documentId}?caseId=${encodeURIComponent(caseId)}`,
          }),
        );
      }
      loopHints.append(drillLink("知識文件庫", "knowledgePortal"));
    } else if (capabilities?.knowledgePortalUrl) {
      const portal = el("a", "drill-link", "開啟知識入口");
      portal.href = capabilities.knowledgePortalUrl;
      portal.target = "_blank";
      portal.rel = "noopener noreferrer";
      loopHints.append(portal);
    }
    content.append(headerRow, metricsGrid, infoPanel, loopHints);
    const transitions = {
      NEW: ["TRIAGED", "WONT_FIX", "DUPLICATE"],
      TRIAGED: ["IN_PROGRESS", "WONT_FIX", "DUPLICATE"],
      IN_PROGRESS: ["WAITING_REVIEW", "OBSERVING", "WONT_FIX", "DUPLICATE"],
      WAITING_REVIEW: ["IN_PROGRESS", "OBSERVING", "WONT_FIX"],
      OBSERVING: ["IN_PROGRESS", "RESOLVED", "WONT_FIX"],
    };
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.quality.write")) {
      const linkFaq = el("button", "", "連結既有 FAQ");
      linkFaq.addEventListener("click", async () => {
        const faqId = window.prompt("請輸入 FAQ ID");
        if (!faqId?.trim()) return;
        await api(`/api/quality-cases/${caseId}/content`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_etag: qualityCase.etag, faq_id: faqId.trim() }),
        });
        await showQualityCaseDetail(caseId);
      });
      actions.append(linkFaq);

      const linkDoc = el("button", "", "連結既有文件");
      linkDoc.addEventListener("click", async () => {
        let docs = [];
        if (capabilities?.knowledgeBridgeEnabled) {
          try {
            const listRes = await api("/api/knowledge/documents");
            docs = listRes.items || listRes.documents || [];
          } catch {
            docs = [];
          }
        }
        const modalBody = el("div");
        const docSelect = document.createElement("select");
        docSelect.className = "input";
        docSelect.style.width = "100%";
        docSelect.style.marginBottom = "0.75rem";

        const defaultOpt = document.createElement("option");
        defaultOpt.value = "";
        defaultOpt.textContent = "-- 請選擇既有文件（或於下方手動輸入 ID）--";
        docSelect.append(defaultOpt);

        for (const doc of docs) {
          const opt = document.createElement("option");
          const dId = doc.document_id || doc.documentId;
          opt.value = dId;
          opt.textContent = `${doc.title} (${dId}｜${doc.status || "草稿"})`;
          docSelect.append(opt);
        }
        const idInput = el("input", "input");
        idInput.type = "text";
        idInput.placeholder = "輸入文件 ID (例如 doc-xxx)";
        idInput.style.width = "100%";
        idInput.style.marginBottom = "1rem";

        docSelect.addEventListener("change", () => {
          if (docSelect.value) idInput.value = docSelect.value;
        });

        const confirmBtn = el("button", "btn primary", "確認關聯文件");
        confirmBtn.addEventListener("click", async () => {
          const docId = idInput.value.trim();
          if (!docId) {
            alert("請選擇或輸入文件 ID");
            return;
          }
          try {
            await api(`/api/quality-cases/${caseId}/content`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_etag: qualityCase.etag, document_id: docId }),
            });
            const root = document.getElementById("modal-root");
            if (root) { root.hidden = true; root.replaceChildren(); }
            await showQualityCaseDetail(caseId);
          } catch (err) {
            alert(`關聯失敗：${err.message || err}`);
          }
        });

        modalBody.append(
          el("p", "", "選擇或輸入要關聯至此品質案件的知識文件："),
          docSelect,
          idInput,
          confirmBtn,
        );
        showContentModal("關聯既有知識文件", modalBody);
      });
      actions.append(linkDoc);

      if (
        capabilities?.knowledgeBridgeEnabled &&
        (capabilities?.knowledgeCapabilities || []).includes("knowledge.create")
      ) {
        const draftDoc = el("button", "", "建立文件草稿");
        draftDoc.addEventListener("click", () => {
          const form = document.createElement("form");
          form.className = "form-grid";

          const titleInput = el("input", "input");
          titleInput.value = qualityCase.title || "";
          titleInput.required = true;
          titleInput.style.width = "100%";

          const ownerDisplay = el("input", "input");
          ownerDisplay.value = qualityCase.owner_unit_id || "";
          ownerDisplay.disabled = true;
          ownerDisplay.style.width = "100%";

          const contactInput = el("input", "input");
          contactInput.value = capabilities?.userId || "IT Service Desk";
          contactInput.style.width = "100%";

          const summaryInput = el("input", "input");
          summaryInput.value = `由品質案件 ${caseId} 建立之改善文件草稿。`;
          summaryInput.style.width = "100%";

          const contentArea = document.createElement("textarea");
          contentArea.className = "input";
          contentArea.rows = 8;
          contentArea.style.width = "100%";
          contentArea.value = `# ${qualityCase.title || "知識文件草稿"}\n\n## 適用問題背景\n\n${qualityCase.description || ""}\n\n## 處理指引步驟\n\n1. 確認系統設定。\n2. 重設並驗證連線狀態。\n`;

          form.append(
            el("label", "form-label", "文件標題："),
            titleInput,
            el("label", "form-label", "負責單位："),
            ownerDisplay,
            el("label", "form-label", "業務聯絡人："),
            contactInput,
            el("label", "form-label", "文件摘要："),
            summaryInput,
            el("label", "form-label", "內容正文草稿（Markdown）："),
            contentArea,
          );

          const submitBtn = el("button", "btn primary", "建立並連結草稿");
          submitBtn.type = "submit";
          submitBtn.style.marginTop = "0.75rem";
          form.append(submitBtn);

          form.addEventListener("submit", async (e) => {
            e.preventDefault();
            submitBtn.disabled = true;
            submitBtn.textContent = "建立中...";
            try {
              const res = await api(`/api/quality-cases/${caseId}/document-draft`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  expected_case_etag: qualityCase.etag,
                  title: titleInput.value.trim(),
                  summary: summaryInput.value.trim(),
                  business_contact: contactInput.value.trim(),
                  markdown_content: contentArea.value,
                }),
              });
              const root = document.getElementById("modal-root");
              if (root) { root.hidden = true; root.replaceChildren(); }
              const createdDocId = res.document?.document_id || "";
              if (res.partialSuccess) {
                showContentModal(
                  "部分成功注意",
                  el("div", "warning", res.message || "文件建立成功但關聯失敗。"),
                );
              } else {
                const promptBox = el("div");
                promptBox.append(
                  el("p", "", `已成功建立文件草稿並關聯至案件（文件 ID：${createdDocId}）！`),
                );
                const goEdit = el("button", "btn primary", "前往編輯草稿");
                goEdit.addEventListener("click", () => {
                  if (root) { root.hidden = true; root.replaceChildren(); }
                  navigateTo("knowledgePortal", {
                    k: `/knowledge/${createdDocId}?caseId=${encodeURIComponent(caseId)}`,
                  });
                });
                promptBox.append(goEdit);
                showContentModal("草稿建立成功", promptBox);
              }
              await showQualityCaseDetail(caseId);
            } catch (err) {
              submitBtn.disabled = false;
              submitBtn.textContent = "建立並連結草稿";
              alert(`建立草稿失敗：${err.message || err}`);
            }
          });

          showContentModal("由品質案件建立知識文件草稿", form);
        });
        actions.append(draftDoc);
      }
      if (allowed.has("ops.faq.write") && qualityCase.issue_type_id) {
        const draftFaq = el("button", "", "建立 FAQ 草稿");
        draftFaq.addEventListener("click", () => {
          const form = buildFaqForm({
            owner_unit_id: qualityCase.owner_unit_id,
            issue_type_ids: [qualityCase.issue_type_id],
          });
          const submit = el("button", "", "建立並連結草稿");
          submit.type = "submit";
          form.append(submit);
          form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const payload = faqPayload(form);
            await api(`/api/quality-cases/${caseId}/faq-draft`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                expected_case_etag: qualityCase.etag,
                faq_key: payload.faq_key, question: payload.question, answer: payload.answer,
                category: payload.category, keywords: payload.keywords,
                business_contact: payload.business_contact,
                audience_type: payload.audience_type,
                audience_group_ids: payload.audience_group_ids,
              }),
            });
            await renderQuality();
          });
          showContentModal("由品質案件建立 FAQ 草稿", form);
        });
        actions.append(draftFaq);
      }
      if (qualityCase.status === "OBSERVING") {
        const refresh = el("button", "", "刷新觀察指標");
        refresh.addEventListener("click", async () => {
          await api(`/api/quality-cases/${caseId}/observation/refresh`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ expected_etag: qualityCase.etag }),
          });
          await showQualityCaseDetail(caseId);
        });
        actions.append(refresh);
      }
    }
    for (const status of transitions[qualityCase.status] || []) {
      const terminal = ["RESOLVED", "WONT_FIX", "DUPLICATE"].includes(status);
      const capability = terminal ? "ops.quality.resolve" : "ops.quality.write";
      if (!allowed.has(capability)) continue;
      const button = el("button", "", transitionLabels[status] || status);
      button.addEventListener("click", async () => {
        const reason = window.prompt(
          `請輸入轉為「${transitionLabels[status] || status}」的原因`,
        );
        if (terminal && !reason?.trim()) return;
        try {
          await api(`/api/quality-cases/${caseId}/transition`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_etag: qualityCase.etag,
              status,
              reason: reason?.trim() || null,
              resolution_type: terminal ? "MANUAL_REVIEW" : null,
            }),
          });
          await renderQuality();
          await showQualityCaseDetail(caseId);
        } catch (error) {
          showContentModal("品質案件操作失敗", el("div", "error", error.message));
        }
      });
      actions.append(button);
    }
    if (qualityCase.observation_baseline) {
      content.append(
        el("h3", "", "觀察指標"),
        el("pre", "json-block", JSON.stringify({
          baseline: qualityCase.observation_baseline,
          latest: qualityCase.observation_latest,
        }, null, 2)),
      );
    }
    content.append(actions, el("h3", "", `操作紀錄（${detail.audit.length}）`));
    if (detail.audit.length) {
      const aTable = el("table");
      aTable.innerHTML = "<thead><tr><th>時間</th><th>操作</th><th>執行人員</th></tr></thead>";
      const aBody = el("tbody");
      for (const event of detail.audit) {
        const row = el("tr");
        const occurred = (event.occurred_at || "").replace("T", " ").slice(0, 19);
        const actCell = el("td");
        actCell.append(statusBadge(event.action));
        row.append(
          el("td", "", occurred),
          actCell,
          el("td", "", event.actor_id || "-"),
        );
        aBody.append(row);
      }
      aTable.append(aBody);
      const aScroll = el("div", "table-responsive");
      aScroll.append(aTable);
      content.append(aScroll);
    } else {
      content.append(el("p", "empty", "尚無操作紀錄"));
    }
    showContentModal(qualityCase.title, content);
  } catch (error) {
    showContentModal("品質案件", el("div", "error", error.message));
  }
}

async function buildQualityLoopPanel() {
  const panel = el("section", "panel");
  panel.append(el("h2", "", "改善案件池"));
  panel.append(
    el(
      "p",
      "metric-label",
      "閉環步驟：待辦／負評 → 合併案件 → 修正文件／FAQ → 審核發布 → 案例與對話驗證 → 觀察成效並結案。",
    ),
  );
  const allowed = new Set(capabilities?.capabilities || []);

  const caseTypeLabels = {
    NO_ANSWER: "無答案",
    NEGATIVE_FEEDBACK: "負評",
    HANDOFF: "轉人工",
    KNOWLEDGE_GAP: "知識缺口",
    LOW_CONFIDENCE: "低信心度",
  };
  const statusLabels = {
    NEW: "新建",
    TRIAGED: "已分派",
    IN_PROGRESS: "修正中",
    WAITING_REVIEW: "待審核",
    OBSERVING: "觀察中",
    RESOLVED: "已結案",
    WONT_FIX: "不處理",
    DUPLICATE: "重複",
  };

  const [candidateData, caseData] = await Promise.all([
    api("/api/quality-candidates?status=OPEN"),
    api("/api/quality-cases"),
  ]);

  const selected = new Set();
  const allCandidates = candidateData.items || [];

  // Top action bar
  const controls = el("div", "filter-bar");
  let mergeBtn = null;

  if (allowed.has("ops.quality.write")) {
    const refresh = el("button", "", "掃描新候選");
    refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      try {
        await api("/api/quality-candidates/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ days: 30 }),
        });
        await renderQuality();
      } catch (error) {
        showContentModal("候選掃描失敗", el("div", "error", error.message));
      } finally {
        refresh.disabled = false;
      }
    });
    controls.append(refresh);

    mergeBtn = el("button", "button-primary", "合併為改善案件 (已選 0 筆)");
    mergeBtn.disabled = true;
    mergeBtn.addEventListener("click", async () => {
      if (!selected.size) return;
      const title = window.prompt(`請輸入改善案件標題（將合併 ${selected.size} 筆候選）：`);
      if (!title?.trim()) return;
      try {
        mergeBtn.disabled = true;
        mergeBtn.textContent = "合併中…";
        await api("/api/quality-candidates/merge", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            candidate_ids: [...selected],
            title: title.trim(),
            description: "由營運事件候選合併",
            priority: "MEDIUM",
          }),
        });
        await renderQuality();
      } catch (error) {
        showContentModal("合併失敗", el("div", "error", error.message));
      } finally {
        updateSelectionState();
      }
    });
    controls.append(mergeBtn);
  }
  panel.append(controls);

  const candidateSectionHeading = el("h3", "", `待合併候選（${candidateData.total || 0}）`);
  panel.append(candidateSectionHeading);

  if (allCandidates.length) {
    let searchQuery = "";
    let selectedCaseType = "";
    let currentPage = 1;
    let pageSize = 25;

    const toolbar = el("div", "candidate-toolbar");

    const searchInput = el("input");
    searchInput.placeholder = "搜尋候選摘要、問題類型…";
    searchInput.style.minWidth = "220px";
    searchInput.addEventListener("input", () => {
      searchQuery = searchInput.value.toLowerCase().trim();
      currentPage = 1;
      renderCandidatesTable();
    });

    const typeSelect = el("select");
    const allOpt = el("option", "", "全部案件類型");
    allOpt.value = "";
    typeSelect.append(allOpt);
    for (const [val, lab] of Object.entries(caseTypeLabels)) {
      const opt = el("option", "", lab);
      opt.value = val;
      typeSelect.append(opt);
    }
    typeSelect.addEventListener("change", () => {
      selectedCaseType = typeSelect.value;
      currentPage = 1;
      renderCandidatesTable();
    });

    const selectFilteredBtn = el("button", "", "選取篩選結果");
    selectFilteredBtn.addEventListener("click", () => {
      const filtered = getFiltered();
      for (const item of filtered) selected.add(item.candidate_id);
      renderCandidatesTable();
    });

    const clearSelectionBtn = el("button", "", "清除選取");
    clearSelectionBtn.addEventListener("click", () => {
      selected.clear();
      renderCandidatesTable();
    });

    const pageSizeSelect = el("select");
    for (const size of [25, 50, 100, "all"]) {
      const opt = el("option", "", size === "all" ? "顯示全部" : `每頁 ${size} 筆`);
      opt.value = String(size);
      if (size === 25) opt.selected = true;
      pageSizeSelect.append(opt);
    }
    pageSizeSelect.addEventListener("change", () => {
      pageSize = pageSizeSelect.value === "all" ? "all" : parseInt(pageSizeSelect.value, 10);
      currentPage = 1;
      renderCandidatesTable();
    });

    const selectionCounter = el("span", "metric-label", `已選取 0 筆`);

    toolbar.append(searchInput, typeSelect, selectFilteredBtn, clearSelectionBtn, pageSizeSelect, selectionCounter);
    panel.append(toolbar);

    const tableBox = el("div", "table-scroll-box candidate-scroll-box");
    const table = el("table", "candidate-table");
    const headerRow = el("tr");
    const headerSelectTh = el("th");
    const headerSelectAllCheckbox = el("input");
    headerSelectAllCheckbox.type = "checkbox";
    headerSelectAllCheckbox.title = "選取／取消本頁全部";
    headerSelectTh.append(headerSelectAllCheckbox);

    headerRow.append(
      headerSelectTh,
      el("th", "", "案件類型"),
      el("th", "", "問題類型"),
      el("th", "", "摘要"),
    );
    table.append(el("thead", "", headerRow));
    const tableBody = el("tbody");
    table.append(tableBody);
    tableBox.append(table);
    panel.append(tableBox);

    const paginationBar = el("div", "candidate-pagination");
    const paginationSummary = el("span", "metric-label", "");
    const pagerButtons = el("div", "filter-bar");
    pagerButtons.style.marginBottom = "0";
    const prevBtn = el("button", "", "上一頁");
    const nextBtn = el("button", "", "下一頁");
    pagerButtons.append(prevBtn, nextBtn);
    paginationBar.append(paginationSummary, pagerButtons);
    panel.append(paginationBar);

    function getFiltered() {
      return allCandidates.filter((item) => {
        if (selectedCaseType && item.case_type !== selectedCaseType) {
          return false;
        }
        if (searchQuery) {
          const desc = (item.description || "").toLowerCase();
          const issue = (item.issue_type_display_name || item.issue_type_id || "").toLowerCase();
          const type = (caseTypeLabels[item.case_type] || item.case_type || "").toLowerCase();
          const title = (item.title || "").toLowerCase();
          if (!desc.includes(searchQuery) && !issue.includes(searchQuery) && !type.includes(searchQuery) && !title.includes(searchQuery)) {
            return false;
          }
        }
        return true;
      });
    }

    function updateSelectionState() {
      selectionCounter.textContent = `已選取 ${selected.size} 筆`;
      if (mergeBtn) {
        mergeBtn.disabled = selected.size === 0;
        mergeBtn.textContent = `合併為改善案件 (已選 ${selected.size} 筆)`;
      }
    }

    function renderCandidatesTable() {
      const filtered = getFiltered();
      const totalFiltered = filtered.length;
      const effectivePageSize = pageSize === "all" ? Math.max(totalFiltered, 1) : pageSize;
      const totalPages = Math.max(1, Math.ceil(totalFiltered / effectivePageSize));
      if (currentPage > totalPages) currentPage = totalPages;
      if (currentPage < 1) currentPage = 1;

      const startIndex = (currentPage - 1) * effectivePageSize;
      const pageItems = filtered.slice(startIndex, startIndex + effectivePageSize);

      tableBody.replaceChildren();

      let allPageSelected = pageItems.length > 0;
      for (const item of pageItems) {
        const isChecked = selected.has(item.candidate_id);
        if (!isChecked) allPageSelected = false;

        const checkbox = el("input");
        checkbox.type = "checkbox";
        checkbox.checked = isChecked;

        const row = el("tr");
        if (isChecked) row.classList.add("is-selected");

        const updateRowCheck = (checked) => {
          if (checked) {
            selected.add(item.candidate_id);
            row.classList.add("is-selected");
          } else {
            selected.delete(item.candidate_id);
            row.classList.remove("is-selected");
          }
          checkbox.checked = checked;
          updateSelectionState();
          headerSelectAllCheckbox.checked = pageItems.every((it) => selected.has(it.candidate_id));
        };

        checkbox.addEventListener("change", () => updateRowCheck(checkbox.checked));

        const selectCell = el("td");
        selectCell.append(checkbox);

        const typeCell = el("td");
        const typeBadge = el("span", "badge", caseTypeLabels[item.case_type] || item.case_type);
        typeCell.append(typeBadge);

        const issueCell = el(
          "td",
          "",
          item.issue_type_display_name || item.issue_type_id || "未分類",
        );

        const descCell = el("td", "", item.description || "-");
        descCell.style.overflowWrap = "break-word";

        row.append(selectCell, typeCell, issueCell, descCell);
        tableBody.append(row);
      }

      headerSelectAllCheckbox.checked = allPageSelected;

      paginationSummary.textContent = `第 ${currentPage} / ${totalPages} 頁（篩選結果 ${totalFiltered} 筆 / 全部 ${candidateData.total || allCandidates.length} 筆）`;
      prevBtn.disabled = currentPage <= 1;
      nextBtn.disabled = currentPage >= totalPages;

      updateSelectionState();
    }

    headerSelectAllCheckbox.addEventListener("change", () => {
      const filtered = getFiltered();
      const effectivePageSize = pageSize === "all" ? Math.max(filtered.length, 1) : pageSize;
      const startIndex = (currentPage - 1) * effectivePageSize;
      const pageItems = filtered.slice(startIndex, startIndex + effectivePageSize);
      for (const item of pageItems) {
        if (headerSelectAllCheckbox.checked) {
          selected.add(item.candidate_id);
        } else {
          selected.delete(item.candidate_id);
        }
      }
      renderCandidatesTable();
    });

    prevBtn.addEventListener("click", () => {
      if (currentPage > 1) {
        currentPage--;
        renderCandidatesTable();
      }
    });

    nextBtn.addEventListener("click", () => {
      currentPage++;
      renderCandidatesTable();
    });

    renderCandidatesTable();
  } else {
    panel.append(el("p", "empty", "目前沒有待處理候選。"));
  }

  // Ongoing cases section
  panel.append(el("h3", "", `進行中案件（${caseData.total || 0}）`));
  if ((caseData.items || []).length) {
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>案件</th><th>狀態</th><th>優先級</th><th>負責單位／承辦</th><th>下一步</th></tr></thead>";
    const body = el("tbody");
    for (const item of caseData.items) {
      const action = el("td");
      const detail = el("button", "", "查看與處理");
      detail.addEventListener("click", () => showQualityCaseDetail(item.case_id));
      action.append(detail);
      const row = el("tr");
      row.append(
        el("td", "", item.title),
        el("td", "", statusLabels[item.status] || item.status),
        el("td", "", item.priority),
        el("td", "", `${item.owner_unit_id} / ${item.assignee_id || "未指派"}`),
        action,
      );
      body.append(row);
    }
    table.append(body);
    const caseScroll = el("div", "table-responsive");
    caseScroll.append(table);
    panel.append(caseScroll);
  } else {
    panel.append(el("p", "empty", "目前沒有進行中案件。"));
  }
  return panel;
}

async function buildGapPanel() {
  const panel = el("section", "panel");
  panel.append(el("h2", "", "Knowledge Gap 排序"));
  const data = await api("/api/gaps/summary?days=30");
  panel.append(el("p", "metric-label", `規則版本：${data.scoreVersion}｜Taxonomy：${data.taxonomyVersion}`));
  if (!(data.items || []).length) {
    panel.append(el("p", "empty", "目前沒有可評分的 Gap。"));
    return panel;
  }
  const table = el("table");
  table.innerHTML = "<thead><tr><th>Issue</th><th>Gap Score</th><th>頻率</th><th>無答案</th><th>負評</th><th>轉人工</th><th>成本</th></tr></thead>";
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    row.append(
      el("td", "", item.displayName || item.issueTypeId),
      el("td", "", item.gapScore.toFixed(2)),
      el("td", "", item.components.frequency.toFixed(2)),
      el("td", "", item.components.noAnswerRate.toFixed(2)),
      el("td", "", item.components.negativeFeedbackRate.toFixed(2)),
      el("td", "", item.components.handoffRate.toFixed(2)),
      el("td", "", item.components.estimatedCostUsd.toFixed(2)),
    );
    body.append(row);
  }
  table.append(body);
  const gapScroll = el("div", "table-responsive");
  gapScroll.append(table);
  panel.append(gapScroll);
  const clusterData = await api("/api/question-clusters");
  const allowed = new Set(capabilities?.capabilities || []);
  const clusterActions = el("div", "filter-bar");
  if (allowed.has("ops.quality.write")) {
    const generate = el("button", "", "產生單位／問題類型分組");
    generate.addEventListener("click", async () => {
      await api("/api/question-clusters/generate", { method: "POST" });
      await renderQuality();
    });
    clusterActions.append(generate);
  }
  panel.append(
    el("h3", "", `單位／問題類型分組（${clusterData.total || 0}）`),
    el(
      "p",
      "metric-label",
      "依 owner unit + issue type 分組，不是語意聚類。確認需求後再導入 embedding／人工審核。",
    ),
    clusterActions,
  );
  for (const cluster of (clusterData.items || []).filter((item) => item.status !== "SUPERSEDED")) {
    const row = el("div", "filter-bar");
    row.append(
      el("strong", "", cluster.name),
      el(
        "span",
        "metric-label",
        `${cluster.status}｜${cluster.grouping_method || "OWNER_UNIT_ISSUE_TYPE"}｜頻率 ${cluster.frequency}｜rev ${cluster.revision}`,
      ),
    );
    if (allowed.has("ops.quality.write") && cluster.status === "CANDIDATE") {
      for (const [action, label] of [["ACCEPT", "接受"], ["REJECT", "拒絕"], ["RENAME", "重新命名"]]) {
        const button = el("button", "", label);
        button.addEventListener("click", async () => {
          const name = action === "RENAME" ? window.prompt("Cluster 名稱", cluster.name) : null;
          if (action === "RENAME" && !name?.trim()) return;
          await api("/api/question-clusters/correct", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ cluster_ids: [cluster.cluster_id], action, name }),
          });
          await renderQuality();
        });
        row.append(button);
      }
    }
    panel.append(row);
  }
  return panel;
}

async function renderPrompts() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const [govData, candidateData, taxonomy, examples, harnessStatus] = await Promise.all([
      api("/api/governance/prompts"),
      api("/api/prompts/candidates"),
      api("/api/taxonomy"),
      api("/api/examples?status=VERIFIED"),
      api("/api/governance/eval-harness").catch(() => null),
    ]);
    const item = (govData.items || [])[0];
    const active = item?.active || {};
    const promptId = item?.prompt?.prompt_id;
    const harnessDetail = harnessStatus || {
      configured: false,
      available: false,
      releaseEligible: false,
      mode: "unset",
      detail: "eval_harness_not_configured",
    };
    let harnessLabel = "評測執行器：未設定";
    if (harnessDetail.configured === false || harnessDetail.mode === "unset") {
      harnessLabel = "評測執行器：未設定（正式發布閘道不可用）";
    } else if (!harnessDetail.available) {
      harnessLabel = `評測執行器：執行失敗／不可用（${harnessDetail.detail || harnessDetail.mode}）`;
    } else if (!harnessDetail.releaseEligible) {
      harnessLabel = `評測執行器：已就緒但非正式閘道（${harnessDetail.name || harnessDetail.mode}；品質／模擬結果不可當作放行）`;
    } else {
      harnessLabel = `評測執行器：正式閘道就緒（${harnessDetail.name}）`;
    }
    const activePanel = el("section", "panel");
    activePanel.append(
      el("h2", "", "Active Issue Extractor Prompt"),
      el("p", "metric-label", `環境影響：正式 Prompt 變更需候選 → Eval → 核准 → Canary → 啟用`),
      el("p", "metric-label", harnessLabel),
      el("p", "metric-label", `Version ${active.version || "-"}｜${active.status || "-"}｜${active.activated_at || active.created_at || "-"}`),
      el("p", "metric-label", `Content Hash ${active.content_hash || "-"}｜核准者 ${active.approved_by || "-"}`),
    );
    if (active.template) {
      const inspect = el("button", "", "檢視內容");
      inspect.addEventListener("click", () => {
        showContentModal("Active Prompt", el("pre", "json-block", active.template));
      });
      activePanel.append(inspect);
    }

    const candidatePanel = el("section", "panel");
    candidatePanel.append(el("h2", "", "Prompt Candidates（Phase 3 治理）"));
    const verified = (examples.items || []).filter((entry) => entry.dataset_version);
    if (allowed.has("ops.prompts.candidates.create") && verified.length && promptId) {
      const form = el("form", "form-grid");
      form.append(
        exampleSelect(
          "Verified Dataset",
          "dataset_version",
          verified.map((entry) => [
            entry.dataset_version,
            `${entry.dataset_version}｜${entry.expected_route} ${entry.label}`,
          ]),
        ),
      );
      const generate = el("button", "", "建立候選");
      generate.type = "submit";
      form.append(generate);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        try {
          await api(`/api/governance/prompts/${promptId}/candidates`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              dataset_version: values.get("dataset_version"),
              taxonomy_version: taxonomy.taxonomyVersion,
            }),
          });
          await renderPrompts();
        } catch (error) {
          showContentModal("候選產生失敗", el("div", "error", error.message));
        }
      });
      candidatePanel.append(form);
    }
    const versions = (item?.versions || []);
    const detail = promptId ? await api(`/api/governance/prompts/${promptId}`) : { versions: [] };
    const rows = detail.versions || versions;
    if (rows.length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Version</th><th>狀態</th><th>Dataset</th><th>建立者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const version of rows.slice().reverse()) {
        const actions = el("td");
        const compare = el("button", "", "比較／風險");
        compare.addEventListener("click", async () => {
          const result = await api(`/api/governance/prompts/${promptId}/versions/${version.version_id}/diff`);
          const content = el("div");
          content.append(
            el("p", "", `Active ${result.active.version}`),
            el("p", "", `Candidate ${result.candidate.version}`),
            el("p", "", `Critical Eval: ${result.eval ? (result.eval.critical_passed ? "PASS" : "FAIL") : "尚未評測"}`),
          );
          if (result.diff) content.append(el("pre", "json-block", result.diff));
          showContentModal("Prompt 比較", content);
        });
        actions.append(compare);
        const addAction = (label, path, payload) => {
          const button = el("button", "", label);
          button.addEventListener("click", async () => {
            const reason = window.prompt(`${label}原因`);
            if (!reason || reason.trim().length < 3) return;
            await api(path, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim(), ...payload }),
            });
            await renderPrompts();
          });
          actions.append(button);
        };
        if (allowed.has("ops.prompts.eval.run") && ["CANDIDATE", "EVALUATED"].includes(version.status)) {
          const evalButton = el("button", "", "執行 Eval");
          evalButton.addEventListener("click", async () => {
            if (!harnessDetail.available) {
              window.alert(
                harnessDetail.configured === false
                  ? "評測執行器尚未設定，無法執行正式評測。"
                  : `評測執行器不可用：${harnessDetail.detail || "unknown"}`,
              );
              return;
            }
            const result = await api(
              `/api/governance/prompts/${promptId}/versions/${version.version_id}/eval`,
              { method: "POST" },
            );
            if (result?.eval?.critical_passed === false) {
              window.alert("評測完成：品質／閘道不合格（critical 未通過）。");
            } else if (result?.eval?.quality_passed === false) {
              window.alert("評測完成：品質不合格。");
            } else if (result?.eval?.status === "INCOMPLETE") {
              window.alert("評測完成：流程不完整（執行失敗或 harness 不可用），非正式放行。");
            }
            await renderPrompts();
          });
          actions.append(evalButton);
        }
        if (allowed.has("ops.prompts.approve") && version.status === "EVALUATED") {
          addAction("送審核准", `/api/governance/prompts/${promptId}/versions/${version.version_id}/approve`, {});
        }
        if (allowed.has("ops.prompts.canary") && version.status === "APPROVED") {
          addAction("開始 Canary", `/api/governance/prompts/${promptId}/versions/${version.version_id}/canary`, {
            percent: 5,
            environment: "prod",
          });
        }
        if (allowed.has("ops.prompts.canary") && version.status === "CANARY") {
          addAction("停止 Canary", `/api/governance/prompts/${promptId}/canary/stop`, {});
          const evaluate = el("button", "", "評估 Canary 指標");
          evaluate.addEventListener("click", async () => {
            const sample = window.prompt("樣本數", "50");
            if (!sample) return;
            const errorRate = window.prompt("錯誤率 0-1", "0.05");
            if (errorRate == null) return;
            const negative = window.prompt("負評率 0-1", "0.1");
            if (negative == null) return;
            const handoff = window.prompt("Handoff 率 0-1", "0.2");
            if (handoff == null) return;
            const result = await api(`/api/governance/prompts/${promptId}/canary/evaluate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                sample_size: Number(sample),
                error_rate: Number(errorRate),
                negative_feedback_rate: Number(negative),
                handoff_rate: Number(handoff),
                safety_alerts: 0,
              }),
            });
            showContentModal("Canary 評估", el("pre", "json-block", JSON.stringify(result, null, 2)));
            await renderPrompts();
          });
          actions.append(evaluate);
        }
        if (allowed.has("ops.prompts.activate") && version.status === "CANARY") {
          addAction("啟用正式版", `/api/governance/prompts/${promptId}/versions/${version.version_id}/activate`, {});
        }
        const row = el("tr");
        row.append(
          el("td", "", version.version),
          el("td", "", version.status),
          el("td", "", version.dataset_version || "-"),
          el("td", "", version.created_by),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const promptScroll = el("div", "table-responsive");
      promptScroll.append(table);
      candidatePanel.append(promptScroll);
    } else {
      candidatePanel.append(el("p", "empty", "目前沒有 Prompt Candidate。"));
    }
    if (allowed.has("ops.prompts.rollback")) {
      const rollback = el("button", "", "回復上一健康版本");
      rollback.addEventListener("click", async () => {
        const reason = window.prompt("回復原因");
        if (!reason || reason.trim().length < 3) return;
        await api(`/api/governance/prompts/${promptId}/rollback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: reason.trim() }),
        });
        await renderPrompts();
      });
      candidatePanel.append(rollback);
    }
    // Keep Phase 2 POC list visible for continuity.
    if ((candidateData.items || []).length) {
      candidatePanel.append(el("p", "metric-label", `Phase 2 POC candidates: ${candidateData.items.length}`));
    }
    app.replaceChildren(activePanel, candidatePanel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderModels() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/models");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "模型／Provider Allowlist"));
    for (const item of data.items || []) {
      const active = item.active || {};
      const configId = item.config?.config_id;
      panel.append(
        el("p", "", `${configId}｜${active.provider || "-"} / ${active.model_id || "-"}｜${active.status || "無正式版"}`),
        el("p", "metric-label", `Secret Ref ${active.secret_ref || "-"}｜Fallback ${active.fallback_model_id || "-"}`),
      );
      if (allowed.has("ops.models.read") && configId) {
        const simulate = el("button", "", "模擬 Fallback");
        simulate.addEventListener("click", async () => {
          const error = window.prompt("觸發錯誤", "TIMEOUT");
          if (!error) return;
          const result = await api(`/api/governance/models/${configId}/simulate-fallback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ error }),
          });
          showContentModal("Fallback 模擬", el("pre", "json-block", JSON.stringify(result, null, 2)));
        });
        panel.append(simulate);
      }
      if (allowed.has("ops.models.activate") && configId) {
        const rollback = el("button", "", "回復上一健康模型");
        rollback.addEventListener("click", async () => {
          const reason = window.prompt("回復原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/models/${configId}/rollback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderModels();
        });
        panel.append(rollback);
      }
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderFlags() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/flags");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "Feature Flags"));
    const items = data.items || [];
    if (!items.length) {
      panel.append(el("p", "empty", "目前無 Feature Flag。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Flag</th><th>Effective</th><th>Safety Locked</th><th>Owner</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of items) {
        const row = el("tr");
        const actions = el("td");
        const flagId = item.flag.flag_id;
        if (allowed.has("ops.flags.read")) {
          const effective = el("button", "", "查有效值");
          effective.addEventListener("click", async () => {
            const result = await api(`/api/governance/flags/${flagId}/effective?environment=lab`);
            showContentModal(`${flagId} effective`, el("pre", "json-block", JSON.stringify(result, null, 2)));
          });
          actions.append(effective);
        }
        const effCell = el("td");
        effCell.append(statusBadge(item.effective ? "ENABLED" : "DISABLED"));
        const lockCell = el("td");
        lockCell.append(statusBadge(item.flag.safety_locked ? "LOCKED" : "UNLOCKED"));
        row.append(
          el("td", "", flagId),
          effCell,
          lockCell,
          el("td", "", item.flag.owner || "-"),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      panel.append(scroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderRoles() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/roles");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "角色映射請求"));
    if (allowed.has("ops.roles.request")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("目標 Principal", "target_principal", ""),
        faqField("目標角色（可空）", "target_role", ""),
        faqField("新增 capabilities（逗號分隔）", "add_capabilities", ""),
        faqField("移除 capabilities（逗號分隔）", "remove_capabilities", ""),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "送出角色請求");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        const reason = String(values.get("reason") || "").trim();
        if (reason.length < 3) return;
        const split = (raw) => String(raw || "").split(",").map((item) => item.trim()).filter(Boolean);
        await api("/api/governance/roles/requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_principal: String(values.get("target_principal") || "").trim(),
            target_role: String(values.get("target_role") || "").trim() || null,
            add_capabilities: split(values.get("add_capabilities")),
            remove_capabilities: split(values.get("remove_capabilities")),
            reason,
          }),
        });
        await renderRoles();
      });
      panel.append(form);
    }
    if (allowed.has("ops.roles.revoke")) {
      const revoke = el("button", "", "緊急撤權");
      revoke.addEventListener("click", async () => {
        const principal = window.prompt("要撤權的 principal");
        if (!principal) return;
        const reason = window.prompt("撤權原因");
        if (!reason || reason.trim().length < 3) return;
        await api("/api/governance/roles/revoke", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ principal: principal.trim(), reason: reason.trim() }),
        });
        await renderRoles();
      });
      panel.append(revoke);
    }
    const items = (data.items || []).slice().reverse();
    if (!items.length) {
      panel.append(el("p", "empty", "目前沒有角色映射請求。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Change</th><th>Principal</th><th>狀態</th><th>請求者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const change of items) {
        const actions = el("td");
        if (allowed.has("ops.roles.approve") && change.status === "REQUESTED") {
          const approve = el("button", "", "核准");
          approve.addEventListener("click", async () => {
            const reason = window.prompt("核准原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/roles/${change.change_id}/approve`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderRoles();
          });
          actions.append(approve);
        }
        const statusCell = el("td");
        statusCell.append(statusBadge(change.status));
        const row = el("tr");
        row.append(
          el("td", "", change.change_id.slice(0, 8)),
          el("td", "", change.target_principal),
          statusCell,
          el("td", "", change.requested_by),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      panel.append(scroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderRetention() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/retention");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "Retention Policies"));
    if (allowed.has("ops.retention.write")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("Policy ID", "policy_id", "operational-events"),
        faqField("TTL days", "ttl_days", "365"),
        faqField("Migration plan", "migration_plan", "archive then delete"),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "建立 Retention 候選");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        await api("/api/governance/retention/candidates", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            policy_id: String(values.get("policy_id") || "").trim(),
            ttl_days: Number(values.get("ttl_days") || 365),
            migration_plan: String(values.get("migration_plan") || "").trim(),
            reason: String(values.get("reason") || "").trim(),
          }),
        });
        await renderRetention();
      });
      panel.append(form);
    }
    const items = (data.items || []).slice().reverse();
    if (!items.length) {
      panel.append(el("p", "empty", "目前無 Retention 政策紀錄。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Policy</th><th>TTL</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of items) {
        const actions = el("td");
        if (allowed.has("ops.retention.write") && item.status === "CANDIDATE") {
          const approve = el("button", "", "核准");
          approve.addEventListener("click", async () => {
            const reason = window.prompt("核准原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/retention/${item.version_id}/approve`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderRetention();
          });
          actions.append(approve);
        }
        if (allowed.has("ops.retention.write") && item.status === "APPROVED") {
          const activate = el("button", "", "啟用");
          activate.addEventListener("click", async () => {
            const reason = window.prompt("啟用原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/retention/${item.version_id}/activate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderRetention();
          });
          actions.append(activate);
        }
        const statusCell = el("td");
        statusCell.append(statusBadge(item.status));
        const row = el("tr");
        row.append(
          el("td", "", item.policy_id),
          el("td", "", `${item.ttl_days} 天`),
          statusCell,
          el("td", "", item.created_by),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      panel.append(scroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderMasking() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const data = await api("/api/governance/masking");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "遮罩政策版本"));
    if (allowed.has("ops.retention.write")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("Policy version", "policy_version", "mask-v2"),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "建立遮罩候選");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        await api("/api/governance/masking/candidates", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            policy_version: String(values.get("policy_version") || "").trim(),
            reason: String(values.get("reason") || "").trim(),
          }),
        });
        await renderMasking();
      });
      panel.append(form);
    }
    const items = (data.items || []).slice().reverse();
    if (!items.length) {
      panel.append(el("p", "empty", "目前無遮罩政策版本紀錄。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Version</th><th>Hash</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of items) {
        const actions = el("td");
        if (allowed.has("ops.retention.write") && item.status === "CANDIDATE") {
          const approve = el("button", "", "核准");
          approve.addEventListener("click", async () => {
            const reason = window.prompt("核准原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/masking/${item.version_id}/approve`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderMasking();
          });
          actions.append(approve);
        }
        if (allowed.has("ops.retention.write") && item.status === "APPROVED") {
          const activate = el("button", "", "啟用");
          activate.addEventListener("click", async () => {
            const reason = window.prompt("啟用原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/masking/${item.version_id}/activate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderMasking();
          });
          actions.append(activate);
        }
        const statusCell = el("td");
        statusCell.append(statusBadge(item.status));
        const row = el("tr");
        row.append(
          el("td", "", item.policy_version),
          el("td", "", (item.rules_hash || "").slice(0, 12)),
          statusCell,
          el("td", "", item.created_by),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      panel.append(scroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderGovernanceSearch() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const panel = el("section", "panel");
    panel.append(el("h2", "", "權限感知全域搜尋"));
    const form = el("form", "form-grid");
    const input = el("input");
    input.name = "q";
    input.placeholder = "搜尋 Prompt / Flag / Model / Role / Retention / FAQ / Example / Issue / Quality / Audit";
    const submit = el("button", "", "搜尋");
    submit.type = "submit";
    form.append(input, submit);
    const results = el("div");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = (input.value || "").trim();
      if (!query) return;
      results.replaceChildren(el("div", "empty", "搜尋中…"));
      try {
        const data = await api(`/api/governance/search?q=${encodeURIComponent(query)}`);
        results.replaceChildren();
        const summaryBar = el("div", "filter-bar");
        summaryBar.style.margin = "1rem 0";
        summaryBar.append(badge(`搜尋結果：${data.count} 筆`, data.count > 0 ? "success" : "neutral"));
        results.append(summaryBar);

        if (!data.items || !data.items.length) {
          results.append(el("p", "empty", "未找到符合關鍵字的資源。"));
        } else {
          const listContainer = el("div");
          listContainer.style.display = "flex";
          listContainer.style.flexDirection = "column";
          listContainer.style.gap = "0.75rem";
          for (const item of data.items) {
            const card = el("div", "metric");
            card.style.flexDirection = "row";
            card.style.justifyContent = "space-between";
            card.style.alignItems = "center";
            card.style.padding = "0.85rem 1.15rem";

            const info = el("div");
            info.style.minWidth = "0";
            const titleRow = el("div");
            titleRow.style.display = "flex";
            titleRow.style.alignItems = "center";
            titleRow.style.gap = "0.6rem";
            titleRow.style.marginBottom = "0.3rem";

            const typeBadge = badge(item.type, "accent");
            const titleStrong = el("strong", "", item.title || item.id || "未命名");
            titleStrong.style.fontSize = "0.95rem";
            titleRow.append(typeBadge, titleStrong);

            const snippetP = el("div", "metric-label", item.snippet || "-");
            snippetP.style.textTransform = "none";
            snippetP.style.letterSpacing = "normal";
            snippetP.style.fontSize = "0.8rem";
            info.append(titleRow, snippetP);

            card.append(info);
            listContainer.append(card);
          }
          results.append(listContainer);
        }
      } catch (err) {
        results.replaceChildren(el("div", "error", `搜尋失敗：${err.message || err}`));
      }
    });
    panel.append(form, results);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderBudgets() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const [policyData, alertData] = await Promise.all([
      api("/api/budget-policies"),
      api("/api/alerts"),
    ]);
    const policyPanel = el("section", "panel");
    const policyHeader = el("div", "section-header-row");
    policyHeader.style.display = "flex";
    policyHeader.style.justifyContent = "space-between";
    policyHeader.style.alignItems = "center";
    policyHeader.append(el("h2", "", "Budget Policies"));
    if (allowed.has("ops.budget.evaluate")) {
      const evalAllBtn = el("button", "btn", "全部自動評估（含個人50元門檻）");
      evalAllBtn.addEventListener("click", async () => {
        try {
          evalAllBtn.disabled = true;
          evalAllBtn.textContent = "評估中…";
          const res = await api("/api/budget-policies/evaluate-all", { method: "POST" });
          showContentModal(
            "自動評估結果",
            el("p", "", `已評估 ${res.evaluatedPolicies} 項政策、${res.evaluatedUsers} 位使用者每日額度；產生 ${res.triggeredAlerts} 項告警，已發送 ${res.dispatchedDeliveries} 筆通知。`),
          );
          await renderBudgets();
        } catch (err) {
          showContentModal("評估失敗", el("div", "error", err.message));
        } finally {
          evalAllBtn.disabled = false;
          evalAllBtn.textContent = "全部自動評估（含個人50元門檻）";
        }
      });
      policyHeader.append(evalAllBtn);
    }
    policyPanel.append(policyHeader);
    if (allowed.has("ops.budget.write")) {
      const form = el("form", "form-grid");
      const ownerOptions = (capabilities.ownerUnitIds || []).map((item) => [item, item]);
      const targetOptions = (policyData.notificationTargets || []).map((item) => [item, item]);
      form.append(
        exampleSelect("Scope", "scope_type", [
          ["PERSONAL", "Personal"], ["SERVICE", "Service"], ["TEAM", "Team"],
          ["TENANT", "Tenant"], ["GLOBAL", "Global"],
        ]),
        faqField("Scope ID", "scope_id", ""),
        exampleSelect("Period", "period", [["DAILY", "Daily"], ["MONTHLY", "Monthly"]]),
        exampleSelect("Measure", "measure", [
          ["TWD", "TWD"], ["USD", "USD"], ["TOKEN", "Token"],
          ["LLM_CALL_COUNT", "LLM Call Count"],
        ]),
        faqField("Warning Threshold", "warning_threshold", ""),
        faqField("Critical Threshold", "critical_threshold", ""),
        exampleSelect("Owner Unit", "owner_unit_id", ownerOptions),
        exampleSelect("Notification Target", "notification_target_id", targetOptions),
      );
      const submit = el("button", "", "建立 Policy");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        try {
          await api("/api/budget-policies", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              scope_type: values.get("scope_type"), scope_id: values.get("scope_id"),
              period: values.get("period"), measure: values.get("measure"),
              warning_threshold: Number(values.get("warning_threshold")),
              critical_threshold: Number(values.get("critical_threshold")),
              owner_unit_id: values.get("owner_unit_id"),
              notification_target_ids: [values.get("notification_target_id")],
            }),
          });
          await renderBudgets();
        } catch (error) {
          showContentModal("建立 Policy 失敗", el("div", "error", error.message));
        }
      });
      policyPanel.append(form);
    }
    if ((policyData.items || []).length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Scope</th><th>期間 / 指標</th><th>門檻</th><th>狀態</th><th>版本</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const policy of policyData.items) {
        const actions = el("td");
        if (allowed.has("ops.budget.evaluate") && policy.enabled) {
          const evaluate = el("button", "", "立即評估");
          evaluate.addEventListener("click", async () => {
            try {
              const result = await api(`/api/budget-policies/${policy.policy_id}/evaluate`, { method: "POST" });
              const usage = result.usage;
              showContentModal(
                "Policy 評估結果",
                el("p", "", `Actual ${usage.actualValue}｜Coverage ${(usage.coverage * 100).toFixed(1)}%｜${usage.periodKey}`),
              );
              await renderBudgets();
            } catch (error) {
              showContentModal("評估失敗", el("div", "error", error.message));
            }
          });
          actions.append(evaluate);
        }
        if (allowed.has("ops.budget.write")) {
          const state = el("button", "", policy.enabled ? "停用" : "啟用");
          state.addEventListener("click", async () => {
            const reason = window.prompt(`${policy.enabled ? "停用" : "啟用"}原因`);
            if (!reason?.trim()) return;
            await api(`/api/budget-policies/${policy.policy_id}/state`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_etag: policy.etag, enabled: !policy.enabled, reason }),
            });
            await renderBudgets();
          });
          actions.append(state);
        }
        const row = el("tr");
        row.append(
          el("td", "", `${policy.scope_type}:${policy.scope_id}`),
          el("td", "", `${policy.period} / ${policy.measure}`),
          el("td", "", `${policy.warning_threshold} / ${policy.critical_threshold}`),
          el("td", "", policy.enabled ? "ENABLED" : "DISABLED"),
          el("td", "", `${policy.pricing_version} / ${policy.exchange_rate_version}`),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const policyScroll = el("div", "table-responsive");
      policyScroll.append(table);
      policyPanel.append(policyScroll);
    } else {
      policyPanel.append(el("p", "empty", "目前沒有 Budget Policy。"));
    }

    const alertPanel = el("section", "panel");
    alertPanel.append(el("h2", "", `Alerts（${alertData.total || 0}）`));
    if ((alertData.items || []).length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Type</th><th>Severity</th><th>Scope</th><th>Actual / Threshold / 說明</th><th>Coverage</th><th>狀態</th><th>通知</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const alert of alertData.items) {
        const actions = el("td");
        if (allowed.has("ops.alerts.manage") && alert.status !== "RESOLVED") {
          const alertActions = alert.status === "OPEN"
            ? [["acknowledge", "Acknowledge"], ["resolve", "Resolve"]]
            : [["resolve", "Resolve"]];
          for (const [action, label] of alertActions) {
            const button = el("button", "", label);
            button.addEventListener("click", async () => {
              const reason = window.prompt(`${label} 原因`);
              if (!reason?.trim()) return;
              await api(`/api/alerts/${alert.alert_id}/${action}`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ expected_etag: alert.etag, reason }),
              });
              await renderBudgets();
            });
            actions.append(button);
          }
          for (const deliveryItem of (alert.deliveries || []).filter((item) => item.status === "FAILED")) {
            const retry = el("button", "", "重試通知");
            retry.addEventListener("click", async () => {
              await api(`/api/alerts/${alert.alert_id}/deliveries/${deliveryItem.delivery_id}/retry`, {
                method: "POST",
              });
              await renderBudgets();
            });
            actions.append(retry);
          }
        }
        const delivery = (alert.deliveries || [])
          .map((item) => `${item.target_id}:${item.status}`).join(", ") || "-";
        const typeBadge = alert.alert_type || "BUDGET_THRESHOLD";
        const detailText = alert.alert_type === "BUDGET_THRESHOLD"
          ? `${alert.actual_value} / ${alert.threshold}`
          : (alert.message || `${alert.actual_value} / ${alert.threshold}`);
        const row = el("tr");
        row.append(
          el("td", "", typeBadge),
          el("td", "", alert.severity),
          el("td", "", `${alert.scope_type}:${alert.scope_id}`),
          el("td", "", detailText),
          el("td", "", `${(alert.coverage * 100).toFixed(1)}%`),
          el("td", "", alert.status),
          el("td", "", delivery),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const alertScroll = el("div", "table-responsive");
      alertScroll.append(table);
      alertPanel.append(alertScroll);
    } else {
      alertPanel.append(el("p", "empty", "目前沒有 Alert。"));
    }
    app.replaceChildren(policyPanel, alertPanel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

async function renderQuality(state = {}) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const navFilters = loadNavFilters();
    const period = state.period || { preset: "30d" };
    const savedFilters = state.filters || {};
    const filters = periodParams(period);
    filters.set("limit", "25");
    if (state.cursor) filters.set("cursor", state.cursor);
    const rating =
      savedFilters.rating ||
      (navFilters.view === "quality" ? navFilters.rating : "");
    const issueTypeId =
      savedFilters.issueTypeId ||
      (navFilters.view === "quality" ? navFilters.issueTypeId : "");
    const reason = savedFilters.reason || "";
    const resolved = savedFilters.resolved || "";
    const handoff = savedFilters.handoff || "";
    if (rating) filters.set("rating", rating);
    if (issueTypeId) filters.set("issue_type_id", issueTypeId);
    if (reason) filters.set("reason", reason);
    if (resolved) filters.set("resolved", resolved);
    if (handoff) filters.set("handoff", handoff);

    const [qualityLoopPanel, gapPanel, feedback] = await Promise.all([
      buildQualityLoopPanel(),
      buildGapPanel(),
      api(`/api/feedback?${filters.toString()}`),
    ]);

    if (navFilters.view === "quality" && navFilters.caseId) {
      await showQualityCaseDetail(navFilters.caseId);
    }

    const panel = el("section", "panel");
    panel.append(el("h2", "", "回饋與待觀察事件"));
    panel.append(
      el(
        "p",
        "metric-label",
        "先處理上方改善案件池；此處用來篩選負評／未解決／轉人工事件，並跳轉對話驗證。",
      ),
    );
    const shortcuts = el("div", "filter-bar");
    shortcuts.append(
      drillLink("文件／FAQ 修正", "knowledge"),
      drillLink("案例集驗證", "examples"),
      drillLink("對話驗證", "conversations"),
    );
    panel.append(shortcuts);
    const filterBar = el("div", "filter-bar quality-filters");
    const issueInput = el("input");
    issueInput.id = "feedback-issue-type";
    issueInput.placeholder = "問題類型（顯示名稱或 ID）";
    issueInput.value = issueTypeId || "";
    const ratingSelect = el("select", "");
    ratingSelect.id = "feedback-rating";
    ratingSelect.innerHTML =
      '<option value="">全部評價</option><option value="UP">好評</option><option value="DOWN">負評</option>';
    if (rating) ratingSelect.value = rating;
    const reasonInput = el("input");
    reasonInput.id = "feedback-reason";
    reasonInput.placeholder = "回饋原因";
    reasonInput.value = reason || "";
    const resolvedSelect = el("select", "");
    resolvedSelect.id = "feedback-resolved";
    resolvedSelect.innerHTML =
      '<option value="">全部解決狀態</option><option value="RESOLVED">已解決</option><option value="UNRESOLVED">未解決</option>';
    if (resolved) resolvedSelect.value = resolved;
    const handoffSelect = el("select", "");
    handoffSelect.id = "feedback-handoff";
    handoffSelect.innerHTML =
      '<option value="">全部轉人工</option><option value="true">有轉人工</option><option value="false">無轉人工</option>';
    if (handoff) handoffSelect.value = handoff;
    const currentFilters = () => ({
      issueTypeId: issueInput.value.trim(),
      rating: ratingSelect.value,
      reason: reasonInput.value.trim(),
      resolved: resolvedSelect.value,
      handoff: handoffSelect.value,
    });
    const applyFilters = el("button", "", "套用篩選");
    applyFilters.addEventListener("click", () =>
      renderQuality({ period, filters: currentFilters(), cursor: "", history: [] }),
    );
    const exportButton = createExportButton("feedback", 30, () => ({
      issue_type_id: issueInput.value || undefined,
      rating: ratingSelect.value || undefined,
      feedback_reason: reasonInput.value || undefined,
      resolved_status: resolvedSelect.value || undefined,
      handoff: handoffSelect.value ? handoffSelect.value === "true" : undefined,
      ...Object.fromEntries(periodParams(period)),
    }));
    filterBar.append(
      issueInput,
      ratingSelect,
      reasonInput,
      resolvedSelect,
      handoffSelect,
      applyFilters,
      exportButton,
    );
    panel.append(filterBar);
    panel.append(
      createPeriodControls(period, (nextPeriod) =>
        renderQuality({
          period: nextPeriod,
          filters: currentFilters(),
          cursor: "",
          history: [],
        }),
      ),
    );

    const ratingLabels = { UP: "好評", DOWN: "負評" };
    if (!feedback.items.length) {
      panel.append(el("p", "empty", "目前沒有符合條件的回饋事件。"));
    } else {
      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>時間</th><th>評價</th><th>問題類型</th><th>來源</th><th>對話</th><th>原因</th><th>動作</th></tr></thead>";
      const body = el("tbody");
      for (const item of feedback.items) {
        const trace = item.trace || {};
        const source = trace.faqKey
          ? `FAQ：${trace.faqKey}`
          : (trace.documentIds || []).join(", ") || "-";
        const row = el("tr");
        row.append(el("td", "", item.occurredAt));
        row.append(el("td", "", ratingLabels[item.rating] || item.rating));
        row.append(
          el(
            "td",
            "",
            trace.issueTypeDisplayName || trace.issueTypeId || String(item.issueId ?? "-"),
          ),
        );
        row.append(el("td", "", source));
        const convLink = el("a", "", "查看對話");
        convLink.href = "#";
        convLink.addEventListener("click", async (event) => {
          event.preventDefault();
          const detail = await api(
            `/api/conversations/${encodeURIComponent(item.conversationId)}`,
          );
          showConversationModal({ ...detail, conversationId: item.conversationId });
        });
        const convCell = el("td");
        convCell.append(convLink);
        row.append(convCell);
        row.append(el("td", "", item.reason ?? "-"));
        const actionCell = el("td");
        actionCell.append(
          drillLink("驗證回答", "conversations", {
            conversationId: item.conversationId || "",
            issueTypeId: trace.issueTypeId || "",
          }),
        );
        row.append(actionCell);
        body.append(row);
      }
      table.append(body);
      const feedbackScroll = el("div", "table-responsive");
      feedbackScroll.append(table);
      panel.append(feedbackScroll);
    }
    const history = state.history || [];
    const pager = el("div", "filter-bar");
    if (history.length) {
      const previous = el("button", "", "上一頁");
      previous.addEventListener("click", () =>
        renderQuality({
          period,
          filters: currentFilters(),
          cursor: history.at(-1),
          history: history.slice(0, -1),
        }),
      );
      pager.append(previous);
    }
    if (feedback.nextCursor) {
      const next = el("button", "", "下一頁");
      next.addEventListener("click", () =>
        renderQuality({
          period,
          filters: currentFilters(),
          cursor: feedback.nextCursor,
          history: [...history, state.cursor || ""],
        }),
      );
      pager.append(next);
    }
    if (pager.childElementCount) panel.append(pager);
    const exportPanel = el("section", "panel");
    exportPanel.append(el("h3", "", "非同步匯出"));
    const csvButton = el("button", "", "建立 CSV 營運摘要匯出");
    csvButton.addEventListener("click", async () => {
      await runExport("csv");
    });
    const xlsxButton = el("button", "", "建立 XLSX 營運摘要匯出");
    xlsxButton.style.marginLeft = "0.5rem";
    xlsxButton.addEventListener("click", async () => {
      await runExport("xlsx");
    });
    exportPanel.append(csvButton, xlsxButton);
    app.replaceChildren(qualityLoopPanel, panel, gapPanel, exportPanel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

async function runExport(
  exportFormat,
  exportType = "operations_summary",
  periodOrDays = 7,
  queryFilters = {},
) {
  let days = 7;
  let preset = undefined;
  let startDate = undefined;
  let endDate = undefined;

  if (typeof periodOrDays === "number") {
    days = periodOrDays;
    preset = `${days}d`;
  } else if (typeof periodOrDays === "object" && periodOrDays !== null) {
    preset = periodOrDays.preset;
    days = periodOrDays.days || (
      preset === "today" || preset === "1d" ? 1 :
      preset === "7d" || preset === "1w" ? 7 :
      preset === "180d" || preset === "6m" || preset === "186d" ? 180 :
      preset === "365d" || preset === "1y" || preset === "12m" ? 365 : 30
    );
    startDate = periodOrDays.startDate || periodOrDays.start_date;
    endDate = periodOrDays.endDate || periodOrDays.end_date;
  }

  const payload = {
    export_type: exportType,
    reason: "UAT export",
    days,
    export_format: exportFormat,
    preset: preset || `${days}d`,
    start_date: startDate,
    end_date: endDate,
    ...queryFilters,
  };

  const created = await api("/api/exports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const job = await pollExport(created.jobId);
  if (job.status === "COMPLETED") {
    const response = await fetch(`/api/exports/${encodeURIComponent(created.jobId)}/download`, {
      headers: authHeaders(),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${exportType.replaceAll("_", "-")}-${created.jobId}.${exportFormat}`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return job;
}

function createExportButton(exportType, periodOrDays, queryFilters = {}) {
  const button = el("button", "", "匯出 CSV");
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "匯出中…";
    try {
      const resolvedPeriod = typeof periodOrDays === "function" ? periodOrDays() : periodOrDays;
      const filters = typeof queryFilters === "function" ? queryFilters() : queryFilters;
      await runExport("csv", exportType, resolvedPeriod, filters);
    } catch (error) {
      showContentModal("匯出失敗", el("div", "error", error.message));
    } finally {
      button.disabled = false;
      button.textContent = "匯出 CSV";
    }
  });
  return button;
}

async function pollExport(jobId) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const job = await api(`/api/exports/${encodeURIComponent(jobId)}`);
    if (job.status === "COMPLETED" || job.status === "FAILED" || job.status === "EXPIRED") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  return { jobId, status: "RUNNING" };
}

async function renderAudit() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = new Set(capabilities?.capabilities || []);
    const [opsAudit, governanceAudit] = await Promise.all([
      api("/api/audit-events").catch(() => ({ items: [] })),
      api("/api/governance/audit").catch(() => ({ items: [] })),
    ]);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "系統稽核紀錄"));

    const actionBar = el("div", "filter-bar");
    actionBar.style.marginBottom = "1rem";
    if (allowed.has("ops.audit.read")) {
      const exportButton = el("button", "", "匯出治理 Audit JSON");
      exportButton.addEventListener("click", async () => {
        try {
          const packageData = await api("/api/governance/audit/export");
          showContentModal("治理 Audit 匯出", el("pre", "json-block", JSON.stringify(packageData, null, 2)));
        } catch (err) {
          showContentModal("匯出失敗", el("div", "error", err.message || err));
        }
      });
      actionBar.append(exportButton);
    }
    panel.append(actionBar);

    function createAuditTable(items, typeLabel) {
      if (!items || !items.length) {
        return el("p", "empty", `目前沒有${typeLabel}稽核事件紀錄。`);
      }
      const table = el("table");
      table.innerHTML = `
        <thead>
          <tr>
            <th>時間</th>
            <th>執行者 / 角色</th>
            <th>操作動作</th>
            <th>目標類型 / ID</th>
            <th>結果</th>
            <th>詳情</th>
          </tr>
        </thead>
      `;
      const body = el("tbody");
      for (const item of items) {
        const row = el("tr");
        const occurred = (item.occurred_at || "").replace("T", " ").slice(0, 19) || "-";
        const actor = `${item.actor_id || "-"}${item.actor_role ? ` (${item.actor_role})` : ""}`;
        const target = item.target_type ? `${item.target_type}：${item.target_id || "-"}` : (item.target_id || "-");

        const resultCell = el("td");
        resultCell.append(statusBadge(item.result || "SUCCESS"));

        const detailCell = el("td");
        const viewBtn = el("button", "", "檢視 Payload");
        viewBtn.addEventListener("click", () => {
          showContentModal(
            `稽核事件詳情：${item.action || item.audit_id}`,
            el("pre", "json-block", JSON.stringify(item, null, 2)),
          );
        });
        detailCell.append(viewBtn);

        row.append(
          el("td", "", occurred),
          el("td", "", actor),
          el("td", "", item.action || "-"),
          el("td", "", target),
          resultCell,
          detailCell,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      return scroll;
    }

    const opsItems = opsAudit.items || [];
    panel.append(el("h3", "", `營運稽核紀錄（${opsItems.length} 筆）`));
    panel.append(createAuditTable(opsItems, "營運"));

    const govItems = governanceAudit.items || [];
    panel.append(el("h3", "", `治理稽核紀錄（${govItems.length} 筆）`));
    panel.append(createAuditTable(govItems, "治理"));

    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

window.addEventListener("message", (event) => {
  if (event.data?.type === "NAVIGATE_CASE" && event.data?.caseId) {
    renderNav("quality");
    void showQualityCaseDetail(event.data.caseId);
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const root = document.getElementById("modal-root");
    if (root && !root.hidden) {
      root.hidden = true;
      root.replaceChildren();
    }
  }
});

window.addEventListener("backoffice:token-expired", async () => {
  if (capabilities?.authMode === "ENTRA") {
    try {
      await showEntraLoginModal({
        message: "您的 Entra 登入憑證已過期，請重新輸入存取權杖以維持連線。",
        reauth: true,
      });
      window.location.reload();
    } catch {
      // Ignored if cancelled
    }
  }
});

window.addEventListener("backoffice:unauthorized", async () => {
  if (capabilities?.authMode === "ENTRA") {
    try {
      await showEntraLoginModal({
        message: "存取遭拒或登入階段已失效 (401 Unauthorized)，請重新驗證身分。",
        reauth: true,
      });
      window.location.reload();
    } catch {
      // Ignored if cancelled
    }
  }
});

boot().catch((error) => {
  console.error("Boot failed:", error);
  const app = document.getElementById("app");
  if (app) {
    app.innerHTML = `<div class="error" style="padding: 2rem;">系統載入失敗：${error.message || error}</div>`;
  }
});
