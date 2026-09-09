/**
 * BU「我的工作」hub — aggregates existing queues without merging domain state.
 * Sources may partially fail; never show a fake zero for a failed source.
 */

import { api, el } from "../api.js";
import { createPageController } from "../app/lifecycle.js";
import { actorCapabilities, canUseKnowledgeUi, getCapabilities } from "../app/capabilities.js";
import { drillLink, navigateTo, saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { withReturnTo } from "../app/returnTo.js";

function currentUserId() {
  const caps = getCapabilities() || {};
  return String(caps.userId || caps.userName || caps.actorId || "").trim();
}

function statusTone(label) {
  if (!label) return "badge-neutral";
  if (/待|退|失敗|負|新建|已分派|修正中|待審|觀察|NEW|TRIAGED|IN_PROGRESS|WAITING|IN_REVIEW/.test(label)) {
    return "badge-warning";
  }
  if (/完成|通過|使用中|結案|已結案|無急迫|RESOLVED|OBSERVING/.test(label)) return "badge-success";
  return "badge-neutral";
}

const CASE_STATUS_LABELS = {
  NEW: "新建",
  TRIAGED: "已分派",
  IN_PROGRESS: "修正中",
  WAITING_REVIEW: "待審核",
  OBSERVING: "觀察中",
  RESOLVED: "已結案",
  WONT_FIX: "不處理",
  DUPLICATE: "重複",
  IN_REVIEW: "審核中",
};

function localizeStatus(status) {
  const raw = String(status || "").trim();
  return CASE_STATUS_LABELS[raw] || raw || "—";
}

function taskRow({ title, type, nextStep, owner, status, action }) {
  const row = el("tr");
  row.append(
    el("td", "", title),
    el("td", "", type),
    el("td", "", nextStep),
    el("td", "", owner || "—"),
  );
  const statusCell = el("td");
  const badge = el("span", `badge ${statusTone(status)}`, status || "—");
  statusCell.append(badge);
  row.append(statusCell);
  const actionCell = el("td");
  actionCell.append(action);
  row.append(actionCell);
  return row;
}

function sectionError(label, error) {
  return el(
    "div",
    "callout",
    `暫無法取得${label}：${error?.message || error || "未知錯誤"}。不代表目前沒有待辦。`,
  );
}

async function loadDocumentQueues() {
  if (!canUseKnowledgeUi()) {
    return { ok: false, skipped: true, rows: [] };
  }
  try {
    const data = await api("/api/knowledge/dashboard");
    const queues = data.work_queues || data.workQueues || [];
    const rows = [];
    for (const queue of queues) {
      const name = queue.label || queue.name || queue.queue || "文件工作";
      const items = queue.items || queue.documents || [];
      for (const item of items.slice(0, 8)) {
        const docId = item.document_id || item.documentId || item.id;
        const title = item.title || docId || name;
        rows.push({
          title,
          type: "文件待辦",
          nextStep: name,
          owner: (item.owner_unit_ids || item.ownerUnitIds || []).join(", ") || item.assignee || "—",
          status: item.lifecycle_status || item.status || name,
          open: () =>
            navigateTo("knowledgePortal", {
              k: docId ? `/knowledge/${docId}` : "#/work",
            }),
        });
      }
      if (!items.length && (queue.count || queue.total)) {
        rows.push({
          title: name,
          type: "文件待辦",
          nextStep: "開啟完整清單",
          owner: "—",
          status: `${queue.count || queue.total} 件`,
          open: () => navigateTo("knowledgeWork"),
        });
      }
    }
    if (!rows.length) {
      rows.push({
        title: "文件工作佇列",
        type: "文件待辦",
        nextStep: "查看完整待辦",
        owner: "—",
        status: "無急迫項目",
        open: () => navigateTo("knowledgeWork"),
      });
    }
    return { ok: true, rows };
  } catch (error) {
    return { ok: false, error, rows: [] };
  }
}

async function loadPendingReviews() {
  if (!canUseKnowledgeUi()) {
    return { ok: false, skipped: true, rows: [] };
  }
  const caps = getCapabilities() || {};
  if (!(caps.knowledgeCapabilities || []).includes("knowledge.review")) {
    return { ok: false, skipped: true, rows: [] };
  }
  try {
    const data = await api("/api/knowledge/reviews/pending");
    const items = data.items || data.reviews || [];
    return {
      ok: true,
      rows: items.slice(0, 12).map((item) => {
        const docId = item.document_id || item.documentId;
        const title = item.title || docId || "待審文件";
        return {
          title,
          type: "文件審核",
          nextStep: "審核修訂",
          owner: item.submitted_by || item.author || "—",
          status: "待審核",
          open: () =>
            navigateTo("knowledgeReviews", docId ? { k: `/knowledge/${docId}` } : {}),
        };
      }),
    };
  } catch (error) {
    return { ok: false, error, rows: [] };
  }
}

async function loadQualityTasks(tab) {
  const allowed = actorCapabilities();
  if (!allowed.has("ops.quality.read") && !allowed.has("ops.feedback.read")) {
    return { ok: false, skipped: true, rows: [] };
  }
  try {
    const data = await api("/api/quality-cases?limit=50");
    const items = data.items || data.cases || [];
    const userId = currentUserId().toLowerCase();
    const openStatuses = new Set([
      "NEW",
      "TRIAGED",
      "IN_PROGRESS",
      "WAITING_REVIEW",
      "OBSERVING",
    ]);
    let filtered = items.filter((item) => openStatuses.has(item.status));
    if (tab === "mine" && userId) {
      const mine = filtered.filter((item) =>
        String(item.assignee_id || "").toLowerCase() === userId,
      );
      filtered = mine.length ? mine : filtered.slice(0, 12);
    }
    if (tab === "tracking") {
      filtered = filtered.filter((item) => item.status === "OBSERVING");
    }
    return {
      ok: true,
      rows: filtered.slice(0, 12).map((item) => ({
        title: item.title || item.case_id,
        type: "改善案件",
        nextStep: item.status === "OBSERVING" ? "觀察成效" : "查證並處理",
        owner: item.assignee_id || item.owner_unit_id || "—",
        status: item.status,
        open: () => {
          navigateTo(
            "quality",
            withReturnTo(
              { caseId: item.case_id, tab: "cases" },
              "workHub",
              { tab },
            ),
          );
        },
      })),
    };
  } catch (error) {
    return { ok: false, error, rows: [] };
  }
}

async function loadEvalReviews() {
  const allowed = actorCapabilities();
  if (!allowed.has("ops.evals.read")) {
    return { ok: false, skipped: true, rows: [] };
  }
  try {
    const data = await api("/api/evaluations/cases?status=IN_REVIEW&limit=20");
    const items = data.items || data.cases || [];
    return {
      ok: true,
      rows: items.slice(0, 12).map((item) => ({
        title: item.title || item.case_id || "驗收題目",
        type: "品質驗收",
        nextStep: "審核題目",
        owner: item.owner_unit_id || "—",
        status: item.status || "IN_REVIEW",
        open: () => navigateTo("evaluations", { tab: "cases", caseId: item.case_id }),
      })),
    };
  } catch (error) {
    return { ok: false, error, rows: [] };
  }
}

function buildTable(rows) {
  const wrap = el("div", "table-responsive");
  const table = el("table");
  table.innerHTML =
    "<thead><tr><th>任務</th><th>類型</th><th>下一步</th><th>負責人</th><th>狀態</th><th>操作</th></tr></thead>";
  const body = el("tbody");
  for (const item of rows) {
    const button = el("button", "button-primary", "處理");
    button.type = "button";
    button.addEventListener("click", () => item.open());
    body.append(
      taskRow({
        title: item.title,
        type: item.type,
        nextStep: item.nextStep,
        owner: item.owner,
        status: localizeStatus(item.status),
        action: button,
      }),
    );
  }
  table.append(body);
  wrap.append(table);
  return wrap;
}

async function renderWorkHub(state = {}) {
  const app = document.getElementById("app");
  const tab = state.tab || "mine";
  app.replaceChildren(el("div", "empty", "載入中…"));

  const caps = getCapabilities() || {};
  const displayName = caps.displayName || caps.userName || "同事";

  const header = el("div");
  header.append(el("h2", "", `早安，${displayName}`));
  header.append(
    el("p", "metric-label", "先處理影響回答品質的工作，從這裡繼續。"),
  );

  const [docs, reviews, cases, evals] = await Promise.all([
    loadDocumentQueues(),
    loadPendingReviews(),
    loadQualityTasks(tab),
    loadEvalReviews(),
  ]);

  const mineRows = [];
  const reviewRows = [];
  const trackingRows = [];
  const errors = [];

  if (docs.ok) mineRows.push(...docs.rows.filter((r) => r.status !== "無急迫項目"));
  else if (!docs.skipped) errors.push(sectionError("文件待辦", docs.error));

  if (cases.ok) {
    if (tab === "tracking") trackingRows.push(...cases.rows);
    else mineRows.push(...cases.rows);
  } else if (!cases.skipped) {
    errors.push(sectionError("改善案件", cases.error));
  }

  if (reviews.ok) reviewRows.push(...reviews.rows);
  else if (!reviews.skipped) errors.push(sectionError("文件待審", reviews.error));

  if (evals.ok) reviewRows.push(...evals.rows);
  else if (!evals.skipped) errors.push(sectionError("驗收待審", evals.error));

  if (docs.ok && tab === "tracking") {
    trackingRows.push(
      ...docs.rows.filter((r) => /觀察|發布|同步/.test(String(r.nextStep || r.status || ""))),
    );
  }

  const stats = el("div", "stats bu-work-stats");
  for (const [key, label, value] of [
    ["mine", "我的待處理", String(mineRows.length)],
    [
      "review",
      "待我審核",
      reviewRows.length
        ? String(reviewRows.length)
        : reviews.ok || evals.ok
          ? "0"
          : "—",
    ],
    [
      "tracking",
      "追蹤中",
      String(
        trackingRows.length ||
          (cases.ok
            ? cases.rows.filter((r) => r.status === "OBSERVING").length
            : 0),
      ),
    ],
  ]) {
    const card = el("button", `stat${key === tab ? " is-active" : ""}`);
    card.type = "button";
    card.append(el("span", "", label), el("b", "", value));
    card.addEventListener("click", () => {
      saveNavFilters({ view: "workHub", tab: key });
      syncLocationHash("workHub", { tab: key });
      void renderWorkHub({ tab: key });
    });
    stats.append(card);
  }

  const listRows =
    tab === "review" ? reviewRows : tab === "tracking" ? trackingRows : mineRows;

  const surface = el("section", "panel");
  if (errors.length) {
    for (const node of errors) surface.append(node);
  }
  if (!listRows.length && !errors.length) {
    surface.append(
      el("div", "empty", "目前沒有此分類的待辦。可從改善案件或知識內容繼續。"),
      drillLink("前往改善案件", "quality"),
      drillLink("前往知識內容", "contentLists"),
    );
  } else if (listRows.length) {
    surface.append(buildTable(listRows));
  }

  const shortcuts = el("div", "filter-bar");
  shortcuts.append(
    drillLink("完整文件待辦", "knowledgeWork"),
    drillLink("待審清單", "knowledgeReviews"),
    drillLink("改善案件", "quality"),
    drillLink("品質驗收", "evaluations"),
  );

  app.replaceChildren(header, stats, surface, shortcuts);
}

export const workHubPage = createPageController({
  enter: async (context = {}) => {
    const tab = context.state?.tab || undefined;
    await renderWorkHub({ tab });
  },
  update: async (context = {}) => {
    const tab = context.state?.tab || undefined;
    await renderWorkHub({ tab });
  },
  leave: async () => {},
});
