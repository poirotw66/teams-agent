import { api, apiForm } from "../api.js";
import { clearDirtyChecker, registerDirtyChecker } from "../dirty-state.js";
import { fluentButton } from "../fluent.js";
import { audienceLabel } from "../labels.js";
import { navigate } from "../router.js";
import { escapeHtml, openDialog, showToast } from "../ui.js?v=20260831e";

const STEPS = [
  { id: 1, label: "基本資料" },
  { id: 2, label: "治理與適用" },
  { id: 3, label: "正文內容" },
  { id: 4, label: "確認摘要" },
];

const TOTAL_STEPS = STEPS.length;

function parseAudienceGroupIds(value) {
  return (value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

let createBaseline = null;

function readCreateFormSnapshot() {
  const form = document.getElementById("createForm");
  if (!form) return "";
  return JSON.stringify(Object.fromEntries(new FormData(form).entries()));
}

function syncCreateDirtyGuard() {
  registerDirtyChecker(() => createBaseline !== null && readCreateFormSnapshot() !== createBaseline);
}

function renderStepHeader(currentStep) {
  return `
    <ol class="create-steps create-steps--four" aria-label="建立步驟">
      ${STEPS.map((step) => `
        <li class="create-step ${step.id === currentStep ? "active" : ""}"${step.id === currentStep ? ' aria-current="step"' : ""}>
          步驟 ${step.id} · ${step.label}
        </li>`).join("")}
    </ol>`;
}

function renderConfirmPanel(formValues) {
  const groupIds = parseAudienceGroupIds(formValues.audience_group_ids);
  const audience = audienceLabel(formValues.audience_type || "ALL_EMPLOYEES", groupIds);
  const bodyPreview = (formValues.markdown_content || "").trim();
  const previewText = bodyPreview.length > 280 ? `${bodyPreview.slice(0, 280)}...` : bodyPreview;

  return `
    <div class="panel confirm-summary">
      <p class="muted">請確認以下資訊無誤，再建立草稿。建立後仍可繼續編輯。</p>
      <dl class="meta-list confirm-meta">
        <div><dt>標題</dt><dd>${escapeHtml(formValues.title || "")}</dd></div>
        <div><dt>擁有單位</dt><dd>${escapeHtml(formValues.owner_unit_id || "")}</dd></div>
        <div><dt>分類</dt><dd>${escapeHtml(formValues.category || "未分類")}</dd></div>
        <div><dt>摘要</dt><dd>${escapeHtml(formValues.summary || "未填")}</dd></div>
        <div><dt>生效日</dt><dd>${escapeHtml(formValues.effective_at || "")}</dd></div>
        <div><dt>下次檢視日</dt><dd>${escapeHtml(formValues.review_due_at || "")}</dd></div>
        <div><dt>適用對象</dt><dd>${escapeHtml(audience)}</dd></div>
        <div><dt>變更原因</dt><dd>${escapeHtml(formValues.change_reason || "")}</dd></div>
      </dl>
      <div class="confirm-preview">
        <h3>正文預覽</h3>
        <pre class="content-preview">${escapeHtml(previewText || "（空白）")}</pre>
      </div>
    </div>`;
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
  if (step === 3) {
    return `
      <div class="panel">
        <label class="full">正文內容
          <textarea name="markdown_content" rows="14" required># 範例標題

## 正文

請在此撰寫知識內容。</textarea>
        </label>
      </div>`;
  }
  return renderConfirmPanel(formValues);
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

function validateStepThree(formValues) {
  if (!formValues.markdown_content?.trim()) {
    showToast("請填寫正文內容", true);
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

let currentSubmissionKey = null;

function getOrCreateSubmissionKey() {
  if (!currentSubmissionKey) {
    currentSubmissionKey = "create-" + Date.now() + "-" + Math.random().toString(36).substring(2, 9);
  }
  return currentSubmissionKey;
}

function resetSubmissionKey() {
  currentSubmissionKey = null;
}

async function submitCreate(formValues) {
  const idempotencyKey = getOrCreateSubmissionKey();
  const created = await api("/api/documents", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(buildCreatePayload(formValues)),
  });
  resetSubmissionKey();
  showToast("草稿已建立");
  clearDirtyChecker();
  createBaseline = null;
  navigate(`#/knowledge/${created.document.document_id}/content`);
}

export async function renderCreateView(app) {
  clearDirtyChecker();
  createBaseline = null;
  resetSubmissionKey();
  let currentStep = 1;
  const formValues = {
    audience_type: "ALL_EMPLOYEES",
    change_reason: "新增知識文件",
  };

  function render() {
    const isConfirmStep = currentStep === TOTAL_STEPS;
    app.innerHTML = `
      <section class="page">
        <header class="page-header">
          <div>
            <h2>新增知識文件</h2>
          </div>
          ${fluentButton("返回列表", { appearance: "outline", dataset: { back: "true" } })}
        </header>
        ${renderStepHeader(currentStep)}
        <form id="createForm">
          ${renderStepPanel(currentStep, formValues)}
          <div class="form-actions">
            ${currentStep > 1 ? fluentButton("上一步", { appearance: "outline", dataset: { prev: "true" } }) : ""}
            ${!isConfirmStep
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
      if (!isConfirmStep) {
        Object.assign(formValues, Object.fromEntries(new FormData(form).entries()));
      }
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
      if (currentStep === 3 && !validateStepThree(formValues)) {
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
      if (!isConfirmStep) return;
      if (!validateStepTwo(formValues) || !validateStepThree(formValues)) {
        currentStep = validateStepThree(formValues) ? 2 : 3;
        render();
        return;
      }
      try {
        await submitCreate(formValues);
      } catch (error) {
        if (error.issues && Array.isArray(error.issues) && error.issues.length > 0) {
          const listHtml = error.issues
            .map((issue) => {
              const fieldPrefix = issue.field ? `<strong>[${escapeHtml(issue.field)}]</strong> ` : "";
              const msg = escapeHtml(issue.message || issue.msg || issue.code || "驗證問題");
              const sev = issue.severity ? ` <small class="text-muted">(${escapeHtml(issue.severity)})</small>` : "";
              return `<li>${fieldPrefix}${msg}${sev}</li>`;
            })
            .join("");
          await openDialog({
            title: "建立文件未通過驗證",
            bodyHtml: `<p>${escapeHtml(error.message)}</p><ul class="issue-list" style="margin:8px 0;padding-left:20px;text-align:left;">${listHtml}</ul>`,
            confirmLabel: "關閉",
          });
          return;
        }
        showToast(error.message, true);
      }
    });

    if (!isConfirmStep) {
      createBaseline = readCreateFormSnapshot();
      syncCreateDirtyGuard();
      form.addEventListener("input", syncCreateDirtyGuard);
      form.addEventListener("change", syncCreateDirtyGuard);
    } else {
      clearDirtyChecker();
      createBaseline = null;
    }
  }

  render();
}
