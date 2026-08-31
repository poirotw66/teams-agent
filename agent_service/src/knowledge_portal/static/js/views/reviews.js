import { api } from "../api.js";
import { navigate } from "../router.js";
import { escapeHtml, renderEmptyState, renderError, renderLoading } from "../ui.js";

export async function renderReviewsView(app) {
  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <p class="eyebrow">待審核</p>
          <h2>審核工作區</h2>
        </div>
      </header>
      <div id="reviewsContent">${renderLoading()}</div>
    </section>`;

  const container = app.querySelector("#reviewsContent");
  try {
    const payload = await api("/api/reviews/pending");
    const items = payload.items || [];
    if (!items.length) {
      container.innerHTML = renderEmptyState("目前沒有待審文件", "新的送審項目會出現在這裡。");
      return;
    }
    container.innerHTML = `
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>文件</th>
              <th>送審者</th>
              <th>送審時間</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${items.map((item) => `
              <tr>
                <td>${escapeHtml(item.document_title)}</td>
                <td>${escapeHtml(item.submitted_by)}</td>
                <td>${new Date(item.submitted_at).toLocaleString("zh-TW")}</td>
                <td>
                  <button type="button" class="btn secondary btn-sm" data-open-doc="${escapeHtml(item.document_id)}">
                    開啟審核
                  </button>
                </td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    container.querySelectorAll("[data-open-doc]").forEach((node) => {
      node.addEventListener("click", () => navigate(`#/knowledge/${node.dataset.openDoc}/overview`));
    });
  } catch (error) {
    if (error.status === 403) {
      container.innerHTML = renderEmptyState("無待審清單權限", "此清單僅供審核者、管理者或稽核人員使用。");
      return;
    }
    container.innerHTML = renderError(error.message);
    container.querySelector("[data-retry]")?.addEventListener("click", () => renderReviewsView(app));
  }
}
