const state = {
  documents: [],
  selectedDocumentId: null,
};

function identityHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Portal-User-Id": document.getElementById("userId").value.trim(),
    "X-Portal-User-Name": document.getElementById("userName").value.trim(),
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
  document.getElementById("dashboardCards").innerHTML = `
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

async function openDocument(documentId) {
  const detail = await api(`/api/documents/${documentId}`);
  state.selectedDocumentId = documentId;
  const draft = detail.draft_version;
  const panel = document.getElementById("documentDetail");
  panel.classList.remove("hidden");
  panel.innerHTML = `
    <h3>${detail.document.title}</h3>
    <p>狀態：<span class="status ${detail.document.status}">${detail.document.status}</span></p>
    ${draft ? `
      <p>草稿版本：${draft.version_id}</p>
      <div>${renderIssues(draft.validation_summary?.issues || [])}</div>
      <div class="actions">
        <button data-action="validate">重新檢查</button>
        <button data-action="add-test">新增測試問題</button>
        <button data-action="submit">送審</button>
      </div>
    ` : "<p>目前沒有可編輯草稿。</p>"}
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

loadDashboard();
loadDocuments();
