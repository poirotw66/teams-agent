import { api, el } from "../../api.js";
import {
  showContentModal,
  closeContentModal,
  showConfirm,
  showTextPrompt,
  showToast,
} from "../../components/modal.js";
import { labelStatus } from "../../app/labels.js";
import { navigateTo } from "../../app/navigation.js";
import { withReturnTo } from "../../app/returnTo.js";
import { escapeHtml } from "./shared.js";
import { showGateDecisionModal } from "./gateSettings.js";

export function executionOutcome(execution = {}) {
  const status = String(execution.status || "").toUpperCase();
  const hasInconclusiveMetric = (execution.metric_results || []).some(
    (metric) => String(metric.pass_status || "").toUpperCase() === "INCONCLUSIVE",
  );
  if (status === "FAILED" || status === "CANCELLED" || execution.passed == null || hasInconclusiveMetric) {
    return { label: "未判定", className: "badge-warning", pass: false, inconclusive: true };
  }
  return execution.passed
    ? { label: "PASS", className: "badge-success", pass: true, inconclusive: false }
    : { label: "FAIL", className: "badge-danger", pass: false, inconclusive: false };
}

export function renderRunSummaryCards(container, summary) {
  if (!summary) {
    container.replaceChildren();
    return;
  }
  const passRate = summary.pass_rate == null ? "—" : `${Math.round(summary.pass_rate * 100)}%`;
  const passRateColor = summary.pass_rate == null
    ? "#6c757d"
    : summary.pass_rate >= 0.95
      ? "#28a745"
      : "#dc3545";
  const coverage = summary.coverage == null ? "—" : `${Math.round(summary.coverage * 100)}%`;
  container.innerHTML = `
    <p class="metric-label" style="margin-bottom: 0.75rem;">下列摘要用來判斷「品質是否過關」；僅有執行紀錄不足以視為通過。</p>
    <div class="summary-cards-grid" style="display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 20px;">
      <div class="card" style="flex: 1 1 180px; min-width: 0; padding: 12px; border-left: 4px solid ${passRateColor}; background: #fff;">
        <div class="text-muted">品質通過率</div>
        <h2 style="margin: 4px 0; color: ${passRateColor};">${escapeHtml(passRate)}</h2>
        <small>候選版通過的可判定案例比例</small>
      </div>
      <div class="card" style="flex: 1 1 180px; min-width: 0; padding: 12px; border-left: 4px solid #dc3545; background: #fff;">
        <div class="text-muted">新增失敗 (Regressions)</div>
        <h2 style="margin: 4px 0; color: #dc3545;">${escapeHtml(summary.regressions ? summary.regressions.length : 0)}</h2>
        <small>候選版不如基準版之案例</small>
      </div>
      <div class="card" style="flex: 1 1 180px; min-width: 0; padding: 12px; border-left: 4px solid #28a745; background: #fff;">
        <div class="text-muted">已修復 (Fixed)</div>
        <h2 style="margin: 4px 0; color: #28a745;">${escapeHtml(summary.fixes ? summary.fixes.length : 0)}</h2>
        <small>候選版成功改善之案例</small>
      </div>
      <div class="card" style="flex: 1 1 180px; min-width: 0; padding: 12px; border-left: 4px solid #ffc107; background: #fff;">
        <div class="text-muted">重大失敗 (Critical)</div>
        <h2 style="margin: 4px 0; color: #856404;">${escapeHtml(summary.critical_failures ? summary.critical_failures.length : 0)}</h2>
        <small>標記重大之失敗題數</small>
      </div>
      <div class="card" style="flex: 1 1 180px; min-width: 0; padding: 12px; border-left: 4px solid #17a2b8; background: #fff;">
        <div class="text-muted">完成比例</div>
        <h2 style="margin: 4px 0; color: #17a2b8;">${escapeHtml(coverage)}</h2>
        <small>${escapeHtml(summary.judged_cases)} / ${escapeHtml(summary.total_cases)} 題已完成判定</small>
      </div>
    </div>
  `;
}

export async function renderResultsTab(container, allowed) {
  container.replaceChildren();
  const box = el("div", "content-box");
  box.innerHTML = `
    <h3>驗收結果與版本比較 (Evaluation Results)</h3>
    <p class="metric-label">執行完成 ≠ 品質通過／閘道通過。請用下方通過率、退步案例與門檻政策判斷是否可發布。</p>
    <div id="results-summary-container"></div>
    <div class="table-responsive" style="margin-top: 20px;">
      <table class="data-table">
        <thead>
          <tr>
            <th>驗收執行 ID</th>
            <th>題庫版本 ID</th>
            <th>測試模式</th>
            <th>候選通過率</th>
            <th>覆蓋率</th>
            <th>實際成本 (USD)</th>
            <th>狀態</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="runs-table-body">
          <tr><td colspan="8">載入中...</td></tr>
        </tbody>
      </table>
    </div>
    <div id="case-comparison-container" style="margin-top: 24px;"></div>
  `;
  container.append(box);

  const tbody = box.querySelector("#runs-table-body");
  const summaryContainer = box.querySelector("#results-summary-container");
  const caseCompContainer = box.querySelector("#case-comparison-container");

  try {
    const runs = await api("/api/evaluations/runs");
    if (!runs || !runs.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-muted">目前尚無驗收執行紀錄。請至「執行驗收」頁籤發起新評測。</td></tr>';
      caseCompContainer.innerHTML = `
        <div class="callout">
          <strong>如何閱讀退步</strong>
          <p class="metric-label" style="margin:0.35rem 0 0">有 run 後，案例比對會標示「新增失敗 (Regression)」；若基準有答、候選空白，會顯示「退步：候選漏答」並在細節並排標紅。執行完成仍不代表品質／閘道通過。</p>
        </div>`;
      return;
    }

    const latestRun = runs[0];
    renderRunSummaryCards(summaryContainer, latestRun.summary);

    tbody.replaceChildren();
    for (const r of runs) {
      const tr = el("tr");
      const candidateManifestHash =
        r.candidate_manifest?.manifest_hash || r.candidate_manifest_hash || "";
      const passRateStr = r.summary && r.summary.pass_rate !== null ? `${Math.round(r.summary.pass_rate * 100)}%` : "-";
      const coverageStr = r.summary ? `${Math.round(r.summary.coverage * 100)}%` : "-";
      const modeLabel = r.mode === "REAL_RAG"
        ? "真實檢索"
        : r.mode === "OFFLINE_BENCHMARK"
          ? "離線基準"
          : r.mode || "—";
      const statusLabel = labelStatus(r.status);

      tr.innerHTML = `
        <td><code>${escapeHtml(r.run_id)}</code></td>
        <td><code>${escapeHtml((r.set_version_id || "").slice(0, 14))}...</code></td>
        <td title="${escapeHtml(r.mode || "")}">${escapeHtml(modeLabel)}</td>
        <td><span class="badge ${r.summary && r.summary.pass_rate >= 0.9 ? "badge-success" : "badge-warning"}">${escapeHtml(passRateStr)}</span></td>
        <td>${escapeHtml(coverageStr)}</td>
        <td>$${escapeHtml(r.actual_cost_usd)}</td>
        <td><span class="badge ${r.status === "COMPLETED" ? "badge-success" : "badge-secondary"}" title="${escapeHtml(r.status || "")}">${escapeHtml(statusLabel)}</span></td>
        <td>
          <button class="btn-secondary btn-sm view-cases-btn">查看比對</button>
          <button class="btn-primary btn-sm eval-gate-btn" style="margin-left: 4px;">門檻判定</button>
        </td>
      `;

      tr.querySelector(".view-cases-btn").addEventListener("click", () => {
        renderRunSummaryCards(summaryContainer, r.summary);
        loadCaseComparison(caseCompContainer, r.run_id, allowed);
      });

      tr.querySelector(".eval-gate-btn").addEventListener("click", () => {
        if (!candidateManifestHash) {
          showContentModal(
            "無法執行門檻判定",
            el("div", "error", "這筆驗收執行缺少候選版本 manifest hash，無法建立可追溯的門檻判定。請重新執行驗收。"),
          );
          return;
        }
        showGateDecisionModal(r.run_id, candidateManifestHash, allowed);
      });

      tbody.append(tr);
    }

    // Default load latest run comparison
    await loadCaseComparison(caseCompContainer, latestRun.run_id, allowed);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-danger">載入執行清單失敗: ${escapeHtml(err.message || err)}</td></tr>`;
  }
}

export async function loadCaseComparison(container, runId, allowed) {
  container.replaceChildren();
  const box = el("div", "sub-content-box");
  box.innerHTML = `
    <h4>案例比對清單 (Run: <code>${escapeHtml(runId)}</code>)</h4>
    <p class="metric-label">「新增失敗」= 基準通過但候選失敗（退步）；若候選答案為空而基準有答，屬漏答退步，請開細節並排比對。</p>
    <div class="table-responsive">
      <table class="data-table">
        <thead>
          <tr>
            <th>案例 ID</th>
            <th>基準版判定</th>
            <th>候選版判定</th>
            <th>比對差異</th>
            <th>失敗分類</th>
            <th>耗時 (ms)</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="case-comp-body">
          <tr><td colspan="7">載入案例中...</td></tr>
        </tbody>
      </table>
    </div>
  `;
  container.append(box);

  const tbody = box.querySelector("#case-comp-body");
  try {
    const cases = await api(`/api/evaluations/runs/${runId}/cases`);
    const baselineCases = {};
    const candidateCases = {};

    for (const c of cases) {
      if (c.target_side === "BASELINE") {
        baselineCases[c.case_revision_id] = c;
      } else {
        candidateCases[c.case_revision_id] = c;
      }
    }

    tbody.replaceChildren();
    const allRevs = [...new Set([
      ...Object.keys(baselineCases),
      ...Object.keys(candidateCases),
    ])];
    if (!allRevs.length) {
      tbody.innerHTML = '<tr><td colspan="7">無案例紀錄</td></tr>';
      return;
    }

    for (const revId of allRevs) {
      const c = candidateCases[revId] || {};
      const b = baselineCases[revId] || {};
      const caseId = c.case_id || b.case_id || revId;

      const baselineOutcome = executionOutcome(b);
      const candidateOutcome = executionOutcome(c);
      let diffTag = '<span class="badge badge-secondary">相同</span>';
      if (!candidateCases[revId]) {
        diffTag = '<span class="badge badge-warning">候選缺少執行紀錄（未判定）</span>';
      } else if (!baselineCases[revId]) {
        diffTag = '<span class="badge badge-warning">基準缺少執行紀錄（未判定）</span>';
      } else if (baselineOutcome.pass && candidateOutcome.inconclusive) {
        diffTag = '<span class="badge badge-warning">退步：候選未判定（不計入通過）</span>';
      } else if (baselineOutcome.pass && !candidateOutcome.pass) {
        const missedAnswer = Boolean((b.answer || "").trim()) && !(c.answer || "").trim();
        diffTag = missedAnswer
          ? '<span class="badge badge-danger">退步：候選漏答</span>'
          : '<span class="badge badge-danger">新增失敗 (Regression)</span>';
      } else if (!baselineOutcome.pass && !baselineOutcome.inconclusive && candidateOutcome.pass) {
        diffTag = '<span class="badge badge-success">已修復 (Fixed)</span>';
      } else if (baselineOutcome.inconclusive || candidateOutcome.inconclusive) {
        diffTag = '<span class="badge badge-warning">未判定：不計入通過</span>';
      }

      const tr = el("tr");
      tr.innerHTML = `
        <td><code>${escapeHtml(caseId)}</code></td>
        <td><span class="badge ${escapeHtml(baselineOutcome.className)}">${escapeHtml(baselineOutcome.label)}</span></td>
        <td><span class="badge ${escapeHtml(candidateOutcome.className)}">${escapeHtml(candidateOutcome.label)}</span></td>
        <td>${diffTag}</td>
        <td>${escapeHtml(c.failure_classification || (!candidateCases[revId] ? "候選缺少執行紀錄" : "-"))}</td>
        <td>${escapeHtml(c.latency_ms ?? "-")}</td>
        <td>
          <button class="btn-secondary btn-sm inspect-btn">檢視細節與覆核</button>
        </td>
      `;

      tr.querySelector(".inspect-btn").addEventListener("click", () => {
        showExecutionDetailModal(runId, c, b, allowed);
      });

      tbody.append(tr);
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-danger">載入比對案例失敗: ${escapeHtml(err.message || err)}</td></tr>`;
  }
}

export function showExecutionDetailModal(runId, candidateExec, baselineExec, allowed) {
  const baselineOutcome = executionOutcome(baselineExec);
  const candidateOutcome = executionOutcome(candidateExec);
  const canReview = allowed.has("ops.evals.write") && Boolean(candidateExec.execution_id);
  const modalContent = el("div", "execution-modal-content");
  modalContent.innerHTML = `
    <h3>案例執行細節與人工覆核</h3>
    <div style="display: flex; gap: 16px; margin-bottom: 16px;">
      <div style="flex: 1; background: #f8f9fa; padding: 12px; border-radius: 4px;">
        <strong>【基準版回答】</strong>
        <p style="white-space: pre-wrap; margin-top: 8px;">${escapeHtml(baselineExec.answer || "(無回答)")}</p>
      </div>
      <div style="flex: 1; background: #f8f9fa; padding: 12px; border-radius: 4px;${!((candidateExec.answer || "").trim()) && (baselineExec.answer || "").trim() ? "border:2px solid #dc3545;" : ""}">
        <strong>【候選版回答】${!((candidateExec.answer || "").trim()) && (baselineExec.answer || "").trim() ? " <span class=\"badge badge-danger\">漏答</span>" : ""}</strong>
        <p style="white-space: pre-wrap; margin-top: 8px;">${escapeHtml(candidateExec.answer || "(無回答)")}</p>
      </div>
    </div>
    <p class="callout ${candidateOutcome.inconclusive ? "warning" : ""}"><strong>候選判定：${escapeHtml(candidateOutcome.label)}</strong>。執行完成不等於品質通過；ERROR／未判定一律不計入通過。${candidateExec.error_detail ? `原因：${escapeHtml(candidateExec.error_detail)}` : ""}</p>
    <h4>指標判定結果 (Candidate Metrics)</h4>
    <table class="data-table" style="margin-bottom: 16px;">
      <thead>
        <tr>
          <th>指標</th>
          <th>判定</th>
          <th>分數</th>
          <th>理由與依據</th>
        </tr>
      </thead>
      <tbody>
        ${(candidateExec.metric_results || []).map(m => `
          <tr>
            <td><code>${escapeHtml(m.metric_id)}</code></td>
            <td><span class="badge ${m.pass_status === "PASS" ? "badge-success" : m.pass_status === "FAIL" ? "badge-danger" : m.pass_status === "INCONCLUSIVE" ? "badge-warning" : "badge-secondary"}">${escapeHtml(m.pass_status)}</span></td>
            <td>${m.score != null ? escapeHtml(m.score) : "-"}</td>
            <td>${escapeHtml(m.reason || "-")}</td>
          </tr>
        `).join("") || '<tr><td colspan="4" class="text-muted">目前沒有可供覆核的指標紀錄。</td></tr>'}
      </tbody>
    </table>
    ${canReview ? `<div class="review-section" style="background: #eef2f7; padding: 12px; border-radius: 4px;">
      <strong>人工覆核決策 (Human Review)</strong>
      <p class="text-muted" style="margin-top: 4px;">覆核將以 Append-only 方式記錄決策歷史，不竄改原始觀測數據。</p>
      <div class="form-group" style="margin-top: 8px;">
        <label>選擇指標</label>
        <select id="review-metric-select" class="form-select">
          ${(candidateExec.metric_results || []).map(m => `<option value="${escapeHtml(m.metric_id)}">${escapeHtml(m.metric_id)}</option>`).join("")}
        </select>
      </div>
      <div class="form-group">
        <label>覆核決策</label>
        <select id="review-decision-select" class="form-select">
          <option value="PASS">覆核為通過 (PASS)</option>
          <option value="FAIL">覆核為失敗 (FAIL)</option>
        </select>
      </div>
      <div class="form-group">
        <label>覆核理由</label>
        <input type="text" id="review-reason-input" class="form-input" placeholder="請填寫覆核理由...">
      </div>
      <div class="btn-row">
        <button id="submit-review-btn" class="btn-primary">送出覆核決策</button>
      </div>
    </div>` : `<div class="callout"><strong>目前為唯讀檢視。</strong> 只有具備驗收寫入權限且存在候選執行紀錄時，才能提交人工覆核。</div>`}
    ${candidateExec.execution_id && !candidateExec.passed && allowed.has("ops.evals.write") ? `
    <div class="qc-section" style="margin-top: 16px; padding: 12px; border: 1px dashed #ced4da; border-radius: 4px; background: #fff;">
      <strong>營運閉環 (GE-4 Quality Case Loop)</strong>
      <p class="text-muted" style="margin-top: 4px;">本案例判定未通過，可直接轉為品質改善案件進行後續追蹤與複測。</p>
      <button id="promote-qc-btn" class="btn-secondary">轉為品質改善案件 (Create Quality Case)</button>
    </div>` : ""}
  `;

  const qcBtn = modalContent.querySelector("#promote-qc-btn");
  if (qcBtn) {
    qcBtn.addEventListener("click", async () => {
      const rootCause = await showTextPrompt({
        title: "建立品質改善案件",
        message: "請輸入問題根本原因（Root Cause，至少 3 個字元）。",
        defaultValue: candidateExec.failure_classification || "評測判定未達標",
        minLength: 3,
        required: true,
      });
      if (rootCause == null) return;
      try {
        const qcRes = await api(`/api/evaluations/runs/${runId}/cases/${candidateExec.execution_id}/quality-case`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ root_cause: rootCause.trim() }),
        });
        const caseId = qcRes.quality_case?.quality_case_id || qcRes.quality_case_id;
        if (caseId && await showConfirm({
          title: "品質改善案件已建立",
          message: `已建立改善案件 ${caseId}。是否立即開啟案件？`,
          confirmLabel: "立即開啟",
          cancelLabel: "稍後處理",
        })) {
          closeContentModal();
          void navigateTo(
            "quality",
            withReturnTo(
              { caseId, tab: "cases" },
              "evaluations",
              { tab: "results", runId },
            ),
          );
          return;
        }
        showToast(`已成功建立品質改善案件：${caseId || "(未知 ID)"}`, { tone: "success" });
      } catch (err) {
        showToast(`建立案件失敗: ${err.message || err}`, { tone: "error" });
      }
    });
  }

  const submitBtn = modalContent.querySelector("#submit-review-btn");
  if (submitBtn) submitBtn.addEventListener("click", async () => {
    const reason = modalContent.querySelector("#review-reason-input").value.trim();
    if (!reason) {
      showToast("請填寫覆核理由", { tone: "error" });
      return;
    }
    const metricId = modalContent.querySelector("#review-metric-select")?.value;
    if (!metricId) {
      showToast("請選擇要覆核的指標", { tone: "error" });
      return;
    }
    const decision = modalContent.querySelector("#review-decision-select").value;

    try {
      await api(`/api/evaluations/runs/${runId}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          execution_id: candidateExec.execution_id,
          metric_id: metricId,
          decision: decision,
          reason: reason,
        }),
      });
      showToast("覆核決策已儲存！", { tone: "success" });
      closeContentModal();
    } catch (err) {
      showToast(`覆核失敗: ${err.message || err}`, { tone: "error" });
    }
  });

  showContentModal(modalContent);
}
