import { api, el } from "../api.js";
import { actorCapabilities, getCapabilities } from "../app/capabilities.js";
import { showContentModal } from "../components/modal.js";
import { exampleSelect, faqField } from "../components/forms.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderBudgets() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const [policyData, alertData] = await Promise.all([
      api("/api/budget-policies"),
      api("/api/alerts"),
    ]);
    const policyPanel = el("section", "panel");
    const policyHeader = el("div", "section-header-row");
    policyHeader.style.display = "flex";
    policyHeader.style.justifyContent = "space-between";
    policyHeader.style.alignItems = "center";
    policyHeader.append(el("h2", "", "Budget Policies"));
    if (allowed.has("ops.budget.evaluate")) {
      const evalAllBtn = el("button", "btn", "全部自動評估（含個人50元門檻）");
      evalAllBtn.addEventListener("click", async () => {
        try {
          evalAllBtn.disabled = true;
          evalAllBtn.textContent = "評估中…";
          const res = await api("/api/budget-policies/evaluate-all", { method: "POST" });
          showContentModal(
            "自動評估結果",
            el("p", "", `已評估 ${res.evaluatedPolicies} 項政策、${res.evaluatedUsers} 位使用者每日額度；產生 ${res.triggeredAlerts} 項告警，已發送 ${res.dispatchedDeliveries} 筆通知。`),
          );
          await renderBudgets();
        } catch (err) {
          showContentModal("評估失敗", el("div", "error", err.message));
        } finally {
          evalAllBtn.disabled = false;
          evalAllBtn.textContent = "全部自動評估（含個人50元門檻）";
        }
      });
      policyHeader.append(evalAllBtn);
    }
    policyPanel.append(policyHeader);
    if (allowed.has("ops.budget.write")) {
      const form = el("form", "form-grid");
      const ownerOptions = (getCapabilities().ownerUnitIds || []).map((item) => [item, item]);
      const targetOptions = (policyData.notificationTargets || []).map((item) => [item, item]);
      form.append(
        exampleSelect("Scope", "scope_type", [
          ["PERSONAL", "Personal"], ["SERVICE", "Service"], ["TEAM", "Team"],
          ["TENANT", "Tenant"], ["GLOBAL", "Global"],
        ]),
        faqField("Scope ID", "scope_id", ""),
        exampleSelect("Period", "period", [["DAILY", "Daily"], ["MONTHLY", "Monthly"]]),
        exampleSelect("Measure", "measure", [
          ["TWD", "TWD"], ["USD", "USD"], ["TOKEN", "Token"],
          ["LLM_CALL_COUNT", "LLM Call Count"],
        ]),
        faqField("Warning Threshold", "warning_threshold", ""),
        faqField("Critical Threshold", "critical_threshold", ""),
        exampleSelect("Owner Unit", "owner_unit_id", ownerOptions),
        exampleSelect("Notification Target", "notification_target_id", targetOptions),
      );
      const submit = el("button", "", "建立 Policy");
      submit.type = "submit";
      form.append(submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        try {
          await api("/api/budget-policies", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              scope_type: values.get("scope_type"), scope_id: values.get("scope_id"),
              period: values.get("period"), measure: values.get("measure"),
              warning_threshold: Number(values.get("warning_threshold")),
              critical_threshold: Number(values.get("critical_threshold")),
              owner_unit_id: values.get("owner_unit_id"),
              notification_target_ids: [values.get("notification_target_id")],
            }),
          });
          await renderBudgets();
        } catch (error) {
          showContentModal("建立 Policy 失敗", el("div", "error", error.message));
        }
      });
      policyPanel.append(form);
    }
    if ((policyData.items || []).length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Scope</th><th>期間 / 指標</th><th>門檻</th><th>狀態</th><th>版本</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const policy of policyData.items) {
        const actions = el("td");
        if (allowed.has("ops.budget.evaluate") && policy.enabled) {
          const evaluate = el("button", "", "立即評估");
          evaluate.addEventListener("click", async () => {
            try {
              const result = await api(`/api/budget-policies/${policy.policy_id}/evaluate`, { method: "POST" });
              const usage = result.usage;
              showContentModal(
                "Policy 評估結果",
                el("p", "", `Actual ${usage.actualValue}｜Coverage ${(usage.coverage * 100).toFixed(1)}%｜${usage.periodKey}`),
              );
              await renderBudgets();
            } catch (error) {
              showContentModal("評估失敗", el("div", "error", error.message));
            }
          });
          actions.append(evaluate);
        }
        if (allowed.has("ops.budget.write")) {
          const state = el("button", "", policy.enabled ? "停用" : "啟用");
          state.addEventListener("click", async () => {
            const reason = window.prompt(`${policy.enabled ? "停用" : "啟用"}原因`);
            if (!reason?.trim()) return;
            await api(`/api/budget-policies/${policy.policy_id}/state`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_etag: policy.etag, enabled: !policy.enabled, reason }),
            });
            await renderBudgets();
          });
          actions.append(state);
        }
        const row = el("tr");
        row.append(
          el("td", "", `${policy.scope_type}:${policy.scope_id}`),
          el("td", "", `${policy.period} / ${policy.measure}`),
          el("td", "", `${policy.warning_threshold} / ${policy.critical_threshold}`),
          el("td", "", policy.enabled ? "ENABLED" : "DISABLED"),
          el("td", "", `${policy.pricing_version} / ${policy.exchange_rate_version}`),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const policyScroll = el("div", "table-responsive");
      policyScroll.append(table);
      policyPanel.append(policyScroll);
    } else {
      policyPanel.append(el("p", "empty", "目前沒有 Budget Policy。"));
    }

    const alertPanel = el("section", "panel");
    alertPanel.append(el("h2", "", `Alerts（${alertData.total || 0}）`));
    if ((alertData.items || []).length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Type</th><th>Severity</th><th>Scope</th><th>Actual / Threshold / 說明</th><th>Coverage</th><th>狀態</th><th>通知</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const alert of alertData.items) {
        const actions = el("td");
        if (allowed.has("ops.alerts.manage") && alert.status !== "RESOLVED") {
          const alertActions = alert.status === "OPEN"
            ? [["acknowledge", "Acknowledge"], ["resolve", "Resolve"]]
            : [["resolve", "Resolve"]];
          for (const [action, label] of alertActions) {
            const button = el("button", "", label);
            button.addEventListener("click", async () => {
              const reason = window.prompt(`${label} 原因`);
              if (!reason?.trim()) return;
              await api(`/api/alerts/${alert.alert_id}/${action}`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ expected_etag: alert.etag, reason }),
              });
              await renderBudgets();
            });
            actions.append(button);
          }
          for (const deliveryItem of (alert.deliveries || []).filter((item) => item.status === "FAILED")) {
            const retry = el("button", "", "重試通知");
            retry.addEventListener("click", async () => {
              await api(`/api/alerts/${alert.alert_id}/deliveries/${deliveryItem.delivery_id}/retry`, {
                method: "POST",
              });
              await renderBudgets();
            });
            actions.append(retry);
          }
        }
        const delivery = (alert.deliveries || [])
          .map((item) => `${item.target_id}:${item.status}`).join(", ") || "-";
        const typeBadge = alert.alert_type || "BUDGET_THRESHOLD";
        const detailText = alert.alert_type === "BUDGET_THRESHOLD"
          ? `${alert.actual_value} / ${alert.threshold}`
          : (alert.message || `${alert.actual_value} / ${alert.threshold}`);
        const row = el("tr");
        row.append(
          el("td", "", typeBadge),
          el("td", "", alert.severity),
          el("td", "", `${alert.scope_type}:${alert.scope_id}`),
          el("td", "", detailText),
          el("td", "", `${(alert.coverage * 100).toFixed(1)}%`),
          el("td", "", alert.status),
          el("td", "", delivery),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const alertScroll = el("div", "table-responsive");
      alertScroll.append(table);
      alertPanel.append(alertScroll);
    } else {
      alertPanel.append(el("p", "empty", "目前沒有 Alert。"));
    }
    app.replaceChildren(policyPanel, alertPanel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

export const budgetsPage = createPageController({
  enter: async () => renderBudgets(),
  update: async () => renderBudgets(),
  leave: async () => {},
});
