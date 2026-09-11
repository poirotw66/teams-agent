import { api, el, metric } from "../api.js";
import { showContentModal, closeContentModal, showTextPrompt } from "../components/modal.js";
import { showConversationModal } from "../components/conversationModal.js";
import { buildFaqForm, faqPayload } from "../components/faqForms.js";
import {
  renderContentPolicyBanner,
  renderDecisionGuide,
} from "../components/contentGuide.js";
import { runExport } from "../services/export.js";
import { actorCapabilities, canUseKnowledgeUi, getCapabilities } from "../app/capabilities.js";
import {
  buildLocationHash,
  drillLink,
  loadNavFilters,
  navigateTo,
} from "../app/navigation.js";
import { renderNativeKnowledgePortal } from "../knowledge_portal_view.js?v=least-priv-20260910a";
import { createPageController } from "../app/lifecycle.js";
import { presentAnalyticsPage } from "../app/analyticsChrome.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";


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

  // Source references used to land on a minimal summary page. That page only
  // exposed the lifecycle value and could not answer T3's key question:
  // whether approval, publication, indexing, and Agent consumption had each
  // completed. Reuse the canonical portal detail view so every entry point
  // shows the same lifecycle strip, version evidence, content, and allowed
  // actions. Preserve caseId so a document opened from a quality case can
  // still return directly to that case.
  await renderNativeKnowledgePortal(app, getCapabilities(), navigateTo, {
    ...filters,
    sub: `knowledge/${documentId}`,
  });
}

async function renderKnowledge() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  if (!isBuShellEnabled()) {
    panel.append(el("h2", "", "內容成效"));
  }
  panel.append(renderContentPolicyBanner());
  if (getCapabilities()?.knowledgeBridgeEnabled) {
    panel.append(
      el(
        "p",
        "",
        "查看文件使用情況與回答成效；編輯內容請前往知識內容。",
      ),
    );
    const openPortal = el("a", "button-link", isBuShellEnabled() ? "開啟知識內容" : "開啟知識文件庫");
    openPortal.href = buildLocationHash(
      "knowledge_ops",
      isBuShellEnabled() ? "contentLists" : "knowledgePortal",
    );
    openPortal.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
        return;
      }
      event.preventDefault();
      navigateTo(isBuShellEnabled() ? "contentLists" : "knowledgePortal");
    });
    openPortal.style.marginRight = "0.5rem";
    panel.append(openPortal);
  } else {
    panel.append(
      el(
        "p",
        "",
        "文件維護、審核、發布與測試仍由 Knowledge Portal 提供。下方可查看文件成效。",
      ),
    );
    const link = el("a", "button-link", "開啟 Knowledge Portal");
    link.href = getCapabilities()?.knowledgePortalUrl || "http://127.0.0.1:8091";
    link.target = "_blank";
    panel.append(link);
  }
  const exportButton = el("button", "", "匯出 CSV");
  exportButton.style.marginLeft = "0.5rem";
  panel.append(exportButton);

  const filters = el("form", "filter-bar knowledge-filters");
  filters.style.marginTop = "1rem";
  const query = el("input");
  query.style.minWidth = "220px";
  query.placeholder = "搜尋標題或文件 ID";
  query.setAttribute("aria-label", "搜尋知識文件");
  const owner = el("input");
  owner.placeholder = "Owner";
  owner.setAttribute("aria-label", "Owner");
  const status = el("select");
  status.setAttribute("aria-label", "生命週期狀態");
  for (const [value, label] of [
    ["", "所有狀態"],
    ["DRAFT", "草稿"],
    ["IN_REVIEW", "審核中"],
    ["APPROVED", "已核准"],
    ["PUBLISHED", "已發布"],
    ["ARCHIVED", "已封存"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    status.append(option);
  }
  const formatType = el("select");
  formatType.setAttribute("aria-label", "文件格式");
  for (const [value, label] of [
    ["", "所有格式"],
    ["MARKDOWN", "Markdown"],
    ["PDF", "PDF"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    formatType.append(option);
  }
  const period = el("select");
  period.setAttribute("aria-label", "績效期間");
  for (const [value, label] of [
    ["30", "最近 30 天"],
    ["7", "最近 7 天"],
    ["186", "最近 6 個月"],
    ["365", "最近 1 年"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    period.append(option);
  }
  const submit = el("button", "", "套用篩選");
  submit.type = "submit";
  filters.append(query, owner, status, formatType, period, submit);
  const result = el("div", "");
  panel.append(filters, result);
  if (isBuShellEnabled()) {
    presentAnalyticsPage(
      "knowledge",
      "內容成效",
      "看哪些文件與 FAQ 真的被用到，再回頭修正內容。",
      panel,
    );
  } else {
    const view = loadNavFilters().view;
    if (!view || view === "knowledge") {
      app.replaceChildren(panel);
    }
  }

  async function loadDocuments(cursor = "") {
    result.replaceChildren(el("p", "empty", "載入中…"));
    try {
      const params = new URLSearchParams({
        days: period.value || "30",
        limit: "50",
      });
      if (query.value.trim()) params.set("query", query.value.trim());
      if (owner.value.trim()) params.set("owner_unit_id", owner.value.trim());
      if (status.value) params.set("status", status.value);
      if (formatType.value) params.set("format_type", formatType.value);
      if (cursor) params.set("cursor", cursor);
      const data = await api(`/api/knowledge?${params.toString()}`);
      result.replaceChildren(
        renderKnowledgeInventory(data, loadDocuments, {
          days: period.value || "30",
        }),
      );
    } catch (error) {
      result.replaceChildren(el("div", "error", error.message));
    }
  }

  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    loadDocuments();
  });
  exportButton.addEventListener("click", async () => {
    exportButton.disabled = true;
    exportButton.textContent = "匯出中…";
    try {
      const activeFilters = {};
      if (query.value.trim()) activeFilters.query = query.value.trim();
      if (owner.value.trim()) activeFilters.owner_unit_id = owner.value.trim();
      if (status.value) activeFilters.status = status.value;
      if (formatType.value) activeFilters.format_type = formatType.value;
      const selectedDays = parseInt(period.value, 10) || 30;
      await runExport("csv", "knowledge_performance", selectedDays, activeFilters);
    } catch (error) {
      result.prepend(el("div", "error", error.message));
    } finally {
      exportButton.disabled = false;
      exportButton.textContent = "匯出 CSV";
    }
  });
  await loadDocuments();
}

async function showSyncDetail(jobId, panel) {
  try {
    const detail = await api(`/api/sync-jobs/${encodeURIComponent(jobId)}`);
    const job = detail.job;
    const allowed = actorCapabilities();
    const content = el("div");
    content.append(
      el("p", "", `${job.status}｜階段 ${job.current_stage}｜進度 ${job.progress_percent}%｜ETag ${job.etag}`),
      el("p", "", `範圍：${job.scope_type} ${job.scope_ids.join(", ") || "全部"}`),
      el("p", "", `文件數：${job.document_count}｜Target release：${job.target_release || "未切換"}`),
      el("p", "", `Checkpoint：${job.checkpoint_stage || "-"}｜Retry checkpoint：${job.retry_checkpoint_stage || "-"}`),
    );
    if (job.error_summary) content.append(el("div", "error", job.error_summary));
    if (job.warnings.length) content.append(el("p", "warning", job.warnings.join("；")));
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.sync.write") && ["FAILED", "CANCELLED"].includes(job.status)) {
      const retry = el("button", "", "重試");
      retry.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: "重試同步工作",
          message: "請輸入重試原因。",
          required: true,
        });
        if (reason == null) return;
        await api(`/api/sync-jobs/${jobId}/retry`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify({ reason: reason.trim() }),
        });
        await renderSyncManagement(panel);
      });
      actions.append(retry);
    }
    if (allowed.has("ops.sync.write") && ["QUEUED", "VALIDATING", "BUILDING", "VERIFYING"].includes(job.status)) {
      const cancel = el("button", "", "取消");
      cancel.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: "取消同步工作",
          message: "請輸入取消原因。",
          required: true,
        });
        if (reason == null) return;
        await api(`/api/sync-jobs/${jobId}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: reason.trim(), expected_etag: job.etag }),
        });
        await renderSyncManagement(panel);
      });
      actions.append(cancel);
    }
    content.append(actions, el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) {
      content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    }
    showContentModal(`Sync Job ${job.job_id}`, content);
  } catch (error) {
    showContentModal("Sync Job", el("div", "error", error.message));
  }
}

async function renderSyncManagement(panel) {
  panel.replaceChildren(el("h2", "", "同步工作"), el("p", "empty", "載入中…"));
  const allowed = actorCapabilities();
  try {
    const data = await api("/api/sync-jobs");
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.sync.write")) {
      const create = el("button", "", "建立同步工作");
      create.addEventListener("click", () => {
        showCreateSyncModal(async () => {
          await renderSyncManagement(panel);
        });
      });
      actions.append(create);
    }
    const result = el("div");
    if (!(data.items || []).length) {
      result.append(el("p", "empty", "目前沒有 Sync Job。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>時間</th><th>範圍</th><th>狀態</th><th>進度</th><th>錯誤 / 警告</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const job of data.items) {
        const action = el("td");
        const detail = el("button", "", "查看");
        detail.addEventListener("click", () => showSyncDetail(job.job_id, panel));
        action.append(detail);
        const progress = `${job.progress_percent}% / ${job.checkpoint_stage || "尚無 checkpoint"}`;
        const row = el("tr");
        row.append(
          el("td", "", job.requested_at),
          el("td", "", `${job.scope_type} ${job.scope_ids.join(", ")}`),
          el("td", "", job.status),
          el("td", "", progress),
          el("td", "", job.error_summary || job.warnings.join("；") || "-"),
          action,
        );
        body.append(row);
      }
      table.append(body);
      const scrollWrapper = el("div", "table-responsive");
      scrollWrapper.append(table);
      result.append(scrollWrapper);
    }
    panel.replaceChildren(el("h2", "", "同步工作"), actions, result);
  } catch (error) {
    panel.replaceChildren(el("h2", "", "同步工作"), el("div", "error", error.message));
  }
}

function showCreateSyncModal(onCreated) {
  const form = el("form", "panel");
  form.style.marginTop = "0";

  const scopeField = el("div", "field");
  scopeField.append(el("label", "", "同步範圍"));
  const scopeSelect = el("select");
  for (const [val, label] of [
    ["ALL", "全部知識庫 (ALL)"],
    ["FAQ", "指定 FAQ (FAQ)"],
    ["DOCUMENT", "指定文件 (DOCUMENT)"],
  ]) {
    const opt = el("option", "", label);
    opt.value = val;
    scopeSelect.append(opt);
  }
  scopeField.append(scopeSelect);

  const idField = el("div", "field");
  idField.style.display = "none";
  idField.style.marginTop = "0.75rem";
  const idLabel = el("label", "", "範圍識別碼（多筆以逗號分隔）");
  const idInput = el("input");
  idInput.placeholder = "例如：faq-001, faq-002";
  idField.append(idLabel, idInput);

  scopeSelect.addEventListener("change", () => {
    if (scopeSelect.value === "ALL") {
      idField.style.display = "none";
    } else {
      idField.style.display = "block";
      idLabel.textContent = scopeSelect.value === "FAQ"
        ? "FAQ ID 清單（多筆以逗號分隔）"
        : "文件 ID 清單（多筆以逗號分隔）";
      idInput.placeholder = scopeSelect.value === "FAQ"
        ? "例如：faq-001, faq-002"
        : "例如：doc-101, doc-102";
    }
  });

  const reasonField = el("div", "field");
  reasonField.style.marginTop = "0.75rem";
  reasonField.append(el("label", "", "同步原因（至少 3 字元）"));
  const reasonInput = el("input");
  reasonInput.placeholder = "請輸入同步原因，將記錄於 Audit Log";
  reasonInput.required = true;
  reasonField.append(reasonInput);

  const errorBox = el("div", "error");
  errorBox.style.display = "none";
  errorBox.style.marginTop = "0.75rem";

  const actions = el("div", "filter-bar");
  actions.style.marginTop = "1.25rem";
  const submitBtn = el("button", "", "開始同步");
  submitBtn.type = "submit";
  const cancelBtn = el("button", "", "取消");
  cancelBtn.type = "button";
  cancelBtn.addEventListener("click", () => closeContentModal());
  actions.append(submitBtn, cancelBtn);

  form.append(scopeField, idField, reasonField, errorBox, actions);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorBox.style.display = "none";

    const reason = reasonInput.value.trim();
    if (reason.length < 3) {
      errorBox.textContent = "同步原因至少需 3 個字元。";
      errorBox.style.display = "block";
      return;
    }

    const scopeType = scopeSelect.value;
    let scopeIds = [];
    if (scopeType !== "ALL") {
      scopeIds = idInput.value
        .split(/[,，\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (!scopeIds.length) {
        errorBox.textContent = `請填寫欲同步的 ${scopeType === "FAQ" ? "FAQ" : "文件"} ID。`;
        errorBox.style.display = "block";
        return;
      }
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "送出中…";
    try {
      await api("/api/sync-jobs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          scope_type: scopeType,
          scope_ids: scopeIds,
          reason,
        }),
      });
      closeContentModal();
      if (onCreated) await onCreated();
    } catch (err) {
      errorBox.textContent = err.message || "建立同步工作失敗";
      errorBox.style.display = "block";
      submitBtn.disabled = false;
      submitBtn.textContent = "開始同步";
    }
  });

  showContentModal("建立知識同步工作", form);
}

export async function renderFaqManagement(panel) {
  panel.replaceChildren(el("h2", "", "FAQ 管理"), el("p", "empty", "載入中…"));
  const allowed = actorCapabilities();
  if (!allowed.has("ops.faq.read")) {
    panel.replaceChildren(el("h2", "", "FAQ 管理"), el("div", "forbidden", "FORBIDDEN"));
    return;
  }
  try {
    const navFilters = loadNavFilters();
    const heading = el("h2", "", "FAQ 管理");
    const policy = renderContentPolicyBanner();
    const decision = renderDecisionGuide();
    let governedNote = null;
    if (isBuShellEnabled()) {
      governedNote = el("details", "bu-ops-note");
      governedNote.append(el("summary", "", "正式環境注意事項"));
      governedNote.append(
        el(
          "p",
          "metric-label",
          "正式環境請將 Agent 設為 FAQ_RUNTIME_MODE=GOVERNED。啟用後會落檔至 FAQ artifact 目錄（稽核用，不進 RAG）。",
        ),
      );
    } else {
      governedNote = el(
        "p",
        "metric-label",
        "正式環境請將 Agent 設為 FAQ_RUNTIME_MODE=GOVERNED。啟用後會落檔至 FAQ artifact 目錄（稽核用，不進 RAG）。",
      );
    }
    const actions = el("div", "filter-bar");
    const query = el("input");
    query.placeholder = "搜尋 FAQ Key 或問題";
    query.setAttribute("aria-label", "搜尋 FAQ Key 或問題");
    query.value = (navFilters.query || navFilters.faqId || "").trim();
    const category = el("input");
    category.placeholder = "分類";
    category.setAttribute("aria-label", "分類");
    const keyword = el("input");
    keyword.placeholder = "關鍵字";
    keyword.setAttribute("aria-label", "關鍵字");
    const owner = el("input");
    owner.placeholder = "Owner";
    owner.setAttribute("aria-label", "Owner");
    const status = el("select");
    status.setAttribute("aria-label", "狀態");
    status.innerHTML = `
      <option value="">全部狀態</option>
      <option value="DRAFT">草稿</option>
      <option value="IN_REVIEW">審核中</option>
      <option value="CHANGES_REQUESTED">需修改</option>
      <option value="APPROVED">已核准</option>
      <option value="ACTIVE">啟用中</option>
      <option value="DISABLED">已停用</option>
    `;
    const result = el("div");
    const load = async () => {
      const params = new URLSearchParams();
      if (query.value.trim()) params.set("query", query.value.trim());
      if (category.value.trim()) params.set("category", category.value.trim());
      if (keyword.value.trim()) params.set("keyword", keyword.value.trim());
      if (owner.value.trim()) params.set("owner_unit_id", owner.value.trim());
      if (status.value) params.set("status", status.value);
      const data = await api(`/api/faqs?${params}`);
      result.replaceChildren();
      summary.textContent = `共 ${data.total || 0} 筆`;
      if (!(data.items || []).length) {
        result.append(el("p", "empty", "沒有符合條件的 FAQ。"));
        return;
      }
      const table = el("table");
      table.innerHTML =
        "<thead><tr><th>FAQ</th><th>分類</th><th>關鍵字</th><th>狀態</th><th>Owner</th><th>版本</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const row = el("tr");
        const name = el("td");
        name.append(
          el("strong", "", item.version.content.question),
          el("div", "metric-label", item.faq.faq_key),
        );
        const faqStatusLabels = {
          DRAFT: "草稿",
          IN_REVIEW: "審核中",
          CHANGES_REQUESTED: "需修改",
          APPROVED: "已核准",
          ACTIVE: "啟用中",
          DISABLED: "已停用",
        };
        const action = el("td");
        const detail = el("button", isBuShellEnabled() ? "button-primary" : "", "查看與處理");
        detail.addEventListener("click", () => showFaqDetail(item.faq.faq_id, panel));
        action.append(detail);
        row.append(
          name,
          el("td", "", item.version.content.category || "-"),
          el("td", "", (item.version.content.keywords || []).join(", ") || "-"),
          el("td", "", faqStatusLabels[item.faq.status] || item.faq.status),
          el("td", "", item.version.content.owner_unit_id),
          el("td", "", `v${item.version.version_number}`),
          action,
        );
        body.append(row);
      }
      table.append(body);
      const scrollWrapper = el("div", "table-responsive");
      scrollWrapper.append(table);
      result.append(scrollWrapper);
    };
    const searchButton = el("button", "", "套用篩選");
    searchButton.addEventListener("click", load);
    for (const input of [query, category, keyword, owner]) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") load();
      });
    }
    if (allowed.has("ops.faq.write")) {
      const createButton = el("button", isBuShellEnabled() ? "button-primary" : "", "新增 FAQ");
      createButton.addEventListener("click", () => showFaqCreateModal(panel));
      actions.append(createButton);
    }
    const summary = el("span", "metric-label", "");
    actions.append(query, category, keyword, owner, status, searchButton, summary);
    panel.replaceChildren(heading, policy, decision, governedNote, actions, result);
    await load();
    if (navFilters.faqId) {
      await showFaqDetail(String(navFilters.faqId), panel);
    }
  } catch (error) {
    panel.replaceChildren(el("h2", "", "FAQ 管理"), el("div", "error", error.message));
  }
}



function showFaqCreateModal(panel) {
  const form = buildFaqForm();
  const message = el("div");
  const submit = el("button", "", "建立草稿");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    try {
      const created = await api("/api/faqs", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify(faqPayload(form)),
      });
      closeContentModal();
      await renderFaqManagement(panel);
      showFaqDetail(created.faq.faq_id, panel);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal("新增 FAQ 草稿", form);
}

function showFaqEditModal(faq, version, panel) {
  const form = buildFaqForm(version.content);
  const message = el("div");
  const submit = el("button", "", "建立新版本");
  submit.type = "submit";
  form.append(submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.replaceChildren();
    try {
      await api(`/api/faqs/${encodeURIComponent(faq.faq_id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ ...faqPayload(form), expected_etag: faq.etag }),
      });
      await renderFaqManagement(panel);
      await showFaqDetail(faq.faq_id, panel);
    } catch (error) {
      message.replaceChildren(el("div", "error", error.message));
    } finally {
      submit.disabled = false;
    }
  });
  showContentModal(`編輯 FAQ v${version.version_number}`, form);
}

async function showFaqDetail(faqId, panel) {
  try {
    const detail = await api(`/api/faqs/${encodeURIComponent(faqId)}`);
    const allowed = actorCapabilities();
    const faq = detail.faq;
    const current = detail.versions.find((version) => version.version_id === faq.draft_version_id)
      || detail.versions.find((version) => version.version_id === faq.published_version_id)
      || detail.versions.at(-1);
    const content = el("div");
    content.append(
      el("p", "", `FAQ：${faq.status}｜工作版本：v${current.version_number} ${current.status}｜ETag：${faq.etag}`),
      el("p", "", `問題：${current.content.question}`),
      el("p", "", `答案：${current.content.answer}`),
      el("p", "", `Owner：${current.content.owner_unit_id}｜Issue：${current.content.issue_type_ids.join(", ")}`),
      el(
        "p",
        "metric-label",
        `相關知識文件：${(current.content.related_document_ids || []).join(", ") || "（尚未手動關聯）"}`,
      ),
    );
    const actions = el("div", "filter-bar");
    const run = async (path, payload) => {
      try {
        await api(path, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
          body: JSON.stringify(payload),
        });
        await renderFaqManagement(panel);
        await showFaqDetail(faqId, panel);
      } catch (error) {
        showContentModal("FAQ 操作失敗", el("div", "error", error.message));
      }
    };
    if (allowed.has("ops.faq.write") && current.status !== "IN_REVIEW") {
      const edit = el("button", "", "建立修訂版本");
      edit.addEventListener("click", () => showFaqEditModal(faq, current, panel));
      actions.append(edit);
    }
    if (allowed.has("ops.faq.write") && ["DRAFT", "CHANGES_REQUESTED"].includes(current.status)) {
      for (const [kind, label] of [["POSITIVE", "新增正例"], ["NEGATIVE", "新增反例"]]) {
        const button = el("button", "", label);
        button.addEventListener("click", async () => {
          const utterance = await showTextPrompt({
            title: label,
            message: `請輸入要加入的${label}問法。`,
            required: true,
          });
          if (utterance == null) return;
          await run(`/api/faqs/${faqId}/versions/${current.version_id}/tests`, {
            expected_etag: faq.etag, kind, utterance,
            expected_audience_group_ids: current.content.audience_group_ids,
          });
        });
        actions.append(button);
      }
      const submit = el("button", "", "送審");
      submit.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/submit`, { expected_etag: faq.etag },
      ));
      actions.append(submit);
    }
    if (allowed.has("ops.faq.review") && current.status === "IN_REVIEW") {
      const approve = el("button", "", "核准");
      approve.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/review`,
        { expected_etag: faq.etag, approve: true, reason: "管理員已審閱內容與正反例" },
      ));
      const reject = el("button", "", "退回修改");
      reject.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: "退回 FAQ 修改",
          message: "請輸入退回原因。",
          required: true,
        });
        if (reason == null) return;
        run(`/api/faqs/${faqId}/versions/${current.version_id}/review`, {
          expected_etag: faq.etag, approve: false, reason: reason.trim(),
        });
      });
      actions.append(approve, reject);
    }
    if (allowed.has("ops.faq.activate") && current.status === "APPROVED") {
      const activate = el("button", "", "啟用");
      activate.addEventListener("click", () => run(
        `/api/faqs/${faqId}/versions/${current.version_id}/activate`,
        { expected_etag: faq.etag, reason: "管理員核准啟用" },
      ));
      actions.append(activate);
    }
    if (allowed.has("ops.faq.disable") && faq.status === "ACTIVE") {
      const disable = el("button", "", "停用");
      disable.addEventListener("click", () => run(
        `/api/faqs/${faqId}/disable`, { expected_etag: faq.etag, reason: "管理員停用" },
      ));
      actions.append(disable);
    }
    const performance = el("button", "", "查看命中成效");
    performance.addEventListener("click", () => {
      showFaqPerformanceModal(faqId, detail.faq?.question || detail.faq?.title || "");
    });
    actions.append(performance);
    content.append(actions, el("h3", "", `測試案例（${detail.tests.length}）`));
    for (const test of detail.tests) content.append(el("p", "", `${test.kind}｜${test.utterance}`));
    content.append(el("h3", "", `版本歷史（${detail.versions.length}）`));
    const versions = el("table");
    versions.innerHTML = "<thead><tr><th>版本</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
    const versionRows = el("tbody");
    for (const version of [...detail.versions].reverse()) {
      const action = el("td");
      const canRollback = allowed.has("ops.faq.activate")
        && version.version_id !== faq.published_version_id
        && ["SUPERSEDED", "DISABLED"].includes(version.status)
        && version.approved_by;
      if (canRollback) {
        const rollback = el("button", "", "回復此版本");
        rollback.addEventListener("click", async () => {
          const reason = await showTextPrompt({
            title: `回復 v${version.version_number}`,
            message: "請輸入回復原因。",
            required: true,
          });
          if (reason == null) return;
          run(`/api/faqs/${faqId}/versions/${version.version_id}/rollback`, {
            expected_etag: faq.etag,
            reason: reason.trim(),
          });
        });
        action.append(rollback);
      } else {
        action.textContent = version.version_id === faq.published_version_id ? "目前發布" : "-";
      }
      const row = el("tr");
      row.append(
        el("td", "", `v${version.version_number}`),
        el("td", "", version.status),
        el("td", "", version.created_by),
        action,
      );
      versionRows.append(row);
    }
    versions.append(versionRows);
    content.append(versions);
    content.append(el("h3", "", `Audit（${detail.audit.length}）`));
    for (const event of detail.audit) content.append(el("p", "metric-label", `${event.occurred_at}｜${event.action}｜${event.actor_id}`));
    showContentModal(current.content.question, content);
  } catch (error) {
    showContentModal("FAQ", el("div", "error", error.message));
  }
}

async function showFaqPerformanceModal(faqId, faqTitle = "") {
  const modalBody = el("div");
  const titleText = faqTitle ? `FAQ 命中成效：${faqTitle}` : "FAQ 命中成效";

  const filterBar = el("div", "filter-bar");
  filterBar.style.marginBottom = "1rem";
  filterBar.style.display = "flex";
  filterBar.style.gap = "0.5rem";
  filterBar.style.flexWrap = "wrap";
  filterBar.style.alignItems = "center";

  const periodSelect = el("select");
  periodSelect.setAttribute("aria-label", "查詢區間");
  for (const [val, label] of [
    ["30", "最近 30 天"],
    ["7", "最近 7 天"],
    ["90", "最近 90 天"],
    ["186", "最近 6 個月"],
    ["365", "最近 1 年"],
    ["custom", "自訂區間"],
  ]) {
    const opt = el("option", "", label);
    opt.value = val;
    periodSelect.append(opt);
  }

  const startDateInput = el("input");
  startDateInput.type = "date";
  startDateInput.setAttribute("aria-label", "開始日期");
  startDateInput.style.display = "none";

  const endDateInput = el("input");
  endDateInput.type = "date";
  endDateInput.setAttribute("aria-label", "結束日期");
  endDateInput.style.display = "none";

  periodSelect.addEventListener("change", () => {
    const isCustom = periodSelect.value === "custom";
    startDateInput.style.display = isCustom ? "inline-block" : "none";
    endDateInput.style.display = isCustom ? "inline-block" : "none";
  });

  const queryBtn = el("button", "", "查詢");
  filterBar.append(periodSelect, startDateInput, endDateInput, queryBtn);

  const contentContainer = el("div");
  modalBody.append(filterBar, contentContainer);
  showContentModal(titleText, modalBody);

  async function loadData() {
    contentContainer.replaceChildren(el("p", "empty", "載入成效資料中…"));
    try {
      const params = new URLSearchParams();
      if (periodSelect.value === "custom") {
        if (startDateInput.value) params.set("start_date", startDateInput.value);
        if (endDateInput.value) params.set("end_date", endDateInput.value);
      } else {
        params.set("days", periodSelect.value || "30");
      }

      const queryString = params.toString() ? `?${params.toString()}` : "";
      const data = await api(`/api/faqs/${encodeURIComponent(faqId)}/performance${queryString}`);

      const result = el("div");
      const metrics = el("div", "metrics");
      metrics.append(
        metric("總命中", data.totalHitCount ?? 0),
        metric("當日", data.todayHitCount ?? 0),
        metric("當週", data.thisWeekHitCount ?? 0),
        metric("當月", data.thisMonthHitCount ?? 0),
        metric("查詢區間命中", data.rangeHitCount ?? data.totalHitCount ?? 0),
      );
      result.append(metrics);

      const appendPeriodTable = (title, rows, periodLabel = "期間") => {
        result.append(el("h3", "", title));
        if (!(rows || []).length) {
          result.append(el("p", "empty", "此區間尚無命中。"));
          return;
        }
        const table = el("table");
        table.innerHTML = `<thead><tr><th>${periodLabel}</th><th>Hits</th></tr></thead>`;
        const body = el("tbody");
        for (const item of rows) {
          const row = el("tr");
          row.append(
            el("td", "", item.period || item.versionId || "-"),
            el("td", "", String(item.hitCount ?? 0)),
          );
          body.append(row);
        }
        table.append(body);
        const wrap = el("div", "table-responsive");
        wrap.append(table);
        result.append(wrap);
      };

      appendPeriodTable("版本歸因", data.byVersion || [], "Version");
      appendPeriodTable("按日彙總", data.byDay || []);
      appendPeriodTable("按週彙總", data.byWeek || []);
      appendPeriodTable("按月彙總", data.byMonth || []);

      result.append(el("h3", "", "最近命中"));
      const recentHits = data.recentHits || [];
      if (!recentHits.length) {
        result.append(el("p", "empty", "此區間尚無最近命中紀錄。"));
      } else {
        const recent = el("table");
        recent.innerHTML =
          "<thead><tr><th>時間</th><th>Conversation</th><th>Turn</th><th>Version</th></tr></thead>";
        const recentRows = el("tbody");
        for (const item of recentHits) {
          const row = el("tr");
          row.append(
            el("td", "", item.occurredAt),
            el("td", "", item.conversationId || "-"),
            el("td", "", item.turnId || "-"),
            el("td", "", item.versionId || "legacy-unattributed"),
          );
          recentRows.append(row);
        }
        recent.append(recentRows);
        const recentWrap = el("div", "table-responsive");
        recentWrap.append(recent);
        result.append(recentWrap);
      }

      contentContainer.replaceChildren(result);
    } catch (error) {
      contentContainer.replaceChildren(el("div", "error", error.message));
    }
  }

  queryBtn.addEventListener("click", () => loadData());
  periodSelect.addEventListener("change", () => {
    if (periodSelect.value !== "custom") {
      loadData();
    }
  });

  await loadData();
}

function renderKnowledgeInventory(data, loadDocuments, options = {}) {
  const days = options.days || String(data.periodDays || 30);
  const container = el("div");
  if (data.warning) container.append(el("p", "warning", data.warning));
  const summary = el(
    "p",
    "",
    `共 ${data.total || 0} 份文件｜績效期間 ${data.periodDays || days} 天` +
      (data.filterFormatType ? `｜格式 ${data.filterFormatType}` : ""),
  );
  container.append(summary);
  if (!(data.items || []).length) {
    container.append(el("p", "empty", "沒有符合條件的知識文件。"));
    return container;
  }
  const table = el("table");
  table.innerHTML = [
    "<thead><tr>",
    "<th>文件</th><th>格式</th><th>Owner</th><th>生命週期</th><th>解析 / 索引</th>",
    "<th style=\"text-align:right;\">命中</th><th style=\"text-align:right;\">對話</th>",
    "<th style=\"text-align:right;\">正面</th><th style=\"text-align:right;\">負面</th><th>操作</th>",
    "</tr></thead>",
  ].join("");
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    const documentCell = el("td");
    documentCell.append(
      el("strong", "", item.title || item.documentId),
      el("div", "metric-label", item.documentId),
    );
    const detailButton = el("button", "", "查看成效");
    detailButton.addEventListener("click", async () => {
      detailButton.disabled = true;
      try {
        await openDocumentPerformanceModal(item.documentId, item.title || item.documentId, {
          days,
        });
      } catch (error) {
        showContentModal("知識文件成效", el("div", "error", error.message));
      } finally {
        detailButton.disabled = false;
      }
    });
    const actionCell = el("td");
    actionCell.append(detailButton);
    const hitCell = el("td", "", String(item.hitCount || 0));
    hitCell.style.textAlign = "right";
    hitCell.style.fontVariantNumeric = "tabular-nums";
    const convCell = el("td", "", String(item.conversationCount || 0));
    convCell.style.textAlign = "right";
    convCell.style.fontVariantNumeric = "tabular-nums";
    const posCell = el("td", "", String(item.positiveFeedbackCount || 0));
    posCell.style.textAlign = "right";
    posCell.style.fontVariantNumeric = "tabular-nums";
    const negCell = el("td", "", String(item.negativeFeedbackCount || 0));
    negCell.style.textAlign = "right";
    negCell.style.fontVariantNumeric = "tabular-nums";
    row.append(
      documentCell,
      el("td", "", item.formatFamily || item.formatType || "-"),
      el("td", "", item.ownerUnitId || "-"),
      el("td", "", item.lifecycleStatus || "UNKNOWN"),
      el("td", "", `${item.parseStatus || "UNKNOWN"} / ${item.indexStatus || "UNKNOWN"}`),
      hitCell,
      convCell,
      posCell,
      negCell,
      actionCell,
    );
    body.append(row);
  }
  table.append(body);
  const scrollWrapper = el("div", "table-responsive");
  scrollWrapper.append(table);
  container.append(scrollWrapper);
  if (data.nextCursor) {
    const next = el("button", "", "下一頁");
    next.style.marginTop = "1rem";
    next.addEventListener("click", () => loadDocuments(data.nextCursor));
    container.append(next);
  }
  return container;
}

async function openDocumentPerformanceModal(documentId, title, initial = {}) {
  const state = {
    days: String(initial.days || "186"),
    issueTypeId: initial.issueTypeId || "",
    cursor: "",
  };
  const root = el("div");

  const reload = async () => {
    root.replaceChildren(el("p", "empty", "載入中…"));
    const params = new URLSearchParams({
      days: state.days,
      limit: "50",
    });
    if (state.issueTypeId) params.set("issue_type_id", state.issueTypeId);
    if (state.cursor) params.set("cursor", state.cursor);
    const detail = await api(
      `/api/knowledge/${encodeURIComponent(documentId)}/performance?${params}`,
    );
    root.replaceChildren(
      renderDocumentPerformance(detail, {
        onFilter: async (next) => {
          Object.assign(state, next, { cursor: "" });
          await reload();
        },
        onPage: async (cursor) => {
          state.cursor = cursor || "";
          await reload();
        },
        currentDays: state.days,
        currentIssueTypeId: state.issueTypeId,
      }),
    );
  };

  showContentModal(title || documentId, root);
  await reload();
}

function renderDocumentPerformance(data, controls = {}) {
  const container = el("div", "panel");
  container.style.marginTop = "1rem";

  const filterBar = el("div", "filter-bar");
  const period = el("select");
  period.setAttribute("aria-label", "命中期間");
  for (const [value, label] of [
    ["30", "最近 30 天"],
    ["7", "最近 7 天"],
    ["186", "最近 6 個月"],
    ["365", "最近 1 年"],
  ]) {
    const option = el("option", "", label);
    option.value = value;
    if (value === String(controls.currentDays || data.periodDays || "30")) {
      option.selected = true;
    }
    period.append(option);
  }
  const issueFilter = el("select");
  issueFilter.setAttribute("aria-label", "Issue 類型");
  const allIssues = el("option", "", "全部 Issue");
  allIssues.value = "";
  issueFilter.append(allIssues);
  for (const item of data.issueTypeDistribution || []) {
    const option = el(
      "option",
      "",
      `${item.displayName || item.issueTypeId}（${item.count}）`,
    );
    option.value = item.issueTypeId;
    if (item.issueTypeId === controls.currentIssueTypeId) option.selected = true;
    issueFilter.append(option);
  }
  if (controls.currentIssueTypeId && !Array.from(issueFilter.options).some((o) => o.value === controls.currentIssueTypeId)) {
    const option = el("option", "", controls.currentIssueTypeId);
    option.value = controls.currentIssueTypeId;
    option.selected = true;
    issueFilter.append(option);
  }
  const apply = el("button", "", "套用 Issue／期間");
  apply.addEventListener("click", () => {
    if (typeof controls.onFilter === "function") {
      controls.onFilter({
        days: period.value,
        issueTypeId: issueFilter.value,
      });
    }
  });
  filterBar.append(
    el("span", "metric-label", "REQ-009 篩選："),
    period,
    issueFilter,
    apply,
  );
  container.append(filterBar);

  const grid = el("div", "grid");
  grid.append(
    metric("命中次數", data.hitCount),
    metric("對話數", data.conversationCount),
    metric("正面回饋", data.positiveFeedbackCount),
    metric("負面回饋", data.negativeFeedbackCount),
  );
  container.append(grid);

  if (data.governance) {
    const governance = data.governance;
    const govPanel = el("div", "panel");
    govPanel.append(el("h3", "", "文件治理狀態"));
    if (governance.status === "available") {
      govPanel.append(
        el(
          "p",
          "",
          `生命週期：${governance.lifecycleStatus}｜格式：${governance.formatType}｜解析：${governance.parseStatus}｜索引：${governance.indexStatus}`,
        ),
        el(
          "p",
          "metric-label",
          "索引狀態獨立於生命週期：INDEXED＝已在 ACTIVE release；PENDING_INDEX＝已發布待入索引；NOT_PARSED／NOT_INDEXED＝尚未可檢索。",
        ),
      );
      if (governance.portalUrl) {
        if (getCapabilities()?.knowledgeBridgeEnabled) {
          const openDoc = el("a", "button-link", "在知識文件庫開啟");
          const documentId = data.documentId || governance.documentId;
          openDoc.href = buildLocationHash("knowledge_ops", "knowledgePortal", {
            k: `/knowledge/${documentId}`,
          });
          openDoc.addEventListener("click", (event) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
              return;
            }
            event.preventDefault();
            navigateTo("knowledgePortal", { k: `/knowledge/${documentId}` });
          });
          govPanel.append(openDoc);
        } else {
          const portalLink = el("a", "button-link", "在 Knowledge Portal 開啟");
          portalLink.href = governance.portalUrl;
          portalLink.target = "_blank";
          govPanel.append(portalLink);
        }
      }
    } else {
      govPanel.append(el("p", "", governance.note || `狀態：${governance.status}`));
    }
    container.append(govPanel);
  }

  const issueTable = el("table");
  issueTable.innerHTML =
    "<thead><tr><th>Issue Type</th><th>Display Name</th><th>Count</th></tr></thead>";
  const issueBody = el("tbody");
  for (const item of data.issueTypeDistribution || []) {
    const row = el("tr");
    const issueLink = el("button", "", item.issueTypeId);
    issueLink.addEventListener("click", () => {
      if (typeof controls.onFilter === "function") {
        controls.onFilter({
          days: period.value,
          issueTypeId: item.issueTypeId,
        });
      }
    });
    const issueCell = el("td");
    issueCell.append(issueLink);
    row.append(issueCell);
    row.append(el("td", "", item.displayName || "-"));
    row.append(el("td", "", String(item.count)));
    issueBody.append(row);
  }
  issueTable.append(issueBody);
  container.append(el("h3", "", "Issue 分布"), issueTable);

  const releaseTable = el("table");
  releaseTable.innerHTML = "<thead><tr><th>Release</th><th>Hits</th></tr></thead>";
  const releaseBody = el("tbody");
  for (const item of data.releaseAttribution || []) {
    const row = el("tr");
    row.append(el("td", "", item.releaseId));
    row.append(el("td", "", String(item.hitCount)));
    releaseBody.append(row);
  }
  releaseTable.append(releaseBody);
  container.append(el("h3", "", "版本歸因"), releaseTable);

  const recentTable = el("table");
  recentTable.innerHTML = "<thead><tr><th>時間</th><th>Conversation</th><th>Issue</th><th>Release</th><th>Chunk</th></tr></thead>";
  const recentBody = el("tbody");
  const hitRows = data.hits || data.recentHits || [];
  for (const item of hitRows) {
    const row = el("tr");
    row.append(el("td", "", item.occurredAt));
    const conversation = el("a", "", item.conversationId || "-");
    conversation.href = "#";
    conversation.addEventListener("click", async (event) => {
      event.preventDefault();
      const detail = await api(`/api/conversations/${encodeURIComponent(item.conversationId)}`);
      showConversationModal(detail);
    });
    const conversationCell = el("td");
    conversationCell.append(conversation);
    row.append(conversationCell);
    row.append(el("td", "", item.issueTypeDisplayName || item.issueTypeId || "-"));
    row.append(el("td", "", item.releaseId || "-"));
    row.append(el("td", "", item.chunkId || "-"));
    recentBody.append(row);
  }
  recentTable.append(recentBody);
  container.append(el("h3", "", "命中紀錄（可追溯對話）"), recentTable);
  if (data.nextCursor && typeof controls.onPage === "function") {
    const next = el("button", "", "下一頁命中");
    next.addEventListener("click", () => controls.onPage(data.nextCursor));
    container.append(next);
  }
  return container;
}

export const knowledgePage = createPageController({
  enter: async () => renderKnowledge(),
  update: async () => renderKnowledge(),
  leave: async () => {},
});

export const knowledgePortalPage = createPageController({
  enter: async () => renderKnowledgePortalEntry(),
  update: async () => renderKnowledgePortalEntry(),
  leave: async () => {},
});

export const knowledgeDocumentPage = createPageController({
  enter: async () => renderKnowledgeDocument(),
  update: async () => renderKnowledgeDocument(),
  leave: async () => {},
});


function standaloneKnowledgePage(render) {
  const show = async () => {
    const panel = el("section", "panel");
    document.getElementById("app").replaceChildren(panel);
    await render(panel);
  };
  return createPageController({ enter: show, update: show, leave: async () => {} });
}

export const faqPage = standaloneKnowledgePage(renderFaqManagement);
export const syncPage = standaloneKnowledgePage(renderSyncManagement);
export function knowledgeSectionPage(sub) {
  return createPageController({
    enter: async () => renderKnowledgePortalEntry(sub),
    update: async () => renderKnowledgePortalEntry(sub),
    leave: async () => {},
  });
}
