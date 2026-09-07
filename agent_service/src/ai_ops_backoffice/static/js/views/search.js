import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderGovernanceSearch() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const panel = el("section", "panel");
    panel.append(el("h2", "", "權限感知全域搜尋"));
    const form = el("form", "form-grid");
    const input = el("input");
    input.name = "q";
    input.placeholder = "搜尋 Prompt / Flag / Model / Role / Retention / FAQ / Example / Issue / Quality / Audit";
    const submit = el("button", "", "搜尋");
    submit.type = "submit";
    form.append(input, submit);
    const results = el("div");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = (input.value || "").trim();
      if (!query) return;
      results.replaceChildren(el("div", "empty", "搜尋中…"));
      try {
        const data = await api(`/api/governance/search?q=${encodeURIComponent(query)}`);
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
