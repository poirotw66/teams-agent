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
