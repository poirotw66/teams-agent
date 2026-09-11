/**
 * BU「我的工作」hub — aggregates existing queues without merging domain state.
 * Sources may partially fail; never show a fake zero for a failed source.
 */

import { api, el } from "../api.js";
import { createPageController } from "../app/lifecycle.js";
import { actorCapabilities, canUseKnowledgeUi, getCapabilities } from "../app/capabilities.js";
import { labelStatus } from "../app/labels.js";
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

function localizeStatus(status) {
  return labelStatus(status);
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
    "warning",
    `暫無法取得${label}：${error?.message || error || "未知錯誤"}。不代表目前沒有待辦。`,
  );
}

async function loadDocumentQueues() {
  if (!canUseKnowledgeUi()) {
    return { ok: false, skipped: true, rows: [], itemCount: 0 };
  }
  try {
    const data = await api("/api/knowledge/dashboard");
    const queues = data.work_queues || data.workQueues || [];
    const rows = [];
    let itemCount = 0;
    for (const queue of queues) {
      const name = queue.label || queue.name || queue.queue || "文件工作";
      const queueCount = Number(queue.count || queue.total || 0);
      const filterStatus = queue.filter_status || queue.filterStatus || "";
      const route = String(queue.route || "#/knowledge");
      let previewItems = queue.items || queue.documents || [];
      const isReviewQueue = /review/i.test(route);
      if (queueCount > 0 && !previewItems.length) {
        try {
          if (filterStatus) {
            const list = await api(
              `/api/knowledge/documents?status=${encodeURIComponent(filterStatus)}`,
            );
            previewItems = list.items || list.documents || [];
          } else if (isReviewQueue) {
            try {
              const list = await api("/api/knowledge/reviews/pending");
              previewItems = (list.items || list.reviews || []).map((item) => ({
                ...item,
                document_id: item.document_id || item.documentId,
                title: item.title || item.document_title || item.document_id,
                status: "待審核",
                _reviewPreview: true,
              }));
            } catch {
              previewItems = [];
            }
            if (!previewItems.length) {
              const list = await api("/api/knowledge/documents?status=IN_REVIEW");
              previewItems = (list.items || list.documents || []).map((item) => ({
                ...item,
                _reviewPreview: true,
                status: item.status || "IN_REVIEW",
              }));
            }
          }
        } catch {
          previewItems = [];
        }
      }
      for (const item of previewItems.slice(0, 5)) {
        const docId = item.document_id || item.documentId || item.id;
        const title = item.title || item.document_title || docId || name;
        const isReviewItem = Boolean(item._reviewPreview) || isReviewQueue;
        itemCount += 1;
        rows.push({
          title,
          type: isReviewItem ? "文件審核" : "文件待辦",
          nextStep: isReviewItem ? "審核修訂" : name,
          owner:
            (item.owner_unit_ids || item.ownerUnitIds || []).join(", ")
            || item.owner_unit_id
            || item.submitted_by
            || item.assignee
            || "—",
          status: item.lifecycle_status || item.status || filterStatus || name,
          kind: "item",
          actionLabel: isReviewItem ? "審核" : "開啟文件",
          open: () =>
            navigateTo(
              isReviewItem ? "knowledgeReviews" : "knowledgePortal",
              isReviewItem
                ? (docId ? { k: `/knowledge/${docId}` } : {})
                : { k: docId ? `/knowledge/${docId}` : route },
            ),
        });
      }
      const shown = Math.min(5, previewItems.length);
      const remaining = Math.max(0, queueCount - shown);
      if (remaining > 0 || (queueCount > 0 && !previewItems.length)) {
        if (!previewItems.length) itemCount += queueCount;
        const listTarget = isReviewQueue
          ? "knowledgeReviews"
          : "knowledgePortal";
        const listPath = filterStatus
          ? `/knowledge?status=${encodeURIComponent(filterStatus)}`
          : route.replace(/^#/, "") || "/knowledge";
        rows.push({
          title: name,
          type: isReviewQueue ? "文件審核（彙總）" : "文件待辦（彙總）",
          nextStep: previewItems.length
            ? `其餘 ${remaining} 件請開啟清單`
            : (isReviewQueue
              ? "明細可能受單位範圍限制；請開啟待審清單確認"
              : "先開啟清單，再選一件處理"),
          owner: "—",
          status: previewItems.length ? `${remaining} 件其餘` : `${queueCount} 件`,
          kind: "aggregate",
          actionLabel: previewItems.length
            ? `查看其餘待辦（共 ${queueCount} 件）`
            : (isReviewQueue ? `查看 ${queueCount} 件待審` : `查看 ${queueCount} 件待辦文件`),
          open: () =>
            navigateTo(
              listTarget,
              listTarget === "knowledgePortal" ? { k: listPath } : {},
            ),
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
        kind: "empty",
        actionLabel: "查看文件待辦",
        open: () => navigateTo("knowledgeWork"),
      });
    }
    return { ok: true, rows, itemCount };
  } catch (error) {
    return { ok: false, error, rows: [], itemCount: 0 };
  }
}

async function loadPendingReviews() {
  if (!canUseKnowledgeUi()) {
    return { ok: false, skipped: true, rows: [], itemCount: 0 };
  }
  const caps = getCapabilities() || {};
  if (!(caps.knowledgeCapabilities || []).includes("knowledge.review")) {
    return { ok: false, skipped: true, rows: [], itemCount: 0 };
  }
  try {
    const data = await api("/api/knowledge/reviews/pending");
    const items = data.items || data.reviews || [];
    const total = Number(data.total || data.count || items.length || 0);
    const rows = items.slice(0, 5).map((item) => {
      const docId = item.document_id || item.documentId;
      const title = item.title || item.document_title || docId || "待審文件";
      return {
        title,
        type: "文件審核",
        nextStep: "審核修訂",
        owner: item.submitted_by || item.author || "—",
        status: "待審核",
        kind: "item",
        actionLabel: "審核",
        open: () =>
          navigateTo("knowledgeReviews", docId ? { k: `/knowledge/${docId}` } : {}),
      };
    });
    if (total > rows.length) {
      rows.push({
        title: "待審文件",
        type: "文件審核（彙總）",
        nextStep: `其餘 ${total - rows.length} 件請開啟清單`,
        owner: "—",
        status: `${total - rows.length} 件其餘`,
        kind: "aggregate",
        actionLabel: `查看全部 ${total} 件待審`,
        open: () => navigateTo("knowledgeReviews"),
      });
    } else if (!rows.length && total > 0) {
      rows.push({
        title: "待審文件",
        type: "文件審核（彙總）",
        nextStep: "先開啟清單，再選一件審核",
        owner: "—",
        status: `${total} 件`,
        kind: "aggregate",
        actionLabel: `查看 ${total} 件待審文件`,
        open: () => navigateTo("knowledgeReviews"),
      });
    }
    return { ok: true, itemCount: total || rows.length, rows };
  } catch (error) {
    return { ok: false, error, rows: [], itemCount: 0 };
  }
}

async function loadQualityTasks(tab) {
  const allowed = actorCapabilities();
  if (!allowed.has("ops.quality.read") && !allowed.has("ops.feedback.read")) {
    return { ok: false, skipped: true, rows: [], itemCount: 0, scopeNote: "" };
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
    let scopeNote = "單位／可見範圍內進行中案件";
    if (tab === "mine" && userId) {
      const mine = filtered.filter((item) =>
        String(item.assignee_id || "").toLowerCase() === userId,
      );
      if (mine.length) {
        filtered = mine;
        scopeNote = "指派給我的進行中案件";
      } else {
        filtered = [];
        scopeNote = "目前沒有指派給我的案件；單位可見待辦請到改善案件查看";
      }
    }
    if (tab === "tracking") {
      filtered = filtered.filter((item) => item.status === "OBSERVING");
      scopeNote = "觀察中案件";
    }
    const rows = filtered.slice(0, 12).map((item) => ({
      title: item.title || item.case_id,
      type: "改善案件",
      nextStep: item.status === "OBSERVING" ? "觀察成效" : "查證並處理",
      owner: item.assignee_id || item.owner_unit_id || "—",
      status: item.status,
      kind: "item",
      actionLabel: "處理案件",
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
    }));
    const remaining = filtered.length - rows.length;
    if (remaining > 0) {
      rows.push({
        title: "改善案件",
        type: "改善案件（彙總）",
        nextStep: `其餘 ${remaining} 件請開啟改善案件清單`,
        owner: "—",
        status: `${remaining} 件其餘`,
        kind: "aggregate",
        actionLabel: `查看其餘案件（共 ${filtered.length} 件）`,
        open: () =>
          navigateTo(
            "quality",
            withReturnTo({ tab: "cases" }, "workHub", { tab }),
          ),
      });
    }
    return {
      ok: true,
      itemCount: filtered.length,
      scopeNote,
      rows,
    };
  } catch (error) {
    return { ok: false, error, rows: [], itemCount: 0, scopeNote: "" };
  }
}

async function loadEvalReviews() {
  const allowed = actorCapabilities();
  if (!allowed.has("ops.evals.read")) {
    return { ok: false, skipped: true, rows: [], itemCount: 0 };
  }
  try {
    const data = await api("/api/evaluations/cases?status=IN_REVIEW&limit=20");
    const items = data.items || data.cases || [];
    const reportedTotal = Number(data.total ?? data.count ?? items.length);
    const total = Number.isFinite(reportedTotal)
      ? Math.max(items.length, reportedTotal)
      : items.length;
    const rows = items.slice(0, 12).map((item) => ({
      title: item.title || item.case_id || "驗收題目",
      type: "品質驗收",
      nextStep: "審核題目",
      owner: item.owner_unit_id || "—",
      status: item.status || "IN_REVIEW",
      kind: "item",
      actionLabel: "審核題目",
      open: () => navigateTo("evaluations", { tab: "cases", caseId: item.case_id }),
    }));
    const remaining = Math.max(0, total - rows.length);
    if (remaining > 0) {
      rows.push({
        title: "驗收題目",
        type: "品質驗收（彙總）",
        nextStep: `其餘 ${remaining} 件請開啟品質驗收清單`,
        owner: "—",
        status: `${remaining} 件其餘`,
        kind: "aggregate",
        actionLabel: `查看其餘驗收題目（共 ${total} 件）`,
        open: () => navigateTo("evaluations", { tab: "cases" }),
      });
    }
    return {
      ok: true,
      itemCount: total,
      rows,
    };
  } catch (error) {
    return { ok: false, error, rows: [], itemCount: 0 };
  }
}

function buildTable(rows) {
  const wrap = el("div", "table-responsive");
  const table = el("table");
  table.innerHTML =
    "<thead><tr><th>任務</th><th>類型</th><th>下一步</th><th>負責人</th><th>狀態</th><th>操作</th></tr></thead>";
  const body = el("tbody");
  for (const item of rows) {
    const button = el(
      "button",
      item.kind === "aggregate" || item.kind === "empty"
        ? "button-secondary"
        : "button-primary",
      item.actionLabel || "處理",
    );
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

function countUnits(rows) {
  let items = 0;
  let aggregates = 0;
  for (const row of rows) {
    if (row.kind === "aggregate") {
      const match = String(row.status || "").match(/(\d+)/);
      aggregates += match ? Number(match[1]) : 1;
    } else if (row.kind !== "empty") {
      items += 1;
    }
  }
  return { items, aggregates, display: items + aggregates };
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
    el(
      "p",
      "metric-label",
      "先處理影響回答品質的工作。標示「彙總」的項目會先進入清單，再選一筆才到處理畫面；其餘可直接處理。",
    ),
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

  const mineCount = countUnits(mineRows);
  const reviewCount = countUnits(reviewRows);
  const trackingCount = countUnits(trackingRows);

  const stats = el("div", "stats bu-work-stats");
  const mineHint =
    tab === "mine" && cases.scopeNote
      ? cases.scopeNote
      : "指派給我的進行中案件";
  for (const [key, label, value, hint] of [
    [
      "mine",
      "我的待處理",
      String(mineCount.display),
      `${mineHint}；數字為任務件數。彙總入口以背後件數計，點進後還需再選一筆。`,
    ],
    [
      "review",
      "待我審核",
      reviews.ok || evals.ok ? String(reviewCount.display) : "—",
      "待審文件與驗收題目件數",
    ],
    [
      "tracking",
      "追蹤中",
      String(
        trackingCount.display ||
          (cases.ok
            ? cases.rows.filter((r) => r.status === "OBSERVING").length
            : 0),
      ),
      "觀察中案件",
    ],
  ]) {
    const card = el("button", `stat${key === tab ? " is-active" : ""}`);
    card.type = "button";
    card.title = hint;
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
  surface.append(
    el(
      "p",
      "metric-label",
      tab === "mine"
        ? "我的待處理：只顯示指派給我的改善案件；未指派或他人案件不會混入此區。文件待辦另依你的文件權限列出。"
        : tab === "review"
          ? "待我審核：文件審核與驗收題目。彙總列會先開清單。"
          : "追蹤中：觀察中的改善案件與相關文件動態。",
    ),
  );
  if (cases.ok && tab === "mine" && cases.scopeNote) {
    surface.append(el("p", "metric-label", cases.scopeNote));
  }
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

  const shortcuts = el("div", "filter-bar bu-work-shortcuts");
  shortcuts.append(
    el("span", "metric-label", "快捷入口"),
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
