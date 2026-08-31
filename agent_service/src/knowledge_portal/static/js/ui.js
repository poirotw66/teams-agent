import { statusLabel } from "./labels.js";

export function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.classList.toggle("error", isError);
  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => toast.classList.add("hidden"), 4000);
}

export function renderStatusBadge(status, label = null) {
  const text = label || statusLabel(status);
  const appearance = {
    DRAFT: "informative",
    IN_REVIEW: "warning",
    CHANGES_REQUESTED: "warning",
    APPROVED: "success",
    PUBLISHED: "success",
    PUBLISH_FAILED: "danger",
    UNPUBLISHED: "danger",
    PASS: "success",
    FAIL: "danger",
    NEEDS_REVIEW: "warning",
  }[status] || "neutral";
  return `<fluent-badge appearance="${appearance}" class="status-badge status-${status}" aria-label="狀態：${escapeHtml(text)}">${escapeHtml(text)}</fluent-badge>`;
}

const VIEW_FORBIDDEN = {
  work: {
    title: "無法載入工作區",
    message: "你目前沒有權限查看此工作區。",
    contact: "如需存取，請聯絡知識庫管理者或 IT Service Desk。",
  },
  knowledge: {
    title: "無法存取知識庫",
    message: "你目前沒有權限瀏覽知識文件。",
    contact: "請確認你的角色與所屬單位設定是否正確。",
  },
  reviews: {
    title: "無待審清單權限",
    message: "待審清單僅供審核者、管理者或平台管理者使用。",
    contact: "若你需要執行審核，請聯絡知識庫管理者調整角色。",
    actionLabel: "返回我的工作",
    actionRoute: "#/work",
  },
  audit: {
    title: "無稽核紀錄權限",
    message: "稽核紀錄僅供稽核者或管理者查閱。",
    contact: "如需稽核存取，請聯絡平台管理者。",
    actionLabel: "返回我的工作",
    actionRoute: "#/work",
  },
  document: {
    title: "無法查看這份文件",
    message: "你沒有權限存取這份知識文件。",
    contact: "若你認為這是錯誤，請聯絡文件擁有單位或知識庫管理者。",
    actionLabel: "返回知識庫",
    actionRoute: "#/knowledge",
  },
};

const VIEW_EMPTY = {
  "work-clear": {
    title: "目前沒有急迫事項",
    message: "你可以到知識庫瀏覽文件，或建立新的草稿。",
  },
  "knowledge-empty": {
    title: "知識庫尚無文件",
    message: "建立第一份草稿，開始累積可被 Teams 引用的知識內容。",
  },
  "knowledge-no-results": {
    title: "找不到符合條件的文件",
    message: "調整搜尋關鍵字或篩選條件後再試一次。",
  },
  "reviews-empty": {
    title: "目前沒有待審文件",
    message: "新的送審項目會出現在這裡，可直接進入審核工作區。",
  },
  "audit-empty": {
    title: "尚無稽核紀錄",
    message: "系統操作會記錄在此，供稽核與追溯使用。",
  },
};

export function isForbiddenError(error) {
  return error?.status === 403;
}

export function renderViewForbidden(viewKey, overrides = {}) {
  const cfg = { ...VIEW_FORBIDDEN[viewKey], ...overrides };
  const action = cfg.actionLabel && cfg.actionRoute
    ? `<fluent-button appearance="outline" data-route="${escapeHtml(cfg.actionRoute)}">${escapeHtml(cfg.actionLabel)}</fluent-button>`
    : "";
  return `
    <div class="state-panel forbidden-state" role="alert">
      <div class="state-icon" aria-hidden="true">⛔</div>
      <h3>${escapeHtml(cfg.title)}</h3>
      <p>${escapeHtml(cfg.message)}</p>
      <p class="muted state-contact">${escapeHtml(cfg.contact)}</p>
      ${action}
    </div>`;
}

export function renderViewEmpty(viewKey, actionHtml = "", overrides = {}) {
  const cfg = { ...(VIEW_EMPTY[viewKey] || { title: "沒有資料", message: "" }), ...overrides };
  return `
    <div class="state-panel empty-state">
      <div class="state-icon" aria-hidden="true">📋</div>
      <h3>${escapeHtml(cfg.title)}</h3>
      <p class="muted">${escapeHtml(cfg.message)}</p>
      ${actionHtml}
    </div>`;
}

export function renderEmptyState(title, description, actionHtml = "") {
  return renderViewEmpty("work-clear", actionHtml, { title, message: description });
}

export function handleViewError(error, { view, onRetry, container }) {
  if (isForbiddenError(error)) {
    container.innerHTML = renderViewForbidden(view);
    container.querySelectorAll("[data-route]").forEach((node) => {
      node.addEventListener("click", () => {
        window.location.hash = node.dataset.route;
      });
    });
    return;
  }
  container.innerHTML = renderError(error.message);
  container.querySelector("[data-retry]")?.addEventListener("click", onRetry);
}

export function renderLoading(message = "載入中…") {
  return `<div class="loading-state" role="status">${escapeHtml(message)}</div>`;
}

export function renderSkeleton(rows = 4) {
  return `
    <div class="skeleton-wrap" aria-hidden="true">
      ${Array.from({ length: rows }, () => '<div class="skeleton-row"></div>').join("")}
    </div>`;
}

export function renderError(message, retryLabel = "重試") {
  return `
    <div class="state-panel error-state" role="alert">
      <div class="state-icon" aria-hidden="true">⚠️</div>
      <h3>載入失敗</h3>
      <p>${escapeHtml(message)}</p>
      <fluent-button appearance="outline" data-retry>${escapeHtml(retryLabel)}</fluent-button>
    </div>`;
}

export function renderForbidden(message = "你沒有權限執行此操作。如需協助，請聯絡知識庫管理者。") {
  return renderViewForbidden("document", { message });
}

let activeDialog = null;

export function closeDialog() {
  if (!activeDialog) return;
  activeDialog.remove();
  activeDialog = null;
}

export function openDialog({ title, bodyHtml, confirmLabel = "確認", cancelLabel = "取消", danger = false }) {
  closeDialog();
  return new Promise((resolve) => {
    const root = document.getElementById("dialogRoot");
    const overlay = document.createElement("div");
    overlay.className = "dialog-overlay";
    overlay.innerHTML = `
      <fluent-dialog class="dialog" aria-labelledby="dialogTitle">
        <div class="dialog-header" slot="title">
          <h2 id="dialogTitle">${escapeHtml(title)}</h2>
        </div>
        <div class="dialog-body">${bodyHtml}</div>
        <div slot="footer" class="dialog-footer">
          <fluent-button appearance="outline" data-dialog-cancel>${escapeHtml(cancelLabel)}</fluent-button>
          <fluent-button appearance="${danger ? "outline" : "accent"}" data-dialog-confirm>${escapeHtml(confirmLabel)}</fluent-button>
        </div>
      </fluent-dialog>`;
    root.appendChild(overlay);
    activeDialog = overlay;
    const dialogEl = overlay.querySelector("fluent-dialog");
    if (dialogEl && typeof dialogEl.show === "function") {
      dialogEl.show();
    }
    const previouslyFocused = document.activeElement;

    function finish(value) {
      closeDialog();
      if (previouslyFocused instanceof HTMLElement) {
        previouslyFocused.focus();
      }
      resolve(value);
    }

    overlay.querySelector("[data-dialog-cancel]").addEventListener("click", () => finish(null));
    overlay.querySelector("[data-dialog-confirm]").addEventListener("click", () => {
      const fields = {};
      overlay.querySelectorAll("[data-dialog-field]").forEach((node) => {
        fields[node.dataset.dialogField] = node.value;
      });
      finish(fields);
    });
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) finish(null);
    });
    dialogEl?.addEventListener("keydown", (event) => {
      if (event.key === "Escape") finish(null);
    });
    const firstInput = overlay.querySelector("input, textarea, select, fluent-button");
    if (firstInput instanceof HTMLElement) firstInput.focus();
  });
}

export async function promptDialog(title, label, { defaultValue = "", required = true, multiline = false } = {}) {
  const control = multiline
    ? `<textarea data-dialog-field="value" rows="4" class="full">${escapeHtml(defaultValue)}</textarea>`
    : `<input data-dialog-field="value" class="full" value="${escapeHtml(defaultValue)}">`;
  const result = await openDialog({
    title,
    bodyHtml: `<label class="full">${escapeHtml(label)}${control}</label>`,
    confirmLabel: "確認",
  });
  if (!result) return null;
  const value = result.value?.trim() ?? "";
  if (required && !value) return null;
  return value;
}

export async function confirmDialog(title, message, { confirmLabel = "確認", danger = false } = {}) {
  const result = await openDialog({
    title,
    bodyHtml: `<p>${escapeHtml(message)}</p>`,
    confirmLabel,
    danger,
  });
  return Boolean(result);
}

export function stripFrontMatter(content) {
  if (!content || !content.trimStart().startsWith("---")) return content || "";
  const end = content.indexOf("---", 3);
  if (end === -1) return content;
  return content.slice(end + 3).trim();
}
