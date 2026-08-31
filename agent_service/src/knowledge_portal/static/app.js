const state = {
  documents: [],
  selectedDocumentId: null,
  relaxedWorkflow: true,
  minTestCasesForReview: 0,
};

const DEMO_PERSONAS = {
  CONTRIBUTOR: { userId: "contributor.demo", userName: "知識貢獻者" },
  REVIEWER: { userId: "reviewer.demo", userName: "知識審核者" },
  MANAGER: { userId: "manager.demo", userName: "知識管理者" },
  PLATFORM: { userId: "platform.demo", userName: "平台管理者" },
};

function applyDemoPersona(role) {
  const persona = DEMO_PERSONAS[role];
  if (!persona) return;
  document.getElementById("userId").value = persona.userId;
  document.getElementById("userName").value = persona.userName;
  document.getElementById("userRole").value = role;
}

function translatePortalError(message) {
  const mapping = {
    "Reviewers cannot approve their own submissions.":
      "審核者不能核准自己送審的內容。請切換為「知識審核者」身分（會自動換成 reviewer.demo）。",
    "At least three test questions are required before review.":
      "送審前請先新增至少 3 個測試問題。",
  };
  return mapping[message] || message;
}

function encodePortalHeaderValue(value) {
  return encodeURIComponent(value);
}

function identityHeaders(includeJsonContentType = true) {
  const headers = {
    "X-Portal-User-Id": document.getElementById("userId").value.trim(),
    "X-Portal-User-Name": encodePortalHeaderValue(
      document.getElementById("userName").value.trim(),
    ),
    "X-Portal-Role": document.getElementById("userRole").value,
    "X-Portal-Owner-Units": "IT Service Desk",
  };
  if (includeJsonContentType) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
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
    headers: { ...identityHeaders(true), ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const raw = payload.detail?.message || payload.detail || "操作失敗";
    const message = typeof raw === "string" ? translatePortalError(raw) : JSON.stringify(raw);
    throw new Error(message);
  }
  return payload;
}

async function apiForm(path, formData, method = "POST") {
  const response = await fetch(path, {
    method,
    headers: identityHeaders(false),
    body: formData,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const raw = payload.detail?.message || payload.detail || "操作失敗";
    const message = typeof raw === "string" ? translatePortalError(raw) : JSON.stringify(raw);
    throw new Error(message);
  }
  return payload;
}

async function loadAssetPreviewUrl(documentId, filename) {
  const response = await fetch(
    `/api/documents/${documentId}/draft/assets/${encodeURIComponent(filename)}`,
    { headers: identityHeaders(false) },
  );
  if (!response.ok) {
    throw new Error("無法載入圖片預覽");
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

function canRemoveDocument(status) {
  return status !== "IN_REVIEW" && status !== "DISCARDED";
}

function removeDocumentLabel(status) {
  return status === "PUBLISHED" ? "下架" : "刪除";
}

async function removeDocument(documentId, status) {
  const verb = removeDocumentLabel(status);
  if (!confirm(`確定要${verb}這份知識文件？`)) return;
  const reason = encodeURIComponent(`從知識庫${verb}`);
  await api(`/api/documents/${documentId}?reason=${reason}`, { method: "DELETE" });
  showToast(`已${verb}`);
  if (state.selectedDocumentId === documentId) {
    document.getElementById("documentDetail").classList.add("hidden");
    state.selectedDocumentId = null;
  }
  await loadDocuments();
  await loadDashboard();
}

function switchView(viewName) {
  document.querySelectorAll(".view").forEach((node) => node.classList.remove("active"));
  document.querySelectorAll(".nav button").forEach((node) => node.classList.remove("active"));
  document.getElementById(`view-${viewName}`).classList.add("active");
  document.querySelector(`[data-view="${viewName}"]`).classList.add("active");
}

async function loadDashboard() {
  const dashboard = await api("/api/dashboard");
  state.relaxedWorkflow = dashboard.relaxed_workflow !== false;
  state.minTestCasesForReview = dashboard.min_test_cases_for_review ?? 0;
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
        <strong>${escapeHtml(doc.title)}</strong>
        <div>${escapeHtml(doc.owner_unit_id)} · 更新 ${new Date(doc.updated_at).toLocaleString("zh-TW")}</div>
      </div>
      <div class="doc-actions">
        <span class="status ${doc.status}">${doc.status}</span>
        <button class="secondary" data-open-doc="${doc.document_id}">查看</button>
        ${canRemoveDocument(doc.status) ? `<button class="danger" data-remove-doc="${doc.document_id}" data-doc-status="${doc.status}">${removeDocumentLabel(doc.status)}</button>` : ""}
      </div>
    </div>
  `).join("");
  list.querySelectorAll("[data-open-doc]").forEach((button) => {
    button.addEventListener("click", () => openDocument(button.dataset.openDoc));
  });
  list.querySelectorAll("[data-remove-doc]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await removeDocument(button.dataset.removeDoc, button.dataset.docStatus);
      } catch (error) {
        showToast(error.message, true);
      }
    });
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
    if (state.relaxedWorkflow) {
      return "<p class=\"muted\">測試問題為選填，可直接送審。</p>";
    }
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

function renderDraftEditor(documentId, detail, draft) {
  const body = stripFrontMatter(draft.canonical_content || "");
  const assets = detail.draft_assets?.items || [];
  const assetList = assets.length
    ? assets.map((item) => `<li>${escapeHtml(item.filename)} (${item.size_bytes} bytes)</li>`).join("")
    : "<li class=\"muted\">尚未上傳圖片</li>";
  return `
    <label class="full">Markdown 正文
      <textarea id="draftMarkdown" rows="12">${escapeHtml(body)}</textarea>
    </label>
    <div class="actions">
      <button type="button" data-action="save-draft">儲存草稿</button>
    </div>
    <h4>草稿圖片</h4>
    <p class="muted">asset slug：<code>${escapeHtml(detail.draft_assets?.asset_slug || "")}</code></p>
    <ul>${assetList}</ul>
    <div id="assetPreviewGrid" class="asset-grid"></div>
    <div class="actions">
      <label class="secondary" style="display:inline-flex;align-items:center;gap:0.5rem;padding:0.55rem 0.7rem;">
        上傳圖片
        <input id="draftAssetUpload" type="file" accept="image/png,image/jpeg,image/gif" multiple hidden>
      </label>
      <button type="button" class="secondary" data-action="insert-asset-ref">插入圖片 Markdown</button>
    </div>
  `;
}

async function hydrateAssetPreviews(documentId, assets) {
  const grid = document.getElementById("assetPreviewGrid");
  if (!grid || !assets.length) return;
  grid.innerHTML = "";
  for (const item of assets) {
    const card = document.createElement("div");
    card.className = "asset-card";
    card.innerHTML = `
      <img alt="${escapeHtml(item.filename)}" />
      <div class="meta">${escapeHtml(item.filename)}</div>
      <button type="button" class="secondary" data-delete-asset="${escapeHtml(item.filename)}">刪除</button>
    `;
    grid.appendChild(card);
    try {
      const url = await loadAssetPreviewUrl(documentId, item.filename);
      card.querySelector("img").src = url;
    } catch (error) {
      card.querySelector(".meta").textContent = `${item.filename} · 預覽失敗`;
    }
  }
  grid.querySelectorAll("[data-delete-asset]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(
          `/api/documents/${documentId}/draft/assets/${encodeURIComponent(button.dataset.deleteAsset)}`,
          { method: "DELETE" },
        );
        showToast("已刪除圖片");
        await openDocument(documentId);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
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
  const testCaseHint = state.relaxedWorkflow
    ? ""
    : `<p class="muted">送審前至少 ${state.minTestCasesForReview} 題測試問題（目前 ${cases.length}/${state.minTestCasesForReview}）。</p>`;
  const reviewHint = state.relaxedWorkflow
    ? ""
    : `<p class="muted">核准／退回需使用審核者身分（與送審者不同使用者）。</p>`;
  panel.innerHTML = `
    <h3>${escapeHtml(detail.document.title)}</h3>
    <p>狀態：<span class="status ${detail.document.status}">${detail.document.status}</span></p>
    ${published ? renderPublishedDetail(detail.document, published) : ""}
    ${draft ? `
      <h4>草稿</h4>
      <p>草稿版本：${draft.version_id}</p>
      <div>${renderIssues(draft.validation_summary?.issues || [])}</div>
      ${renderDraftEditor(documentId, detail, draft)}
      <div class="actions">
        <button data-action="validate">重新檢查</button>
        <button data-action="add-test">新增測試問題</button>
        <button data-action="draft-search">草稿檢索</button>
        <button data-action="submit">送審</button>
      </div>
      <h4>測試室</h4>
      ${testCaseHint}
      <div id="testCaseList">${renderTestCases(cases, runsByCase)}</div>
    ` : published ? `
      <p class="muted">目前沒有可編輯草稿。</p>
      <div class="actions">
        <button data-action="start-revision">建立新版本草稿</button>
      </div>
    ` : "<p class=\"muted\">目前沒有可編輯草稿。請到「新增／更新」建立第一份草稿。</p>"}
    ${detail.open_review ? `<p>待審核 review：${detail.open_review.review_id}${detail.open_review.submitted_by ? ` · 送審者 ${escapeHtml(detail.open_review.submitted_by)}` : ""}</p>
      ${reviewHint}
      <div class="actions">
        <button data-action="approve">核准</button>
        <button data-action="reject">退回修改</button>
      </div>` : ""}
    ${detail.document.status === "APPROVED" && draft ? "" : ""}
    ${detail.document.status === "APPROVED" ? `
      <div class="actions">
        <button data-action="publish">發布正式版本</button>
      </div>` : ""}
    ${canRemoveDocument(detail.document.status) ? `
      <div class="actions">
        <button class="danger" data-action="remove">${removeDocumentLabel(detail.document.status)}</button>
      </div>` : ""}
  `;
  panel.querySelectorAll("button[data-action]").forEach((button) => {
    button.addEventListener("click", () => handleDocumentAction(documentId, button.dataset.action, detail));
  });
  const assetUpload = panel.querySelector("#draftAssetUpload");
  if (assetUpload) {
    assetUpload.addEventListener("change", async (event) => {
      const files = event.target.files;
      if (!files?.length) return;
      try {
        const formData = new FormData();
        for (const file of files) {
          formData.append("files", file);
        }
        await apiForm(`/api/documents/${documentId}/draft/assets`, formData);
        showToast(`已上傳 ${files.length} 張圖片`);
        await openDocument(documentId);
      } catch (error) {
        showToast(error.message, true);
      } finally {
        event.target.value = "";
      }
    });
  }
  if (detail.draft_assets?.items?.length) {
    await hydrateAssetPreviews(documentId, detail.draft_assets.items);
  }
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
    if (action === "start-revision") {
      await api(`/api/documents/${documentId}/start-revision`, { method: "POST" });
      showToast("已建立新版本草稿");
    }
    if (action === "save-draft") {
      const markdown = document.getElementById("draftMarkdown")?.value;
      if (!markdown?.trim()) {
        showToast("Markdown 內容不可為空", true);
        return;
      }
      const draftVersion = detail.draft_version;
      await api(`/api/documents/${documentId}/draft`, {
        method: "PUT",
        body: JSON.stringify({
          etag: detail.document.etag,
          title: detail.document.title,
          summary: detail.document.summary || "",
          category: detail.document.category || "",
          owner_unit_id: detail.document.owner_unit_id,
          business_contact: detail.document.business_contact || "",
          audience_type: detail.document.audience_type,
          audience_group_ids: detail.document.audience_group_ids || [],
          effective_at: draftVersion.effective_at,
          review_due_at: draftVersion.review_due_at,
          change_summary: draftVersion.change_summary || "",
          change_reason: draftVersion.change_reason || "更新草稿內容",
          markdown_content: markdown,
        }),
      });
      showToast("草稿已儲存");
    }
    if (action === "insert-asset-ref") {
      const filename = prompt("圖片檔名（留空則自動命名 p01.png …）：") || "";
      const altText = prompt("替代文字（可留空）：") || "";
      const suggestion = await api(
        `/api/documents/${documentId}/draft/asset-ref?filename=${encodeURIComponent(filename)}&alt_text=${encodeURIComponent(altText)}`,
        { method: "POST" },
      );
      const textarea = document.getElementById("draftMarkdown");
      if (textarea) {
        const suffix = textarea.value.endsWith("\n") || !textarea.value ? "" : "\n";
        textarea.value = `${textarea.value}${suffix}${suggestion.markdown}\n`;
      }
      showToast("已產生 Markdown 參考");
      return;
    }
    if (action === "submit") {
      if (!state.relaxedWorkflow) {
        applyDemoPersona("CONTRIBUTOR");
      }
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
      if (!state.relaxedWorkflow) {
        applyDemoPersona("REVIEWER");
      }
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
      if (!state.relaxedWorkflow) {
        applyDemoPersona("MANAGER");
      }
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
    if (action === "remove") {
      await removeDocument(documentId, detail.document.status);
      return;
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

document.getElementById("libraryCreateBtn")?.addEventListener("click", () => {
  switchView("editor");
});

document.getElementById("userRole")?.addEventListener("change", (event) => {
  applyDemoPersona(event.target.value);
});

document.getElementById("createForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  try {
    const created = await api("/api/documents", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast("草稿已建立");
    event.target.reset();
    switchView("library");
    await loadDocuments();
    await loadDashboard();
    await openDocument(created.document.document_id);
  } catch (error) {
    showToast(error.message, true);
  }
});

document.getElementById("importMarkdownFile")?.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const formData = new FormData();
    formData.append("file", file);
    const imported = await apiForm("/api/documents/import-markdown", formData);
    const form = document.getElementById("createForm");
    form.title.value = imported.title;
    form.owner_unit_id.value = imported.owner_unit_id;
    form.effective_at.value = imported.effective_at;
    form.review_due_at.value = imported.review_due_at;
    form.markdown_content.value = imported.markdown_content;
    if (imported.warnings?.length) {
      showToast(imported.warnings.join(" "));
    } else {
      showToast("已匯入 Markdown");
    }
    switchView("editor");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    event.target.value = "";
  }
});

async function initPortal() {
  const list = document.getElementById("documentList");
  const cards = document.getElementById("dashboardCards");
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
