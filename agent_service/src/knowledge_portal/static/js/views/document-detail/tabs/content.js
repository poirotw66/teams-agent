import { escapeHtml, stripFrontMatter } from "../../../ui.js?v=20260831c";
import { can, renderIssues, renderParsePreview } from "../shared.js";

export function renderContentTab(documentId, detail, draft) {
  if (!draft) {
    return `
      <div class="panel">
        <p class="muted">目前沒有可編輯草稿。</p>
        ${can("START_REVISION", detail.allowed_actions) ? `
          <button type="button" class="btn primary" data-action="start-revision">建立新版本草稿</button>` : ""}
      </div>`;
  }
  const doc = detail.document;
  const body = stripFrontMatter(draft.canonical_content || "");
  const assets = detail.draft_assets?.items || [];
  const audienceGroups = (doc.audience_group_ids || []).join(", ");
  const editable = can("EDIT_DRAFT", detail.allowed_actions);
  return `
    <form id="draftEditorForm" class="editor-sections">
      <div class="panel">
        <h3>基本資料</h3>
        <div class="form-grid">
          <label>標題
            <input id="draftTitle" value="${escapeHtml(doc.title)}" ${editable ? "" : "readonly"}>
          </label>
          <label>擁有單位
            <input id="draftOwnerUnit" value="${escapeHtml(doc.owner_unit_id)}" ${editable ? "" : "readonly"}>
          </label>
          <label>分類
            <input id="draftCategory" value="${escapeHtml(doc.category || "")}" ${editable ? "" : "readonly"}>
          </label>
          <label>摘要
            <textarea id="draftSummary" rows="2" ${editable ? "" : "readonly"}>${escapeHtml(doc.summary || "")}</textarea>
          </label>
          <label>生效日
            <input id="draftEffectiveAt" type="date" value="${escapeHtml(draft.effective_at)}" ${editable ? "" : "readonly"}>
          </label>
          <label>下次檢視日
            <input id="draftReviewDueAt" type="date" value="${escapeHtml(draft.review_due_at)}" ${editable ? "" : "readonly"}>
          </label>
          <label class="full">變更原因
            <textarea id="draftChangeReason" rows="2" ${editable ? "" : "readonly"}>${escapeHtml(draft.change_reason || "")}</textarea>
          </label>
        </div>
      </div>
      <div class="panel">
        <h3>適用範圍</h3>
        <div class="form-grid">
          <label>適用對象
            <select id="draftAudienceType" data-original="${escapeHtml(doc.audience_type)}" ${editable ? "" : "disabled"}>
              <option value="ALL_EMPLOYEES" ${doc.audience_type === "ALL_EMPLOYEES" ? "selected" : ""}>全體員工</option>
              <option value="RESTRICTED_GROUPS" ${doc.audience_type === "RESTRICTED_GROUPS" ? "selected" : ""}>特定群組</option>
            </select>
          </label>
          <label class="full">特定群組（選填，逗號分隔）
            <input id="draftAudienceGroups" value="${escapeHtml(audienceGroups)}" ${editable ? "" : "readonly"}>
          </label>
        </div>
        <p class="muted">變更適用範圍可能影響引用權限，儲存前會再次確認。</p>
      </div>
      <div class="panel">
        <h3>內容</h3>
        ${renderIssues(draft.validation_summary?.issues || [])}
        <label class="full">正文內容
          <textarea id="draftMarkdown" rows="14" ${editable ? "" : "readonly"}>${escapeHtml(body)}</textarea>
        </label>
        <div class="action-row secondary-actions">
          ${editable ? `<button type="button" class="btn primary" data-action="save-draft">儲存草稿</button>` : ""}
          ${can("VALIDATE", detail.allowed_actions) ? `<button type="button" class="btn secondary" data-action="validate">重新檢查</button>` : ""}
        </div>
      </div>
      <div class="panel">
        <h3>解析預覽</h3>
        <p class="muted">以下為系統依標題結構切分的段落，實際檢索切塊可能略有不同。</p>
        ${renderParsePreview(draft.parse_preview)}
      </div>
      <div class="panel">
        <h3>圖片附件</h3>
        <ul class="asset-list">${assets.length
    ? assets.map((item) => `<li>${escapeHtml(item.filename)} (${item.size_bytes} bytes)</li>`).join("")
    : "<li class=\"muted\">尚未上傳圖片</li>"}</ul>
        <div id="assetPreviewGrid" class="asset-grid"></div>
        ${editable ? `
          <div class="action-row secondary-actions">
            <label class="btn secondary file-button">
              上傳圖片
              <input id="draftAssetUpload" type="file" accept="image/png,image/jpeg,image/gif" multiple hidden>
            </label>
            <button type="button" class="btn secondary" data-action="insert-asset-ref">插入圖片</button>
          </div>` : ""}
      </div>
    </form>`;
}
