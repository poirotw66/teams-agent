import { confirmDialog } from "./ui.js?v=20260831e";

let dirtyChecker = null;
let dirtyMessage = "你有尚未儲存的變更。離開此頁將捨棄這些變更。確定要離開？";

export function registerDirtyChecker(checker, message = dirtyMessage) {
  dirtyChecker = checker;
  if (message) dirtyMessage = message;
  window.__isKnowledgeDirty = isNavigationDirty;
  window.__confirmKnowledgeDirty = confirmLeaveIfDirty;
  window.__clearKnowledgeDirty = clearDirtyChecker;
}

export function clearDirtyChecker() {
  dirtyChecker = null;
  window.__isKnowledgeDirty = null;
  window.__confirmKnowledgeDirty = null;
  window.__clearKnowledgeDirty = null;
}

export function isNavigationDirty() {
  return typeof dirtyChecker === "function" ? Boolean(dirtyChecker()) : false;
}

export async function confirmLeaveIfDirty(message = dirtyMessage) {
  if (!isNavigationDirty()) return true;
  return confirmDialog("尚未儲存", message, { confirmLabel: "離開", danger: true });
}

export function installBeforeUnloadGuard() {
  if (window.__beforeUnloadGuardInstalled) return;
  window.__beforeUnloadGuardInstalled = true;
  window.addEventListener("beforeunload", (event) => {
    if (!isNavigationDirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });
}

export function bindNavigationGuard(selector, getTarget) {
  document.querySelectorAll(selector).forEach((node) => {
    node.addEventListener("click", async (event) => {
      if (!isNavigationDirty()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const ok = await confirmLeaveIfDirty();
      if (!ok) return;
      clearDirtyChecker();
      const target = typeof getTarget === "function" ? getTarget(node) : getTarget;
      if (target) window.location.hash = target;
    }, true);
  });
}
