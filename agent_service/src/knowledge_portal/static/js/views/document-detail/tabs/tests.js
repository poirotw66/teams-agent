import { testResultLabel } from "../../../labels.js";
import { getSession } from "../../../session.js";
import { escapeHtml, renderStatusBadge } from "../../../ui.js";
import { can } from "../shared.js";

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
        <div class="list-row">
          <div>
            <strong>${escapeHtml(item.question)}</strong>
            <div>${status}${run?.failure_reason ? ` · ${escapeHtml(run.failure_reason)}` : ""}</div>
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
