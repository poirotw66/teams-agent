import { api, el } from "../api.js";
import { attributionCell, badge } from "../components/badges.js";
import {
  actionCell,
  emptyState,
  filterChipBar,
  formatCount,
  formatPercent,
  kpiStrip,
  pageHeader,
  renderIssueTrendChart,
  routeBadge,
  shareBarCell,
} from "../components/analyticsUi.js";
import { createPeriodControls, periodParams } from "../components/period.js";
import { createExportButton } from "../services/export.js";
import {
  clearNavFilters,
  drillLink,
  loadNavFilters,
} from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";

function renderIssueTreeNode(node, depth = 0) {
  const item = el("li", "");
  const label = `${"  ".repeat(depth)}${node.displayName} (${node.aggregateCount ?? node.count})`;
  item.append(el("span", "", label));
  item.append(drillLink(" 路由", "issues", { issueTypeId: node.issueTypeId }));
  if (node.children?.length) {
    const children = el("ul", "");
    for (const child of node.children) {
      children.append(renderIssueTreeNode(child, depth + 1));
    }
    item.append(children);
  }
  return item;
}

function renderTrendSection(trends, nameMap) {
  const panel = el("section", "analytics-trend-panel");
  const titleRow = el("div", "analytics-section-title");
  titleRow.append(
    el("h3", "", "Issue 數量趨勢"),
    el("span", "metric-label", "顯示期間內數量最高的前 5 類 Issue"),
  );
  panel.append(titleRow);
  panel.append(renderIssueTrendChart(trends, { topN: 5, names: nameMap }));

  const details = el("details");
  details.append(el("summary", "", "查看按日明細表"));
  if (!(trends || []).length) {
    details.append(el("p", "empty", "此期間尚無趨勢資料。"));
    panel.append(details);
    return panel;
  }
  const table = el("table");
  table.innerHTML =
    "<thead><tr><th>日期</th><th>Issue</th><th>Count</th><th>動作</th></tr></thead>";
  const body = el("tbody");
  for (const day of trends) {
    for (const item of day.counts || []) {
      const row = el("tr");
      row.append(el("td", "", day.date || "-"));
      const nameCell = el("td", "");
      nameCell.append(
        el("div", "", nameMap[item.issueTypeId] || item.issueTypeId),
        el("div", "analytics-mono", item.issueTypeId),
      );
      row.append(nameCell);
      row.append(el("td", "", formatCount(item.count)));
      row.append(
        actionCell(
          drillLink("路由", "issues", { issueTypeId: item.issueTypeId }),
          drillLink("來源", "routes", { issueTypeId: item.issueTypeId }),
        ),
      );
      body.append(row);
    }
  }
  table.append(body);
  const wrap = el("div", "table-responsive");
  wrap.append(table);
  details.append(wrap);
  panel.append(details);
  return panel;
}

function renderIssueRouteDrill(data, period, query) {
  const panel = el("section", "panel");
  const back = drillLink("← 返回 Issue 總覽", "issues", { clear: true });
  panel.append(
    pageHeader(
      `${data.displayName}｜路由分布`,
      `Issue：${data.issueTypeId}｜期間可切換後重新載入`,
      back,
    ),
  );

  const toolbar = el("div", "analytics-toolbar");
  toolbar.append(createPeriodControls(period, (next) => renderIssues({ ...next, query })));
  toolbar.append(
    createExportButton("routes_summary", period, {
      issue_type_id: data.issueTypeId,
    }),
  );
  panel.append(toolbar);

  const total = (data.routes || []).reduce((sum, item) => sum + (item.count || 0), 0);
  panel.append(
    kpiStrip([
      { label: "路由總次數", value: formatCount(total) },
      { label: "Route 類型數", value: formatCount((data.routes || []).length) },
    ]),
  );

  if (!(data.routes || []).length) {
    panel.append(
      emptyState(
        "此 Issue 在選定期間沒有路由紀錄",
        "可拉長期間，或到對話驗證確認是否已有 issue.extracted／route.selected 事件。",
      ),
    );
    return panel;
  }

  const table = el("table");
  table.innerHTML =
    "<thead><tr><th>Route</th><th>Count</th><th>實際來源（FAQ／Document）</th><th>動作</th></tr></thead>";
  const body = el("tbody");
  for (const item of data.routes || []) {
    const row = el("tr");
    const routeCell = el("td", "");
    routeCell.append(routeBadge(item.route));
    row.append(routeCell);
    row.append(el("td", "", formatCount(item.count)));
    row.append(attributionCell(item.attribution));
    row.append(
      actionCell(
        drillLink("對話", "conversations", { issueTypeId: data.issueTypeId }),
        drillLink("回饋", "quality", { issueTypeId: data.issueTypeId }),
        drillLink("來源總覽", "routes", {
          issueTypeId: data.issueTypeId,
          route: item.route,
        }),
      ),
    );
    body.append(row);
  }
  table.append(body);
  const scroll = el("div", "table-scroll-box");
  scroll.append(table);
  panel.append(scroll);
  return panel;
}

export async function renderIssues(state = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  const period = {
    preset: state.preset || "30d",
    start: state.start || "",
    end: state.end || "",
  };
  const query = (state.query || "").trim();
  const filters = loadNavFilters();
  if (filters.clear) {
    clearNavFilters();
  } else if (filters.view === "issues" && filters.issueTypeId) {
    try {
      const data = await api(
        `/api/issues/${encodeURIComponent(filters.issueTypeId)}/routes?${periodParams(period).toString()}`,
      );
      app.replaceChildren(renderIssueRouteDrill(data, period, query));
      return;
    } catch (error) {
      app.replaceChildren(
        el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message),
      );
      return;
    }
  }

  try {
    const params = periodParams(period);
    if (query) params.set("query", query);
    const data = await api(`/api/issues/summary?${params.toString()}`);
    const panel = el("section", "panel");
    const versionBadge = badge(data.taxonomyVersion || "taxonomy", "accent");
    panel.append(
      pageHeader(
        "Issue 分析",
        "切換期間查看 Issue 數量、占比與趨勢；可下鑽路由來源與回饋。",
        versionBadge,
      ),
    );

    const toolbar = el("div", "analytics-toolbar");
    toolbar.append(createPeriodControls(period, (next) => renderIssues({ ...next, query })));

    const filterBar = el("div", "filter-bar");
    const queryInput = el("input");
    queryInput.type = "search";
    queryInput.placeholder = "篩選 Issue（ID 或顯示名稱）";
    queryInput.value = query;
    queryInput.setAttribute("aria-label", "Issue 關鍵字");
    const applyFilter = el("button", "", "套用篩選");
    const reload = () => renderIssues({ ...period, query: queryInput.value.trim() });
    applyFilter.addEventListener("click", reload);
    queryInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        reload();
      }
    });
    filterBar.append(queryInput, applyFilter);
    toolbar.append(filterBar);
    toolbar.append(
      createExportButton("issues_summary", period, () => ({
        query: queryInput.value.trim() || undefined,
      })),
    );
    panel.append(toolbar);

    panel.append(
      filterChipBar(
        [
          {
            label: "Issue",
            value: query,
            onClear: () => renderIssues({ ...period, query: "" }),
          },
        ],
        query ? () => renderIssues({ ...period, query: "" }) : null,
      ),
    );

    const totalCount = (data.items || []).reduce((sum, item) => sum + (item.count || 0), 0);
    panel.append(
      kpiStrip([
        { label: "Issue 總量", value: formatCount(totalCount) },
        { label: "Issue 類型數", value: formatCount((data.items || []).length) },
        { label: "未分類", value: formatCount(data.unclassifiedCount || 0) },
        {
          label: "趨勢天數",
          value: formatCount((data.trends || []).length),
        },
      ]),
    );

    if (!(data.items || []).length) {
      panel.append(
        emptyState(
          "選定期間沒有 Issue 資料",
          query
            ? "請調整關鍵字，或清除篩選後再試。"
            : "確認 Agent 已寫入 issue.extracted 事件，或拉長查詢期間。",
        ),
      );
      app.replaceChildren(panel);
      return;
    }

    const titleRow = el("div", "analytics-section-title");
    titleRow.append(el("h3", "", "Issue 數量與品質指標"), el("span", "metric-label", "可下鑽路由／來源／負評"));
    panel.append(titleRow);

    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Issue</th><th>Count</th><th>Share</th><th>負評率</th><th>Handoff</th><th>成本 USD</th><th>動作</th></tr></thead>";
    const body = el("tbody");
    const nameMap = {};
    for (const item of data.items) {
      nameMap[item.issueTypeId] = item.displayName;
      const row = el("tr");
      const nameCell = el("td", "");
      nameCell.append(
        el("div", "", item.displayName),
        el("div", "analytics-mono", item.issueTypeId),
      );
      row.append(nameCell);
      row.append(el("td", "", formatCount(item.count)));
      row.append(shareBarCell(item.share));
      row.append(el("td", "", formatPercent(item.negativeFeedbackRate ?? 0)));
      row.append(el("td", "", formatPercent(item.handoffRate ?? 0)));
      row.append(el("td", "", Number(item.estimatedCostUsd ?? 0).toFixed(4)));
      row.append(
        actionCell(
          drillLink("路由", "issues", { issueTypeId: item.issueTypeId }),
          drillLink("來源", "routes", { issueTypeId: item.issueTypeId }),
          drillLink("回饋", "quality", {
            rating: "DOWN",
            issueTypeId: item.issueTypeId,
          }),
        ),
      );
      body.append(row);
    }
    table.append(body);
    const issuesScroll = el("div", "table-scroll-box");
    issuesScroll.append(table);
    panel.append(issuesScroll);
    panel.append(renderTrendSection(data.trends, nameMap));

    if (data.hierarchy?.length) {
      const hierarchyTitle = el("div", "analytics-section-title");
      hierarchyTitle.append(el("h3", "", "Taxonomy 階層"), el("span", "metric-label", "含 parent／child 彙總"));
      panel.append(hierarchyTitle);
      const tree = el("ul", "issue-tree");
      for (const node of data.hierarchy) {
        tree.append(renderIssueTreeNode(node));
      }
      panel.append(tree);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(
      el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message),
    );
  }
}

export const issuesPage = createPageController({
  enter: async (context = {}) => renderIssues(context.state || { preset: "30d" }),
  update: async (context = {}) => renderIssues(context.state || { preset: "30d" }),
  leave: async () => {},
});
