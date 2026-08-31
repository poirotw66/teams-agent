let baselineSnapshot = null;

function readDraftEditorValues() {
  return {
    title: document.getElementById("draftTitle")?.value ?? "",
    ownerUnit: document.getElementById("draftOwnerUnit")?.value ?? "",
    category: document.getElementById("draftCategory")?.value ?? "",
    summary: document.getElementById("draftSummary")?.value ?? "",
    effectiveAt: document.getElementById("draftEffectiveAt")?.value ?? "",
    reviewDueAt: document.getElementById("draftReviewDueAt")?.value ?? "",
    changeReason: document.getElementById("draftChangeReason")?.value ?? "",
    audienceType: document.getElementById("draftAudienceType")?.value ?? "",
    audienceGroups: document.getElementById("draftAudienceGroups")?.value ?? "",
    markdown: document.getElementById("draftMarkdown")?.value ?? "",
  };
}

export function captureDraftBaseline() {
  if (!document.getElementById("draftEditorForm")) {
    baselineSnapshot = null;
    return;
  }
  baselineSnapshot = JSON.stringify(readDraftEditorValues());
}

export function isDraftEditorDirty() {
  if (!baselineSnapshot || !document.getElementById("draftEditorForm")) {
    return false;
  }
  return JSON.stringify(readDraftEditorValues()) !== baselineSnapshot;
}

export function clearDraftBaseline() {
  baselineSnapshot = null;
}
