import { api, el } from "../../api.js";
import { showContentModal } from "../../components/modal.js";

function locatorSummary(locator = {}) {
  const bits = [];
  const type = locator.locator_type || locator.locatorType;
  if (type) bits.push(`類型：${type}`);
  const page =
    locator.page_label ||
    locator.pageLabel ||
    (locator.page_index != null || locator.pageIndex != null
      ? String(Number(locator.page_index ?? locator.pageIndex) + 1)
      : null);
  if (page) bits.push(`頁面：${page}`);
  if (locator.section_path || locator.sectionPath) {
    bits.push(`章節：${locator.section_path || locator.sectionPath}`);
  }
  if (locator.sheet_name || locator.sheetName) {
    bits.push(`工作表：${locator.sheet_name || locator.sheetName}`);
  }
  if (locator.cell_range || locator.cellRange) {
    bits.push(`範圍：${locator.cell_range || locator.cellRange}`);
  }
  return bits.join("｜");
}

function buildDownloadHref(res) {
  if (!res.downloadUrl) return "";
  const locator = res.locator || {};
  const url = new URL(res.downloadUrl, window.location.origin);
  const page =
    locator.page_label ||
    locator.pageLabel ||
    (locator.page_index != null || locator.pageIndex != null
      ? String(Number(locator.page_index ?? locator.pageIndex) + 1)
      : null);
  if (page) {
    url.hash = `page=${encodeURIComponent(page)}`;
    if (locator.bbox) {
      url.hash += `&bbox=${encodeURIComponent(JSON.stringify(locator.bbox))}`;
    }
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

export async function openSourceCitationModal(sourceRefId) {
  const modalBody = el("div", "modal-body");
  modalBody.innerHTML = "<p>載入來源引用中...</p>";
  showContentModal("來源引用詳情", modalBody);

  try {
    const res = await api(`/api/sources/${encodeURIComponent(sourceRefId)}`);
    const locator = res.locator || {};
    const locatorText = locatorSummary(locator);
    const canDownload =
      res.downloadUrl &&
      res.actions?.canDownloadOriginal !== false &&
      res.mappingStatus !== "LEGACY_UNVERIFIED";
    modalBody.innerHTML = `
      <h3>${res.title || "來源文件"}</h3>
      <div class="meta-grid" style="margin-bottom: 12px;">
        <div><strong>Source Ref:</strong> <code>${res.sourceRefId || sourceRefId}</code></div>
        <div><strong>文件 ID:</strong> ${res.documentId || "-"}</div>
        <div><strong>版本:</strong> ${res.versionId || "-"}</div>
        <div><strong>發布 ID:</strong> ${res.releaseId || "-"}</div>
        <div><strong>狀態:</strong> ${res.mappingStatus || res.traceStatus || "UNKNOWN"}</div>
        ${locatorText ? `<div><strong>定位:</strong> ${locatorText}</div>` : ""}
      </div>
      ${locator.degraded_reason || locator.degradedReason ? `
      <div class="callout warning" style="margin-bottom: 12px;">
        ${locator.degraded_reason || locator.degradedReason}
      </div>` : ""}
      <div class="section-block">
        <h4>摘錄內容</h4>
        <div class="content-box source-highlight-target" style="white-space: pre-wrap;"
          data-page-index="${locator.page_index ?? locator.pageIndex ?? ""}"
          data-paragraph-id="${locator.paragraph_id || locator.paragraphId || ""}">${res.evidence?.excerpt || res.snippet || "(無摘錄內容)"}</div>
      </div>
      ${canDownload ? `
      <div style="margin-top: 16px;">
        <a href="${buildDownloadHref(res)}" target="_blank" class="btn-primary">開啟原始文件（跳至定位）</a>
      </div>` : ""}
    `;
  } catch (err) {
    modalBody.innerHTML = `<div class="error">載入來源失敗: ${err.message || err}</div>`;
  }
}
