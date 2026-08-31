import { testResultLabel } from "../../../labels.js";
import { getSession } from "../../../session.js";
import { escapeHtml, renderStatusBadge } from "../../../ui.js?v=20260831e";
import { can } from "../shared.js";

function renderRunDetails(run) {
  if (!run) return "";
  const parts = [];
  if (run.answer_excerpt) {
    parts.push(`<p><strong>命中摘要</strong>：${escapeHtml(run.answer_excerpt)}</p>`);
  }
  if (run.cited_titles?.length) {
    parts.push(`<p><strong>引用來源</strong>：${run.cited_titles.map((title) => escapeHtml(title)).join("、")}</p>`);
  }
  if (run.failure_reason) {
    parts.push(`<p><strong>失敗原因</strong>：${escapeHtml(run.failure_reason)}</p>`);
  }
  if (!parts.length) return "";
  return `<div class="test-run-detail">${parts.join("")}</div>`;
}

export function renderTestsTab(cases, runsByCase, detail) {
  const session = getSession();
  const hint = session.relaxedWorkflow
    ? "<p class=\"muted\">測試問題為選填，可直接送審。</p>"
    : `<p class="muted">送審前至少 ${session.minTestCasesForReview} 題測試問題（目前 ${cases.length}/${session.minTestCasesForReview}）。</p>`;
  const rows = !cases.length
    ? "<p class=\"muted\">尚未建立測試問題。</p>"
    : cases.map((item) => {
      const run = runsByCase[item.test_case_id];
      const status = run
        ? renderStatusBadge(run.status, testResultLabel(run.status))
        : "尚未執行";
      return `
        <div class="list-row test-case-row">
          <div>
            <strong>${escapeHtml(item.question)}</strong>
            <div>${status}</div>
            ${renderRunDetails(run)}
          </div>
          ${can("MANAGE_TESTS", detail.allowed_actions) ? `
            <button type="button" class="btn secondary btn-sm" data-run-test="${escapeHtml(item.test_case_id)}">執行</button>` : ""}
        </div>`;
    }).join("");
  return `
    ${hint}
    <div class="action-row secondary-actions">
      ${can("MANAGE_TESTS", detail.allowed_actions) ? `
        <button type="button" class="btn secondary" data-action="add-test">新增測試問題</button>
        <button type="button" class="btn secondary" data-action="draft-search">進階診斷</button>` : ""}
    </div>
    <div class="panel">${rows}</div>`;
}
