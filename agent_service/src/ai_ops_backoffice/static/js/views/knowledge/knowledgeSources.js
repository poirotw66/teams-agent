import { api, el } from "../../api.js";
import { showContentModal } from "../../components/modal.js";

export async function openSourceCitationModal(sourceRefId) {
  const modalBody = el("div", "modal-body");
  modalBody.innerHTML = "<p>載入來源引用中...</p>";
  showContentModal("來源引用詳情", modalBody);

  try {
    const res = await api(`/api/sources/${encodeURIComponent(sourceRefId)}`);
    modalBody.innerHTML = `
      <h3>${res.title || "來源文件"}</h3>
      <div class="meta-grid" style="margin-bottom: 12px;">
        <div><strong>Source Ref:</strong> <code>${res.sourceRefId || sourceRefId}</code></div>
        <div><strong>文件 ID:</strong> ${res.documentId || "-"}</div>
        <div><strong>版本:</strong> ${res.versionId || "-"}</div>
        <div><strong>發布 ID:</strong> ${res.releaseId || "-"}</div>
        <div><strong>狀態:</strong> ${res.mappingStatus || "UNKNOWN"}</div>
      </div>
      <div class="section-block">
        <h4>摘錄內容</h4>
        <div class="content-box" style="white-space: pre-wrap;">${res.snippet || "(無摘錄內容)"}</div>
      </div>
      ${res.downloadUrl ? `
      <div style="margin-top: 16px;">
        <a href="${res.downloadUrl}" target="_blank" class="btn-primary">下載原始文件</a>
      </div>` : ""}
    `;
  } catch (err) {
    modalBody.innerHTML = `<div class="error">載入來源失敗: ${err.message || err}</div>`;
  }
}
