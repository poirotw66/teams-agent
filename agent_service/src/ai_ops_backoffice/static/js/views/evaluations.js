import { api, el } from "../api.js";
import { showContentModal, closeContentModal } from "../components/modal.js";
import { actorCapabilities } from "../app/capabilities.js";
import { createPageController } from "../app/lifecycle.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import {
  labelBehavior,
  labelSourceHealth,
  labelStatus,
} from "../app/labels.js";
import { loadNavFilters, navigateTo, saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { navigateReturnTo, parseReturnTo, withReturnTo } from "../app/returnTo.js";

let currentActiveTab = "cases";

export async function renderEvaluations() {
  const app = document.getElementById("app");
  const allowed = actorCapabilities();
  const nav = loadNavFilters();
  if (nav.view === "evaluations" && nav.tab) {
    currentActiveTab = nav.tab;
  }

  const container = el("div", "evaluations-container");

  if (parseReturnTo(nav.returnTo)) {
    const back = el("button", "button-link", "← 返回改善案件");
    back.type = "button";
    back.addEventListener("click", () => navigateReturnTo("workHub", {}));
    container.append(back);
  }

  const header = el("div", "page-header");
  const title = el(
    "h2",
    "",
    isBuShellEnabled() ? "品質驗收" : "品質驗收 (Golden Eval Set)",
  );
  const subtitle = el(
    "p",
    "page-subtitle",
    isBuShellEnabled()
      ? "以固定問題比較版本，知道這次改善了什麼。"
      : "BU 驗收題庫管理、版本發布與真實評測比較",
  );
  header.append(title, subtitle);

  const tabsNav = el("div", isBuShellEnabled() ? "bu-quality-tabs" : "tabs-nav");
  const tabCasesBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "cases" ? "active" : ""}`.trim(), "驗收題庫");
  const tabRunsBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "runs" ? "active" : ""}`.trim(), "執行驗收");
  const tabResultsBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "results" ? "active" : ""}`.trim(), "驗收結果");
  const tabGatesBtn = el("button", `${isBuShellEnabled() ? "" : "tab-btn "}${currentActiveTab === "gates" ? "active" : ""}`.trim(), "發布門檻");

  tabsNav.append(tabCasesBtn, tabRunsBtn, tabResultsBtn, tabGatesBtn);

  const tabContent = el("div", "tab-content");

  function activate(tab, renderFn) {
    currentActiveTab = tab;
    for (const btn of [tabCasesBtn, tabRunsBtn, tabResultsBtn, tabGatesBtn]) {
      btn.classList.remove("active");
    }
    if (tab === "cases") tabCasesBtn.classList.add("active");
    if (tab === "runs") tabRunsBtn.classList.add("active");
    if (tab === "results") tabResultsBtn.classList.add("active");
    if (tab === "gates") tabGatesBtn.classList.add("active");
    const existing = loadNavFilters();
    const preserved = { ...existing, view: "evaluations", tab };
    saveNavFilters(preserved);
    syncLocationHash("evaluations", preserved);
    renderFn(tabContent, allowed);
  }

  tabCasesBtn.addEventListener("click", () => activate("cases", renderCasesTab));
  tabRunsBtn.addEventListener("click", () => activate("runs", renderRunsTab));
  tabResultsBtn.addEventListener("click", () => activate("results", renderResultsTab));
  tabGatesBtn.addEventListener("click", () => activate("gates", renderGatesTab));

  container.append(header, tabsNav, tabContent);
  app.replaceChildren(container);

  if (currentActiveTab === "cases") {
    await renderCasesTab(tabContent, allowed);
  } else if (currentActiveTab === "runs") {
    await renderRunsTab(tabContent, allowed);
  } else if (currentActiveTab === "results") {
    await renderResultsTab(tabContent, allowed);
  } else {
    await renderGatesTab(tabContent, allowed);
  }
}

async function renderCasesTab(container, allowed) {
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

async function loadCasesList(container, allowed) {
  container.replaceChildren();

  const toolbar = el("div", "toolbar-grid");

  const searchInput = el("input", "search-input");
  searchInput.placeholder = "搜尋問題關鍵字或標題...";

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
          titleCell.innerHTML = `<strong>${c.title || "（無標題）"}</strong><span class="bu-eval-query-preview text-muted">${queryPreview}</span>`;
          titleCell.title = `${critMark}${c.owner_unit_id || ""}｜rev ${r.revision_number}\n${r.query || ""}`;
        } else {
          titleCell.innerHTML = `<strong>${c.title}</strong><br><span class="text-muted">${r.query}</span>`;
        }

        const behaviorCell = el("td");
        const behaviorLabel = labelBehavior(r.behavior);
        behaviorCell.innerHTML = `<span class="badge badge-info" title="${r.behavior}">${behaviorLabel}</span>`;

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
          statusCell.innerHTML = `<span class="status-tag status-${String(r.status || "").toLowerCase()}" title="${r.status}">${labelStatus(r.status)} · v${r.revision_number}</span>`;
          const healthCell = el("td");
          const healthLabel = labelSourceHealth(r.source_health);
          if (r.source_health === "NEEDS_REVIEW") {
            healthCell.innerHTML = `<span class="badge badge-warning" title="${r.source_health}">${healthLabel}</span>`;
          } else if (r.source_health === "SOURCE_UNAVAILABLE") {
            healthCell.innerHTML = `<span class="badge badge-danger" title="${r.source_health}">${healthLabel}</span>`;
          } else {
            healthCell.innerHTML = `<span class="badge badge-success" title="${r.source_health || "VALID"}">${healthLabel}</span>`;
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
          statusCell.innerHTML = `<span class="status-tag status-${r.status.toLowerCase()}">${r.status} (rev ${r.revision_number})</span>`;
          row.append(titleCell, behaviorCell, critCell, ownerCell, healthCell, statusCell, actionsCell);
        }
        tbody.append(row);
      }

      table.append(tbody);
      tableContainer.replaceChildren(table);
    } catch (err) {
      tableContainer.replaceChildren(el("div", "error", `載入失敗: ${err.message}`));
    }
  };

  searchBtn.addEventListener("click", fetchCases);
  await fetchCases();
}

async function loadSetsList(container, allowed) {
  container.replaceChildren();

  const toolbar = el("div", "toolbar-row");
  const title = el("h3", "", "題庫清單 (Eval Sets)");
  const createSetBtn = el("button", "btn-primary", "＋ 建立題庫");
  toolbar.append(title);
  if (allowed.has("ops.evals.write")) {
    toolbar.append(createSetBtn);
  }

  const tableContainer = el("div", "table-responsive");
  container.append(toolbar, tableContainer);

  const fetchSets = async () => {
    try {
      const res = await api("/api/evaluations/sets");
      if (!res.items || res.items.length === 0) {
        tableContainer.replaceChildren(el("p", "empty", "目前尚未建立任何驗收題庫。"));
        return;
      }

      const table = el("table", "data-table");
      table.innerHTML = `
        <thead>
          <tr>
            <th>題庫名稱</th>
            <th>用途 (Purpose)</th>
            <th>負責單位</th>
            <th>負責人</th>
            <th>操作</th>
          </tr>
        </thead>
      `;
      const tbody = el("tbody");
      for (const s of res.items) {
        const row = el("tr");
        const nameCell = el("td");
        nameCell.innerHTML = `<strong>${s.name}</strong><br><span class="text-muted">${s.description || ""}</span>`;

        const purposeCell = el("td");
        purposeCell.innerHTML = s.purpose === "HOLDOUT"
          ? `<span class="badge badge-warning">🔒 保留集 (HOLDOUT)</span>`
          : `<span class="badge badge-success">開發集 (DEVELOPMENT)</span>`;

        const ownerCell = el("td", "", s.owner_unit_ids.join(", "));
        const leadCell = el("td", "", s.lead_owner);

        const actionsCell = el("td");
        const detailBtn = el("button", "btn-sm btn-link", "版本與成員");
        detailBtn.addEventListener("click", () => showSetDetailModal(s.set_id));
        actionsCell.append(detailBtn);

        row.append(nameCell, purposeCell, ownerCell, leadCell, actionsCell);
        tbody.append(row);
      }
      table.append(tbody);
      tableContainer.replaceChildren(table);
    } catch (err) {
      tableContainer.replaceChildren(el("div", "error", `載入失敗: ${err.message}`));
    }
  };

  createSetBtn.addEventListener("click", () => showCreateSetModal(() => fetchSets()));
  await fetchSets();
}

function showCaseCreateModal(onSuccess) {
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
      <div class="form-group">
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

  const form = content.querySelector("#new-case-form");
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
      await api("/api/evaluations/cases", {
        method: "POST",
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
          source_type: "MANUAL",
        }),
      });
      closeContentModal();
      if (onSuccess) onSuccess();
    } catch (err) {
      alert(`建立失敗: ${err.message}`);
    }
  });

  showContentModal(content);
}

async function showCaseDetailModal(caseId, onUpdate) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>載入案例詳情中...</p>";
  showContentModal(content);

  try {
    const res = await api(`/api/evaluations/cases/${caseId}`);
    const c = res.case;
    const r = res.current_revision;

    content.innerHTML = `
      <h3>${c.title}</h3>
      <div class="meta-grid">
        <div><strong>Case ID:</strong> ${c.case_id}</div>
        <div><strong>負責單位:</strong> ${c.owner_unit_id}</div>
        <div><strong>目前版本:</strong> rev ${r.revision_number} (${r.status})</div>
        <div><strong>建立者:</strong> ${r.created_by}</div>
        <div><strong>行為類型:</strong> ${r.behavior}</div>
        <div><strong>重要性:</strong> ${r.criticality}</div>
        <div><strong>來源健康度:</strong> ${r.source_health}</div>
        <div><strong>內容雜湊:</strong> <code>${r.content_hash.slice(0, 10)}...</code></div>
      </div>
      <div class="section-block">
        <h4>問題內容</h4>
        <div class="content-box">${r.query}</div>
      </div>
      ${r.criteria.reference_answer ? `
      <div class="section-block">
        <h4>參考回答</h4>
        <div class="content-box">${r.criteria.reference_answer}</div>
      </div>` : ""}
      <div class="section-block">
        <h4>必要事實重點</h4>
        <ul>
          ${(r.criteria.required_facts || []).map(f => `<li>${f.description}</li>`).join("") || "<li>(無)</li>"}
        </ul>
      </div>
      <div class="section-block">
        <h4>禁止主張</h4>
        <ul>
          ${(r.criteria.forbidden_claims || []).map(fc => `<li>${fc}</li>`).join("") || "<li>(無)</li>"}
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
          alert(`送審失敗: ${err.message}`);
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
        const newQuery = prompt("請輸入修訂後的使用者問題 (Query)：", r.query);
        if (!newQuery) return;
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
          alert("新草稿修訂版本已建立！");
          showCaseDetailModal(caseId, onUpdate);
          if (onUpdate) onUpdate();
        } catch (err) {
          alert(`建立新修訂失敗: ${err.message || err}`);
        }
      });
      actionsBar.append(newRevBtn);
    }

    if (r.status !== "RETIRED") {
      const retireBtn = el("button", "btn-danger", "退役案例 (Retire)");
      retireBtn.addEventListener("click", async () => {
        const reason = prompt("請輸入退役原因：");
        if (!reason) return;
        try {
          await api(`/api/evaluations/cases/${caseId}/retire`, {
            method: "POST",
            body: JSON.stringify({ reason }),
          });
          closeContentModal();
          if (onUpdate) onUpdate();
        } catch (err) {
          alert(`退役失敗: ${err.message}`);
        }
      });
      actionsBar.append(retireBtn);
    }
  } catch (err) {
    content.innerHTML = `<div class="error">讀取失敗: ${err.message}</div>`;
  }
}

function showReviewDialog(caseId, revision, onUpdate) {
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
      alert(`審核失敗: ${err.message}`);
    }
  });

  showContentModal(content);
}

function showCreateSetModal(onSuccess) {
  const content = el("div", "modal-body");
  content.innerHTML = `
    <h3>建立驗收題庫 (Eval Set)</h3>
    <form id="create-set-form">
      <div class="form-group">
        <label>題庫名稱 *</label>
        <input type="text" id="set-name" class="form-input" required placeholder="例：人事規定標準驗收集">
      </div>
      <div class="form-group">
        <label>題庫用途 (Purpose) *</label>
        <select id="set-purpose" class="form-select">
          <option value="DEVELOPMENT">開發集 (DEVELOPMENT) - 用於日常改版與驗證</option>
          <option value="HOLDOUT">保留集 (HOLDOUT) - 嚴格隔離，不可用於優化</option>
        </select>
      </div>
      <div class="form-group">
        <label>負責單位 (以逗號分隔) *</label>
        <input type="text" id="set-owners" class="form-input" required value="IT Service Desk">
      </div>
      <div class="form-group">
        <label>說明描述</label>
        <textarea id="set-desc" class="form-textarea" rows="2"></textarea>
      </div>
      <div class="btn-row">
        <button type="submit" class="btn-primary">建立題庫</button>
      </div>
    </form>
  `;

  const form = content.querySelector("#create-set-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = form.querySelector("#set-name").value.trim();
    const purpose = form.querySelector("#set-purpose").value;
    const owners = form.querySelector("#set-owners").value.split(",").map(s => s.trim()).filter(Boolean);
    const description = form.querySelector("#set-desc").value.trim();

    try {
      await api("/api/evaluations/sets", {
        method: "POST",
        body: JSON.stringify({ name, purpose, owner_unit_ids: owners, description }),
      });
      closeContentModal();
      if (onSuccess) onSuccess();
    } catch (err) {
      alert(`建立題庫失敗: ${err.message}`);
    }
  });

  showContentModal(content);
}

async function showSetDetailModal(setId) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>載入題庫詳情中...</p>";
  showContentModal(content);

  try {
    const res = await api(`/api/evaluations/sets/${setId}`);
    const s = res.eval_set;
    const versions = res.versions || [];

    content.innerHTML = `
      <h3>${s.name}</h3>
      <div class="meta-grid">
        <div><strong>Set ID:</strong> ${s.set_id}</div>
        <div><strong>用途:</strong> ${s.purpose}</div>
        <div><strong>負責單位:</strong> ${s.owner_unit_ids.join(", ")}</div>
        <div><strong>負責人:</strong> ${s.lead_owner}</div>
      </div>
      <h4>已發布版本清單</h4>
      <div id="versions-list">
        ${versions.length === 0 ? "<p class='empty'>目前無任何版本。</p>" : ""}
      </div>
      <div class="btn-row">
        <button id="create-ver-btn" class="btn-primary">＋ 建立並發布新版本</button>
      </div>
    `;

    const verList = content.querySelector("#versions-list");
    for (const v of versions) {
      const vCard = el("div", "card-item");
      vCard.innerHTML = `
        <strong>v${v.version}</strong> (${v.status}) - ${v.case_revision_ids.length} 題
        <br><small class="text-muted">Manifest Hash: <code>${v.manifest_hash ? v.manifest_hash.slice(0, 12) : "尚未發布"}</code> | 發布時間: ${v.published_at || "-"}</small>
      `;
      verList.append(vCard);
    }

    const createVerBtn = content.querySelector("#create-ver-btn");
    createVerBtn.addEventListener("click", () => showPublishVersionModal(setId, () => showSetDetailModal(setId)));
  } catch (err) {
    content.innerHTML = `<div class="error">讀取失敗: ${err.message}</div>`;
  }
}

async function showPublishVersionModal(setId, onSuccess) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>載入可納入題庫的案例清單...</p>";
  showContentModal(content);

  try {
    const casesRes = await api("/api/evaluations/cases?status=APPROVED");
    const approvedCases = casesRes.items || [];

    if (approvedCases.length === 0) {
      content.innerHTML = `
        <h3>發布新題庫版本</h3>
        <p class="error">目前沒有任何已核准 (APPROVED) 的案例！根據規格 GE1-A01，未核准案例不可發布入題庫。</p>
      `;
      return;
    }

    content.innerHTML = `
      <h3>發布新題庫版本 (不可變快照)</h3>
      <p class="text-muted">請勾選要包含在本次發布版本中的核准案例：</p>
      <form id="publish-ver-form">
        <div class="cases-selector" style="max-height: 250px; overflow-y: auto; border: 1px solid #ccc; padding: 8px;">
          ${approvedCases.map(item => `
            <label style="display:block; margin-bottom: 4px;">
              <input type="checkbox" name="rev_id" value="${item.current_revision.revision_id}" checked>
              <strong>${item.case.title}</strong> (rev ${item.current_revision.revision_number}) - ${item.current_revision.behavior}
            </label>
          `).join("")}
        </div>
        <div class="btn-row" style="margin-top: 12px;">
          <button type="submit" class="btn-primary">建立並發布版本</button>
        </div>
      </form>
    `;

    const form = content.querySelector("#publish-ver-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const checkedBoxes = form.querySelectorAll("input[name='rev_id']:checked");
      const revIds = Array.from(checkedBoxes).map(b => b.value);
      if (revIds.length === 0) {
        alert("請至少選擇一個案例！");
        return;
      }

      try {
        const draftRes = await api(`/api/evaluations/sets/${setId}/versions`, {
          method: "POST",
          body: JSON.stringify({ case_revision_ids: revIds }),
        });
        const draft = draftRes.version;

        await api(`/api/evaluations/sets/${setId}/versions/${draft.set_version_id}/publish`, {
          method: "POST",
          body: JSON.stringify({ expected_etag: draft.etag }),
        });

        alert("題庫版本發布成功！此版本成員與 Manifest Hash 已永久鎖定。");
        closeContentModal();
        if (onSuccess) onSuccess();
      } catch (err) {
        alert(`發布失敗: ${err.message}`);
      }
    });
  } catch (err) {
    content.innerHTML = `<div class="error">讀取失敗: ${err.message}</div>`;
  }
}

function showImportModal(onSuccess) {
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
            <strong>驗證失敗！共 ${valRes.error_rows} 筆錯誤：</strong>
            <ul>${valRes.errors.map(err => `<li>第 ${err.row} 列: [${err.field}] ${err.message}</li>`).join("")}</ul>
          </div>
        `;
      } else {
        resultDiv.innerHTML = `
          <div class="alert alert-success">
            <strong>驗證通過！</strong> 共 ${valRes.valid_rows} 筆有效案例。
            ${valRes.similar_warnings.length > 0 ? `<br><small>提示：有 ${valRes.similar_warnings.length} 題在現有題庫中已有相似問題。</small>` : ""}
          </div>
          <button id="commit-import-btn" class="btn-primary" style="margin-top: 8px;">確認原子寫入題庫</button>
        `;

        const commitBtn = resultDiv.querySelector("#commit-import-btn");
        commitBtn.addEventListener("click", async () => {
          try {
            const commitRes = await api(`/api/evaluations/imports/${valRes.staged_import_id}/commit?owner_unit_id=${encodeURIComponent(owner_unit_id)}`, {
              method: "POST",
            });
            alert(`成功匯入 ${commitRes.total} 筆案例！`);
            closeContentModal();
            if (onSuccess) onSuccess();
          } catch (cErr) {
            alert(`提交失敗: ${cErr.message}`);
          }
        });
      }
    } catch (err) {
      resultDiv.innerHTML = `<div class="error">驗證請求失敗: ${err.message}</div>`;
    }
  });

  showContentModal(content);
}

function showExportModal() {
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

function showCandidateJobModal(onSuccess) {
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
          <strong>生成成功！</strong> 已生成 ${res.created_candidate_case_ids.length} 筆草稿候選題。<br>
          <small>消耗 Token: ${res.used_tokens} | 預估成本: $${res.estimated_cost_usd} USD</small>
        </div>
      `;
      if (onSuccess) onSuccess();
    } catch (err) {
      statusDiv.innerHTML = `<div class="error">生成失敗: ${err.message}</div>`;
    }
  });

  showContentModal(content);
}

async function renderRunsTab(container, allowed) {
  container.replaceChildren();
  const box = el("div", "content-box");
  box.innerHTML = `
    <h3>執行驗收</h3>
    <p class="text-muted">選擇題庫版本、正式版／候選版 Prompt 與模型，先預檢再啟動比較。</p>
    <div class="form-grid">
      <div class="form-group">
        <label for="run-set-version">評測題庫版本</label>
        <select id="run-set-version" class="form-select">
          <option value="">載入中...</option>
        </select>
      </div>
      <div class="form-group">
        <label for="baseline-prompt">基準（正式版）</label>
        <select id="baseline-prompt" class="form-select">
          <option value="">載入中...</option>
        </select>
        <p id="baseline-prompt-meta" class="metric-label"></p>
      </div>
      <div class="form-group">
        <label for="candidate-prompt">候選版</label>
        <select id="candidate-prompt" class="form-select">
          <option value="">載入中...</option>
        </select>
        <p id="candidate-prompt-meta" class="metric-label"></p>
      </div>
      <div class="form-group">
        <label for="target-model">模型</label>
        <select id="target-model" class="form-select">
          <option value="">載入中...</option>
        </select>
      </div>
      <div class="form-group">
        <label for="run-mode">評測模式</label>
        <select id="run-mode" class="form-select">
          <option value="REAL_RAG">真實檢索評測 — 固定知識版本</option>
          <option value="OFFLINE_BENCHMARK">離線基準評測</option>
        </select>
      </div>
      <div class="form-group">
        <label for="run-max-cases">最大題數（選填）</label>
        <input type="number" id="run-max-cases" class="form-input" placeholder="不限制或輸入數字">
      </div>
      <details class="bu-ops-note" id="run-advanced">
        <summary>進階資訊（技術識別）</summary>
        <p class="metric-label">預檢通過後會顯示 Manifest Hash 等技術欄位；日常操作不需手填版本代碼。</p>
        <div id="run-advanced-ids" class="metric-label"></div>
      </details>
      <div class="btn-row">
        <button id="preflight-btn" class="button-primary" type="button">執行預檢</button>
        <button id="start-run-btn" class="button-primary" type="button" style="display: none;">啟動驗收執行</button>
      </div>
    </div>
    <div id="preflight-results" style="margin-top: 16px;"></div>
  `;

  container.append(box);

  const select = box.querySelector("#run-set-version");
  const baselineSelect = box.querySelector("#baseline-prompt");
  const candidateSelect = box.querySelector("#candidate-prompt");
  const modelSelect = box.querySelector("#target-model");
  const baselineMeta = box.querySelector("#baseline-prompt-meta");
  const candidateMeta = box.querySelector("#candidate-prompt-meta");
  const advancedIds = box.querySelector("#run-advanced-ids");
  const preflightBtn = box.querySelector("#preflight-btn");
  const startRunBtn = box.querySelector("#start-run-btn");
  const resultsDiv = box.querySelector("#preflight-results");

  let resolvedPreflight = null;
  const promptOptionsByValue = new Map();

  function formatTaipei(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("zh-TW", {
        timeZone: "Asia/Taipei",
        hour12: false,
      });
    } catch {
      return String(iso);
    }
  }

  function promptOptionLabel(version) {
    const status = String(version.status || "").toUpperCase();
    const isOfficial = status === "ACTIVE";
    const kind = isOfficial ? "正式版" : "候選版";
    const name = version.display_name || version.version || version.version_id || "未命名";
    const updated = formatTaipei(version.activated_at || version.approved_at || version.created_at);
    return `${kind} · ${name} · ${status || "—"} · ${updated}`;
  }

  function syncPromptMeta(selectEl, metaEl) {
    const opt = promptOptionsByValue.get(selectEl.value);
    if (!opt) {
      metaEl.textContent = "";
      return;
    }
    metaEl.textContent = `版本代碼 ${opt.version || opt.version_id || "—"}｜更新 ${formatTaipei(opt.activated_at || opt.approved_at || opt.created_at)}`;
  }

  try {
    const setsRes = await api("/api/evaluations/sets");
    select.innerHTML = '<option value="">-- 請選擇題庫版本 --</option>';
    for (const s of setsRes.items || []) {
      const detail = await api(`/api/evaluations/sets/${s.set_id}`);
      for (const v of detail.versions || []) {
        select.innerHTML += `<option value="${v.set_version_id}">${s.name} - ${v.version}（${v.status}，${v.case_revision_ids.length} 題）</option>`;
      }
    }
  } catch (err) {
    select.innerHTML = '<option value="">無法載入題庫版本</option>';
  }

  try {
    const govData = await api("/api/governance/prompts");
    const item = (govData.items || [])[0];
    const promptId = item?.prompt?.prompt_id;
    const activeId = item?.active?.version_id;
    const versions = [];
    if (promptId) {
      const detail = await api(`/api/governance/prompts/${promptId}`);
      versions.push(...(detail.versions || []));
    } else if (item?.active) {
      versions.push(item.active);
    }
    baselineSelect.innerHTML = "";
    candidateSelect.innerHTML = "";
    promptOptionsByValue.clear();
    if (!versions.length) {
      baselineSelect.innerHTML = '<option value="default">default（無治理版本資料）</option>';
      candidateSelect.innerHTML = '<option value="default">default（無治理版本資料）</option>';
    } else {
      const sorted = [...versions].sort((a, b) => {
        const aActive = a.version_id === activeId || a.status === "ACTIVE" ? 0 : 1;
        const bActive = b.version_id === activeId || b.status === "ACTIVE" ? 0 : 1;
        if (aActive !== bActive) return aActive - bActive;
        return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      });
      for (const version of sorted) {
        const value = version.version || version.version_id;
        promptOptionsByValue.set(value, version);
        const baselineOpt = document.createElement("option");
        baselineOpt.value = value;
        baselineOpt.textContent = promptOptionLabel(version);
        baselineSelect.append(baselineOpt);
        const candidateOpt = document.createElement("option");
        candidateOpt.value = value;
        candidateOpt.textContent = promptOptionLabel(version);
        candidateSelect.append(candidateOpt);
      }
      const official = sorted.find((v) => v.version_id === activeId || v.status === "ACTIVE") || sorted[0];
      const candidate =
        sorted.find((v) => v !== official && String(v.status || "").toUpperCase() !== "ACTIVE") ||
        sorted.find((v) => v !== official) ||
        official;
      baselineSelect.value = official.version || official.version_id;
      candidateSelect.value = candidate.version || candidate.version_id;
    }
    syncPromptMeta(baselineSelect, baselineMeta);
    syncPromptMeta(candidateSelect, candidateMeta);
    baselineSelect.addEventListener("change", () => syncPromptMeta(baselineSelect, baselineMeta));
    candidateSelect.addEventListener("change", () => syncPromptMeta(candidateSelect, candidateMeta));
  } catch (err) {
    baselineSelect.innerHTML = '<option value="default">default</option>';
    candidateSelect.innerHTML = '<option value="candidate-v1.1">candidate-v1.1</option>';
  }

  try {
    const modelsRes = await api("/api/governance/models");
    const modelItems = modelsRes.items || [];
    modelSelect.innerHTML = "";
    const seen = new Set();
    for (const entry of modelItems) {
      const active = entry.active || {};
      const modelId = active.model_id;
      if (!modelId || seen.has(modelId)) continue;
      seen.add(modelId);
      const opt = document.createElement("option");
      opt.value = modelId;
      opt.textContent = `${modelId}（${active.status || "ACTIVE"} · ${active.provider || "model"}）`;
      modelSelect.append(opt);
    }
    if (!modelSelect.options.length) {
      modelSelect.innerHTML = '<option value="gemini-2.5-flash">gemini-2.5-flash</option>';
    }
  } catch (err) {
    modelSelect.innerHTML = '<option value="gemini-2.5-flash">gemini-2.5-flash</option>';
  }

  preflightBtn.addEventListener("click", async () => {
    const setVersionId = select.value;
    if (!setVersionId) {
      alert("請先選擇評測題庫版本");
      return;
    }
    const maxCasesVal = box.querySelector("#run-max-cases")?.value;
    const limits = maxCasesVal ? { max_cases: parseInt(maxCasesVal, 10) } : {};
    const baselinePrompt = (baselineSelect.value || "").trim() || "default";
    const candidatePrompt = (candidateSelect.value || "").trim() || baselinePrompt;
    const targetModel = (modelSelect.value || "").trim() || "gemini-2.5-flash";

    resultsDiv.innerHTML = '<div class="alert alert-info">正在執行預檢中...</div>';
    try {
      const res = await api("/api/evaluations/runs/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          set_version_id: setVersionId,
          baseline_target: {
            prompt_version: baselinePrompt,
            model_id: targetModel,
          },
          candidate_target: {
            prompt_version: candidatePrompt,
            model_id: targetModel,
          },
          limits: limits,
        }),
      });
      resolvedPreflight = res;
      if (res.is_valid) {
        resultsDiv.innerHTML = `
          <div class="alert alert-success">
            <strong>預檢通過</strong><br>
            • 案例題數: ${res.case_count} 題<br>
            • 預估耗費: $${res.estimated_cost_usd} USD（約 ${res.estimated_duration_seconds} 秒）
            ${res.warnings && res.warnings.length ? `<br>提醒: ${res.warnings.join("; ")}` : ""}
          </div>
        `;
        advancedIds.innerHTML = `
          基準 Manifest: <code>${res.resolved_baseline_manifest ? res.resolved_baseline_manifest.manifest_hash.slice(0, 16) : ""}…</code><br>
          候選 Manifest: <code>${res.resolved_candidate_manifest ? res.resolved_candidate_manifest.manifest_hash.slice(0, 16) : ""}…</code>
        `;
        startRunBtn.style.display = "inline-block";
      } else {
        resultsDiv.innerHTML = `
          <div class="alert alert-danger">
            <strong>預檢阻擋</strong><br>
            ${res.blocking_errors.join("<br>")}
          </div>
        `;
        startRunBtn.style.display = "none";
      }
    } catch (err) {
      resultsDiv.innerHTML = `<div class="alert alert-danger">預檢失敗: ${err.message || err}</div>`;
    }
  });

  startRunBtn.addEventListener("click", async () => {
    if (!resolvedPreflight) return;
    startRunBtn.disabled = true;
    startRunBtn.textContent = "執行評測中...";

    try {
      const maxCasesVal = box.querySelector("#run-max-cases")?.value;
      const limits = maxCasesVal ? { max_cases: parseInt(maxCasesVal, 10) } : {};
      const baselinePrompt = (baselineSelect.value || "").trim() || "default";
      const candidatePrompt = (candidateSelect.value || "").trim() || baselinePrompt;
      const targetModel = (modelSelect.value || "").trim() || "gemini-2.5-flash";
      const runMode = box.querySelector("#run-mode")?.value || "REAL_RAG";

      const res = await api("/api/evaluations/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          set_version_id: select.value,
          baseline_target: {
            prompt_version: baselinePrompt,
            model_id: targetModel,
          },
          candidate_target: {
            prompt_version: candidatePrompt,
            model_id: targetModel,
          },
          mode: runMode,
          limits: limits,
        }),
      });

      resultsDiv.innerHTML = `
        <div class="alert alert-success">
          <strong>評測執行已啟動／完成排程</strong><br>
          Run ID: <code>${res.run?.run_id || res.run_id || "—"}</code>｜狀態: ${res.run?.status || "—"}<br>
          可至「驗收結果」頁籤查看對比分析。<br>
          <span class="text-muted">注意：執行完成只代表評測跑完，不代表品質通過或發布閘道通過；請對照通過率、退步案例與門檻政策。</span>
        </div>
      `;
      startRunBtn.disabled = false;
      startRunBtn.textContent = "啟動驗收執行";
    } catch (err) {
      alert(`啟動評測失敗: ${err.message || err}`);
      startRunBtn.disabled = false;
      startRunBtn.textContent = "啟動驗收執行";
    }
  });
}

async function renderResultsTab(container, allowed) {
  container.replaceChildren();
  const box = el("div", "content-box");
  box.innerHTML = `
    <h3>驗收結果與版本比較 (Evaluation Results)</h3>
    <p class="metric-label">執行完成 ≠ 品質通過／閘道通過。請用下方通過率、退步案例與門檻政策判斷是否可發布。</p>
    <div id="results-summary-container"></div>
    <div class="table-responsive" style="margin-top: 20px;">
      <table class="data-table">
        <thead>
          <tr>
            <th>驗收執行 ID</th>
            <th>題庫版本 ID</th>
            <th>測試模式</th>
            <th>候選通過率</th>
            <th>覆蓋率</th>
            <th>實際成本 (USD)</th>
            <th>狀態</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="runs-table-body">
          <tr><td colspan="8">載入中...</td></tr>
        </tbody>
      </table>
    </div>
    <div id="case-comparison-container" style="margin-top: 24px;"></div>
  `;
  container.append(box);

  const tbody = box.querySelector("#runs-table-body");
  const summaryContainer = box.querySelector("#results-summary-container");
  const caseCompContainer = box.querySelector("#case-comparison-container");

  try {
    const runs = await api("/api/evaluations/runs");
    if (!runs || !runs.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-muted">目前尚無驗收執行紀錄。請至「執行驗收」頁籤發起新評測。</td></tr>';
      caseCompContainer.innerHTML = `
        <div class="callout">
          <strong>如何閱讀退步</strong>
          <p class="metric-label" style="margin:0.35rem 0 0">有 run 後，案例比對會標示「新增失敗 (Regression)」；若基準有答、候選空白，會顯示「退步：候選漏答」並在細節並排標紅。執行完成仍不代表品質／閘道通過。</p>
        </div>`;
      return;
    }

    const latestRun = runs[0];
    renderRunSummaryCards(summaryContainer, latestRun.summary);

    tbody.replaceChildren();
    for (const r of runs) {
      const tr = el("tr");
      const passRateStr = r.summary && r.summary.pass_rate !== null ? `${Math.round(r.summary.pass_rate * 100)}%` : "-";
      const coverageStr = r.summary ? `${Math.round(r.summary.coverage * 100)}%` : "-";

      tr.innerHTML = `
        <td><code>${r.run_id}</code></td>
        <td><code>${r.set_version_id.slice(0, 14)}...</code></td>
        <td>${r.mode}</td>
        <td><span class="badge ${r.summary && r.summary.pass_rate >= 0.9 ? "badge-success" : "badge-warning"}">${passRateStr}</span></td>
        <td>${coverageStr}</td>
        <td>$${r.actual_cost_usd}</td>
        <td><span class="badge ${r.status === "COMPLETED" ? "badge-success" : "badge-secondary"}">${r.status}</span></td>
        <td>
          <button class="btn-secondary btn-sm view-cases-btn">查看比對</button>
          <button class="btn-primary btn-sm eval-gate-btn" style="margin-left: 4px;">門檻判定</button>
        </td>
      `;

      tr.querySelector(".view-cases-btn").addEventListener("click", () => {
        renderRunSummaryCards(summaryContainer, r.summary);
        loadCaseComparison(caseCompContainer, r.run_id, allowed);
      });

      tr.querySelector(".eval-gate-btn").addEventListener("click", () => {
        showGateDecisionModal(r.run_id, r.candidate_manifest_hash, allowed);
      });

      tbody.append(tr);
    }

    // Default load latest run comparison
    await loadCaseComparison(caseCompContainer, latestRun.run_id, allowed);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-danger">載入執行清單失敗: ${err.message || err}</td></tr>`;
  }
}

function renderRunSummaryCards(container, summary) {
  if (!summary) {
    container.replaceChildren();
    return;
  }
  container.innerHTML = `
    <p class="metric-label" style="margin-bottom: 0.75rem;">下列摘要用來判斷「品質是否過關」；僅有執行紀錄不足以視為通過。</p>
    <div class="summary-cards-grid" style="display: flex; gap: 16px; margin-bottom: 20px;">
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #dc3545; background: #fff;">
        <div class="text-muted">新增失敗 (Regressions)</div>
        <h2 style="margin: 4px 0; color: #dc3545;">${summary.regressions ? summary.regressions.length : 0}</h2>
        <small>候選版不如基準版之案例</small>
      </div>
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #28a745; background: #fff;">
        <div class="text-muted">已修復 (Fixed)</div>
        <h2 style="margin: 4px 0; color: #28a745;">${summary.fixes ? summary.fixes.length : 0}</h2>
        <small>候選版成功改善之案例</small>
      </div>
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #ffc107; background: #fff;">
        <div class="text-muted">重大失敗 (Critical)</div>
        <h2 style="margin: 4px 0; color: #856404;">${summary.critical_failures ? summary.critical_failures.length : 0}</h2>
        <small>標記重大之失敗題數</small>
      </div>
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #17a2b8; background: #fff;">
        <div class="text-muted">完成比例</div>
        <h2 style="margin: 4px 0; color: #17a2b8;">${Math.round(summary.coverage * 100)}%</h2>
        <small>${summary.judged_cases} / ${summary.total_cases} 題已完成判定</small>
      </div>
    </div>
  `;
}

function executionOutcome(execution = {}) {
  const status = String(execution.status || "").toUpperCase();
  const hasInconclusiveMetric = (execution.metric_results || []).some(
    (metric) => String(metric.pass_status || "").toUpperCase() === "INCONCLUSIVE",
  );
  if (status === "FAILED" || status === "CANCELLED" || execution.passed == null || hasInconclusiveMetric) {
    return { label: "未判定", className: "badge-warning", pass: false, inconclusive: true };
  }
  return execution.passed
    ? { label: "PASS", className: "badge-success", pass: true, inconclusive: false }
    : { label: "FAIL", className: "badge-danger", pass: false, inconclusive: false };
}

async function loadCaseComparison(container, runId, allowed) {
  container.replaceChildren();
  const box = el("div", "sub-content-box");
  box.innerHTML = `
    <h4>案例比對清單 (Run: <code>${runId}</code>)</h4>
    <p class="metric-label">「新增失敗」= 基準通過但候選失敗（退步）；若候選答案為空而基準有答，屬漏答退步，請開細節並排比對。</p>
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>案例 ID</th>
            <th>基準版判定</th>
            <th>候選版判定</th>
            <th>比對差異</th>
            <th>失敗分類</th>
            <th>耗時 (ms)</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="case-comp-body">
          <tr><td colspan="7">載入案例中...</td></tr>
        </tbody>
      </table>
    </div>
  `;
  container.append(box);

  const tbody = box.querySelector("#case-comp-body");
  try {
    const cases = await api(`/api/evaluations/runs/${runId}/cases`);
    const baselineCases = {};
    const candidateCases = {};

    for (const c of cases) {
      if (c.target_side === "BASELINE") {
        baselineCases[c.case_revision_id] = c;
      } else {
        candidateCases[c.case_revision_id] = c;
      }
    }

    tbody.replaceChildren();
    const allRevs = Object.keys(candidateCases);
    if (!allRevs.length) {
      tbody.innerHTML = '<tr><td colspan="7">無案例紀錄</td></tr>';
      return;
    }

    for (const revId of allRevs) {
      const c = candidateCases[revId];
      const b = baselineCases[revId] || {};

      const baselineOutcome = executionOutcome(b);
      const candidateOutcome = executionOutcome(c);
      let diffTag = '<span class="badge badge-secondary">相同</span>';
      if (baselineOutcome.pass && candidateOutcome.inconclusive) {
        diffTag = '<span class="badge badge-warning">退步：候選未判定（不計入通過）</span>';
      } else if (baselineOutcome.pass && !candidateOutcome.pass) {
        const missedAnswer = Boolean((b.answer || "").trim()) && !(c.answer || "").trim();
        diffTag = missedAnswer
          ? '<span class="badge badge-danger">退步：候選漏答</span>'
          : '<span class="badge badge-danger">新增失敗 (Regression)</span>';
      } else if (!baselineOutcome.pass && !baselineOutcome.inconclusive && candidateOutcome.pass) {
        diffTag = '<span class="badge badge-success">已修復 (Fixed)</span>';
      } else if (baselineOutcome.inconclusive || candidateOutcome.inconclusive) {
        diffTag = '<span class="badge badge-warning">未判定：不計入通過</span>';
      }

      const tr = el("tr");
      tr.innerHTML = `
        <td><code>${c.case_id}</code></td>
        <td><span class="badge ${baselineOutcome.className}">${baselineOutcome.label}</span></td>
        <td><span class="badge ${candidateOutcome.className}">${candidateOutcome.label}</span></td>
        <td>${diffTag}</td>
        <td>${c.failure_classification || "-"}</td>
        <td>${c.latency_ms}</td>
        <td>
          <button class="btn-secondary btn-sm inspect-btn">檢視細節與覆核</button>
        </td>
      `;

      tr.querySelector(".inspect-btn").addEventListener("click", () => {
        showExecutionDetailModal(runId, c, b, allowed);
      });

      tbody.append(tr);
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-danger">載入比對案例失敗: ${err.message || err}</td></tr>`;
  }
}

function showExecutionDetailModal(runId, candidateExec, baselineExec, allowed) {
  const baselineOutcome = executionOutcome(baselineExec);
  const candidateOutcome = executionOutcome(candidateExec);
  const modalContent = el("div", "execution-modal-content");
  modalContent.innerHTML = `
    <h3>案例執行細節與人工覆核</h3>
    <div style="display: flex; gap: 16px; margin-bottom: 16px;">
      <div style="flex: 1; background: #f8f9fa; padding: 12px; border-radius: 4px;">
        <strong>【基準版回答】</strong>
        <p style="white-space: pre-wrap; margin-top: 8px;">${baselineExec.answer || "(無回答)"}</p>
      </div>
      <div style="flex: 1; background: #f8f9fa; padding: 12px; border-radius: 4px;${!((candidateExec.answer || "").trim()) && (baselineExec.answer || "").trim() ? "border:2px solid #dc3545;" : ""}">
        <strong>【候選版回答】${!((candidateExec.answer || "").trim()) && (baselineExec.answer || "").trim() ? " <span class=\"badge badge-danger\">漏答</span>" : ""}</strong>
        <p style="white-space: pre-wrap; margin-top: 8px;">${candidateExec.answer || "(無回答)"}</p>
      </div>
    </div>
    <p class="callout ${candidateOutcome.inconclusive ? "warning" : ""}"><strong>候選判定：${candidateOutcome.label}</strong>。執行完成不等於品質通過；ERROR／未判定一律不計入通過。${candidateExec.error_detail ? `原因：${candidateExec.error_detail}` : ""}</p>
    <h4>指標判定結果 (Candidate Metrics)</h4>
    <table class="data-table" style="margin-bottom: 16px;">
      <thead>
        <tr>
          <th>指標</th>
          <th>判定</th>
          <th>分數</th>
          <th>理由與依據</th>
        </tr>
      </thead>
      <tbody>
        ${(candidateExec.metric_results || []).map(m => `
          <tr>
            <td><code>${m.metric_id}</code></td>
            <td><span class="badge ${m.pass_status === "PASS" ? "badge-success" : m.pass_status === "FAIL" ? "badge-danger" : m.pass_status === "INCONCLUSIVE" ? "badge-warning" : "badge-secondary"}">${m.pass_status}</span></td>
            <td>${m.score !== null ? m.score : "-"}</td>
            <td>${m.reason || "-"}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
    <div class="review-section" style="background: #eef2f7; padding: 12px; border-radius: 4px;">
      <strong>人工覆核決策 (Human Review)</strong>
      <p class="text-muted" style="margin-top: 4px;">覆核將以 Append-only 方式記錄決策歷史，不竄改原始觀測數據。</p>
      <div class="form-group" style="margin-top: 8px;">
        <label>選擇指標</label>
        <select id="review-metric-select" class="form-select">
          ${(candidateExec.metric_results || []).map(m => `<option value="${m.metric_id}">${m.metric_id}</option>`).join("")}
        </select>
      </div>
      <div class="form-group">
        <label>覆核決策</label>
        <select id="review-decision-select" class="form-select">
          <option value="PASS">覆核為通過 (PASS)</option>
          <option value="FAIL">覆核為失敗 (FAIL)</option>
        </select>
      </div>
      <div class="form-group">
        <label>覆核理由</label>
        <input type="text" id="review-reason-input" class="form-input" placeholder="請填寫覆核理由...">
      </div>
      <div class="btn-row">
        <button id="submit-review-btn" class="btn-primary">送出覆核決策</button>
      </div>
    </div>
    ${!candidateExec.passed && allowed.has("ops.evals.write") ? `
    <div class="qc-section" style="margin-top: 16px; padding: 12px; border: 1px dashed #ced4da; border-radius: 4px; background: #fff;">
      <strong>營運閉環 (GE-4 Quality Case Loop)</strong>
      <p class="text-muted" style="margin-top: 4px;">本案例判定未通過，可直接轉為品質改善案件進行後續追蹤與複測。</p>
      <button id="promote-qc-btn" class="btn-secondary">轉為品質改善案件 (Create Quality Case)</button>
    </div>` : ""}
  `;

  const qcBtn = modalContent.querySelector("#promote-qc-btn");
  if (qcBtn) {
    qcBtn.addEventListener("click", async () => {
      const rootCause = prompt("請輸入問題根本原因 (Root Cause)：", candidateExec.failure_classification || "評測判定未達標");
      if (!rootCause) return;
      try {
        const qcRes = await api(`/api/evaluations/runs/${runId}/cases/${candidateExec.execution_id}/quality-case`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ root_cause: rootCause.trim() }),
        });
        const caseId = qcRes.quality_case?.quality_case_id || qcRes.quality_case_id;
        if (caseId && window.confirm(`已建立改善案件 ${caseId}。是否立即開啟案件？`)) {
          closeContentModal();
          void navigateTo(
            "quality",
            withReturnTo(
              { caseId, tab: "cases" },
              "evaluations",
              { tab: "results", runId },
            ),
          );
          return;
        }
        alert(`已成功建立品質改善案件：${caseId || "(未知 ID)"}`);
      } catch (err) {
        alert(`建立案件失敗: ${err.message || err}`);
      }
    });
  }

  const submitBtn = modalContent.querySelector("#submit-review-btn");
  submitBtn.addEventListener("click", async () => {
    const reason = modalContent.querySelector("#review-reason-input").value.trim();
    if (!reason) {
      alert("請填寫覆核理由");
      return;
    }
    const metricId = modalContent.querySelector("#review-metric-select")?.value;
    if (!metricId) {
      alert("請選擇要覆核的指標");
      return;
    }
    const decision = modalContent.querySelector("#review-decision-select").value;

    try {
      await api(`/api/evaluations/runs/${runId}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          execution_id: candidateExec.execution_id,
          metric_id: metricId,
          decision: decision,
          reason: reason,
        }),
      });
      alert("覆核決策已儲存！");
      closeContentModal();
    } catch (err) {
      alert(`覆核失敗: ${err.message || err}`);
    }
  });

  showContentModal(modalContent);
}

async function showGateDecisionModal(runId, targetManifestHash, allowed) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>正在執行門檻判定 (Evaluating Quality Gate)...</p>";
  showContentModal(content);

  try {
    const res = await api("/api/evaluations/gate-decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        policy_id: "default-gate-policy",
        run_id: runId,
        target_manifest_hash: targetManifestHash,
      }),
    });

    const dec = res.decision;
    const statusBadge = dec.status === "PASS"
      ? '<span class="badge badge-success">✅ 通過 (PASS)</span>'
      : dec.status === "BLOCK"
      ? '<span class="badge badge-danger">❌ 阻擋 (BLOCK)</span>'
      : '<span class="badge badge-warning">⚠️ 需審核 (REVIEW_REQUIRED)</span>';

    content.innerHTML = `
      <h3>發布門檻判定結果 (Quality Gate Decision)</h3>
      <div class="meta-grid" style="margin-bottom: 16px;">
        <div><strong>判定 ID:</strong> <code>${dec.decision_id}</code></div>
        <div><strong>政策:</strong> ${dec.policy_id} (v${dec.policy_version})</div>
        <div><strong>判定狀態:</strong> ${statusBadge}</div>
        <div><strong>運作模式:</strong> ${dec.mode}</div>
        <div><strong>候選 Hash:</strong> <code>${dec.target_manifest_hash ? dec.target_manifest_hash.slice(0, 16) : ""}...</code></div>
        <div><strong>判定時間:</strong> ${dec.decided_at}</div>
      </div>
      <div class="section-block">
        <h4>判定理由與分析</h4>
        <div class="content-box">${dec.reason}</div>
      </div>
      <div class="section-block">
        <h4>指標門檻檢核細項</h4>
        <ul>
          ${(dec.rule_results || []).map(r => `
            <li>
              <strong>${r.rule_name}:</strong>
              ${r.passed ? "✅ 符合" : "❌ 不符"}
              <span class="text-muted">(${r.details || ""})</span>
            </li>
          `).join("") || "<li>無細部規則紀錄</li>"}
        </ul>
      </div>
      ${(dec.blocking_reasons && dec.blocking_reasons.length) ? `
      <div class="alert alert-danger" style="margin-top: 12px;">
        <strong>阻擋原因：</strong><br>
        ${dec.blocking_reasons.join("<br>")}
      </div>` : ""}
      <div id="waiver-section" style="margin-top: 16px;"></div>
    `;

    const waiverSection = content.querySelector("#waiver-section");
    if (dec.status !== "PASS" && allowed.has("ops.evals.write")) {
      const waiverBtn = el("button", "btn-secondary", "申請例外放行 (Request Waiver)");
      waiverBtn.addEventListener("click", async () => {
        const waiverReason = prompt("請輸入申請例外放行原因 (須經雙人審核)：");
        if (!waiverReason) return;
        try {
          const excRes = await api(`/api/evaluations/gate-decisions/${dec.decision_id}/exceptions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              reason: waiverReason.trim(),
              validity_hours: 24,
            }),
          });
          alert(`例外申請已送出 (ID: ${excRes.exception.exception_id})，狀態: ${excRes.exception.status}`);
          closeContentModal();
        } catch (err) {
          alert(`申請例外放行失敗: ${err.message || err}`);
        }
      });
      waiverSection.append(waiverBtn);
    }
  } catch (err) {
    content.innerHTML = `<div class="error">門檻判定失敗: ${err.message || err}</div>`;
  }
}

async function renderGatesTab(container, allowed) {
  container.replaceChildren();
  const box = el("div", "content-box");
  box.innerHTML = `
    <h3>發布門檻與治理 (Quality Gates & Impact)</h3>
    <p class="text-muted">管理品質發布門檻政策、執行知識變更影響分析與定期回歸排程。</p>

    <div class="section-block" style="margin-top: 20px;">
      <h4>1. 預設發布門檻政策 (Gate Policy)</h4>
      <div id="gate-policy-container" style="background: #fdfdfd; padding: 16px; border: 1px solid #e2e8f0; border-radius: 6px;">
        <p>載入政策資訊中...</p>
      </div>
    </div>

    <div class="section-block" style="margin-top: 24px;">
      <h4>2. 知識變更影響分析 (Knowledge Impact Analysis)</h4>
      <p class="text-muted">當知識文件或 FAQ 異動時，分析受影響的驗收題庫案例與版本。</p>
      <form id="impact-form" class="form-grid">
        <div class="form-group">
          <label>來源類型</label>
          <select id="impact-source-type" class="form-select">
            <option value="DOCUMENT">知識文件 (DOCUMENT)</option>
            <option value="FAQ">常見問答 (FAQ)</option>
          </select>
        </div>
        <div class="form-group">
          <label>來源 ID *</label>
          <input type="text" id="impact-source-id" class="form-input" required placeholder="例：doc_pwd_policy 或 faq_001" value="doc_pwd_policy">
        </div>
        <div class="btn-row">
          <button type="submit" class="btn-primary">分析變更影響</button>
        </div>
      </form>
      <div id="impact-result" style="margin-top: 12px;"></div>
    </div>

    <div class="section-block" style="margin-top: 24px;">
      <h4>3. 定期回歸排程 (Evaluation Schedules)</h4>
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>排程 ID</th>
              <th>名稱</th>
              <th>題庫版本 ID</th>
              <th>執行頻率</th>
              <th>預算上限 (USD)</th>
              <th>狀態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="schedules-tbody">
            <tr><td colspan="7">載入排程中...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
  container.append(box);

  // 1. Load Policy
  const policyContainer = box.querySelector("#gate-policy-container");
  const loadPolicy = async () => {
    try {
      const res = await api("/api/evaluations/gate-policies/default-gate-policy");
      if (res.error) {
        policyContainer.innerHTML = `<div class="text-muted">${res.error}</div>`;
        return;
      }
      const p = res.policy;
      const v = (res.versions || [])[0] || {};
      const isEnforce = v.mode === "ENFORCE";

      policyContainer.innerHTML = `
        <div class="meta-grid">
          <div><strong>政策 ID:</strong> <code>${p.policy_id}</code></div>
          <div><strong>政策名稱:</strong> ${p.name}</div>
          <div><strong>目前版本:</strong> v${p.current_version} (生效版本: v${p.active_version})</div>
          <div><strong>運作模式:</strong> <span class="badge ${isEnforce ? "badge-danger" : "badge-warning"}">${v.mode || "REPORT_ONLY"}</span></div>
          <div><strong>最低覆蓋率要求:</strong> ${(v.minimum_coverage ?? 1.0) * 100}%</div>
          <div><strong>最低通過率要求:</strong> ${(v.minimum_pass_rate ?? 0.95) * 100}%</div>
          <div><strong>重大失敗容忍度:</strong> ${v.critical_rule || "ZERO_TOLERANCE"} (零容忍)</div>
          <div><strong>最大退步案例數:</strong> ${v.max_regression_count ?? 0} 題</div>
        </div>
        ${allowed.has("ops.evals.gates.manage") ? `
        <div style="margin-top: 12px;">
          <button id="toggle-mode-btn" class="btn-secondary">
            ${isEnforce ? "切換為僅產報告 (REPORT_ONLY)" : "切換為強制阻擋 (ENFORCE)"}
          </button>
        </div>` : ""}
      `;

      const toggleBtn = policyContainer.querySelector("#toggle-mode-btn");
      if (toggleBtn) {
        toggleBtn.addEventListener("click", async () => {
          const newMode = isEnforce ? "REPORT_ONLY" : "ENFORCE";
          try {
            await api(`/api/evaluations/gate-policies/${p.policy_id}/versions/${v.version}/activate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ mode: newMode }),
            });
            alert(`門檻政策已切換為 ${newMode} 模式！`);
            loadPolicy();
          } catch (err) {
            alert(`模式切換失敗: ${err.message || err}`);
          }
        });
      }
    } catch (err) {
      policyContainer.innerHTML = `<div class="error">載入門檻政策失敗: ${err.message || err}</div>`;
    }
  };
  await loadPolicy();

  // 2. Impact Form
  const impactForm = box.querySelector("#impact-form");
  const impactResult = box.querySelector("#impact-result");
  impactForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sType = box.querySelector("#impact-source-type").value;
    const sId = box.querySelector("#impact-source-id").value.trim();
    impactResult.innerHTML = "<p>分析中...</p>";
    try {
      const res = await api(`/api/evaluations/source-impacts?source_type=${encodeURIComponent(sType)}&source_id=${encodeURIComponent(sId)}`);
      const imp = res.impact;
      impactResult.innerHTML = `
        <div class="alert ${imp.affected_case_ids.length > 0 ? "alert-warning" : "alert-success"}">
          <strong>分析完成：</strong><br>
          • 受影響驗收案例數: ${imp.affected_case_ids.length} 題 ${imp.affected_case_ids.length ? `(ID: <code>${imp.affected_case_ids.join(", ")}</code>)` : ""}<br>
          • 需複核案例數 (Requires Review): ${imp.requires_review_count} 題<br>
          • 受影響已發布題庫版本: ${imp.affected_set_version_ids.length ? imp.affected_set_version_ids.map(id => `<code>${id}</code>`).join(", ") : "無"}<br>
          • 是否直接衝擊線上 Active Manifest: <strong>${imp.has_active_manifest_impact ? "⚠️ 是 (需優先重測)" : "否"}</strong>
        </div>
      `;
    } catch (err) {
      impactResult.innerHTML = `<div class="error">分析失敗: ${err.message || err}</div>`;
    }
  });

  // 3. Schedules
  const schedTbody = box.querySelector("#schedules-tbody");
  const loadSchedules = async () => {
    try {
      const schedules = await api("/api/evaluations/schedules");
      if (!schedules || !schedules.length) {
        schedTbody.innerHTML = '<tr><td colspan="7" class="text-muted">目前尚無排程任務。</td></tr>';
        return;
      }
      schedTbody.replaceChildren();
      for (const s of schedules) {
        const tr = el("tr");
        tr.innerHTML = `
          <td><code>${s.schedule_id}</code></td>
          <td>${s.name}</td>
          <td><code>${(s.set_version_id || "").slice(0, 14)}...</code></td>
          <td>${s.frequency}</td>
          <td>$${s.budget_limit_usd}</td>
          <td><span class="badge ${s.is_enabled ? "badge-success" : "badge-secondary"}">${s.is_enabled ? "啟用中" : "已停用"}</span></td>
          <td>
            ${allowed.has("ops.evals.write") ? `
              <button class="btn-sm btn-link toggle-sched-btn">${s.is_enabled ? "停用" : "啟用"}</button>
            ` : "-"}
          </td>
        `;

        const toggleBtn = tr.querySelector(".toggle-sched-btn");
        if (toggleBtn) {
          toggleBtn.addEventListener("click", async () => {
            try {
              await api(`/api/evaluations/schedules/${s.schedule_id}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ is_enabled: !s.is_enabled }),
              });
              loadSchedules();
            } catch (err) {
              alert(`更新排程失敗: ${err.message || err}`);
            }
          });
        }

        schedTbody.append(tr);
      }
    } catch (err) {
      schedTbody.innerHTML = `<tr><td colspan="7" class="text-danger">載入排程失敗: ${err.message || err}</td></tr>`;
    }
  };
  await loadSchedules();
}

export const evaluationsPage = createPageController({
  enter: async () => renderEvaluations(),
  update: async () => renderEvaluations(),
  leave: async () => {},
});
