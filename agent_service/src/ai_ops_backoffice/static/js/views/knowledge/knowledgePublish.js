import { el } from "../../api.js";
import { canUseKnowledgeUi, getCapabilities } from "../../app/capabilities.js";
import { loadNavFilters, navigateTo } from "../../app/navigation.js";
import { renderNativeKnowledgePortal } from "../../knowledge_portal_view.js?v=least-priv-20260910a";

export async function renderKnowledgePortalEntry(sub, mountEl = null) {
  const root = mountEl || document.getElementById("app");
  if (!canUseKnowledgeUi()) {
    root.replaceChildren(
      el(
        "div",
        "error",
        "知識文件庫尚未啟用，或目前角色沒有 knowledge.read。請用 KNOWLEDGE_ADMIN 登入，並確認 start.sh 已啟用 knowledge bridge。",
      ),
    );
    return;
  }

  const filters = { ...loadNavFilters(), ...(sub ? { sub } : {}) };
  await renderNativeKnowledgePortal(root, getCapabilities(), navigateTo, filters);
}

export async function renderKnowledgeDocument() {
  const app = document.getElementById("app");
  const filters = loadNavFilters();
  const documentId = filters.documentId;
  if (!documentId) {
    app.replaceChildren(el("div", "error", "缺少文件 ID。請從品質案件或文件清單進入。"));
    return;
  }
  if (!getCapabilities()?.knowledgeBridgeEnabled) {
    app.replaceChildren(
      el("div", "error", "知識整合尚未啟用。請聯絡平台管理員開啟 knowledge bridge。"),
    );
    return;
  }

  await renderNativeKnowledgePortal(app, getCapabilities(), navigateTo, {
    ...filters,
    sub: `knowledge/${documentId}`,
  });
}
