import { el, metric } from "../api.js";
import { badge } from "./badges.js";

const SERIES_COLORS = ["#2563eb", "#d97706", "#059669", "#7c3aed", "#dc2626", "#0891b2"];

const ROUTE_BADGE = {
  FAQ: "success",
  KNOWLEDGE: "accent",
  TICKET: "neutral",
  HANDOFF: "warning",
  CLARIFICATION: "warning",
  FAILED: "danger",
};

export function formatPercent(rate, digits = 1) {
  const value = Number(rate);
  if (!Number.isFinite(value)) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatCount(value) {
  const n = Number(value) || 0;
  return n.toLocaleString("zh-TW");
}

export function pageHeader(title, subtitle, trailing = null) {
  const header = el("div", "analytics-page-header");
  const text = el("div", "analytics-page-header-text");
  text.append(el("h2", "", title));
  if (subtitle) text.append(el("p", "metric-label", subtitle));
  header.append(text);
  if (trailing) header.append(trailing);
  return header;
}

export function kpiStrip(items = []) {
  const grid = el("div", "metrics analytics-kpi-strip");
  for (const item of items) {
    grid.append(metric(item.label, item.value));
  }
  return grid;
}

export function filterChipBar(chips = [], onClearAll = null) {
  const active = chips.filter((chip) => chip.value);
  if (!active.length) return el("div");
  const bar = el("div", "analytics-chip-bar");
  bar.append(el("span", "metric-label", "目前篩選"));
  for (const chip of active) {
    const node = el("span", "analytics-chip", `${chip.label}：${chip.value}`);
    if (typeof chip.onClear === "function") {
      const clear = el("button", "analytics-chip-clear", "×");
      clear.type = "button";
      clear.setAttribute("aria-label", `清除 ${chip.label}`);
      clear.addEventListener("click", chip.onClear);
      node.append(clear);
    }
    bar.append(node);
  }
  if (typeof onClearAll === "function") {
    const clearAll = el("button", "button-link", "清除全部");
    clearAll.type = "button";
    clearAll.addEventListener("click", onClearAll);
    bar.append(clearAll);
  }
  return bar;
}

export function shareBarCell(share) {
  const cell = el("td", "analytics-share-cell");
  const pct = Math.max(0, Math.min(100, Number(share || 0) * 100));
  const wrap = el("div", "analytics-share");
  wrap.append(el("span", "analytics-share-label", formatPercent(share)));
  const track = el("div", "analytics-share-track");
  const fill = el("div", "analytics-share-fill");
  fill.style.width = `${pct}%`;
  track.append(fill);
  wrap.append(track);
  cell.append(wrap);
  return cell;
}

export function routeBadge(route) {
  const key = String(route || "UNKNOWN").toUpperCase();
  return badge(key, ROUTE_BADGE[key] || "neutral");
}

export function distributionBars(items, { labelKey = "label", valueKey = "count", max = null } = {}) {
  const section = el("div", "analytics-dist");
  if (!(items || []).length) {
    section.append(el("p", "empty", "此條件尚無分布資料。"));
    return section;
  }
  const peak = max || Math.max(...items.map((item) => Number(item[valueKey]) || 0), 1);
  const total = items.reduce((sum, item) => sum + (Number(item[valueKey]) || 0), 0) || 1;
  for (const item of items) {
    const count = Number(item[valueKey]) || 0;
    const row = el("div", "analytics-dist-row");
    const label = el("div", "analytics-dist-label");
    if (item.route) label.append(routeBadge(item.route));
    else label.append(el("span", "", item[labelKey] || "-"));
    const track = el("div", "analytics-dist-track");
    const fill = el("div", "analytics-dist-fill");
    fill.style.width = `${(count / peak) * 100}%`;
    if (item.color) fill.style.background = item.color;
    track.append(fill);
    const meta = el("div", "analytics-dist-meta");
    meta.append(
      el("strong", "", formatCount(count)),
      el("span", "metric-label", formatPercent(count / total)),
    );
    row.append(label, track, meta);
    section.append(row);
  }
  return section;
}

/** Multi-series daily issue trend chart (top N issues). */
export function renderIssueTrendChart(trends, { topN = 5, names = {} } = {}) {
  const container = el("div", "trend-svg-container analytics-trend-chart");
  if (!(trends || []).length) {
    container.append(el("div", "empty", "此期間尚無趨勢資料。"));
    return container;
  }

  const totals = new Map();
  for (const day of trends) {
    for (const item of day.counts || []) {
      totals.set(item.issueTypeId, (totals.get(item.issueTypeId) || 0) + (item.count || 0));
    }
  }
  const topIds = [...totals.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, topN)
    .map(([id]) => id);
  if (!topIds.length) {
    container.append(el("div", "empty", "此期間尚無趨勢資料。"));
    return container;
  }

  const dates = trends.map((day) => day.date);
  const series = topIds.map((id, index) => ({
    id,
    label: names[id] || id,
    color: SERIES_COLORS[index % SERIES_COLORS.length],
    values: trends.map((day) => {
      const hit = (day.counts || []).find((item) => item.issueTypeId === id);
      return hit?.count || 0;
    }),
  }));

  const allValues = series.flatMap((s) => s.values);
  const maxY = Math.max(...allValues, 1);
  const W = 820;
  const H = 230;
  const padL = 48;
  const padR = 18;
  const padT = 18;
  const padB = 36;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const N = dates.length;
  const getX = (idx) => (N === 1 ? padL + plotW / 2 : padL + (idx * plotW) / (N - 1));
  const getY = (v) => padT + plotH - (v / maxY) * plotH;

  let grid = "";
  for (let step = 0; step <= 4; step += 1) {
    const y = padT + (plotH * step) / 4;
    const tick = Math.round(maxY * (1 - step / 4));
    grid += `
      <line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="var(--border)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="${padL - 8}" y="${y + 3}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="var(--mono)">${tick}</text>
    `;
  }

  let xLabels = "";
  dates.forEach((date, i) => {
    if (N > 14 && i % 2 !== 0 && i !== N - 1) return;
    const short = String(date || "").slice(5);
    xLabels += `<text x="${getX(i)}" y="${H - 12}" text-anchor="middle" font-size="10" fill="var(--muted)" font-family="var(--mono)">${short}</text>`;
  });

  let paths = "";
  series.forEach((s) => {
    if (N === 1) {
      paths += `<circle cx="${getX(0)}" cy="${getY(s.values[0])}" r="5" fill="${s.color}" stroke="#fff" stroke-width="2"/>`;
      return;
    }
    const pts = s.values.map((v, i) => `${getX(i)},${getY(v)}`).join(" ");
    paths += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>`;
    s.values.forEach((v, i) => {
      paths += `<circle cx="${getX(i)}" cy="${getY(v)}" r="3" fill="${s.color}" stroke="#fff" stroke-width="1.5"/>`;
    });
  });

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "trend-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Issue 按日趨勢圖");
  svg.innerHTML = `${grid}${xLabels}${paths}`;
  container.append(svg);

  const legend = el("div", "trend-legend-row analytics-trend-legend");
  for (const s of series) {
    const item = el("div", "trend-legend-item");
    const mark = el("span", "trend-legend-mark");
    mark.style.background = s.color;
    item.append(mark, el("span", "", s.label));
    legend.append(item);
  }
  container.append(legend);
  return container;
}

export function emptyState(title, hint) {
  const box = el("div", "analytics-empty");
  box.append(el("p", "empty", title));
  if (hint) box.append(el("p", "metric-label", hint));
  return box;
}

export function actionGroup(...nodes) {
  const wrap = el("div", "analytics-actions");
  for (const node of nodes) {
    if (!node) continue;
    wrap.append(node);
  }
  return wrap;
}

export function actionCell(...nodes) {
  const cell = el("td", "");
  cell.append(actionGroup(...nodes));
  return cell;
}
