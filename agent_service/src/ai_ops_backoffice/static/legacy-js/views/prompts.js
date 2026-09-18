import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { presentSystemPage } from "../app/adminChrome.js";
import { showContentModal, showTextPrompt, showToast } from "../components/modal.js";
import { exampleSelect } from "../components/forms.js";
import { createPageController } from "../app/lifecycle.js";

export async function renderPrompts() {
  const app = document.getElementById("app");
  app.replaceChildren(el("div", "empty", "載入中…"));
  try {
    const allowed = actorCapabilities();
    const [govData, candidateData, taxonomy, examples, harnessStatus] = await Promise.all([
      api("/api/governance/prompts"),
      api("/api/prompts/candidates"),
      api("/api/taxonomy"),
      api("/api/examples?status=VERIFIED"),
      api("/api/governance/eval-harness").catch(() => null),
    ]);
    const item = (govData.items || [])[0];
    const active = item?.active || {};
    const promptId = item?.prompt?.prompt_id;
    const harnessDetail = harnessStatus || {
      configured: false,
      available: false,
      releaseEligible: false,
      mode: "unset",
      detail: "eval_harness_not_configured",
    };
    let harnessLabel = "評測執行器：未設定";
    if (harnessDetail.configured === false || harnessDetail.mode === "unset") {
      harnessLabel = "評測執行器：未設定（正式發布閘道不可用）";
    } else if (!harnessDetail.available) {
      harnessLabel = `評測執行器：執行失敗／不可用（${harnessDetail.detail || harnessDetail.mode}）`;
    } else if (!harnessDetail.releaseEligible) {
      harnessLabel = `評測執行器：已就緒但非正式閘道（${harnessDetail.name || harnessDetail.mode}；品質／模擬結果不可當作放行）`;
    } else {
      harnessLabel = `評測執行器：正式閘道就緒（${harnessDetail.name}）`;
    }
    const activePanel = el("section", "panel");
    activePanel.append(
      el("h2", "", "Active Issue Extractor Prompt"),
      el("p", "metric-label", `環境影響：正式 Prompt 變更需候選 → Eval → 核准 → Canary → 啟用`),
      el("p", "metric-label", harnessLabel),
      el("p", "metric-label", `Version ${active.version || "-"}｜${active.status || "-"}｜${active.activated_at || active.created_at || "-"}`),
      el("p", "metric-label", `Content Hash ${active.content_hash || "-"}｜核准者 ${active.approved_by || "-"}`),
    );
    if (active.template) {
      const inspect = el("button", "", "檢視內容");
      inspect.addEventListener("click", () => {
        showContentModal("Active Prompt", el("pre", "json-block", active.template));
      });
      activePanel.append(inspect);
    }

    const candidatePanel = el("section", "panel");
    candidatePanel.append(el("h2", "", "Prompt Candidates（Phase 3 治理）"));
    const verified = (examples.items || []).filter((entry) => entry.dataset_version);
    if (allowed.has("ops.prompts.candidates.create") && verified.length && promptId) {
      const form = el("form", "form-grid");
      form.append(
        exampleSelect(
          "Verified Dataset",
          "dataset_version",
          verified.map((entry) => [
            entry.dataset_version,
            `${entry.dataset_version}｜${entry.expected_route} ${entry.label}`,
          ]),
        ),
      );
      const generate = el("button", "", "建立候選");
      generate.type = "submit";
      form.append(generate);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = new FormData(form);
        try {
          await api(`/api/governance/prompts/${promptId}/candidates`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              dataset_version: values.get("dataset_version"),
              taxonomy_version: taxonomy.taxonomyVersion,
            }),
          });
          await renderPrompts();
        } catch (error) {
          showContentModal("候選產生失敗", el("div", "error", error.message));
        }
      });
      candidatePanel.append(form);
    }
    const versions = (item?.versions || []);
    const detail = promptId ? await api(`/api/governance/prompts/${promptId}`) : { versions: [] };
    const rows = detail.versions || versions;
    if (rows.length) {
      const table = el("table");
      table.innerHTML = "<thead><tr><th>Version</th><th>狀態</th><th>Dataset</th><th>建立者</th><th>操作</th></tr></thead>";
      const body = el("tbody");
      for (const version of rows.slice().reverse()) {
        const actions = el("td");
        const compare = el("button", "", "比較／風險");
        compare.addEventListener("click", async () => {
          const result = await api(`/api/governance/prompts/${promptId}/versions/${version.version_id}/diff`);
          const content = el("div");
          content.append(
            el("p", "", `Active ${result.active.version}`),
            el("p", "", `Candidate ${result.candidate.version}`),
            el("p", "", `Critical Eval: ${result.eval ? (result.eval.critical_passed ? "PASS" : "FAIL") : "尚未評測"}`),
          );
          if (result.diff) content.append(el("pre", "json-block", result.diff));
          showContentModal("Prompt 比較", content);
        });
        actions.append(compare);
        const addAction = (label, path, payload) => {
          const button = el("button", "", label);
          button.addEventListener("click", async () => {
            const reason = await showTextPrompt({
              title: label,
              message: `請輸入${label}原因（至少 3 個字元）。`,
              minLength: 3,
              required: true,
            });
            if (reason == null) return;
            await api(path, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ reason: reason.trim(), ...payload }),
            });
            await renderPrompts();
          });
          actions.append(button);
        };
        if (allowed.has("ops.prompts.eval.run") && ["CANDIDATE", "EVALUATED"].includes(version.status)) {
          const evalButton = el("button", "", "執行 Eval");
          evalButton.addEventListener("click", async () => {
            if (!harnessDetail.available) {
              showToast(
                harnessDetail.configured === false
                  ? "評測執行器尚未設定，無法執行正式評測。"
                  : `評測執行器不可用：${harnessDetail.detail || "unknown"}`,
                { tone: "error" },
              );
              return;
            }
            const result = await api(
              `/api/governance/prompts/${promptId}/versions/${version.version_id}/eval`,
              { method: "POST" },
            );
            if (result?.eval?.critical_passed === false) {
              showToast("評測完成：品質／閘道不合格（critical 未通過）。", { tone: "error" });
            } else if (result?.eval?.quality_passed === false) {
              showToast("評測完成：品質不合格。", { tone: "error" });
            } else if (result?.eval?.status === "INCOMPLETE") {
              showToast("評測完成：流程不完整（執行失敗或 harness 不可用），非正式放行。", { tone: "warning" });
            }
            await renderPrompts();
          });
          actions.append(evalButton);
        }
        if (allowed.has("ops.prompts.approve") && version.status === "EVALUATED") {
          addAction("送審核准", `/api/governance/prompts/${promptId}/versions/${version.version_id}/approve`, {});
        }
        if (allowed.has("ops.prompts.canary") && version.status === "APPROVED") {
          addAction("開始 Canary", `/api/governance/prompts/${promptId}/versions/${version.version_id}/canary`, {
            percent: 5,
            environment: "prod",
          });
        }
        if (allowed.has("ops.prompts.canary") && version.status === "CANARY") {
          addAction("停止 Canary", `/api/governance/prompts/${promptId}/canary/stop`, {});
          const evaluate = el("button", "", "評估 Canary 指標");
          evaluate.addEventListener("click", async () => {
            const sample = await showTextPrompt({
              title: "評估 Canary 指標",
              message: "請輸入樣本數。",
              defaultValue: "50",
              inputType: "number",
              required: true,
            });
            if (sample == null) return;
            const errorRate = await showTextPrompt({
              title: "評估 Canary 指標",
              message: "請輸入錯誤率（0–1）。",
              defaultValue: "0.05",
              inputType: "number",
              required: true,
            });
            if (errorRate == null) return;
            const negative = await showTextPrompt({
              title: "評估 Canary 指標",
              message: "請輸入負評率（0–1）。",
              defaultValue: "0.1",
              inputType: "number",
              required: true,
            });
            if (negative == null) return;
            const handoff = await showTextPrompt({
              title: "評估 Canary 指標",
              message: "請輸入 Handoff 率（0–1）。",
              defaultValue: "0.2",
              inputType: "number",
              required: true,
            });
            if (handoff == null) return;
            const result = await api(`/api/governance/prompts/${promptId}/canary/evaluate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                sample_size: Number(sample),
                error_rate: Number(errorRate),
                negative_feedback_rate: Number(negative),
                handoff_rate: Number(handoff),
                safety_alerts: 0,
              }),
            });
            showContentModal("Canary 評估", el("pre", "json-block", JSON.stringify(result, null, 2)));
            await renderPrompts();
          });
          actions.append(evaluate);
        }
        if (allowed.has("ops.prompts.activate") && version.status === "CANARY") {
          addAction("啟用正式版", `/api/governance/prompts/${promptId}/versions/${version.version_id}/activate`, {});
        }
        const row = el("tr");
        row.append(
          el("td", "", version.version),
          el("td", "", version.status),
          el("td", "", version.dataset_version || "-"),
          el("td", "", version.created_by),
          actions,
        );
        body.append(row);
      }
      table.append(body);
      const promptScroll = el("div", "table-responsive");
      promptScroll.append(table);
      candidatePanel.append(promptScroll);
    } else {
      candidatePanel.append(el("p", "empty", "目前沒有 Prompt Candidate。"));
    }
    if (allowed.has("ops.prompts.rollback")) {
      const rollback = el("button", "", "回復上一健康版本");
      rollback.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: "回復上一健康版本",
          message: "請輸入回復原因（至少 3 個字元）。",
          minLength: 3,
          required: true,
        });
        if (reason == null) return;
        await api(`/api/governance/prompts/${promptId}/rollback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: reason.trim() }),
        });
        await renderPrompts();
      });
      candidatePanel.append(rollback);
    }
    // Keep Phase 2 POC list visible for continuity.
    if ((candidateData.items || []).length) {
      candidatePanel.append(el("p", "metric-label", `Phase 2 POC candidates: ${candidateData.items.length}`));
    }
    presentSystemPage(
      "Prompt 管理",
      "管理問題抽取 Prompt 的生效版本與候選稿。",
      activePanel,
      candidatePanel,
    );
  } catch (error) {
    presentSystemPage("Prompt 管理", null, el("div", "error", error.message));
  }
}

export const promptsPage = createPageController({
  enter: async () => renderPrompts(),
  update: async () => renderPrompts(),
  leave: async () => {},
});
