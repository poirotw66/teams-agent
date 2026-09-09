/**
 * BU task-oriented shell (U1) configuration.
 * Visual / IA baseline: outputs/bu-ux-prototype-v1 (Teams brand).
 */

export const BU_SHELL_STORAGE_KEY = "ai_ops_bu_shell_v1";
export const BU_SHELL_FLAG_ID = "bu_ui_shell_v1";

/** Primary BU nav: [viewId, label, capability, group]. */
export const BU_PRIMARY_NAV = [
  ["workHub", "我的工作", "bu.work.ui", "daily"],
  ["quality", "改善案件", "bu.quality.nav", "daily"],
  ["contentLists", "知識內容", "content.hub", "daily"],
  ["conversations", "對話紀錄", "ops.conversations.read", "daily"],
  ["evaluations", "品質驗收", "ops.evals.read", "daily"],
  ["overview", "營運分析", "ops.summary.read", "daily"],
];

/** Secondary system admin entries (collapsed group). */
export const BU_SYSTEM_NAV = [
  ["examples", "分類正反例", "ops.examples.read"],
  ["sync", "同步工作", "ops.sync.read"],
  ["prompts", "Prompt", "ops.prompts.read"],
  ["models", "模型", "ops.models.read"],
  ["flags", "功能開關", "ops.flags.read"],
  ["budgets", "預算與告警", "ops.budget.read"],
  ["health", "服務狀態", "ops.health.read"],
  ["roles", "角色權限", "ops.roles.read"],
  ["retention", "保存政策", "ops.retention.read"],
  ["masking", "遮罩政策", "ops.retention.read"],
  ["audit", "稽核", "ops.audit.read"],
  ["search", "搜尋結果", "ops.search.read"],
];

export const BU_VIEW_TITLES = Object.fromEntries([
  ...BU_PRIMARY_NAV.map(([id, label]) => [id, label]),
  ...BU_SYSTEM_NAV.map(([id, label]) => [id, label]),
  ["faq", "FAQ"],
  ["contentHub", "內容維護"],
  ["knowledgePortal", "知識文件庫"],
  ["knowledgeWork", "文件待辦"],
  ["knowledgeReviews", "待審清單"],
  ["knowledgeReleases", "發布與更新"],
  ["knowledge", "內容成效"],
  ["issues", "問題分析"],
  ["routes", "處理方式與回答依據"],
  ["costs", "成本"],
  ["examples", "分類正反例"],
  ["sync", "同步工作"],
  ["knowledgeAudit", "知識稽核"],
]);

/**
 * Resolve whether the BU shell is active.
 * Precedence: URL ?buShell= → localStorage → window override → false.
 */
export function isBuShellEnabled() {
  try {
    const params = new URLSearchParams(window.location.search);
    const query = params.get("buShell");
    if (query === "1" || query === "true") {
      return true;
    }
    if (query === "0" || query === "false") {
      return false;
    }
  } catch {
    /* ignore */
  }
  try {
    const stored = localStorage.getItem(BU_SHELL_STORAGE_KEY);
    if (stored === "1" || stored === "true") {
      return true;
    }
    if (stored === "0" || stored === "false") {
      return false;
    }
  } catch {
    /* ignore */
  }
  if (window.__AI_OPS_BU_SHELL_V1__ === true) {
    return true;
  }
  if (window.__AI_OPS_FLAGS__ && typeof window.__AI_OPS_FLAGS__ === "object") {
    const flag = window.__AI_OPS_FLAGS__[BU_SHELL_FLAG_ID];
    if (flag === true || flag === "true" || flag === "ENABLED") {
      return true;
    }
  }
  return false;
}

export function setBuShellEnabled(enabled) {
  localStorage.setItem(BU_SHELL_STORAGE_KEY, enabled ? "1" : "0");
}

export function applyBuShellBodyClass(enabled = isBuShellEnabled()) {
  document.body.classList.toggle("bu-shell-v1", Boolean(enabled));
  document.body.classList.toggle("legacy-shell", !enabled);
  if (typeof document.querySelector !== "function") {
    return;
  }
  const eyebrow = document.querySelector(".brand-copy .eyebrow");
  const title = document.querySelector(".brand-copy h1");
  if (eyebrow && title) {
    if (!eyebrow.dataset.classicLabel) {
      eyebrow.dataset.classicLabel = eyebrow.textContent || "";
      title.dataset.classicLabel = title.textContent || "";
    }
    if (enabled) {
      eyebrow.textContent = "資訊客服";
      title.textContent = "營運工作台";
    } else {
      eyebrow.textContent = eyebrow.dataset.classicLabel;
      title.textContent = title.dataset.classicLabel;
    }
  }
}
