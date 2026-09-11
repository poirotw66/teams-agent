import { el } from "../api.js";
import { closeModalDialog, openModalDialog } from "./modalA11y.js";

export function showContentModal(title, content, { onClose } = {}) {
  // A few detail views naturally have a DOM node but no separate heading.
  // Keep the helper tolerant of that call shape so the modal never renders
  // `[object HTMLDivElement]` or an undefined body.
  const isDomNode = (value) => value && typeof value === "object" && value.nodeType === 1;
  if (content === undefined && isDomNode(title)) {
    content = title;
    title = "詳細內容";
  }
  if (!isDomNode(content)) {
    content = el("div", "empty", content == null ? "目前沒有可顯示的內容。" : String(content));
  }
  title = title == null || title === "" ? "詳細內容" : String(title);
  const root = document.getElementById("modal-root");
  if (!root) return;
  root.hidden = false;
  root.replaceChildren();
  root.onclick = (e) => {
    if (e.target === root) {
      closeContentModal();
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
  close.type = "button";
  close.addEventListener("click", () => {
    closeContentModal();
  });
  header.append(heading, close);
  modal.append(header, content);
  root.append(modal);
  openModalDialog(root, modal, {
    titleElement: heading,
    initialFocus: () =>
      content.querySelector("input, select, textarea, button, a[href]") || close,
    onClose,
  });
}

export function closeContentModal() {
  closeModalDialog();
}

export function showToast(message, { tone = "info", duration = 4200 } = {}) {
  if (typeof document === "undefined") return;
  let root = document.getElementById("toast-root");
  if (!root) {
    root = el("div", "toast-stack");
    root.id = "toast-root";
    root.setAttribute("aria-live", tone === "error" ? "assertive" : "polite");
    root.setAttribute("aria-atomic", "false");
    document.body.append(root);
  }
  const toast = el("div", `toast toast-${tone}`, String(message || ""));
  toast.setAttribute("role", tone === "error" ? "alert" : "status");
  root.append(toast);
  window.setTimeout(() => toast.remove(), Math.max(1500, duration));
}

export function showNotice(
  title,
  message,
  { tone = "info", confirmLabel = "關閉" } = {},
) {
  const content = el("div", "dialog-content");
  content.append(el("p", `dialog-message dialog-message-${tone}`, String(message || "")));
  const actions = el("div", "form-actions");
  const close = el("button", "button-primary", confirmLabel);
  close.type = "button";
  close.addEventListener("click", () => closeContentModal());
  actions.append(close);
  content.append(actions);
  showContentModal(title, content);
}

export function showConfirm({
  title = "請確認操作",
  message = "確定要繼續嗎？",
  confirmLabel = "確認",
  cancelLabel = "取消",
  tone = "warning",
} = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeContentModal();
      resolve(value);
    };
    const content = el("div", "dialog-content");
    content.append(el("p", `dialog-message dialog-message-${tone}`, String(message)));
    const actions = el("div", "form-actions");
    const cancel = el("button", "button-secondary", cancelLabel);
    cancel.type = "button";
    cancel.addEventListener("click", () => finish(false));
    const confirm = el("button", "button-primary", confirmLabel);
    confirm.type = "button";
    confirm.addEventListener("click", () => finish(true));
    actions.append(cancel, confirm);
    content.append(actions);
    showContentModal(title, content, {
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(false);
        }
      },
    });
  });
}

export function showTextPrompt({
  title = "需要輸入",
  message = "請輸入內容。",
  defaultValue = "",
  placeholder = "",
  inputType = "text",
  minLength = 0,
  required = false,
  confirmLabel = "確認",
  cancelLabel = "取消",
  readOnly = false,
} = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeContentModal();
      resolve(value);
    };
    const form = el("form", "dialog-form");
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = input.value;
      if (required && !value.trim()) {
        error.textContent = "請輸入內容。";
        input.focus();
        return;
      }
      if (minLength > 0 && value.trim().length < minLength) {
        error.textContent = `請至少輸入 ${minLength} 個字元。`;
        input.focus();
        return;
      }
      finish(value);
    });
    form.append(el("p", "dialog-message", message));
    const label = el("label", "form-field");
    label.append(el("span", "metric-label", "內容"));
    const input = el("input");
    input.type = inputType;
    input.value = defaultValue == null ? "" : String(defaultValue);
    input.placeholder = placeholder;
    input.readOnly = readOnly;
    input.required = required;
    label.append(input);
    form.append(label);
    const error = el("p", "error");
    error.setAttribute("role", "alert");
    form.append(error);
    const actions = el("div", "form-actions");
    const cancel = el("button", "button-secondary", cancelLabel);
    cancel.type = "button";
    cancel.addEventListener("click", () => finish(null));
    const confirm = el("button", "button-primary", confirmLabel);
    confirm.type = "submit";
    actions.append(cancel, confirm);
    form.append(actions);
    showContentModal(title, form, {
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(null);
        }
      },
    });
  });
}
