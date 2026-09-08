import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { createPageController } from "../app/lifecycle.js";
import { badge } from "../components/badges.js";

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

    const ownerInput = el("input");
    ownerInput.name = "owner_unit_id";
    ownerInput.placeholder = "擁有單位 (Owner)…";
    ownerInput.setAttribute("aria-label", "擁有單位");

    const submit = el("button", "", "搜尋");
    submit.type = "submit";
    form.append(input, categorySelect, ownerInput, submit);
    const results = el("div");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = (input.value || "").trim();
      const docType = categorySelect.value;
      const ownerUnitId = (ownerInput.value || "").trim();
      if (!query && !docType && !ownerUnitId) return;
      results.replaceChildren(el("div", "empty", "搜尋中…"));
      try {
        const params = new URLSearchParams();
        if (query) params.set("q", query);
        if (docType) params.set("doc_type", docType);
        if (ownerUnitId) params.set("owner_unit_id", ownerUnitId);
        const data = await api(`/api/governance/search?${params.toString()}`);
        results.replaceChildren();
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
            if (item.owner_unit_id) {
              titleRow.append(badge(item.owner_unit_id, "neutral"));
            }

            const snippetP = el("div", "metric-label", item.snippet || "-");
            snippetP.style.textTransform = "none";
            snippetP.style.letterSpacing = "normal";
            snippetP.style.fontSize = "0.8rem";
            info.append(titleRow, snippetP);

            card.append(info);
            listContainer.append(card);
          }
          results.append(listContainer);
        }
      } catch (err) {
        results.replaceChildren(el("div", "error", `搜尋失敗：${err.message || err}`));
      }
    });
    panel.append(form, results);
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

export const searchPage = createPageController({
  enter: async () => renderGovernanceSearch(),
  update: async () => renderGovernanceSearch(),
  leave: async () => {},
});
