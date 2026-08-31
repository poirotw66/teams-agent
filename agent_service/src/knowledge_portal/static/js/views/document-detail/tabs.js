import { navigate } from "../../router.js";
import { confirmDialog } from "../../ui.js?v=20260831d";
import { clearDraftBaseline, isDraftEditorDirty } from "./editor-state.js";

let pendingTabFocus = null;

async function goToTab(documentId, activeTab, targetTab) {
  if (activeTab === "content" && targetTab !== "content" && isDraftEditorDirty()) {
    const ok = await confirmDialog(
      "尚未儲存",
      "內容與附件有未儲存的變更。離開此分頁將捨棄這些變更。確定要離開？",
      { confirmLabel: "離開", danger: true },
    );
    if (!ok) return;
  }
  clearDraftBaseline();
  navigate(`#/knowledge/${documentId}/${targetTab}`);
}

export function wireTabList(tabNav, documentId, activeTab) {
  const tabs = [...tabNav.querySelectorAll('[role="tab"]')];
  tabs.forEach((node) => {
    node.tabIndex = node.dataset.tab === activeTab ? 0 : -1;
    node.addEventListener("click", () => {
      goToTab(documentId, activeTab, node.dataset.tab);
    });
  });

  tabNav.addEventListener("keydown", async (event) => {
    const current = tabs.findIndex((node) => node.getAttribute("aria-selected") === "true");
    if (current < 0) return;

    let next = current;
    if (event.key === "ArrowRight") {
      next = (current + 1) % tabs.length;
    } else if (event.key === "ArrowLeft") {
      next = (current - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = tabs.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    pendingTabFocus = tabs[next].dataset.tab;
    await goToTab(documentId, activeTab, pendingTabFocus);
  });
}

export function focusPendingTab() {
  if (!pendingTabFocus) return;
  const target = document.getElementById(`tab-${pendingTabFocus}`);
  target?.focus();
  pendingTabFocus = null;
}
