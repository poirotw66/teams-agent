import { el } from "../api.js";
import { customPeriodInputs, formatLocalClock, periodSelect } from "../components/period.js";
import { drillLink } from "../app/navigation.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { formatTaipeiEventStamp } from "../app/labels.js";
import { OVERVIEW_ISSUE_NAMES } from "./overviewExport.js";
import { renderOverviewTrendChart } from "./overviewSections.js";

const STALE_EVENT_MINUTES = 15;

export function buildOverviewHome({
  data,
  metrics,
  preset,
  savedStart,
  savedEnd,
  onPresetChange,
  onApply,
  onRefresh,
  onExport,
}) {
  const page = el("div", "ov-home");
  page.append(
    buildToolbar({
      data,
      preset,
      savedStart,
      savedEnd,
      onPresetChange,
      onApply,
      onRefresh,
      onExport,
    }),
  );

  const notice = buildAttentionNotice(data, metrics);
  if (notice) page.append(notice);

  page.append(
    buildKpiRow(data, metrics),
    buildTrendPanel(data),
    buildLowerGrid(data, metrics),
  );
  return page;
}

function buildToolbar({
  data,
  preset,
  savedStart,
  savedEnd,
  onPresetChange,
  onApply,
  onRefresh,
  onExport,
}) {
  const bar = el("header", "ov-toolbar");
  const lead = el("div", "ov-toolbar-lead");
  if (!isBuShellEnabled()) {
    lead.append(
      el("h2", "ov-title", "營運總覽"),
      el("p", "ov-lead", "看本期服務量、有沒有解答，以及要不要接著處理。"),
    );
  }
  lead.append(buildStatusLine(data));

  const controls = el("div", "ov-controls");
  const select = periodSelect(preset);
  select.id = "overview-preset";
  select.setAttribute("aria-label", "統計期間");
  const customPeriod = customPeriodInputs(savedStart, savedEnd);
  customPeriod.id = "overview-custom-period";
  customPeriod.hidden = preset !== "custom";
  select.addEventListener("change", () => {
    const custom = select.value === "custom";
    customPeriod.hidden = !custom;
    apply.hidden = !custom;
    onPresetChange({ preset: select.value, customPeriod });
  });

  const apply = el("button", "button-secondary", "套用期間");
  apply.type = "button";
  apply.hidden = preset !== "custom";
  apply.addEventListener("click", () => onApply());

  const refresh = el("button", "button-primary", "重新整理");
  refresh.type = "button";
  refresh.addEventListener("click", () => onRefresh());

  const exportBtn = el("button", "button-secondary", "匯出");
  exportBtn.type = "button";
  exportBtn.addEventListener("click", () => onExport(data));

  controls.append(select, customPeriod, apply, refresh, exportBtn);
  bar.append(lead, controls);
  return bar;
}

function buildStatusLine(data) {
  const line = el("p", "ov-status");
  const tz = data.timezone || "Asia/Taipei";
  const updated = formatLocalClock(data.updatedAt, tz);
  line.append(el("span", "", `資料更新 ${updated}`));
  if (data.latestEventAt) {
    line.append(el("span", "ov-status-sep", "·"));
    line.append(el("span", "", `最近事件 ${formatTaipeiEventStamp(data.latestEventAt)}`));
  }
  if (isStale(data)) {
    line.append(el("span", "ov-status-sep", "·"));
    line.append(el("span", "ov-status-warn", "這段時間沒有新事件，數字可能尚未反映最新狀況"));
  }
  return line;
}

function buildAttentionNotice(data, metrics) {
  const failures = data.requestFailureCount ?? 0;
  const pending = metrics.hCount + metrics.noAnsCount;
  if (pending <= 0 && failures <= 0) return null;

  const note = el("div", "ov-notice");
  const copy = el("p", "");
  if (pending > 0) {
    copy.textContent = `${pending.toLocaleString()} 則對話沒有直接解答（轉接 ${metrics.hCount.toLocaleString()}、無答案 ${metrics.noAnsCount.toLocaleString()}）。`;
  } else {
    copy.textContent = `本期有 ${failures.toLocaleString()} 次系統失敗，請先確認服務狀態。`;
  }
  note.append(copy);
  note.append(pending > 0 ? drillLink("查看問題", "issues") : drillLink("查看系統健康度", "health"));
  return note;
}

function buildKpiRow(data, metrics) {
  const row = el("section", "ov-kpis");
  row.setAttribute("aria-label", "本期重點");
  const answered = metrics.kAns + metrics.fAns;
  const pending = metrics.hCount + metrics.noAnsCount;
  const cards = [
    kpi("對話", metrics.convCount.toLocaleString(), `${metrics.turnCount.toLocaleString()} 輪 · ${(data.activeUserCount ?? 0).toLocaleString()} 人`),
    kpi("已解答", answered.toLocaleString(), `${metrics.autoResolutionRate}% · 知識庫 ${metrics.kAns.toLocaleString()} / FAQ ${metrics.fAns.toLocaleString()}`),
    kpi("待處理", pending.toLocaleString(), `轉接 ${metrics.hCount.toLocaleString()} · 無答案 ${metrics.noAnsCount.toLocaleString()}`, pending > 0 ? "is-attention" : ""),
  ];
  if (data.costDisplayEnabled === false) {
    cards.push(kpi("系統失敗", (data.requestFailureCount ?? 0).toLocaleString(), "請求未能完成"));
  } else {
    cards.push(kpi("預估費用", `$${metrics.costUsd.toFixed(2)}`, `每則對話 $${metrics.avgCostPerConv}`));
  }
  row.append(...cards);
  return row;
}

function kpi(label, value, detail, extra = "") {
  const card = el("article", `ov-kpi ${extra}`.trim());
  card.append(el("p", "ov-kpi-label", label), el("p", "ov-kpi-value", value), el("p", "ov-kpi-detail", detail));
  return card;
}

function buildTrendPanel(data) {
  const panel = el("section", "ov-panel");
  const head = el("div", "ov-panel-head");
  head.append(el("h3", "ov-panel-title", "對話走勢"), el("p", "ov-panel-note", "實線為對話數，虛線為輪次。"));
  const legend = el("p", "ov-legend");
  legend.append(legendMark("對話", "solid"), legendMark("輪次", "dashed"));
  panel.append(head, renderOverviewTrendChart(data.trends, "conv"), legend);
  return panel;
}

function legendMark(label, tone) {
  const item = el("span", "ov-legend-item");
  item.append(el("span", `ov-legend-swatch is-${tone}`), el("span", "", label));
  return item;
}

function buildLowerGrid(data, metrics) {
  const grid = el("div", "ov-lower");
  grid.append(buildIssueList(data, metrics), buildDisposition(metrics));
  return grid;
}

function buildIssueList(data, metrics) {
  const panel = el("section", "ov-panel");
  const head = el("div", "ov-panel-head");
  head.append(el("h3", "ov-panel-title", "高頻問題"), drillLink("查看全部", "issues"));
  panel.append(head);

  const issues = data.topIssueTypes || [];
  if (!issues.length) {
    panel.append(el("p", "ov-empty", "這段期間還沒有問題分類。"));
    return panel;
  }

  const list = el("ol", "ov-issues");
  issues.slice(0, 5).forEach((item, index) => {
    const row = el("li", "ov-issue");
    const name = OVERVIEW_ISSUE_NAMES[item.issueTypeId] || item.issueTypeId;
    const share = metrics.totalIssues
      ? `${((item.count / metrics.totalIssues) * 100).toFixed(0)}%`
      : "";
    const meta = el("div", "ov-issue-meta");
    meta.append(el("span", "ov-rank", String(index + 1)), el("span", "ov-issue-name", name));
    const stat = el("span", "ov-issue-stat", `${Number(item.count || 0).toLocaleString()} 件${share ? ` · ${share}` : ""}`);
    row.append(meta, stat, drillLink("查看", "issues", { issueTypeId: item.issueTypeId }));
    list.append(row);
  });
  panel.append(list);
  return panel;
}

function buildDisposition(metrics) {
  const panel = el("section", "ov-panel");
  const head = el("div", "ov-panel-head");
  head.append(el("h3", "ov-panel-title", "回答結果"));
  panel.append(head);

  const stages = [
    ["知識庫直答", metrics.kAns],
    ["FAQ 直答", metrics.fAns],
    ["轉接人工", metrics.hCount],
    ["無答案", metrics.noAnsCount],
    ["需再釐清", metrics.clarCount],
  ];
  const total = stages.reduce((sum, [, count]) => sum + count, 0);
  if (total <= 0) {
    panel.append(el("p", "ov-empty", "這段期間還沒有可歸類的回答結果。"));
    return panel;
  }

  const list = el("ul", "ov-bars");
  for (const [label, count] of stages) {
    const pct = (count / total) * 100;
    const row = el("li", "ov-bar");
    const meta = el("div", "ov-bar-meta");
    meta.append(el("span", "", label), el("span", "", `${count.toLocaleString()} · ${pct.toFixed(0)}%`));
    const track = el("div", "ov-bar-track");
    const fill = el("span", "ov-bar-fill");
    fill.style.width = `${Math.min(100, Math.max(count > 0 ? 2 : 0, pct))}%`;
    track.append(fill);
    row.append(meta, track);
    list.append(row);
  }
  panel.append(list, el("p", "ov-footnote", "比例以回答結果次數計算，不是對話數。"));
  return panel;
}

function isStale(data) {
  if (data.dataFreshnessMinutes == null) return false;
  return data.dataFreshnessMinutes > STALE_EVENT_MINUTES;
}
