import { api, apiForm } from "../api.js";
import { fluentButton } from "../fluent.js";
import { navigate } from "../router.js";
import { escapeHtml, showToast } from "../ui.js";

const STEPS = [
  { id: 1, label: "基本資料" },
  { id: 2, label: "治理與適用" },
  { id: 3, label: "正文內容" },
];

function renderStepHeader(currentStep) {
  return `
    <div class="create-steps" aria-label="建立步驟">
      ${STEPS.map((step) => `
        <div class="create-step ${step.id === currentStep ? "active" : ""}">
          步驟 ${step.id} · ${step.label}
        </div>`).join("")}
    </div>`;
}

function renderStepPanel(step) {
  if (step === 1) {
    return `
      <div class="panel form-grid">
        <label class="full">
          匯入文件（可選）
          <input id="importMarkdownFile" type="file" accept=".md,text/markdown">
        </label>
        <p class="muted full">匯入後會自動填入標題與內容。</p>
        <label>標題<input name="title" required></label>
        <label>摘要<textarea name="summary" rows="2"></textarea></label>
        <label>擁有單位<input name="owner_unit_id" value="IT Service Desk" required></label>
        <label>分類<input name="category"></label>
      </div>`;
  }
  if (step === 2) {
    return `
      <div class="panel form-grid">
        <label>生效日<input name="effective_at" type="date" required></label>
        <label>下次檢視日<input name="review_due_at" type="date" required></label>
        <label class="full">變更原因<textarea name="change_reason" rows="2" required></textarea></label>
        <label>適用對象
          <select name="audience_type">
            <option value="ALL_EMPLOYEES">全體員工</option>
            <option value="RESTRICTED_GROUPS">特定群組</option>
          </select>
        </label>
      </div>`;
  }
  return `
    <div class="panel">
      <label class="full">正文內容
        <textarea name="markdown_content" rows="14" required># 範例標題

## 正文

請在此撰寫知識內容。</textarea>
      </label>
    </div>`;
}

export async function renderCreateView(app) {
  let currentStep = 1;
  const formValues = {};

  function render() {
    app.innerHTML = `
      <section class="page">
        <header class="page-header">
          <div>
            <p class="eyebrow">知識庫</p>
            <h2>新增知識文件</h2>
          </div>
          ${fluentButton("返回列表", { appearance: "outline", dataset: { back: "true" } })}
        </header>
        ${renderStepHeader(currentStep)}
        <form id="createForm">
          ${renderStepPanel(currentStep)}
          <div class="form-actions">
            ${currentStep > 1 ? fluentButton("上一步", { appearance: "outline", dataset: { prev: "true" } }) : ""}
            ${currentStep < 3
    ? fluentButton("下一步", { appearance: "accent", dataset: { next: "true" } })
    : fluentButton("建立草稿", { appearance: "accent", type: "submit" })}
          </div>
        </form>
      </section>`;

    app.querySelector("[data-back]")?.addEventListener("click", () => navigate("#/knowledge"));
    const form = app.querySelector("#createForm");
    Object.entries(formValues).forEach(([key, value]) => {
      if (form[key]) form[key].value = value;
    });

    app.querySelector("[data-prev]")?.addEventListener("click", (event) => {
      event.preventDefault();
      Object.assign(formValues, Object.fromEntries(new FormData(form).entries()));
      currentStep -= 1;
      render();
    });
    app.querySelector("[data-next]")?.addEventListener("click", (event) => {
      event.preventDefault();
      Object.assign(formValues, Object.fromEntries(new FormData(form).entries()));
      if (currentStep === 1 && !formValues.title?.trim()) {
        showToast("請先填寫標題", true);
        return;
      }
      if (currentStep === 2 && (!formValues.effective_at || !formValues.review_due_at || !formValues.change_reason?.trim())) {
        showToast("請完成治理與適用欄位", true);
        return;
      }
      currentStep += 1;
      render();
    });

    app.querySelector("#importMarkdownFile")?.addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        const formData = new FormData();
        formData.append("file", file);
        const imported = await apiForm("/api/documents/import-markdown", formData);
        Object.assign(formValues, {
          title: imported.title,
          owner_unit_id: imported.owner_unit_id,
          effective_at: imported.effective_at,
          review_due_at: imported.review_due_at,
          markdown_content: imported.markdown_content,
        });
        showToast(imported.warnings?.length ? imported.warnings.join(" ") : "已匯入文件");
        render();
      } catch (error) {
        showToast(error.message, true);
      } finally {
        event.target.value = "";
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      Object.assign(formValues, Object.fromEntries(new FormData(form).entries()));
      try {
        const created = await api("/api/documents", {
          method: "POST",
          body: JSON.stringify(formValues),
        });
        showToast("草稿已建立");
        navigate(`#/knowledge/${created.document.document_id}/content`);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  }

  render();
}
