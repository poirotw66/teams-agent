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
  return `<span class="status-badge status-${status}" aria-label="狀態：${escapeHtml(text)}">${escapeHtml(text)}</span>`;
}

export function renderEmptyState(title, description, actionHtml = "") {
  return `
    <div class="empty-state">
      <h3>${escapeHtml(title)}</h3>
      <p class="muted">${escapeHtml(description)}</p>
      ${actionHtml}
    </div>`;
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
    <div class="error-state" role="alert">
      <p>${escapeHtml(message)}</p>
      <button type="button" class="btn secondary" data-retry>${escapeHtml(retryLabel)}</button>
    </div>`;
}

export function renderForbidden(message = "你沒有權限執行此操作。如需協助，請聯絡知識庫管理者。") {
  return `
    <div class="forbidden-state" role="alert">
      <h3>沒有權限</h3>
      <p>${escapeHtml(message)}</p>
    </div>`;
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
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="dialogTitle">
        <header class="dialog-header">
          <h2 id="dialogTitle">${escapeHtml(title)}</h2>
        </header>
        <div class="dialog-body">${bodyHtml}</div>
        <footer class="dialog-footer">
          <button type="button" class="btn secondary" data-dialog-cancel>${escapeHtml(cancelLabel)}</button>
          <button type="button" class="btn ${danger ? "danger" : "primary"}" data-dialog-confirm>${escapeHtml(confirmLabel)}</button>
        </footer>
      </div>`;
    root.appendChild(overlay);
    activeDialog = overlay;
    const dialog = overlay.querySelector(".dialog");
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
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") finish(null);
    });
    const firstInput = dialog.querySelector("input, textarea, select, button");
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
