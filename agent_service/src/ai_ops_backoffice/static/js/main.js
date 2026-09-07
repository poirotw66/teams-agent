import {
  api,
  el,
  ensureAuth,
  saveAuthHeaders,
  loadAuthHeaders,
  clearAuthHeaders,
  logout,
  getTokenExpiryDetails,
  showEntraLoginModal,
} from "./api.js";
import { showContentModal, closeContentModal } from "./components/modal.js";
import { enterPage } from "./app/lifecycle.js";
import {
  canUseKnowledgeUi,
  setCapabilities,
} from "./app/capabilities.js";
import {
  ROLE_DEFAULT_WORKSPACE,
  WORKSPACE_KEY,
} from "./app/workspaces.js";
import {
  activeWorkspaceId,
  buildLocationHash,
  isSyncingLocationHash,
  loadNavFilters,
  navigateTo,
  parseLocationHash,
  saveNavFilters,
  setKnownViews,
  syncLocationHash,
  workspaceForView,
} from "./app/navigation.js";
import { bindShellRoutes, firstVisibleView, renderNav, visibleWorkspaces } from "./app/shell.js";
import { auditPage } from "./views/audit.js";
import { budgetsPage } from "./views/budgets.js";
import { conversationsPage } from "./views/conversations.js";
import { costsPage } from "./views/costs.js";
import { flagsPage } from "./views/flags.js";
import { healthPage } from "./views/health.js";
import { issuesPage } from "./views/issues.js";
import { maskingPage } from "./views/masking.js";
import { modelsPage } from "./views/models.js";
import { examplesPage } from "./views/examples.js";
import {
  knowledgeDocumentPage,
  knowledgePage,
  knowledgePortalPage,
} from "./views/knowledge.js";
import { overviewPage } from "./views/overview.js";
import { promptsPage } from "./views/prompts.js";
import { qualityPage, showQualityCaseDetail } from "./views/quality.js";
import { retentionPage } from "./views/retention.js";
import { rolesPage } from "./views/roles.js";
import { routesPage } from "./views/routes.js";
import { searchPage } from "./views/search.js";

const LIFECYCLE_VIEWS = new Set([
  "costs",
  "health",
  "routes",
  "issues",
  "budgets",
  "audit",
  "models",
  "flags",
  "prompts",
  "roles",
  "retention",
  "masking",
  "search",
  "overview",
  "conversations",
  "quality",
  "knowledge",
  "knowledgeDocument",
  "knowledgePortal",
  "examples",
]);

const routes = {
  overview: () => enterPage(overviewPage),
  conversations: (state) => enterPage(conversationsPage, { state: state || {} }),
  issues: (state) => enterPage(issuesPage, { state: state || { preset: "30d" } }),
  routes: (state) => enterPage(routesPage, { state: state || { preset: "30d" } }),
  costs: (state) => enterPage(costsPage, { state: state || { preset: "30d" } }),
  budgets: () => enterPage(budgetsPage),
  health: () => enterPage(healthPage),
  knowledge: () => enterPage(knowledgePage),
  knowledgeDocument: () => enterPage(knowledgeDocumentPage),
  knowledgePortal: () => enterPage(knowledgePortalPage),
  examples: () => enterPage(examplesPage),
  quality: (state) => enterPage(qualityPage, { state: state || {} }),
  prompts: () => enterPage(promptsPage),
  models: () => enterPage(modelsPage),
  flags: () => enterPage(flagsPage),
  roles: () => enterPage(rolesPage),
  retention: () => enterPage(retentionPage),
  masking: () => enterPage(maskingPage),
  search: () => enterPage(searchPage),
  audit: () => enterPage(auditPage),
};

setKnownViews(Object.keys(routes));



let capabilities = null;

async function boot() {
  const authConfig = await fetch("/api/auth/config").then((response) => response.json());
  await ensureAuth(authConfig);
  capabilities = await api("/api/capabilities");
  setCapabilities(capabilities);
  const defaultWorkspace =
    ROLE_DEFAULT_WORKSPACE[capabilities.role] || visibleWorkspaces()[0]?.id || "platform";
  if (!sessionStorage.getItem(WORKSPACE_KEY)) {
    sessionStorage.setItem(WORKSPACE_KEY, defaultWorkspace);
  }
  renderTopbarActions();
  window.addEventListener("hashchange", async () => {
    if (isSyncingLocationHash()) {
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

bindShellRoutes({ routes, lifecycleViews: LIFECYCLE_VIEWS });



















window.addEventListener("message", (event) => {
  if (event.data?.type === "NAVIGATE_CASE" && event.data?.caseId) {
    renderNav("quality");
    void showQualityCaseDetail(event.data.caseId);
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeContentModal();
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
