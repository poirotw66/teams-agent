import { api, el } from "../api.js";
import { attributionCell } from "../components/badges.js";
import {
  actionCell,
  distributionBars,
  emptyState,
  filterChipBar,
  formatCount,
  kpiStrip,
  pageHeader,
  routeBadge,
} from "../components/analyticsUi.js";
import { createPeriodControls, periodParams } from "../components/period.js";
import { createExportButton } from "../services/export.js";
import { clearNavFilters, drillLink, loadNavFilters, saveNavFilters } from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";

const ROUTE_OPTIONS = [
  "",
  "FAQ",
  "KNOWLEDGE",
  "TICKET",
  "HANDOFF",
  "CLARIFICATION",
  "FAILED",
];

function syncRouteNavFilters(issueTypeId, route) {
  saveNavFilters({
    view: "routes",
    ...(issueTypeId ? { issueTypeId } : {}),
    ...(route ? { route } : {}),
  });
}

export async function renderRoutes(state = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  const navFilters = loadNavFilters();
  const period = {
    preset: state.preset || "30d",
    start: state.start || "",
    end: state.end || "",
  };
  const issueTypeId = (
    state.issueTypeId ??
    (navFilters.view === "routes" ? navFilters.issueTypeId : "") ??
    ""
  )
    .toString()
    .trim();
  const route = (
    state.route ??
    (navFilters.view === "routes" ? navFilters.route : "") ??
    ""
  )
    .toString()
    .trim()
    .toUpperCase();

  try {
    const params = periodParams(period);
    if (issueTypeId) params.set("issue_type_id", issueTypeId);
    if (route) params.set("route", route);
    const data = await api(`/api/routes/summary?${params.toString()}`);
    syncRouteNavFilters(issueTypeId, route);

    const panel = el("section", "panel");
    panel.append(
      pageHeader(
        "路由來源分析",
        "查看 FAQ／RAG／Handoff 等處理分布，並追查實際命中的 FAQ ID 與 Document ID。",
      ),
    );

    const toolbar = el("div", "analytics-toolbar");
    toolbar.append(
      createPeriodControls(period, (next) =>
        renderRoutes({ ...next, issueTypeId, route }),
      ),
    );

    const filterBar = el("div", "filter-bar");
    const issueInput = el("input");
    issueInput.type = "search";
    issueInput.placeholder = "Issue Type ID";
    issueInput.value = issueTypeId;
    issueInput.setAttribute("aria-label", "Issue Type");
    const routeSelect = el("select", "");
    routeSelect.setAttribute("aria-label", "Route Type");
    for (const optionValue of ROUTE_OPTIONS) {
      const option = el("option", "", optionValue || "全部 Route");
      option.value = optionValue;
      if (optionValue === route) option.selected = true;
      routeSelect.append(option);
    }
    const applyFilter = el("button", "", "套用篩選");
    const apply = () =>
      renderRoutes({
        ...period,
        issueTypeId: issueInput.value.trim(),
        route: routeSelect.value,
      });
    applyFilter.addEventListener("click", apply);
    issueInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        apply();
      }
    });
    filterBar.append(issueInput, routeSelect, applyFilter);
    toolbar.append(filterBar);
    toolbar.append(
      createExportButton("routes_summary", period, () => ({
        issue_type_id: issueInput.value.trim() || undefined,
        route: routeSelect.value || undefined,
      })),
    );
    panel.append(toolbar);

    const clearAll = () => {
      clearNavFilters();
      saveNavFilters({ view: "routes" });
      renderRoutes({ ...period, issueTypeId: "", route: "" });
    };
    panel.append(
      filterChipBar(
        [
          {
            label: "Issue",
            value: issueTypeId,
            onClear: () => renderRoutes({ ...period, issueTypeId: "", route }),
          },
          {
            label: "Route",
            value: route,
            onClear: () => renderRoutes({ ...period, issueTypeId, route: "" }),
          },
        ],
        issueTypeId || route ? clearAll : null,
      ),
    );

    const routeTotal = (data.routeDistribution || []).reduce(
      (sum, item) => sum + (item.count || 0),
      0,
    );
    const issueCount = (data.byIssueType || []).length;
    panel.append(
      kpiStrip([
        { label: "路由總次數", value: formatCount(routeTotal) },
        { label: "Route 類型數", value: formatCount((data.routeDistribution || []).length) },
        { label: "涉及 Issue 數", value: formatCount(issueCount) },
      ]),
    );

    const distTitle = el("div", "analytics-section-title");
    distTitle.append(el("h3", "", "Route 分布"), el("span", "metric-label", "FAQ vs RAG 等處理比例一目了然"));
    panel.append(distTitle);
    panel.append(
      distributionBars(
        (data.routeDistribution || []).map((item) => ({
          ...item,
          label: item.route,
        })),
      ),
    );

    const tableTitle = el("div", "analytics-section-title");
    tableTitle.append(el("h3", "", "Route 與實際來源"), el("span", "metric-label", "可點擊 FAQ／Document 下鑽"));
    panel.append(tableTitle);

    if (!(data.routeDistribution || []).length) {
      panel.append(
        emptyState(
          "此條件尚無路由資料",
          "試著清除 Issue／Route 篩選，或改用較長期間。",
        ),
      );
    } else {
      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>Route</th><th>Count</th><th>實際來源</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.routeDistribution || []) {
        const row = el("tr");
        const routeCell = el("td", "");
        routeCell.append(routeBadge(item.route));
        row.append(routeCell);
        row.append(el("td", "", formatCount(item.count)));
        row.append(attributionCell(item.attribution));
        body.append(row);
      }
      table.append(body);
      const routeScroll = el("div", "table-scroll-box");
      routeScroll.append(table);
      panel.append(routeScroll);
    }

    const byIssueTitle = el("div", "analytics-section-title");
    byIssueTitle.append(
      el("h3", "", "依 Issue 追查來源"),
      el("span", "metric-label", "Issue → Route → FAQ／Document → 對話"),
    );
    panel.append(byIssueTitle);

    if (!(data.byIssueType || []).length) {
      panel.append(emptyState("此條件尚無 Issue 路由資料", "可先從 Issue 分析頁下鑽，或放寬篩選條件。"));
    } else {
      const byIssue = el("table");
      byIssue.innerHTML =
        "<thead><tr><th>Issue</th><th>Route</th><th>Count</th><th>FAQ／Document</th><th>動作</th></tr></thead>";
      const byIssueBody = el("tbody");
      for (const issue of data.byIssueType || []) {
        for (const routeItem of issue.routes || []) {
          const row = el("tr");
          const nameCell = el("td", "");
          nameCell.append(
            el("div", "", issue.displayName),
            el("div", "analytics-mono", issue.issueTypeId),
          );
          row.append(nameCell);
          const routeCell = el("td", "");
          routeCell.append(routeBadge(routeItem.route));
          row.append(routeCell);
          row.append(el("td", "", formatCount(routeItem.count)));
          row.append(attributionCell(routeItem.attribution));
          row.append(
            actionCell(
              drillLink("Issue 路由", "issues", { issueTypeId: issue.issueTypeId }),
              drillLink("對話", "conversations", { issueTypeId: issue.issueTypeId }),
              drillLink("回饋", "quality", { issueTypeId: issue.issueTypeId }),
            ),
          );
          byIssueBody.append(row);
        }
      }
      byIssue.append(byIssueBody);
      const byIssueScroll = el("div", "table-scroll-box");
      byIssueScroll.append(byIssue);
      panel.append(byIssueScroll);
    }

    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(
      el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message),
    );
  }
}

export const routesPage = createPageController({
  enter: async (context = {}) => {
    const nav = loadNavFilters();
    await renderRoutes({
      ...(context.state || { preset: "30d" }),
      issueTypeId: context.state?.issueTypeId || nav.issueTypeId || "",
      route: context.state?.route || nav.route || "",
    });
  },
  update: async (context = {}) => {
    const nav = loadNavFilters();
    await renderRoutes({
      ...(context.state || { preset: "30d" }),
      issueTypeId: context.state?.issueTypeId || nav.issueTypeId || "",
      route: context.state?.route || nav.route || "",
    });
  },
  leave: async () => {},
});
