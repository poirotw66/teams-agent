import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
import { statusBadge } from "../components/badges.js";
import { faqField } from "../components/forms.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderMasking() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/masking");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "遮罩政策版本"));
    if (allowed.has("ops.retention.write")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("Policy version", "policy_version", "mask-v2"),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "建立遮罩候選");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        await api("/api/governance/masking/candidates", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            policy_version: String(values.get("policy_version") || "").trim(),
            reason: String(values.get("reason") || "").trim(),
          }),
        });
        await renderMasking();
      });
      panel.append(form);
    }
    const items = (data.items || []).slice().reverse();
    if (!items.length) {
      panel.append(el("p", "empty", "目前無遮罩政策版本紀錄。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Version</th><th>Hash</th><th>狀態</th><th>建立者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const item of items) {
        const actions = el("td");
        if (allowed.has("ops.retention.write") && item.status === "CANDIDATE") {
          const approve = el("button", "", "核准");
          approve.addEventListener("click", async () => {
            const reason = window.prompt("核准原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/masking/${item.version_id}/approve`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderMasking();
          });
          actions.append(approve);
        }
        if (allowed.has("ops.retention.write") && item.status === "APPROVED") {
          const activate = el("button", "", "啟用");
          activate.addEventListener("click", async () => {
            const reason = window.prompt("啟用原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/masking/${item.version_id}/activate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderMasking();
          });
          actions.append(activate);
        }
        const statusCell = el("td");
        statusCell.append(statusBadge(item.status));
        const row = el("tr");
        row.append(
          el("td", "", item.policy_version),
          el("td", "", (item.rules_hash || "").slice(0, 12)),
          statusCell,
          el("td", "", item.created_by),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const scroll = el("div", "table-responsive");
      scroll.append(table);
      panel.append(scroll);
    }
    presentSystemPage(
      "遮罩政策",
      "管理敏感資料遮罩政策版本。",
      panel,
    );
  } catch (error) {
    presentSystemPage("遮罩政策", null, el("div", "error", error.message));
  }
}

export const maskingPage = createPageController({
  enter: async () => renderMasking(),
  update: async () => renderMasking(),
  leave: async () => {},
});
