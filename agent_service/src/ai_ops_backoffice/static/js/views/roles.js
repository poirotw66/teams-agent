import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
import { statusBadge } from "../components/badges.js";
import { faqField } from "../components/forms.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderRoles() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/roles");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "角色映射請求"));
    if (allowed.has("ops.roles.request")) {
      const form = el("form", "form-grid");
      form.append(
        faqField("目標 Principal", "target_principal", ""),
        faqField("目標角色（可空）", "target_role", ""),
        faqField("新增 capabilities（逗號分隔）", "add_capabilities", ""),
        faqField("移除 capabilities（逗號分隔）", "remove_capabilities", ""),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "", "送出角色請求");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        const reason = String(values.get("reason") || "").trim();
        if (reason.length < 3) return;
        const split = (raw) => String(raw || "").split(",").map((item) => item.trim()).filter(Boolean);
        await api("/api/governance/roles/requests", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_principal: String(values.get("target_principal") || "").trim(),
            target_role: String(values.get("target_role") || "").trim() || null,
            add_capabilities: split(values.get("add_capabilities")),
            remove_capabilities: split(values.get("remove_capabilities")),
            reason,
          }),
        });
        await renderRoles();
      });
      panel.append(form);
    }
    if (allowed.has("ops.roles.revoke")) {
      const revoke = el("button", "", "緊急撤權");
      revoke.addEventListener("click", async () => {
        const principal = window.prompt("要撤權的 principal");
        if (!principal) return;
        const reason = window.prompt("撤權原因");
        if (!reason || reason.trim().length < 3) return;
        await api("/api/governance/roles/revoke", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ principal: principal.trim(), reason: reason.trim() }),
        });
        await renderRoles();
      });
      panel.append(revoke);
    }
    const items = (data.items || []).slice().reverse();
    if (!items.length) {
      panel.append(el("p", "empty", "目前沒有角色映射請求。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Change</th><th>Principal</th><th>狀態</th><th>請求者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const change of items) {
        const actions = el("td");
        if (allowed.has("ops.roles.approve") && change.status === "REQUESTED") {
          const approve = el("button", "", "核准");
          approve.addEventListener("click", async () => {
            const reason = window.prompt("核准原因");
            if (!reason || reason.trim().length < 3) return;
            await api(`/api/governance/roles/${change.change_id}/approve`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderRoles();
          });
          actions.append(approve);
        }
        const statusCell = el("td");
        statusCell.append(statusBadge(change.status));
        const row = el("tr");
        row.append(
          el("td", "", change.change_id.slice(0, 8)),
          el("td", "", change.target_principal),
          statusCell,
          el("td", "", change.requested_by),
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
      "角色權限",
      "處理角色映射申請與核准。",
      panel,
    );
  } catch (error) {
    presentSystemPage("角色權限", null, el("div", "error", error.message));
  }
}

export const rolesPage = createPageController({
  enter: async () => renderRoles(),
  update: async () => renderRoles(),
  leave: async () => {},
});
