import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { showContentModal } from "../components/modal.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderModels() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const data = await api("/api/governance/models");
    const panel = el("section", "panel");
    panel.append(el("h2", "", "模型／Provider Allowlist"));
    for (const item of data.items || []) {
      const active = item.active || {};
      const configId = item.config?.config_id;
      panel.append(
        el("p", "", `${configId}｜${active.provider || "-"} / ${active.model_id || "-"}｜${active.status || "無正式版"}`),
        el("p", "metric-label", `Secret Ref ${active.secret_ref || "-"}｜Fallback ${active.fallback_model_id || "-"}`),
      );
      if (allowed.has("ops.models.read") && configId) {
        const simulate = el("button", "", "模擬 Fallback");
        simulate.addEventListener("click", async () => {
          const error = window.prompt("觸發錯誤", "TIMEOUT");
          if (!error) return;
          const result = await api(`/api/governance/models/${configId}/simulate-fallback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ error }),
          });
          showContentModal("Fallback 模擬", el("pre", "json-block", JSON.stringify(result, null, 2)));
        });
        panel.append(simulate);
      }
      if (allowed.has("ops.models.activate") && configId) {
        const rollback = el("button", "", "回復上一健康模型");
        rollback.addEventListener("click", async () => {
          const reason = window.prompt("回復原因");
          if (!reason || reason.trim().length < 3) return;
          await api(`/api/governance/models/${configId}/rollback`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason.trim() }),
          });
          await renderModels();
        });
        panel.append(rollback);
      }
    }
    app.replaceChildren(panel);
  } catch (error) {
    app.replaceChildren(el("div", "error", error.message));
  }
}

export const modelsPage = createPageController({
  enter: async () => renderModels(),
  update: async () => renderModels(),
  leave: async () => {},
});
