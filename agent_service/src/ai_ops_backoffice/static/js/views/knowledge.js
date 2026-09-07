import { api, el, metric } from "../api.js";
import { showContentModal } from "../components/modal.js";
import { showConversationModal } from "../components/conversationModal.js";
import { buildFaqForm, faqPayload } from "../components/faqForms.js";
import { runExport } from "../services/export.js";
import { actorCapabilities, canUseKnowledgeUi, getCapabilities } from "../app/capabilities.js";
import {
  buildLocationHash,
  drillLink,
  loadNavFilters,
  navigateTo,
} from "../app/navigation.js";
import { renderNativeKnowledgePortal } from "../knowledge_portal_view.js";
import { createPageController } from "../app/lifecycle.js";


export async function renderKnowledgePortalEntry() {
  const app = document.getElementById("app");
  if (!canUseKnowledgeUi()) {
    app.replaceChildren(
      el(
        "div",
        "error",
        "知識文件庫尚未啟用，或目前角色沒有 knowledge.read。請用 KNOWLEDGE_ADMIN 登入，並確認 start.sh 已啟用 knowledge bridge。",
      ),
    );
    return;
  }

  const filters = loadNavFilters();
  await renderNativeKnowledgePortal(app, getCapabilities(), navigateTo, filters);
}

export async function renderKnowledgeDocument() {
  const app = document.getElementById("app");
  const filters = loadNavFilters();
  const documentId = filters.documentId;
  const caseId = filters.caseId;
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
  try {
    const payload = await api(`/api/knowledge/documents/${encodeURIComponent(documentId)}`);
    const document = payload.document || payload;
    const panel = el("section", "panel");
    panel.append(el("h2", "", document.title || documentId));
    panel.append(
      el("p", "metric-label", `知識營運／文件／${document.title || documentId}`),
    );
    if (caseId) {
      const back = el("button", "", "返回品質案件");
      back.addEventListener("click", () => navigateTo("quality", { caseId }));
      panel.append(back);
    }
    panel.append(
      el("p", "", `狀態：${document.lifecycle_status || document.status || "-"}`),
      el("p", "", `負責單位：${(document.owner_unit_ids || []).join(", ") || "-"}`),
      el(
        "p",
        "metric-label",
        `文件 ID（進階）：${document.document_id || documentId}`,
      ),
    );
    const draft = document.draft || document.current_draft;
    if (draft?.markdown || draft?.content) {
      const pre = el("pre");
      pre.textContent = String(draft.markdown || draft.content).slice(0, 8000);
      panel.append(el("h3", "", "草稿內容預覽"), pre);
    } else if (payload.draft_markdown) {
      const pre = el("pre");
      pre.textContent = String(payload.draft_markdown).slice(0, 8000);
      panel.append(el("h3", "", "草稿內容預覽"), pre);
    } else {
      panel.append(el("p", "", "目前沒有可預覽的草稿正文（可能尚未建立修訂）。"));
    }
    app.replaceChildren(panel);
  } catch (error) {
    const message =
      error.message === "FORBIDDEN"
        ? "沒有知識讀取權限（knowledge.read）。"
        : error.message;
    app.replaceChildren(el("div", error.message === "FORBIDDEN" ? "forbidden" : "error", message));
  }
}

async function renderKnowledge() {
  const app = document.getElementById("app");
  const panel = el("section", "panel");
  const faqPanel = el("section", "panel");
  const syncPanel = el("section", "panel");
  panel.append(el("h2", "", "知識營運"));
  if (getCapabilities()?.knowledgeBridgeEnabled) {
    panel.append(
      el(
        "p",
        "",
        "文件編輯、審核與發布請使用上方「知識文件庫」分頁（內嵌於營運後台）。本頁保留 FAQ 與成效查詢。",
      ),
    );
    const openPortal = el("a", "button-link", "開啟知識文件庫");
    openPortal.href = buildLocationHash("knowledge_ops", "knowledgePortal");
    openPortal.addEventListener("click", (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) {
        return;
      }
      event.preventDefault();
      navigateTo("knowledgePortal");
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
  query.style.minWidth = "280px";
  query.placeholder = "搜尋標題或文件 ID";
  query.setAttribute("aria-label", "搜尋知識文件");
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
  const submit = el("button", "", "套用篩選");
  submit.type = "submit";
  filters.append(query, status, submit);
  const result = el("div", "");
  panel.append(filters, result);
  app.replaceChildren(panel, faqPanel, syncPanel);

  async function loadDocuments(cursor = "") {
    result.replaceChildren(el("p", "empty", "載入中…"));
    try {
      const params = new URLSearchParams({ days: "30", limit: "50" });
      if (query.value.trim()) params.set("query", query.value.trim());
      if (status.value) params.set("status", status.value);
      if (cursor) params.set("cursor", cursor);
      const data = await api(`/api/knowledge?${params.toString()}`);
      result.replaceChildren(renderKnowledgeInventory(data, loadDocuments));
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
      await runExport("csv", "knowledge_performance", 30);
    } catch (error) {
      result.prepend(el("div", "error", error.message));
    } finally {
      exportButton.disabled = false;
      exportButton.textContent = "匯出 CSV";
    }
  });
  await Promise.all([
    loadDocuments(),
    renderFaqManagement(faqPanel),
    renderSyncManagement(syncPanel),
  ]);
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
        const reason = window.prompt("重試原因");
        if (!reason?.trim()) return;
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
        const reason = window.prompt("取消原因");
        if (!reason?.trim()) return;
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
  panel.replaceChildren(el("h2", "", "重新同步 / 索引"), el("p", "empty", "載入中…"));
  const allowed = actorCapabilities();
  try {
    const data = await api("/api/sync-jobs");
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.sync.write")) {
      const create = el("button", "", "建立全量 Sync");
      create.addEventListener("click", async () => {
        const reason = window.prompt("Sync 原因");
        if (!reason?.trim()) return;
        try {
          await api("/api/sync-jobs", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
            body: JSON.stringify({ scope_type: "ALL", scope_ids: [], reason: reason.trim() }),
          });
          await renderSyncManagement(panel);
        } catch (error) {
          showContentModal("建立 Sync 失敗", el("div", "error", error.message));
        }
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
    panel.replaceChildren(el("h2", "", "重新同步 / 索引"), actions, result);
  } catch (error) {
    panel.replaceChildren(el("h2", "", "重新同步 / 索引"), el("div", "error", error.message));
  }
}

async function renderFaqManagement(panel) {
  panel.replaceChildren(el("h2", "", "FAQ 治理"), el("p", "empty", "載入中…"));
  const allowed = actorCapabilities();
  if (!allowed.has("ops.faq.read")) {
    panel.replaceChildren(el("h2", "", "FAQ 治理"), el("div", "forbidden", "FORBIDDEN"));
    return;
  }
  try {
    const heading = el("h2", "", "FAQ 治理");
    const actions = el("div", "filter-bar");
    const query = el("input");
    query.placeholder = "搜尋 FAQ Key 或問題";
    const status = el("select");
    status.innerHTML = `
      <option value="">全部狀態</option>
      <option value="DRAFT">DRAFT</option>
      <option value="IN_REVIEW">IN_REVIEW</option>
      <option value="CHANGES_REQUESTED">CHANGES_REQUESTED</option>
      <option value="APPROVED">APPROVED</option>
      <option value="ACTIVE">ACTIVE</option>
      <option value="DISABLED">DISABLED</option>
    `;
    const result = el("div");
    const load = async () => {
      const params = new URLSearchParams();
      if (query.value.trim()) params.set("query", query.value.trim());
      if (status.value) params.set("status", status.value);
      const data = await api(`/api/faqs?${params}`);
      result.replaceChildren();
      summary.textContent = `共 ${data.total || 0} 筆`;
      if (!(data.items || []).length) {
        result.append(el("p", "empty", "沒有符合條件的 FAQ。"));
        return;
      }
      const table = el("table");
      table.innerHTML = "<thead><tr><th>FAQ</th><th>狀態</th><th>Owner</th><th>版本</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of data.items) {
        const row = el("tr");
        const name = el("td");
        name.append(
          el("strong", "", item.version.content.question),
          el("div", "metric-label", item.faq.faq_key),
        );
        const action = el("td");
        const detail = el("button", "", "查看與處理");
        detail.addEventListener("click", () => showFaqDetail(item.faq.faq_id, panel));
        action.append(detail);
        row.append(
          name,
          el("td", "", item.faq.status),
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
    query.addEventListener("keydown", (event) => {
      if (event.key === "Enter") load();
    });
    if (allowed.has("ops.faq.write")) {
      const createButton = el("button", "", "新增 FAQ");
      createButton.addEventListener("click", () => showFaqCreateModal(panel));
      actions.append(createButton);
    }
    const summary = el("span", "metric-label", "");
    actions.append(query, status, searchButton, summary);
    panel.replaceChildren(heading, actions, result);
    await load();
  } catch (error) {
    panel.replaceChildren(el("h2", "", "FAQ 治理"), el("div", "error", error.message));
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
      document.getElementById("modal-root").hidden = true;
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
          const utterance = window.prompt(`${label}問法`);
          if (!utterance) return;
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
      reject.addEventListener("click", () => {
        const reason = window.prompt("請輸入退回原因");
        if (!reason?.trim()) return;
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
    performance.addEventListener("click", async () => {
      try {
        const data = await api(`/api/faqs/${faqId}/performance`);
        const result = el("div");
        result.append(el("p", "", `總命中：${data.totalHitCount}`));
        const versions = el("table");
        versions.innerHTML = "<thead><tr><th>Version</th><th>Hits</th></tr></thead>";
        const versionRows = el("tbody");
        for (const item of data.byVersion || []) {
          const row = el("tr");
          row.append(el("td", "", item.versionId), el("td", "", String(item.hitCount)));
          versionRows.append(row);
        }
        versions.append(versionRows);
        const recent = el("table");
        recent.innerHTML = "<thead><tr><th>時間</th><th>Conversation</th><th>Turn</th><th>Version</th></tr></thead>";
        const recentRows = el("tbody");
        for (const item of data.recentHits || []) {
          const row = el("tr");
          row.append(
            el("td", "", item.occurredAt), el("td", "", item.conversationId || "-"),
            el("td", "", item.turnId || "-"), el("td", "", item.versionId || "legacy-unattributed"),
          );
          recentRows.append(row);
        }
        recent.append(recentRows);
        result.append(el("h3", "", "版本歸因"), versions, el("h3", "", "最近命中"), recent);
        showContentModal("FAQ 命中成效", result);
      } catch (error) {
        showContentModal("FAQ 命中成效", el("div", "error", error.message));
      }
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
        rollback.addEventListener("click", () => {
          const reason = window.prompt(`請輸入回復 v${version.version_number} 的原因`);
          if (!reason?.trim()) return;
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



function renderKnowledgeInventory(data, loadDocuments) {
  const container = el("div");
  if (data.warning) container.append(el("p", "warning", data.warning));
  const summary = el(
    "p",
    "",
    `共 ${data.total || 0} 份文件｜績效期間 ${data.periodDays || 30} 天`,
  );
  container.append(summary);
  if (!(data.items || []).length) {
    container.append(el("p", "empty", "沒有符合條件的知識文件。"));
    return container;
  }
  const table = el("table");
  table.innerHTML = [
    "<thead><tr>",
    "<th>文件</th><th>Owner</th><th>生命週期</th><th>解析 / 索引</th>",
    "<th style=\"text-align:right;\">命中</th><th style=\"text-align:right;\">對話</th><th style=\"text-align:right;\">負面回饋</th><th>操作</th>",
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
        const detail = await api(
          `/api/knowledge/${encodeURIComponent(item.documentId)}/performance?days=30`,
        );
        showContentModal(item.title || item.documentId, renderDocumentPerformance(detail));
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
    const negCell = el("td", "", String(item.negativeFeedbackCount || 0));
    negCell.style.textAlign = "right";
    negCell.style.fontVariantNumeric = "tabular-nums";
    row.append(
      documentCell,
      el("td", "", item.ownerUnitId || "-"),
      el("td", "", item.lifecycleStatus || "UNKNOWN"),
      el("td", "", `${item.parseStatus || "UNKNOWN"} / ${item.indexStatus || "UNKNOWN"}`),
      hitCell,
      convCell,
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

function renderDocumentPerformance(data) {
  const container = el("div", "panel");
  container.style.marginTop = "1rem";
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
    row.append(el("td", "", item.issueTypeId));
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
  for (const item of data.recentHits || []) {
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
    row.append(el("td", "", item.issueTypeId || "-"));
    row.append(el("td", "", item.releaseId || "-"));
    row.append(el("td", "", item.chunkId || "-"));
    recentBody.append(row);
  }
  recentTable.append(recentBody);
  container.append(el("h3", "", "最近命中對話"), recentTable);
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
