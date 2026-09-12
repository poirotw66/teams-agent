import { el } from "../api.js";
import { drillLink } from "../app/navigation.js";

const ATTRIBUTION_LABELS = {
  faqIds: "FAQ ID",
  faqKeys: "FAQ Key",
  documentIds: "文件 (Doc)",
  sourcePaths: "來源路徑 (Source)",
  versionIds: "版本 (Version)",
  releaseIds: "發佈 (Release)",
};

export function attributionText(attribution = {}) {
  const parts = [];
  for (const [key, label] of Object.entries(ATTRIBUTION_LABELS)) {
    const values = (attribution[key] || []).map((item) => `${item.id} (${item.count})`);
    if (values.length) parts.push(`${label}: ${values.join(", ")}`);
  }
  return parts.join(" | ") || "-";
}

/** Render attribution with drill links for FAQ / Document IDs. */
export function attributionCell(attribution = {}, extras = {}) {
  const cell = el("td", "");
  const parts = [];
  const issueTypeId = extras.issueTypeId || "";

  for (const [key, label] of Object.entries(ATTRIBUTION_LABELS)) {
    const values = attribution[key] || [];
    if (!values.length) continue;
    const group = el("div", "metric-label");
    group.append(document.createTextNode(`${label}: `));
    values.forEach((item, index) => {
      if (index > 0) group.append(document.createTextNode(", "));
      if (key === "documentIds") {
        group.append(drillLink(`${item.id} (${item.count})`, "knowledge", { documentId: item.id }));
      } else if (key === "sourcePaths") {
        group.append(drillLink(`${item.id} (${item.count})`, "knowledge", { query: item.id }));
      } else if (key === "faqIds") {
        group.append(drillLink(`${item.id} (${item.count})`, "faq", { faqId: item.id }));
      } else if (key === "faqKeys") {
        group.append(drillLink(`${item.id} (${item.count})`, "faq", { query: item.id }));
      } else {
        group.append(document.createTextNode(`${item.id} (${item.count})`));
      }
    });
    parts.push(group);
  }

  if (!parts.length) {
    cell.append(document.createTextNode("-"));
    return cell;
  }
  for (const part of parts) cell.append(part);
  if (issueTypeId) {
    const actions = el("div", "filter-bar");
    actions.append(
      drillLink("對話", "conversations", { issueTypeId }),
      drillLink("回饋", "quality", { issueTypeId }),
    );
    cell.append(actions);
  }
  return cell;
}

export const STATUS_LABELS_ZH = {
  ACTIVE: "正式生效",
  PUBLISHED: "已發布",
  REALTIME: "即時更新",
  RESOLVED: "已結案",
  NEW: "新進待辦",
  TRIAGED: "已分派",
  IN_PROGRESS: "處理中",
  WAITING_REVIEW: "待審核",
  OBSERVING: "觀察中",
  WONT_FIX: "不修復",
  DUPLICATE: "重複案件",
  DRAFT: "草稿",
  ARCHIVED: "已封存",
  DEPRECATED: "已停用",
  REJECTED: "已駁回",
  APPROVED: "已核准",
  CANDIDATE: "候選版",
  HEALTHY: "健康正常",
  DEGRADED: "服務降級",
  CRITICAL: "嚴重異常",
  QUALITY_CASE_CREATED: "建立改善案件",
  QUALITY_CASE_UPDATED: "更新改善案件",
  QUALITY_CASE_TRANSITIONED: "變更案件狀態",
  QUALITY_CASE_DELETED: "刪除改善案件",
  TRANSITION_STATUS: "變更案件狀態",
  ASSOCIATE_CONTENT: "關聯內容",
  CREATE_DOCUMENT_DRAFT: "建立文件草稿",
  CREATE_FAQ_DRAFT: "建立 FAQ 草稿",
  REFRESH_OBSERVATION: "刷新觀察指標",
};

export function badge(text, variant = "neutral") {
  return el("span", `badge badge-${variant}`, String(text ?? ""));
}

export function statusBadge(status) {
  const raw = String(status || "").trim();
  const s = raw.toUpperCase();
  let variant = "neutral";
  if (["ACTIVE", "APPROVED", "RESOLVED", "OK", "HEALTHY", "ENABLED", "SUCCESS", "TRUE", "PUBLISHED"].includes(s)) {
    variant = "success";
  } else if (["REQUESTED", "CANDIDATE", "OBSERVING", "IN_PROGRESS", "TRIAGED", "WAITING_REVIEW", "DEGRADED", "WARNING", "REALTIME"].includes(s)) {
    variant = "warning";
  } else if (["FAILED", "ERROR", "CRITICAL", "REJECTED", "WONT_FIX", "LOCKED", "YES"].includes(s)) {
    variant = "danger";
  } else if (["NEW", "DISABLED", "DUPLICATE", "FALSE", "UNLOCKED", "NO", "DRAFT", "ARCHIVED", "DEPRECATED"].includes(s)) {
    variant = "neutral";
  }
  const label = STATUS_LABELS_ZH[s] || STATUS_LABELS_ZH[raw] || raw;
  const pill = badge(label, variant);
  if (raw && label !== raw) {
    pill.title = raw;
  }
  return pill;
}
