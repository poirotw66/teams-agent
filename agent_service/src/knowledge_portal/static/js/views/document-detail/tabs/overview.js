import { nextActionLabel } from "../../../labels.js";
import { escapeHtml, renderStatusBadge } from "../../../ui.js?v=20260831e";
import { renderDocumentViewer } from "../../../markdown.js";

function renderPublishedPreview(document, published) {
  if (!published) return "<p class=\"muted\">尚無正式版本內容。</p>";
  const audience = document.audience_type === "ALL_EMPLOYEES"
    ? "全體員工"
    : (document.audience_group_ids || []).join(", ") || "特定群組";
  return `
    <div class="panel doc-preview-panel">
      <div class="doc-preview-meta">
        <div class="doc-preview-title-row">
          <h3>正式版本內容</h3>
          <span class="badge badge--success" style="background:#e7f5eb;color:#0e7030;border:1px solid #b7e1c1;padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:600;">v${published.version_number} 正式發佈</span>
        </div>
        <p class="muted">生效時間：${published.effective_at} · 下次檢視：${published.review_due_at}</p>
        <p class="muted">擁有單位：${escapeHtml(document.owner_unit_id)} · 適用範圍：${escapeHtml(audience)}</p>
        ${document.summary ? `<p class="doc-summary-text">${escapeHtml(document.summary)}</p>` : ""}
      </div>
      ${renderDocumentViewer({
        content: published.canonical_content || "",
        document,
        published,
        id: "overviewDocViewer",
      })}
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
