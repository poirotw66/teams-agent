import { nextActionLabel } from "../../labels.js";
import { escapeHtml } from "../../ui.js";

export const TABS = [
  { id: "overview", label: "概覽" },
  { id: "content", label: "內容與附件" },
  { id: "tests", label: "問答測試" },
  { id: "versions", label: "版本與稽核" },
];

export function can(action, allowedActions = []) {
  return allowedActions.includes(action);
}

export function renderIssues(issues = []) {
  if (!issues.length) return "<p class=\"muted\">未發現品質問題。</p>";
  return `<ul class="issue-list">${issues.map((issue) => `
    <li class="issue ${issue.severity.toLowerCase()}">[${issue.severity}] ${escapeHtml(issue.message)}</li>
  `).join("")}</ul>`;
}

export function getVisibleTabs(detail) {
  if (
    detail.open_review
    && (can("APPROVE", detail.allowed_actions) || can("REJECT", detail.allowed_actions))
  ) {
    return [
      TABS[0],
      { id: "review", label: "審核工作" },
      ...TABS.slice(1),
    ];
  }
  return TABS;
}

function actionSlug(action) {
  const mapping = {
    EDIT_DRAFT: "save-draft",
    SUBMIT_REVIEW: "submit",
    START_REVISION: "start-revision",
  };
  return mapping[action] || action.toLowerCase().replace(/_/g, "-");
}

export function renderActionPanel(detail) {
  const actions = detail.allowed_actions || [];
  const primary = detail.next_action;
  const hasReviewTab = getVisibleTabs(detail).some((item) => item.id === "review");
  const buttons = [];
  if (primary && can(primary, actions)) {
    const reviewDecision = primary === "APPROVE" || primary === "REJECT";
    if (!(hasReviewTab && reviewDecision)) {
      const slug = primary === "EDIT_DRAFT" ? "edit-draft" : actionSlug(primary);
      buttons.push(`<button type="button" class="btn primary" data-action="${slug}">${escapeHtml(nextActionLabel(primary))}</button>`);
    }
  }
  if (!hasReviewTab && can("APPROVE", actions) && primary !== "APPROVE") {
    buttons.push(`<button type="button" class="btn primary" data-action="approve">核准</button>`);
  }
  if (!hasReviewTab && can("REJECT", actions) && primary !== "REJECT") {
    buttons.push(`<button type="button" class="btn secondary" data-action="reject">退回修改</button>`);
  }
  if (can("PUBLISH", actions) && primary !== "PUBLISH") {
    buttons.push(`<button type="button" class="btn primary" data-action="publish">發布正式版本</button>`);
  }
  if (can("SUBMIT_REVIEW", actions) && primary !== "SUBMIT_REVIEW") {
    buttons.push(`<button type="button" class="btn secondary" data-action="submit">送審</button>`);
  }
  if (!buttons.length) return "";
  return `<aside class="action-panel"><h3>工作區</h3><div class="action-row">${buttons.join("")}</div></aside>`;
}
