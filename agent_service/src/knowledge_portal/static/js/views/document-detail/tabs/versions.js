import { escapeHtml } from "../../../ui.js";
import { can } from "../shared.js";

export function renderVersionsTab(detail) {
  const doc = detail.document;
  const draft = detail.draft_version;
  const published = detail.published_version;
  return `
    <div class="panel">
      <h3>版本資訊</h3>
      <dl class="meta-list">
        ${published ? `<div><dt>正式版本</dt><dd>第 ${published.version_number} 版</dd></div>` : ""}
        ${draft ? `<div><dt>草稿狀態</dt><dd>${escapeHtml(draft.change_summary || "編輯中")}</dd></div>` : ""}
      </dl>
      <details class="advanced-meta">
        <summary>進階資訊</summary>
        <dl class="meta-list technical-meta">
          ${draft ? `<div><dt>草稿版本 ID</dt><dd>${escapeHtml(draft.version_id)}</dd></div>` : ""}
          ${detail.open_review ? `<div><dt>審核編號</dt><dd>${escapeHtml(detail.open_review.review_id)}</dd></div>` : ""}
        </dl>
      </details>
    </div>
    ${can("DISCARD_DRAFT", detail.allowed_actions) || can("UNPUBLISH", detail.allowed_actions) ? `
      <div class="panel danger-zone">
        <h3>高風險操作</h3>
        ${can("DISCARD_DRAFT", detail.allowed_actions) ? `
          <button type="button" class="btn danger" data-action="discard-draft">放棄草稿</button>` : ""}
        ${can("UNPUBLISH", detail.allowed_actions) ? `
          <button type="button" class="btn danger" data-action="unpublish">下架正式文件</button>
          <p class="muted">下架後 Teams 將無法引用此文件。</p>` : ""}
      </div>` : ""}`;
}
