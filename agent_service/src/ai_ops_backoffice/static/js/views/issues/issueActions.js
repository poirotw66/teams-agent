import { loadNavFilters } from "../../app/navigation.js";
import { presentAnalyticsPage } from "../../app/analyticsChrome.js";
import { isBuShellEnabled } from "../../app/buShellConfig.js";

export function stillOnIssues() {
  const view = loadNavFilters().view;
  return !view || view === "issues";
}

export function finishIssuesPage(panel) {
  if (!stillOnIssues()) {
    return;
  }
  if (isBuShellEnabled()) {
    presentAnalyticsPage(
      "issues",
      "問題分析",
      "以排名找出需改善的問題，並追到處理方式、依據與案件。",
      panel,
    );
    return;
  }
  document.getElementById("app").replaceChildren(panel);
}

export function periodToNavFilters(period) {
  if (period?.preset === "custom") {
    return { preset: "custom", start: period.start || "", end: period.end || "" };
  }
  return { preset: period?.preset || "30d" };
}

export function periodLabel(period) {
  if (period?.preset === "today") return "今天";
  if (period?.preset === "1d") return "最近 1 日";
  if (period?.preset === "7d") return "最近 1 週";
  if (period?.preset === "30d") return "最近 30 天";
  if (period?.preset === "month") return "本月";
  if (period?.preset === "6m") return "最近 6 個月";
  if (period?.preset === "1y") return "最近 1 年";
  if (period?.preset === "custom") {
    return `${period.start || "起"} 至 ${period.end || "迄"}`;
  }
  return period?.preset || "30d";
}
