import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { statusBadge, badge } from "../components/badges.js";
import { showContentModal, closeContentModal } from "../components/modal.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderModels() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/models");
    const panel = el("section", "panel");

    const headerRow = el("div", "filter-bar");
    headerRow.style.justifyContent = "space-between";
    headerRow.style.alignItems = "center";
    headerRow.style.marginBottom = "1rem";

    const titleH2 = el("h2", "", "模型與 Provider 治理 (Model Governance)");
    titleH2.style.margin = "0";
    headerRow.append(titleH2);
    panel.append(headerRow);

    const items = data.items || [];
    if (!items.length) {
      panel.append(el("p", "empty", "目前無模型配置。"));
      app.replaceChildren(panel);
      return;
    }

    for (const item of items) {
      const config = item.config || {};
      const active = item.active || {};
      const configId = config.config_id || "default-model-config";
      const versions = item.versions || [];

      const card = el("div", "panel");
      card.style.marginBottom = "1.5rem";
      card.style.border = "1px solid var(--border-subtle, #e2e8f0)";
      card.style.borderRadius = "8px";
      card.style.padding = "1rem";

      // Card Header
      const cardHead = el("div", "filter-bar");
      cardHead.style.justifyContent = "space-between";
      cardHead.style.alignItems = "center";
      cardHead.style.marginBottom = "0.75rem";

      const titleGroup = el("div");
      titleGroup.append(
        el("strong", "", configId),
        el("span", "metric-label", ` ｜ 組件：${config.component || "issue-extractor"}`),
      );

      const headActions = el("div", "filter-bar");
      headActions.style.gap = "0.4rem";

      if (allowed.has("ops.models.write")) {
        const newCandidateBtn = el("button", "", "新增模型候選");
        newCandidateBtn.addEventListener("click", () => showModelCandidateModal(configId, config.component, renderModels));
        headActions.append(newCandidateBtn);
      }

      if (allowed.has("ops.models.read") && configId) {
        const simulate = el("button", "secondary", "模擬 Fallback");
        simulate.addEventListener("click", async () => {
          const error = window.prompt("觸發錯誤 (TIMEOUT / RATE_LIMIT / UNAVAILABLE)：", "TIMEOUT");
          if (!error) return;
          try {
            const result = await api(`/api/governance/models/${configId}/simulate-fallback`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ error: error.trim() }),
            });
            showContentModal("Fallback 模擬結果", el("pre", "json-block", JSON.stringify(result, null, 2)));
          } catch (err) {
            alert(`模擬失敗：${err.message || err}`);
          }
        });
        headActions.append(simulate);
      }

      if (allowed.has("ops.models.activate") && configId) {
        const rollback = el("button", "secondary", "回復上一模型");
        rollback.addEventListener("click", async () => {
          const reason = window.prompt("請輸入回復原因：");
          if (!reason || reason.trim().length < 3) return;
          try {
            await api(`/api/governance/models/${configId}/rollback`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim() }),
            });
            await renderModels();
          } catch (err) {
            alert(`回復失敗：${err.message || err}`);
          }
        });
        headActions.append(rollback);
      }

      cardHead.append(titleGroup, headActions);
      card.append(cardHead);

      // Active Model Details
      const activeDetails = el("div", "metric-bar");
      activeDetails.style.display = "grid";
      activeDetails.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
      activeDetails.style.gap = "0.75rem";
      activeDetails.style.padding = "0.75rem";
      activeDetails.style.backgroundColor = "var(--bg-subtle, #f8fafc)";
      activeDetails.style.borderRadius = "6px";
      activeDetails.style.marginBottom = "1rem";

      activeDetails.append(
        createMetricBox("當前正式模型", `${active.provider || "-"} / ${active.model_id || "-"}`),
        createMetricBox("正式版狀態", active.status || "無正式版", active.status ? "success" : "neutral"),
        createMetricBox("參數配置", `Temp: ${active.temperature ?? "-"} | MaxTokens: ${active.max_output_tokens ?? "-"}`),
        createMetricBox("逾時與重試", `Timeout: ${active.timeout_seconds ?? "-"}s | Retry: ${active.retry ?? "-"}`),
        createMetricBox("密鑰與備援", `Secret: ${active.secret_ref || "-"} | Fallback: ${active.fallback_model_id || "無"}`),
      );
      card.append(activeDetails);

      // Versions History Table
      const verH3 = el("h3", "", `版本清單 (${versions.length})`);
      verH3.style.fontSize = "0.95rem";
      verH3.style.margin = "0.75rem 0 0.5rem 0";
      card.append(verH3);

      if (!versions.length) {
        card.append(el("p", "empty", "尚無版本紀錄。"));
      } else {
        const table = el("table");
        table.innerHTML =
          "<thead><tr><th>版本 ID</th><th>Provider / 模型</th><th>狀態</th><th>參數</th><th>建立者</th><th>操作</th></tr></thead>";
        const body = el("tbody");

        for (const v of versions) {
          const row = el("tr");
          const actions = el("td");
          actions.style.display = "flex";
          actions.style.gap = "0.4rem";

          if (v.status === "CANDIDATE" && allowed.has("ops.models.write")) {
            const evalBtn = el("button", "", "評測 (Eval)");
            evalBtn.addEventListener("click", async () => {
              try {
                evalBtn.disabled = true;
                evalBtn.textContent = "評測中…";
                const res = await api(`/api/governance/models/${configId}/versions/${v.version_id}/eval`, {
                  method: "POST",
                });
                showContentModal("模型安全評測結果", el("pre", "json-block", JSON.stringify(res, null, 2)));
                await renderModels();
              } catch (err) {
                alert(`評測失敗：${err.message || err}`);
                evalBtn.disabled = false;
                evalBtn.textContent = "評測 (Eval)";
              }
            });
            actions.append(evalBtn);
          }

          if (v.status === "EVALUATED" && allowed.has("ops.models.approve")) {
            const approveBtn = el("button", "", "核准 (Approve)");
            approveBtn.addEventListener("click", async () => {
              const reason = window.prompt("請輸入核准原因：", "模型評測指標通過基準");
              if (!reason || reason.trim().length < 3) return;
              try {
                await api(`/api/governance/models/${configId}/versions/${v.version_id}/approve`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ reason: reason.trim() }),
                });
                await renderModels();
              } catch (err) {
                alert(`核准失敗：${err.message || err}`);
              }
            });
            actions.append(approveBtn);
          }

          if (v.status === "APPROVED" && allowed.has("ops.models.activate")) {
            const activateBtn = el("button", "", "啟用 (Activate)");
            activateBtn.addEventListener("click", async () => {
              const reason = window.prompt("請輸入啟用原因：", "核准後正式切換線上模型");
              if (!reason || reason.trim().length < 3) return;
              try {
                await api(`/api/governance/models/${configId}/versions/${v.version_id}/activate`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ reason: reason.trim() }),
                });
                await renderModels();
              } catch (err) {
                alert(`啟用失敗：${err.message || err}`);
              }
            });
            actions.append(activateBtn);
          }

          row.append(
            el("td", "metric-label", v.version_id.slice(0, 8)),
            el("td", "strong", `${v.provider} / ${v.model_id}`),
            el("td", "", statusBadge(v.status)),
            el("td", "metric-label", `T:${v.temperature} Max:${v.max_output_tokens} To:${v.timeout_seconds}s`),
            el("td", "", v.created_by || "-"),
            actions,
          );
          body.append(row);
        }
        table.append(body);
        const scroll = el("div", "table-responsive");
        scroll.append(table);
        card.append(scroll);
      }
      panel.append(card);
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

function createMetricBox(label, value, badgeVariant = null) {
  const box = el("div");
  box.append(el("div", "metric-label", label));
  if (badgeVariant) {
    box.append(statusBadge(value));
  } else {
    const valDiv = el("div", "strong", value);
    valDiv.style.fontSize = "0.9rem";
    box.append(valDiv);
  }
  return box;
}

function showModelCandidateModal(configId, component, onRefresh) {
  const form = el("form", "form-grid");
  form.style.display = "flex";
  form.style.flexDirection = "column";
  form.style.gap = "0.6rem";

  form.append(el("label", "metric-label", `Config ID: ${configId}`));

  const providerGroup = el("div");
  providerGroup.append(el("label", "metric-label", "Provider："));
  const providerSelect = el("select");
  ["google", "azure", "openai", "anthropic"].forEach((p) => {
    const opt = el("option", "", p);
    opt.value = p;
    providerSelect.append(opt);
  });
  providerGroup.append(providerSelect);
  form.append(providerGroup);

  const modelIdGroup = el("div");
  modelIdGroup.append(el("label", "metric-label", "Model ID："));
  const modelIdInput = el("input");
  modelIdInput.required = true;
  modelIdInput.value = "gemini-2.5-flash";
  modelIdGroup.append(modelIdInput);
  form.append(modelIdGroup);

  const tempGroup = el("div");
  tempGroup.append(el("label", "metric-label", "Temperature (0.0 ~ 1.0)："));
  const tempInput = el("input");
  tempInput.type = "number";
  tempInput.step = "0.1";
  tempInput.min = "0";
  tempInput.max = "1";
  tempInput.value = "0.0";
  tempGroup.append(tempInput);
  form.append(tempGroup);

  const maxTokensGroup = el("div");
  maxTokensGroup.append(el("label", "metric-label", "Max Output Tokens："));
  const maxTokensInput = el("input");
  maxTokensInput.type = "number";
  maxTokensInput.value = "2048";
  maxTokensGroup.append(maxTokensInput);
  form.append(maxTokensGroup);

  const timeoutGroup = el("div");
  timeoutGroup.append(el("label", "metric-label", "Timeout Seconds (1 ~ 120)："));
  const timeoutInput = el("input");
  timeoutInput.type = "number";
  timeoutInput.value = "30";
  timeoutGroup.append(timeoutInput);
  form.append(timeoutGroup);

  const retryGroup = el("div");
  retryGroup.append(el("label", "metric-label", "Retry (0 ~ 3)："));
  const retryInput = el("input");
  retryInput.type = "number";
  retryInput.value = "1";
  retryGroup.append(retryInput);
  form.append(retryGroup);

  const secretGroup = el("div");
  secretGroup.append(el("label", "metric-label", "Secret Ref："));
  const secretInput = el("input");
  secretInput.required = true;
  secretInput.value = "gemini-api-key";
  secretGroup.append(secretInput);
  form.append(secretGroup);

  const fallbackGroup = el("div");
  fallbackGroup.append(el("label", "metric-label", "Fallback Model ID (可選)："));
  const fallbackInput = el("input");
  fallbackInput.placeholder = "例：gemini-2.5-flash";
  fallbackGroup.append(fallbackInput);
  form.append(fallbackGroup);

  const reasonGroup = el("div");
  reasonGroup.append(el("label", "metric-label", "變更原因 (至少 3 字)："));
  const reasonInput = el("input");
  reasonInput.required = true;
  reasonInput.placeholder = "請輸入變更原因";
  reasonGroup.append(reasonInput);
  form.append(reasonGroup);

  const submitBtn = el("button", "", "建立模型候選 (Submit Candidate)");
  submitBtn.type = "submit";
  form.append(submitBtn);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const reason = reasonInput.value.trim();
    if (reason.length < 3) {
      alert("變更原因至少需 3 個字元");
      return;
    }
    const fallbackId = fallbackInput.value.trim() || null;
    const fallbackOn = fallbackId ? ["TIMEOUT", "RATE_LIMIT", "UNAVAILABLE"] : [];
    try {
      await api("/api/governance/models/candidates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          config_id: configId,
          provider: providerSelect.value,
          model_id: modelIdInput.value.trim(),
          component: component || "issue-extractor",
          temperature: parseFloat(tempInput.value) || 0.0,
          max_output_tokens: parseInt(maxTokensInput.value, 10) || 2048,
          timeout_seconds: parseInt(timeoutInput.value, 10) || 30,
          retry: parseInt(retryInput.value, 10) || 1,
          secret_ref: secretInput.value.trim(),
          region: "asia-east1",
          pricing_version: "v1",
          fallback_model_id: fallbackId,
          fallback_on: fallbackOn,
          change_reason: reason,
        }),
      });
      closeContentModal();
      await onRefresh();
    } catch (err) {
      alert(`建立失敗：${err.message || err}`);
    }
  });

  showContentModal(`新增模型候選：${configId}`, form);
}

export const modelsPage = createPageController({
  enter: async () => renderModels(),
  update: async () => renderModels(),
  leave: async () => {},
});
