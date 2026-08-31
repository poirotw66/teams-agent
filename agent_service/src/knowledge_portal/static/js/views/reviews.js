import { api } from "../api.js";
import { fluentButton } from "../fluent.js";
import { navigate } from "../router.js";
import {
  escapeHtml,
  handleViewError,
  isForbiddenError,
  renderSkeleton,
  renderViewEmpty,
} from "../ui.js?v=20260831e";

export async function renderReviewsView(app) {
  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
          <h2>審核工作區</h2>
        </div>
      </header>
      <div id="reviewsContent">${renderSkeleton(4)}</div>
    </section>`;

  const container = app.querySelector("#reviewsContent");
  try {
    const payload = await api("/api/reviews/pending");
    const items = payload.items || [];
    if (!items.length) {
      container.innerHTML = renderViewEmpty(
        "reviews-empty",
        fluentButton("瀏覽知識庫", { appearance: "outline", dataset: { route: "#/knowledge" } }),
      );
      container.querySelector("[data-route]")?.addEventListener("click", () => navigate("#/knowledge"));
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
                  ${fluentButton("開啟審核", { appearance: "outline", dataset: { "open-doc": item.document_id } })}
                </td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    container.querySelectorAll("[data-open-doc]").forEach((node) => {
      node.addEventListener("click", () => navigate(`#/knowledge/${node.dataset.openDoc}/review`));
    });
  } catch (error) {
    handleViewError(error, {
      view: "reviews",
      container,
      onRetry: () => renderReviewsView(app),
    });
    if (!isForbiddenError(error)) throw error;
  }
}
