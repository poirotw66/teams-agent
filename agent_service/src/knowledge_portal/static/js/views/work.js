import { releaseLabel } from "../labels.js";
import { api } from "../api.js";
import { fluentButton } from "../fluent.js";
import { ROLE_LABELS } from "../labels.js";
import { navigate } from "../router.js";
import {
  escapeHtml,
  handleViewError,
  isForbiddenError,
  renderSkeleton,
  renderViewEmpty,
} from "../ui.js?v=20260831c";

const ROLE_SUBTITLES = {
  CONTRIBUTOR: "優先處理你的草稿與被退回內容",
  REVIEWER: "優先處理待審文件",
  MANAGER: "監控待審、發布失敗與即將到期文件",
  PLATFORM: "監控待審、發布失敗與即將到期文件",
  AUDITOR: "查閱系統操作軌跡",
};

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
      <div id="workContent">${renderSkeleton(3)}</div>
    </section>`;

  const container = app.querySelector("#workContent");
  try {
    const dashboard = await api("/api/dashboard");
    const role = dashboard.actor_role || "CONTRIBUTOR";
    const subtitle = ROLE_SUBTITLES[role] || "待處理事項";
    app.querySelector(".page-header h2").insertAdjacentHTML(
      "afterend",
      `<p class="muted role-subtitle">${escapeHtml(subtitle)} · ${escapeHtml(ROLE_LABELS[role] || role)}</p>`,
    );
    const queues = dashboard.work_queues || [];
    const actionable = queues.filter((item) => item.count > 0);
    if (!actionable.length) {
      container.innerHTML = renderViewEmpty(
        "work-clear",
        fluentButton("新增文件", { appearance: "accent", dataset: { route: "#/knowledge/new" } }),
      );
    } else {
      container.innerHTML = `
        <div class="queue-grid">${actionable.map(queueCard).join("")}</div>
        <div class="panel muted-panel">
          <p>${escapeHtml(releaseLabel(dashboard.active_release_id))}</p>
        </div>`;
    }
    container.querySelectorAll("[data-route]").forEach((node) => {
      node.addEventListener("click", () => navigate(node.dataset.route));
    });
    return dashboard;
  } catch (error) {
    handleViewError(error, {
      view: "work",
      container,
      onRetry: () => renderWorkView(app),
    });
    if (!isForbiddenError(error)) throw error;
    return null;
  }
}
