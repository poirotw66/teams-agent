import { api, apiForm } from "../../api.js";
import { handleConflictError } from "../../errors.js";
import { navigate } from "../../router.js";
import { testResultLabel } from "../../labels.js";
import { showToast } from "../../ui.js?v=20260831e";
import { handleAction } from "./actions.js";

export function wireActions(app, documentId, detail, refresh) {
  app.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const changed = await handleAction(documentId, button.dataset.action, detail);
        if (changed !== false) {
          await refresh();
        }
      } catch (error) {
        if (await handleConflictError(error, refresh)) return;
        showToast(error.message, true);
      }
    });
  });
  app.querySelectorAll("[data-run-test]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const run = await api(
          `/api/documents/${documentId}/test-cases/${button.dataset.runTest}/run`,
          { method: "POST" },
        );
        showToast(`測試結果：${testResultLabel(run.status)}`);
        await refresh();
      } catch (error) {
        if (await handleConflictError(error, refresh)) return;
        showToast(error.message, true);
      }
    });
  });
  app.querySelector('[data-action="run-all-tests"]')?.addEventListener("click", async () => {
    const buttons = [...app.querySelectorAll("[data-run-test]")];
    if (!buttons.length) {
      showToast("請先新增測試問題", true);
      return;
    }
    try {
      for (const button of buttons) {
        await api(
          `/api/documents/${documentId}/test-cases/${button.dataset.runTest}/run`,
          { method: "POST" },
        );
      }
      showToast(`已完成 ${buttons.length} 題測試`);
      await refresh();
    } catch (error) {
      if (await handleConflictError(error, refresh)) return;
      showToast(error.message, true);
    }
  });
  const assetUpload = app.querySelector("#draftAssetUpload");
  if (assetUpload) {
    assetUpload.addEventListener("change", async (event) => {
      const files = event.target.files;
      if (!files?.length) return;
      try {
        const formData = new FormData();
        for (const file of files) formData.append("files", file);
        await apiForm(`/api/documents/${documentId}/draft/assets`, formData);
        showToast(`已上傳 ${files.length} 張圖片`);
        navigate(`#/knowledge/${documentId}/content`);
      } catch (error) {
        if (await handleConflictError(error, refresh)) return;
        showToast(error.message, true);
      } finally {
        event.target.value = "";
      }
    });
  }
}
