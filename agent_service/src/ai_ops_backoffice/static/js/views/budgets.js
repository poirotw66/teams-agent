import { api, el } from "../api.js";
import { actorCapabilities, getCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
import { showContentModal, closeContentModal } from "../components/modal.js";
import { exampleSelect, faqField } from "../components/forms.js";
import { createPageController } from "../app/lifecycle.js";

function showActionReasonModal(title, promptText, onConfirm) {
  const container = el("div", "form-grid");
  const group = el("div", "form-group");
  const label = el("label", "form-label", promptText);
  const input = el("input");
  input.placeholder = "請輸入原因…";
  input.style.width = "100%";
  group.append(label, input);

  const actions = el("div", "filter-bar");
  actions.style.marginTop = "1rem";
  actions.style.justifyContent = "flex-end";
  const cancelBtn = el("button", "", "取消");
  cancelBtn.addEventListener("click", () => closeContentModal());

  const confirmBtn = el("button", "button-primary", "確認");
  confirmBtn.addEventListener("click", async () => {
    const val = input.value.trim();
    if (!val) {
      alert("請輸入原因");
      return;
    }
    confirmBtn.disabled = true;
    confirmBtn.textContent = "處理中…";
    try {
      await onConfirm(val);
      closeContentModal();
    } catch (err) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "確認";
      showContentModal("操作失敗", el("div", "error", err.message));
    }
  });

  actions.append(cancelBtn, confirmBtn);
  container.append(group, actions);
  showContentModal(title, container);
}

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
      let availableModels = [
        "gpt-4o",
        "gpt-4o-mini",
        "claude-3-5-sonnet",
        "claude-3-haiku",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
      ];
      try {
        const ratesData = await api("/api/costs/rates");
        if (ratesData && ratesData.rates) {
          const fetched = Object.keys(ratesData.rates);
          if (fetched.length) availableModels = [...new Set([...fetched, ...availableModels])];
        }
      } catch {
        // fallback
      }

      const form = el("form", "form-grid");
      const ownerOptions = (getCapabilities().ownerUnitIds || []).map((item) => [item, item]);
      const targetOptions = (policyData.notificationTargets || []).map((item) => [item, item]);

      const scopeSelectWrap = exampleSelect("Scope", "scope_type", [
        ["PERSONAL", "Personal"], ["SERVICE", "Service"], ["TEAM", "Team"],
        ["TENANT", "Tenant"], ["GLOBAL", "Global"], ["MODEL", "Model"],
      ]);
      const scopeSelect = scopeSelectWrap.querySelector("select");

      const modelSelectWrap = exampleSelect("選擇模型 (Model)", "model_picker", [
        ["", "-- 請選擇模型 --"],
        ...availableModels.map((m) => [m, m]),
      ]);
      modelSelectWrap.style.display = "none";
      const modelSelect = modelSelectWrap.querySelector("select");

      const scopeIdField = faqField("Scope ID", "scope_id", "");
      const scopeIdInput = scopeIdField.querySelector("input");

      scopeSelect.addEventListener("change", () => {
        const isModel = scopeSelect.value === "MODEL";
        modelSelectWrap.style.display = isModel ? "" : "none";
        if (isModel && modelSelect.value) {
          scopeIdInput.value = modelSelect.value;
        }
      });

      modelSelect.addEventListener("change", () => {
        if (modelSelect.value) {
          scopeIdInput.value = modelSelect.value;
        }
      });

      form.append(
        scopeSelectWrap,
        modelSelectWrap,
        scopeIdField,
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
          state.addEventListener("click", () => {
            showActionReasonModal(
              `${policy.enabled ? "停用" : "啟用"} Budget Policy`,
              `請輸入${policy.enabled ? "停用" : "啟用"}原因：`,
              async (reason) => {
                await api(`/api/budget-policies/${policy.policy_id}/state`, {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ expected_etag: policy.etag, enabled: !policy.enabled, reason }),
                });
                await renderBudgets();
              },
            );
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
            button.addEventListener("click", () => {
              showActionReasonModal(
                `${label} Alert`,
                `請輸入 ${label} 原因：`,
                async (reason) => {
                  await api(`/api/alerts/${alert.alert_id}/${action}`, {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ expected_etag: alert.etag, reason }),
                  });
                  await renderBudgets();
                },
              );
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
    presentSystemPage(
      "預算與警示",
      "管理用量預算政策與告警。",
      policyPanel,
      alertPanel,
    );
  } catch (error) {
    presentSystemPage("預算與警示", null, el("div", "error", error.message));
  }
}

export const budgetsPage = createPageController({
  enter: async () => renderBudgets(),
  update: async () => renderBudgets(),
  leave: async () => {},
});
