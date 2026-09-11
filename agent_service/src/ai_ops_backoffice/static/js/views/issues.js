import { api, el } from "../api.js";
import { badge } from "../components/badges.js";
import {
  actionCell,
  emptyState,
  filterChipBar,
  formatCount,
  formatPercent,
  kpiStrip,
  pageHeader,
  routeBadge,
  shareBarCell,
} from "../components/analyticsUi.js";
import { createPeriodControls, periodParams } from "../components/period.js";
import { createExportButton } from "../services/export.js";
import {
  clearNavFilters,
  drillLink,
  loadNavFilters,
  navigateTo,
} from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";
import { showIssueDetailModal } from "../components/issueModal.js";
import { withReturnTo } from "../app/returnTo.js";

import {
  stillOnIssues,
  finishIssuesPage,
  periodToNavFilters,
  periodLabel,
} from "./issues/issueActions.js";
import {
  renderIssueTreeNode,
  renderTrendSection,
} from "./issues/issuesList.js";
import {
  renderIssueRouteDrill,
} from "./issues/issueDetail.js";

export { stillOnIssues, finishIssuesPage, periodToNavFilters, periodLabel };

export async function renderIssues(state = { preset: "30d" }) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));

  const navFilters = loadNavFilters();
  const period = {
    preset: state.preset || (navFilters.view === "issues" && navFilters.preset) || "30d",
    start: state.start || (navFilters.view === "issues" && navFilters.start) || "",
    end: state.end || (navFilters.view === "issues" && navFilters.end) || "",
  };
  const query = (state.query ?? (navFilters.view === "issues" ? navFilters.query : "") ?? "").trim();
  const ownerUnitId = (state.ownerUnitId ?? (navFilters.view === "issues" ? navFilters.ownerUnitId : "") ?? "").trim();

  if (navFilters.clear) {
    clearNavFilters();
  } else if (navFilters.view === "issues" && navFilters.issueTypeId) {
    try {
      const data = await api(
        `/api/issues/${encodeURIComponent(navFilters.issueTypeId)}/routes?${periodParams(period).toString()}`,
      );
      finishIssuesPage(renderIssueRouteDrill(data, period, query, (next) => renderIssues({ ...next, query })));
      return;
    } catch (error) {
      finishIssuesPage(
        el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message),
      );
      return;
    }
  }

  try {
    const params = periodParams(period);
    if (query) params.set("query", query);
    if (ownerUnitId) params.set("owner_unit_id", ownerUnitId);

    const data = await api(`/api/issues/summary?${params.toString()}`);
    const panel = el("section", "panel");
    const versionBadge = badge(data.taxonomyVersion || "taxonomy", "accent");

    panel.append(
      pageHeader(
        "問題分析",
        "統計各類問題的發生頻率、處置方式、品質指標與負評；深入排查知識缺口並推進改善閉環。",
        versionBadge,
      ),
    );

    // 1. Filter Toolbar
    const toolbar = el("div", "analytics-toolbar");
    toolbar.append(
      createPeriodControls(period, (next) =>
        renderIssues({ ...next, query, ownerUnitId }),
      ),
    );

    const filterBar = el("div", "filter-bar");
    const unitSelect = el("select");
    unitSelect.setAttribute("aria-label", "權責單位篩選");
    const allOpt = el("option");
    allOpt.value = "";
    allOpt.textContent = "全部權責單位";
    unitSelect.append(allOpt);

    for (const cat of data.categories || []) {
      const opt = el("option");
      opt.value = cat;
      opt.textContent = cat;
      if (cat === ownerUnitId) opt.selected = true;
      unitSelect.append(opt);
    }
    const unclassOpt = el("option");
    unclassOpt.value = "other.unclassified";
    unclassOpt.textContent = "未分類 (Unclassified)";
    if (ownerUnitId === "other.unclassified") unclassOpt.selected = true;
    unitSelect.append(unclassOpt);

    unitSelect.addEventListener("change", (e) => {
      renderIssues({ ...period, query, ownerUnitId: e.target.value });
    });
    filterBar.append(unitSelect);

    const queryInput = el("input");
    queryInput.type = "search";
    queryInput.placeholder = "搜尋問題名稱或代碼";
    queryInput.value = query;
    queryInput.setAttribute("aria-label", "Issue 關鍵字");
    const applyFilter = el("button", "", "套用篩選");
    const reload = () =>
      renderIssues({
        ...period,
        query: queryInput.value.trim(),
        ownerUnitId: unitSelect.value,
      });
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
        owner_unit_id: unitSelect.value || undefined,
      })),
    );
    panel.append(toolbar);

    // Filter Chips
    const chips = [
      {
        label: "權責單位",
        value: ownerUnitId,
        onClear: () => renderIssues({ ...period, query, ownerUnitId: "" }),
      },
      {
        label: "關鍵字",
        value: query,
        onClear: () => renderIssues({ ...period, query: "", ownerUnitId }),
      },
    ];
    panel.append(
      filterChipBar(
        chips,
        query || ownerUnitId
          ? () => renderIssues({ ...period, query: "", ownerUnitId: "" })
          : null,
      ),
    );

    // 2. KPI Strip
    const totalCount = data.totalCount ?? (data.items || []).reduce((sum, item) => sum + (item.count || 0), 0);
    const totalNegFeedback = data.totalNegativeFeedbackCount ?? 0;
    const totalHandoff = data.totalHandoffCount ?? 0;
    const totalNoAnswer = data.totalNoAnswerCount ?? 0;
    const unclassCount = data.unclassifiedCount ?? 0;

    let totalChangeText = "";
    if (data.totalChangeCount != null && data.previousTotalCount != null) {
      if (data.totalChangeCount > 0) {
        totalChangeText = ` (較前期 +${formatCount(data.totalChangeCount)} / +${formatPercent(data.totalChangeRate)})`;
      } else if (data.totalChangeCount < 0) {
        totalChangeText = ` (較前期 ${formatCount(data.totalChangeCount)} / ${formatPercent(data.totalChangeRate)})`;
      } else {
        totalChangeText = " (較前期 持平)";
      }
    }

    panel.append(
      kpiStrip([
        {
          label: "Issue 總量",
          value: `${formatCount(totalCount)}${totalChangeText}`,
        },
        {
          label: "負評總數",
          value: `${formatCount(totalNegFeedback)} 筆`,
        },
        {
          label: "轉人工客服",
          value: `${formatCount(totalHandoff)} 次`,
        },
        {
          label: "未能回答",
          value: `${formatCount(totalNoAnswer)} 次`,
        },
        {
          label: "未分類數量",
          value: `${formatCount(unclassCount)} 筆`,
        },
      ]),
    );

    // 3. Info Banner
    const infoBanner = el("div", "content-guide");
    infoBanner.style.marginBottom = "1.25rem";
    infoBanner.innerHTML = `
      <strong class="content-guide-title">💡 指標計算與解讀說明</strong>
      <div class="content-guide-grid">
        <div class="content-guide-col">
          <h4>出現次數</h4>
          <p>依據對話中 Agent 辨識出的問題事件（<code>issue.extracted</code>）統計，非對話對局數（同一對話可能諮詢多個不同問題）。</p>
        </div>
        <div class="content-guide-col">
          <h4>負評率</h4>
          <p>負評數 ÷ 總回饋數（僅計算已表達意見者）。<strong>若無人填寫回饋則明確顯示「尚無回饋」</strong>，避免誤判為 100% 滿意。</p>
        </div>
        <div class="content-guide-col">
          <h4>轉人工率</h4>
          <p>處置方式為轉真人客服（<code>HANDOFF</code>）的次數 ÷ 該問題總出現次數。高轉人工率代表知識庫或 FAQ 覆蓋不足。</p>
        </div>
        <div class="content-guide-col">
          <h4>改善閉環行動</h4>
          <p>透過排行榜排序快速鎖定「負評最多」或「轉人工最多」的問題，點擊「查看詳情」排查依據文件並派案修訂。</p>
        </div>
      </div>
    `;
    panel.append(infoBanner);

    if (!(data.items || []).length) {
      panel.append(
        emptyState(
          "選定期間沒有 Issue 資料",
          "請切換篩選條件、拉長期間，或至對話驗證確認是否已記錄 Issue 事件。",
        ),
      );
      finishIssuesPage(panel);
      return;
    }

    // 4. Issue Leaderboard Table
    const nameMap = {};
    for (const item of data.items) {
      nameMap[item.issueTypeId] = item.displayName;
    }

    const leaderboardSection = el("section", "analytics-section");
    leaderboardSection.style.marginBottom = "2rem";

    const boardHeader = el("div", "analytics-section-title");
    boardHeader.style.display = "flex";
    boardHeader.style.justifyContent = "space-between";
    boardHeader.style.alignItems = "center";
    boardHeader.style.flexWrap = "wrap";
    boardHeader.style.gap = "0.5rem";

    const boardLeft = el("div");
    boardLeft.append(
      el("h3", "", "Issue 排行榜"),
      el("span", "metric-label", "按指標排名快速找出痛點，並可進一步查看處理方式、負評詳情與相關對話"),
    );
    boardHeader.append(boardLeft);

    const sortTabsWrap = el("div", "filter-bar");
    sortTabsWrap.style.margin = "0";
    const sortButtons = new Map();
    const sortConfigs = [
      { key: "count", label: "🔥 總量最多", title: "依問題出現次數排序" },
      { key: "negative", label: "👎 負評最多", title: "依負評絕對筆數排序" },
      { key: "negative_rate", label: "⚠️ 負評率最高", title: "依負評率排序（僅排有回饋資料者）" },
      { key: "handoff", label: "轉人工最多", title: "依轉人工次數排序" },
      { key: "no_answer", label: "未能回答最多", title: "依未能回答次數排序" },
      { key: "increase", label: "📈 增加最多", title: "較前期絕對增加量排序" },
    ];

    const table = el("table");
    table.innerHTML = `
      <thead>
        <tr>
          <th>排名</th>
          <th>問題名稱 / 代碼</th>
          <th>權責單位</th>
          <th>出現次數</th>
          <th>佔比</th>
          <th>前期比較</th>
          <th>負評次數 (負評率)</th>
          <th>轉人工次數 (轉人工率)</th>
          <th>未能回答</th>
          <th>主要處置方式</th>
          <th>操作 / 改善閉環</th>
        </tr>
      </thead>
    `;
    const tbody = el("tbody");
    table.append(tbody);

    const renderRows = (sortKey) => {
      for (const [key, btn] of sortButtons.entries()) {
        btn.classList.toggle("active", key === sortKey);
      }
      tbody.replaceChildren();

      const sortedItems = [...data.items].sort((a, b) => {
        if (sortKey === "negative") {
          return (b.negativeFeedbackCount || 0) - (a.negativeFeedbackCount || 0);
        }
        if (sortKey === "negative_rate") {
          const rateA = a.negativeFeedbackRate ?? -1;
          const rateB = b.negativeFeedbackRate ?? -1;
          return rateB - rateA;
        }
        if (sortKey === "handoff") {
          return (b.handoffCount || 0) - (a.handoffCount || 0);
        }
        if (sortKey === "no_answer") {
          return (b.noAnswerCount || 0) - (a.noAnswerCount || 0);
        }
        if (sortKey === "increase") {
          return (b.changeCount || 0) - (a.changeCount || 0);
        }
        return (b.count || 0) - (a.count || 0);
      });

      let rank = 1;
      for (const item of sortedItems) {
        const row = el("tr");
        const rankBadge = el("span", rank <= 3 ? "badge badge-accent" : "metric-label", `#${rank++}`);
        const rankCell = el("td");
        rankCell.append(rankBadge);
        row.append(rankCell);

        const nameCell = el("td");
        nameCell.append(
          el("div", "font-medium", item.displayName),
          el("div", "analytics-mono text-muted", item.issueTypeId),
        );
        row.append(nameCell);

        row.append(el("td", "", item.ownerUnitId || "未指定"));
        row.append(el("td", "font-bold", formatCount(item.count)));

        const sharePct = data.totalCount > 0 ? (item.count / data.totalCount) : (item.share || 0);
        row.append(shareBarCell(sharePct));

        let changeText = "-";
        let changeClass = "text-muted";
        if (item.changeCount != null) {
          if (item.changeCount > 0) {
            changeText = `+${formatCount(item.changeCount)}`;
            changeClass = "text-danger";
          } else if (item.changeCount < 0) {
            changeText = `${formatCount(item.changeCount)}`;
            changeClass = "text-success";
          } else {
            changeText = "持平";
          }
        }
        row.append(el("td", changeClass, changeText));

        const negRateText = item.negativeFeedbackRate != null ? formatPercent(item.negativeFeedbackRate) : "尚無回饋";
        const negCell = el("td");
        negCell.append(
          el("span", item.negativeFeedbackCount > 0 ? "font-bold text-danger" : "", formatCount(item.negativeFeedbackCount || 0)),
          el("span", "text-muted", ` (${negRateText})`),
        );
        row.append(negCell);

        const handoffRateText = item.handoffRate != null ? formatPercent(item.handoffRate) : "-";
        const handoffCell = el("td");
        handoffCell.append(
          el("span", item.handoffCount > 0 ? "font-bold" : "", formatCount(item.handoffCount || 0)),
          el("span", "text-muted", ` (${handoffRateText})`),
        );
        row.append(handoffCell);

        row.append(el("td", "", formatCount(item.noAnswerCount || 0)));

        const routeCell = el("td");
        routeCell.append(routeBadge(item.primaryRoute));
        row.append(routeCell);

        const detailBtn = el("button", "button-link", "查看詳情");
        detailBtn.addEventListener("click", () => {
          navigateTo("issues", {
            issueTypeId: item.issueTypeId,
            ...periodToNavFilters(period),
          });
        });

        let negDrillNode;
        if (item.negativeFeedbackCount > 0) {
          negDrillNode = drillLink(
            `👎 ${formatCount(item.negativeFeedbackCount)}`,
            "conversations",
            withReturnTo(
              {
                issueTypeId: item.issueTypeId,
                rating: "DOWN",
                ...periodToNavFilters(period),
              },
              "issues",
              periodToNavFilters(period),
            ),
          );
          negDrillNode.title = "直接前往查看此 Issue 的負評對話明細";
        } else {
          negDrillNode = el("span", "metric-label", "尚無負評");
          negDrillNode.style.display = "inline-flex";
          negDrillNode.style.alignItems = "center";
          negDrillNode.style.padding = "0.38rem 0.5rem";
          negDrillNode.style.color = "var(--text-muted, #94a3b8)";
        }

        row.append(actionCell(detailBtn, negDrillNode));
        tbody.append(row);
      }
    };

    for (const conf of sortConfigs) {
      const btn = el("button", "button-link", conf.label);
      btn.type = "button";
      btn.style.fontSize = "0.78rem";
      btn.style.padding = "0.3rem 0.65rem";
      btn.style.margin = "0";
      btn.addEventListener("click", () => renderRows(conf.key));
      sortButtons.set(conf.key, btn);
      sortTabsWrap.append(btn);
    }
    boardHeader.append(sortTabsWrap);
    leaderboardSection.append(boardHeader);

    const issuesScroll = el("div", "table-scroll-box");
    issuesScroll.append(table);
    leaderboardSection.append(issuesScroll);
    panel.append(leaderboardSection);

    renderRows("count");

    // 5. Trend Section
    panel.append(renderTrendSection(data.trends, nameMap, period, data.items));

    // 6. Taxonomy Hierarchy
    if (data.hierarchy?.length) {
      const details = el("details");
      details.style.marginTop = "1.5rem";
      details.style.background = "var(--panel-muted, #f8fafc)";
      details.style.border = "1px solid var(--border-subtle, #e2e8f0)";
      details.style.borderRadius = "var(--radius-sm, 8px)";
      details.style.padding = "0.75rem 1rem";

      const summary = el("summary");
      summary.style.cursor = "pointer";
      summary.style.fontWeight = "700";
      summary.style.fontSize = "0.95rem";
      summary.style.color = "var(--text, #0f172a)";
      summary.innerHTML = "🗂️ 展開問題分類階層結構 (Taxonomy 階層與彙總) <span class=\"metric-label\" style=\"margin-left:0.5rem;\">點擊展開／收合</span>";
      details.append(summary);

      const tree = el("ul", "issue-tree");
      tree.style.marginTop = "0.75rem";
      for (const node of data.hierarchy) {
        tree.append(renderIssueTreeNode(node, 0, period));
      }
      details.append(tree);
      panel.append(details);
    }

    finishIssuesPage(panel);
  } catch (error) {
    if (!stillOnIssues()) {
      return;
    }
    document.getElementById("app").replaceChildren(
      el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message),
    );
  }
}

export const issuesPage = createPageController({
  enter: async (context = {}) => renderIssues(context.state || { preset: "30d" }),
  update: async (context = {}) => renderIssues(context.state || { preset: "30d" }),
  leave: async () => {},
});
