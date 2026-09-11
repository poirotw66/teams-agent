import { api, el } from "../../api.js";
import { showToast } from "../../components/modal.js";
import { loadNavFilters } from "../../app/navigation.js";
import { parseReturnTo } from "../../app/returnTo.js";
import { escapeHtml } from "./shared.js";

export async function renderRunsTab(container, allowed) {
  container.replaceChildren();
  if (!allowed.has("ops.evals.run")) {
    const readOnly = el("div", "content-box");
    readOnly.append(
      el("h3", "", "執行驗收"),
      el(
        "div",
        "callout warning",
        "目前角色只有驗收讀取權限，沒有執行預檢或啟動驗收的權限。請改看「驗收結果」或聯絡具備驗收執行權限的管理者。",
      ),
    );
    container.append(readOnly);
    return;
  }
  const returnContext = parseReturnTo(loadNavFilters().returnTo);
  const qualityCaseId = returnContext?.view === "quality"
    ? returnContext.filters.caseId || ""
    : "";
  const box = el("div", "content-box");
  box.innerHTML = `
    <h3>執行驗收</h3>
    <p class="text-muted">選擇題庫版本、正式版／候選版 Prompt 與模型，先預檢再啟動比較。</p>
    <div class="form-grid">
      <div class="form-group">
        <label for="run-set-version">評測題庫版本</label>
        <select id="run-set-version" class="form-select">
          <option value="">載入中...</option>
        </select>
      </div>
      <div class="form-group">
        <label for="baseline-prompt">基準（正式版）</label>
        <select id="baseline-prompt" class="form-select">
          <option value="">載入中...</option>
        </select>
        <p id="baseline-prompt-meta" class="metric-label"></p>
      </div>
      <div class="form-group">
        <label for="candidate-prompt">候選版</label>
        <select id="candidate-prompt" class="form-select">
          <option value="">載入中...</option>
        </select>
        <p id="candidate-prompt-meta" class="metric-label"></p>
      </div>
      <div class="form-group">
        <label for="target-model">模型</label>
        <select id="target-model" class="form-select">
          <option value="">載入中...</option>
        </select>
      </div>
      <div class="form-group">
        <label for="run-mode">評測模式</label>
        <select id="run-mode" class="form-select">
          <option value="REAL_RAG">真實檢索評測 — 固定知識版本</option>
          <option value="OFFLINE_BENCHMARK">離線基準評測</option>
        </select>
      </div>
      <div class="form-group">
        <label for="run-max-cases">最大題數（選填）</label>
        <input type="number" id="run-max-cases" class="form-input" placeholder="不限制或輸入數字">
      </div>
      <details class="bu-ops-note" id="run-advanced">
        <summary>進階資訊（技術識別）</summary>
        <p class="metric-label">預檢通過後會顯示 Manifest Hash 等技術欄位；日常操作不需手填版本代碼。</p>
        <div id="run-advanced-ids" class="metric-label"></div>
      </details>
      <div class="btn-row">
        <button id="preflight-btn" class="button-primary" type="button">執行預檢</button>
        <button id="start-run-btn" class="button-primary" type="button" style="display: none;">啟動驗收執行</button>
      </div>
    </div>
    <div id="preflight-results" style="margin-top: 16px;"></div>
  `;

  if (qualityCaseId) {
    const contextNote = el(
      "div",
      "callout",
      `本次驗收執行會記錄到改善案件 ${qualityCaseId.slice(0, 8)}…；執行完成不會自動將案件標為已結案。`,
    );
    contextNote.style.marginBottom = "1rem";
    box.querySelector("h3")?.after(contextNote);
  }

  container.append(box);

  const select = box.querySelector("#run-set-version");
  const baselineSelect = box.querySelector("#baseline-prompt");
  const candidateSelect = box.querySelector("#candidate-prompt");
  const modelSelect = box.querySelector("#target-model");
  const baselineMeta = box.querySelector("#baseline-prompt-meta");
  const candidateMeta = box.querySelector("#candidate-prompt-meta");
  const advancedIds = box.querySelector("#run-advanced-ids");
  const preflightBtn = box.querySelector("#preflight-btn");
  const startRunBtn = box.querySelector("#start-run-btn");
  const resultsDiv = box.querySelector("#preflight-results");

  let resolvedPreflight = null;
  const promptOptionsByValue = new Map();

  function formatTaipei(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("zh-TW", {
        timeZone: "Asia/Taipei",
        hour12: false,
      });
    } catch {
      return String(iso);
    }
  }

  function promptOptionLabel(version) {
    const status = String(version.status || "").toUpperCase();
    const isOfficial = status === "ACTIVE";
    const kind = isOfficial ? "正式版" : "候選版";
    const name = version.display_name || version.version || version.version_id || "未命名";
    const updated = formatTaipei(version.activated_at || version.approved_at || version.created_at);
    return `${kind} · ${name} · ${status || "—"} · ${updated}`;
  }

  function syncPromptMeta(selectEl, metaEl) {
    const opt = promptOptionsByValue.get(selectEl.value);
    if (!opt) {
      metaEl.textContent = "";
      return;
    }
    metaEl.textContent = `版本代碼 ${opt.version || opt.version_id || "—"}｜更新 ${formatTaipei(opt.activated_at || opt.approved_at || opt.created_at)}`;
  }

  try {
    const setsRes = await api("/api/evaluations/sets");
    select.innerHTML = '<option value="">-- 請選擇題庫版本 --</option>';
    for (const s of setsRes.items || []) {
      const detail = await api(`/api/evaluations/sets/${s.set_id}`);
      for (const v of detail.versions || []) {
        select.innerHTML += `<option value="${escapeHtml(v.set_version_id)}">${escapeHtml(s.name)} - ${escapeHtml(v.version)}（${escapeHtml(v.status)}，${escapeHtml(v.case_revision_ids.length)} 題）</option>`;
      }
    }
  } catch (err) {
    select.innerHTML = '<option value="">無法載入題庫版本</option>';
  }

  try {
    const govData = await api("/api/governance/prompts");
    const item = (govData.items || [])[0];
    const promptId = item?.prompt?.prompt_id;
    const activeId = item?.active?.version_id;
    const versions = [];
    if (promptId) {
      const detail = await api(`/api/governance/prompts/${promptId}`);
      versions.push(...(detail.versions || []));
    } else if (item?.active) {
      versions.push(item.active);
    }
    baselineSelect.innerHTML = "";
    candidateSelect.innerHTML = "";
    promptOptionsByValue.clear();
    if (!versions.length) {
      baselineSelect.innerHTML = '<option value="default">default（無治理版本資料）</option>';
      candidateSelect.innerHTML = '<option value="default">default（無治理版本資料）</option>';
    } else {
      const sorted = [...versions].sort((a, b) => {
        const aActive = a.version_id === activeId || a.status === "ACTIVE" ? 0 : 1;
        const bActive = b.version_id === activeId || b.status === "ACTIVE" ? 0 : 1;
        if (aActive !== bActive) return aActive - bActive;
        return String(b.created_at || "").localeCompare(String(a.created_at || ""));
      });
      for (const version of sorted) {
        const value = version.version || version.version_id;
        promptOptionsByValue.set(value, version);
        const baselineOpt = document.createElement("option");
        baselineOpt.value = value;
        baselineOpt.textContent = promptOptionLabel(version);
        baselineSelect.append(baselineOpt);
        const candidateOpt = document.createElement("option");
        candidateOpt.value = value;
        candidateOpt.textContent = promptOptionLabel(version);
        candidateSelect.append(candidateOpt);
      }
      const official = sorted.find((v) => v.version_id === activeId || v.status === "ACTIVE") || sorted[0];
      const candidate =
        sorted.find((v) => v !== official && String(v.status || "").toUpperCase() !== "ACTIVE") ||
        sorted.find((v) => v !== official) ||
        official;
      baselineSelect.value = official.version || official.version_id;
      candidateSelect.value = candidate.version || candidate.version_id;
    }
    syncPromptMeta(baselineSelect, baselineMeta);
    syncPromptMeta(candidateSelect, candidateMeta);
    baselineSelect.addEventListener("change", () => syncPromptMeta(baselineSelect, baselineMeta));
    candidateSelect.addEventListener("change", () => syncPromptMeta(candidateSelect, candidateMeta));
  } catch (err) {
    baselineSelect.innerHTML = '<option value="default">default</option>';
    candidateSelect.innerHTML = '<option value="candidate-v1.1">candidate-v1.1</option>';
  }

  try {
    const modelsRes = await api("/api/governance/models");
    const modelItems = modelsRes.items || [];
    modelSelect.innerHTML = "";
    const seen = new Set();
    for (const entry of modelItems) {
      const active = entry.active || {};
      const modelId = active.model_id;
      if (!modelId || seen.has(modelId)) continue;
      seen.add(modelId);
      const opt = document.createElement("option");
      opt.value = modelId;
      opt.textContent = `${modelId}（${active.status || "ACTIVE"} · ${active.provider || "model"}）`;
      modelSelect.append(opt);
    }
    if (!modelSelect.options.length) {
      modelSelect.innerHTML = '<option value="gemini-2.5-flash">gemini-2.5-flash</option>';
    }
  } catch (err) {
    modelSelect.innerHTML = '<option value="gemini-2.5-flash">gemini-2.5-flash</option>';
  }

  preflightBtn.addEventListener("click", async () => {
    const setVersionId = select.value;
    if (!setVersionId) {
      showToast("請先選擇評測題庫版本", { tone: "error" });
      return;
    }
    const maxCasesVal = box.querySelector("#run-max-cases")?.value;
    const limits = maxCasesVal ? { max_cases: parseInt(maxCasesVal, 10) } : {};
    const baselinePrompt = (baselineSelect.value || "").trim() || "default";
    const candidatePrompt = (candidateSelect.value || "").trim() || baselinePrompt;
    const targetModel = (modelSelect.value || "").trim() || "gemini-2.5-flash";

    resultsDiv.innerHTML = '<div class="alert alert-info">正在執行預檢中...</div>';
    try {
      const res = await api("/api/evaluations/runs/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          set_version_id: setVersionId,
          baseline_target: {
            prompt_version: baselinePrompt,
            model_id: targetModel,
          },
          candidate_target: {
            prompt_version: candidatePrompt,
            model_id: targetModel,
          },
          limits: limits,
        }),
      });
      resolvedPreflight = res;
      if (res.is_valid) {
        resultsDiv.innerHTML = `
          <div class="alert alert-success">
            <strong>預檢通過</strong><br>
            • 案例題數: ${escapeHtml(res.case_count)} 題<br>
            • 預估耗費: $${escapeHtml(res.estimated_cost_usd)} USD（約 ${escapeHtml(res.estimated_duration_seconds)} 秒）
            ${res.warnings && res.warnings.length ? `<br>提醒: ${escapeHtml(res.warnings.join("; "))}` : ""}
          </div>
        `;
        advancedIds.innerHTML = `
          基準 Manifest: <code>${escapeHtml(res.resolved_baseline_manifest ? res.resolved_baseline_manifest.manifest_hash.slice(0, 16) : "")}…</code><br>
          候選 Manifest: <code>${escapeHtml(res.resolved_candidate_manifest ? res.resolved_candidate_manifest.manifest_hash.slice(0, 16) : "")}…</code>
        `;
        startRunBtn.style.display = "inline-block";
      } else {
        resultsDiv.innerHTML = `
          <div class="alert alert-danger">
            <strong>預檢阻擋</strong><br>
            ${res.blocking_errors.map((error) => escapeHtml(error)).join("<br>")}
          </div>
        `;
        startRunBtn.style.display = "none";
      }
    } catch (err) {
      resultsDiv.innerHTML = `<div class="alert alert-danger">預檢失敗: ${escapeHtml(err.message || err)}</div>`;
    }
  });

  startRunBtn.addEventListener("click", async () => {
    if (!resolvedPreflight) return;
    startRunBtn.disabled = true;
    startRunBtn.textContent = "執行評測中...";

    try {
      const maxCasesVal = box.querySelector("#run-max-cases")?.value;
      const limits = maxCasesVal ? { max_cases: parseInt(maxCasesVal, 10) } : {};
      const baselinePrompt = (baselineSelect.value || "").trim() || "default";
      const candidatePrompt = (candidateSelect.value || "").trim() || baselinePrompt;
      const targetModel = (modelSelect.value || "").trim() || "gemini-2.5-flash";
      const runMode = box.querySelector("#run-mode")?.value || "REAL_RAG";

      const res = await api("/api/evaluations/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          set_version_id: select.value,
          baseline_target: {
            prompt_version: baselinePrompt,
            model_id: targetModel,
          },
          candidate_target: {
            prompt_version: candidatePrompt,
            model_id: targetModel,
          },
          mode: runMode,
          limits: limits,
          quality_case_id: qualityCaseId || null,
        }),
      });

      resultsDiv.innerHTML = `
        <div class="alert alert-success">
          <strong>評測執行已啟動／完成排程</strong><br>
          Run ID: <code>${escapeHtml(res.run?.run_id || res.run_id || "—")}</code>｜狀態: ${escapeHtml(res.run?.status || "—")}<br>
          可至「驗收結果」頁籤查看對比分析${qualityCaseId ? "；返回案件後會顯示本次結果" : ""}。<br>
          <span class="text-muted">注意：執行完成只代表評測跑完，不代表品質通過或發布閘道通過；請對照通過率、退步案例與門檻政策。</span>
        </div>
      `;
      startRunBtn.disabled = false;
      startRunBtn.textContent = "啟動驗收執行";
    } catch (err) {
      showToast(`啟動評測失敗: ${err.message || err}`, { tone: "error" });
      startRunBtn.disabled = false;
      startRunBtn.textContent = "啟動驗收執行";
    }
  });
}
