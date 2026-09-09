/**
 * BU「知識內容」— documents + FAQ tabs, no hub card hop.
 */

import { el } from "../api.js";
import { createPageController } from "../app/lifecycle.js";
import { actorCapabilities, canUseKnowledgeUi } from "../app/capabilities.js";
import { drillLink, loadNavFilters, saveNavFilters, syncLocationHash } from "../app/navigation.js";
import {
  renderFaqManagement,
  renderKnowledgePortalEntry,
} from "./knowledge.js";

async function renderContentLists(state = {}) {
  const app = document.getElementById("app");
  const navFilters = loadNavFilters();
  const tab = state.tab || navFilters.tab || "documents";
  const allowed = actorCapabilities();

  const header = el("div");
  header.append(el("h2", "", "知識內容"));
  header.append(
    el("p", "metric-label", "直接維護使用者會讀到的答案與引用依據。"),
  );

  const secondary = el("div", "bu-content-secondary");
  secondary.append(el("span", "metric-label", "進階："));
  if (canUseKnowledgeUi()) {
    secondary.append(drillLink("待審核", "knowledgeReviews"));
    secondary.append(drillLink("發布紀錄", "knowledgeReleases"));
  }
  if (allowed.has("ops.sync.read") || allowed.has("ops.knowledge.read")) {
    secondary.append(drillLink("同步狀態", "sync"));
  }
  header.append(secondary);

  const tabs = el("div", "bu-quality-tabs");
  const tabDefs = [];
  if (canUseKnowledgeUi()) {
    tabDefs.push(["documents", "文件"]);
  }
  if (allowed.has("ops.faq.read")) {
    tabDefs.push(["faq", "FAQ"]);
  }
  if (!tabDefs.length) {
    app.replaceChildren(
      header,
      el("div", "forbidden", "沒有知識文件或 FAQ 的讀取權限。"),
    );
    return;
  }
  const activeTab = tabDefs.some(([key]) => key === tab) ? tab : tabDefs[0][0];

  for (const [key, label] of tabDefs) {
    const button = el("button", key === activeTab ? "active" : "", label);
    button.type = "button";
    button.addEventListener("click", () => {
      saveNavFilters({ view: "contentLists", tab: key });
      syncLocationHash("contentLists", { tab: key });
      void renderContentLists({ tab: key });
    });
    tabs.append(button);
  }

  if (activeTab === "faq") {
    const panel = el("section", "panel");
    app.replaceChildren(header, tabs, panel);
    await renderFaqManagement(panel);
    // Avoid duplicate page title from FAQ renderer when nested.
    const faqHeading = panel.querySelector("h2");
    if (faqHeading) {
      faqHeading.remove();
    }
    return;
  }

  // Documents: reuse native knowledge portal list (same data path as knowledgePortal).
  app.replaceChildren(header, tabs, el("div", "empty", "載入文件清單…"));
  const mount = el("div", "bu-content-docs");
  app.replaceChildren(header, tabs, mount);
  await renderKnowledgePortalEntry();
  // renderKnowledgePortalEntry replaces #app — re-apply chrome after portal mount.
  const portalRoot = document.getElementById("app");
  const portalContent = el("div");
  while (portalRoot.firstChild) {
    portalContent.append(portalRoot.firstChild);
  }
  portalRoot.replaceChildren(header, tabs, portalContent);
}

export const contentListsPage = createPageController({
  enter: async (context = {}) => renderContentLists({ tab: context.state?.tab }),
  update: async (context = {}) => renderContentLists({ tab: context.state?.tab }),
  leave: async () => {},
});
