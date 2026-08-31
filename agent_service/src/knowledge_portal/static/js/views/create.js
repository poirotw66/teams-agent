import { api, apiForm } from "../api.js";
import { navigate } from "../router.js";
import { escapeHtml, showToast } from "../ui.js";

export async function renderCreateView(app) {
  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <p class="eyebrow">知識庫</p>
          <h2>新增知識文件</h2>
        </div>
        <button type="button" class="btn secondary" data-back>返回列表</button>
      </header>
      <div class="panel">
        <label class="full">
          匯入 Markdown 檔（可選）
          <input id="importMarkdownFile" type="file" accept=".md,text/markdown">
        </label>
        <p class="muted">匯入後會自動填入標題與內容；建立草稿後再上傳圖片。</p>
      </div>
      <form id="createForm" class="panel form-grid">
        <label>標題<input name="title" required></label>
        <label>摘要<textarea name="summary" rows="2"></textarea></label>
        <label>擁有單位<input name="owner_unit_id" value="IT Service Desk" required></label>
        <label>分類<input name="category"></label>
        <label>生效日<input name="effective_at" type="date" required></label>
        <label>下次檢視日<input name="review_due_at" type="date" required></label>
        <label>變更原因<textarea name="change_reason" rows="2" required></textarea></label>
        <label>適用範圍
          <select name="audience_type">
            <option value="ALL_EMPLOYEES">全體員工</option>
            <option value="RESTRICTED_GROUPS">特定群組</option>
          </select>
        </label>
        <label class="full">Markdown 內容
          <textarea name="markdown_content" rows="14" required># 範例標題

## 正文

請在此撰寫知識內容。</textarea>
        </label>
        <div class="form-actions full">
          <button type="submit" class="btn primary">建立草稿</button>
        </div>
      </form>
    </section>`;

  app.querySelector("[data-back]")?.addEventListener("click", () => navigate("#/knowledge"));

  app.querySelector("#importMarkdownFile")?.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const imported = await apiForm("/api/documents/import-markdown", formData);
      const form = app.querySelector("#createForm");
      form.title.value = imported.title;
      form.owner_unit_id.value = imported.owner_unit_id;
      form.effective_at.value = imported.effective_at;
      form.review_due_at.value = imported.review_due_at;
      form.markdown_content.value = imported.markdown_content;
      showToast(imported.warnings?.length ? imported.warnings.join(" ") : "已匯入 Markdown");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      event.target.value = "";
    }
  });

  app.querySelector("#createForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = Object.fromEntries(form.entries());
    try {
      const created = await api("/api/documents", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showToast("草稿已建立");
      navigate(`#/knowledge/${created.document.document_id}/content`);
    } catch (error) {
      showToast(error.message, true);
    }
  });
}
