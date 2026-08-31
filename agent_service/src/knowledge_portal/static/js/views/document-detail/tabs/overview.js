import { nextActionLabel } from "../../../labels.js";
import { escapeHtml, renderStatusBadge, stripFrontMatter } from "../../../ui.js";

function renderPublishedPreview(document, published) {
  if (!published) return "<p class=\"muted\">尚無正式版本內容。</p>";
  const body = stripFrontMatter(published.canonical_content || "");
  const preview = body.length > 1200 ? `${body.slice(0, 1200)}\n…` : body;
  const audience = document.audience_type === "ALL_EMPLOYEES"
    ? "全體員工"
    : (document.audience_group_ids || []).join(", ") || "特定群組";
  return `
    <div class="panel">
      <h3>正式版本預覽</h3>
      <p class="muted">版本 ${published.version_number} · 生效 ${published.effective_at} · 下次檢視 ${published.review_due_at}</p>
      <p>擁有單位：${escapeHtml(document.owner_unit_id)} · 適用範圍：${escapeHtml(audience)}</p>
      ${document.summary ? `<p>${escapeHtml(document.summary)}</p>` : ""}
      <pre class="content-preview">${escapeHtml(preview)}</pre>
    </div>`;
}

export function renderOverviewTab(detail) {
  const doc = detail.document;
  const nextLabel = nextActionLabel(detail.next_action);
  return `
    <div class="detail-grid">
      <div class="panel">
        <h3>文件摘要</h3>
        <dl class="meta-list">
          <div><dt>狀態</dt><dd>${renderStatusBadge(doc.status, detail.status_label)}</dd></div>
          <div><dt>擁有單位</dt><dd>${escapeHtml(doc.owner_unit_id)}</dd></div>
          <div><dt>最後更新</dt><dd>${new Date(doc.updated_at).toLocaleString("zh-TW")}</dd></div>
        </dl>
        ${doc.summary ? `<p>${escapeHtml(doc.summary)}</p>` : ""}
      </div>
      ${detail.published_version ? renderPublishedPreview(doc, detail.published_version) : ""}
      ${detail.open_review ? `
        <div class="panel review-panel">
          <h3>審核中</h3>
          <p>送審者：${escapeHtml(detail.open_review.submitted_by)}</p>
          <p class="muted">送審時間：${new Date(detail.open_review.submitted_at).toLocaleString("zh-TW")}</p>
        </div>` : ""}
    </div>
    ${nextLabel ? `<p class="next-action-hint">建議下一步：<strong>${escapeHtml(nextLabel)}</strong></p>` : ""}`;
}
