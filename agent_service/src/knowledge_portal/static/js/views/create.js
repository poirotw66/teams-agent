import { api, apiForm } from "../api.js";
import { fluentButton } from "../fluent.js";
import { navigate } from "../router.js";
import { escapeHtml, showToast } from "../ui.js?v=20260831d";

const STEPS = [
  { id: 1, label: "基本資料" },
  { id: 2, label: "治理與適用" },
  { id: 3, label: "正文內容" },
];

function parseAudienceGroupIds(value) {
  return (value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderStepHeader(currentStep) {
  return `
    <ol class="create-steps" aria-label="建立步驟">
      ${STEPS.map((step) => `
        <li class="create-step ${step.id === currentStep ? "active" : ""}"${step.id === currentStep ? ' aria-current="step"' : ""}>
          步驟 ${step.id} · ${step.label}
        </li>`).join("")}
    </ol>`;
}

function renderStepPanel(step, formValues) {
  if (step === 1) {
    return `
      <div class="panel form-grid">
        <label class="full">
          匯入文件（可選）
          <input id="importMarkdownFile" type="file" accept=".md,text/markdown">
        </label>
        <p class="muted full">匯入後會自動填入標題、適用範圍與內容。</p>
        <label>標題<input name="title" required></label>
        <label>摘要<textarea name="summary" rows="2"></textarea></label>
        <label>擁有單位<input name="owner_unit_id" value="IT Service Desk" required></label>
        <label>分類<input name="category"></label>
      </div>`;
  }
  if (step === 2) {
    const restricted = formValues.audience_type === "RESTRICTED_GROUPS";
    return `
      <div class="panel form-grid">
        <label>生效日<input name="effective_at" type="date" required></label>
        <label>下次檢視日<input name="review_due_at" type="date" required></label>
        <label class="full">變更原因<textarea name="change_reason" rows="2" required>${escapeHtml(formValues.change_reason || "新增知識文件")}</textarea></label>
        <label>適用對象
          <select name="audience_type" id="createAudienceType">
            <option value="ALL_EMPLOYEES" ${formValues.audience_type !== "RESTRICTED_GROUPS" ? "selected" : ""}>全體員工</option>
            <option value="RESTRICTED_GROUPS" ${formValues.audience_type === "RESTRICTED_GROUPS" ? "selected" : ""}>特定群組</option>
          </select>
        </label>
        <label class="full ${restricted ? "" : "hidden"}" id="createAudienceGroupsField">
          特定群組（逗號分隔，至少一個）
          <input name="audience_group_ids" value="${escapeHtml(formValues.audience_group_ids || "")}" ${restricted ? "required" : ""}>
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

function validateStepTwo(formValues) {
  if (!formValues.effective_at || !formValues.review_due_at || !formValues.change_reason?.trim()) {
    showToast("請完成治理與適用欄位", true);
    return false;
  }
  if (
    formValues.audience_type === "RESTRICTED_GROUPS"
    && !parseAudienceGroupIds(formValues.audience_group_ids).length
  ) {
    showToast("選擇特定群組時，請至少輸入一個群組", true);
    return false;
  }
  return true;
}

function buildCreatePayload(formValues) {
  const audienceGroupIds = parseAudienceGroupIds(formValues.audience_group_ids);
  return {
    title: formValues.title,
    summary: formValues.summary || "",
    category: formValues.category || "",
    owner_unit_id: formValues.owner_unit_id,
    business_contact: "",
    audience_type: formValues.audience_type || "ALL_EMPLOYEES",
    audience_group_ids: audienceGroupIds,
    effective_at: formValues.effective_at,
    review_due_at: formValues.review_due_at,
    change_summary: "Initial draft",
    change_reason: formValues.change_reason,
    markdown_content: formValues.markdown_content,
  };
}

export async function renderCreateView(app) {
  let currentStep = 1;
  const formValues = {
    audience_type: "ALL_EMPLOYEES",
    change_reason: "新增知識文件",
  };

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
          ${renderStepPanel(currentStep, formValues)}
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

    app.querySelector("#createAudienceType")?.addEventListener("change", (event) => {
      formValues.audience_type = event.target.value;
      Object.assign(formValues, Object.fromEntries(new FormData(form).entries()));
      render();
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
      if (currentStep === 2 && !validateStepTwo(formValues)) {
        return;
      }
      currentStep += 1;
      render();
    });

    app.querySelector("#importMarkdownFile")?.addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const filenameTitle = file.name.replace(/\.md$/i, "").trim();
      if (filenameTitle) {
        formValues.title = filenameTitle;
      }
      try {
        const formData = new FormData();
        formData.append("file", file);
        const imported = await apiForm("/api/documents/import-markdown", formData);
        Object.assign(formValues, {
          title: imported.title,
          owner_unit_id: imported.owner_unit_id,
          effective_at: imported.effective_at,
          review_due_at: imported.review_due_at,
          audience_type: imported.audience_type || "ALL_EMPLOYEES",
          audience_group_ids: (imported.audience_group_ids || []).join(", "),
          markdown_content: imported.markdown_content,
          change_reason: formValues.change_reason || "新增知識文件",
        });
        const warnings = [...(imported.warnings || [])];
        if (imported.audience_type === "RESTRICTED_GROUPS") {
          warnings.push("已保留匯入文件的特定群組設定。");
        }
        showToast(warnings.length ? warnings.join(" ") : "已匯入文件");
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
      if (!validateStepTwo(formValues)) {
        currentStep = 2;
        render();
        return;
      }
      try {
        const created = await api("/api/documents", {
          method: "POST",
          body: JSON.stringify(buildCreatePayload(formValues)),
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
