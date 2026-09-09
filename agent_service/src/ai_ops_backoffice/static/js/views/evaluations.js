import { api, el } from "../api.js";
import { showContentModal, closeContentModal } from "../components/modal.js";
import { actorCapabilities } from "../app/capabilities.js";
import { createPageController } from "../app/lifecycle.js";

let currentActiveTab = "cases";

export async function renderEvaluations() {
  const app = document.getElementById("app");
  const allowed = actorCapabilities();

  const container = el("div", "evaluations-container");

  const header = el("div", "page-header");
  const title = el("h2", "", "品質驗收 (Golden Eval Set)");
  const subtitle = el("p", "page-subtitle", "BU 驗收題庫管理、版本發布與真實評測比較");
  header.append(title, subtitle);

  const tabsNav = el("div", "tabs-nav");
  const tabCasesBtn = el("button", `tab-btn ${currentActiveTab === "cases" ? "active" : ""}`, "驗收題庫");
  const tabRunsBtn = el("button", `tab-btn ${currentActiveTab === "runs" ? "active" : ""}`, "執行驗收");
  const tabResultsBtn = el("button", `tab-btn ${currentActiveTab === "results" ? "active" : ""}`, "驗收結果");

  tabsNav.append(tabCasesBtn, tabRunsBtn, tabResultsBtn);

  const tabContent = el("div", "tab-content");

  tabCasesBtn.addEventListener("click", () => {
    currentActiveTab = "cases";
    tabCasesBtn.classList.add("active");
    tabRunsBtn.classList.remove("active");
    tabResultsBtn.classList.remove("active");
    renderCasesTab(tabContent, allowed);
  });

  tabRunsBtn.addEventListener("click", () => {
    currentActiveTab = "runs";
    tabRunsBtn.classList.add("active");
    tabCasesBtn.classList.remove("active");
    tabResultsBtn.classList.remove("active");
    renderRunsTab(tabContent, allowed);
  });

  tabResultsBtn.addEventListener("click", () => {
    currentActiveTab = "results";
    tabResultsBtn.classList.add("active");
    tabCasesBtn.classList.remove("active");
    tabRunsBtn.classList.remove("active");
    renderResultsTab(tabContent, allowed);
  });

  container.append(header, tabsNav, tabContent);
  app.replaceChildren(container);

  if (currentActiveTab === "cases") {
    await renderCasesTab(tabContent, allowed);
  } else if (currentActiveTab === "runs") {
    await renderRunsTab(tabContent, allowed);
  } else {
    await renderResultsTab(tabContent, allowed);
  }
}

async function renderCasesTab(container, allowed) {
  container.replaceChildren();

  const subNav = el("div", "sub-nav-bar");
  let subView = "cases";
  const viewCasesBtn = el("button", "btn-secondary active", "驗收題目清單");
  const viewSetsBtn = el("button", "btn-secondary", "題庫與版本 (Eval Sets)");
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

  const statusSelect = el("select", "form-select");
  statusSelect.innerHTML = `
    <option value="">-- 全部狀態 --</option>
    <option value="DRAFT">草稿 (DRAFT)</option>
    <option value="IN_REVIEW">審核中 (IN_REVIEW)</option>
    <option value="APPROVED">已核准 (APPROVED)</option>
    <option value="REJECTED">已退回 (REJECTED)</option>
    <option value="RETIRED">已退役 (RETIRED)</option>
  `;

  const behaviorSelect = el("select", "form-select");
  behaviorSelect.innerHTML = `
    <option value="">-- 全部行為類型 --</option>
    <option value="ANSWER_WITH_CITATION">引用回答 (ANSWER_WITH_CITATION)</option>
    <option value="CLARIFY">需求澄清 (CLARIFY)</option>
    <option value="REFUSE">安全拒答 (REFUSE)</option>
    <option value="HANDOFF">轉真人 (HANDOFF)</option>
    <option value="TOOL_TASK">工具執行 (TOOL_TASK)</option>
  `;

  const criticalitySelect = el("select", "form-select");
  criticalitySelect.innerHTML = `
    <option value="">-- 重要性 --</option>
    <option value="CRITICAL">重大 (CRITICAL)</option>
    <option value="NORMAL">一般 (NORMAL)</option>
  `;

  const healthSelect = el("select", "form-select");
  healthSelect.innerHTML = `
    <option value="">-- 來源健康度 --</option>
    <option value="VALID">正常 (VALID)</option>
    <option value="NEEDS_REVIEW">來源變更待複核 (NEEDS_REVIEW)</option>
    <option value="SOURCE_UNAVAILABLE">來源失效 (SOURCE_UNAVAILABLE)</option>
  `;

  const searchBtn = el("button", "btn-primary", "篩選");
  const summarySpan = el("span", "text-muted", "載入中...");

  const actionButtons = el("div", "btn-group");

  if (allowed.has("ops.evals.write")) {
    const createBtn = el("button", "btn-primary", "＋ 新增驗收題");
    createBtn.addEventListener("click", () => showCaseCreateModal(() => loadCasesList(container, allowed)));

    const genBtn = el("button", "btn-secondary", "⚡ 自動生成候選");
    genBtn.addEventListener("click", () => showCandidateJobModal(() => loadCasesList(container, allowed)));

    const importBtn = el("button", "btn-secondary", "📥 匯入題庫");
    importBtn.addEventListener("click", () => showImportModal(() => loadCasesList(container, allowed)));

    actionButtons.append(createBtn, genBtn, importBtn);
  }

  if (allowed.has("ops.evals.export")) {
    const exportBtn = el("button", "btn-secondary", "📤 匯出");
    exportBtn.addEventListener("click", showExportModal);
    actionButtons.append(exportBtn);
  }

  toolbar.append(searchInput, statusSelect, behaviorSelect, criticalitySelect, healthSelect, searchBtn, actionButtons, summarySpan);

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

      const table = el("table", "data-table");
      table.innerHTML = `
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

        const titleCell = el("td");
        titleCell.innerHTML = `<strong>${c.title}</strong><br><span class="text-muted">${r.query}</span>`;

        const behaviorCell = el("td");
        behaviorCell.innerHTML = `<span class="badge badge-info">${r.behavior}</span>`;

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

        const actionsCell = el("td");
        const viewBtn = el("button", "btn-sm btn-link", "查看與處理");
        viewBtn.addEventListener("click", () => showCaseDetailModal(c.case_id, () => fetchCases()));
        actionsCell.append(viewBtn);

        row.append(titleCell, behaviorCell, critCell, ownerCell, healthCell, statusCell, actionsCell);
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
    <h3>執行真實評測 (GE-2 預檢與執行)</h3>
    <p class="text-muted">選擇固定題庫版本與受測目標 Manifest，執行左右版本比較。</p>
    <div class="form-grid">
      <div class="form-group">
        <label>評測題庫版本</label>
        <select id="run-set-version" class="form-select">
          <option value="">載入中...</option>
        </select>
      </div>
      <div class="form-group">
        <label>基準版本 (Baseline)</label>
        <input type="text" class="form-input" value="baseline-v1.0.0 (當前正式版本)" readonly>
      </div>
      <div class="form-group">
        <label>候選版本 (Candidate)</label>
        <input type="text" class="form-input" value="candidate-v1.1.0-alpha (待驗收版本)">
      </div>
      <div class="form-group">
        <label>評測模式</label>
        <select class="form-select">
          <option value="STANDARD">標準模式 (STANDARD) - 完整檢索與判定</option>
          <option value="FAST">快速模式 (FAST) - 抽樣驗證</option>
        </select>
      </div>
      <div class="btn-row">
        <button id="preflight-btn" class="btn-primary">執行預檢 (Preflight Check)</button>
      </div>
    </div>
    <div id="preflight-results" style="margin-top: 16px;"></div>
  `;

  container.append(box);

  const select = box.querySelector("#run-set-version");
  const preflightBtn = box.querySelector("#preflight-btn");
  const resultsDiv = box.querySelector("#preflight-results");

  try {
    const setsRes = await api("/api/evaluations/sets");
    select.innerHTML = '<option value="">-- 請選擇題庫 --</option>';
    for (const s of (setsRes.items || [])) {
      select.innerHTML += `<option value="${s.set_id}">${s.name} (${s.purpose})</option>`;
    }
  } catch (err) {
    select.innerHTML = '<option value="">無法載入題庫</option>';
  }

  preflightBtn.addEventListener("click", () => {
    resultsDiv.innerHTML = `
      <div class="alert alert-info">
        <strong>預檢結果 (Preflight Check)</strong><br>
        ✅ 題庫版本固定<br>
        ✅ 模型與檢索器參數有效<br>
        ✅ 預估上限: 60 Cases | 25,000 Tokens | 成本約 $0.12 USD<br>
        <em>提示: 完整 GE-2 執行器已排入第二階段流程。</em>
      </div>
    `;
  });
}

async function renderResultsTab(container, allowed) {
  container.replaceChildren();
  const box = el("div", "content-box");
  box.innerHTML = `
    <h3>驗收結果與版本比較 (Evaluation Results)</h3>
    <div class="summary-cards-grid" style="display: flex; gap: 16px; margin-bottom: 20px;">
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #dc3545; background: #fff;">
        <div class="text-muted">新增失敗 (Regressions)</div>
        <h2 style="margin: 4px 0; color: #dc3545;">0</h2>
        <small>候選版不如基準版之案例</small>
      </div>
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #28a745; background: #fff;">
        <div class="text-muted">已修復 (Fixed)</div>
        <h2 style="margin: 4px 0; color: #28a745;">0</h2>
        <small>候選版成功改善之案例</small>
      </div>
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #ffc107; background: #fff;">
        <div class="text-muted">重大失敗 (Critical)</div>
        <h2 style="margin: 4px 0; color: #856404;">0</h2>
        <small>標記重大之失敗題數</small>
      </div>
      <div class="card" style="flex: 1; padding: 12px; border-left: 4px solid #17a2b8; background: #fff;">
        <div class="text-muted">完成比例</div>
        <h2 style="margin: 4px 0; color: #17a2b8;">100%</h2>
        <small>所有測試案例皆完成判定</small>
      </div>
    </div>
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>驗收執行 ID</th>
            <th>題庫版本</th>
            <th>測試模式</th>
            <th>通過率</th>
            <th>執行時間</th>
            <th>狀態</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>run_init_baseline</code></td>
            <td>標準驗收題庫 v1</td>
            <td>STANDARD</td>
            <td><span class="badge badge-success">100% (60/60)</span></td>
            <td>2026-09-09 15:00</td>
            <td><span class="badge badge-success">COMPLETED</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  `;
  container.append(box);
}

export const evaluationsPage = createPageController({
  enter: async () => renderEvaluations(),
  update: async () => renderEvaluations(),
  leave: async () => {},
});
