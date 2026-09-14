import { api, el } from "../../api.js";
import { showContentModal } from "../../components/modal.js";
import { showConversationModal } from "../../components/conversationModal.js";
import { renderContentPolicyBanner } from "../../components/contentGuide.js";
import { runExport } from "../../services/export.js";
import { getCapabilities } from "../../app/capabilities.js";
import { buildLocationHash, navigateTo } from "../../app/navigation.js";
import { isBuShellEnabled } from "../../app/buShellConfig.js";
import { presentAnalyticsPage } from "../../app/analyticsChrome.js";
import { loadingState } from "../../components/state.js";
import { formatUserFacingError, labelStatus } from "../../app/labels.js";
import { kpiStrip } from "../../components/analyticsUi.js";

export async function renderKnowledge() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  if (!isBuShellEnabled()) {
    panel.append(el("h2", "", "內容成效"));
  }
  panel.append(renderContentPolicyBanner({ compact: true }));
  const toolbar = el("div", "analytics-toolbar");
  if (getCapabilities()?.knowledgeBridgeEnabled) {
    const openPortal = el("a", "button-link", isBuShellEnabled() ? "開啟知識內容" : "開啟知識文件庫");
    openPortal.href = buildLocationHash(
      "knowledge_ops",
      isBuShellEnabled() ? "contentLists" : "knowledgePortal",
    );
    openPortal.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
        return;
      }
      event.preventDefault();
      navigateTo(isBuShellEnabled() ? "contentLists" : "knowledgePortal");
    });
    openPortal.style.marginRight = "0.5rem";
    toolbar.append(openPortal);
  } else {
    const link = el("a", "button-link", "開啟 Knowledge Portal");
    link.href = getCapabilities()?.knowledgePortalUrl || "http://127.0.0.1:8091";
    link.target = "_blank";
    toolbar.append(link);
  }
  const exportButton = el("button", "", "匯出 CSV");
  toolbar.append(exportButton);
  panel.append(toolbar);

  const filters = el("form", "filter-bar knowledge-filters ov-controls");
  filters.style.marginTop = "1rem";
  const query = el("input");
  query.style.minWidth = "220px";
  query.placeholder = "搜尋標題或文件 ID";
  query.setAttribute("aria-label", "搜尋知識文件");
  const owner = el("input");
  owner.placeholder = "負責單位";
  owner.setAttribute("aria-label", "負責單位");
  const status = el("select");
  status.setAttribute("aria-label", "生命週期狀態");
  for (const [value, label] of [
    ["", "所有狀態"],
    ["DRAFT", "草稿"],
    ["IN_REVIEW", "審核中"],
    ["APPROVED", "已核准"],
    ["PUBLISHED", "已發布"],
    ["ARCHIVED", "已封存"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    status.append(option);
  }
  const formatType = el("select");
  formatType.setAttribute("aria-label", "文件格式");
  for (const [value, label] of [
    ["", "所有格式"],
    ["markdown", "Markdown (.md)"],
    ["docx", "Word (.docx)"],
    ["pdf", "PDF (.pdf)"],
    ["xlsx", "Excel (.xlsx)"],
    ["csv", "CSV (.csv)"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    formatType.append(option);
  }
  const days = el("select");
  days.setAttribute("aria-label", "成效統計區間");
  for (const [value, label] of [
    ["30", "最近 30 天"],
    ["7", "最近 7 天"],
    ["186", "最近 6 個月"],
    ["365", "最近 1 年"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    days.append(option);
  }
  const submit = el("button", "", "查詢");
  filters.append(query, owner, status, formatType, days, submit);
  panel.append(filters);

  const tableContainer = el("div");
  panel.append(tableContainer);

  async function loadDocuments(cursor = "") {
    tableContainer.replaceChildren(loadingState("正在載入文件清單…", 4));
    const params = new URLSearchParams();
    if (query.value.trim()) params.set("query", query.value.trim());
    if (owner.value.trim()) params.set("owner_unit_id", owner.value.trim());
    if (status.value) params.set("status", status.value);
    if (formatType.value) params.set("format_type", formatType.value);
    if (days.value) params.set("days", days.value);
    if (cursor) params.set("cursor", cursor);
    try {
      const data = await api(`/api/knowledge?${params}`);
      tableContainer.replaceChildren(
        renderKnowledgeInventory(data, loadDocuments, {
          days: days.value || "30",
        }),
      );
    } catch (error) {
      tableContainer.replaceChildren(el("div", "error", formatUserFacingError(error)));
    }
  }

  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    loadDocuments();
  });

  exportButton.addEventListener("click", () => {
    runExport("knowledge_performance", {
      preset: days.value ? `${days.value}d` : "30d",
      days: days.value || "30",
      query: query.value.trim() || undefined,
      owner_unit_id: owner.value.trim() || undefined,
      status: status.value || undefined,
      format_type: formatType.value || undefined,
    });
  });

  if (isBuShellEnabled()) {
    presentAnalyticsPage(
      "knowledge",
      "內容成效",
      "文件有沒有被用到，以及使用者是否覺得有幫助。",
      panel,
    );
  } else {
    app.replaceChildren(panel);
  }
  await loadDocuments();
}

export function renderKnowledgeInventory(data, loadDocuments, options = {}) {
  const days = options.days || String(data.periodDays || 30);
  const container = el("div");
  if (data.warning) container.append(el("p", "warning", data.warning));
  const summary = el(
    "p",
    "",
    `共 ${data.total || 0} 份文件，統計 ${data.periodDays || days} 天` +
      (data.filterFormatType ? `，格式 ${data.filterFormatType}` : ""),
  );
  container.append(summary);
  if (!(data.items || []).length) {
    container.append(el("p", "empty", "沒有符合條件的知識文件。"));
    return container;
  }
  const table = el("table");
  table.innerHTML = [
    "<thead><tr>",
    "<th>文件</th><th>格式</th><th>負責單位</th><th>生命週期</th><th>解析 / 索引</th>",
    "<th style=\"text-align:right;\">命中</th><th style=\"text-align:right;\">對話</th>",
    "<th style=\"text-align:right;\">正面</th><th style=\"text-align:right;\">負面</th><th>操作</th>",
    "</tr></thead>",
  ].join("");
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    const documentCell = el("td");
    documentCell.append(
      el("strong", "", item.title || item.documentId),
      el("div", "metric-label", item.documentId),
    );
    const detailButton = el("button", "", "查看成效");
    detailButton.addEventListener("click", async () => {
      detailButton.disabled = true;
      try {
        await openDocumentPerformanceModal(item.documentId, item.title || item.documentId, {
          days,
        });
      } catch (error) {
        showContentModal("知識文件成效", el("div", "error", error.message));
      } finally {
        detailButton.disabled = false;
      }
    });
    const actionCell = el("td");
    actionCell.append(detailButton);
    const hitCell = el("td", "", String(item.hitCount || 0));
    hitCell.style.textAlign = "right";
    hitCell.style.fontVariantNumeric = "tabular-nums";
    const convCell = el("td", "", String(item.conversationCount || 0));
    convCell.style.textAlign = "right";
    convCell.style.fontVariantNumeric = "tabular-nums";
    const posCell = el("td", "", String(item.positiveFeedbackCount || 0));
    posCell.style.textAlign = "right";
    posCell.style.fontVariantNumeric = "tabular-nums";
    const negCell = el("td", "", String(item.negativeFeedbackCount || 0));
    negCell.style.textAlign = "right";
    negCell.style.fontVariantNumeric = "tabular-nums";
    row.append(
      documentCell,
      el("td", "", item.formatFamily || item.formatType || "-"),
      el("td", "", item.ownerUnitId || "-"),
      el("td", "", labelStatus(item.lifecycleStatus)),
      el("td", "", `${labelStatus(item.parseStatus)} / ${labelStatus(item.indexStatus)}`),
      hitCell,
      convCell,
      posCell,
      negCell,
      actionCell,
    );
    body.append(row);
  }
  table.append(body);
  const scrollWrapper = el("div", "table-responsive");
  scrollWrapper.append(table);
  container.append(scrollWrapper);
  if (data.nextCursor) {
    const next = el("button", "", "下一頁");
    next.style.marginTop = "1rem";
    next.addEventListener("click", () => loadDocuments(data.nextCursor));
    container.append(next);
  }
  return container;
}

export async function openDocumentPerformanceModal(documentId, title, initial = {}) {
  const state = {
    days: String(initial.days || "186"),
    issueTypeId: initial.issueTypeId || "",
    cursor: "",
  };
  const root = el("div");

  const reload = async () => {
    root.replaceChildren(el("p", "empty", "載入中…"));
    const params = new URLSearchParams({
      days: state.days,
      limit: "50",
    });
    if (state.issueTypeId) params.set("issue_type_id", state.issueTypeId);
    if (state.cursor) params.set("cursor", state.cursor);
    const detail = await api(
      `/api/knowledge/${encodeURIComponent(documentId)}/performance?${params}`,
    );
    root.replaceChildren(
      renderDocumentPerformance(detail, {
        onFilter: async (next) => {
          Object.assign(state, next, { cursor: "" });
          await reload();
        },
        onPage: async (cursor) => {
          state.cursor = cursor || "";
          await reload();
        },
        currentDays: state.days,
        currentIssueTypeId: state.issueTypeId,
      }),
    );
  };

  showContentModal(title || documentId, root);
  await reload();
}

export function renderDocumentPerformance(data, controls = {}) {
  const container = el("div", "panel");
  container.style.marginTop = "1rem";

  const filterBar = el("div", "filter-bar");
  const period = el("select");
  period.setAttribute("aria-label", "命中期間");
  for (const [value, label] of [
    ["30", "最近 30 天"],
    ["7", "最近 7 天"],
    ["186", "最近 6 個月"],
    ["365", "最近 1 年"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    if (value === String(controls.currentDays || data.periodDays || "30")) {
      option.selected = true;
    }
    period.append(option);
  }
  const issueFilter = el("select");
  issueFilter.setAttribute("aria-label", "問題類型");
  const allIssues = el("option", "", "全部問題");
  allIssues.value = "";
  issueFilter.append(allIssues);
  for (const item of data.issueTypeDistribution || []) {
    const option = el(
      "option",
      "",
      `${item.displayName || item.issueTypeId}（${item.count}）`,
    );
    option.value = item.issueTypeId;
    if (item.issueTypeId === controls.currentIssueTypeId) option.selected = true;
    issueFilter.append(option);
  }
  if (controls.currentIssueTypeId && !Array.from(issueFilter.options).some((o) => o.value === controls.currentIssueTypeId)) {
    const option = el("option", "", controls.currentIssueTypeId);
    option.value = controls.currentIssueTypeId;
    option.selected = true;
    issueFilter.append(option);
  }
  const apply = el("button", "", "套用");
  apply.addEventListener("click", () => {
    if (typeof controls.onFilter === "function") {
      controls.onFilter({
        days: period.value,
        issueTypeId: issueFilter.value,
      });
    }
  });
  filterBar.append(period, issueFilter, apply);
  container.append(filterBar);

  container.append(
    kpiStrip([
      { label: "命中", value: String(data.hitCount ?? 0) },
      { label: "對話", value: String(data.conversationCount ?? 0) },
      { label: "正面回饋", value: String(data.positiveFeedbackCount ?? 0) },
      { label: "負面回饋", value: String(data.negativeFeedbackCount ?? 0) },
    ]),
  );

  if (data.governance) {
    const governance = data.governance;
    const govPanel = el("div", "panel");
    govPanel.append(el("h3", "", "文件治理狀態"));
    if (governance.status === "available") {
      govPanel.append(
        el(
          "p",
          "",
          `生命週期 ${labelStatus(governance.lifecycleStatus)}，格式 ${governance.formatType || "-"}，解析 ${labelStatus(governance.parseStatus)}，索引 ${labelStatus(governance.indexStatus)}`,
        ),
      );
      if (governance.portalUrl) {
        if (getCapabilities()?.knowledgeBridgeEnabled) {
          const openDoc = el("a", "button-link", "在知識文件庫開啟");
          const documentId = data.documentId || governance.documentId;
          openDoc.href = buildLocationHash("knowledge_ops", "knowledgePortal", {
            k: `/knowledge/${documentId}`,
          });
          openDoc.addEventListener("click", (event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
              return;
            }
            event.preventDefault();
            navigateTo("knowledgePortal", { k: `/knowledge/${documentId}` });
          });
          govPanel.append(openDoc);
        } else {
          const portalLink = el("a", "button-link", "在 Knowledge Portal 開啟");
          portalLink.href = governance.portalUrl;
          portalLink.target = "_blank";
          govPanel.append(portalLink);
        }
      }
    } else {
      govPanel.append(el("p", "", governance.note || `狀態：${governance.status}`));
    }
    container.append(govPanel);
  }

  const issueTable = el("table");
  issueTable.innerHTML =
    "<thead><tr><th>問題代碼</th><th>問題名稱</th><th>次數</th></tr></thead>";
  const issueBody = el("tbody");
  for (const item of data.issueTypeDistribution || []) {
    const row = el("tr");
    const issueLink = el("button", "", item.issueTypeId);
    issueLink.addEventListener("click", () => {
      if (typeof controls.onFilter === "function") {
        controls.onFilter({
          days: period.value,
          issueTypeId: item.issueTypeId,
        });
      }
    });
    const issueCell = el("td");
    issueCell.append(issueLink);
    row.append(issueCell);
    row.append(el("td", "", item.displayName || "-"));
    row.append(el("td", "", String(item.count)));
    issueBody.append(row);
  }
  issueTable.append(issueBody);
  container.append(el("h3", "ov-panel-title", "相關問題"), issueTable);

  const releaseTable = el("table");
  releaseTable.innerHTML = "<thead><tr><th>發布版本</th><th>命中</th></tr></thead>";
  const releaseBody = el("tbody");
  for (const item of data.releaseAttribution || []) {
    const row = el("tr");
    row.append(el("td", "", item.releaseId));
    row.append(el("td", "", String(item.hitCount)));
    releaseBody.append(row);
  }
  releaseTable.append(releaseBody);
  container.append(el("h3", "ov-panel-title", "版本歸因"), releaseTable);

  const recentTable = el("table");
  recentTable.innerHTML = "<thead><tr><th>時間</th><th>對話</th><th>問題</th><th>發布版本</th><th>片段</th></tr></thead>";
  const recentBody = el("tbody");
  const hitRows = data.hits || data.recentHits || [];
  for (const item of hitRows) {
    const row = el("tr");
    row.append(el("td", "", item.occurredAt));
    const conversation = el("a", "", item.conversationId || "-");
    conversation.href = "#";
    conversation.addEventListener("click", async (event) => {
      event.preventDefault();
      const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}`);
      showConversationModal(detail);
    });
    const conversationCell = el("td");
    conversationCell.append(conversation);
    row.append(conversationCell);
    row.append(el("td", "", item.issueTypeDisplayName || item.issueTypeId || "-"));
    row.append(el("td", "", item.releaseId || "-"));
    row.append(el("td", "", item.chunkId || "-"));
    recentBody.append(row);
  }
  recentTable.append(recentBody);
  container.append(el("h3", "ov-panel-title", "最近命中"), recentTable);
  if (data.nextCursor && typeof controls.onPage === "function") {
    const next = el("button", "", "下一頁命中");
    next.addEventListener("click", () => controls.onPage(data.nextCursor));
    container.append(next);
  }
  return container;
}
