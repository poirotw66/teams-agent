import { api } from "../api.js";
import { can } from "../capabilities.js";
import { fluentButton } from "../fluent.js";
import { statusLabel } from "../labels.js";
import { navigate } from "../router.js";
import { getSession } from "../session.js";
import {
  escapeHtml,
  handleViewError,
  renderSkeleton,
  renderStatusBadge,
  renderViewEmpty,
} from "../ui.js?v=20260831e";

function buildQuery(filters) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.format) params.set("format", filters.format);
  if (filters.query) params.set("query", filters.query);
  if (filters.owner_unit_id) params.set("owner_unit_id", filters.owner_unit_id);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function renderFilters(filters) {
  return `
    <div class="command-bar">
      <label class="search-field">
        <span class="sr-only">搜尋</span>
        <fluent-search id="knowledgeSearch" placeholder="搜尋標題或摘要…" value="${escapeHtml(filters.query || "")}"></fluent-search>
      </label>
      <label>
        狀態
        <fluent-select id="knowledgeStatus">
          <fluent-option value="">全部狀態</fluent-option>
          ${Object.entries({
            DRAFT: "草稿",
            IN_REVIEW: "待審核",
            CHANGES_REQUESTED: "待修正",
            APPROVED: "已核准",
            PUBLISHED: "已發布",
            PUBLISH_FAILED: "發布失敗",
            UNPUBLISHED: "已下架",
          }).map(([value, label]) => `
            <fluent-option value="${value}" ${filters.status === value ? "selected" : ""}>${label}</fluent-option>`).join("")}
        </fluent-select>
      </label>
      <label>
        格式
        <fluent-select id="knowledgeFormat">
          <fluent-option value="">全部格式</fluent-option>
          <fluent-option value="MARKDOWN" ${filters.format === "MARKDOWN" ? "selected" : ""}>Markdown</fluent-option>
          <fluent-option value="PDF" ${filters.format === "PDF" ? "selected" : ""}>PDF</fluent-option>
        </fluent-select>
      </label>
      <label>
        擁有單位
        <fluent-text-field id="knowledgeOwner" placeholder="擁有單位…" value="${escapeHtml(filters.owner_unit_id || "")}"></fluent-text-field>
      </label>
      ${can("create_document") ? fluentButton("新增文件", { appearance: "accent", dataset: { route: "#/knowledge/new" } }) : ""}
    </div>`;
}

function renderTable(items) {
  if (!items.length) {
    return "";
  }
  return `
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>標題</th>
            <th>文件 ID</th>
            <th>狀態</th>
            <th>格式</th>
            <th>正式版本</th>
            <th>擁有單位</th>
            <th>最後更新</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${items.map((doc) => `
            <tr>
              <td>
                <fluent-button appearance="stealth" data-open-doc="${escapeHtml(doc.document_id)}">
                  ${escapeHtml(doc.title)}
                </fluent-button>
              </td>
              <td><code>${escapeHtml(doc.document_id)}</code></td>
              <td>${renderStatusBadge(doc.status, statusLabel(doc.status))}</td>
              <td><span class="badge ${doc.format === "PDF" ? "badge-neutral" : "badge-outline"}">${escapeHtml(doc.format || "MARKDOWN")}</span></td>
              <td><code>${escapeHtml(doc.current_published_version_id || "尚未發布")}</code></td>
              <td>${escapeHtml(doc.owner_unit_id)}</td>
              <td>${new Date(doc.updated_at).toLocaleString("zh-TW")}</td>
              <td class="table-actions">
                ${fluentButton("查看", { appearance: "outline", dataset: { "open-doc": doc.document_id } })}
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

export async function renderKnowledgeListView(app, query) {
  const filters = {
    status: query.get("status") || "",
    format: query.get("format") || "",
    query: query.get("query") || "",
    owner_unit_id: query.get("owner_unit_id") || "",
  };
  const hasFilters = Boolean(filters.status || filters.format || filters.query || filters.owner_unit_id);
  const session = getSession();
  const isReadonly =
    session.role === "AUDITOR"
    || (!can("create_document") && !can("publish") && !can("decide_review"));

  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <h2>知識文件${isReadonly ? '<span class="readonly-badge" title="目前身分僅能檢視，無法建立或修改">唯讀</span>' : ""}</h2>
          ${isReadonly ? '<p class="muted">目前身分僅能檢視文件；若看不到項目，可能是權限或篩選結果，而非系統錯誤。</p>' : ""}
        </div>
      </header>
      ${renderFilters(filters)}
      <div id="knowledgeContent">${renderSkeleton(5)}</div>
    </section>`;

  const container = app.querySelector("#knowledgeContent");
  const searchInput = app.querySelector("#knowledgeSearch");
  const statusSelect = app.querySelector("#knowledgeStatus");
  const formatSelect = app.querySelector("#knowledgeFormat");
  const ownerInput = app.querySelector("#knowledgeOwner");

  async function loadList() {
    container.innerHTML = renderSkeleton(5);
    try {
      const payload = await api(`/api/documents${buildQuery(filters)}`);
      const items = payload.items || [];
      if (!items.length) {
        if (isReadonly && !hasFilters) {
          container.innerHTML = `
            <div class="empty-state" role="status">
              <h3>目前沒有可檢視的知識文件</h3>
              <p class="muted">這是資料結果為空，不是權限拒絕。若懷疑權限問題，請改由具備知識讀取權限的角色協助確認。</p>
            </div>`;
          return;
        }
        const emptyKey = hasFilters ? "knowledge-no-results" : "knowledge-empty";
        const action = hasFilters
          ? fluentButton("清除篩選", { appearance: "outline", dataset: { route: "#/knowledge" } })
          : (can("create_document")
            ? fluentButton("新增文件", { appearance: "accent", dataset: { route: "#/knowledge/new" } })
            : "");
        container.innerHTML = renderViewEmpty(emptyKey, action);
        container.querySelectorAll("[data-route]").forEach((node) => {
          node.addEventListener("click", () => navigate(node.dataset.route));
        });
        return;
      }
      container.innerHTML = renderTable(items);
      container.querySelectorAll("[data-open-doc]").forEach((node) => {
        node.addEventListener("click", () => navigate(`#/knowledge/${node.dataset.openDoc}`));
      });
    } catch (error) {
      handleViewError(error, { view: "knowledge", container, onRetry: loadList });
    }
  }

  function applyFilters() {
    filters.query = searchInput?.value?.trim?.() || searchInput?.currentValue || "";
    filters.status = statusSelect?.value || "";
    filters.format = formatSelect?.value || "";
    filters.owner_unit_id = ownerInput?.value?.trim?.() || ownerInput?.currentValue || "";
    navigate(`#/knowledge${buildQuery(filters)}`);
  }

  searchInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyFilters();
  });
  ownerInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyFilters();
  });
  statusSelect?.addEventListener("change", applyFilters);
  formatSelect?.addEventListener("change", applyFilters);
  app.querySelectorAll("[data-route]").forEach((node) => {
    node.addEventListener("click", () => navigate(node.dataset.route));
  });

  await loadList();
}
