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

export function badge(text, variant = "neutral") {
  return el("span", `badge badge-${variant}`, String(text ?? ""));
}

export function statusBadge(status) {
  const s = String(status || "").toUpperCase();
  let variant = "neutral";
  if (["ACTIVE", "APPROVED", "RESOLVED", "OK", "HEALTHY", "ENABLED", "SUCCESS", "TRUE"].includes(s)) {
    variant = "success";
  } else if (["REQUESTED", "CANDIDATE", "OBSERVING", "IN_PROGRESS", "TRIAGED", "WAITING_REVIEW", "DEGRADED", "WARNING"].includes(s)) {
    variant = "warning";
  } else if (["FAILED", "ERROR", "CRITICAL", "REJECTED", "WONT_FIX", "LOCKED", "YES"].includes(s)) {
    variant = "danger";
  } else if (["NEW", "DISABLED", "DUPLICATE", "FALSE", "UNLOCKED", "NO"].includes(s)) {
    variant = "neutral";
  }
  return badge(status, variant);
}
