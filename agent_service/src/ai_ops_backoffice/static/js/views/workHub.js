/**
 * First-demo home: what to do now, using the prepared VPN story only.
 * Live queues stay on their own pages so this screen is not a metric tour.
 */

import { el } from "../api.js";
import { createPageController } from "../app/lifecycle.js";
import { loadNavFilters } from "../app/navigation.js";
import {
  renderVpnCase,
  renderVpnComparison,
  vpnWorkItems,
} from "../demo/vpnStory.js";

function taskCard({ problem, reason, owner, nextStep, actionLabel, open }) {
  const card = el("article", "demo-task");
  card.append(
    el("h3", "", problem),
    el("p", "", reason),
    el("p", "ov-lead", `負責人：${owner}`),
    el("p", "ov-lead", `下一步：${nextStep}`),
  );
  const button = el("button", "button-primary", actionLabel);
  button.type = "button";
  button.addEventListener("click", open);
  card.append(button);
  return card;
}

function renderWorkHub() {
  const app = document.getElementById("app");
  const story = loadNavFilters().story || "";
  if (story === "case") {
    renderVpnCase(app);
    return;
  }
  if (story === "compare") {
    renderVpnComparison(app);
    return;
  }
  const demo = vpnWorkItems();
  const page = el("section", "demo-home");
  const header = el("div", "bu-page-header");
  header.append(
    el("h2", "", "待處理問題"),
    el("p", "ov-lead", "先看員工問了什麼，再處理負評、審核文件、確認改善。"),
  );
  page.append(header);

  const sections = [
    ["待我處理", [demo.seen, demo.mine]],
    ["待我審核", [demo.review]],
    ["最近完成改善", [demo.done]],
  ];
  for (const [title, items] of sections) {
    const section = el("section", "ov-panel");
    section.append(el("h3", "ov-panel-title", title));
    for (const item of items) {
      section.append(taskCard(item));
    }
    page.append(section);
  }

  page.append(
    el(
      "p",
      "ov-lead",
      "現場可以試著：找到這筆負評的原因，開啟要修改的文件，指出下一步。",
    ),
  );
  app.replaceChildren(page);
}

export const workHubPage = createPageController({
  enter: async () => {
    renderWorkHub();
  },
  update: async () => {
    renderWorkHub();
  },
  leave: async () => {},
});
