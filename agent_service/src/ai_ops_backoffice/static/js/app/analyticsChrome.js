/**
 * Shared analytics tab chrome for BU shell (overview / issues / routes / costs).
 */

import { el } from "../api.js";
import { actorHasCapability } from "./capabilities.js";
import { isBuShellEnabled } from "./buShellConfig.js";
import { loadNavFilters, navigateTo } from "./navigation.js";

const ANALYTICS_TABS = [
  ["overview", "總覽", "ops.summary.read"],
  ["issues", "問題分析", "ops.issues.read"],
  ["routes", "處理方式與回答依據", "ops.issues.read"],
  ["knowledge", "內容成效", "ops.knowledge.read"],
  ["costs", "成本", "ops.cost.read"],
];

function periodFiltersFromNav() {
  const nav = loadNavFilters();
  const next = {};
  for (const key of ["preset", "start", "end"]) {
    if (nav[key]) next[key] = nav[key];
  }
  return next;
}

export function buildAnalyticsTabs(activeView) {
  if (!isBuShellEnabled()) {
    return null;
  }
  const tabs = el("div", "bu-quality-tabs");
  for (const [id, label, capability] of ANALYTICS_TABS) {
    if (!actorHasCapability(capability)) {
      continue;
    }
    const button = el("button", id === activeView ? "active" : "", label);
    button.type = "button";
    button.addEventListener("click", () => navigateTo(id, periodFiltersFromNav()));
    tabs.append(button);
  }
  if (!tabs.childElementCount) {
    return null;
  }
  return tabs;
}

/** Wrap page content with BU analytics header + tabs when shell is on. */
export function presentAnalyticsPage(activeView, title, subtitle, ...nodes) {
  // Ignore late completions after the user already navigated away.
  const currentView = loadNavFilters().view;
  if (currentView && currentView !== activeView) {
    return;
  }
  const app = document.getElementById("app");
  if (!isBuShellEnabled()) {
    app.replaceChildren(...nodes);
    return;
  }
  const header = el("div");
  header.append(el("h2", "", title || "營運分析"));
  if (subtitle) {
    header.append(el("p", "metric-label", subtitle));
  }
  const tabs = buildAnalyticsTabs(activeView);
  const body = el("div", "bu-analytics-body");
  for (const node of nodes) {
    if (node) body.append(node);
  }
  app.replaceChildren(header, ...(tabs ? [tabs] : []), body);
}
