import { audienceLabel, testResultLabel } from "../../../labels.js";
import { getSession } from "../../../session.js";
import { renderLineDiffHtml } from "../../../diff.js";
import { escapeHtml, stripFrontMatter } from "../../../ui.js?v=20260831e";
import { can, renderIssues } from "../shared.js";
import { renderDocumentViewer } from "../../../markdown.js?v=pdf-img-20260908c";

export function renderReviewTab(detail, cases, runsByCase) {
  const session = getSession();
  const minimumCases = Number(session.minTestCasesForReview ?? 3);
  const belowMinimum = cases.length < minimumCases;
  const draft = detail.draft_version;
  const published = detail.published_version;
  const draftBody = stripFrontMatter(draft?.canonical_content || "");
  const publishedBody = published ? stripFrontMatter(published.canonical_content || "") : "";
  const audienceChanged = Boolean(
    published
    && draft
    && (
      draft.audience_type !== published.audience_type
      || JSON.stringify(draft.audience_group_ids || []) !== JSON.stringify(published.audience_group_ids || [])
    ),
  );
  const testRows = cases.length
    ? cases.map((item) => {
      const run = runsByCase[item.test_case_id];
      const label = run ? testResultLabel(run.status) : "尚未執行";
      return `<li>${escapeHtml(item.question)} - ${escapeHtml(label)}</li>`;
    }).join("")
    : "<li class=\"muted\">尚未建立測試問題</li>";

  return `
    <div class="review-workspace">
      <div class="panel">
        <h3>送審資訊</h3>
        <p>送審者：${escapeHtml(detail.open_review?.submitted_by || "")}</p>
        <p>送審時間：${detail.open_review ? new Date(detail.open_review.submitted_at).toLocaleString("zh-TW") : ""}</p>
        <p>送審理由：${escapeHtml(draft?.change_reason || "未提供")}</p>
      </div>
      ${audienceChanged ? `
        <div class="panel review-alert">
          <h3>適用範圍變更提醒</h3>
          <p>正式版：${escapeHtml(audienceLabel(published.audience_type, published.audience_group_ids))}</p>
          <p>草稿版：${escapeHtml(audienceLabel(draft.audience_type, draft.audience_group_ids))}</p>
        </div>` : ""}
      <div class="panel">
        <h3>品質檢查</h3>
        ${renderIssues(draft?.validation_summary?.issues || [])}
      </div>
      <div class="panel">
        <h3>問答測試結果</h3>
        ${belowMinimum ? `<div class="review-alert"><strong>尚不能完成審核</strong><p>正式流程要求至少 ${minimumCases} 題測試問題，目前只有 ${cases.length} 題；請先建立測試問題。</p></div>` : (cases.length === 0 ? '<p class="muted">目前為放寬工作流程（允許 0 題）；正式環境仍應確認審核政策。</p>' : '')}
        <ul class="issue-list">${testRows}</ul>
      </div>
      ${publishedBody ? `
        <div class="panel">
          <h3>內容變更摘要</h3>
          <p class="muted">以下列出與正式版本不同的段落；完整內容請見下方並排檢視。</p>
          ${renderLineDiffHtml(publishedBody, draftBody)}
        </div>` : ""}
      <div class="compare-grid${published?.canonical_content ? "" : " compare-grid--draft-only"}">
        ${published?.canonical_content ? `
          <details class="panel collapsible-panel review-published-panel">
            <summary class="collapsible-panel__summary">
              <span class="collapsible-panel__title">正式版本內容</span>
              <span class="collapsible-panel__hint muted">點擊展開／收合 · v${published.version_number}</span>
            </summary>
            <div class="collapsible-panel__body">
              ${renderDocumentViewer({ content: published.canonical_content, compact: true, id: "reviewPublishedViewer" })}
            </div>
          </details>` : ""}
        <div class="panel">
          <h3>草稿版本內容</h3>
          ${draft?.canonical_content
            ? renderDocumentViewer({ content: draft.canonical_content, compact: true, id: "reviewDraftViewer" })
            : '<p class="muted">（無內容）</p>'}
        </div>
      </div>
      ${can("APPROVE", detail.allowed_actions) || can("REJECT", detail.allowed_actions) ? `
        <div class="panel review-actions">
          <h3>審核決策</h3>
          <p class="muted">核准或退回前，請確認內容、適用範圍與測試結果。${belowMinimum ? "目前尚未達到最低測試題數，核准按鈕已停用。" : ""}</p>
          <div class="action-row">
            ${can("APPROVE", detail.allowed_actions) ? `<button type="button" class="btn primary" data-action="approve" ${belowMinimum ? "disabled title=\"尚未達到最低測試題數\"" : ""}>核准</button>` : ""}
            ${can("REJECT", detail.allowed_actions) ? `<button type="button" class="btn secondary" data-action="reject">退回修改</button>` : ""}
          </div>
        </div>` : ""}
    </div>`;
}
