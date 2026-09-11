import { el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { createPageController } from "../app/lifecycle.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { loadNavFilters, saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { navigateReturnTo, parseReturnTo } from "../app/returnTo.js";

import { renderCasesTab, showCaseCreateModal } from "./evaluations/cases.js";
import { renderRunsTab } from "./evaluations/runForm.js";
import { renderResultsTab } from "./evaluations/runComparison.js";
import { renderGatesTab } from "./evaluations/gateSettings.js";

export { showCaseCreateModal };

let currentActiveTab = "cases";

export async function renderEvaluations() {
  const app = document.getElementById("app");
  const allowed = actorCapabilities();
  const nav = loadNavFilters();
  if (nav.view === "evaluations" && nav.tab) {
    currentActiveTab = nav.tab;
  }

  const container = el("div", "evaluations-container");

  if (parseReturnTo(nav.returnTo)) {
    const back = el("button", "button-link", "← 返回改善案件");
    back.type = "button";
    back.addEventListener("click", () => navigateReturnTo("workHub", {}));
    container.append(back);
  }

  const header = el("div", "page-header");
  const title = el(
    "h2",
    "",
    isBuShellEnabled() ? "品質驗收" : "品質驗收 (Golden Eval Set)",
  );
  const subtitle = el(
    "p",
    "page-subtitle",
    isBuShellEnabled()
      ? "以固定問題比較版本，知道這次改善了什麼。"
      : "BU 驗收題庫管理、版本發布與真實評測比較",
  );
  header.append(title, subtitle);

  const tabsNav = el("div", isBuShellEnabled() ? "bu-quality-tabs" : "tabs-nav");
  const tabCasesBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "cases" ? "active" : ""}`.trim(), "驗收題庫");
  const tabRunsBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "runs" ? "active" : ""}`.trim(), "執行驗收");
  const tabResultsBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "results" ? "active" : ""}`.trim(), "驗收結果");
  const tabGatesBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "gates" ? "active" : ""}`.trim(), "發布門檻");

  tabsNav.append(tabCasesBtn, tabRunsBtn, tabResultsBtn, tabGatesBtn);

  const tabContent = el("div", "tab-content");

  function activate(tab, renderFn) {
    currentActiveTab = tab;
    for (const btn of [tabCasesBtn, tabRunsBtn, tabResultsBtn, tabGatesBtn]) {
      btn.classList.remove("active");
    }
    if (tab === "cases") tabCasesBtn.classList.add("active");
    if (tab === "runs") tabRunsBtn.classList.add("active");
    if (tab === "results") tabResultsBtn.classList.add("active");
    if (tab === "gates") tabGatesBtn.classList.add("active");
    const existing = loadNavFilters();
    const preserved = { ...existing, view: "evaluations", tab };
    saveNavFilters(preserved);
    syncLocationHash("evaluations", preserved);
    renderFn(tabContent, allowed);
  }

  tabCasesBtn.addEventListener("click", () => activate("cases", renderCasesTab));
  tabRunsBtn.addEventListener("click", () => activate("runs", renderRunsTab));
  tabResultsBtn.addEventListener("click", () => activate("results", renderResultsTab));
  tabGatesBtn.addEventListener("click", () => activate("gates", renderGatesTab));

  container.append(header, tabsNav, tabContent);
  app.replaceChildren(container);

  if (currentActiveTab === "cases") {
    await renderCasesTab(tabContent, allowed);
  } else if (currentActiveTab === "runs") {
    await renderRunsTab(tabContent, allowed);
  } else if (currentActiveTab === "results") {
    await renderResultsTab(tabContent, allowed);
  } else {
    await renderGatesTab(tabContent, allowed);
  }
}

export const evaluationsPage = createPageController({
  enter: async () => renderEvaluations(),
  update: async () => renderEvaluations(),
  leave: async () => {},
});
