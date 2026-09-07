import { api, el } from "../api.js";
import { buildPeriodQuery } from "../components/period.js";
import { createPageController } from "../app/lifecycle.js";
import {
  buildFreshnessWarning,
  buildHeroKpiGrid,
  buildMetricsGlossary,
  buildOverviewHeader,
  buildQuickNavPanel,
  buildSlaHealthStrip,
  buildSplitAnalyticsGrid,
  buildTrendChartPanel,
  deriveOverviewMetrics,
  exportOverviewCsv,
} from "./overviewSections.js";

let currentOverviewPreset = "7d";
let currentOverviewTrendTab = "conv";
let currentOverviewInterval = "DAY";
let currentOverviewModel = "";
let currentOverviewIssueTypeId = "";

export async function renderOverview(forceRefresh = false) {
  const app = document.getElementById("app");
  const presetEl = document.getElementById("overview-preset");
  const preset = presetEl?.value || currentOverviewPreset || "7d";
  currentOverviewPreset = preset;

  const startEl = document.getElementById("custom-start-date");
  const endEl = document.getElementById("custom-end-date");
  const savedStart = startEl?.value || "";
  const savedEnd = endEl?.value || "";

  const intervalEl = document.getElementById("overview-interval");
  const interval = (intervalEl?.value || currentOverviewInterval || "DAY").toUpperCase();
  currentOverviewInterval = ["DAY", "WEEK", "MONTH"].includes(interval) ? interval : "DAY";

  const modelEl = document.getElementById("overview-model");
  const issueEl = document.getElementById("overview-issue-type");
  const model = (modelEl?.value || currentOverviewModel || "").trim();
  const issueTypeId = (issueEl?.value || currentOverviewIssueTypeId || "").trim();
  currentOverviewModel = model;
  currentOverviewIssueTypeId = issueTypeId;

  // Capture period before clearing the DOM — buildPeriodQuery must not read
  // controls that replaceChildren is about to remove.
  const query = new URLSearchParams(buildPeriodQuery("", {
    preset,
    start: savedStart,
    end: savedEnd,
  }));
  query.set("interval", currentOverviewInterval);
  if (model) query.set("model", model);
  if (issueTypeId) query.set("issue_type_id", issueTypeId);
  if (forceRefresh) query.set("refresh", "true");

  app.replaceChildren(el("div", "empty", "載入營運數據中…"));

  try {
    const data = await api(`/api/operations/summary?${query.toString()}`);

    const dashboard = el("div", "overview-dashboard");
    const metrics = deriveOverviewMetrics(data);

    dashboard.append(
      buildOverviewHeader({
        data,
        preset,
        savedStart,
        savedEnd,
        interval: currentOverviewInterval,
        model,
        issueTypeId,
        onPresetChange: ({ preset: nextPreset, customPeriod, modelInput, issueInput, intervalControl }) => {
          currentOverviewPreset = nextPreset;
          customPeriod.hidden = nextPreset !== "custom";
          if (nextPreset !== "custom") {
            currentOverviewModel = modelInput.value.trim();
            currentOverviewIssueTypeId = issueInput.value.trim();
            currentOverviewInterval = intervalControl.value;
            renderOverview(false);
          }
        },
        onIntervalChange: ({ modelInput, issueInput, intervalControl }) => {
          currentOverviewInterval = intervalControl.value;
          currentOverviewModel = modelInput.value.trim();
          currentOverviewIssueTypeId = issueInput.value.trim();
          renderOverview(false);
        },
        onApply: ({ modelInput, issueInput, intervalControl }) => {
          currentOverviewModel = modelInput.value.trim();
          currentOverviewIssueTypeId = issueInput.value.trim();
          currentOverviewInterval = intervalControl.value;
          renderOverview(false);
        },
        onRefresh: ({ modelInput, issueInput, intervalControl }) => {
          currentOverviewModel = modelInput.value.trim();
          currentOverviewIssueTypeId = issueInput.value.trim();
          currentOverviewInterval = intervalControl.value;
          renderOverview(true);
        },
        onExport: exportOverviewCsv,
      }),
    );

    const warnBox = buildFreshnessWarning(data);
    if (warnBox) dashboard.append(warnBox);

    dashboard.append(
      buildSlaHealthStrip(data, metrics),
      buildHeroKpiGrid(data, metrics),
      buildTrendChartPanel({
        data,
        interval: currentOverviewInterval,
        trendTab: currentOverviewTrendTab,
        onTrendTabChange: (nextTab) => {
          currentOverviewTrendTab = nextTab;
        },
      }),
      buildSplitAnalyticsGrid(data, metrics),
      buildQuickNavPanel(),
    );

    const glossary = buildMetricsGlossary(data.metricDefinitions || {});
    if (glossary) dashboard.append(glossary);

    app.replaceChildren(dashboard);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

export const overviewPage = createPageController({
  enter: async () => renderOverview(),
  update: async () => renderOverview(),
  leave: async () => {},
});
