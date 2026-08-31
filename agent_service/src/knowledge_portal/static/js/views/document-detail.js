import { api, apiForm, loadAssetPreviewUrl } from "../api.js";
import { nextActionLabel, testResultLabel } from "../labels.js";
import { getSession } from "../session.js";
import { navigate } from "../router.js";
import {
  confirmDialog,
  escapeHtml,
  openDialog,
  promptDialog,
  renderError,
  renderForbidden,
  renderLoading,
  renderStatusBadge,
  showToast,
  stripFrontMatter,
} from "../ui.js";

const TABS = [
  { id: "overview", label: "概覽" },
  { id: "content", label: "內容與附件" },
  { id: "tests", label: "問答測試" },
  { id: "versions", label: "版本與稽核" },
];

function can(action, allowedActions = []) {
  return allowedActions.includes(action);
}

function renderIssues(issues = []) {
  if (!issues.length) return "<p class=\"muted\">未發現品質問題。</p>";
  return `<ul class="issue-list">${issues.map((issue) => `
    <li class="issue ${issue.severity.toLowerCase()}">[${issue.severity}] ${escapeHtml(issue.message)}</li>
  `).join("")}</ul>`;
}

function renderPublishedPreview(document, published) {
  if (!published) return "<p class=\"muted\">尚無正式版本內容。</p>";
  const body = stripFrontMatter(published.canonical_content || "");
  const preview = body.length > 1200 ? `${body.slice(0, 1200)}\n…` : body;
  const audience = document.audience_type === "ALL_EMPLOYEES"
    ? "全體員工"
    : (document.audience_group_ids || []).join(", ") || "特定群組";
  return `
    <div class="panel">
      <h3>正式版本預覽</h3>
      <p class="muted">版本 ${published.version_number} · 生效 ${published.effective_at} · 下次檢視 ${published.review_due_at}</p>
      <p>擁有單位：${escapeHtml(document.owner_unit_id)} · 適用範圍：${escapeHtml(audience)}</p>
      ${document.summary ? `<p>${escapeHtml(document.summary)}</p>` : ""}
      <pre class="content-preview">${escapeHtml(preview)}</pre>
    </div>`;
}

function renderOverviewTab(detail) {
  const doc = detail.document;
  const nextLabel = nextActionLabel(detail.next_action);
  return `
    <div class="detail-grid">
      <div class="panel">
        <h3>文件摘要</h3>
        <dl class="meta-list">
          <div><dt>狀態</dt><dd>${renderStatusBadge(doc.status, detail.status_label)}</dd></div>
          <div><dt>擁有單位</dt><dd>${escapeHtml(doc.owner_unit_id)}</dd></div>
          <div><dt>最後更新</dt><dd>${new Date(doc.updated_at).toLocaleString("zh-TW")}</dd></div>
        </dl>
        ${doc.summary ? `<p>${escapeHtml(doc.summary)}</p>` : ""}
      </div>
      ${detail.published_version ? renderPublishedPreview(doc, detail.published_version) : ""}
      ${detail.open_review ? `
        <div class="panel review-panel">
          <h3>審核中</h3>
          <p>送審者：${escapeHtml(detail.open_review.submitted_by)}</p>
          <p class="muted">送審時間：${new Date(detail.open_review.submitted_at).toLocaleString("zh-TW")}</p>
        </div>` : ""}
    </div>
    ${nextLabel ? `<p class="next-action-hint">建議下一步：<strong>${escapeHtml(nextLabel)}</strong></p>` : ""}`;
}

function renderContentTab(documentId, detail, draft) {
  if (!draft) {
    return `
      <div class="panel">
        <p class="muted">目前沒有可編輯草稿。</p>
        ${can("START_REVISION", detail.allowed_actions) ? `
          <button type="button" class="btn primary" data-action="start-revision">建立新版本草稿</button>` : ""}
      </div>`;
  }
  const body = stripFrontMatter(draft.canonical_content || "");
  const assets = detail.draft_assets?.items || [];
  return `
    <div class="panel">
      <h3>草稿內容</h3>
      ${renderIssues(draft.validation_summary?.issues || [])}
      <label class="full">Markdown 正文
        <textarea id="draftMarkdown" rows="14">${escapeHtml(body)}</textarea>
      </label>
      <div class="action-row secondary-actions">
        ${can("EDIT_DRAFT", detail.allowed_actions) ? `<button type="button" class="btn primary" data-action="save-draft">儲存草稿</button>` : ""}
        ${can("VALIDATE", detail.allowed_actions) ? `<button type="button" class="btn secondary" data-action="validate">重新檢查</button>` : ""}
      </div>
    </div>
    <div class="panel">
      <h3>圖片附件</h3>
      <ul class="asset-list">${assets.length
    ? assets.map((item) => `<li>${escapeHtml(item.filename)} (${item.size_bytes} bytes)</li>`).join("")
    : "<li class=\"muted\">尚未上傳圖片</li>"}</ul>
      <div id="assetPreviewGrid" class="asset-grid"></div>
      ${can("EDIT_DRAFT", detail.allowed_actions) ? `
        <div class="action-row secondary-actions">
          <label class="btn secondary file-button">
            上傳圖片
            <input id="draftAssetUpload" type="file" accept="image/png,image/jpeg,image/gif" multiple hidden>
          </label>
          <button type="button" class="btn secondary" data-action="insert-asset-ref">插入圖片 Markdown</button>
        </div>` : ""}
    </div>`;
}

function renderTestsTab(cases, runsByCase, detail) {
  const session = getSession();
  const hint = session.relaxedWorkflow
    ? "<p class=\"muted\">測試問題為選填，可直接送審。</p>"
    : `<p class="muted">送審前至少 ${session.minTestCasesForReview} 題測試問題（目前 ${cases.length}/${session.minTestCasesForReview}）。</p>`;
  const rows = !cases.length
    ? "<p class=\"muted\">尚未建立測試問題。</p>"
    : cases.map((item) => {
      const run = runsByCase[item.test_case_id];
      const status = run
        ? renderStatusBadge(run.status, testResultLabel(run.status))
        : "尚未執行";
      return `
        <div class="list-row">
          <div>
            <strong>${escapeHtml(item.question)}</strong>
            <div>${status}${run?.failure_reason ? ` · ${escapeHtml(run.failure_reason)}` : ""}</div>
          </div>
          ${can("MANAGE_TESTS", detail.allowed_actions) ? `
            <button type="button" class="btn secondary btn-sm" data-run-test="${escapeHtml(item.test_case_id)}">執行</button>` : ""}
        </div>`;
    }).join("");
  return `
    ${hint}
    <div class="action-row secondary-actions">
      ${can("MANAGE_TESTS", detail.allowed_actions) ? `
        <button type="button" class="btn secondary" data-action="add-test">新增測試問題</button>
        <button type="button" class="btn secondary" data-action="draft-search">進階診斷：草稿檢索</button>` : ""}
    </div>
    <div class="panel">${rows}</div>`;
}

function renderVersionsTab(detail) {
  const doc = detail.document;
  const draft = detail.draft_version;
  const published = detail.published_version;
  return `
    <div class="panel">
      <h3>版本資訊</h3>
      <dl class="meta-list technical-meta">
        ${published ? `<div><dt>正式版本</dt><dd>v${published.version_number}</dd></div>` : ""}
        ${draft ? `<div><dt>草稿版本</dt><dd>${escapeHtml(draft.version_id)}</dd></div>` : ""}
        ${detail.open_review ? `<div><dt>審核編號</dt><dd>${escapeHtml(detail.open_review.review_id)}</dd></div>` : ""}
      </dl>
    </div>
    ${can("DISCARD_DRAFT", detail.allowed_actions) || can("UNPUBLISH", detail.allowed_actions) ? `
      <div class="panel danger-zone">
        <h3>高風險操作</h3>
        ${can("DISCARD_DRAFT", detail.allowed_actions) ? `
          <button type="button" class="btn danger" data-action="discard-draft">放棄草稿</button>` : ""}
        ${can("UNPUBLISH", detail.allowed_actions) ? `
          <button type="button" class="btn danger" data-action="unpublish">下架正式文件</button>
          <p class="muted">下架後 Teams 將無法引用此文件。</p>` : ""}
      </div>` : ""}`;
}

function actionSlug(action) {
  const mapping = {
    EDIT_DRAFT: "save-draft",
    SUBMIT_REVIEW: "submit",
    START_REVISION: "start-revision",
  };
  return mapping[action] || action.toLowerCase().replace(/_/g, "-");
}

function renderActionPanel(detail) {
  const actions = detail.allowed_actions || [];
  const primary = detail.next_action;
  const buttons = [];
  if (primary && can(primary, actions)) {
    const slug = primary === "EDIT_DRAFT" ? "edit-draft" : actionSlug(primary);
    buttons.push(`<button type="button" class="btn primary" data-action="${slug}">${escapeHtml(nextActionLabel(primary))}</button>`);
  }
  if (can("APPROVE", actions) && primary !== "APPROVE") {
    buttons.push(`<button type="button" class="btn primary" data-action="approve">核准</button>`);
  }
  if (can("REJECT", actions) && primary !== "REJECT") {
    buttons.push(`<button type="button" class="btn secondary" data-action="reject">退回修改</button>`);
  }
  if (can("PUBLISH", actions) && primary !== "PUBLISH") {
    buttons.push(`<button type="button" class="btn primary" data-action="publish">發布正式版本</button>`);
  }
  if (can("SUBMIT_REVIEW", actions) && primary !== "SUBMIT_REVIEW") {
    buttons.push(`<button type="button" class="btn secondary" data-action="submit">送審</button>`);
  }
  if (!buttons.length) return "";
  return `<aside class="action-panel"><h3>工作區</h3><div class="action-row">${buttons.join("")}</div></aside>`;
}

async function loadTestData(documentId, detail) {
  if (!detail.draft_version) return { cases: [], runsByCase: {} };
  const cases = await api(`/api/documents/${documentId}/test-cases`);
  const runsByCase = {};
  const runs = await api(`/api/documents/${documentId}/test-runs`).catch(() => []);
  for (const run of runs || []) {
    runsByCase[run.test_case_id] = run;
  }
  return { cases, runsByCase };
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
      <button type="button" class="btn secondary btn-sm" data-delete-asset="${escapeHtml(item.filename)}">刪除</button>`;
    grid.appendChild(card);
    try {
      const url = await loadAssetPreviewUrl(documentId, item.filename);
      card.querySelector("img").src = url;
    } catch {
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
        navigate(`#/knowledge/${documentId}/content`);
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
}

async function handleAction(documentId, action, detail) {
  if (action === "validate") {
    const result = await api(`/api/documents/${documentId}/validate`, { method: "POST" });
    showToast(`檢查完成：${result.issues?.length || 0} 項結果`);
  }
  if (action === "add-test") {
    const question = await promptDialog("新增測試問題", "問題內容");
    if (!question) return;
    await api(`/api/documents/${documentId}/test-cases`, {
      method: "POST",
      body: JSON.stringify({ question, simulated_audience: [], notes: "" }),
    });
    showToast("已新增測試問題");
  }
  if (action === "draft-search") {
    const query = await promptDialog("草稿檢索", "請輸入檢索問題");
    if (!query) return;
    const result = await api(`/api/documents/${documentId}/draft-search`, {
      method: "POST",
      body: JSON.stringify({ query, groups: [], limit: 4 }),
    });
    const hits = (result.hits || [])
      .map((hit) => `${hit.title}: ${hit.content.slice(0, 80)}…`)
      .join("\n");
    await openDialog({
      title: "草稿檢索結果",
      bodyHtml: `
        <p>草稿命中：${result.matchedDraft ? "是" : "否"}</p>
        <p>正式版洩漏：${result.leakedFromActiveRelease ? "是" : "否"}</p>
        <pre class="content-preview">${escapeHtml(hits || "草稿索引沒有命中")}</pre>`,
      confirmLabel: "關閉",
      cancelLabel: "關閉",
    });
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
    const filename = await promptDialog("插入圖片", "圖片檔名（留空則自動命名）", { required: false });
    if (filename === null) return;
    const altText = await promptDialog("插入圖片", "替代文字（可留空）", { required: false, defaultValue: "" });
    if (altText === null) return;
    const suggestion = await api(
      `/api/documents/${documentId}/draft/asset-ref?filename=${encodeURIComponent(filename)}&alt_text=${encodeURIComponent(altText || "")}`,
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
  if (action === "submit" || action === "edit-draft") {
    if (action === "edit-draft") {
      navigate(`#/knowledge/${documentId}/content`);
      return;
    }
    const ok = await confirmDialog("送審", "確定要將此草稿送交審核？");
    if (!ok) return;
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
    const decision = action === "approve" ? "APPROVED" : "CHANGES_REQUESTED";
    const comment = await promptDialog(
      action === "approve" ? "核准" : "退回修改",
      "審核意見",
      {
        defaultValue: action === "approve" ? "內容與測試結果可接受。" : "請依意見修正後再送審。",
        multiline: true,
      },
    );
    if (comment === null) return;
    await api(`/api/reviews/${detail.open_review.review_id}/decision`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        comment,
        policy_exceptions: [],
      }),
    });
    showToast(action === "approve" ? "已核准" : "已退回修改");
  }
  if (action === "publish") {
    const ok = await confirmDialog(
      "發布正式版本",
      "發布後 Teams 將引用此版本。確定要發布？",
      { confirmLabel: "發布" },
    );
    if (!ok) return;
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
  if (action === "discard-draft") {
    const reason = await promptDialog("放棄草稿", "請說明原因", { defaultValue: "放棄草稿" });
    if (reason === null) return;
    const ok = await confirmDialog("放棄草稿", "此操作無法復原。確定要放棄草稿？", { danger: true, confirmLabel: "放棄" });
    if (!ok) return;
    await api(`/api/documents/${documentId}/discard-draft`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    showToast("已放棄草稿");
    navigate("#/knowledge");
    return;
  }
  if (action === "unpublish") {
    const reason = await promptDialog("下架正式文件", "請說明原因", { defaultValue: "下架正式文件" });
    if (reason === null) return;
    const ok = await confirmDialog(
      "下架正式文件",
      "下架後 Teams 將無法引用此文件。確定要下架？",
      { danger: true, confirmLabel: "下架" },
    );
    if (!ok) return;
    await api(`/api/documents/${documentId}/unpublish`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    showToast("已下架");
  }
  if (action === "view") {
    navigate(`#/knowledge/${documentId}/overview`);
    return;
  }
}

function wireActions(app, documentId, detail) {
  app.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await handleAction(documentId, button.dataset.action, detail);
        await renderDocumentDetailView(app, documentId, currentRouteTab());
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  app.querySelectorAll("[data-run-test]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const run = await api(
          `/api/documents/${documentId}/test-cases/${button.dataset.runTest}/run`,
          { method: "POST" },
        );
        showToast(`測試結果：${testResultLabel(run.status)}`);
        await renderDocumentDetailView(app, documentId, "tests");
      } catch (error) {
        showToast(error.message, true);
      }
    });
  });
  const assetUpload = app.querySelector("#draftAssetUpload");
  if (assetUpload) {
    assetUpload.addEventListener("change", async (event) => {
      const files = event.target.files;
      if (!files?.length) return;
      try {
        const formData = new FormData();
        for (const file of files) formData.append("files", file);
        await apiForm(`/api/documents/${documentId}/draft/assets`, formData);
        showToast(`已上傳 ${files.length} 張圖片`);
        navigate(`#/knowledge/${documentId}/content`);
      } catch (error) {
        showToast(error.message, true);
      } finally {
        event.target.value = "";
      }
    });
  }
}

let currentRouteTab = () => "overview";

export async function renderDocumentDetailView(app, documentId, tab = "overview") {
  currentRouteTab = () => tab;
  app.innerHTML = `
    <section class="page detail-page">
      <header class="page-header">
        <div>
          <button type="button" class="btn text" data-back>← 返回知識庫</button>
          <div id="detailHeader">${renderLoading()}</div>
        </div>
      </header>
      <div class="detail-layout">
        <div class="detail-main">
          <nav class="tab-nav" aria-label="文件分頁">
            ${TABS.map((item) => `
              <button type="button" class="tab ${item.id === tab ? "active" : ""}" data-tab="${item.id}">
                ${item.label}
              </button>`).join("")}
          </nav>
          <div id="detailTabContent">${renderLoading()}</div>
        </div>
        <div id="detailActionPanel"></div>
      </div>
    </section>`;

  app.querySelector("[data-back]")?.addEventListener("click", () => navigate("#/knowledge"));
  app.querySelectorAll("[data-tab]").forEach((node) => {
    node.addEventListener("click", () => navigate(`#/knowledge/${documentId}/${node.dataset.tab}`));
  });

  try {
    const detail = await api(`/api/documents/${documentId}`);
    app.querySelector("#detailHeader").innerHTML = `
      <h2>${escapeHtml(detail.document.title)}</h2>
      <p>${renderStatusBadge(detail.document.status, detail.status_label)}</p>`;
    app.querySelector("#detailActionPanel").innerHTML = renderActionPanel(detail);

    const { cases, runsByCase } = await loadTestData(documentId, detail);
    let tabHtml = "";
    if (tab === "overview") tabHtml = renderOverviewTab(detail);
    if (tab === "content") tabHtml = renderContentTab(documentId, detail, detail.draft_version);
    if (tab === "tests") tabHtml = renderTestsTab(cases, runsByCase, detail);
    if (tab === "versions") tabHtml = renderVersionsTab(detail);
    app.querySelector("#detailTabContent").innerHTML = tabHtml;

    wireActions(app, documentId, detail);
    if (tab === "content" && detail.draft_assets?.items?.length) {
      await hydrateAssetPreviews(documentId, detail.draft_assets.items);
    }
  } catch (error) {
    if (error.status === 403) {
      app.querySelector("#detailTabContent").innerHTML = renderForbidden();
      return;
    }
    if (error.status === 404) {
      app.querySelector("#detailTabContent").innerHTML = renderError("找不到這份文件。");
      return;
    }
    app.querySelector("#detailTabContent").innerHTML = renderError(error.message);
    app.querySelector("[data-retry]")?.addEventListener("click", () => renderDocumentDetailView(app, documentId, tab));
  }
}
