import { api } from "../api.js";
import { statusLabel } from "../labels.js";
import { navigate } from "../router.js";
import { escapeHtml, renderEmptyState, renderError, renderSkeleton, renderStatusBadge } from "../ui.js";

function buildQuery(filters) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
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
        <input type="search" id="knowledgeSearch" placeholder="搜尋標題或摘要…" value="${escapeHtml(filters.query || "")}">
      </label>
      <label>
        狀態
        <select id="knowledgeStatus">
          <option value="">全部</option>
          ${Object.entries({
            DRAFT: "草稿",
            IN_REVIEW: "待審核",
            CHANGES_REQUESTED: "待修正",
            APPROVED: "已核准",
            PUBLISHED: "已發布",
            PUBLISH_FAILED: "發布失敗",
            UNPUBLISHED: "已下架",
          }).map(([value, label]) => `
            <option value="${value}" ${filters.status === value ? "selected" : ""}>${label}</option>`).join("")}
        </select>
      </label>
      <button type="button" class="btn primary" data-route="#/knowledge/new">新增文件</button>
    </div>`;
}

function renderTable(items) {
  if (!items.length) {
    return renderEmptyState("找不到符合條件的文件", "調整搜尋或篩選條件後再試一次。");
  }
  return `
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>標題</th>
            <th>狀態</th>
            <th>擁有單位</th>
            <th>最後更新</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${items.map((doc) => `
            <tr>
              <td>
                <button type="button" class="link-button" data-open-doc="${escapeHtml(doc.document_id)}">
                  ${escapeHtml(doc.title)}
                </button>
              </td>
              <td>${renderStatusBadge(doc.status, statusLabel(doc.status))}</td>
              <td>${escapeHtml(doc.owner_unit_id)}</td>
              <td>${new Date(doc.updated_at).toLocaleString("zh-TW")}</td>
              <td class="table-actions">
                <button type="button" class="btn secondary btn-sm" data-open-doc="${escapeHtml(doc.document_id)}">查看</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

export async function renderKnowledgeListView(app, query) {
  const filters = {
    status: query.get("status") || "",
    query: query.get("query") || "",
    owner_unit_id: query.get("owner_unit_id") || "",
  };

  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <p class="eyebrow">知識庫</p>
          <h2>知識文件</h2>
        </div>
      </header>
      ${renderFilters(filters)}
      <div id="knowledgeContent">${renderSkeleton(5)}</div>
    </section>`;

  const container = app.querySelector("#knowledgeContent");
  const searchInput = app.querySelector("#knowledgeSearch");
  const statusSelect = app.querySelector("#knowledgeStatus");

  async function loadList() {
    container.innerHTML = renderSkeleton(5);
    try {
      const payload = await api(`/api/documents${buildQuery(filters)}`);
      container.innerHTML = renderTable(payload.items || []);
      container.querySelectorAll("[data-open-doc]").forEach((node) => {
        node.addEventListener("click", () => navigate(`#/knowledge/${node.dataset.openDoc}`));
      });
    } catch (error) {
      container.innerHTML = renderError(error.message);
      container.querySelector("[data-retry]")?.addEventListener("click", loadList);
    }
  }

  function applyFilters() {
    filters.query = searchInput.value.trim();
    filters.status = statusSelect.value;
    navigate(`#/knowledge${buildQuery(filters)}`);
  }

  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyFilters();
  });
  statusSelect.addEventListener("change", applyFilters);
  app.querySelectorAll("[data-route]").forEach((node) => {
    node.addEventListener("click", () => navigate(node.dataset.route));
  });

  await loadList();
}
