/**
 * My Work home: live pending items only.
 * Prepared VPN demo stories stay isolated under demo/vpnStory.js and are not
 * mixed into this queue.
 */

import { api, el } from "../api.js";
import { createPageController } from "../app/lifecycle.js";
import { navigateTo } from "../app/navigation.js";

function bucketForStatus(status) {
  const normalized = String(status || "").toUpperCase();
  if (["NEW", "TRIAGED", "IN_PROGRESS"].includes(normalized)) return "pending_action";
  if (normalized === "WAITING_REVIEW") return "pending_review";
  if (normalized === "OBSERVING") return "tracking";
  return "completed";
}

function emptyState() {
  const page = el("section", "demo-home");
  const header = el("div", "bu-page-header");
  header.append(
    el("h2", "", "待處理問題"),
    el("p", "ov-lead", "目前沒有待處理項目。新的負評、審核與改善案件會顯示在這裡。"),
  );
  page.append(header);
  const panel = el("section", "ov-panel");
  panel.append(el("p", "muted", "尚無待處理問題。"));
  const actions = el("div", "demo-actions");
  const casesButton = el("button", "button-primary", "前往品質案件");
  casesButton.type = "button";
  casesButton.addEventListener("click", () => navigateTo("quality"));
  actions.append(casesButton);
  panel.append(actions);
  page.append(panel);
  return page;
}

function taskCard(item) {
  const card = el("article", "demo-task");
  card.append(
    el("h3", "", item.title || "未命名工作"),
    el("p", "", item.step || "請繼續處理此項目。"),
    el("p", "ov-lead", `狀態：${item.source_status || "—"}`),
  );
  const route = item.next_action?.route;
  if (route) {
    const button = el("button", "button-primary", "開啟");
    button.type = "button";
    button.addEventListener("click", () => {
      if (String(route).startsWith("/console-v2/")) {
        window.location.assign(route);
        return;
      }
      navigateTo("quality", { caseId: item.source_id });
    });
    card.append(button);
  }
  return card;
}

async function renderWorkHub() {
  const app = document.getElementById("app");
  let items = [];
  try {
    const payload = await api("/api/console/work-items?bucket=all&limit=50");
    items = Array.isArray(payload?.items) ? payload.items : [];
  } catch {
    items = [];
  }

  if (!items.length) {
    app.replaceChildren(emptyState());
    return;
  }

  const page = el("section", "demo-home");
  const header = el("div", "bu-page-header");
  header.append(
    el("h2", "", "待處理問題"),
    el("p", "ov-lead", "先處理指派給你的負評、審核與改善案件。"),
  );
  page.append(header);

  const withBucket = items.map((item) => ({
    ...item,
    bucket: bucketForStatus(item.source_status),
  }));
  const sections = [
    ["待我處理", withBucket.filter((item) => item.bucket === "pending_action")],
    ["待我審核", withBucket.filter((item) => item.bucket === "pending_review")],
    ["追蹤中", withBucket.filter((item) => item.bucket === "tracking")],
    ["最近完成", withBucket.filter((item) => item.bucket === "completed")],
  ];

  let rendered = 0;
  for (const [title, sectionItems] of sections) {
    if (!sectionItems.length) continue;
    const section = el("section", "ov-panel");
    section.append(el("h3", "ov-panel-title", title));
    for (const item of sectionItems) {
      section.append(taskCard(item));
      rendered += 1;
    }
    page.append(section);
  }

  if (!rendered) {
    app.replaceChildren(emptyState());
    return;
  }
  app.replaceChildren(page);
}

export const workHubPage = createPageController({
  enter: async () => {
    await renderWorkHub();
  },
  update: async () => {
    await renderWorkHub();
  },
  leave: async () => {},
});
