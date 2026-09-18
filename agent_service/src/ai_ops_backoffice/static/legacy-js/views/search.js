import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
import { createPageController } from "../app/lifecycle.js";
import { badge } from "../components/badges.js";
import { showContentModal, closeContentModal } from "../components/modal.js";
import { showConversationModal } from "../components/conversationModal.js";
import { showQualityCaseDetail } from "./quality.js";

function openSearchItemDetail(item) {
  if (item.type === "CONVERSATION") {
    showConversationModal(item.id);
    return;
  }
  if (item.type === "QUALITY_CASE") {
    showQualityCaseDetail(item.id);
    return;
  }

  const content = el("div");
  content.style.display = "flex";
  content.style.flexDirection = "column";
  content.style.gap = "0.75rem";

  const metaRow = el("div", "filter-bar");
  metaRow.style.gap = "0.5rem";
  metaRow.append(badge(`類別：${item.type}`, "accent"));
  if (item.status) metaRow.append(badge(`狀態：${item.status}`, "neutral"));
  if (item.owner_unit_id) metaRow.append(badge(`單位：${item.owner_unit_id}`, "neutral"));
  content.append(metaRow);

  const idRow = el("div");
  idRow.append(el("span", "metric-label", "資源識別碼 (ID)： "), el("code", "", item.id));
  content.append(idRow);

  const snippetBox = el("div");
  snippetBox.style.background = "var(--bg-card, #f8fafc)";
  snippetBox.style.padding = "0.75rem";
  snippetBox.style.borderRadius = "4px";
  snippetBox.style.border = "1px solid var(--border-subtle, #e2e8f0)";
  snippetBox.style.whiteSpace = "pre-wrap";
  snippetBox.style.wordBreak = "break-word";
  snippetBox.textContent = item.snippet || item.title || "無摘要內容";
  content.append(snippetBox);

  const viewTargetMap = {
    FAQ: "#/knowledge_ops/faq",
    KNOWLEDGE: "#/knowledge_ops/knowledgePortal",
    EXAMPLE: "#/ai_ops/examples",
    FLAG: "#/ai_ops/flags",
    MODEL: "#/ai_ops/models",
    PROMPT: "#/ai_ops/prompts",
    ROLE_MAPPING: "#/platform/roles",
    RETENTION: "#/platform/retention",
    MASKING: "#/platform/masking",
    AUDIT: "#/platform/audit",
    ISSUE_TYPE: "#/platform/issues",
  };

  const targetHash = viewTargetMap[item.type];
  if (targetHash) {
    const actions = el("div");
    actions.style.display = "flex";
    actions.style.justifyContent = "flex-end";
    actions.style.marginTop = "0.5rem";

    const navBtn = el("button", "", "前往此資源頁面");
    navBtn.addEventListener("click", () => {
      closeContentModal();
      window.location.hash = targetHash;
    });
    actions.append(navBtn);
    content.append(actions);
  }

  showContentModal(`${item.title || item.id} 詳情`, content);
}

export async function renderGovernanceSearch() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const panel = el("section", "panel");
    panel.append(el("h2", "", "權限感知全域搜尋"));
    const form = el("form", "form-grid");
    const input = el("input");
    input.name = "q";
    input.placeholder = "搜尋關鍵字…";
    input.setAttribute("aria-label", "搜尋關鍵字");

    const categorySelect = el("select");
    categorySelect.name = "doc_type";
    categorySelect.setAttribute("aria-label", "資源類別");
    for (const [val, lab] of [
      ["", "全部類別"],
      ["FAQ", "常見問題 (FAQ)"],
      ["KNOWLEDGE", "知識文件 (Knowledge)"],
      ["ISSUE_TYPE", "問題分類 (Issue Type)"],
      ["CONVERSATION", "對話紀錄 (Conversation)"],
      ["QUALITY_CASE", "品質案件 (Quality Case)"],
      ["EXAMPLE", "測試案例 (Example)"],
      ["FLAG", "功能開關 (Feature Flag)"],
      ["MODEL", "模型設定 (Model Config)"],
      ["PROMPT", "系統提示詞 (Prompt)"],
      ["ROLE_MAPPING", "角色權限 (Role Mapping)"],
      ["AUDIT", "稽核事件 (Audit)"],
    ]) {
      const opt = el("option", "", lab);
      opt.value = val;
      categorySelect.append(opt);
    }

    const statusSelect = el("select");
    statusSelect.name = "status";
    statusSelect.setAttribute("aria-label", "狀態篩選");
    for (const [val, lab] of [
      ["", "全部狀態"],
      ["ACTIVE", "啟用 (ACTIVE)"],
      ["DRAFT", "草稿 (DRAFT)"],
      ["PUBLISHED", "已發布 (PUBLISHED)"],
      ["IN_REVIEW", "審查中 (IN_REVIEW)"],
      ["ARCHIVED", "已封存 (ARCHIVED)"],
      ["RETIRED", "已淘汰 (RETIRED)"],
      ["OPEN", "待處理 (OPEN)"],
      ["RESOLVED", "已解決 (RESOLVED)"],
      ["CLOSED", "已關閉 (CLOSED)"],
    ]) {
      const opt = el("option", "", lab);
      opt.value = val;
      statusSelect.append(opt);
    }

    const ownerInput = el("input");
    ownerInput.name = "owner_unit_id";
    ownerInput.placeholder = "擁有單位 (Owner)…";
    ownerInput.setAttribute("aria-label", "擁有單位");

    const submit = el("button", "", "搜尋");
    submit.type = "submit";
    form.append(input, categorySelect, statusSelect, ownerInput, submit);
    const results = el("div");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = (input.value || "").trim();
      const docType = categorySelect.value;
      const status = statusSelect.value;
      const ownerUnitId = (ownerInput.value || "").trim();
      if (!query && !docType && !status && !ownerUnitId) return;
      results.replaceChildren(el("div", "empty", "搜尋中…"));
      try {
        const params = new URLSearchParams();
        if (query) params.set("q", query);
        if (docType) params.set("doc_type", docType);
        if (status) params.set("status", status);
        if (ownerUnitId) params.set("owner_unit_id", ownerUnitId);
        const data = await api(`/api/governance/search?${params.toString()}`);
        results.replaceChildren();

        if (data.warnings && data.warnings.length) {
          const warnBox = el("div");
          warnBox.className = "alert alert-warning";
          warnBox.style.margin = "0.75rem 0";
          warnBox.style.padding = "0.75rem 1rem";
          warnBox.style.borderRadius = "6px";
          warnBox.style.background = "#fff8e6";
          warnBox.style.color = "#8a5300";
          warnBox.style.border = "1px solid #ffd591";
          const warnTitle = el("strong", "", "部分外部資料來源讀取異常：");
          const warnList = el("ul");
          warnList.style.margin = "0.35rem 0 0 1.25rem";
          warnList.style.padding = "0";
          for (const w of data.warnings) {
            warnList.append(el("li", "", w));
          }
          warnBox.append(warnTitle, warnList);
          results.append(warnBox);
        }

        const summaryBar = el("div", "filter-bar");
        summaryBar.style.margin = "1rem 0";
        summaryBar.append(badge(`搜尋結果：${data.count} 筆`, data.count > 0 ? "success" : "neutral"));
        results.append(summaryBar);

        if (!data.items || !data.items.length) {
          results.append(el("p", "empty", "未找到符合關鍵字的資源。"));
        } else {
          const listContainer = el("div");
          listContainer.style.display = "flex";
          listContainer.style.flexDirection = "column";
          listContainer.style.gap = "0.75rem";
          for (const item of data.items) {
            const card = el("div", "metric");
            card.style.flexDirection = "row";
            card.style.justifyContent = "space-between";
            card.style.alignItems = "center";
            card.style.padding = "0.85rem 1.15rem";

            const info = el("div");
            info.style.minWidth = "0";
            const titleRow = el("div");
            titleRow.style.display = "flex";
            titleRow.style.alignItems = "center";
            titleRow.style.gap = "0.6rem";
            titleRow.style.marginBottom = "0.3rem";

            const typeBadge = badge(item.type, "accent");
            const titleStrong = el("strong", "", item.title || item.id || "未命名");
            titleStrong.style.fontSize = "0.95rem";
            titleRow.append(typeBadge, titleStrong);
            if (item.status) {
              titleRow.append(badge(item.status, "info"));
            }
            if (item.owner_unit_id) {
              titleRow.append(badge(item.owner_unit_id, "neutral"));
            }

            const snippetP = el("div", "metric-label", item.snippet || "-");
            snippetP.style.textTransform = "none";
            snippetP.style.letterSpacing = "normal";
            snippetP.style.fontSize = "0.8rem";
            info.append(titleRow, snippetP);

            const detailBtn = el("button", "secondary", "開啟詳情");
            detailBtn.style.flexShrink = "0";
            detailBtn.style.marginLeft = "1rem";
            detailBtn.addEventListener("click", () => openSearchItemDetail(item));

            card.append(info, detailBtn);
            listContainer.append(card);
          }
          results.append(listContainer);
        }
      } catch (err) {
        results.replaceChildren(el("div", "error", `搜尋失敗：${err.message || err}`));
      }
    });
    panel.append(form, results);
    presentSystemPage(
      "全域搜尋",
      "依權限搜尋對話、案件與知識內容。",
      panel,
    );
  } catch (error) {
    presentSystemPage("全域搜尋", null, el("div", "error", error.message));
  }
}

export const searchPage = createPageController({
  enter: async () => renderGovernanceSearch(),
  update: async () => renderGovernanceSearch(),
  leave: async () => {},
});
