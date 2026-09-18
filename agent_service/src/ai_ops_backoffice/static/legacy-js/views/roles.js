import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
import { statusBadge } from "../components/badges.js";
import { faqField } from "../components/forms.js";
import { showTextPrompt, showToast } from "../components/modal.js";
import { createPageController } from "../app/lifecycle.js";
import { loadingState } from "../components/state.js";
import { formatUserFacingError } from "../app/labels.js";

export async function renderRoles() {
  const app = document.getElementById("app");
  app.replaceChildren(loadingState("正在載入角色權限…", 3));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/roles");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "角色映射請求"));
    if (allowed.has("ops.roles.request")) {
      const form = el("form", "form-grid bu-role-form");
      form.append(
        el(
          "p",
          "metric-label",
          "提出角色或能力變更申請；涉及高風險權限時，請在理由中說明範圍、期限與核准依據。",
        ),
      );
      form.append(
        faqField("目標身分識別碼（Principal）", "target_principal", ""),
        faqField("目標角色（可空）", "target_role", "", false, false),
        faqField("新增能力（capabilities，逗號分隔）", "add_capabilities", ""),
        faqField("移除能力（capabilities，逗號分隔）", "remove_capabilities", ""),
        faqField("理由", "reason", ""),
      );
      const submit = el("button", "button-primary", "送出角色請求");
      submit.type = "submit";
      submit.setAttribute("aria-label", "送出角色請求");
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        const reason = String(values.get("reason") || "").trim();
        if (reason.length < 3) {
          showToast("請輸入至少 3 個字的變更理由。", { tone: "error" });
          return;
        }
        const split = (raw) => String(raw || "").split(",").map((item) => item.trim()).filter(Boolean);
        try {
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
        } catch (error) {
          showToast(formatUserFacingError(error), { tone: "error" });
        }
      });
      panel.append(form);
    }
    if (allowed.has("ops.roles.revoke")) {
      const dangerZone = el("section", "bu-danger-zone");
      dangerZone.append(
        el("h3", "", "緊急撤權"),
        el(
          "p",
          "metric-label",
          "僅在帳號或能力需要立即停用時使用。此操作會直接送出撤權請求，仍需填寫原因以留下稽核紀錄。",
        ),
      );
      const revoke = el("button", "", "啟動緊急撤權");
      revoke.setAttribute("aria-label", "啟動緊急撤權");
      revoke.addEventListener("click", async () => {
        const principal = await showTextPrompt({
          title: "緊急撤權",
          message: "請輸入要撤權的 principal。",
          required: true,
        });
        if (!principal) return;
        const reason = await showTextPrompt({
          title: "緊急撤權原因",
          message: "請輸入撤權原因（至少 3 個字）。",
          minLength: 3,
          required: true,
        });
        if (reason == null) return;
        try {
          await api("/api/governance/roles/revoke", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ principal: principal.trim(), reason: reason.trim() }),
          });
          await renderRoles();
        } catch (error) {
          showToast(formatUserFacingError(error), { tone: "error" });
        }
      });
      dangerZone.append(revoke);
      panel.append(dangerZone);
    }
    const items = (data.items || []).slice().reverse();
    if (!items.length) {
      panel.append(el("p", "empty", "目前沒有角色映射請求。"));
    } else {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>變更</th><th>目標身分</th><th>狀態</th><th>請求者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const change of items) {
        const actions = el("td");
        if (allowed.has("ops.roles.approve") && change.status === "REQUESTED") {
          const approve = el("button", "", "核准");
          approve.setAttribute("aria-label", `核准角色變更 ${change.change_id.slice(0, 8)}`);
          approve.addEventListener("click", async () => {
            const reason = await showTextPrompt({
              title: "核准角色變更",
              message: "請輸入核准原因（至少 3 個字）。",
              minLength: 3,
              required: true,
            });
            if (reason == null) return;
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
    presentSystemPage("角色權限", null, el("div", "error", formatUserFacingError(error)));
  }
}

export const rolesPage = createPageController({
  enter: async () => renderRoles(),
  update: async () => renderRoles(),
  leave: async () => {},
});
