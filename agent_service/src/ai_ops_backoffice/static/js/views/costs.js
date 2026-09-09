import { api, el, metric } from "../api.js";
import { createPeriodControls, periodParams } from "../components/period.js";
import { createExportButton } from "../services/export.js";
import { createPageController } from "../app/lifecycle.js";
import { presentAnalyticsPage } from "../app/analyticsChrome.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { loadNavFilters } from "../app/navigation.js";

function stillOnCosts() {
  const view = loadNavFilters().view;
  return !view || view === "costs";
}

export async function renderCosts(state = { preset: "30d" }) {
  const app = document.getElementById("app");
  const period = {
    preset: state.preset || "30d",
    start: state.start || "",
    end: state.end || "",
  };
  const modelFilter = String(state.model || "").trim();
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const params = periodParams(period);
    if (modelFilter) params.set("model", modelFilter);
    const data = await api(`/api/costs/summary?${params.toString()}`);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "成本分析"));

    const modelInput = el("input");
    modelInput.type = "text";
    modelInput.id = "costs-model-filter";
    modelInput.placeholder = "Model（選填，例如 gemini-3.8-flash）";
    modelInput.value = modelFilter;
    modelInput.setAttribute("aria-label", "模型篩選");

    const reloadWithFilters = (nextPeriod) => {
      renderCosts({
        ...(nextPeriod || period),
        model: modelInput.value.trim(),
      });
    };

    panel.append(createPeriodControls(period, reloadWithFilters));

    const filterBar = el("div", "filter-bar");
    const applyModel = el("button", "", "套用模型篩選");
    applyModel.type = "button";
    applyModel.addEventListener("click", () => reloadWithFilters(period));
    modelInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        reloadWithFilters(period);
      }
    });
    const exportFilters = () => ({
      ...(modelInput.value.trim() ? { model: modelInput.value.trim() } : {}),
    });
    filterBar.append(
      el("label", "", "模型"),
      modelInput,
      applyModel,
      createExportButton("costs_summary", () => ({
        preset: period.preset,
        start: period.start,
        end: period.end,
      }), exportFilters),
    );
    panel.append(filterBar);
    if (modelFilter) {
      panel.append(el("p", "metric-label", `目前篩選模型：${modelFilter}`));
    }

    const grid = el("div", "grid");
    grid.append(
      metric("預估總成本 USD", (data.totalEstimatedCostUsd ?? 0).toFixed(4)),
      metric("預估總成本 TWD", data.totalEstimatedCostTwd != null ? Number(data.totalEstimatedCostTwd).toFixed(2) : "-"),
      metric("零成本事件", data.zeroCostEventCount ?? 0),
      metric("未知成本事件", data.missingCostEventCount ?? 0),
      metric("Input Tokens", (data.inputTokens ?? 0).toLocaleString()),
      metric("Output Tokens", (data.outputTokens ?? 0).toLocaleString()),
      metric("總 Tokens", ((data.inputTokens ?? 0) + (data.outputTokens ?? 0)).toLocaleString()),
    );
    panel.append(grid);

    const metaRow = el("div", "filter-bar");
    if (data.usdTwdExchangeRate) metaRow.append(el("span", "metric-label", `匯率：${data.usdTwdExchangeRate} TWD/USD`));
    if (data.embeddingTokens != null || data.toolContextTokens != null) {
      metaRow.append(el("span", "metric-label", `Embedding：${(data.embeddingTokens ?? 0).toLocaleString()} tokens｜Tool Context：${(data.toolContextTokens ?? 0).toLocaleString()} tokens`));
    }
    metaRow.append(el("span", "metric-label", `定價版本：${data.pricingVersion || "v1"}`));
    panel.append(metaRow);

    const modelTable = el("table");
    modelTable.innerHTML =
      "<thead><tr><th>Model</th><th>成本狀態</th><th>Input Tokens</th><th>Output Tokens</th><th>總 Tokens</th><th>Events</th><th>Estimated USD</th><th>Input $/1M</th><th>Output $/1M</th></tr></thead>";
    const modelBody = el("tbody");
    for (const item of data.byModel || []) {
      const row = el("tr");
      const totalTokens = item.totalTokens ?? ((item.inputTokens ?? 0) + (item.outputTokens ?? 0));
      row.append(el("td", "", item.model || "unknown"));

      const statusCell = el("td");
      let statusLabel = "預估成本";
      let chipStyle = "";
      if (item.costStatus === "ZERO_COST" || (item.estimatedCostUsd === 0 && totalTokens === 0)) {
        statusLabel = "零成本";
        chipStyle = "background: #e2e3e5; color: #383d41;";
      } else if (item.costStatus === "UNKNOWN" || item.estimatedCostUsd == null) {
        statusLabel = "未知成本";
        chipStyle = "background: #fff3cd; color: #856404;";
      } else {
        chipStyle = "background: #d4edda; color: #155724;";
      }
      const chip = el("span", "badge", statusLabel);
      if (chipStyle) chip.style.cssText = chipStyle;
      statusCell.append(chip);
      row.append(statusCell);

      row.append(el("td", "", Number(item.inputTokens ?? 0).toLocaleString()));
      row.append(el("td", "", Number(item.outputTokens ?? 0).toLocaleString()));
      row.append(el("td", "", Number(totalTokens).toLocaleString()));
      row.append(el("td", "", String(item.eventCount ?? 0)));
      row.append(el("td", "", item.estimatedCostUsd != null ? String(item.estimatedCostUsd) : "-"));
      row.append(el("td", "", item.inputUsdPer1MTokens != null ? String(item.inputUsdPer1MTokens) : "-"));
      row.append(el("td", "", item.outputUsdPer1MTokens != null ? String(item.outputUsdPer1MTokens) : "-"));
      modelBody.append(row);
    }
    if (!(data.byModel || []).length) {
      const emptyRow = el("tr");
      emptyRow.append(el("td", "", "期間內沒有模型用量資料"));
      emptyRow.firstChild.colSpan = 9;
      modelBody.append(emptyRow);
    }
    modelTable.append(modelBody);
    const modelScroll = el("div", "table-responsive");
    modelScroll.append(modelTable);
    panel.append(el("h3", "", "依 Model（Token 與成本）"), modelScroll);

    const ratesTable = el("table");
    ratesTable.innerHTML =
      "<thead><tr><th>Model</th><th>Input USD / 1M tokens</th><th>Output USD / 1M tokens</th><th>Pricing Version</th></tr></thead>";
    const ratesBody = el("tbody");
    for (const item of data.modelRates || []) {
      const row = el("tr");
      row.append(el("td", "", item.model || "-"));
      row.append(el("td", "", String(item.inputUsdPer1MTokens ?? "-")));
      row.append(el("td", "", String(item.outputUsdPer1MTokens ?? "-")));
      row.append(el("td", "", item.pricingVersion || "-"));
      ratesBody.append(row);
    }
    ratesTable.append(ratesBody);
    const ratesScroll = el("div", "table-responsive");
    ratesScroll.append(ratesTable);
    panel.append(
      el("h3", "", "使用模型費率表"),
      el("p", "metric-label", "目前系統估算成本所採用的模型單價（USD / 每百萬 tokens）"),
      ratesScroll,
    );

    // Historical rates and changelog / audit log (REQ-002)
    try {
      const historyData = await api("/api/costs/rates/history");
      if ((historyData.audits || []).length || (historyData.history || []).length) {
        const auditTable = el("table");
        auditTable.innerHTML =
          "<thead><tr><th>異動項目</th><th>異動前</th><th>異動後</th><th>操作者</th><th>生效時間</th><th>變更原因</th><th>紀錄時間</th></tr></thead>";
        const auditBody = el("tbody");
        for (const record of historyData.audits || []) {
          const row = el("tr");
          row.append(el("td", "", record.target_id || record.change_type));
          const fmtBefore = record.before
            ? (record.before.exchangeRate ? `${record.before.exchangeRate} TWD/USD` : `In: $${record.before.inputUsdPer1MTokens} / Out: $${record.before.outputUsdPer1MTokens}`)
            : "-";
          const fmtAfter = record.after
            ? (record.after.exchangeRate ? `${record.after.exchangeRate} TWD/USD` : `In: $${record.after.inputUsdPer1MTokens} / Out: $${record.after.outputUsdPer1MTokens}`)
            : "-";
          row.append(el("td", "", fmtBefore));
          row.append(el("td", "", fmtAfter));
          row.append(el("td", "", record.actor_id || "-"));
          row.append(el("td", "", record.effective_at ? new Date(record.effective_at).toLocaleString() : "-"));
          row.append(el("td", "", record.reason || "-"));
          row.append(el("td", "", record.occurred_at ? new Date(record.occurred_at).toLocaleString() : "-"));
          auditBody.append(row);
        }
        if (!(historyData.audits || []).length) {
          const emptyRow = el("tr");
          emptyRow.append(el("td", "", "目前尚無費率異動紀錄"));
          emptyRow.firstChild.colSpan = 7;
          auditBody.append(emptyRow);
        }
        auditTable.append(auditBody);
        const auditScroll = el("div", "table-responsive");
        auditScroll.append(auditTable);
        panel.append(
          el("h3", "", "費率與匯率異動紀錄（Audit Log）"),
          el("p", "metric-label", "包含費率／匯率變更之前後值、操作者、生效時間與稽核軌跡"),
          auditScroll,
        );
      }
    } catch (_err) {
      // Historical rate view is non-fatal if capability is missing
    }

    const table = el("table");
    table.innerHTML = "<thead><tr><th>Date</th><th>Estimated USD</th></tr></thead>";
    const body = el("tbody");
    for (const item of data.byDay || []) {
      const row = el("tr");
      row.append(el("td", "", item.date));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      body.append(row);
    }
    table.append(body);
    const dateScroll = el("div", "table-responsive");
    dateScroll.append(table);
    panel.append(el("h3", "", "依日期"), dateScroll);

    const routeTable = el("table");
    routeTable.innerHTML = "<thead><tr><th>Route</th><th>Estimated USD</th></tr></thead>";
    const routeBody = el("tbody");
    for (const item of data.byRoute || []) {
      const row = el("tr");
      row.append(el("td", "", item.route));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      routeBody.append(row);
    }
    routeTable.append(routeBody);
    const routeScroll = el("div", "table-responsive");
    routeScroll.append(routeTable);
    panel.append(el("h3", "", "依 Route"), routeScroll);

    const issueTable = el("table");
    issueTable.innerHTML =
      "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Estimated USD</th></tr></thead>";
    const issueBody = el("tbody");
    for (const item of data.byIssueType || []) {
      const row = el("tr");
      row.append(el("td", "", item.issueTypeId));
      row.append(el("td", "", item.displayName || "-"));
      row.append(el("td", "", String(item.estimatedCostUsd)));
      issueBody.append(row);
    }
    issueTable.append(issueBody);
    const issueScroll = el("div", "table-responsive");
    issueScroll.append(issueTable);
    panel.append(el("h3", "", "依 Issue Type"), issueScroll);

    for (const [heading, items, key] of [
      ["依 Provider", data.byProvider, "provider"],
      ["依 Component", data.byComponent, "component"],
      ["依 Knowledge Backend", data.byBackend, "backend"],
    ]) {
      const dimensionTable = el("table");
      dimensionTable.innerHTML = `<thead><tr><th>${heading.replace("依 ", "")}</th><th>Events</th><th>Estimated USD</th></tr></thead>`;
      const dimensionBody = el("tbody");
      for (const item of items || []) {
        const row = el("tr");
        row.append(el("td", "", item[key] || "unknown"));
        row.append(el("td", "", String(item.eventCount ?? 0)));
        row.append(el("td", "", String(item.estimatedCostUsd ?? "-")));
        dimensionBody.append(row);
      }
      dimensionTable.append(dimensionBody);
      const dimScroll = el("div", "table-responsive");
      dimScroll.append(dimensionTable);
      panel.append(el("h3", "", heading), dimScroll);
    }
    if (!stillOnCosts()) {
      return;
    }
    if (isBuShellEnabled()) {
      presentAnalyticsPage(
        "costs",
        "成本與用量",
        "用量與趨勢獨立檢視，不與品質指標混算。",
        panel,
      );
    } else {
      app.replaceChildren(panel);
    }
  } catch (error) {
    if (!stillOnCosts()) {
      return;
    }
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

export const costsPage = createPageController({
  enter: async (context = {}) => renderCosts(context.state || { preset: "30d" }),
  update: async (context = {}) => renderCosts(context.state || { preset: "30d" }),
  leave: async () => {},
});
