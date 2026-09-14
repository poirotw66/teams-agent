import { el } from "../api.js";

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
