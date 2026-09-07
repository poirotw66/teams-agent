import { el } from "../api.js";

export function attributionText(attribution = {}) {
  const labels = {
    faqKeys: "FAQ",
    documentIds: "Document",
    versionIds: "Version",
    releaseIds: "Release",
  };
  const parts = [];
  for (const [key, label] of Object.entries(labels)) {
    const values = (attribution[key] || []).map((item) => `${item.id} (${item.count})`);
    if (values.length) parts.push(`${label}: ${values.join(", ")}`);
  }
  return parts.join(" | ") || "-";
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
