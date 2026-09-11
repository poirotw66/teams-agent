import { api, el } from "../../api.js";
import {
  showContentModal,
  closeContentModal,
  showTextPrompt,
  showToast,
} from "../../components/modal.js";
import { isBuShellEnabled } from "../../app/buShellConfig.js";
import {
  labelBehavior,
  labelSourceHealth,
  labelStatus,
} from "../../app/labels.js";
import { loadNavFilters } from "../../app/navigation.js";
import { escapeHtml, safeClassToken } from "./shared.js";
import { loadSetsList } from "./sets.js";

export async function renderCasesTab(container, allowed) {
  container.replaceChildren();

  const subNav = el("div", isBuShellEnabled() ? "bu-sub-tabs" : "sub-nav-bar");
  let subView = "cases";
  const viewCasesBtn = el(
    "button",
    isBuShellEnabled() ? "active" : "btn-secondary active",
    "驗收題目清單",
  );
  const viewSetsBtn = el(
    "button",
    isBuShellEnabled() ? "" : "btn-secondary",
    isBuShellEnabled() ? "題庫與版本" : "題庫與版本 (Eval Sets)",
  );
  subNav.append(viewCasesBtn, viewSetsBtn);

  const viewContainer = el("div", "eval-view-content");
  container.append(subNav, viewContainer);

  viewCasesBtn.addEventListener("click", () => {
    subView = "cases";
    viewCasesBtn.classList.add("active");
    viewSetsBtn.classList.remove("active");
    loadCasesList(viewContainer, allowed);
  });

  viewSetsBtn.addEventListener("click", () => {
    subView = "sets";
    viewSetsBtn.classList.add("active");
    viewCasesBtn.classList.remove("active");
    loadSetsList(viewContainer, allowed);
  });

  await loadCasesList(viewContainer, allowed);
}

export async function loadCasesList(container, allowed) {
  container.replaceChildren();

  const toolbar = el("div", "toolbar-grid");

  const searchInput = el("input", "search-input");
  searchInput.placeholder = "搜尋問題關鍵字或標題...";
  const navFilters = loadNavFilters();
  if (navFilters.view === "evaluations" && navFilters.q) {
    searchInput.value = navFilters.q;
  }

  const bu = isBuShellEnabled();
  const statusSelect = el("select", "form-select");
  statusSelect.innerHTML = bu
    ? `
    <option value="">全部狀態</option>
    <option value="DRAFT">草稿</option>
    <option value="IN_REVIEW">審核中</option>
    <option value="APPROVED">已核准</option>
    <option value="REJECTED">已退回</option>
    <option value="RETIRED">已退役</option>
  `
    : `
    <option value="">-- 全部狀態 --</option>
    <option value="DRAFT">草稿 (DRAFT)</option>
    <option value="IN_REVIEW">審核中 (IN_REVIEW)</option>
    <option value="APPROVED">已核准 (APPROVED)</option>
    <option value="REJECTED">已退回 (REJECTED)</option>
    <option value="RETIRED">已退役 (RETIRED)</option>
  `;

  const behaviorSelect = el("select", "form-select");
  behaviorSelect.innerHTML = bu
    ? `
    <option value="">全部行為類型</option>
    <option value="ANSWER_WITH_CITATION">引用回答</option>
    <option value="CLARIFY">需求澄清</option>
    <option value="REFUSE">安全拒答</option>
    <option value="HANDOFF">轉真人</option>
    <option value="TOOL_TASK">工具任務</option>
  `
    : `
    <option value="">-- 全部行為類型 --</option>
    <option value="ANSWER_WITH_CITATION">引用回答 (ANSWER_WITH_CITATION)</option>
    <option value="CLARIFY">需求澄清 (CLARIFY)</option>
    <option value="REFUSE">安全拒答 (REFUSE)</option>
    <option value="HANDOFF">轉真人 (HANDOFF)</option>
    <option value="TOOL_TASK">工具執行 (TOOL_TASK)</option>
  `;

  const criticalitySelect = el("select", "form-select");
  criticalitySelect.innerHTML = bu
    ? `
    <option value="">重要性</option>
    <option value="CRITICAL">重大</option>
    <option value="NORMAL">一般</option>
  `
    : `
    <option value="">-- 重要性 --</option>
    <option value="CRITICAL">重大 (CRITICAL)</option>
    <option value="NORMAL">一般 (NORMAL)</option>
  `;

  const healthSelect = el("select", "form-select");
  healthSelect.innerHTML = bu
    ? `
    <option value="">來源健康度</option>
    <option value="VALID">正常</option>
    <option value="NEEDS_REVIEW">來源更新待複核</option>
    <option value="SOURCE_UNAVAILABLE">來源已失效</option>
  `
    : `
    <option value="">-- 來源健康度 --</option>
    <option value="VALID">正常 (VALID)</option>
    <option value="NEEDS_REVIEW">來源變更待複核 (NEEDS_REVIEW)</option>
    <option value="SOURCE_UNAVAILABLE">來源失效 (SOURCE_UNAVAILABLE)</option>
  `;

  const searchBtn = el("button", bu ? "button-primary" : "btn-primary", "篩選");
  const summarySpan = el("span", "text-muted", "載入中...");

  const actionButtons = el("div", bu ? "filter-bar" : "btn-group");

  if (allowed.has("ops.evals.write")) {
    const createBtn = el("button", bu ? "button-primary" : "btn-primary", "＋ 新增驗收題");
    createBtn.addEventListener("click", () => showCaseCreateModal(() => loadCasesList(container, allowed)));

    const genBtn = el("button", bu ? "button-secondary" : "btn-secondary", "自動生成候選");
    genBtn.addEventListener("click", () => showCandidateJobModal(() => loadCasesList(container, allowed)));

    const importBtn = el("button", bu ? "button-secondary" : "btn-secondary", "匯入題庫");
    importBtn.addEventListener("click", () => showImportModal(() => loadCasesList(container, allowed)));

    actionButtons.append(createBtn, genBtn, importBtn);
  }

  if (allowed.has("ops.evals.export")) {
    const exportBtn = el("button", bu ? "button-secondary" : "btn-secondary", "匯出");
    exportBtn.addEventListener("click", showExportModal);
    actionButtons.append(exportBtn);
  }

  toolbar.append(searchInput, statusSelect, behaviorSelect, criticalitySelect, healthSelect, searchBtn, actionButtons, summarySpan);
  if (bu) toolbar.classList.add("bu-eval-toolbar");

  const tableContainer = el("div", "table-responsive");
  container.append(toolbar, tableContainer);

  const fetchCases = async () => {
    tableContainer.replaceChildren(el("p", "loading-text", "資料讀取中..."));
    try {
      const params = new URLSearchParams();
      if (searchInput.value.trim()) params.set("q", searchInput.value.trim());
      if (statusSelect.value) params.set("status", statusSelect.value);
      if (behaviorSelect.value) params.set("behavior", behaviorSelect.value);
      if (criticalitySelect.value) params.set("criticality", criticalitySelect.value);
      if (healthSelect.value) params.set("source_health", healthSelect.value);

      const res = await api(`/api/evaluations/cases?${params.toString()}`);
      summarySpan.textContent = `共 ${res.total || 0} 題`;

      if (!res.items || res.items.length === 0) {
        tableContainer.replaceChildren(el("p", "empty", "目前無符合條件的驗收題目。"));
        return;
      }

      const table = el("table", bu ? "data-table bu-eval-cases" : "data-table");
      table.innerHTML = bu
        ? `
        <thead>
          <tr>
            <th class="bu-eval-col-query">題目</th>
            <th>行為</th>
            <th>狀態</th>
            <th>健康度</th>
            <th>操作</th>
          </tr>
        </thead>
      `
        : `
        <thead>
          <tr>
            <th>標題 / 問題</th>
            <th>行為類型</th>
            <th>重要性</th>
            <th>Owner</th>
            <th>來源健康度</th>
            <th>版本狀態</th>
            <th>操作</th>
          </tr>
        </thead>
      `;
      const tbody = el("tbody");

      for (const item of res.items) {
        const c = item.case;
        const r = item.current_revision;

        const row = el("tr");

        const titleCell = el("td", bu ? "bu-eval-col-query" : "");
        const queryPreview = String(r.query || "").replace(/\s+/g, " ").trim();
        const critMark = r.criticality === "CRITICAL" ? "重大 · " : "";
        if (bu) {
          titleCell.innerHTML = `<strong>${escapeHtml(c.title || "（無標題）")}</strong><span class="bu-eval-query-preview text-muted">${escapeHtml(queryPreview)}</span>`;
          titleCell.title = `${critMark}${c.owner_unit_id || ""}｜rev ${r.revision_number}\n${r.query || ""}`;
        } else {
          titleCell.innerHTML = `<strong>${escapeHtml(c.title)}</strong><br><span class="text-muted">${escapeHtml(r.query)}</span>`;
        }

        const behaviorCell = el("td");
        const behaviorLabel = labelBehavior(r.behavior);
        behaviorCell.innerHTML = `<span class="badge badge-info" title="${escapeHtml(r.behavior)}">${escapeHtml(behaviorLabel)}</span>`;

        const actionsCell = el("td");
        const viewBtn = el(
          "button",
          bu ? "button-secondary" : "btn-sm btn-link",
          bu ? "查看" : "查看與處理",
        );
        viewBtn.addEventListener("click", () => showCaseDetailModal(c.case_id, () => fetchCases()));
        actionsCell.append(viewBtn);

        if (bu) {
          const statusCell = el("td");
          statusCell.innerHTML = `<span class="status-tag status-${safeClassToken(r.status)}" title="${escapeHtml(r.status)}">${escapeHtml(labelStatus(r.status))} · v${escapeHtml(r.revision_number)}</span>`;
          const healthCell = el("td");
          const healthLabel = labelSourceHealth(r.source_health);
          if (r.source_health === "NEEDS_REVIEW") {
            healthCell.innerHTML = `<span class="badge badge-warning" title="${escapeHtml(r.source_health)}">${escapeHtml(healthLabel)}</span>`;
          } else if (r.source_health === "SOURCE_UNAVAILABLE") {
            healthCell.innerHTML = `<span class="badge badge-danger" title="${escapeHtml(r.source_health)}">${escapeHtml(healthLabel)}</span>`;
          } else {
            healthCell.innerHTML = `<span class="badge badge-success" title="${escapeHtml(r.source_health || "VALID")}">${escapeHtml(healthLabel)}</span>`;
          }
          row.append(titleCell, behaviorCell, statusCell, healthCell, actionsCell);
        } else {
          const critCell = el("td");
          critCell.innerHTML = r.criticality === "CRITICAL"
            ? `<span class="badge badge-danger">★ 重大</span>`
            : `<span class="badge badge-secondary">一般</span>`;
          const ownerCell = el("td", "", c.owner_unit_id);
          const healthCell = el("td");
          if (r.source_health === "NEEDS_REVIEW") {
            healthCell.innerHTML = `<span class="badge badge-warning">⚠️ 來源更新待複核</span>`;
          } else if (r.source_health === "SOURCE_UNAVAILABLE") {
            healthCell.innerHTML = `<span class="badge badge-danger">❌ 來源已失效</span>`;
          } else {
            healthCell.innerHTML = `<span class="badge badge-success">正常</span>`;
          }
          const statusCell = el("td");
          statusCell.innerHTML = `<span class="status-tag status-${safeClassToken(r.status)}">${escapeHtml(r.status)} (rev ${escapeHtml(r.revision_number)})</span>`;
          row.append(titleCell, behaviorCell, critCell, ownerCell, healthCell, statusCell, actionsCell);
        }
        tbody.append(row);
      }

      table.append(tbody);
      tableContainer.replaceChildren(table);
    } catch (err) {
      tableContainer.replaceChildren(el("div", "error", `載入失敗: ${err.message || err}`));
    }
  };

  searchBtn.addEventListener("click", fetchCases);
  await fetchCases();
}

export function showCaseCreateModal(onSuccess, prefill = {}) {
  const content = el("div", "modal-body");
  content.innerHTML = `
    <h3>新增驗收案例</h3>
    <form id="new-case-form" class="form-grid">
      <div class="form-group">
        <label>標題 *</label>
        <input type="text" id="case-title" class="form-input" required placeholder="例：特休天數折現計算規定">
      </div>
      <div class="form-group">
        <label>負責單位 *</label>
        <input type="text" id="case-owner" class="form-input" required value="IT Service Desk">
      </div>
      <div class="form-group">
        <label>使用者問題 (Query) *</label>
        <textarea id="case-query" class="form-textarea" rows="3" required placeholder="使用者提問的典型語句..."></textarea>
      </div>
      <div class="form-group">
        <label>預期行為類型 *</label>
        <select id="case-behavior" class="form-select">
          <option value="ANSWER_WITH_CITATION">引用回答 (ANSWER_WITH_CITATION)</option>
          <option value="CLARIFY">需求澄清 (CLARIFY)</option>
          <option value="REFUSE">安全拒答 (REFUSE)</option>
          <option value="HANDOFF">轉真人專員 (HANDOFF)</option>
          <option value="TOOL_TASK">工具任務 (TOOL_TASK)</option>
        </select>
        <small id="behavior-hint" class="text-muted">引用回答模式需提供必要事實重點與依據來源。</small>
      </div>
      <div class="form-group">
        <label>重要性等級</label>
        <select id="case-criticality" class="form-select">
          <option value="NORMAL">一般 (NORMAL)</option>
          <option value="CRITICAL">重大 (CRITICAL)</option>
        </select>
      </div>
      <div class="form-group" id="ref-answer-group">
        <label>參考回答 (僅供人工查驗參考，不進行全文嚴格比對)</label>
        <textarea id="case-ref-answer" class="form-textarea" rows="3"></textarea>
      </div>
      <div class="form-group" id="required-facts-group">
        <label>必要事實重點 (每行一項)</label>
        <textarea id="case-facts" class="form-textarea" rows="2" placeholder="例：未休完特休應於次月結算發給工資"></textarea>
      </div>
      <div class="form-group" id="forbidden-claims-group">
        <label>禁答內容 / 錯誤主張 (每行一項)</label>
        <textarea id="case-forbidden" class="form-textarea" rows="2" placeholder="例：不得宣稱特休自動歸零不補償"></textarea>
      </div>
      <div class="form-group">
        <label>標籤 (以逗號分隔)</label>
        <input type="text" id="case-tags" class="form-input" placeholder="single-hop, hr-policy">
      </div>
      <div class="btn-row">
        <button type="submit" class="btn-primary">建立案例</button>
      </div>
    </form>
  `;

  const behaviorSelect = content.querySelector("#case-behavior");
  const refAnswerGroup = content.querySelector("#ref-answer-group");
  const factsGroup = content.querySelector("#required-facts-group");
  const hint = content.querySelector("#behavior-hint");
  const ownerInput = content.querySelector("#case-owner");
  const criticalitySelect = content.querySelector("#case-criticality");

  content.querySelector("#case-title").value = prefill.title || "";
  ownerInput.value = prefill.owner_unit_id || "IT Service Desk";
  if (prefill.owner_unit_id) {
    ownerInput.readOnly = true;
    ownerInput.title = "沿用改善案件負責單位，避免驗收候選跨單位。";
  }
  content.querySelector("#case-query").value = prefill.query || "";
  content.querySelector("#case-ref-answer").value = prefill.reference_answer || "";
  content.querySelector("#case-facts").value = Array.isArray(prefill.required_facts)
    ? prefill.required_facts.map((item) => item.description || item).join("\n")
    : prefill.required_facts || "";
  content.querySelector("#case-forbidden").value = Array.isArray(prefill.forbidden_claims)
    ? prefill.forbidden_claims.join("\n")
    : prefill.forbidden_claims || "";
  content.querySelector("#case-tags").value = Array.isArray(prefill.tags)
    ? prefill.tags.join(", ")
    : prefill.tags || "";
  if (prefill.behavior) behaviorSelect.value = prefill.behavior;
  if (prefill.criticality) criticalitySelect.value = prefill.criticality;

  const form = content.querySelector("#new-case-form");
  if (prefill.source_type === "QUALITY_CASE") {
    const provenanceNote = el(
      "div",
      "callout",
      "這筆驗收候選會保留改善案件來源；送審、核准並加入已發布題庫後，驗收執行結果才能回到案件追蹤。",
    );
    provenanceNote.style.marginBottom = "0.75rem";
    form.prepend(provenanceNote);
  }

  behaviorSelect.addEventListener("change", () => {
    if (behaviorSelect.value === "REFUSE") {
      refAnswerGroup.style.display = "none";
      factsGroup.style.display = "none";
      hint.textContent = "拒答案例不強迫填寫可回答依據與事實。";
    } else {
      refAnswerGroup.style.display = "";
      factsGroup.style.display = "";
      hint.textContent = "引用回答模式需提供必要事實重點與依據來源。";
    }
  });

  behaviorSelect.dispatchEvent(new Event("change"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = content.querySelector("#case-title").value.trim();
    const owner = content.querySelector("#case-owner").value.trim();
    const query = content.querySelector("#case-query").value.trim();
    const behavior = behaviorSelect.value;
    const criticality = content.querySelector("#case-criticality").value;
    const refAnswer = content.querySelector("#case-ref-answer").value.trim();
    const factsRaw = content.querySelector("#case-facts").value.split("\n").map(s => s.trim()).filter(Boolean);
    const forbiddenRaw = content.querySelector("#case-forbidden").value.split("\n").map(s => s.trim()).filter(Boolean);
    const tagsRaw = content.querySelector("#case-tags").value.split(",").map(s => s.trim()).filter(Boolean);

    const requiredFacts = factsRaw.map((f, idx) => ({
      criterion_id: `crit_${idx + 1}`,
      description: f,
      is_mandatory: true,
    }));

    try {
      const created = await api("/api/evaluations/cases", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          title,
          owner_unit_id: owner,
          query,
          behavior,
          criticality,
          reference_answer: refAnswer || null,
          required_facts: requiredFacts,
          forbidden_claims: forbiddenRaw,
          tags: tagsRaw,
          source_type: prefill.source_type || "MANUAL",
          source_id: prefill.source_id || null,
          source_version_id: prefill.source_version_id || null,
          metadata: prefill.metadata || {},
        }),
      });
      closeContentModal();
      if (onSuccess) await onSuccess(created);
    } catch (err) {
      showToast(`建立失敗: ${err.message}`, { tone: "error" });
    }
  });

  showContentModal(content);
}

export async function showCaseDetailModal(caseId, onUpdate) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>載入案例詳情中...</p>";
  showContentModal(content);

  try {
    const res = await api(`/api/evaluations/cases/${caseId}`);
    const c = res.case;
    const r = res.current_revision;

    content.innerHTML = `
      <h3>${escapeHtml(c.title)}</h3>
      <div class="meta-grid">
        <div><strong>Case ID:</strong> ${escapeHtml(c.case_id)}</div>
        <div><strong>負責單位:</strong> ${escapeHtml(c.owner_unit_id)}</div>
        <div><strong>目前版本:</strong> rev ${escapeHtml(r.revision_number)} (${escapeHtml(r.status)})</div>
        <div><strong>建立者:</strong> ${escapeHtml(r.created_by)}</div>
        <div><strong>行為類型:</strong> ${escapeHtml(r.behavior)}</div>
        <div><strong>重要性:</strong> ${escapeHtml(r.criticality)}</div>
        <div><strong>來源健康度:</strong> ${escapeHtml(r.source_health)}</div>
        <div><strong>內容雜湊:</strong> <code>${escapeHtml((r.content_hash || "").slice(0, 10))}...</code></div>
      </div>
      <div class="section-block">
        <h4>問題內容</h4>
        <div class="content-box">${escapeHtml(r.query)}</div>
      </div>
      ${r.criteria.reference_answer ? `
      <div class="section-block">
        <h4>參考回答</h4>
        <div class="content-box">${escapeHtml(r.criteria.reference_answer)}</div>
      </div>` : ""}
      <div class="section-block">
        <h4>必要事實重點</h4>
        <ul>
          ${(r.criteria.required_facts || []).map(f => `<li>${escapeHtml(f.description)}</li>`).join("") || "<li>(無)</li>"}
        </ul>
      </div>
      <div class="section-block">
        <h4>禁止主張</h4>
        <ul>
          ${(r.criteria.forbidden_claims || []).map(fc => `<li>${escapeHtml(fc)}</li>`).join("") || "<li>(無)</li>"}
        </ul>
      </div>
      <div class="action-footer" id="case-actions-bar"></div>
    `;

    const actionsBar = content.querySelector("#case-actions-bar");

    if (r.status === "DRAFT" || r.status === "REJECTED") {
      const submitBtn = el("button", "btn-primary", "送審 (Submit for Review)");
      submitBtn.addEventListener("click", async () => {
        try {
          await api(`/api/evaluations/cases/${caseId}/revisions/${r.revision_id}/submit`, {
            method: "POST",
            body: JSON.stringify({ expected_etag: r.etag }),
          });
          closeContentModal();
          if (onUpdate) onUpdate();
        } catch (err) {
          showToast(`送審失敗: ${err.message}`, { tone: "error" });
        }
      });
      actionsBar.append(submitBtn);
    }

    if (r.status === "IN_REVIEW") {
      const reviewBtn = el("button", "btn-primary", "執行審核 (Review)");
      reviewBtn.addEventListener("click", () => {
        showReviewDialog(caseId, r, onUpdate);
      });
      actionsBar.append(reviewBtn);
    }

    if (r.status === "APPROVED") {
      const newRevBtn = el("button", "btn-secondary", "建立新修訂 (New Revision)");
      newRevBtn.addEventListener("click", async () => {
        const newQuery = await showTextPrompt({
          title: "建立新修訂",
          message: "請輸入修訂後的使用者問題（Query）。",
          defaultValue: r.query,
          required: true,
        });
        if (newQuery == null) return;
        try {
          await api(`/api/evaluations/cases/${caseId}/revisions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              query: newQuery.trim(),
              base_revision_id: r.revision_id,
              behavior: r.behavior,
              criticality: r.criticality,
            }),
          });
          showToast("新草稿修訂版本已建立！", { tone: "success" });
          showCaseDetailModal(caseId, onUpdate);
          if (onUpdate) onUpdate();
        } catch (err) {
          showToast(`建立新修訂失敗: ${err.message || err}`, { tone: "error" });
        }
      });
      actionsBar.append(newRevBtn);
    }

    if (r.status !== "RETIRED") {
      const retireBtn = el("button", "btn-danger", "退役案例 (Retire)");
      retireBtn.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: "退役評測案例",
          message: "請輸入退役原因。",
          required: true,
        });
        if (reason == null) return;
        try {
          await api(`/api/evaluations/cases/${caseId}/retire`, {
            method: "POST",
            body: JSON.stringify({ reason }),
          });
          closeContentModal();
          if (onUpdate) onUpdate();
        } catch (err) {
          showToast(`退役失敗: ${err.message}`, { tone: "error" });
        }
      });
      actionsBar.append(retireBtn);
    }
  } catch (err) {
    content.innerHTML = `<div class="error">讀取失敗: ${escapeHtml(err.message || err)}</div>`;
  }
}

export function showReviewDialog(caseId, revision, onUpdate) {
  const content = el("div", "modal-body");
  content.innerHTML = `
    <h3>審核驗收案例 (Separation of Duties)</h3>
    <p class="text-muted">案例作者不得核准自己的版本。請客觀查驗問題、依據與期望行為。</p>
    <form id="review-form">
      <div class="form-group">
        <label>審核判定 *</label>
        <div class="radio-row">
          <label><input type="radio" name="decision" value="approve" checked> 核准 (APPROVED)</label>
          <label><input type="radio" name="decision" value="reject"> 退回 (REJECTED)</label>
        </div>
      </div>
      <div class="form-group">
        <label>審核意見 / 退回理由 *</label>
        <textarea id="review-reason" class="form-textarea" rows="3" required placeholder="說明核准依據或退回理由..."></textarea>
      </div>
      <div class="btn-row">
        <button type="submit" class="btn-primary">提交審核決定</button>
      </div>
    </form>
  `;

  const form = content.querySelector("#review-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const approve = form.querySelector("input[name='decision']:checked").value === "approve";
    const reason = form.querySelector("#review-reason").value.trim();

    try {
      await api(`/api/evaluations/cases/${caseId}/revisions/${revision.revision_id}/review`, {
        method: "POST",
        body: JSON.stringify({
          approve,
          reason,
          expected_etag: revision.etag,
        }),
      });
      closeContentModal();
      if (onUpdate) onUpdate();
    } catch (err) {
      showToast(`審核失敗: ${err.message}`, { tone: "error" });
    }
  });

  showContentModal(content);
}

export function showCandidateJobModal(onSuccess) {
  const content = el("div", "modal-body");
  content.innerHTML = `
    <h3>由來源自動生成候選題 (Synthetic Candidate Generator)</h3>
    <p class="text-muted">自動生成僅作為候選題目來源；未經人工審核核准前不得納入正式題庫 (GE1-05)。</p>
    <form id="cand-job-form">
      <div class="form-group">
        <label>來源標題與 ID *</label>
        <input type="text" id="source-title" class="form-input" required placeholder="例：差旅報銷規範" value="差旅報銷規範">
      </div>
      <div class="form-group">
        <label>來源類型</label>
        <select id="source-type" class="form-select">
          <option value="FAQ">FAQ</option>
          <option value="DOCUMENT">文件 (DOCUMENT)</option>
        </select>
      </div>
      <div class="form-group">
        <label>預計生成題數 (上限 100)</label>
        <input type="number" id="cand-count" class="form-input" value="3" min="1" max="100">
      </div>
      <div class="form-group">
        <label>負責單位 *</label>
        <input type="text" id="cand-owner" class="form-input" required value="IT Service Desk">
      </div>
      <div class="btn-row">
        <button type="submit" class="btn-primary">啟動生成工作</button>
      </div>
    </form>
    <div id="job-status-div" style="margin-top: 12px;"></div>
  `;

  const form = content.querySelector("#cand-job-form");
  const statusDiv = content.querySelector("#job-status-div");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = form.querySelector("#source-title").value.trim();
    const sType = form.querySelector("#source-type").value;
    const count = parseInt(form.querySelector("#cand-count").value, 10);
    const owner = form.querySelector("#cand-owner").value.trim();

    statusDiv.innerHTML = "<p>生成工作執行中...</p>";
    try {
      const res = await api("/api/evaluations/candidate-jobs", {
        method: "POST",
        body: JSON.stringify({
          source_refs: [{ source_type: sType, source_id: `source_${Date.now()}`, version_id: "v1", title }],
          target_types: ["ANSWER_WITH_CITATION", "CLARIFY", "REFUSE"],
          requested_count: count,
          owner_unit_id: owner,
        }),
      });

      statusDiv.innerHTML = `
        <div class="alert alert-success">
          <strong>生成成功！</strong> 已生成 ${escapeHtml(res.created_candidate_case_ids.length)} 筆草稿候選題。<br>
          <small>消耗 Token: ${escapeHtml(res.used_tokens)} | 預估成本: $${escapeHtml(res.estimated_cost_usd)} USD</small>
        </div>
      `;
      if (onSuccess) onSuccess();
    } catch (err) {
      statusDiv.innerHTML = `<div class="error">生成失敗: ${escapeHtml(err.message || err)}</div>`;
    }
  });

  showContentModal(content);
}

export function showImportModal(onSuccess) {
  const content = el("div", "modal-body");
  content.innerHTML = `
    <h3>匯入題庫 (支援 JSONL / CSV)</h3>
    <form id="import-form">
      <div class="form-group">
        <label>格式</label>
        <select id="import-format" class="form-select">
          <option value="JSONL">完整 JSONL 格式</option>
          <option value="CSV">基本單輪 CSV 格式 (防試算表注入防護)</option>
        </select>
      </div>
      <div class="form-group">
        <label>負責單位 *</label>
        <input type="text" id="import-owner" class="form-input" required value="IT Service Desk">
      </div>
      <div class="form-group">
        <label>資料內容 *</label>
        <textarea id="import-content" class="form-textarea" rows="8" required placeholder="貼上 JSONL 或 CSV 內容..."></textarea>
      </div>
      <div class="btn-row">
        <button type="submit" class="btn-primary">進行驗證 (Dry-run)</button>
      </div>
    </form>
    <div id="validation-result" style="margin-top: 12px;"></div>
  `;

  const form = content.querySelector("#import-form");
  const resultDiv = content.querySelector("#validation-result");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file_format = form.querySelector("#import-format").value;
    const owner_unit_id = form.querySelector("#import-owner").value.trim();
    const rawContent = form.querySelector("#import-content").value;

    resultDiv.innerHTML = "<p>驗證中...</p>";
    try {
      const valRes = await api("/api/evaluations/imports/validate", {
        method: "POST",
        body: JSON.stringify({ content: rawContent, file_format, owner_unit_id }),
      });

      if (!valRes.is_valid) {
        resultDiv.innerHTML = `
          <div class="error">
            <strong>驗證失敗！共 ${escapeHtml(valRes.error_rows)} 筆錯誤：</strong>
            <ul>${valRes.errors.map(err => `<li>第 ${escapeHtml(err.row)} 列: [${escapeHtml(err.field)}] ${escapeHtml(err.message)}</li>`).join("")}</ul>
          </div>
        `;
      } else {
        resultDiv.innerHTML = `
          <div class="alert alert-success">
            <strong>驗證通過！</strong> 共 ${escapeHtml(valRes.valid_rows)} 筆有效案例。
            ${valRes.similar_warnings.length > 0 ? `<br><small>提示：有 ${escapeHtml(valRes.similar_warnings.length)} 題在現有題庫中已有相似問題。</small>` : ""}
          </div>
          <button id="commit-import-btn" class="btn-primary" style="margin-top: 8px;">確認原子寫入題庫</button>
        `;

        const commitBtn = resultDiv.querySelector("#commit-import-btn");
        commitBtn.addEventListener("click", async () => {
          try {
            const commitRes = await api(`/api/evaluations/imports/${valRes.staged_import_id}/commit?owner_unit_id=${encodeURIComponent(owner_unit_id)}`, {
              method: "POST",
            });
            showToast(`成功匯入 ${commitRes.total} 筆案例！`, { tone: "success" });
            closeContentModal();
            if (onSuccess) onSuccess();
          } catch (cErr) {
            showToast(`提交失敗: ${cErr.message}`, { tone: "error" });
          }
        });
      }
    } catch (err) {
      resultDiv.innerHTML = `<div class="error">驗證請求失敗: ${escapeHtml(err.message || err)}</div>`;
    }
  });

  showContentModal(content);
}

export function showExportModal() {
  const content = el("div", "modal-body");
  content.innerHTML = `
    <h3>匯出驗收題庫</h3>
    <form id="export-form">
      <div class="form-group">
        <label>匯出格式</label>
        <select id="export-format" class="form-select">
          <option value="JSONL">完整 JSONL 格式 (包含多輪與工具契約)</option>
          <option value="CSV">基本 CSV 格式 (試算表防注入保護)</option>
        </select>
      </div>
      <div class="btn-row">
        <button type="submit" class="btn-primary">匯出下載</button>
      </div>
    </form>
    <div id="export-download" style="margin-top: 12px;"></div>
  `;

  const form = content.querySelector("#export-form");
  const downloadDiv = content.querySelector("#export-download");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file_format = form.querySelector("#export-format").value;

    try {
      const res = await api("/api/evaluations/exports", {
        method: "POST",
        body: JSON.stringify({ file_format }),
      });
      const blob = new Blob([res.content], { type: file_format === "CSV" ? "text/csv;charset=utf-8;" : "application/json" });
      const url = URL.createObjectURL(blob);
      const a = el("a", "btn-secondary", `下載 ${file_format} 檔案`);
      a.href = url;
      a.download = `golden_evals_${Date.now()}.${file_format.toLowerCase()}`;
      downloadDiv.replaceChildren(a);
    } catch (err) {
      downloadDiv.innerHTML = `<div class="error">匯出失敗: ${err.message}</div>`;
    }
  });

  showContentModal(content);
}
