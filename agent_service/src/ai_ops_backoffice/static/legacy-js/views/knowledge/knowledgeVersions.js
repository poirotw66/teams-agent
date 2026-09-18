import { api, el } from "../../api.js";
import { showContentModal, closeContentModal, showTextPrompt } from "../../components/modal.js";
import { actorCapabilities } from "../../app/capabilities.js";

export async function showSyncDetail(jobId, panel) {
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

export async function renderSyncManagement(panel) {
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

export function showCreateSyncModal(onCreated) {
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
