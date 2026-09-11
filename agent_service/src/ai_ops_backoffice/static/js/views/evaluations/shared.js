import { getCapabilities } from "../../app/capabilities.js";

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function safeClassToken(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "");
}

export function actorCanManageOwnerUnits(ownerUnitIds = []) {
  const current = getCapabilities() || {};
  if (["SYSTEM_ADMIN", "AI_ADMIN", "AUDITOR"].includes(current.role)) {
    return true;
  }
  const ownedUnits = new Set(current.ownerUnitIds || []);
  return ownerUnitIds.every((unit) => ownedUnits.has(unit));
}
