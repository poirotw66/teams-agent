import { api, apiForm } from "../api.js";
import { clearDirtyChecker, registerDirtyChecker } from "../dirty-state.js";
import { fluentButton } from "../fluent.js";
import { audienceLabel } from "../labels.js";
import { navigate } from "../router.js";
import { escapeHtml, openDialog, showToast } from "../ui.js?v=20260908a";
import { renderDocumentViewer, wireDocumentViewer } from "../markdown.js?v=pdf-img-20260908c";

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
    </ol>
    <p class="create-step-hint muted" role="status">
      ${currentStep < TOTAL_STEPS
    ? `步驟 ${currentStep}/${TOTAL_STEPS}：草稿尚未建立。請按「下一步」繼續；最後一步才會儲存。`
    : `步驟 ${currentStep}/${TOTAL_STEPS}：請確認摘要無誤後按「建立草稿」。建立後才可送審與發布。`}
    </p>`;
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
        ${formValues.markdown_content
          ? renderDocumentViewer({ content: formValues.markdown_content, compact: true, id: "createConfirmDocViewer" })
          : '<p class="muted">（空白）</p>'}
      </div>
    </div>`;
}

function applyImportedPdf(formValues, imported) {
  const result = imported?.result || imported;
  Object.assign(formValues, {
    title: result.title,
    owner_unit_id: result.owner_unit_id,
    effective_at: result.effective_at,
    review_due_at: result.review_due_at,
    audience_type: result.audience_type || "ALL_EMPLOYEES",
    audience_group_ids: (result.audience_group_ids || []).join(", "),
    markdown_content: result.markdown_content,
    change_reason: formValues.change_reason || "由 PDF 匯入新增知識文件",
    source_type: "PDF",
    conversion_mode: result.conversion_mode || "converter",
    conversion_engine: result.conversion_engine || "unknown",
    original_asset_token: result.original_asset_token || "",
    original_asset_name: result.original_asset_name || "",
    import_entry: "pdf",
  });
  formValues._pdfAssets = result.assets || [];
  return result;
}

async function pollPdfJob(jobId, onProgress) {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    const job = await api(`/api/documents/pdf-jobs/${encodeURIComponent(jobId)}`);
    if (job.status === "COMPLETED" && job.result) {
      return job.result;
    }
    if (job.status === "FAILED") {
      throw new Error(job.error || "PDF 轉換失敗");
    }
    const pct = Math.min(92, 18 + attempt * 2.2);
    const statusLabel = job.status === "QUEUED" ? "排隊中" : "轉換中";
    if (typeof onProgress === "function") {
      onProgress(pct, `${statusLabel}…（工作 ${job.jobId || jobId}，第 ${attempt + 1} 次查詢）`);
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error("PDF 轉換逾時，請稍後在發布前重試匯入。");
}

function createPdfProgressController(root) {
  const wrap = root.querySelector("#pdfImportProgress");
  const fill = root.querySelector("#pdfImportProgressFill");
  const meter = root.querySelector("#pdfImportProgressMeter");
  const label = root.querySelector("#pdfImportProgressLabel");
  const statusEl = root.querySelector("#pdfImportStatus");
  const fileInput = root.querySelector("#importPdfFile");
  let timer = null;
  let current = 0;

  function show() {
    wrap?.classList.remove("is-hidden");
    wrap?.setAttribute("aria-hidden", "false");
    if (fileInput) fileInput.disabled = true;
  }

  function set(percent, text) {
    current = Math.max(0, Math.min(100, Number(percent) || 0));
    const rounded = Math.round(current);
    if (fill) fill.style.width = `${current}%`;
    if (meter) meter.setAttribute("aria-valuenow", String(rounded));
    if (label) label.textContent = `${rounded}%`;
    if (typeof text === "string" && statusEl) statusEl.textContent = text;
  }

  function startSoftProgress({ from = 6, ceiling = 90, durationMs = 55000 } = {}) {
    show();
    set(from);
    const startedAt = Date.now();
    if (timer) clearInterval(timer);
    timer = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const t = Math.min(1, elapsed / durationMs);
      const eased = 1 - (1 - t) ** 2.4;
      set(from + (ceiling - from) * eased);
    }, 180);
  }

  function stopSoftProgress() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  async function complete(text) {
    stopSoftProgress();
    set(100, text);
    await new Promise((resolve) => setTimeout(resolve, 280));
  }

  function fail(text) {
    stopSoftProgress();
    wrap?.classList.add("is-error");
    set(current || 8, text);
    if (fileInput) fileInput.disabled = false;
  }

  function reset() {
    stopSoftProgress();
    wrap?.classList.add("is-hidden");
    wrap?.classList.remove("is-error");
    wrap?.setAttribute("aria-hidden", "true");
    set(0, "上傳後會呼叫 PDF Converter；大檔會自動改背景工作並輪詢。");
    if (fileInput) fileInput.disabled = false;
  }

  return { show, set, startSoftProgress, stopSoftProgress, complete, fail, reset };
}

function renderImportBanner(formValues) {
  if (formValues.import_entry !== "pdf" || !formValues.markdown_content) return "";
  const engine = formValues.conversion_engine || "";
  let modeLabel = "本機文字抽取（未連上 Converter 時的後備）";
  if (formValues.conversion_mode === "converter") {
    modeLabel =
      engine === "gemini_vision"
        ? "上游 PDF Converter（PyMuPDF + Gemini Vision）"
        : engine === "legacy_text"
          ? "PDF Converter 服務（文字抽取模式）"
          : "PDF Converter 服務";
  }
  const preview = (formValues.markdown_content || "").trim();
  const short = preview.length > 220 ? `${preview.slice(0, 220)}…` : preview;
  return `
    <div class="create-import-banner panel">
      <p><strong>已從 PDF 轉換完成</strong>（${escapeHtml(modeLabel)}）</p>
      <p class="muted">請繼續填寫治理資訊，確認正文後建立草稿。發布後才會進入 Bot 知識索引。</p>
      <pre class="create-import-preview">${escapeHtml(short)}</pre>
    </div>`;
}

function renderStepPanel(step, formValues) {
  if (step === 1) {
    const entry = formValues.import_entry || "manual";
    return `
      <div class="panel">
        <p class="muted">先選擇建立方式。若選 PDF，會呼叫內部 PDF Converter 轉成 Markdown 草稿。</p>
        <div class="create-entry-grid" role="radiogroup" aria-label="建立方式">
          <label class="create-entry-card ${entry === "manual" ? "active" : ""}">
            <input type="radio" name="import_entry" value="manual" ${entry === "manual" ? "checked" : ""}>
            <strong>手動撰寫</strong>
            <span class="muted">直接填標題與正文</span>
          </label>
          <label class="create-entry-card ${entry === "pdf" ? "active" : ""}">
            <input type="radio" name="import_entry" value="pdf" ${entry === "pdf" ? "checked" : ""}>
            <strong>從 PDF 匯入</strong>
            <span class="muted">經 PDF Converter → Markdown 草稿</span>
          </label>
          <label class="create-entry-card ${entry === "markdown" ? "active" : ""}">
            <input type="radio" name="import_entry" value="markdown" ${entry === "markdown" ? "checked" : ""}>
            <strong>從 Markdown 匯入</strong>
            <span class="muted">上傳 .md 後自動帶入欄位</span>
          </label>
        </div>
        ${entry === "pdf" ? `
          <div class="create-import-box">
            <label class="full">
              選擇 PDF 檔案
              <input id="importPdfFile" type="file" accept=".pdf,application/pdf">
            </label>
            <div id="pdfImportProgress" class="pdf-import-progress is-hidden" aria-hidden="true">
              <div class="pdf-import-progress__meta">
                <span>轉換進度</span>
                <span id="pdfImportProgressLabel">0%</span>
              </div>
              <div
                id="pdfImportProgressMeter"
                class="pdf-import-progress__track"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow="0"
                aria-labelledby="pdfImportStatus"
              >
                <div id="pdfImportProgressFill" class="pdf-import-progress__fill"></div>
              </div>
            </div>
            <p class="muted" id="pdfImportStatus">上傳後會呼叫 PDF Converter；大檔會自動改背景工作並輪詢。</p>
          </div>` : ""}
        ${entry === "markdown" ? `
          <div class="create-import-box">
            <label class="full">
              選擇 Markdown 檔案
              <input id="importMarkdownFile" type="file" accept=".md,text/markdown">
            </label>
          </div>` : ""}
        ${renderImportBanner(formValues)}
        <div class="form-grid" style="margin-top:1rem">
          <label>標題<input name="title" required value="${escapeHtml(formValues.title || "")}"></label>
          <label>摘要<textarea name="summary" rows="2">${escapeHtml(formValues.summary || "")}</textarea></label>
          <label>擁有單位<input name="owner_unit_id" value="${escapeHtml(formValues.owner_unit_id || "IT Service Desk")}" required></label>
          <label>分類<input name="category" value="${escapeHtml(formValues.category || "")}"></label>
        </div>
      </div>`;
  }
  if (step === 2) {
    const restricted = formValues.audience_type === "RESTRICTED_GROUPS";
    return `
      <div class="panel form-grid">
        ${renderImportBanner(formValues)}
        <p class="muted full">請填妥日期與變更原因；缺欄時會提示具體欄位名稱。</p>
        <label>生效日<input name="effective_at" type="date" required value="${escapeHtml(formValues.effective_at || "")}"></label>
        <label>下次檢視日<input name="review_due_at" type="date" required value="${escapeHtml(formValues.review_due_at || "")}"></label>
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
        ${renderImportBanner(formValues)}
        <label class="full">正文內容
          <textarea name="markdown_content" rows="14" required>${escapeHtml(formValues.markdown_content || `# 範例標題

## 正文

請在此撰寫知識內容。`)}</textarea>
        </label>
      </div>`;
  }
  return renderConfirmPanel(formValues);
}

function validateStepTwo(formValues) {
  const missing = [];
  if (!formValues.effective_at) missing.push("生效日");
  if (!formValues.review_due_at) missing.push("下次檢視日");
  if (!formValues.change_reason?.trim()) missing.push("變更原因");
  if (missing.length) {
    showToast(`請先填寫：${missing.join("、")}`, true);
    return false;
  }
  if (
    formValues.audience_type === "RESTRICTED_GROUPS"
    && !parseAudienceGroupIds(formValues.audience_group_ids).length
  ) {
    showToast("適用對象為特定群組時，請至少輸入一個群組 ID", true);
    return false;
  }
  return true;
}

function validateStepThree(formValues) {
  const body = (formValues.markdown_content || "").trim();
  if (!body) {
    showToast("請先填寫「正文內容」後再按下一步", true);
    return false;
  }
  const defaultTemplate = "# 範例標題\n\n## 正文\n\n請在此撰寫知識內容。";
  if (body === defaultTemplate) {
    showToast("請將範例正文改成實際內容後再繼續", true);
    return false;
  }
  return true;
}

function buildCreatePayload(formValues) {
  const audienceGroupIds = parseAudienceGroupIds(formValues.audience_group_ids);
  const assets = (formValues._pdfAssets || [])
    .map((item) => ({
      filename: item.filename || item.name,
      content_base64: item.content_base64 || item.contentBase64 || "",
    }))
    .filter((item) => item.filename && item.content_base64);
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
    change_summary: formValues.import_entry === "pdf" ? "Initial draft from PDF" : "Initial draft",
    change_reason: formValues.change_reason,
    markdown_content: formValues.markdown_content,
    source_type: formValues.source_type || (formValues.import_entry === "markdown" ? "MARKDOWN_UPLOAD" : "MARKDOWN_PASTE"),
    assets,
    original_asset_token: formValues.original_asset_token || null,
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
  const payload = buildCreatePayload(formValues);
  if (
    formValues.import_entry === "pdf"
    && /!\[[^\]]*\]\((?:assets\/)?[^)]+\.(?:png|jpe?g|gif)\)/i.test(payload.markdown_content || "")
    && !(payload.assets || []).length
  ) {
    showToast("PDF 轉換結果含圖片，但未取得圖檔資產；請重新匯入 PDF 後再建立草稿。", true);
    return;
  }
  const idempotencyKey = getOrCreateSubmissionKey();
  const created = await api("/api/documents", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(payload),
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
    import_entry: "pdf",
  };

  function render() {
    const isConfirmStep = currentStep === TOTAL_STEPS;
    app.innerHTML = `
      <section class="page">
        <header class="page-header">
          <div>
            <h2>新增知識文件</h2>
            <p class="muted">建議：內部 SOP／手冊用「從 PDF 匯入」；短文可用手動撰寫。此流程完成前不會儲存草稿。</p>
          </div>
          ${fluentButton("返回列表", { appearance: "outline", dataset: { back: "true" } })}
        </header>
        ${renderStepHeader(currentStep)}
        <form id="createForm">
          ${renderStepPanel(currentStep, formValues)}
          <div class="form-actions create-form-actions">
            ${currentStep > 1 ? fluentButton("上一步", { appearance: "outline", dataset: { prev: "true" } }) : ""}
            ${!isConfirmStep
    ? fluentButton("下一步（尚未儲存）", { appearance: "accent", dataset: { next: "true" } })
    : fluentButton("建立草稿", { appearance: "accent", type: "submit" })}
          </div>
        </form>
      </section>`;

    app.querySelector("[data-back]")?.addEventListener("click", () => navigate("#/knowledge"));
    const form = app.querySelector("#createForm");
    Object.entries(formValues).forEach(([key, value]) => {
      if (key.startsWith("_")) return;
      if (form[key] && typeof value === "string") form[key].value = value;
    });

    form.querySelectorAll('input[name="import_entry"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        formValues.import_entry = radio.value;
        if (radio.value !== "pdf") {
          formValues.conversion_mode = undefined;
        }
        render();
      });
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
        showToast("請先填寫標題（或先匯入 PDF／Markdown）", true);
        return;
      }
      if (currentStep === 1 && formValues.import_entry === "pdf" && !formValues.markdown_content?.trim()) {
        showToast("請先選擇 PDF 並完成轉換，再按下一步", true);
        return;
      }
      if (currentStep === 2 && !validateStepTwo(formValues)) {
        return;
      }
      if (currentStep === 3 && !validateStepThree(formValues)) {
        return;
      }
      if (currentStep === 1) {
        const today = new Date();
        const iso = (d) => d.toISOString().slice(0, 10);
        if (!formValues.effective_at) formValues.effective_at = iso(today);
        if (!formValues.review_due_at) {
          const review = new Date(today);
          review.setDate(review.getDate() + 180);
          formValues.review_due_at = iso(review);
        }
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
          source_type: "MARKDOWN_UPLOAD",
          import_entry: "markdown",
        });
        const warnings = [...(imported.warnings || [])];
        if (imported.audience_type === "RESTRICTED_GROUPS") {
          warnings.push("已保留匯入文件的特定群組設定。");
        }
        showToast(warnings.length ? warnings.join(" ") : "已匯入文件");
        currentStep = 2;
        render();
      } catch (error) {
        showToast(error.message, true);
      } finally {
        event.target.value = "";
      }
    });

    app.querySelector("#importPdfFile")?.addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const progress = createPdfProgressController(app);
      const filenameTitle = file.name.replace(/\.pdf$/i, "").trim();
      if (filenameTitle) {
        formValues.title = filenameTitle;
      }
      try {
        progress.startSoftProgress({ from: 4, ceiling: 88, durationMs: 60000 });
        progress.set(6, `正在上傳「${file.name}」…`);
        const formData = new FormData();
        formData.append("file", file);
        let imported = await apiForm("/api/documents/import-pdf?async_mode=auto", formData);
        if (imported?.mode === "async" && imported.jobId) {
          progress.stopSoftProgress();
          progress.set(16, `已進入背景轉換（${imported.jobId}）…`);
          imported = await pollPdfJob(imported.jobId, (pct, text) => progress.set(pct, text));
        } else {
          progress.set(92, "正在整理轉換結果…");
        }
        applyImportedPdf(formValues, imported);
        const assetCount = (formValues._pdfAssets || []).length;
        const mode =
          formValues.conversion_engine === "gemini_vision"
            ? "Gemini Vision"
            : formValues.conversion_mode === "converter"
              ? "PDF Converter"
              : "後備文字抽取";
        const warnings = [...(imported.warnings || [])];
        if (assetCount) {
          warnings.push(`已附帶 ${assetCount} 張圖片資產，建立草稿時會一併上傳。`);
        } else if (/!\[[^\]]*\]\([^)]+\.(?:png|jpe?g|gif)\)/i.test(formValues.markdown_content || "")) {
          warnings.push("正文含圖片引用，但轉換結果未附圖檔；建立草稿前請確認。");
        }
        await progress.complete(`轉換完成（${mode}${assetCount ? `，${assetCount} 張圖` : ""}）`);
        showToast(warnings.length ? warnings.join(" ") : `已透過 ${mode} 匯入 PDF`);
        currentStep = 2;
        render();
      } catch (error) {
        progress.fail(error.message || "PDF 轉換失敗");
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
            showCancel: false,
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
      wireDocumentViewer(app, { inlineAssets: formValues._pdfAssets || [] });
    }
  }

  render();
}
