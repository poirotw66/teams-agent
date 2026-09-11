import { el } from "../../api.js";
import {
  actionCell,
  formatCount,
  renderIssueTrendChart,
} from "../../components/analyticsUi.js";
import { showIssueDetailModal } from "../../components/issueModal.js";

export function renderIssueTreeNode(node, depth = 0, period = { preset: "30d" }) {
  const item = el("li", "");
  const label = `${"  ".repeat(depth)}${node.displayName} (${formatCount(node.aggregateCount ?? node.count)})`;
  item.append(el("span", "", label));

  const detailBtn = el("button", "button-link", "查看詳情");
  detailBtn.style.padding = "0.2rem 0.55rem";
  detailBtn.style.fontSize = "0.75rem";
  detailBtn.style.marginLeft = "0.4rem";
  detailBtn.addEventListener("click", () => {
    showIssueDetailModal(node.issueTypeId, period);
  });
  item.append(detailBtn);

  if (node.children?.length) {
    const children = el("ul", "");
    for (const child of node.children) {
      children.append(renderIssueTreeNode(child, depth + 1, period));
    }
    item.append(children);
  }
  return item;
}

export function renderTrendSection(trends, nameMap, period, allItems = []) {
  const panel = el("section", "analytics-trend-panel");
  const titleRow = el("div", "analytics-section-title");
  titleRow.style.display = "flex";
  titleRow.style.justifyContent = "space-between";
  titleRow.style.alignItems = "center";
  titleRow.style.flexWrap = "wrap";
  titleRow.style.gap = "0.5rem";

  const leftHeading = el("div");
  leftHeading.append(
    el("h3", "", "Issue 數量趨勢"),
    el("span", "metric-label", "按日追蹤高頻問題變化趨勢，支援切換特定單一問題"),
  );
  titleRow.append(leftHeading);

  // Issue selector dropdown for single vs top 5
  const selectWrap = el("div", "filter-bar");
  selectWrap.style.margin = "0";
  const issueSelect = el("select");
  issueSelect.setAttribute("aria-label", "選擇趨勢顯示問題");

  const optTop = el("option");
  optTop.value = "__top5__";
  optTop.textContent = "🔥 數量最高的前 5 類 Issue (Top 5)";
  issueSelect.append(optTop);

  for (const item of allItems) {
    const opt = el("option");
    opt.value = item.issueTypeId;
    opt.textContent = `${item.displayName} (${formatCount(item.count)})`;
    issueSelect.append(opt);
  }
  selectWrap.append(issueSelect);
  titleRow.append(selectWrap);
  panel.append(titleRow);

  const chartContainerWrap = el("div");
  const renderChart = (selectedId) => {
    chartContainerWrap.replaceChildren();
    if (selectedId === "__top5__") {
      chartContainerWrap.append(renderIssueTrendChart(trends, { topN: 5, names: nameMap }));
    } else {
      const filteredTrends = (trends || []).map((day) => ({
        ...day,
        counts: (day.counts || []).filter((c) => c.issueTypeId === selectedId),
      }));
      chartContainerWrap.append(
        renderIssueTrendChart(filteredTrends, { topN: 1, names: nameMap }),
      );
    }
  };

  issueSelect.addEventListener("change", (e) => {
    renderChart(e.target.value);
  });

  renderChart("__top5__");
  panel.append(chartContainerWrap);

  const details = el("details");
  details.style.marginTop = "1rem";
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

      const detailBtn = el("button", "button-link", "查看詳情");
      detailBtn.addEventListener("click", () => {
        showIssueDetailModal(item.issueTypeId, period);
      });
      row.append(actionCell(detailBtn));
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
