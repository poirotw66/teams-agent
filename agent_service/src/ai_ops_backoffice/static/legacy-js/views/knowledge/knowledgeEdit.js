import { api, el, metric } from "../../api.js";
import { showContentModal, closeContentModal, showTextPrompt } from "../../components/modal.js";
import { buildFaqForm, faqPayload } from "../../components/faqForms.js";
import {
  renderContentPolicyBanner,
  renderDecisionGuide,
} from "../../components/contentGuide.js";
import { actorCapabilities } from "../../app/capabilities.js";
import { loadNavFilters } from "../../app/navigation.js";
import { isBuShellEnabled } from "../../app/buShellConfig.js";
import { loadingState } from "../../components/state.js";

export async function renderFaqManagement(panel) {
  panel.replaceChildren(el("h2", "", "FAQ 管理"), loadingState("正在載入 FAQ…", 3));
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
    owner.placeholder = "負責單位";
    owner.setAttribute("aria-label", "負責單位");
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
        "<thead><tr><th>FAQ</th><th>分類</th><th>關鍵字</th><th>狀態</th><th>負責單位</th><th>版本</th><th>操作</th></tr></thead>";
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
    const guidance = el("div", "bu-content-guidance-stack");
    guidance.append(policy, decision);
    panel.replaceChildren(heading, guidance, governedNote, actions, result);
    await load();
    if (navFilters.faqId) {
      await showFaqDetail(String(navFilters.faqId), panel);
    }
  } catch (error) {
    panel.replaceChildren(el("h2", "", "FAQ 管理"), el("div", "error", error.message));
  }
}

export function showFaqCreateModal(panel) {
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

export function showFaqEditModal(faq, version, panel) {
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

export async function showFaqDetail(faqId, panel) {
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

export async function showFaqPerformanceModal(faqId, faqTitle = "") {
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
