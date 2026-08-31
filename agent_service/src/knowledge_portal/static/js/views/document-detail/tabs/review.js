import { audienceLabel, testResultLabel } from "../../../labels.js";
import { escapeHtml, stripFrontMatter } from "../../../ui.js";
import { can, renderIssues } from "../shared.js";

export function renderReviewTab(detail, cases, runsByCase) {
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
      return `<li>${escapeHtml(item.question)} — ${escapeHtml(label)}</li>`;
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
        <ul class="issue-list">${testRows}</ul>
      </div>
      <div class="compare-grid">
        <div class="panel">
          <h3>正式版本內容</h3>
          <pre class="content-preview content-preview--full">${escapeHtml(publishedBody || "（首次送審，無正式版本）")}</pre>
        </div>
        <div class="panel">
          <h3>草稿版本內容</h3>
          <pre class="content-preview content-preview--full">${escapeHtml(draftBody || "（無內容）")}</pre>
        </div>
      </div>
      ${can("APPROVE", detail.allowed_actions) || can("REJECT", detail.allowed_actions) ? `
        <div class="panel review-actions">
          <h3>審核決策</h3>
          <p class="muted">核准或退回前，請確認內容、適用範圍與測試結果。</p>
          <div class="action-row">
            ${can("APPROVE", detail.allowed_actions) ? `<button type="button" class="btn primary" data-action="approve">核准</button>` : ""}
            ${can("REJECT", detail.allowed_actions) ? `<button type="button" class="btn secondary" data-action="reject">退回修改</button>` : ""}
          </div>
        </div>` : ""}
    </div>`;
}
