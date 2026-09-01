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

export function computeTestReadiness(cases, runsByCase, session) {
  const minRequired = session.relaxedWorkflow ? 0 : (session.minTestCasesForReview || 3);
  let passCount = 0;
  let needsReviewCount = 0;
  let failCount = 0;
  let executed = 0;

  for (const item of cases) {
    const run = runsByCase[item.test_case_id];
    if (!run) continue;
    executed += 1;
    if (run.status === "PASS") passCount += 1;
    else if (run.status === "NEEDS_REVIEW") needsReviewCount += 1;
    else if (run.status === "FAIL") failCount += 1;
  }

  const meetsMinimum = cases.length >= minRequired;
  const allExecuted = cases.length > 0 && executed === cases.length;
  const readyForReview = session.relaxedWorkflow
    ? true
    : meetsMinimum && allExecuted && failCount === 0;

  return {
    minRequired,
    total: cases.length,
    executed,
    passCount,
    needsReviewCount,
    failCount,
    meetsMinimum,
    allExecuted,
    readyForReview,
  };
}

function renderReadinessPanel(readiness, session) {
  const statusClass = readiness.readyForReview ? "readiness-ok" : "readiness-warn";
  const statusText = readiness.readyForReview ? "可送審" : "尚未就緒";
  const minLine = session.relaxedWorkflow
    ? "Demo 環境：測試題為選填。"
    : `送審前至少 ${readiness.minRequired} 題測試（目前 ${readiness.total}/${readiness.minRequired}）。`;

  return `
    <div class="readiness-panel ${statusClass}" role="status">
      <div class="readiness-header">
        <strong>測試就緒狀態：${escapeHtml(statusText)}</strong>
      </div>
      <p class="muted">${escapeHtml(minLine)}</p>
      <dl class="readiness-stats">
        <div><dt>已執行</dt><dd>${readiness.executed}/${readiness.total}</dd></div>
        <div><dt>可回答</dt><dd>${readiness.passCount}</dd></div>
        <div><dt>需要確認</dt><dd>${readiness.needsReviewCount}</dd></div>
        <div><dt>無法回答</dt><dd>${readiness.failCount}</dd></div>
      </dl>
    </div>`;
}

export function renderTestsTab(cases, runsByCase, detail) {
  const session = getSession();
  const readiness = computeTestReadiness(cases, runsByCase, session);
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

  const canManage = can("MANAGE_TESTS", detail.allowed_actions);
  return `
    ${renderReadinessPanel(readiness, session)}
    <div class="action-row secondary-actions">
      ${canManage ? `
        <button type="button" class="btn secondary" data-action="add-test">新增測試問題</button>
        <button type="button" class="btn secondary" data-action="run-all-tests" ${cases.length ? "" : "disabled"}>全部執行</button>
        <button type="button" class="btn secondary" data-action="draft-search">進階診斷</button>` : ""}
    </div>
    <div class="panel">${rows}</div>`;
}
