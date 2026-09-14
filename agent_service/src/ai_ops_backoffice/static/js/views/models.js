import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
import { statusBadge, badge } from "../components/badges.js";
import {
  showContentModal,
  closeContentModal,
  showTextPrompt,
  showToast,
} from "../components/modal.js";
import { createPageController } from "../app/lifecycle.js";

const EFFECT_LABELS = {
  next_request: "下一則請求生效",
  reindex: "排入重建後生效",
  service_refresh: "排入套用後生效",
};

const SOURCE_LABELS = {
  governance: "治理生效版",
  settings_baseline: "環境變數退路",
};

const SCHEDULE_LABELS = {
  queued: "已排入，尚未切換",
  running: "執行中，尚未切換",
  failed: "失敗，仍使用目前生效模型",
  applied: "已套用",
};

function effectLabel(effect) {
  return EFFECT_LABELS[effect] || effect || "未定義";
}

function sourceLabel(source) {
  return SOURCE_LABELS[source] || source || "未知來源";
}

export async function renderModels() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/models");
    const runtime = data.runtime || { available: false, items: [] };
    const ready = Boolean(runtime.controlPlaneReady);
    const panel = el("section", "panel");
    panel.append(renderIntro(runtime, ready));
    const ledger = indexLedger(data.items || []);
    const components = indexComponents(data.components || []);
    const rows = runtime.items?.length ? runtime.items : fallbackRows(data.components || []);
    if (!rows.length) {
      panel.append(el("p", "empty", "目前沒有模型元件。"));
    }
    for (const row of rows) {
      panel.append(renderComponentCard(row, ledger.get(row.configId), components.get(row.configId), allowed, ready));
    }
    presentSystemPage(
      "模型治理",
      "每個元件只顯示現在生效的模型。聊天模型啟用後下一則請求生效；Embedding 與 File Search 要等重建或套用完成。",
      panel,
    );
  } catch (error) {
    presentSystemPage("模型治理", null, el("div", "error", error.message));
  }
}

function renderIntro(runtime, ready) {
  const section = el("section", "panel");
  section.style.marginBottom = "1.25rem";
  if (!runtime.available) {
    section.append(el("p", "warning", runtime.reason || "目前無法讀取 Agent 執行中的模型。切換按鈕已停用。"));
    return section;
  }
  if (!ready) {
    section.append(el("p", "warning", "治理未接上執行中 Agent。可以登記候選，但不能啟用或排入切換。"));
  }
  if (runtime.knowledgeMode) {
    section.append(el("p", "metric-label", `知識模式：${runtime.knowledgeMode}`));
  }
  return section;
}

function renderComponentCard(row, ledgerItem, component, allowed, ready) {
  const config = ledgerItem?.config || {};
  const versions = ledgerItem?.versions || [];
  const configId = row.configId || config.config_id;
  const card = el("div", "panel");
  card.style.marginBottom = "1.5rem";
  card.style.border = "1px solid var(--border-subtle, #e2e8f0)";
  card.style.borderRadius = "8px";
  card.style.padding = "1rem";

  const head = el("div", "filter-bar");
  head.style.justifyContent = "space-between";
  head.style.alignItems = "center";
  head.style.marginBottom = "0.75rem";
  const title = el("div");
  title.append(
    el("strong", "", row.label || configId),
    el("span", "metric-label", ` ｜ ${effectLabel(row.effect)}`),
  );
  const actions = el("div", "filter-bar");
  actions.style.gap = "0.4rem";
  appendHeaderActions(actions, { row, config, configId, component, allowed, ready });
  head.append(title, actions);
  card.append(head);
  card.append(renderEffective(row));
  card.append(renderVersionTable(versions, configId, row.effect, allowed, ready));
  return card;
}

function renderEffective(row) {
  const box = el("div", "metric-bar");
  box.style.display = "grid";
  box.style.gridTemplateColumns = "repeat(auto-fit, minmax(180px, 1fr))";
  box.style.gap = "0.75rem";
  box.style.padding = "0.75rem";
  box.style.backgroundColor = "var(--bg-subtle, #f8fafc)";
  box.style.borderRadius = "6px";
  box.style.marginBottom = "1rem";
  box.append(
    createMetricBox("現在生效", row.model || "未設定"),
    createMetricBox("來源", sourceLabel(row.source), row.source === "governance" ? "success" : "neutral"),
    createMetricBox("版本", row.versionId ? String(row.versionId).slice(0, 8) : "無"),
  );
  if (row.fallbackModel) {
    box.append(createMetricBox("環境變數退路", row.fallbackModel));
  }
  if (row.scheduleStatus && row.scheduleStatus !== "applied") {
    const label = SCHEDULE_LABELS[row.scheduleStatus] || row.scheduleStatus;
    const extra = row.scheduledModel ? `${label}：${row.scheduledModel}` : label;
    box.append(createMetricBox("排程", extra, row.scheduleStatus === "failed" ? "warning" : "neutral"));
  }
  return box;
}

function appendHeaderActions(actions, context) {
  const { row, config, configId, component, allowed, ready } = context;
  if (allowed.has("ops.models.write") && configId) {
    const add = el("button", "", "新增模型候選");
    add.addEventListener("click", () => showModelCandidateModal(configId, row.component || config.component, component, renderModels));
    actions.append(add);
  }
  if (row.effect === "next_request" && allowed.has("ops.models.read") && configId) {
    actions.append(simulateButton(configId));
  }
  if (!ready || !allowed.has("ops.models.activate") || !configId) return;
  if (row.effect === "next_request") {
    actions.append(rollbackButton(configId));
    return;
  }
  const verb = row.effect === "reindex" ? "排入重建並回復" : "排入套用並回復";
  actions.append(rollbackButton(configId, verb));
}

function renderVersionTable(versions, configId, effect, allowed, ready) {
  const wrap = el("div");
  const heading = el("h3", "", `版本清單 (${versions.length})`);
  heading.style.fontSize = "0.95rem";
  heading.style.margin = "0.75rem 0 0.5rem 0";
  wrap.append(heading);
  if (!versions.length) {
    wrap.append(el("p", "empty", "尚無版本紀錄。"));
    return wrap;
  }
  const table = el("table");
  table.innerHTML = "<thead><tr><th>版本 ID</th><th>Provider / 模型</th><th>狀態</th><th>參數</th><th>建立者</th><th>操作</th></tr></thead>";
  const body = el("tbody");
  for (const version of versions) {
    const row = el("tr");
    const actions = el("td");
    actions.style.display = "flex";
    actions.style.gap = "0.4rem";
    appendVersionActions(actions, version, configId, effect, allowed, ready);
    row.append(
      el("td", "metric-label", String(version.version_id || "").slice(0, 8)),
      el("td", "strong", `${version.provider} / ${version.model_id}`),
      el("td", "", statusBadge(version.status)),
      el("td", "metric-label", `T:${version.temperature} Max:${version.max_output_tokens}`),
      el("td", "", version.created_by || "-"),
      actions,
    );
    body.append(row);
  }
  table.append(body);
  const scroll = el("div", "table-responsive");
  scroll.append(table);
  wrap.append(scroll);
  return wrap;
}

function appendVersionActions(actions, version, configId, effect, allowed, ready) {
  if (version.status === "CANDIDATE" && allowed.has("ops.models.write")) {
    actions.append(staticCheckButton(configId, version.version_id));
  }
  if (version.status === "EVALUATED" && allowed.has("ops.models.approve")) {
    actions.append(approveButton(configId, version.version_id));
  }
  if (version.status !== "APPROVED" || !allowed.has("ops.models.activate") || !ready) return;
  if (effect === "next_request") {
    actions.append(activateButton(configId, version.version_id));
    return;
  }
  const label = effect === "reindex" ? "排入重建" : "排入套用";
  actions.append(scheduleButton(configId, version.version_id, label));
}

function staticCheckButton(configId, versionId) {
  const button = el("button", "", "靜態檢查");
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "檢查中…";
    try {
      const result = await api(`/api/governance/models/${configId}/versions/${versionId}/eval`, { method: "POST" });
      showContentModal("模型靜態檢查結果", el("pre", "json-block", JSON.stringify(result, null, 2)));
      await renderModels();
    } catch (error) {
      showToast(`靜態檢查失敗：${error.message || error}`, { tone: "error" });
      button.disabled = false;
      button.textContent = "靜態檢查";
    }
  });
  return button;
}

function approveButton(configId, versionId) {
  const button = el("button", "", "核准");
  button.addEventListener("click", async () => {
    const reason = await promptReason("核准模型版本", "請輸入核准原因（至少 3 個字元）。", "靜態檢查通過");
    if (reason == null) return;
    try {
      await api(`/api/governance/models/${configId}/versions/${versionId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      await renderModels();
    } catch (error) {
      showToast(`核准失敗：${error.message || error}`, { tone: "error" });
    }
  });
  return button;
}

function activateButton(configId, versionId) {
  const button = el("button", "", "啟用");
  button.addEventListener("click", async () => {
    const reason = await promptReason("啟用模型版本", "啟用後下一則請求改用這個版本。請輸入原因（至少 3 個字元）。", "核准後切換下一則請求");
    if (reason == null) return;
    try {
      await api(`/api/governance/models/${configId}/versions/${versionId}/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      await renderModels();
    } catch (error) {
      showToast(`啟用失敗：${error.message || error}`, { tone: "error" });
    }
  });
  return button;
}

function scheduleButton(configId, versionId, label) {
  const button = el("button", "", label);
  button.addEventListener("click", async () => {
    const reason = await promptReason(label, "完成前仍使用目前生效模型。請輸入原因（至少 3 個字元）。", label);
    if (reason == null) return;
    button.disabled = true;
    try {
      await api(`/api/governance/models/${configId}/versions/${versionId}/schedule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      await renderModels();
    } catch (error) {
      showToast(`${label}失敗：${error.message || error}`, { tone: "error" });
      button.disabled = false;
    }
  });
  return button;
}

function rollbackButton(configId, label = "回復上一模型") {
  const button = el("button", "secondary", label);
  button.addEventListener("click", async () => {
    const reason = await promptReason(label, "請輸入回復原因（至少 3 個字元）。");
    if (reason == null) return;
    try {
      await api(`/api/governance/models/${configId}/rollback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      await renderModels();
    } catch (error) {
      showToast(`回復失敗：${error.message || error}`, { tone: "error" });
    }
  });
  return button;
}

function simulateButton(configId) {
  const button = el("button", "secondary", "模擬 Fallback");
  button.addEventListener("click", async () => {
    const error = await showTextPrompt({
      title: "模擬 Fallback",
      message: "這只是模擬，不會呼叫模型。請輸入錯誤代碼（TIMEOUT／RATE_LIMIT／UNAVAILABLE）。",
      defaultValue: "TIMEOUT",
      required: true,
    });
    if (error == null || !error.trim()) return;
    try {
      const result = await api(`/api/governance/models/${configId}/simulate-fallback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ error: error.trim() }),
      });
      showContentModal("Fallback 模擬結果", el("pre", "json-block", JSON.stringify(result, null, 2)));
    } catch (err) {
      showToast(`模擬失敗：${err.message || err}`, { tone: "error" });
    }
  });
  return button;
}

function showModelCandidateModal(configId, component, spec, onRefresh) {
  const providers = spec?.providers || { google_genai: [] };
  const form = el("form", "form-grid");
  form.style.display = "flex";
  form.style.flexDirection = "column";
  form.style.gap = "0.6rem";
  form.append(el("label", "metric-label", `Config ID: ${configId}`));

  const providerSelect = labeledSelect(form, "Provider", Object.keys(providers));
  const modelSelect = labeledSelect(form, "Model ID", providers[providerSelect.value] || []);
  providerSelect.addEventListener("change", () => {
    replaceOptions(modelSelect, providers[providerSelect.value] || []);
  });
  const temperature = labeledInput(form, "Temperature (0.0 ~ 1.0)", "0.0", "number");
  const maxTokens = labeledInput(form, "Max Output Tokens", "2048", "number");
  const timeout = labeledInput(form, "Timeout Seconds (1 ~ 120)", "30", "number");
  const retry = labeledInput(form, "Retry (0 ~ 3)", "1", "number");
  const secret = labeledInput(form, "Secret Ref", "secret://gemini-api-key");
  const fallback = labeledInput(form, "Fallback Model ID（可選）", "");
  const reason = labeledInput(form, "變更原因 (至少 3 字)", "");
  reason.required = true;
  const submit = el("button", "", "建立模型候選");
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const changeReason = reason.value.trim();
    if (changeReason.length < 3) {
      showToast("變更原因至少需 3 個字元", { tone: "error" });
      return;
    }
    const fallbackId = fallback.value.trim() || null;
    try {
      await api("/api/governance/models/candidates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          config_id: configId,
          provider: providerSelect.value,
          model_id: modelSelect.value,
          component: component || "issue-extractor",
          temperature: Number(temperature.value) || 0,
          max_output_tokens: Number(maxTokens.value) || 2048,
          timeout_seconds: Number(timeout.value) || 30,
          retry: Number(retry.value) || 1,
          secret_ref: secret.value.trim(),
          region: "asia-east1",
          pricing_version: "v1",
          fallback_model_id: fallbackId,
          fallback_on: fallbackId ? ["TIMEOUT", "RATE_LIMIT", "UNAVAILABLE"] : [],
          change_reason: changeReason,
        }),
      });
      closeContentModal();
      await onRefresh();
    } catch (error) {
      showToast(`建立失敗：${error.message || error}`, { tone: "error" });
    }
  });
  showContentModal(`新增模型候選：${configId}`, form);
}

function labeledSelect(form, label, values) {
  const group = el("div");
  group.append(el("label", "metric-label", `${label}：`));
  const select = el("select");
  replaceOptions(select, values);
  select.required = true;
  group.append(select);
  form.append(group);
  return select;
}

function replaceOptions(select, values) {
  select.replaceChildren();
  for (const value of values) {
    const option = el("option", "", value);
    option.value = value;
    select.append(option);
  }
}

function labeledInput(form, label, value, type = "text") {
  const group = el("div");
  group.append(el("label", "metric-label", `${label}：`));
  const input = el("input");
  input.type = type;
  input.value = value;
  group.append(input);
  form.append(group);
  return input;
}

function createMetricBox(label, value, badgeVariant = null) {
  const box = el("div");
  box.append(el("div", "metric-label", label));
  if (badgeVariant) {
    box.append(badge(value, badgeVariant));
  } else {
    const val = el("div", "strong", value);
    val.style.fontSize = "0.9rem";
    box.append(val);
  }
  return box;
}

function indexLedger(items) {
  return new Map(items.map((item) => [item.config?.config_id, item]));
}

function indexComponents(components) {
  return new Map(components.map((item) => [item.configId, item]));
}

function fallbackRows(components) {
  return components.map((item) => ({
    configId: item.configId,
    label: item.label,
    effect: item.effect,
    component: item.component,
    model: null,
    source: null,
  }));
}

async function promptReason(title, message, defaultValue) {
  const reason = await showTextPrompt({
    title,
    message,
    defaultValue,
    minLength: 3,
    required: true,
  });
  return reason == null ? null : reason.trim();
}

export const modelsPage = createPageController({
  enter: async () => renderModels(),
  update: async () => renderModels(),
  leave: async () => {},
});
