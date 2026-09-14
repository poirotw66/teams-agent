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
import { presentAnalyticsPage } from "../app/analyticsChrome.js";
import { labelRoute } from "../app/labels.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";

function stillOnRoutes() {
  const view = loadNavFilters().view;
  return !view || view === "routes";
}

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
        "處理方式與回答依據",
        "固定答案、知識文件和轉人工各占多少，以及實際命中了什麼。",
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
    issueInput.placeholder = "問題代碼";
    issueInput.value = issueTypeId;
    issueInput.setAttribute("aria-label", "問題代碼");
    const routeSelect = el("select", "");
    routeSelect.setAttribute("aria-label", "處理方式");
    for (const optionValue of ROUTE_OPTIONS) {
      const option = el(
        "option",
        "",
        optionValue ? labelRoute(optionValue) : "全部處理方式",
      );
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
            label: "問題",
            value: issueTypeId,
            onClear: () => renderRoutes({ ...period, issueTypeId: "", route }),
          },
          {
            label: "處理方式",
            value: route ? labelRoute(route) : "",
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
        { label: "處理次數", value: formatCount(routeTotal) },
        { label: "處理方式", value: formatCount((data.routeDistribution || []).length) },
        { label: "涉及問題", value: formatCount(issueCount) },
      ]),
    );

    const distTitle = el("div", "analytics-section-title");
    distTitle.append(el("h3", "ov-panel-title", "處理方式分布"));
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
    tableTitle.append(el("h3", "ov-panel-title", "實際命中來源"));
    panel.append(tableTitle);

    if (!(data.routeDistribution || []).length) {
      panel.append(
        emptyState(
          "此條件沒有處理紀錄",
          "試著清除問題或處理方式篩選，或改用較長期間。",
        ),
      );
    } else {
      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>處理方式</th><th>次數</th><th>實際來源</th></tr></thead>";
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
    byIssueTitle.append(el("h3", "ov-panel-title", "依問題追查來源"));
    panel.append(byIssueTitle);

    if (!(data.byIssueType || []).length) {
      panel.append(emptyState("此條件沒有問題分流資料", "可先從問題分析頁查看，或放寬篩選條件。"));
    } else {
      const byIssue = el("table");
      byIssue.innerHTML =
        "<thead><tr><th>問題</th><th>處理方式</th><th>次數</th><th>依據</th><th>動作</th></tr></thead>";
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
              drillLink("問題分析", "issues", { issueTypeId: issue.issueTypeId }),
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

    if (!stillOnRoutes()) {
      return;
    }
    if (isBuShellEnabled()) {
      presentAnalyticsPage(
        "routes",
        "處理方式與回答依據",
        "固定答案、知識文件和轉人工各占多少，以及實際命中了什麼。",
        panel,
      );
    } else {
      app.replaceChildren(panel);
    }
  } catch (error) {
    if (!stillOnRoutes()) {
      return;
    }
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
