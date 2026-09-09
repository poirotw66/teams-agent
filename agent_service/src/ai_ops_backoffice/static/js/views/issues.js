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
  navigateTo,
} from "../app/navigation.js";
import { createPageController } from "../app/lifecycle.js";
import { showIssueDetailModal } from "../components/issueModal.js";
import { showConversationModal } from "../components/conversationModal.js";
import { presentAnalyticsPage } from "../app/analyticsChrome.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { withReturnTo } from "../app/returnTo.js";

function stillOnIssues() {
  const view = loadNavFilters().view;
  return !view || view === "issues";
}

function finishIssuesPage(panel) {
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

function periodToNavFilters(period) {
  if (period?.preset === "custom") {
    return { preset: "custom", start: period.start || "", end: period.end || "" };
  }
  return { preset: period?.preset || "30d" };
}

function periodLabel(period) {
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

function renderIssueTreeNode(node, depth = 0, period = { preset: "30d" }) {
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


function renderTrendSection(trends, nameMap, period, allItems = []) {
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
      // Filter trend data to only the selected issue
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

function renderIssueRouteDrill(data, period, query) {
  const panel = el("section", "panel");
  const back = drillLink("← 返回問題總覽", "issues", { clear: true });
  panel.append(
    pageHeader(
      `${data.displayName || data.issueTypeId}｜問題分析詳情`,
      `代碼：${data.issueTypeId}｜權責單位：${data.ownerUnitId || "未指定"}｜期間：${periodLabel(period)}`,
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

  const totalCount = data.totalCount || 0;
  const negCount = data.negativeFeedbackCount || 0;
  const handoffCount = data.handoffCount || 0;
  const noAnsCount = data.noAnswerCount || 0;

  const negRate = totalCount > 0 ? formatPercent(negCount / totalCount) : "0%";
  const handoffRate = totalCount > 0 ? formatPercent(handoffCount / totalCount) : "0%";

  panel.append(
    kpiStrip([
      { label: "出現次數", value: formatCount(totalCount) },
      {
        label: "負評次數",
        value: negCount > 0 ? `${formatCount(negCount)} 筆 (${negRate})` : "尚無負評",
      },
      {
        label: "轉人工客服",
        value: `${formatCount(handoffCount)} 次 (${handoffRate})`,
      },
      { label: "未能回答", value: formatCount(noAnsCount) },
    ]),
  );

  if (data.description) {
    const descCard = el("div", "content-guide");
    descCard.style.margin = "0.75rem 0 1.25rem";
    descCard.innerHTML = `<strong>問題說明：</strong> ${data.description}`;
    panel.append(descCard);
  }

  // 1. 處理方式 (Route Distribution)
  const secRoutes = el("section", "analytics-section");
  secRoutes.style.marginBottom = "1.5rem";
  const routeTitle = el("div", "analytics-section-title");
  routeTitle.append(
    el("h3", "", "處理方式（AI 處置分流分布）"),
    el("span", "metric-label", "AI 如何處理此問題：FAQ、知識檢索 HYBRID、轉真人客服 HANDOFF 等"),
  );
  secRoutes.append(routeTitle);

  const routes = data.routes || [];
  if (!routes.length) {
    secRoutes.append(
      emptyState(
        "此問題在選定期間尚無分流紀錄",
        "可拉長查詢期間，或至對話驗證確認是否已有 issue.extracted 與 route.selected 事件。",
      ),
    );
  } else {
    const routeTable = el("table");
    routeTable.innerHTML = `
      <thead>
        <tr>
          <th>處理方式 (Route)</th>
          <th>次數</th>
          <th>佔比</th>
          <th>回答依據（FAQ／知識庫文件）</th>
        </tr>
      </thead>
    `;
    const tbody = el("tbody");
    for (const rt of routes) {
      const row = el("tr");
      const rtCell = el("td");
      rtCell.append(routeBadge(rt.route));
      row.append(rtCell);
      row.append(el("td", "", formatCount(rt.count)));
      const sharePct = totalCount > 0 ? formatPercent(rt.count / totalCount) : "-";
      row.append(el("td", "", sharePct));
      row.append(attributionCell(rt.attribution, { issueTypeId: data.issueTypeId }));
      tbody.append(row);
    }
    routeTable.append(tbody);
    const wrap = el("div", "table-responsive");
    wrap.append(routeTable);
    secRoutes.append(wrap);
  }
  panel.append(secRoutes);

  // 2. 回答依據與知識文件 (Knowledge Sources & FAQ Keys)
  const allDocIds = new Set();
  const allSourcePaths = new Set();
  const allFaqKeys = new Set();
  for (const rt of routes) {
    const attr = rt.attribution || {};
    (attr.documentIds || []).forEach((item) => item.id && allDocIds.add(item.id));
    (attr.sourcePaths || []).forEach((item) => item.id && allSourcePaths.add(item.id));
    (attr.faqKeys || []).forEach((item) => item.id && allFaqKeys.add(item.id));
  }

  const secSources = el("section", "analytics-section");
  secSources.style.marginBottom = "1.5rem";
  const srcTitle = el("div", "analytics-section-title");
  srcTitle.append(
    el("h3", "", "回答依據與知識文件（改善入口）"),
    el("span", "metric-label", "AI 回答此問題時引用的知識庫文件或 FAQ 項目，可快速檢視或修訂"),
  );
  secSources.append(srcTitle);

  const sourcesBox = el("div");
  sourcesBox.style.padding = "0.85rem 1rem";
  sourcesBox.style.background = "var(--panel-muted, #f8fafc)";
  sourcesBox.style.border = "1px solid var(--border-subtle, #e2e8f0)";
  sourcesBox.style.borderRadius = "var(--radius-sm, 8px)";

  if (!allDocIds.size && !allSourcePaths.size && !allFaqKeys.size) {
    sourcesBox.append(el("p", "empty", "未引用具體文件或 FAQ（可能多由對話模型直接回覆或直接轉人工）。"));
  } else {
    if (allSourcePaths.size || allDocIds.size) {
      const docGroup = el("div");
      docGroup.style.marginBottom = "0.75rem";
      const docHeading = el("div", "", "📚 引用的知識庫文件：");
      docHeading.style.fontWeight = "600";
      docHeading.style.marginBottom = "0.35rem";
      docGroup.append(docHeading);

      const list = el("ul");
      list.style.margin = "0";
      list.style.paddingLeft = "1.25rem";

      const combinedDocs = Array.from(allSourcePaths.size ? allSourcePaths : allDocIds);
      for (const doc of combinedDocs) {
        const li = el("li");
        li.style.marginBottom = "0.35rem";
        li.append(el("span", "analytics-mono", doc));
        li.append(document.createTextNode(" "));

        const actionBtn = el("button", "btn-secondary btn-small", "📄 前往知識庫檢視／修訂");
        actionBtn.style.fontSize = "0.75rem";
        actionBtn.style.padding = "0.15rem 0.5rem";
        actionBtn.style.marginLeft = "0.5rem";
        actionBtn.addEventListener("click", () => {
          navigateTo("knowledge", { query: doc });
        });
        li.append(actionBtn);
        list.append(li);
      }
      docGroup.append(list);
      sourcesBox.append(docGroup);
    }

    if (allFaqKeys.size) {
      const faqGroup = el("div");
      const faqHeading = el("div", "", "❓ 引用的 FAQ 項目：");
      faqHeading.style.fontWeight = "600";
      faqHeading.style.marginBottom = "0.35rem";
      faqGroup.append(faqHeading);

      const list = el("ul");
      list.style.margin = "0";
      list.style.paddingLeft = "1.25rem";
      for (const key of allFaqKeys) {
        const li = el("li");
        li.style.marginBottom = "0.35rem";
        li.append(el("span", "analytics-mono", key));
        li.append(document.createTextNode(" "));

        const actionBtn = el("button", "btn-secondary btn-small", "❓ 前往 FAQ 編輯");
        actionBtn.style.fontSize = "0.75rem";
        actionBtn.style.padding = "0.15rem 0.5rem";
        actionBtn.style.marginLeft = "0.5rem";
        actionBtn.addEventListener("click", () => {
          navigateTo("faq", { query: key });
        });
        li.append(actionBtn);
        list.append(li);
      }
      faqGroup.append(list);
      sourcesBox.append(faqGroup);
    }
  }
  secSources.append(sourcesBox);
  panel.append(secSources);

  // 3. 使用者負評紀錄
  const secFeedback = el("section", "analytics-section");
  secFeedback.style.marginBottom = "1.5rem";
  const fbTitle = el("div", "analytics-section-title");
  fbTitle.append(
    el("h3", "", `使用者負評紀錄 (${negCount} 筆)`),
    el("span", "metric-label", "查看使用者對此問題回答的不滿原因與上下文，協助確認需補充之知識"),
  );
  secFeedback.append(fbTitle);

  const feedbacks = data.negativeFeedbacks || [];
  if (!feedbacks.length) {
    secFeedback.append(el("p", "empty", "選定期間內尚無負評紀錄。"));
  } else {
    const fbList = el("div");
    fbList.style.display = "flex";
    fbList.style.flexDirection = "column";
    fbList.style.gap = "0.75rem";

    for (const fb of feedbacks) {
      const item = el("div");
      item.style.padding = "0.75rem 1rem";
      item.style.borderLeft = "4px solid var(--text-danger, #ef4444)";
      item.style.background = "var(--panel-muted, #f8fafc)";
      item.style.borderRadius = "4px";

      const topRow = el("div");
      topRow.style.display = "flex";
      topRow.style.justifyContent = "space-between";
      topRow.style.fontSize = "0.8rem";
      topRow.style.color = "var(--text-muted, #64748b)";

      topRow.append(
        el("span", "", `時間：${fb.occurredAt ? fb.occurredAt.replace("T", " ").slice(0, 19) : "-"}`),
        fb.resolvedStatus ? el("span", "badge badge-neutral", fb.resolvedStatus) : el("span"),
      );
      item.append(topRow);

      const reasonRow = el("div");
      reasonRow.style.marginTop = "0.35rem";
      reasonRow.style.fontSize = "0.9rem";
      reasonRow.style.fontWeight = "600";
      reasonRow.style.color = "var(--text-danger, #b91c1c)";
      reasonRow.textContent = `❌ 負評原因：${fb.reason || "未填寫原因"}`;
      item.append(reasonRow);

      if (fb.userMessage) {
        const uMsg = el("div");
        uMsg.style.fontSize = "0.85rem";
        uMsg.style.marginTop = "0.25rem";
        uMsg.innerHTML = `<span style="color:var(--text-muted);">提問：</span> ${fb.userMessage}`;
        item.append(uMsg);
      }

      if (fb.aiReply) {
        const aReply = el("div");
        aReply.style.fontSize = "0.85rem";
        aReply.style.marginTop = "0.2rem";
        aReply.innerHTML = `<span style="color:var(--text-muted);">回覆：</span> ${fb.aiReply.slice(0, 140)}${fb.aiReply.length > 140 ? "…" : ""}`;
        item.append(aReply);
      }

      if (fb.conversationId) {
        const viewConvBtn = el("button", "button-link", "🔍 查看該筆對話");
        viewConvBtn.style.fontSize = "0.75rem";
        viewConvBtn.style.marginTop = "0.4rem";
        viewConvBtn.addEventListener("click", async () => {
          try {
            const detail = await api(`/api/conversations/${encodeURIComponent(fb.conversationId)}`);
            showConversationModal(detail, fb.conversationId);
          } catch (err) {
            alert(`無法載入對話：${err.message}`);
          }
        });
        item.append(viewConvBtn);
      }

      fbList.append(item);
    }
    secFeedback.append(fbList);
  }
  panel.append(secFeedback);

  // 4. Action Footer
  const footer = el("div", "filter-bar");
  footer.style.marginTop = "1.5rem";
  footer.style.paddingTop = "1rem";
  footer.style.borderTop = "1px solid var(--border-subtle, #e2e8f0)";
  footer.style.display = "flex";
  footer.style.justifyContent = "space-between";
  footer.style.alignItems = "center";

  const leftActions = el("div");
  leftActions.style.display = "flex";
  leftActions.style.gap = "0.6rem";
  leftActions.style.flexWrap = "wrap";

  leftActions.append(
    drillLink(
      `💬 查看相關對話 (${formatCount(totalCount)} 筆)`,
      "conversations",
      withReturnTo(
        {
          issueTypeId: data.issueTypeId,
          ...periodToNavFilters(period),
        },
        "issues",
        {
          issueTypeId: data.issueTypeId,
          ...periodToNavFilters(period),
        },
      ),
    ),
  );

  if (negCount > 0) {
    leftActions.append(
      drillLink(
        `⚠️ 前往品質案件處理 (${formatCount(negCount)} 筆負評)`,
        "quality",
        withReturnTo(
          {
            rating: "DOWN",
            issueTypeId: data.issueTypeId,
            ...periodToNavFilters(period),
          },
          "issues",
          {
            issueTypeId: data.issueTypeId,
            ...periodToNavFilters(period),
          },
        ),
      ),
    );
  }

  footer.append(leftActions, back);
  panel.append(footer);
  return panel;
}

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
      finishIssuesPage(renderIssueRouteDrill(data, period, query));
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

    // ==========================================
    // 1. 篩選列 (Filter Toolbar)
    // ==========================================
    const toolbar = el("div", "analytics-toolbar");
    toolbar.append(
      createPeriodControls(period, (next) =>
        renderIssues({ ...next, query, ownerUnitId }),
      ),
    );

    const filterBar = el("div", "filter-bar");

    // Owner Unit / Category selector
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

    // Keyword search input
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

    // ==========================================
    // 2. 重點摘要 (KPI Strip)
    // ==========================================
    const totalCount = data.totalCount ?? (data.items || []).reduce((sum, item) => sum + (item.count || 0), 0);
    const totalNegFeedback = data.totalNegativeFeedbackCount ?? 0;
    const totalFeedback = data.totalFeedbackCount ?? 0;
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

    // ==========================================
    // 3. 指標計算方式說明 (Info Banner)
    // ==========================================
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
          query || ownerUnitId
            ? "請調整篩選條件或清除關鍵字後再試。"
            : "確認 Agent 已寫入 issue.extracted 事件，或拉長查詢期間。",
        ),
      );
      finishIssuesPage(panel);
      return;
    }

    // ==========================================
    // 4. 問題排行榜 (Leaderboard Table with Tabs)
    // ==========================================
    const leaderboardSection = el("section", "analytics-section");
    leaderboardSection.style.marginBottom = "1.5rem";

    const boardHeader = el("div", "analytics-section-title");
    boardHeader.style.display = "flex";
    boardHeader.style.justifyContent = "space-between";
    boardHeader.style.alignItems = "center";
    boardHeader.style.flexWrap = "wrap";
    boardHeader.style.gap = "0.75rem";

    const boardTitle = el("div");
    boardTitle.append(
      el("h3", "", "問題排行榜"),
      el("span", "metric-label", "排序切換快速找出改善重點；點擊「查看詳情」深入排查，點擊「查看負評」下鑽品質案件"),
    );
    boardHeader.append(boardTitle);

    // Sort tabs
    const sortTabsWrap = el("div", "filter-bar");
    sortTabsWrap.style.margin = "0";
    sortTabsWrap.style.gap = "0.35rem";

    const sortConfigs = [
      { key: "count", label: "🔥 問題量最多 (預設)" },
      { key: "negativeFeedbackCount", label: "👎 負評最多" },
      { key: "changeCount", label: "📈 增加最多" },
      { key: "handoffCount", label: "👤 轉人工最多" },
    ];

    let currentSortKey = "count";
    const sortButtons = new Map();

    const table = el("table");
    table.innerHTML = `
      <thead>
        <tr>
          <th>問題 (Issue)</th>
          <th>出現次數 / 佔比</th>
          <th>較前期</th>
          <th>負評</th>
          <th>轉人工</th>
          <th>未能回答</th>
          <th>成本 USD</th>
          <th>動作</th>
        </tr>
      </thead>
    `;
    const tbody = el("tbody");
    table.append(tbody);

    const nameMap = {};
    for (const item of data.items) {
      nameMap[item.issueTypeId] = item.displayName;
    }

    const sortItems = (key) => {
      const itemsCopy = [...data.items];
      if (key === "negativeFeedbackCount") {
        return itemsCopy.sort((a, b) => (b.negativeFeedbackCount || 0) - (a.negativeFeedbackCount || 0) || (b.count || 0) - (a.count || 0));
      }
      if (key === "changeCount") {
        return itemsCopy.sort((a, b) => (b.changeCount || 0) - (a.changeCount || 0) || (b.count || 0) - (a.count || 0));
      }
      if (key === "handoffCount") {
        return itemsCopy.sort((a, b) => (b.handoffCount || 0) - (a.handoffCount || 0) || (b.count || 0) - (a.count || 0));
      }
      // default: count
      return itemsCopy.sort((a, b) => (b.count || 0) - (a.count || 0));
    };

    const renderRows = (key) => {
      currentSortKey = key;
      for (const [sKey, btn] of sortButtons.entries()) {
        if (sKey === key) {
          btn.style.background = "var(--accent, #2563eb)";
          btn.style.color = "#ffffff";
          btn.style.borderColor = "var(--accent, #2563eb)";
        } else {
          btn.style.background = "var(--panel-muted, #f8fafc)";
          btn.style.color = "var(--text-secondary, #475569)";
          btn.style.borderColor = "var(--border-subtle, #e2e8f0)";
        }
      }

      tbody.replaceChildren();
      const sorted = sortItems(key);

      for (const item of sorted) {
        const row = el("tr");

        // 1. Issue Name + ID + Owner Unit Badge
        const nameCell = el("td", "");
        const titleLine = el("div", "", item.displayName);
        titleLine.style.fontWeight = "600";
        nameCell.append(titleLine);

        const subLine = el("div", "");
        subLine.style.display = "flex";
        subLine.style.alignItems = "center";
        subLine.style.gap = "0.4rem";
        subLine.style.marginTop = "0.2rem";
        subLine.append(el("span", "analytics-mono", item.issueTypeId));
        if (item.ownerUnitId) {
          subLine.append(badge(item.ownerUnitId, "neutral"));
        }
        nameCell.append(subLine);
        row.append(nameCell);

        // 2. Count + Share Bar
        row.append(shareBarCell(item.share));

        // 3. Period-over-period change
        const changeCell = el("td", "");
        if (item.previousCount === 0 && (item.count || 0) > 0) {
          changeCell.append(badge("新出現", "accent"));
        } else if ((item.changeCount || 0) > 0) {
          const changeSpan = el("span", "", `+${item.changeCount} (${formatPercent(item.changeRate)})`);
          changeSpan.style.color = "var(--text-danger, #dc2626)";
          changeSpan.style.fontWeight = "600";
          changeCell.append(changeSpan);
        } else if ((item.changeCount || 0) < 0) {
          const changeSpan = el("span", "", `${item.changeCount} (${formatPercent(item.changeRate)})`);
          changeSpan.style.color = "var(--text-success, #16a34a)";
          changeSpan.style.fontWeight = "600";
          changeCell.append(changeSpan);
        } else {
          changeCell.append(el("span", "metric-label", "持平"));
        }
        row.append(changeCell);

        // 4. Negative Feedback
        const feedbackCell = el("td", "");
        if ((item.feedbackCount || 0) > 0) {
          const negCountText = `${formatCount(item.negativeFeedbackCount || 0)} 筆`;
          const negRateText = `負評率 ${formatPercent(item.negativeFeedbackRate || 0)}`;
          feedbackCell.append(
            el("div", "", negCountText),
            el("div", "metric-label", negRateText),
          );
        } else {
          const noFb = el("span", "metric-label", "尚無回饋");
          noFb.style.color = "var(--text-muted, #94a3b8)";
          feedbackCell.append(noFb);
        }
        row.append(feedbackCell);

        // 5. Handoff
        const handoffCell = el("td", "");
        handoffCell.append(
          el("div", "", `${formatCount(item.handoffCount || 0)} 次`),
          el("div", "metric-label", `轉人工率 ${formatPercent(item.handoffRate || 0)}`),
        );
        row.append(handoffCell);

        // 6. No Answer
        const noAnsCell = el("td", "");
        noAnsCell.append(el("div", "", `${formatCount(item.noAnswerCount || 0)} 次`));
        row.append(noAnsCell);

        // 7. Cost USD
        row.append(el("td", "analytics-mono", Number(item.estimatedCostUsd ?? 0).toFixed(4)));

        // 8. Actions (Consolidated into 2 clear entries)
        const detailBtn = el("button", "button-link", "查看詳情");
        detailBtn.addEventListener("click", () => {
          showIssueDetailModal(item.issueTypeId, period);
        });

        let negDrillNode;
        if ((item.negativeFeedbackCount || 0) > 0) {
          negDrillNode = drillLink(
            `查看負評 (${item.negativeFeedbackCount} 筆)`,
            "quality",
            withReturnTo(
              {
                rating: "DOWN",
                issueTypeId: item.issueTypeId,
                ...periodToNavFilters(period),
              },
              "issues",
              {
                issueTypeId: item.issueTypeId,
                ...periodToNavFilters(period),
              },
            ),
          );
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

    // Initial table render
    renderRows("count");

    // ==========================================
    // 5. 趨勢圖 (Trend Section)
    // ==========================================
    panel.append(renderTrendSection(data.trends, nameMap, period, data.items));

    // ==========================================
    // 6. 問題分類結構 (Taxonomy Hierarchy inside <details>)
    // ==========================================
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
