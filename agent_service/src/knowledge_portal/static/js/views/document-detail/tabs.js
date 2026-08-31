import { navigate } from "../../router.js";

let pendingTabFocus = null;

export function wireTabList(tabNav, documentId, activeTab) {
  const tabs = [...tabNav.querySelectorAll('[role="tab"]')];
  tabs.forEach((node) => {
    node.tabIndex = node.dataset.tab === activeTab ? 0 : -1;
    node.addEventListener("click", () => navigate(`#/knowledge/${documentId}/${node.dataset.tab}`));
  });

  tabNav.addEventListener("keydown", (event) => {
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
    navigate(`#/knowledge/${documentId}/${pendingTabFocus}`);
  });
}

export function focusPendingTab() {
  if (!pendingTabFocus) return;
  const target = document.getElementById(`tab-${pendingTabFocus}`);
  target?.focus();
  pendingTabFocus = null;
}
