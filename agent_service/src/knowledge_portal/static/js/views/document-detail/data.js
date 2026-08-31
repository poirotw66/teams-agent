import { api, loadAssetPreviewUrl } from "../../api.js";
import { navigate } from "../../router.js";
import { escapeHtml, showToast } from "../../ui.js";

export async function loadTestData(documentId, detail) {
  if (!detail.draft_version) return { cases: [], runsByCase: {} };
  const cases = await api(`/api/documents/${documentId}/test-cases`);
  const runsByCase = {};
  const runs = await api(`/api/documents/${documentId}/test-runs`).catch(() => []);
  for (const run of runs || []) {
    runsByCase[run.test_case_id] = run;
  }
  return { cases, runsByCase };
}

export async function hydrateAssetPreviews(documentId, assets) {
  const grid = document.getElementById("assetPreviewGrid");
  if (!grid || !assets.length) return;
  grid.innerHTML = "";
  for (const item of assets) {
    const card = document.createElement("div");
    card.className = "asset-card";
    card.innerHTML = `
      <img alt="${escapeHtml(item.filename)}" />
      <div class="meta">${escapeHtml(item.filename)}</div>
      <button type="button" class="btn secondary btn-sm" data-delete-asset="${escapeHtml(item.filename)}">刪除</button>`;
    grid.appendChild(card);
    try {
      const url = await loadAssetPreviewUrl(documentId, item.filename);
      card.querySelector("img").src = url;
    } catch {
      card.querySelector(".meta").textContent = `${item.filename} · 預覽失敗`;
    }
  }
  grid.querySelectorAll("[data-delete-asset]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(
          `/api/documents/${documentId}/draft/assets/${encodeURIComponent(button.dataset.deleteAsset)}`,
          { method: "DELETE" },
        );
        showToast("已刪除圖片");
        navigate(`#/knowledge/${documentId}/content`);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
}
