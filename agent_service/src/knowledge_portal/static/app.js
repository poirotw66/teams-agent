const state = {
  documents: [],
  selectedDocumentId: null,
};

function encodePortalHeaderValue(value) {
  return encodeURIComponent(value);
}

function identityHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Portal-User-Id": document.getElementById("userId").value.trim(),
    "X-Portal-User-Name": encodePortalHeaderValue(
      document.getElementById("userName").value.trim(),
    ),
    "X-Portal-Role": document.getElementById("userRole").value,
    "X-Portal-Owner-Units": "IT Service Desk",
  };
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  toast.style.background = isError ? "#b91c1c" : "#1f2933";
  setTimeout(() => toast.classList.add("hidden"), 3500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...identityHeaders(), ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload.detail?.message || payload.detail || "操作失敗";
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return payload;
}

function switchView(viewName) {
  document.querySelectorAll(".view").forEach((node) => node.classList.remove("active"));
  document.querySelectorAll(".nav button").forEach((node) => node.classList.remove("active"));
  document.getElementById(`view-${viewName}`).classList.add("active");
  document.querySelector(`[data-view="${viewName}"]`).classList.add("active");
}

async function loadDashboard() {
  const dashboard = await api("/api/dashboard");
  const totalDocs = state.documents.length;
  const publishedDocs = state.documents.filter((doc) => doc.status === "PUBLISHED").length;
  document.getElementById("dashboardCards").innerHTML = `
    <div class="card"><span>知識文件</span><strong>${totalDocs}</strong></div>
    <div class="card"><span>已發布</span><strong>${publishedDocs}</strong></div>
    <div class="card"><span>我的草稿</span><strong>${dashboard.my_drafts}</strong></div>
    <div class="card"><span>待審核</span><strong>${dashboard.pending_review}</strong></div>
    <div class="card"><span>發布失敗</span><strong>${dashboard.publish_failed}</strong></div>
    <div class="card"><span>正式版本</span><strong>${dashboard.active_release_id || "尚未發布"}</strong></div>
  `;
}

async function loadDocuments() {
  const payload = await api("/api/documents");
  state.documents = payload.items || [];
  const list = document.getElementById("documentList");
  if (!state.documents.length) {
    list.innerHTML = "<p>尚無知識文件。請到「新增／更新」建立第一份草稿。</p>";
    return;
  }
  list.innerHTML = state.documents.map((doc) => `
    <div class="doc-row">
      <div>
        <strong>${doc.title}</strong>
        <div>${doc.owner_unit_id} · 更新 ${new Date(doc.updated_at).toLocaleString("zh-TW")}</div>
      </div>
      <div>
        <span class="status ${doc.status}">${doc.status}</span>
        <button class="secondary" data-open-doc="${doc.document_id}">查看</button>
      </div>
    </div>
  `).join("");
  list.querySelectorAll("[data-open-doc]").forEach((button) => {
    button.addEventListener("click", () => openDocument(button.dataset.openDoc));
  });
}

function renderIssues(issues = []) {
  if (!issues.length) return "<p>未發現品質問題。</p>";
  return `<ul>${issues.map((issue) => `
    <li class="issue ${issue.severity.toLowerCase()}">
      [${issue.severity}] ${issue.message}
    </li>`).join("")}</ul>`;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function stripFrontMatter(content) {
  if (!content || !content.trimStart().startsWith("---")) return content || "";
  const end = content.indexOf("---", 3);
  if (end === -1) return content;
  return content.slice(end + 3).trim();
}

function renderPublishedDetail(document, published) {
  if (!published) {
    return "<p>尚無正式版本內容。</p>";
  }
  const body = stripFrontMatter(published.canonical_content || "");
  const preview = body.length > 1200 ? `${body.slice(0, 1200)}\n…` : body;
  const audience = document.audience_type === "ALL_EMPLOYEES"
    ? "全體員工"
    : (document.audience_group_ids || []).join(", ") || "特定群組";
  return `
    <h4>正式版本</h4>
    <p>版本 ${published.version_number} · 生效 ${published.effective_at} · 下次檢視 ${published.review_due_at}</p>
    <p>擁有單位：${escapeHtml(document.owner_unit_id)} · 適用範圍：${escapeHtml(audience)}</p>
    ${document.summary ? `<p>${escapeHtml(document.summary)}</p>` : ""}
    <pre class="content-preview">${escapeHtml(preview)}</pre>
  `;
}

async function loadTestCases(documentId) {
  const cases = await api(`/api/documents/${documentId}/test-cases`);
  const runsByCase = {};
  const detail = await api(`/api/documents/${documentId}`);
  if (detail.draft_version) {
    const runs = await api(`/api/documents/${documentId}/test-runs`).catch(() => []);
    for (const run of runs || []) {
      runsByCase[run.test_case_id] = run;
    }
  }
  return { cases, runsByCase };
}

function renderTestCases(cases, runsByCase) {
  if (!cases.length) {
    return "<p>尚未建立測試問題。請先新增至少 3 題再送審。</p>";
  }
  return cases.map((item) => {
    const run = runsByCase[item.test_case_id];
    const status = run ? `<span class="status ${run.status}">${run.status}</span>` : "尚未執行";
    return `
      <div class="doc-row">
        <div>
          <strong>${item.question}</strong>
          <div>${status}${run?.failure_reason ? ` · ${run.failure_reason}` : ""}</div>
        </div>
        <button class="secondary" data-run-test="${item.test_case_id}">執行</button>
      </div>`;
  }).join("");
}

async function runDraftSearch(documentId) {
  const query = prompt("請輸入草稿檢索問題：");
  if (!query) return;
  const result = await api(`/api/documents/${documentId}/draft-search`, {
    method: "POST",
    body: JSON.stringify({ query, groups: [], limit: 4 }),
  });
  const hits = (result.hits || [])
    .map((hit) => `[${hit.score.toFixed(2)}] ${hit.title}: ${hit.content.slice(0, 80)}…`)
    .join("\n");
  showToast(
    hits
      ? `草稿命中：${result.matchedDraft ? "是" : "否"}；正式版洩漏：${result.leakedFromActiveRelease ? "是" : "否"}`
      : "草稿索引沒有命中",
  );
  if (hits) alert(`草稿檢索結果：\n${hits}`);
}

async function openDocument(documentId) {
  const detail = await api(`/api/documents/${documentId}`);
  state.selectedDocumentId = documentId;
  const draft = detail.draft_version;
  const published = detail.published_version;
  const { cases, runsByCase } = draft ? await loadTestCases(documentId) : { cases: [], runsByCase: {} };
  const panel = document.getElementById("documentDetail");
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <h3>${escapeHtml(detail.document.title)}</h3>
    <p>狀態：<span class="status ${detail.document.status}">${detail.document.status}</span></p>
    ${published ? renderPublishedDetail(detail.document, published) : ""}
    ${draft ? `
      <h4>草稿</h4>
      <p>草稿版本：${draft.version_id}</p>
      <div>${renderIssues(draft.validation_summary?.issues || [])}</div>
      <div class="actions">
        <button data-action="validate">重新檢查</button>
        <button data-action="add-test">新增測試問題</button>
        <button data-action="draft-search">草稿檢索</button>
        <button data-action="submit">送審</button>
      </div>
      <h4>測試室</h4>
      <div id="testCaseList">${renderTestCases(cases, runsByCase)}</div>
    ` : "<p class=\"muted\">目前沒有可編輯草稿。若要更新內容，請到「新增／更新」建立新版本流程。</p>"}
    ${detail.open_review ? `<p>待審核 review：${detail.open_review.review_id}</p>
      <div class="actions">
        <button data-action="approve">核准</button>
        <button data-action="reject">退回修改</button>
      </div>` : ""}
    ${detail.document.status === "APPROVED" && draft ? "" : ""}
    ${detail.document.status === "APPROVED" ? `
      <div class="actions">
        <button data-action="publish">發布正式版本</button>
      </div>` : ""}
  `;
  panel.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleDocumentAction(documentId, button.dataset.action, detail));
  });
  panel.querySelectorAll("[data-run-test]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const run = await api(
          `/api/documents/${documentId}/test-cases/${button.dataset.runTest}/run`,
          { method: "POST" },
        );
        showToast(`測試結果：${run.status}`);
        await openDocument(documentId);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function handleDocumentAction(documentId, action, detail) {
  try {
    if (action === "validate") {
      const result = await api(`/api/documents/${documentId}/validate`, { method: "POST" });
      showToast(`檢查完成：${result.issues?.length || 0} 項結果`);
    }
    if (action === "add-test") {
      const question = prompt("請輸入測試問題：");
      if (!question) return;
      await api(`/api/documents/${documentId}/test-cases`, {
        method: "POST",
        body: JSON.stringify({ question, simulated_audience: [], notes: "" }),
      });
      showToast("已新增測試問題");
    }
    if (action === "draft-search") {
      await runDraftSearch(documentId);
      return;
    }
    if (action === "submit") {
      await api(`/api/documents/${documentId}/submit-review`, {
        method: "POST",
        body: JSON.stringify({
          etag: detail.document.etag,
          change_reason: detail.draft_version?.change_reason || "送審",
        }),
      });
      showToast("已送審");
    }
    if (action === "approve" || action === "reject") {
      document.getElementById("userRole").value = "REVIEWER";
      await api(`/api/reviews/${detail.open_review.review_id}/decision`, {
        method: "POST",
        body: JSON.stringify({
          decision: action === "approve" ? "APPROVED" : "CHANGES_REQUESTED",
          comment: action === "approve" ? "內容與測試結果可接受。" : "請依意見修正後再送審。",
          policy_exceptions: [],
        }),
      });
      showToast(action === "approve" ? "已核准" : "已退回修改");
    }
    if (action === "publish") {
      document.getElementById("userRole").value = "MANAGER";
      const versionId = detail.draft_version?.version_id || detail.document.current_published_version_id;
      await api(`/api/documents/${documentId}/publish`, {
        method: "POST",
        body: JSON.stringify({
          version_id: versionId,
          reason: "核准後發布正式版本",
        }),
      });
      showToast("發布成功");
    }
    await loadDocuments();
    await openDocument(documentId);
    await loadDashboard();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function loadAudit() {
  const events = await api("/api/audit-events?limit=50");
  document.getElementById("auditList").innerHTML = events.length
    ? events.map((event) => `
      <div class="doc-row">
        <div>
          <strong>${event.action}</strong>
          <div>${event.target_type} · ${event.target_id}</div>
        </div>
        <div>${new Date(event.occurred_at).toLocaleString("zh-TW")}</div>
      </div>`).join("")
    : "<p>尚無稽核紀錄。</p>";
}

document.querySelectorAll(".nav button").forEach((button) => {
  button.addEventListener("click", async () => {
    switchView(button.dataset.view);
    if (button.dataset.view === "dashboard") await loadDashboard();
    if (button.dataset.view === "library") await loadDocuments();
    if (button.dataset.view === "audit") await loadAudit();
  });
});

document.getElementById("createForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  try {
    await api("/api/documents", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast("草稿已建立");
    event.target.reset();
    switchView("library");
    await loadDocuments();
    await loadDashboard();
  } catch (error) {
    showToast(error.message, true);
  }
});

async function initPortal() {
  const list = document.getElementById("documentList");
  const cards = document.getElementById("dashboardCards");
  const baseUrl = document.getElementById("portalBaseUrl");
  if (baseUrl) baseUrl.textContent = window.location.origin;
  try {
    await loadDocuments();
    await loadDashboard();
    if (state.documents.length > 0) {
      switchView("library");
    }
  } catch (error) {
    const message = `無法載入知識庫：${error.message}`;
    showToast(message, true);
    if (cards) cards.innerHTML = `<p class="issue blocking">${message}</p>`;
    if (list) list.innerHTML = `<p class="issue blocking">${message}</p>`;
  }
}

initPortal();
