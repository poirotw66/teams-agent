/**
 * Shared Traditional Chinese labels for BU-facing status / route codes.
 * Keep technical codes available via title/tooltip where helpful.
 */

const ROUTE_LABELS = {
  FAQ: "固定答案 FAQ",
  KNOWLEDGE: "知識檢索",
  TICKET: "開立工單",
  HANDOFF: "轉人工",
  CLARIFICATION: "澄清追問",
  DIRECT: "直接回覆",
  ESCALATE: "升級處理",
  FAILED: "失敗",
  NOT_IT: "非 IT 問題",
  TOOL_TASK: "工具任務",
  SUMMARY_REVIEW: "摘要覆核",
};

const STATUS_LABELS = {
  NEW: "新建",
  TRIAGED: "已分派",
  IN_PROGRESS: "修正中",
  WAITING_REVIEW: "待審核",
  OBSERVING: "觀察中",
  RESOLVED: "已結案",
  WONT_FIX: "不處理",
  DUPLICATE: "重複",
  DRAFT: "草稿",
  IN_REVIEW: "審核中",
  CHANGES_REQUESTED: "需修改",
  APPROVED: "已核准",
  REJECTED: "已退回",
  RETIRED: "已退役",
  ACTIVE: "啟用中",
  DISABLED: "已停用",
  PUBLISHED: "已發布",
  ARCHIVED: "已封存",
  MEDIUM: "中",
  HIGH: "高",
  LOW: "低",
  CRITICAL: "緊急",
  NORMAL: "一般",
  OPEN: "待處理",
  CLOSED: "已關閉",
};

const BEHAVIOR_LABELS = {
  ANSWER_WITH_CITATION: "引用回答",
  CLARIFY: "需求澄清",
  REFUSE: "安全拒答",
  HANDOFF: "轉真人",
  TOOL_TASK: "工具任務",
};

const SOURCE_HEALTH_LABELS = {
  VALID: "正常",
  NEEDS_REVIEW: "來源更新待複核",
  SOURCE_UNAVAILABLE: "來源已失效",
};

export function labelRoute(code) {
  const key = String(code || "").trim();
  return ROUTE_LABELS[key] || key || "—";
}

export function labelStatus(code) {
  const key = String(code || "").trim();
  return STATUS_LABELS[key] || key || "—";
}

export function labelBehavior(code) {
  const key = String(code || "").trim();
  return BEHAVIOR_LABELS[key] || key || "—";
}

export function labelSourceHealth(code) {
  const key = String(code || "").trim();
  return SOURCE_HEALTH_LABELS[key] || key || "—";
}

export function formatTaipeiDateTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-TW", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return String(iso);
  }
}

/** Compact calendar+clock for freshness chips, e.g. 昨天 17:01 / 今天 09:12. */
export function formatTaipeiEventStamp(iso, now = new Date()) {
  if (!iso) return "—";
  try {
    const then = new Date(iso);
    const tz = "Asia/Taipei";
    const dayFmt = { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" };
    const timeFmt = { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false };
    const thenDay = then.toLocaleDateString("en-CA", dayFmt);
    const todayDay = now.toLocaleDateString("en-CA", dayFmt);
    const yesterday = new Date(now.getTime() - 86400000);
    const yDay = yesterday.toLocaleDateString("en-CA", dayFmt);
    const clock = then.toLocaleTimeString("zh-TW", timeFmt);
    if (thenDay === todayDay) return `今天 ${clock}`;
    if (thenDay === yDay) return `昨天 ${clock}`;
    return formatTaipeiDateTime(iso);
  } catch {
    return String(iso);
  }
}

export function formatTaipeiRelative(iso, now = new Date()) {
  if (!iso) return "—";
  try {
    const then = new Date(iso);
    const diffMs = now.getTime() - then.getTime();
    if (!Number.isFinite(diffMs)) return formatTaipeiDateTime(iso);
    const minutes = Math.floor(diffMs / 60000);
    if (minutes < 1) return "剛剛";
    if (minutes < 60) return `${minutes} 分鐘前`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} 小時前（${formatTaipeiEventStamp(iso, now)}）`;
    return formatTaipeiEventStamp(iso, now);
  } catch {
    return String(iso);
  }
}

/** Escape then lightly format assistant text for safe HTML display. */
export function formatAssistantHtml(text) {
  const raw = String(text || "");
  const escaped = raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return escaped
    .replace(/^######\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/^#####\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/^####\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/^###\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/^##\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/^#\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/\[S(\d+)\]/g, '<span class="bu-cite">來源 $1</span>')
    .replace(/\n/g, "<br>");
}

/** Map transport/auth errors to Traditional Chinese copy for BU operators. */
export function formatUserFacingError(error) {
  const raw = String(error?.message || error || "").trim();
  if (!raw) {
    return "資料讀取失敗。這不是「查無資料」。";
  }
  if (raw === "FORBIDDEN") {
    return "目前身分沒有權限查看此內容。若需要存取，請改用有權限的角色或向管理員申請。";
  }
  if (raw === "UNAUTHORIZED") {
    return "登入已失效，請重新設定身分後再試。";
  }
  if (/Failed to fetch|NetworkError|Load failed|network/i.test(raw)) {
    return "無法連線到資料服務。請確認網路或後端是否可用，然後按「重試」。這不是「查無資料」。";
  }
  if (/^HTTP \d+/.test(raw)) {
    return `資料讀取失敗（${raw}）。這不是「查無資料」。`;
  }
  return `資料讀取失敗：${raw}。這不是「查無資料」。`;
}
