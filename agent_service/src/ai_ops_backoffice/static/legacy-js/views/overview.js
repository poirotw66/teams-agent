import { api, el } from "../api.js";
import { buildPeriodQuery } from "../components/period.js";
import { createPageController } from "../app/lifecycle.js";
import { deriveOverviewMetrics } from "./overviewSections.js";
import { exportOverviewCsv } from "./overviewExport.js";
import { buildOverviewHome } from "./overviewHome.js";
import { presentAnalyticsPage } from "../app/analyticsChrome.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { loadNavFilters } from "../app/navigation.js";
import { loadingState } from "../components/state.js";
import { formatUserFacingError } from "../app/labels.js";

let currentOverviewPreset = "7d";

function stillOnOverview() {
  const view = loadNavFilters().view;
  return !view || view === "overview";
}

export async function renderOverview(forceRefresh = false) {
  const app = document.getElementById("app");
  const presetEl = document.getElementById("overview-preset");
  const preset = presetEl?.value || currentOverviewPreset || "7d";
  currentOverviewPreset = preset;

  const startEl = document.getElementById("custom-start-date");
  const endEl = document.getElementById("custom-end-date");
  const savedStart = startEl?.value || "";
  const savedEnd = endEl?.value || "";

  // Capture period before clearing the DOM — buildPeriodQuery must not read
  // controls that replaceChildren is about to remove.
  const query = new URLSearchParams(buildPeriodQuery("", {
    preset,
    start: savedStart,
    end: savedEnd,
  }));
  query.set("interval", "DAY");
  if (forceRefresh) query.set("refresh", "true");

  app.replaceChildren(loadingState("正在整理營運數據…", 5));

  try {
    const data = await api(`/api/operations/summary?${query.toString()}`);

    const metrics = deriveOverviewMetrics(data);
    const dashboard = buildOverviewHome({
      data,
      metrics,
      preset,
      savedStart,
      savedEnd,
      onPresetChange: ({ preset: nextPreset }) => {
        currentOverviewPreset = nextPreset;
        if (nextPreset !== "custom") {
          renderOverview(false);
        }
      },
      onApply: () => renderOverview(false),
      onRefresh: () => renderOverview(true),
      onExport: exportOverviewCsv,
    });

    if (!stillOnOverview()) {
      return;
    }
    if (isBuShellEnabled()) {
      presentAnalyticsPage(
        "overview",
        "營運總覽",
        "本期服務量、解答結果，以及需要接著處理的問題。",
        dashboard,
      );
    } else {
      app.replaceChildren(dashboard);
    }
  } catch (error) {
    if (!stillOnOverview()) {
      return;
    }
    app.replaceChildren(
      el(
        "div",
        error.message === "FORBIDDEN" ? "forbidden" : "error",
        formatUserFacingError(error),
      ),
    );
  }
}

export const overviewPage = createPageController({
  enter: async () => renderOverview(),
  update: async () => renderOverview(),
  leave: async () => {},
});
