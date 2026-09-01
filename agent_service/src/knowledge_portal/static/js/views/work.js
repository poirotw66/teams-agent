import { releaseLabel } from "../labels.js";
import { api } from "../api.js";
import { can } from "../capabilities.js";
import { fluentButton } from "../fluent.js";
import { ROLE_LABELS } from "../labels.js";
import { navigate } from "../router.js";
import {
  escapeHtml,
  handleViewError,
  isForbiddenError,
  renderSkeleton,
  renderViewEmpty,
} from "../ui.js?v=20260831e";

const ROLE_SUBTITLES = {
  CONTRIBUTOR: "優先處理你的草稿與被退回內容",
  REVIEWER: "優先處理待審文件",
  MANAGER: "監控待審、發布失敗與即將到期文件",
  PLATFORM: "監控待審、發布失敗與即將到期文件",
  AUDITOR: "查閱系統操作軌跡",
};

const QUEUE_VARIANTS = {
  "我的草稿": "draft",
  "被退回內容": "changes",
  "待審文件": "review",
  "發布失敗": "failed",
  "即將到期": "due",
};

const EMPTY_BY_ROLE = {
  CONTRIBUTOR: {
    title: "目前沒有急迫事項",
    message: "你可以到知識庫瀏覽文件，或建立新的草稿。",
    action: () => (can("create_document")
      ? fluentButton("新增文件", { appearance: "accent", dataset: { route: "#/knowledge/new" } })
      : fluentButton("瀏覽知識庫", { appearance: "outline", dataset: { route: "#/knowledge" } })),
  },
  REVIEWER: {
    title: "目前沒有待審文件",
    message: "新的送審項目會出現在待審清單，你可以先到知識庫了解現有內容。",
    action: () => fluentButton("前往待審清單", { appearance: "outline", dataset: { route: "#/reviews" } }),
  },
  MANAGER: {
    title: "目前沒有急迫事項",
    message: "系統運作正常。你可以查看發布紀錄或知識庫概況。",
    action: () => (can("list_releases")
      ? fluentButton("查看發布紀錄", { appearance: "outline", dataset: { route: "#/releases" } })
      : fluentButton("瀏覽知識庫", { appearance: "outline", dataset: { route: "#/knowledge" } })),
  },
  PLATFORM: {
    title: "目前沒有急迫事項",
    message: "系統運作正常。你可以查看發布紀錄或知識庫概況。",
    action: () => fluentButton("查看發布紀錄", { appearance: "outline", dataset: { route: "#/releases" } }),
  },
  AUDITOR: {
    title: "目前沒有急迫事項",
    message: "你可以前往稽核紀錄查閱近期操作軌跡。",
    action: () => fluentButton("前往稽核紀錄", { appearance: "outline", dataset: { route: "#/audit" } }),
  },
};

function queueCard(item) {
  const filter = item.filter_status ? `?status=${encodeURIComponent(item.filter_status)}` : "";
  const variant = QUEUE_VARIANTS[item.label] || "draft";
  return `
    <button type="button" class="queue-card queue-card--${variant}" data-route="${escapeHtml(item.route + filter)}">
      <span class="queue-label">${escapeHtml(item.label)}</span>
      <strong class="queue-count">${item.count}</strong>
    </button>`;
}

function renderReleaseStrip(dashboard) {
  if (!can("list_releases") && !dashboard.active_release_id) return "";
  return `
    <div class="release-strip" role="status">
      <span>正式知識版本</span>
      <strong>${escapeHtml(releaseLabel(dashboard.active_release_id))}</strong>
    </div>`;
}

export async function renderWorkView(app) {
  app.innerHTML = `
    <section class="page">
      <header class="page-header">
        <div>
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
    const releaseStrip = renderReleaseStrip(dashboard);
    if (!actionable.length) {
      const emptyCfg = EMPTY_BY_ROLE[role] || EMPTY_BY_ROLE.CONTRIBUTOR;
      container.innerHTML = `
        ${renderViewEmpty("work-clear", emptyCfg.action(), { title: emptyCfg.title, message: emptyCfg.message })}
        ${releaseStrip}`;
    } else {
      container.innerHTML = `
        <div class="queue-grid">${actionable.map(queueCard).join("")}</div>
        ${releaseStrip}`;
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
