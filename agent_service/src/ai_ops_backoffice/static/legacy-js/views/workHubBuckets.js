/**
 * Work-hub counters must stay on the same items when the selected tab changes.
 * The selected tab only chooses which list is shown.
 */

export const OPEN_CASE_STATUSES = new Set([
  "NEW",
  "TRIAGED",
  "IN_PROGRESS",
  "WAITING_REVIEW",
  "OBSERVING",
]);

export function partitionQualityCases(items, userId) {
  const openItems = (items || []).filter((item) =>
    OPEN_CASE_STATUSES.has(item.status),
  );
  const normalizedUserId = String(userId || "").trim().toLowerCase();
  let mineItems;
  let mineScopeNote;
  if (normalizedUserId) {
    mineItems = openItems.filter(
      (item) => String(item.assignee_id || "").toLowerCase() === normalizedUserId,
    );
    mineScopeNote = mineItems.length
      ? "指派給我的進行中案件"
      : "目前沒有指派給我的案件；單位可見待辦請到改善案件查看";
  } else {
    mineItems = openItems;
    mineScopeNote = "單位／可見範圍內進行中案件";
  }
  const trackingItems = openItems.filter((item) => item.status === "OBSERVING");
  return { mineItems, trackingItems, mineScopeNote };
}

function isUrgentDocumentRow(row) {
  return row.status !== "無急迫項目";
}

function isTrackingDocumentRow(row) {
  return /觀察|發布|同步/.test(String(row.nextStep || row.status || ""));
}

export function assignWorkHubBuckets({
  documentRows = [],
  pendingReviewRows = [],
  evaluationRows = [],
  mineCaseRows = [],
  trackingCaseRows = [],
}) {
  return {
    mineRows: [
      ...documentRows.filter(isUrgentDocumentRow),
      ...mineCaseRows,
    ],
    reviewRows: [...pendingReviewRows, ...evaluationRows],
    trackingRows: [
      ...trackingCaseRows,
      ...documentRows.filter(isTrackingDocumentRow),
    ],
  };
}
