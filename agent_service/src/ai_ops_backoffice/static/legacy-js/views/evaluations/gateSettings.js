import { api, el } from "../../api.js";
import {
  showContentModal,
  closeContentModal,
  showTextPrompt,
  showToast,
} from "../../components/modal.js";
import { escapeHtml } from "./shared.js";
import { renderSchedulesSection } from "./schedules.js";

export async function showGateDecisionModal(runId, targetManifestHash, allowed) {
  const content = el("div", "modal-body");
  content.innerHTML = "<p>正在執行門檻判定 (Evaluating Quality Gate)...</p>";
  showContentModal(content);

  try {
    const res = await api("/api/evaluations/gate-decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        policy_id: "default-gate-policy",
        run_id: runId,
        target_manifest_hash: targetManifestHash,
      }),
    });

    const dec = res.decision;
    const decisionStatus = dec.decision || dec.status || "UNKNOWN";
    const statusBadge = decisionStatus === "PASS"
      ? '<span class="badge badge-success">✅ 通過 (PASS)</span>'
      : decisionStatus === "FAIL" || decisionStatus === "BLOCK"
      ? '<span class="badge badge-danger">❌ 未通過 (FAIL)</span>'
      : '<span class="badge badge-warning">⚠️ 狀態待確認</span>';
    const blockingReasons = dec.blocking_reasons || [];
    const metrics = dec.metrics_snapshot || {};

    content.innerHTML = `
      <h3>發布門檻判定結果 (Quality Gate Decision)</h3>
      <div class="meta-grid" style="margin-bottom: 16px;">
        <div><strong>判定 ID:</strong> <code>${escapeHtml(dec.decision_id)}</code></div>
        <div><strong>政策:</strong> ${escapeHtml(dec.policy_id)} (v${escapeHtml(dec.policy_version)})</div>
        <div><strong>判定狀態:</strong> ${statusBadge}</div>
        <div><strong>運作模式:</strong> ${escapeHtml(dec.mode_at_evaluation || "—")}</div>
        <div><strong>候選 Hash:</strong> <code>${escapeHtml(dec.target_manifest_hash ? dec.target_manifest_hash.slice(0, 16) : "")}...</code></div>
        <div><strong>判定時間:</strong> ${escapeHtml(dec.created_at || "—")}</div>
      </div>
      <div class="section-block">
        <h4>判定理由與分析</h4>
        <div class="content-box">${blockingReasons.length ? blockingReasons.map((reason) => escapeHtml(reason)).join("<br>") : "未記錄阻擋原因。"}</div>
      </div>
      <div class="section-block">
        <h4>指標門檻檢核細項</h4>
        <ul>
          ${(dec.rule_results || []).map(r => `
            <li>
              <strong>${escapeHtml(r.rule_name)}:</strong>
              ${r.passed ? "✅ 符合" : "❌ 不符"}
              <span class="text-muted">(${escapeHtml(r.details || "")})</span>
            </li>
          `).join("") || `
            <li>候選通過率：${metrics.pass_rate == null ? "—" : `${Math.round(metrics.pass_rate * 100)}%`}</li>
            <li>判定覆蓋率：${metrics.coverage == null ? "—" : `${Math.round(metrics.coverage * 100)}%`}</li>
            <li>退步案例：${Array.isArray(metrics.regressions) ? metrics.regressions.length : "—"}</li>
          `}
        </ul>
      </div>
      ${blockingReasons.length ? `
      <div class="alert alert-danger" style="margin-top: 12px;">
        <strong>阻擋原因：</strong><br>
        ${blockingReasons.map((reason) => escapeHtml(reason)).join("<br>")}
      </div>` : ""}
      <div id="waiver-section" style="margin-top: 16px;"></div>
    `;

    const waiverSection = content.querySelector("#waiver-section");
    if (decisionStatus !== "PASS" && allowed.has("ops.evals.write")) {
      const waiverBtn = el("button", "btn-secondary", "申請例外放行 (Request Waiver)");
      waiverBtn.addEventListener("click", async () => {
        const waiverReason = await showTextPrompt({
          title: "申請例外放行",
          message: "請輸入申請例外放行原因（須經雙人審核，至少 3 個字元）。",
          minLength: 3,
          required: true,
        });
        if (waiverReason == null) return;
        try {
          const excRes = await api(`/api/evaluations/gate-decisions/${dec.decision_id}/exceptions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              reason: waiverReason.trim(),
              validity_hours: 24,
            }),
          });
          showToast(`例外申請已送出 (ID: ${excRes.exception.exception_id})，狀態: ${excRes.exception.status}`, { tone: "success" });
          closeContentModal();
        } catch (err) {
          showToast(`申請例外放行失敗: ${err.message || err}`, { tone: "error" });
        }
      });
      waiverSection.append(waiverBtn);
    }
  } catch (err) {
    content.innerHTML = `<div class="error">門檻判定失敗: ${escapeHtml(err.message || err)}</div>`;
  }
}

export async function renderGatesTab(container, allowed) {
  container.replaceChildren();
  const box = el("div", "content-box");
  box.innerHTML = `
    <h3>發布門檻與治理 (Quality Gates & Impact)</h3>
    <p class="text-muted">管理品質發布門檻政策、執行知識變更影響分析與定期回歸排程。</p>

    <div class="section-block" style="margin-top: 20px;">
      <h4>1. 預設發布門檻政策 (Gate Policy)</h4>
      <div id="gate-policy-container" style="background: #fdfdfd; padding: 16px; border: 1px solid #e2e8f0; border-radius: 6px;">
        <p>載入政策資訊中...</p>
      </div>
    </div>

    <div class="section-block" style="margin-top: 24px;">
      <h4>2. 知識變更影響分析 (Knowledge Impact Analysis)</h4>
      <p class="text-muted">當知識文件或 FAQ 異動時，分析受影響的驗收題庫案例與版本。</p>
      <form id="impact-form" class="form-grid">
        <div class="form-group">
          <label>來源類型</label>
          <select id="impact-source-type" class="form-select">
            <option value="DOCUMENT">知識文件 (DOCUMENT)</option>
            <option value="FAQ">常見問答 (FAQ)</option>
          </select>
        </div>
        <div class="form-group">
          <label>來源 ID *</label>
          <input type="text" id="impact-source-id" class="form-input" required placeholder="例：doc_pwd_policy 或 faq_001" value="doc_pwd_policy">
        </div>
        <div class="btn-row">
          <button type="submit" class="btn-primary">分析變更影響</button>
        </div>
      </form>
      <div id="impact-result" style="margin-top: 12px;"></div>
    </div>

    <div class="section-block" style="margin-top: 24px;">
      <h4>3. 定期回歸排程 (Evaluation Schedules)</h4>
      <div class="table-responsive">
        <table class="data-table">
          <thead>
            <tr>
              <th>排程 ID</th>
              <th>名稱</th>
              <th>題庫版本 ID</th>
              <th>執行頻率</th>
              <th>預算上限 (USD)</th>
              <th>狀態</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="schedules-tbody">
            <tr><td colspan="7">載入排程中...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  `;
  container.append(box);

  // 1. Load Policy
  const policyContainer = box.querySelector("#gate-policy-container");
  const loadPolicy = async () => {
    try {
      const res = await api("/api/evaluations/gate-policies/default-gate-policy");
      if (res.error) {
        policyContainer.innerHTML = `<div class="text-muted">${escapeHtml(res.error)}</div>`;
        return;
      }
      const p = res.policy;
      const v = (res.versions || [])[0] || {};
      const isEnforce = v.mode === "ENFORCE";

      policyContainer.innerHTML = `
        <div class="meta-grid">
          <div><strong>政策 ID:</strong> <code>${escapeHtml(p.policy_id)}</code></div>
          <div><strong>政策名稱:</strong> ${escapeHtml(p.name)}</div>
          <div><strong>目前版本:</strong> v${escapeHtml(p.current_version)} (生效版本: v${escapeHtml(p.active_version)})</div>
          <div><strong>運作模式:</strong> <span class="badge ${isEnforce ? "badge-danger" : "badge-warning"}">${escapeHtml(v.mode || "REPORT_ONLY")}</span></div>
          <div><strong>最低覆蓋率要求:</strong> ${escapeHtml((v.minimum_coverage ?? 1.0) * 100)}%</div>
          <div><strong>最低通過率要求:</strong> ${escapeHtml((v.minimum_pass_rate ?? 0.95) * 100)}%</div>
          <div><strong>重大失敗容忍度:</strong> ${escapeHtml(v.critical_rule || "ZERO_TOLERANCE")} (零容忍)</div>
          <div><strong>最大退步案例數:</strong> ${escapeHtml(v.max_regression_count ?? 0)} 題</div>
        </div>
        ${allowed.has("ops.evals.gates.manage") ? `
        <div style="margin-top: 12px;">
          <button id="toggle-mode-btn" class="btn-secondary">
            ${isEnforce ? "切換為僅產報告 (REPORT_ONLY)" : "切換為強制阻擋 (ENFORCE)"}
          </button>
        </div>` : ""}
      `;

      const toggleBtn = policyContainer.querySelector("#toggle-mode-btn");
      if (toggleBtn) {
        toggleBtn.addEventListener("click", async () => {
          const newMode = isEnforce ? "REPORT_ONLY" : "ENFORCE";
          try {
            await api(`/api/evaluations/gate-policies/${p.policy_id}/versions/${v.version}/activate`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ mode: newMode }),
            });
            showToast(`門檻政策已切換為 ${newMode} 模式！`, { tone: "success" });
            loadPolicy();
          } catch (err) {
            showToast(`模式切換失敗: ${err.message || err}`, { tone: "error" });
          }
        });
      }
    } catch (err) {
      policyContainer.innerHTML = `<div class="error">載入門檻政策失敗: ${escapeHtml(err.message || err)}</div>`;
    }
  };
  await loadPolicy();

  // 2. Impact Form
  const impactForm = box.querySelector("#impact-form");
  const impactResult = box.querySelector("#impact-result");
  impactForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sType = box.querySelector("#impact-source-type").value;
    const sId = box.querySelector("#impact-source-id").value.trim();
    impactResult.innerHTML = "<p>分析中...</p>";
    try {
      const res = await api(`/api/evaluations/source-impacts?source_type=${encodeURIComponent(sType)}&source_id=${encodeURIComponent(sId)}`);
      const imp = res.impact;
      impactResult.innerHTML = `
        <div class="alert ${imp.affected_case_ids.length > 0 ? "alert-warning" : "alert-success"}">
          <strong>分析完成：</strong><br>
          • 受影響驗收案例數: ${escapeHtml(imp.affected_case_ids.length)} 題 ${imp.affected_case_ids.length ? `(ID: <code>${escapeHtml(imp.affected_case_ids.join(", "))}</code>)` : ""}<br>
          • 需複核案例數 (Requires Review): ${escapeHtml(imp.requires_review_count)} 題<br>
          • 受影響已發布題庫版本: ${imp.affected_set_version_ids.length ? imp.affected_set_version_ids.map(id => `<code>${escapeHtml(id)}</code>`).join(", ") : "無"}<br>
          • 是否直接衝擊線上 Active Manifest: <strong>${imp.has_active_manifest_impact ? "⚠️ 是 (需優先重測)" : "否"}</strong>
        </div>
      `;
    } catch (err) {
      impactResult.innerHTML = `<div class="error">分析失敗: ${escapeHtml(err.message || err)}</div>`;
    }
  });

  // 3. Schedules
  await renderSchedulesSection(box, allowed);
}
