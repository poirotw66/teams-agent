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

function formatTestSummary(summary) {
  if (!summary || summary.total === 0) {
    return '<span class="muted">尚未建立測試</span>';
  }
  const parts = [
    `共 ${summary.total} 題`,
    `已執行 ${summary.executed}`,
    `可回答 ${summary.pass_count}`,
  ];
  if (summary.needs_review_count) parts.push(`需確認 ${summary.needs_review_count}`);
  if (summary.fail_count) parts.push(`無法回答 ${summary.fail_count}`);
  if (!summary.meets_minimum) {
    parts.push('<span class="review-alert-inline">未達最低題數</span>');
  }
  return parts.join(" · ");
}

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
        <table class="data-table reviews-table">
          <thead>
            <tr>
              <th>文件</th>
              <th>擁有單位</th>
              <th>變更原因</th>
              <th>適用範圍</th>
              <th>測試摘要</th>
              <th>送審者</th>
              <th>送審時間</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            ${items.map((item) => `
              <tr>
                <td>${escapeHtml(item.document_title)}</td>
                <td>${escapeHtml(item.owner_unit_id || "未填")}</td>
                <td>${escapeHtml(item.change_reason || "未填")}</td>
                <td>
                  ${escapeHtml(item.audience_label || "未填")}
                  ${item.audience_changed ? '<span class="review-alert-inline">適用範圍已變更</span>' : ""}
                </td>
                <td>${formatTestSummary(item.test_summary)}</td>
                <td>${escapeHtml(item.submitted_by)}</td>
                <td>${new Date(item.submitted_at).toLocaleString("zh-TW")}</td>
                <td class="table-actions">
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
