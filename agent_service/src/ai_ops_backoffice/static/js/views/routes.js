import { api, el } from "../api.js";
import { attributionText } from "../components/badges.js";
import { createPeriodControls, periodParams } from "../components/period.js";
import { createExportButton } from "../services/export.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderRoutes(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const data = await api(`/api/routes/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "路由來源分析"));
    panel.append(createPeriodControls(period, renderRoutes));
    panel.append(createExportButton("routes_summary", period));
    const table = el("table");
    table.innerHTML = "<thead><tr><th>Route</th><th>Count</th><th>實際來源</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.routeDistribution || []) {
      const row = el("tr");
      row.append(el("td", "", item.route));
      row.append(el("td", "", String(item.count)));
      row.append(el("td", "", attributionText(item.attribution)));
      body.append(row);
    }
    table.append(body);
    const routeScroll = el("div", "table-responsive");
    routeScroll.append(table);
    panel.append(routeScroll);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

export const routesPage = createPageController({
  enter: async (context = {}) => renderRoutes(context.state || { preset: "30d" }),
  update: async (context = {}) => renderRoutes(context.state || { preset: "30d" }),
  leave: async () => {},
});
