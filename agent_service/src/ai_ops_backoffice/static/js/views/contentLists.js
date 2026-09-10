/**
 * BU「知識內容」— documents + FAQ tabs, no hub card hop.
 */

import { el } from "../api.js";
import { createPageController } from "../app/lifecycle.js";
import { actorCapabilities, canUseKnowledgeUi } from "../app/capabilities.js";
import { drillLink, loadNavFilters, saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { navigateReturnTo, parseReturnTo } from "../app/returnTo.js";
import {
  renderFaqManagement,
  renderKnowledgePortalEntry,
} from "./knowledge.js";

let contentListsGeneration = 0;

function returnLabel(view) {
  if (view === "quality") return "← 返回改善案件";
  if (view === "conversations") return "← 返回對話紀錄";
  if (view === "workHub") return "← 返回我的工作";
  if (view === "evaluations") return "← 返回品質驗收";
  return "← 返回上一頁";
}

function buildReturnBar() {
  const parsed = parseReturnTo(loadNavFilters().returnTo);
  if (!parsed) {
    return null;
  }
  const bar = el("div", "bu-return-bar");
  const back = el("a", "button-link", returnLabel(parsed.view));
  back.href = "#";
  back.addEventListener("click", (event) => {
    event.preventDefault();
    navigateReturnTo(parsed.view, parsed.filters);
  });
  bar.append(back);
  return bar;
}

function filtersWithReturn(tab) {
  const current = loadNavFilters();
  const next = { view: "contentLists", tab };
  if (current.returnTo) {
    next.returnTo = current.returnTo;
  }
  return next;
}

async function renderContentLists(state = {}) {
  const generation = ++contentListsGeneration;
  const app = document.getElementById("app");
  const navFilters = loadNavFilters();
  const tab = state.tab || navFilters.tab || "documents";
  const allowed = actorCapabilities();

  const header = el("div");
  const returnBar = buildReturnBar();
  if (returnBar) {
    header.append(returnBar);
  }
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
      const next = filtersWithReturn(key);
      saveNavFilters(next);
      syncLocationHash("contentLists", {
        tab: key,
        ...(next.returnTo ? { returnTo: next.returnTo } : {}),
      });
      void renderContentLists({ tab: key });
    });
    tabs.append(button);
  }

  if (activeTab === "faq") {
    const panel = el("section", "panel");
    app.replaceChildren(header, tabs, panel);
    await renderFaqManagement(panel);
    if (generation !== contentListsGeneration) {
      return;
    }
    // Avoid duplicate page title from FAQ renderer when nested.
    const faqHeading = panel.querySelector("h2");
    if (faqHeading) {
      faqHeading.remove();
    }
    return;
  }

  // Documents: mount portal into a dedicated container so chrome is never scooped.
  const mount = el("div", "bu-content-docs");
  mount.append(el("div", "empty", "載入文件清單…"));
  app.replaceChildren(header, tabs, mount);
  await renderKnowledgePortalEntry(undefined, mount);
  if (generation !== contentListsGeneration) {
    return;
  }
  // Ensure chrome stays singular even if portal temporarily touched ancestors.
  if (!app.contains(header) || !app.contains(tabs) || !app.contains(mount)) {
    app.replaceChildren(header, tabs, mount);
  }
}

export const contentListsPage = createPageController({
  enter: async (context = {}) => renderContentLists({ tab: context.state?.tab }),
  update: async (context = {}) => renderContentLists({ tab: context.state?.tab }),
  leave: async () => {
    contentListsGeneration += 1;
  },
});
