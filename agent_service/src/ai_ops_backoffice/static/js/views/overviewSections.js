import { el } from "../api.js";
import {
  periodSelect,
  intervalSelect,
  formatLocalClock,
  customPeriodInputs,
} from "../components/period.js";
import { badge } from "../components/badges.js";
import {
  activeWorkspaceId,
  buildLocationHash,
  drillLink,
  navigateTo,
  workspaceForView,
} from "../app/navigation.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";

export const OVERVIEW_ISSUE_NAMES = {
  "vpn.connection_failed": "VPN 連線異常與斷線",
  "other.unclassified": "一般未分類問題",
  "password.account_locked": "密碼鎖定與重設需求",
  "other.greeting": "問候與引導交談",
  "email.outlook_sync": "Outlook 信件同步失敗",
  "hardware.laptop_battery": "筆記型電腦電池與電源問題",
  "software.teams_login": "Teams 登入與授權問題",
};

export const OVERVIEW_METRIC_TRANSLATIONS = {
  conversation_count: "總對話數 (Conversation Count)",
  turn_count: "總對話輪次 (Turn Count)",
  active_user_count: "活躍使用者數 (Active Users)",
  issue_occurrence_count: "問題提取次數 (Issue Occurrences)",
  knowledge_hit_rate: "知識庫命中解答率 (Knowledge Hit Rate)",
  faq_hit_rate: "FAQ 直接命中率 (FAQ Hit Rate)",
  no_answer_count: "無答案兜底次數 (No Answer Count)",
  clarification_count: "需澄清確認次數 (Clarification Count)",
  handoff_count: "真人客服轉接數 (Handoff Count)",
  handoff_rate: "真人客服轉接率 (Handoff Rate)",
  ticket_count: "自動建立派工單數 (Ticket Count)",
  positive_feedback_count: "正面好評數 (Positive Feedback)",
  negative_feedback_count: "負面差評數 (Negative Feedback)",
  resolved_feedback_count: "已標記解決回饋數 (Resolved Feedback)",
  total_tokens: "總模型權杖消耗 (Total Tokens)",
  estimated_cost_usd: "預估模型成本 USD (Estimated Cost)",
  cost_coverage: "成本可追蹤覆蓋率 (Cost Tracking Coverage)",
  error_rate: "系統調用錯誤率 (System Error Rate)",
  p50_latency_ms: "中位數回應延遲 P50 (ms)",
  p95_latency_ms: "95 百分位回應延遲 P95 (ms)",
};

export function exportOverviewCsv(data) {
  const rows = [];
  rows.push(["=== 平台營運總覽摘要報告 ==="]);
  rows.push(["統計期間", data.periodPreset || "7d", `開始時間: ${data.periodStart || "-"}`, `結束時間: ${data.periodEnd || "-"}`]);
  rows.push(["資料更新時間", data.updatedAt || "-", `時區: ${data.timezone || "Asia/Taipei"}`]);
  rows.push([]);
  rows.push(["指標名稱", "數值", "計算備註"]);
  rows.push(["總處理對話數 (Conversations)", data.conversationCount ?? 0, "期間至少有一次進線交談的獨立對話"]);
  rows.push(["總對話輪次 (Turns)", data.turnCount ?? 0, "使用者進線發言總輪次"]);
  rows.push(["活躍使用者數 (Active Users)", data.activeUserCount ?? 0, "期間內提出請求之獨立使用者數"]);
  rows.push(["問題提取總數 (Issues)", data.issueOccurrenceCount ?? 0, "系統自對話中成功識別提取之 IT 問題次數"]);
  rows.push(["知識庫解答數", data.knowledgeAnswerCount ?? 0, "成功自企業知識庫命中解答"]);
  rows.push(["FAQ 解答數", data.faqAnswerCount ?? 0, "成功自 FAQ 知識點直答"]);
  rows.push(["需澄清問答數", data.clarificationCount ?? 0, "意圖不明需反問澄清"]);
  rows.push(["無解答兜底數", data.noAnswerCount ?? 0, "無法確認解答或超出知識庫範圍"]);
  rows.push(["真人客服轉接數", data.handoffCount ?? 0, `轉單率: ${((data.handoffRate ?? 0) * 100).toFixed(1)}%`]);
  rows.push(["建立派工單數", data.ticketCount ?? 0, "自動派發至工單系統"]);
  rows.push(["正面滿意回饋", data.positiveFeedbackCount ?? 0, "使用者評為滿意/有幫助"]);
  rows.push(["負面待改善回饋", data.negativeFeedbackCount ?? 0, "使用者反饋無幫助/待改善"]);
  rows.push(["總權杖消耗 (Tokens)", data.totalTokens ?? 0, "LLM Prompt 與 Completion 合計 Tokens"]);
  rows.push(["預估費用 (USD)", `$${(data.estimatedCostUsd ?? 0).toFixed(4)}`, `成本完整追蹤率: ${((data.costCoverage ?? 0) * 100).toFixed(1)}%`]);
  rows.push(["系統錯誤率", `${((data.errorRate ?? 0) * 100).toFixed(3)}%`, "包含超時與異常失敗"]);
  rows.push(["延遲 P50 / P95 (ms)", `${data.p50LatencyMs ?? "-"} ms / ${data.p95LatencyMs ?? "-"} ms`, "系統回應延遲指標"]);
  rows.push([]);
  rows.push(["=== 每日營運趨勢 (Daily Trends) ==="]);
  rows.push(["日期", "對話數", "輪次數", "活躍使用者", "問題量", "總 Tokens", "估算成本 USD"]);
  for (const t of data.trends || []) {
    rows.push([t.period, t.conversationCount ?? 0, t.turnCount ?? 0, t.activeUserCount ?? 0, t.issueOccurrenceCount ?? 0, t.totalTokens ?? 0, t.estimatedCostUsd ?? 0]);
  }
  rows.push([]);
  rows.push(["=== Top 問題分類排行 ==="]);
  rows.push(["排名", "問題代碼", "中文名稱", "發生次數", "佔比"]);
  const totalIssues = data.issueOccurrenceCount || 1;
  (data.topIssueTypes || []).forEach((item, idx) => {
    const friendlyName = OVERVIEW_ISSUE_NAMES[item.issueTypeId] || item.issueTypeId;
    rows.push([idx + 1, item.issueTypeId, friendlyName, item.count, `${((item.count / totalIssues) * 100).toFixed(1)}%`]);
  });

  const csvText = "\uFEFF" + rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `teams-agent-operations-summary-${data.periodPreset || "period"}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function renderOverviewTrendChart(trends, activeTab) {
  const container = el("div", "trend-svg-container");
  if (!trends || trends.length === 0) {
    container.append(el("div", "empty", "目前選定期間內尚無趨勢數據"));
    return container;
  }

  let s1Label = "對話數";
  let s1Color = "#2563eb";
  let s1Unit = "次";
  let s2Label = "輪次數";
  let s2Color = "#059669";
  let s2Unit = "次";
  let getS1 = (d) => d.conversationCount ?? 0;
  let getS2 = (d) => d.turnCount ?? 0;
  let formatVal = (v, isS2) => Number(v).toLocaleString();

  if (activeTab === "issues") {
    s1Label = "問題提取量";
    s1Color = "#d97706";
    s1Unit = "件";
    s2Label = "活躍使用者";
    s2Color = "#2563eb";
    s2Unit = "人";
    getS1 = (d) => d.issueOccurrenceCount ?? 0;
    getS2 = (d) => d.activeUserCount ?? 0;
  } else if (activeTab === "cost") {
    s1Label = "Token 消耗";
    s1Color = "#7c3aed";
    s1Unit = "tokens";
    s2Label = "估算成本";
    s2Color = "#059669";
    s2Unit = "USD";
    getS1 = (d) => d.totalTokens ?? 0;
    getS2 = (d) => d.estimatedCostUsd ?? 0;
    formatVal = (v, isS2) => (isS2 ? `$${Number(v).toFixed(4)}` : Number(v).toLocaleString());
  }

  const s1Values = trends.map(getS1);
  const s2Values = trends.map(getS2);
  const maxS1 = Math.max(...s1Values, 1);
  const maxS2 = Math.max(...s2Values, activeTab === "cost" ? 0.0001 : 1);

  const W = 800;
  const H = 220;
  const padL = 55;
  const padR = 40;
  const padT = 20;
  const padB = 35;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const N = trends.length;

  const getX = (idx) => (N === 1 ? padL + plotW / 2 : padL + (idx * plotW) / (N - 1));
  const getY1 = (v) => padT + plotH - (v / maxS1) * plotH;
  const getY2 = (v) => padT + plotH - (v / maxS2) * plotH;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "trend-svg");

  const defs = `
    <defs>
      <linearGradient id="trendGradS1" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${s1Color}" stop-opacity="0.22"/>
        <stop offset="100%" stop-color="${s1Color}" stop-opacity="0.0"/>
      </linearGradient>
    </defs>
  `;

  let gridLines = "";
  for (let step = 0; step <= 4; step++) {
    const yVal = padT + (plotH * step) / 4;
    const s1Tick = Math.round(maxS1 * (1 - step / 4));
    gridLines += `
      <line x1="${padL}" y1="${yVal}" x2="${W - padR}" y2="${yVal}" stroke="var(--border)" stroke-width="1" stroke-dasharray="3 3"/>
      <text x="${padL - 8}" y="${yVal + 3}" text-anchor="end" font-size="10" fill="var(--muted)" font-family="var(--mono)">${s1Tick.toLocaleString()}</text>
    `;
  }

  let xLabels = "";
  trends.forEach((t, i) => {
    if (N > 10 && i % 2 !== 0 && i !== N - 1) return;
    const x = getX(i);
    const shortDate = (t.period || "").length > 5 ? t.period.slice(5) : t.period;
    xLabels += `<text x="${x}" y="${H - 12}" text-anchor="middle" font-size="10" fill="var(--muted)" font-family="var(--mono)">${shortDate}</text>`;
  });

  let s1AreaPath = "";
  let s1LinePath = "";
  let s2LinePath = "";
  let s1Circles = "";
  let s2Circles = "";

  if (N === 1) {
    const cx = getX(0);
    const cy1 = getY1(s1Values[0]);
    const cy2 = getY2(s2Values[0]);
    s1Circles = `<circle cx="${cx}" cy="${cy1}" r="6" fill="${s1Color}" stroke="#ffffff" stroke-width="2.5"/>`;
    s2Circles = `<circle cx="${cx}" cy="${cy2}" r="5" fill="${s2Color}" stroke="#ffffff" stroke-width="2"/>`;
  } else {
    const pts1 = trends.map((_, i) => `${getX(i)},${getY1(s1Values[i])}`);
    const pts2 = trends.map((_, i) => `${getX(i)},${getY2(s2Values[i])}`);
    s1LinePath = `<polyline points="${pts1.join(" ")}" fill="none" stroke="${s1Color}" stroke-width="2.75" stroke-linecap="round" stroke-linejoin="round"/>`;
    s2LinePath = `<polyline points="${pts2.join(" ")}" fill="none" stroke="${s2Color}" stroke-width="2" stroke-dasharray="4 3" stroke-linecap="round" stroke-linejoin="round"/>`;
    s1AreaPath = `<polygon points="${padL},${padT + plotH} ${pts1.join(" ")} ${padL + plotW},${padT + plotH}" fill="url(#trendGradS1)"/>`;
    trends.forEach((_, i) => {
      s1Circles += `<circle cx="${getX(i)}" cy="${getY1(s1Values[i])}" r="3.5" fill="${s1Color}" stroke="#ffffff" stroke-width="1.5"/>`;
      s2Circles += `<circle cx="${getX(i)}" cy="${getY2(s2Values[i])}" r="3" fill="${s2Color}" stroke="#ffffff" stroke-width="1.5"/>`;
    });
  }

  const guideLine = `<line id="trendGuideLine" x1="0" y1="${padT}" x2="0" y2="${padT + plotH}" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="3 3" opacity="0"/>`;
  const activeDot1 = `<circle id="trendActiveDot1" cx="0" cy="0" r="5.5" fill="${s1Color}" stroke="#ffffff" stroke-width="2.5" opacity="0"/>`;
  const activeDot2 = `<circle id="trendActiveDot2" cx="0" cy="0" r="4.5" fill="${s2Color}" stroke="#ffffff" stroke-width="2" opacity="0"/>`;

  svg.innerHTML = `
    ${defs}
    ${gridLines}
    ${xLabels}
    ${s1AreaPath}
    ${s1LinePath}
    ${s2LinePath}
    ${guideLine}
    ${s1Circles}
    ${s2Circles}
    ${activeDot1}
    ${activeDot2}
    <rect x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="transparent" style="cursor: crosshair;" id="trendInteractiveOverlay"/>
  `;

  const tooltip = el("div", "trend-tooltip");
  tooltip.style.opacity = "0";

  container.append(svg, tooltip);

  const overlay = svg.querySelector("#trendInteractiveOverlay");
  const guide = svg.querySelector("#trendGuideLine");
  const dot1 = svg.querySelector("#trendActiveDot1");
  const dot2 = svg.querySelector("#trendActiveDot2");

  if (overlay) {
    overlay.addEventListener("pointermove", (evt) => {
      const rect = svg.getBoundingClientRect();
      const clientX = evt.clientX - rect.left;
      const svgX = (clientX / rect.width) * W;
      let nearestIdx = 0;
      let nearestDist = Infinity;
      trends.forEach((_, i) => {
        const x = getX(i);
        const dist = Math.abs(x - svgX);
        if (dist < nearestDist) {
          nearestDist = dist;
          nearestIdx = i;
        }
      });

      const d = trends[nearestIdx];
      const ptX = getX(nearestIdx);
      const ptY1 = getY1(s1Values[nearestIdx]);
      const ptY2 = getY2(s2Values[nearestIdx]);

      guide.setAttribute("x1", ptX);
      guide.setAttribute("x2", ptX);
      guide.setAttribute("opacity", "0.75");

      dot1.setAttribute("cx", ptX);
      dot1.setAttribute("cy", ptY1);
      dot1.setAttribute("opacity", "1");

      dot2.setAttribute("cx", ptX);
      dot2.setAttribute("cy", ptY2);
      dot2.setAttribute("opacity", "1");

      const s1Display = formatVal(s1Values[nearestIdx], false);
      const s2Display = formatVal(s2Values[nearestIdx], true);

      tooltip.innerHTML = `
        <div style="font-weight: 800; font-family: var(--mono); margin-bottom: 4px; color: #cbd5e1;">${d.period}</div>
        <div style="display: flex; align-items: center; gap: 6px; color: #ffffff;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${s1Color};"></span>
          <span>${s1Label}:</span> <strong style="font-family: var(--mono);">${s1Display} ${s1Unit}</strong>
        </div>
        <div style="display: flex; align-items: center; gap: 6px; color: #ffffff;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${s2Color};"></span>
          <span>${s2Label}:</span> <strong style="font-family: var(--mono);">${s2Display} ${s2Unit}</strong>
        </div>
      `;

      const tipX = (ptX / W) * rect.width;
      const tipY = Math.min((ptY1 / H) * rect.height, rect.height - 70);
      tooltip.style.transform = `translate(${tipX > rect.width - 160 ? tipX - 170 : tipX + 15}px, ${Math.max(10, tipY - 20)}px)`;
      tooltip.style.opacity = "1";
    });

    overlay.addEventListener("pointerleave", () => {
      guide.setAttribute("opacity", "0");
      dot1.setAttribute("opacity", "0");
      dot2.setAttribute("opacity", "0");
      tooltip.style.opacity = "0";
    });
  }

  return container;
}


export function deriveOverviewMetrics(data) {
  const availVal = ((1 - (data.errorRate ?? 0)) * 100).toFixed(2);
  const p50 = data.p50LatencyMs != null ? `${data.p50LatencyMs}ms` : "-";
  const p95 = data.p95LatencyMs != null ? `${data.p95LatencyMs}ms` : "-";
  const totalAnswered = (data.knowledgeAnswerCount ?? 0) + (data.faqAnswerCount ?? 0);
  const convCount = data.conversationCount ?? 0;
  const autoResolutionRate = convCount ? ((totalAnswered / convCount) * 100).toFixed(1) : "0.0";
  const totalFeedback = (data.positiveFeedbackCount ?? 0) + (data.negativeFeedbackCount ?? 0);
  const csatPercent = totalFeedback > 0 ? ((data.positiveFeedbackCount / totalFeedback) * 100).toFixed(1) : "100.0";
  const costCov = ((data.costCoverage ?? 1) * 100).toFixed(1);
  const turnCount = data.turnCount ?? 0;
  const avgTurns = convCount > 0 ? (turnCount / convCount).toFixed(1) : "-";
  const kAns = data.knowledgeAnswerCount ?? 0;
  const fAns = data.faqAnswerCount ?? 0;
  const clarCount = data.clarificationCount ?? 0;
  const hCount = data.handoffCount ?? 0;
  const hRate = ((data.handoffRate ?? 0) * 100).toFixed(1);
  const noAnsCount = data.noAnswerCount ?? 0;
  const costUsd = data.estimatedCostUsd ?? 0;
  const totalToks = data.totalTokens ?? 0;
  const avgCostPerConv = convCount > 0 ? (costUsd / convCount).toFixed(4) : "0.0000";
  const totalIssues = data.issueOccurrenceCount || convCount || 1;
  return {
    availVal,
    p50,
    p95,
    totalAnswered,
    convCount,
    autoResolutionRate,
    totalFeedback,
    csatPercent,
    costCov,
    turnCount,
    avgTurns,
    kAns,
    fAns,
    clarCount,
    hCount,
    hRate,
    noAnsCount,
    costUsd,
    totalToks,
    avgCostPerConv,
    totalIssues,
  };
}

export function buildOverviewHeader({
  data,
  preset,
  savedStart,
  savedEnd,
  interval,
  model,
  issueTypeId,
  onPresetChange,
  onIntervalChange,
  onApply,
  onRefresh,
  onExport,
}) {
  const header = el("header", "overview-header-bar");
  const titleGroup = el("div", "overview-title-group");

  const badgeRow = el("div", "overview-badge-row");
  const statusPill = el("span", "overview-status-pill");
  statusPill.innerHTML = '<span class="live-dot pulse"></span> 平台即時營運中控';

  const tz = data.timezone || "Asia/Taipei";
  const updateTimeStr = formatLocalClock(data.updatedAt, tz);
  const freshnessChip = el("span", "overview-freshness-chip", `摘要更新：${updateTimeStr}（時區：${tz}）`);
  freshnessChip.title = "本次營運摘要 API 產生時間（非事件管線最後寫入時間）";
  badgeRow.append(statusPill, freshnessChip);

  if (data.dataFreshnessMinutes != null) {
    const idleMinutes = data.dataFreshnessMinutes;
    const latestEventHint = data.latestEventAt
      ? `期間內最近一筆營運事件時間：${formatLocalClock(data.latestEventAt, tz)}（${tz}）。此指標反映「多久沒有新事件」，不代表批次管線故障。`
      : "此指標反映期間內多久沒有新營運事件，不代表批次管線故障。";
    if (idleMinutes > 15) {
      const idleChip = el(
        "span",
        "overview-warning-chip",
        `⚠️ 最近事件：${idleMinutes} 分鐘前`,
      );
      idleChip.title = latestEventHint;
      badgeRow.append(idleChip);
    } else {
      const idleChip = el(
        "span",
        "overview-freshness-chip",
        `🟢 最近事件：${idleMinutes} 分鐘前`,
      );
      idleChip.title = latestEventHint;
      badgeRow.append(idleChip);
    }
  }
  titleGroup.append(badgeRow);
  if (!isBuShellEnabled()) {
    titleGroup.append(
      el("h2", "overview-main-heading", "平台營運總覽"),
      el("p", "overview-sub-heading", "即時監控企業知識庫問答、對話輪次、真人轉單分流與 AI Token 預算消耗"),
    );
  }

  const actionsGroup = el("div", "overview-actions-group");
  const periodControl = el("div", "overview-period-control");
  const select = periodSelect(preset);
  select.id = "overview-preset";

  const customPeriod = customPeriodInputs(savedStart, savedEnd);
  customPeriod.id = "overview-custom-period";
  customPeriod.hidden = preset !== "custom";

  const intervalControl = intervalSelect(interval);
  intervalControl.id = "overview-interval";

  const modelInput = el("input");
  modelInput.type = "text";
  modelInput.id = "overview-model";
  modelInput.placeholder = "Model（選填）";
  modelInput.value = model;
  modelInput.setAttribute("aria-label", "模型篩選");

  const issueInput = el("input");
  issueInput.type = "text";
  issueInput.id = "overview-issue-type";
  issueInput.placeholder = "Issue Type（選填）";
  issueInput.value = issueTypeId;
  issueInput.setAttribute("aria-label", "Issue 篩選");

  select.addEventListener("change", () => {
    onPresetChange({
      preset: select.value,
      customPeriod,
      modelInput,
      issueInput,
      intervalControl,
    });
  });

  intervalControl.addEventListener("change", () => {
    onIntervalChange({ modelInput, issueInput, intervalControl });
  });

  const apply = el("button", "btn", "套用");
  apply.type = "button";
  apply.addEventListener("click", () => {
    onApply({ modelInput, issueInput, intervalControl });
  });

  const refresh = el("button", "btn button-primary", "🔄 重新整理");
  refresh.type = "button";
  refresh.title = "即刻向後端取得最新營運數據（繞過快取）";
  refresh.addEventListener("click", () => {
    onRefresh({ modelInput, issueInput, intervalControl });
  });

  const exportBtn = el("button", "btn", "📥 匯出 CSV");
  exportBtn.type = "button";
  exportBtn.title = "下載本期營運摘要與趨勢報表";
  exportBtn.addEventListener("click", () => onExport(data));

  periodControl.append(
    select,
    customPeriod,
    intervalControl,
    modelInput,
    issueInput,
    apply,
    refresh,
    exportBtn,
  );
  actionsGroup.append(periodControl);
  header.append(titleGroup, actionsGroup);
  return header;
}

export function buildFreshnessWarning(data) {
  if (data.dataFreshnessMinutes == null || data.dataFreshnessMinutes <= 15) {
    return null;
  }
  const warnBox = el(
    "div",
    "warning",
    `期間內最近一筆營運事件已是 ${data.dataFreshnessMinutes} 分鐘前；若這段時間本來就沒有新對話，屬正常閒置，不代表查詢管線故障。`,
  );
  warnBox.style.margin = "0";
  return warnBox;
}

export function buildSlaHealthStrip(data, metrics) {
  const {
    availVal,
    p50,
    p95,
    autoResolutionRate,
    totalAnswered,
    csatPercent,
    costCov,
  } = metrics;
  const slaStrip = el("div", "sla-health-strip");

  const slaItem1 = el("div", "sla-strip-item");
  slaItem1.innerHTML = `
      <div class="sla-strip-dot emerald"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">系統可用性 (SLA)</span>
        <span class="sla-strip-val">${availVal}% <span class="badge badge-success">正常</span></span>
      </div>
    `;

  const slaItem2 = el("div", "sla-strip-item");
  slaItem2.innerHTML = `
      <div class="sla-strip-dot sapphire"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">延遲 P50 / P95</span>
        <span class="sla-strip-val">${p50} / ${p95} <span class="badge badge-accent">達標</span></span>
      </div>
    `;

  const slaItem3 = el("div", "sla-strip-item");
  slaItem3.innerHTML = `
      <div class="sla-strip-dot emerald"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">自動解答涵蓋率</span>
        <span class="sla-strip-val">${autoResolutionRate}% <span class="badge badge-success">${totalAnswered.toLocaleString()} 件</span></span>
      </div>
    `;

  const slaItem4 = el("div", "sla-strip-item");
  slaItem4.innerHTML = `
      <div class="sla-strip-dot sapphire"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">滿意度 (CSAT)</span>
        <span class="sla-strip-val">${csatPercent}% <span class="badge badge-success">${data.positiveFeedbackCount ?? 0} 正評</span></span>
      </div>
    `;

  const slaItem5 = el("div", "sla-strip-item");
  slaItem5.innerHTML = `
      <div class="sla-strip-dot emerald"></div>
      <div class="sla-strip-info">
        <span class="sla-strip-label">成本追蹤涵蓋</span>
        <span class="sla-strip-val">${costCov}% <span class="badge badge-neutral">可審核</span></span>
      </div>
    `;

  slaStrip.append(slaItem1, slaItem2, slaItem3, slaItem4, slaItem5);
  return slaStrip;
}

export function buildHeroKpiGrid(data, metrics) {
  const {
    convCount,
    turnCount,
    avgTurns,
    autoResolutionRate,
    kAns,
    fAns,
    clarCount,
    hCount,
    hRate,
    noAnsCount,
    costUsd,
    totalToks,
    avgCostPerConv,
    costCov,
  } = metrics;

  const heroGrid = el("div", "hero-kpi-grid");

  const cardTraffic = el("div", "hero-kpi-card card-traffic");
  cardTraffic.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">對話服務量能</span>
        <span class="hero-icon-badge">💬</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${convCount.toLocaleString()}</div>
        <div class="hero-stat-caption">總處理對話數 (Conversations)</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">總對話輪次</span>
          <span class="hero-subval">${turnCount.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">平均輪次</span>
          <span class="hero-subval">${avgTurns} 輪/次</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">活躍使用者</span>
          <span class="hero-subval">${(data.activeUserCount ?? 0).toLocaleString()} 人</span>
        </div>
      </div>
    `;

  const cardResolution = el("div", "hero-kpi-card card-resolution");
  cardResolution.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">AI 自動化解答</span>
        <span class="badge badge-success">${autoResolutionRate}% 涵蓋</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${(kAns + fAns).toLocaleString()}</div>
        <div class="hero-stat-caption">自主成功解答 (Knowledge & FAQ)</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">知識庫直答</span>
          <span class="hero-subval">${kAns.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">FAQ 命中</span>
          <span class="hero-subval">${fAns.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">需澄清問答</span>
          <span class="hero-subval">${clarCount.toLocaleString()}</span>
        </div>
      </div>
    `;

  const cardHandoff = el("div", "hero-kpi-card card-handoff");
  cardHandoff.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">真人轉單與異常</span>
        <span class="badge badge-warning">${hRate}% 轉接率</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${hCount.toLocaleString()}</div>
        <div class="hero-stat-caption">轉接真人客服處理 (Handoffs)</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">建立派工單</span>
          <span class="hero-subval">${(data.ticketCount ?? 0).toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">無答案兜底</span>
          <span class="hero-subval">${noAnsCount.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">系統失敗次數</span>
          <span class="hero-subval">${(data.requestFailureCount ?? 0).toLocaleString()}</span>
        </div>
      </div>
    `;

  const cardCost = el("div", "hero-kpi-card card-cost");
  cardCost.innerHTML = `
      <div class="hero-card-header">
        <span class="hero-card-tag">模型耗用與成本</span>
        <span class="badge badge-accent">${costCov}% 覆蓋率</span>
      </div>
      <div class="hero-card-body">
        <div class="hero-main-stat">${data.costDisplayEnabled === false ? "已關閉" : `$${costUsd.toFixed(4)}`}</div>
        <div class="hero-stat-caption">預估模型總費用 USD</div>
      </div>
      <div class="hero-card-subgrid">
        <div class="hero-subitem">
          <span class="hero-sublabel">Total Tokens</span>
          <span class="hero-subval">${totalToks.toLocaleString()}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">平均對話成本</span>
          <span class="hero-subval">$${avgCostPerConv}</span>
        </div>
        <div class="hero-subitem">
          <span class="hero-sublabel">錯誤異常率</span>
          <span class="hero-subval">${((data.errorRate ?? 0) * 100).toFixed(2)}%</span>
        </div>
      </div>
    `;

  heroGrid.append(cardTraffic, cardResolution, cardHandoff, cardCost);
  return heroGrid;
}

export function buildTrendChartPanel({
  data,
  interval,
  trendTab,
  onTrendTabChange,
}) {
  const trendPanel = el("div", "trend-chart-panel");
  const trendHeader = el("div", "trend-panel-header");
  const trendTitleCol = el("div", "trend-title-col");
  const intervalLabel =
    interval === "WEEK" ? "每週" :
    interval === "MONTH" ? "每月" : "每日";
  trendTitleCol.append(
    el("h3", "trend-title", "營運趨勢走勢分析"),
    el("p", "trend-desc", `追蹤${intervalLabel}對話進線量、問題發生頻率與 Token / 成本消耗曲線`),
  );

  const tabGroup = el("div", "trend-tab-group");
  const tabConv = el("button", `trend-tab-btn ${trendTab === "conv" ? "active" : ""}`, "對話與輪次");
  const tabIssues = el("button", `trend-tab-btn ${trendTab === "issues" ? "active" : ""}`, "問題發生量");
  const tabCost = el("button", `trend-tab-btn ${trendTab === "cost" ? "active" : ""}`, "Token 與成本");
  tabGroup.append(tabConv, tabIssues, tabCost);
  trendHeader.append(trendTitleCol, tabGroup);

  const calloutBanner = el("div", "trend-stats-callout");
  function updateTrendCallouts(tabKey) {
    const trends = data.trends || [];
    let totalVal = 0;
    let peakVal = 0;
    let peakPeriod = "-";
    let unit = "次";

    if (tabKey === "conv") {
      unit = "次";
      totalVal = trends.reduce((acc, cur) => acc + (cur.conversationCount || 0), 0);
      trends.forEach((t) => {
        if ((t.conversationCount || 0) >= peakVal) {
          peakVal = t.conversationCount || 0;
          peakPeriod = t.period;
        }
      });
    } else if (tabKey === "issues") {
      unit = "件";
      totalVal = trends.reduce((acc, cur) => acc + (cur.issueOccurrenceCount || 0), 0);
      trends.forEach((t) => {
        if ((t.issueOccurrenceCount || 0) >= peakVal) {
          peakVal = t.issueOccurrenceCount || 0;
          peakPeriod = t.period;
        }
      });
    } else if (tabKey === "cost") {
      unit = "tokens";
      totalVal = trends.reduce((acc, cur) => acc + (cur.totalTokens || 0), 0);
      trends.forEach((t) => {
        if ((t.totalTokens || 0) >= peakVal) {
          peakVal = t.totalTokens || 0;
          peakPeriod = t.period;
        }
      });
    }

    const avgVal = trends.length > 0 ? (totalVal / trends.length).toFixed(1) : "0";
    calloutBanner.innerHTML = `
        <div class="trend-callout-item">
          <span class="trend-callout-label">統計區間總計:</span>
          <span class="trend-callout-val">${totalVal.toLocaleString()} ${unit}</span>
        </div>
        <div class="trend-callout-item">
          <span class="trend-callout-label">日最高峰值:</span>
          <span class="trend-callout-val">${peakVal.toLocaleString()} ${unit} (${peakPeriod})</span>
        </div>
        <div class="trend-callout-item">
          <span class="trend-callout-label">每日平均量:</span>
          <span class="trend-callout-val">${Number(avgVal).toLocaleString()} ${unit}/日</span>
        </div>
      `;
  }

  updateTrendCallouts(trendTab);

  let chartSlot = renderOverviewTrendChart(data.trends, trendTab);

  function switchTrendTab(nextTab) {
    onTrendTabChange(nextTab);
    tabConv.className = `trend-tab-btn ${nextTab === "conv" ? "active" : ""}`;
    tabIssues.className = `trend-tab-btn ${nextTab === "issues" ? "active" : ""}`;
    tabCost.className = `trend-tab-btn ${nextTab === "cost" ? "active" : ""}`;
    updateTrendCallouts(nextTab);
    const newChart = renderOverviewTrendChart(data.trends, nextTab);
    chartSlot.replaceWith(newChart);
    chartSlot = newChart;
  }

  tabConv.addEventListener("click", () => switchTrendTab("conv"));
  tabIssues.addEventListener("click", () => switchTrendTab("issues"));
  tabCost.addEventListener("click", () => switchTrendTab("cost"));

  const legendRow = el("div", "trend-legend-row");
  legendRow.innerHTML = `
      <div class="trend-legend-item">
        <span class="trend-legend-mark" style="background: #2563eb;"></span>
        <span>主指標 (實線)</span>
      </div>
      <div class="trend-legend-item">
        <span class="trend-legend-mark" style="background: #059669; border-top: 1px dashed #059669;"></span>
        <span>次指標 (虛線)</span>
      </div>
      <div class="trend-legend-item" style="margin-left: auto; color: var(--subtle); font-size: 0.725rem;">
        * 可將滑鼠移至圖表上方檢視每日詳細數值
      </div>
    `;

  trendPanel.append(trendHeader, calloutBanner, chartSlot, legendRow);
  return trendPanel;
}

export function buildSplitAnalyticsGrid(data, metrics) {
  const { convCount, kAns, fAns, clarCount, hCount, noAnsCount, totalIssues } = metrics;
  const splitGrid = el("div", "split-analytics-grid");

  const funnelCard = el("div", "analytics-card");
  const funnelHeader = el("div", "analytics-card-header");
  const funnelTitleGroup = el("div");
  funnelTitleGroup.append(
    el("h3", "analytics-card-title", "服務處置分流 (Resolution Breakdown)"),
    el("p", "analytics-card-subtitle", "依各類回覆處置結果評估 AI 解答成效與轉單比例"),
  );
  funnelHeader.append(funnelTitleGroup, badge(`共 ${(data.issueOccurrenceCount || convCount).toLocaleString()} 次處理`, "neutral"));

  const funnelBars = el("div", "funnel-bars-container");
  const funnelStages = [
    {
      title: "企業知識庫直答 (Knowledge)",
      count: kAns,
      color: "emerald",
    },
    {
      title: "真人客服轉接 (Live Agent)",
      count: hCount,
      color: "sapphire",
    },
    {
      title: "無確認答案 (No Knowledge)",
      count: noAnsCount,
      color: "rose",
    },
    {
      title: "需反問澄清 (Clarification)",
      count: clarCount,
      color: "amber",
    },
    {
      title: "FAQ 命中直答 (FAQ Hit)",
      count: fAns,
      color: "purple",
    },
  ];

  for (const stage of funnelStages) {
    const stageRow = el("div", "funnel-stage-row");
    const pct = ((stage.count / totalIssues) * 100).toFixed(1);
    stageRow.innerHTML = `
        <div class="funnel-stage-meta">
          <span class="funnel-stage-title">${stage.title}</span>
          <span class="funnel-stage-stat">${stage.count.toLocaleString()} 次 (${pct}%)</span>
        </div>
        <div class="funnel-bar-track">
          <div class="funnel-bar-fill ${stage.color}" style="width: ${Math.min(100, Math.max(stage.count > 0 ? 3 : 0, Number(pct)))}%;"></div>
        </div>
      `;
    funnelBars.append(stageRow);
  }
  funnelCard.append(funnelHeader, funnelBars);

  const issuesCard = el("div", "analytics-card");
  const issuesHeader = el("div", "analytics-card-header");
  const issuesTitleGroup = el("div");
  issuesTitleGroup.append(
    el("h3", "analytics-card-title", "Top 問題類型排行 (Top Issues)"),
    el("p", "analytics-card-subtitle", "進線高頻問題統計，點選可直接進入鑽取診斷"),
  );
  const issuesAllLink = drillLink("查看全部 Issue →", "issues");
  issuesHeader.append(issuesTitleGroup, issuesAllLink);

  const issuesList = el("div", "issues-list-container");
  const topIssues = data.topIssueTypes || [];
  if (topIssues.length === 0) {
    issuesList.append(el("div", "empty", "目前無問題分類紀錄"));
  } else {
    topIssues.slice(0, 5).forEach((item, idx) => {
      const itemRow = el("div", "issue-rank-item");
      const rankClass = idx === 0 ? "top1" : idx === 1 ? "top2" : idx === 2 ? "top3" : "";
      const friendlyName = OVERVIEW_ISSUE_NAMES[item.issueTypeId] || item.issueTypeId;
      const sharePct = ((item.count / totalIssues) * 100).toFixed(1);

      const head = el("div", "issue-rank-head");
      const titleWrap = el("div", "issue-rank-title-group");
      titleWrap.append(el("span", `issue-rank-badge ${rankClass}`, `#${idx + 1}`), el("span", "issue-rank-name", friendlyName));
      const valSpan = el("span", "issue-rank-val", `${item.count.toLocaleString()} 件 (${sharePct}%)`);
      head.append(titleWrap, valSpan);

      const barWrap = el("div", "issue-rank-bar-wrap");
      barWrap.innerHTML = `
          <div class="issue-rank-track">
            <div class="issue-rank-fill" style="width: ${Math.min(100, Math.max(4, Number(sharePct)))}%;"></div>
          </div>
        `;

      const actions = el("div", "issue-rank-actions");
      actions.append(
        drillLink("🔍 查看 Issue 分析", "issues", { issueTypeId: item.issueTypeId }),
        drillLink("🔀 路由規則", "routes", { issueTypeId: item.issueTypeId }),
      );

      itemRow.append(head, barWrap, actions);
      issuesList.append(itemRow);
    });
  }
  issuesCard.append(issuesHeader, issuesList);

  splitGrid.append(funnelCard, issuesCard);
  return splitGrid;
}

export function buildQuickNavPanel() {
  const quickNavPanel = el("div", "quick-nav-panel");
  quickNavPanel.append(el("h3", "quick-nav-title", "⚡ 常用營運功能導航"));
  const quickNavGrid = el("div", "quick-nav-grid");

  const quickActions = [
    {
      icon: "🔍",
      title: "Issue 深入分析",
      desc: "檢視各類問題發生趨勢、對話樣本與解答分佈",
      view: "issues",
      filters: {},
    },
    {
      icon: "🔀",
      title: "路由來源管理",
      desc: "檢查與配置各業務分類的 AI / 人工轉派分流策略",
      view: "routes",
      filters: {},
    },
    {
      icon: "⭐",
      title: "品質與負評案件",
      desc: "追蹤使用者差評、澄清未果與回饋已解決標記",
      view: "quality",
      filters: { rating: "DOWN" },
    },
    {
      icon: "💰",
      title: "成本與費用分析",
      desc: "監控各模型 Token 消耗、預估花費與預算告警",
      view: "costs",
      filters: {},
    },
    {
      icon: "📚",
      title: "知識文件庫",
      desc: "檢視企業知識文件覆蓋度、命中解答率與待補缺口",
      view: "knowledgePortal",
      filters: {},
    },
  ];

  for (const qa of quickActions) {
    const card = el("a", "quick-nav-card");
    card.href = buildLocationHash(workspaceForView(qa.view) || activeWorkspaceId(), qa.view, qa.filters);
    card.addEventListener("click", (evt) => {
      if (evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey || evt.button !== 0) return;
      evt.preventDefault();
      navigateTo(qa.view, qa.filters);
    });
    card.innerHTML = `
        <div class="quick-nav-head">
          <div class="quick-nav-icon-title">
            <span>${qa.icon}</span>
            <span>${qa.title}</span>
          </div>
          <span class="quick-nav-arrow">&rarr;</span>
        </div>
        <p class="quick-nav-desc">${qa.desc}</p>
      `;
    quickNavGrid.append(card);
  }
  quickNavPanel.append(quickNavGrid);
  return quickNavPanel;
}

export function buildMetricsGlossary(definitions) {
  if (!definitions || !Object.keys(definitions).length) {
    return null;
  }
  const details = el("details", "overview-glossary");
  const summary = el("summary", "glossary-summary");
  summary.innerHTML = `
        <span class="glossary-summary-title">📖 指標計算定義與公式說明 (點擊展開 ${Object.keys(definitions).length} 項指標)</span>
        <span class="glossary-toggle-icon">▾</span>
      `;
  details.append(summary);

  const content = el("div", "glossary-content");
  const table = el("table");
  table.innerHTML = "<thead><tr><th>指標代碼</th><th>中文指標名稱</th><th>計算公式與說明</th></tr></thead>";
  const tbody = el("tbody");
  for (const [key, value] of Object.entries(definitions)) {
    const row = el("tr");
    const codeTd = el("td", "");
    codeTd.append(el("code", "", key));
    row.append(codeTd);
    row.append(el("td", "", OVERVIEW_METRIC_TRANSLATIONS[key] || key));
    row.append(el("td", "", String(value)));
    tbody.append(row);
  }
  table.append(tbody);
  const tableScroll = el("div", "table-responsive");
  tableScroll.append(table);
  content.append(tableScroll);
  details.append(content);
  return details;
}
