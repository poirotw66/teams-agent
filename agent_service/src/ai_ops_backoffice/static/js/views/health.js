import { api, el, metric } from "../api.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderHealth(targetDate = null) {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const url = targetDate ? `/api/health/summary?date=${encodeURIComponent(targetDate)}` : "/api/health/summary";
    const data = await api(url);
    const panel = el("section", "panel");
    panel.append(el("h2", "", "系統健康度"));

    // Date filter bar (REQ-024)
    const filterBar = el("div", "filter-bar");
    filterBar.style.marginBottom = "1rem";
    const dateLabel = el("label", "", "歷史日期查詢：");
    dateLabel.style.marginRight = "0.5rem";
    const dateInput = el("input");
    dateInput.type = "date";
    if (targetDate) dateInput.value = targetDate;
    const queryBtn = el("button", "button-primary", "查詢日期");
    const liveBtn = el("button", "", "即時 (最近 24 小時)");
    queryBtn.addEventListener("click", () => {
      if (dateInput.value) renderHealth(dateInput.value);
    });
    dateInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && dateInput.value) renderHealth(dateInput.value);
    });
    liveBtn.addEventListener("click", () => renderHealth(null));
    filterBar.append(dateLabel, dateInput, queryBtn, liveBtn);
    panel.append(filterBar);

    const components = data.components || [];
    const healthyCount = components.filter((c) => ["READY", "AVAILABLE", "OK"].includes(c.status?.toUpperCase())).length;
    const abnormalCount = components.length - healthyCount;

    const grid = el("div", "grid");
    grid.append(
      metric("監控元件總數", components.length),
      metric("運作正常", healthyCount),
      metric("異常／降級", abnormalCount),
      metric("遙測視窗", targetDate ? `歷史日期：${targetDate}` : `${data.telemetryWindowHours || 24} 小時`),
    );
    panel.append(grid);

    if (data.isHistorical && data.historicalNotice) {
      panel.append(
        el("div", "warning", data.historicalNotice),
      );
    }
    if (data.monitoringScope?.teamsAdapter?.note) {
      const scopeNote = el(
        "div",
        "metric-label",
        [
          "監控範圍：",
          data.monitoringScope.teamsAdapter.note,
          data.monitoringScope.retrievalIndex?.note
            ? ` ${data.monitoringScope.retrievalIndex.note}`
            : "",
        ].join(""),
      );
      scopeNote.style.marginBottom = "0.75rem";
      panel.append(scopeNote);
    }
    if (data.simulatedAnomalies) {
      panel.append(
        el("div", "warning", "目前為模擬異常模式，部分元件狀態為測試用途。"),
      );
    }
    if (data.monitoringLinks?.cloudMonitoring) {
      const links = el("div", "filter-bar");
      const monitoringLink = el("a", "button-link", "Cloud Monitoring");
      monitoringLink.href = data.monitoringLinks.cloudMonitoring;
      monitoringLink.target = "_blank";
      const loggingLink = el("a", "button-link", "Cloud Logging");
      loggingLink.href = data.monitoringLinks.cloudLogging;
      loggingLink.target = "_blank";
      links.append(monitoringLink, loggingLink);
      panel.append(links);
    }
    const table = el("table");
    const windowCol = data.isHistorical ? "當日請求數" : (targetDate ? "Requests" : "24h Requests");
    const statusHeaders = data.isHistorical
      ? "<th>歷史狀態</th><th>即時探測</th>"
      : "<th>Status</th>";
    table.innerHTML = [
      `<thead><tr><th>Component</th>${statusHeaders}<th>${windowCol}</th>`,
      "<th>Availability</th><th>Error</th><th>Timeout</th>",
      "<th>P50 ms</th><th>P95 ms</th><th>Note</th></tr></thead>",
    ].join("");
    const body = el("tbody");
    for (const item of components) {
      const row = el("tr");
      row.append(el("td", "", item.id));

      const statusCell = el("td");
      const isOk = ["READY", "AVAILABLE", "OK"].includes(item.status?.toUpperCase());
      const statusChip = el("span", "badge", item.status || "UNKNOWN");
      if (!isOk) {
        statusChip.style.background = item.status === "NO_DATA" ? "var(--warning-soft, #fff3cd)" : "var(--danger-soft)";
        statusChip.style.borderColor = item.status === "NO_DATA" ? "var(--warning-border, #ffeeba)" : "var(--danger-border)";
        statusChip.style.color = item.status === "NO_DATA" ? "var(--warning, #856404)" : "var(--danger)";
      }
      statusCell.append(statusChip);
      row.append(statusCell);

      if (data.isHistorical) {
        const liveCell = el("td");
        const liveOk = ["READY", "AVAILABLE", "OK"].includes(item.liveProbeStatus?.toUpperCase());
        const liveChip = el("span", "badge", `${item.liveProbeStatus || "UNKNOWN"} (即時)`);
        if (!liveOk) {
          liveChip.style.background = "var(--danger-soft)";
          liveChip.style.color = "var(--danger)";
        }
        liveCell.append(liveChip);
        row.append(liveCell);
      }

      row.append(
        el(
          "td",
          "",
          item.telemetryStatus === "AVAILABLE" ? String(item.requestCount) : "NO DATA",
        ),
      );
      for (const value of [item.availabilityRate, item.errorRate, item.timeoutRate]) {
        row.append(el("td", "", value == null ? "-" : `${(value * 100).toFixed(1)}%`));
      }
      row.append(el("td", "", item.p50LatencyMs == null ? "-" : String(item.p50LatencyMs)));
      row.append(el("td", "", item.p95LatencyMs == null ? "-" : String(item.p95LatencyMs)));
      row.append(el("td", "", item.note || item.url || ""));
      body.append(row);
    }
    table.append(body);
    const tableScroll = el("div", "table-responsive");
    tableScroll.append(table);
    panel.append(tableScroll);

    if ((data.recentAnomalies || []).length) {
      const anomalyTable = el("table");
      anomalyTable.innerHTML = "<thead><tr><th>時間</th><th>Component</th><th>Status</th><th>Error Type</th><th>Correlation</th></tr></thead>";
      const anomalyBody = el("tbody");
      for (const item of data.recentAnomalies) {
        const row = el("tr");
        row.append(el("td", "", item.occurredAt));
        row.append(el("td", "", item.component));
        row.append(el("td", "", item.status));
        row.append(el("td", "", item.errorType));
        row.append(el("td", "", item.correlationId || "-"));
        anomalyBody.append(row);
      }
      anomalyTable.append(anomalyBody);
      const anomalyScroll = el("div", "table-responsive");
      anomalyScroll.append(anomalyTable);
      panel.append(el("h3", "", "最近異常"), anomalyScroll);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", error.message));
  }
}

export const healthPage = createPageController({
  enter: async () => renderHealth(),
  update: async () => renderHealth(),
  leave: async () => {},
});
