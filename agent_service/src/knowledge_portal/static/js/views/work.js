import { api } from "../api.js";
import { navigate } from "../router.js";
import { escapeHtml, renderEmptyState, renderError, renderLoading } from "../ui.js";

function queueCard(item) {
  const filter = item.filter_status ? `?status=${encodeURIComponent(item.filter_status)}` : "";
  return `
    <button type="button" class="queue-card" data-route="${escapeHtml(item.route + filter)}">
      <span class="queue-label">${escapeHtml(item.label)}</span>
      <strong class="queue-count">${item.count}</strong>
    </button>`;
}

export async function renderWorkView(app) {
  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <p class="eyebrow">我的工作</p>
          <h2>待處理事項</h2>
        </div>
      </header>
      <div id="workContent">${renderLoading()}</div>
    </section>`;

  const container = app.querySelector("#workContent");
  try {
    const dashboard = await api("/api/dashboard");
    const queues = dashboard.work_queues || [];
    const actionable = queues.filter((item) => item.count > 0);
    if (!actionable.length) {
      container.innerHTML = renderEmptyState(
        "目前沒有急迫事項",
        "你可以到知識庫瀏覽文件，或建立新的草稿。",
        `<button type="button" class="btn primary" data-route="#/knowledge/new">新增文件</button>`,
      );
    } else {
      container.innerHTML = `
        <div class="queue-grid">${actionable.map(queueCard).join("")}</div>
        <div class="panel muted-panel">
          <p>正式版本：${escapeHtml(dashboard.active_release_id || "尚未發布")}</p>
        </div>`;
    }
    container.querySelectorAll("[data-route]").forEach((node) => {
      node.addEventListener("click", () => navigate(node.dataset.route));
    });
    return dashboard;
  } catch (error) {
    container.innerHTML = renderError(error.message);
    container.querySelector("[data-retry]")?.addEventListener("click", () => renderWorkView(app));
    throw error;
  }
}
