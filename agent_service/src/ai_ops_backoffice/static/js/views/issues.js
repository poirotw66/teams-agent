import { api, el } from "../api.js";
import { attributionText } from "../components/badges.js";
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
  item.append(
    drillLink(" 路由", "issues", { issueTypeId: node.issueTypeId }),
  );
  if (node.children?.length) {
    const children = el("ul", "");
    for (const child of node.children) {
      children.append(renderIssueTreeNode(child, depth + 1));
    }
    item.append(children);
  }
  return item;
}

export async function renderIssues(period = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  const filters = loadNavFilters();
  if (filters.clear) {
    clearNavFilters();
  } else if (filters.view === "issues" && filters.issueTypeId) {
    try {
      const data = await api(
        `/api/issues/${encodeURIComponent(filters.issueTypeId)}/routes?${periodParams(period).toString()}`,
      );
      const panel = el("section", "panel");
      panel.append(el("h2", "", `${data.displayName} 路由分布`));
      panel.append(createPeriodControls(period, renderIssues));
      panel.append(drillLink("返回 Issue 總覽", "issues", { clear: true }));
      panel.append(
        createExportButton("routes_summary", period, {
          issue_type_id: data.issueTypeId,
        }),
      );
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Route</th><th>Count</th><th>實際來源</th><th>動作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.routes || []) {
        const row = el("tr");
        row.append(el("td", "", item.route));
        row.append(el("td", "", String(item.count)));
        row.append(el("td", "", attributionText(item.attribution)));
        const actions = el("td", "");
        actions.append(
          drillLink("對話", "conversations"),
          document.createTextNode(" "),
          drillLink("回饋", "quality", { issueTypeId: data.issueTypeId }),
        );
        row.append(actions);
        body.append(row);
      }
      table.append(body);
      const issueRouteScroll = el("div", "table-responsive");
      issueRouteScroll.append(table);
      panel.append(issueRouteScroll);
      app.replaceChildren(panel);
      return;
    } catch (error) {
      app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
      return;
    }
  }
  try {
    const data = await api(`/api/issues/summary?${periodParams(period).toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", `Issue 分析 (${data.taxonomyVersion})`));
    panel.append(createPeriodControls(period, renderIssues));
    panel.append(createExportButton("issues_summary", period));
    panel.append(el("p", "", `未分類：${data.unclassifiedCount}`));
    const table = el("table");
    table.innerHTML =
      "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Count</th><th>Share</th><th>負評率</th><th>Handoff</th><th>成本 USD</th><th>動作</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.items) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", item.displayName));
      row.append(el("td", "", String(item.count)));
      row.append(el("td", "", String(item.share)));
      row.append(el("td", "", String(item.negativeFeedbackRate ?? 0)));
      row.append(el("td", "", String(item.handoffRate ?? 0)));
      row.append(el("td", "", String(item.estimatedCostUsd ?? 0)));
      const actions = el("td", "");
      actions.append(
        drillLink("路由", "issues", { issueTypeId: item.issueTypeId }),
        document.createTextNode(" "),
        drillLink("回饋", "quality", { rating: "DOWN", issueTypeId: item.issueTypeId }),
      );
      row.append(actions);
      body.append(row);
    }
    table.append(body);
    const issuesScroll = el("div", "table-responsive");
    issuesScroll.append(table);
    panel.append(issuesScroll);

    if (data.hierarchy?.length) {
      panel.append(el("h3", "", "Taxonomy 階層"));
      const tree = el("ul", "issue-tree");
      for (const node of data.hierarchy) {
        tree.append(renderIssueTreeNode(node));
      }
      panel.append(tree);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

export const issuesPage = createPageController({
  enter: async (context = {}) => renderIssues(context.state || { preset: "30d" }),
  update: async (context = {}) => renderIssues(context.state || { preset: "30d" }),
  leave: async () => {},
});
