import { api } from "../api.js";
import { escapeHtml, renderEmptyState, renderError, renderLoading } from "../ui.js";

export async function renderAuditView(app) {
  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <p class="eyebrow">稽核紀錄</p>
          <h2>操作軌跡</h2>
        </div>
      </header>
      <div id="auditContent">${renderLoading()}</div>
    </section>`;

  const container = app.querySelector("#auditContent");
  try {
    const events = await api("/api/audit-events?limit=50");
    if (!events.length) {
      container.innerHTML = renderEmptyState("尚無稽核紀錄", "系統操作會記錄在此供稽核查閱。");
      return;
    }
    container.innerHTML = `
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>動作</th>
              <th>目標</th>
              <th>時間</th>
            </tr>
          </thead>
          <tbody>
            ${events.map((event) => `
              <tr>
                <td>${escapeHtml(event.action)}</td>
                <td>${escapeHtml(event.target_type)} · ${escapeHtml(event.target_id)}</td>
                <td>${new Date(event.occurred_at).toLocaleString("zh-TW")}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  } catch (error) {
    container.innerHTML = renderError(error.message);
    container.querySelector("[data-retry]")?.addEventListener("click", () => renderAuditView(app));
  }
}
