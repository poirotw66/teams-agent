import { api, el, metric } from "../api.js";
import { badge, statusBadge } from "../components/badges.js";
import {
  showContentModal,
  closeContentModal,
  showTextPrompt,
  showToast,
} from "../components/modal.js";
import { buildFaqForm, faqPayload } from "../components/faqForms.js";
import {
  recommendContentType,
  renderContentPolicyBanner,
  renderDecisionGuide,
} from "../components/contentGuide.js";
import { actorCapabilities, getCapabilities } from "../app/capabilities.js";
import { drillLink, navigateTo } from "../app/navigation.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { navigateReturnTo, withReturnTo } from "../app/returnTo.js";
import { formatTaipeiDateTime, labelBehavior, labelStatus } from "../app/labels.js";

function priorityPresentation(priority) {
  const raw = String(priority ?? "").trim();
  const key = raw.toUpperCase();
  const labels = {
    CRITICAL: "緊急",
    HIGH: "高",
    MEDIUM: "中",
    LOW: "低",
  };
  const label = labels[key] || (raw ? `P${raw}` : "未指定");
  const numericHigh = Number.isFinite(Number(raw)) && Number(raw) <= 2;
  return {
    label,
    variant: ["CRITICAL", "HIGH"].includes(key) || numericHigh ? "danger" : "neutral",
    title: raw ? `優先級：${label} (${raw})` : "優先級：未指定",
  };
}

function evaluationBehaviorForCase(caseType) {
  return {
    HANDOFF: "HANDOFF",
    NO_ANSWER: "CLARIFY",
    LOW_CONFIDENCE: "ANSWER_WITH_CITATION",
    NEGATIVE_FEEDBACK: "ANSWER_WITH_CITATION",
    KNOWLEDGE_GAP: "ANSWER_WITH_CITATION",
  }[String(caseType || "").toUpperCase()] || "ANSWER_WITH_CITATION";
}

async function resolveQualityCaseSourceRefs(qualityCase) {
  const refs = [];
  const documentIds = [...new Set((qualityCase.document_ids || []).filter(Boolean))];
  const faqIds = [...new Set((qualityCase.faq_ids || []).filter(Boolean))];

  await Promise.all([
    ...documentIds.map(async (documentId) => {
      const ref = {
        source_type: "DOCUMENT",
        source_id: documentId,
        version_id: null,
        title: documentId,
        resolution_status: "UNRESOLVED",
      };
      try {
        const detail = await api(`/api/knowledge/documents/${encodeURIComponent(documentId)}`);
        const document = detail.document || detail;
        ref.title = document.title || document.document_id || documentId;
        ref.version_id = document.current_published_version_id
          || document.currentPublishedVersionId
          || detail.published_version?.version_id
          || detail.publishedVersion?.version_id
          || null;
        ref.resolution_status = ref.version_id ? "RESOLVED" : "UNRESOLVED";
      } catch {
        ref.resolution_status = "UNAVAILABLE";
      }
      refs.push(ref);
    }),
    ...faqIds.map(async (faqId) => {
      const ref = {
        source_type: "FAQ",
        source_id: faqId,
        version_id: null,
        title: faqId,
        resolution_status: "UNRESOLVED",
      };
      try {
        const detail = await api(`/api/faqs/${encodeURIComponent(faqId)}`);
        const faq = detail.faq || detail;
        const versions = Array.isArray(detail.versions) ? detail.versions : [];
        const published = versions.find((version) =>
          version.version_id === faq.published_version_id
          || ["PUBLISHED", "ACTIVE"].includes(String(version.status || "").toUpperCase()),
        );
        ref.title = faq.title || faq.faq_key || faqId;
        ref.version_id = faq.published_version_id
          || faq.publishedVersionId
          || detail.published_version?.version_id
          || published?.version_id
          || null;
        ref.resolution_status = ref.version_id ? "RESOLVED" : "UNRESOLVED";
      } catch {
        ref.resolution_status = "UNAVAILABLE";
      }
      refs.push(ref);
    }),
  ]);

  return refs.sort((left, right) =>
    `${left.source_type}:${left.source_id}`.localeCompare(`${right.source_type}:${right.source_id}`),
  );
}

function formatQualityCaseSourceRefs(sourceRefs, fallbackVersionId = null) {
  if (sourceRefs.length) {
    return sourceRefs.map((ref) => {
      const version = ref.version_id || "版本未解析";
      const state = ref.resolution_status === "UNAVAILABLE" ? "讀取失敗" : version;
      return `${ref.source_type} ${ref.title || ref.source_id} · ${state}`;
    }).join("；");
  }
  return fallbackVersionId || "建立時未保存來源版本";
}

function renderEvaluationTracking(detail, caseId, qualityCase, allowed, options) {
  const panel = el("section", "case-evaluation-tracking");
  panel.style.padding = "1rem";
  panel.style.marginBottom = "1rem";
  panel.style.border = "1px solid var(--border-subtle)";
  panel.style.borderRadius = "var(--radius-sm)";
  panel.style.background = "var(--panel-muted)";

  const heading = el("h3", "", "驗收追蹤");
  heading.style.marginTop = "0";
  panel.append(heading);

  if (!allowed.has("ops.evals.read")) {
    panel.append(el("p", "metric-label", "目前身分可處理案件，但沒有查看驗收題庫與執行結果的權限。"));
    return panel;
  }

  const candidates = detail.evaluation_candidates || [];
  const runs = detail.evaluation_runs || [];
  const candidateIntro = el(
    "p",
    "metric-label",
    "驗收候選保留本案件來源；只有送審、核准並加入已發布題庫後，執行結果才可用來判斷改善成效。",
  );
  candidateIntro.style.marginTop = "0";
  panel.append(candidateIntro);

  if (candidates.length) {
    const candidateList = el("div", "case-evaluation-list");
    for (const item of candidates) {
      const candidate = item.case || {};
      const revision = item.current_revision || {};
      const sourceRefs = Array.isArray(candidate.metadata?.quality_case_source_refs)
        ? candidate.metadata.quality_case_source_refs
        : [];
      const card = el("div", "card-item");
      card.style.marginBottom = "0.55rem";
      card.append(
        el("strong", "", candidate.title || candidate.case_id || "未命名驗收候選"),
        el(
          "p",
          "metric-label",
          `${labelStatus(revision.status)} · v${revision.revision_number || "—"} · ${labelBehavior(revision.behavior)} · ${candidate.case_id || "—"}`,
        ),
        el(
          "p",
          "metric-label",
          `來源：品質案件 ${caseId} · 關聯來源版本：${formatQualityCaseSourceRefs(
            sourceRefs,
            revision.provenance?.source_version_id,
          )}`,
        ),
      );
      card.append(
        drillLink(
          "查看／送審候選",
          "evaluations",
          withReturnTo(
            { tab: "cases", q: candidate.title || candidate.case_id || "" },
            "quality",
            { caseId, tab: "cases" },
          ),
        ),
      );
      candidateList.append(card);
    }
    panel.append(candidateList);
  } else {
    panel.append(el("p", "empty", "尚未加入驗收候選。"));
  }

  if (runs.length) {
    panel.append(el("h4", "", "最近驗收執行"));
    const runList = el("div", "case-evaluation-list");
    for (const run of runs.slice(0, 5)) {
      const summary = run.summary || {};
      const gate = run.gate_decision;
      const manifestHash = run.candidate_manifest?.manifest_hash || "";
      const passRate = summary.pass_rate == null ? "—" : `${Math.round(summary.pass_rate * 100)}%`;
      const coverage = summary.coverage == null ? "—" : `${Math.round(summary.coverage * 100)}%`;
      const card = el("div", "card-item");
      card.style.marginBottom = "0.55rem";
      const manifestLine = el(
        "p",
        "metric-label",
        `候選版本 ${manifestHash ? `${manifestHash.slice(0, 16)}…` : "—"} · 建立於 ${formatTaipeiDateTime(run.created_at)}`,
      );
      if (manifestHash) {
        manifestLine.title = `完整候選版本雜湊：${manifestHash}`;
        manifestLine.style.overflowWrap = "anywhere";
      }
      card.append(
        el("strong", "", `${labelStatus(run.status)} · ${run.run_id}`),
        el(
          "p",
          "metric-label",
          `品質通過率 ${passRate} · 判定覆蓋率 ${coverage} · 題庫版本 ${run.set_version_id || "—"}`,
        ),
        manifestLine,
        el(
          "p",
          "metric-label",
          gate ? `門檻判定：${gate.decision || "—"}` : "門檻判定：尚未建立（執行完成不等於品質通過）",
        ),
      );
      card.append(
        drillLink(
          "查看驗收結果",
          "evaluations",
          withReturnTo(
            { tab: "results", runId: run.run_id },
            "quality",
            { caseId, tab: "cases" },
          ),
        ),
      );
      runList.append(card);
    }
    panel.append(runList);
  }

  if (allowed.has("ops.evals.write")) {
    const addCandidate = el("button", "button-primary", candidates.length ? "再建立驗收修訂" : "加入驗收候選");
    addCandidate.type = "button";
    addCandidate.addEventListener("click", async () => {
      addCandidate.disabled = true;
      const originalLabel = addCandidate.textContent;
      addCandidate.textContent = "讀取來源版本…";
      try {
        const sourceRefs = await resolveQualityCaseSourceRefs(qualityCase);
        const firstResolvedVersion = sourceRefs.find((ref) => ref.version_id)?.version_id || null;
        const { showCaseCreateModal } = await import("./evaluations.js");
        showCaseCreateModal(
          async () => showQualityCaseDetail(caseId, options),
          {
            title: `改善驗收：${qualityCase.title || caseId}`,
            owner_unit_id: qualityCase.owner_unit_id,
            query: qualityCase.description || qualityCase.title || "",
            behavior: evaluationBehaviorForCase(qualityCase.case_type),
            criticality: qualityCase.priority === "CRITICAL" ? "CRITICAL" : "NORMAL",
            source_type: "QUALITY_CASE",
            source_id: caseId,
            source_version_id: firstResolvedVersion,
            metadata: {
              quality_case_id: caseId,
              quality_case_type: qualityCase.case_type,
              quality_case_source_refs: sourceRefs,
            },
            tags: ["quality-case", qualityCase.case_type].filter(Boolean),
          },
        );
      } finally {
        addCandidate.disabled = false;
        addCandidate.textContent = originalLabel;
      }
    });
    panel.append(addCandidate);
  }

  return panel;
}

async function refreshQuality(state) {
  const { renderQuality } = await import("./quality.js");
  return renderQuality(state);
}


export async function showQualityCaseDetail(caseId, options = {}) {
  const pageMode = Boolean(options.pageMode) || isBuShellEnabled();
  try {
    const detail = await api(`/api/quality-cases/${encodeURIComponent(caseId)}`);
    const qualityCase = detail.case;
    const allowed = actorCapabilities();
    const statusLabels = {
      NEW: "新建",
      TRIAGED: "已分派",
      IN_PROGRESS: "修正中",
      WAITING_REVIEW: "待審核發布",
      OBSERVING: "觀察成效",
      RESOLVED: "已結案",
      WONT_FIX: "不處理",
      DUPLICATE: "重複案件",
    };
    const transitionLabels = {
      TRIAGED: "分派處理",
      IN_PROGRESS: "開始修正知識",
      WAITING_REVIEW: "送審／待發布",
      OBSERVING: "進入觀察",
      RESOLVED: "驗證通過並結案",
      WONT_FIX: "標記不處理",
      DUPLICATE: "標記重複",
    };
    const content = el("div");

    const headerRow = el("div", "meta-panel");
    headerRow.style.justifyContent = "flex-start";
    headerRow.style.marginBottom = "1rem";
    headerRow.style.gap = "0.6rem";
    const statusPill = statusBadge(statusLabels[qualityCase.status] || qualityCase.status);
    const priority = priorityPresentation(qualityCase.priority);
    const prioPill = badge(`優先級 ${priority.label}`, priority.variant);
    prioPill.title = priority.title;
    const caseIdPill = badge(`ID: ${caseId.slice(0, 8)}`, "neutral");
    headerRow.append(statusPill, prioPill, caseIdPill);

    const metricsGrid = el("div", "grid");
    metricsGrid.style.marginBottom = "1rem";
    metricsGrid.append(
      metric("發生頻率", (qualityCase.frequency || 0).toLocaleString()),
      metric("負評率", `${((qualityCase.negative_rate || 0) * 100).toFixed(1)}%`),
      metric("轉人工率", `${((qualityCase.handoff_rate || 0) * 100).toFixed(1)}%`),
      metric(
        "預估成本影響",
        qualityCase.estimated_cost_impact != null
          ? `$${Number(qualityCase.estimated_cost_impact).toFixed(3)}`
          : qualityCase.cost_impact_usd != null
            ? `$${Number(qualityCase.cost_impact_usd).toFixed(3)}`
            : "USD 0.00",
      ),
    );

    const infoPanel = el("div");
    infoPanel.style.padding = "0.85rem 1.1rem";
    infoPanel.style.borderRadius = "var(--radius-sm)";
    infoPanel.style.background = "var(--panel-muted)";
    infoPanel.style.border = "1px solid var(--border-subtle)";
    infoPanel.style.marginBottom = "1rem";

    if (qualityCase.description) {
      const descP = el("p", "", qualityCase.description);
      descP.style.margin = "0 0 0.6rem 0";
      descP.style.fontWeight = "550";
      infoPanel.append(descP);
    }

    const metaGrid = el("div", "filter-bar");
    metaGrid.style.gap = "1.2rem";
    metaGrid.style.fontSize = "0.825rem";
    metaGrid.append(
      el("span", "", `負責單位：${qualityCase.owner_unit_id}`),
      el("span", "", `承辦人：${qualityCase.assignee_id || "未指派"}`),
      el("span", "", `問題類型：${qualityCase.issue_type_display_name || qualityCase.issue_type_id || "未指定"}`),
    );
    infoPanel.append(metaGrid);

    if (allowed.has("ops.quality.write")) {
      const assignment = el("div", "case-assignment-panel");
      assignment.append(
        el("strong", "", "指派承辦人"),
        el("p", "metric-label", "輸入使用者 ID 後儲存；未指派可清空。這只會變更承辦人，不會自動改變案件狀態。"),
      );
      const assignmentRow = el("div", "filter-bar");
      const assigneeInput = el("input", "input");
      assigneeInput.type = "text";
      assigneeInput.placeholder = "例如 ops.knowledge";
      assigneeInput.value = qualityCase.assignee_id || "";
      assigneeInput.setAttribute("aria-label", "案件承辦人使用者 ID");
      const assigneeOptions = el("datalist");
      assigneeOptions.id = `quality-assignee-options-${String(caseId).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
      const actorIds = new Set([
        qualityCase.assignee_id,
        getCapabilities()?.userId,
        ...(detail.audit || []).map((event) => event.actor_id),
      ].filter(Boolean));
      for (const actorId of actorIds) {
        const option = el("option");
        option.value = actorId;
        assigneeOptions.append(option);
      }
      assigneeInput.setAttribute("list", assigneeOptions.id);
      const assignButton = el("button", "button-secondary", "儲存指派");
      assignButton.type = "button";
      const assignmentStatus = el("span", "metric-label", "");
      assignButton.addEventListener("click", async () => {
        assignButton.disabled = true;
        assignmentStatus.textContent = "儲存中…";
        try {
          await api(`/api/quality-cases/${encodeURIComponent(caseId)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_etag: qualityCase.etag,
              title: qualityCase.title,
              description: qualityCase.description,
              priority: qualityCase.priority,
              assignee_id: assigneeInput.value.trim() || null,
              target_due_at: qualityCase.target_due_at || null,
            }),
          });
          await showQualityCaseDetail(caseId, options);
        } catch (error) {
          assignmentStatus.textContent = `指派失敗：${error.message || error}`;
          assignButton.disabled = false;
        }
      });
      assignmentRow.append(assigneeInput, assigneeOptions, assignButton, assignmentStatus);
      assignment.append(assignmentRow);
      infoPanel.append(assignment);
    }

    const relBox = el("div", "filter-bar");
    relBox.style.marginTop = "0.5rem";
    relBox.style.gap = "0.5rem";
    relBox.append(el("span", "metric-label", "關聯 FAQ:"));
    if (qualityCase.faq_ids && qualityCase.faq_ids.length) {
      for (const fid of qualityCase.faq_ids) {
        relBox.append(badge(fid, "neutral"));
      }
    } else {
      relBox.append(el("span", "muted", "無"));
    }

    relBox.append(el("span", "metric-label", "關聯文件:"));
    if (qualityCase.document_ids && qualityCase.document_ids.length) {
      for (const did of qualityCase.document_ids) {
        relBox.append(badge(did, "accent"));
      }
    } else {
      relBox.append(el("span", "muted", "無"));
    }
    infoPanel.append(relBox);

    const returnCtx = { caseId, tab: "cases" };
    const loopHints = el("div", "filter-bar");
    loopHints.style.marginBottom = "1rem";
    loopHints.append(
      el("span", "metric-label", "閉環捷徑："),
      drillLink(
        "修正文件",
        "contentLists",
        withReturnTo({ tab: "documents" }, "quality", returnCtx),
      ),
      drillLink(
        "修正 FAQ",
        "contentLists",
        withReturnTo({ tab: "faq" }, "quality", returnCtx),
      ),
      drillLink("案例驗證", "examples", withReturnTo({}, "quality", returnCtx)),
      drillLink(
        "對話驗證",
        "conversations",
        withReturnTo(
          { issueTypeId: qualityCase.issue_type_id || "" },
          "quality",
          returnCtx,
        ),
      ),
      drillLink(
        "Golden 驗收",
        "evaluations",
        withReturnTo({ tab: "runs" }, "quality", returnCtx),
      ),
    );
    if (getCapabilities()?.knowledgeBridgeEnabled) {
      for (const documentId of qualityCase.document_ids || []) {
        loopHints.append(
          drillLink(
            "開啟關聯文件",
            "knowledgePortal",
            withReturnTo(
              {
                k: `/knowledge/${documentId}?caseId=${encodeURIComponent(caseId)}`,
              },
              "quality",
              returnCtx,
            ),
          ),
        );
      }
      loopHints.append(
        drillLink(
          "知識文件庫",
          "contentLists",
          withReturnTo({ tab: "documents" }, "quality", returnCtx),
        ),
      );
    } else if (getCapabilities()?.knowledgePortalUrl) {
      const portal = el("a", "drill-link", "開啟知識入口");
      portal.href = getCapabilities().knowledgePortalUrl;
      portal.target = "_blank";
      portal.rel = "noopener noreferrer";
      loopHints.append(portal);
    }
    content.append(headerRow, metricsGrid, infoPanel);
    if (pageMode) {
      const saveNote = el(
        "div",
        "callout bu-case-save-note",
        "提醒：在文件／FAQ 儲存草稿或發布，不會自動把本案件標成「已結案」。改善完成需在本頁把狀態轉為「已結案」（或「不修復／重複」），並完成必要驗證。",
      );
      saveNote.style.marginBottom = "0.85rem";
      content.append(saveNote);
    }
    content.append(loopHints, renderEvaluationTracking(detail, caseId, qualityCase, allowed, options));
    content.append(
      renderContentPolicyBanner(),
      renderDecisionGuide({ recommended: recommendContentType(qualityCase) }),
    );
    const transitions = {
      NEW: ["TRIAGED", "WONT_FIX", "DUPLICATE"],
      TRIAGED: ["IN_PROGRESS", "WONT_FIX", "DUPLICATE"],
      IN_PROGRESS: ["WAITING_REVIEW", "OBSERVING", "WONT_FIX", "DUPLICATE"],
      WAITING_REVIEW: ["IN_PROGRESS", "OBSERVING", "WONT_FIX"],
      OBSERVING: ["IN_PROGRESS", "RESOLVED", "WONT_FIX"],
    };
    const actions = el("div", "filter-bar");
    if (allowed.has("ops.quality.write")) {
      const linkFaq = el("button", "", "連結既有 FAQ");
      linkFaq.addEventListener("click", async () => {
        let faqs = [];
        try {
          const listRes = await api("/api/faqs");
          faqs = listRes.items || [];
        } catch {
          faqs = [];
        }
        const modalBody = el("div");
        const faqSelect = document.createElement("select");
        faqSelect.className = "input";
        faqSelect.style.width = "100%";
        faqSelect.style.marginBottom = "0.75rem";

        const defaultOpt = document.createElement("option");
        defaultOpt.value = "";
        defaultOpt.textContent = "-- 請選擇既有 FAQ（或於下方手動輸入 ID）--";
        faqSelect.append(defaultOpt);

        for (const item of faqs) {
          const opt = document.createElement("option");
          const f = item.faq || item;
          const v = item.version || {};
          const fId = f.faq_id;
          const qText = v.content?.question || f.title || fId;
          opt.value = fId;
          opt.textContent = `${qText} (${fId}｜${f.status || "草稿"})`;
          faqSelect.append(opt);
        }
        const idInput = el("input", "input");
        idInput.type = "text";
        idInput.placeholder = "輸入 FAQ ID (例如 faq-xxx)";
        idInput.style.width = "100%";
        idInput.style.marginBottom = "1rem";

        faqSelect.addEventListener("change", () => {
          if (faqSelect.value) idInput.value = faqSelect.value;
        });

        const confirmBtn = el("button", "button-primary", "確認關聯 FAQ");
        confirmBtn.addEventListener("click", async () => {
          const fId = idInput.value.trim();
          if (!fId) {
            showToast("請選擇或輸入 FAQ ID", { tone: "error" });
            idInput.focus();
            return;
          }
          try {
            confirmBtn.disabled = true;
            await api(`/api/quality-cases/${caseId}/content`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_etag: qualityCase.etag, faq_id: fId }),
            });
            closeContentModal();
            await showQualityCaseDetail(caseId);
          } catch (err) {
            confirmBtn.disabled = false;
            showToast(`關聯失敗：${err.message || err}`, { tone: "error" });
          }
        });

        modalBody.append(
          el("p", "", "選擇或輸入要關聯至此品質案件的 FAQ："),
          faqSelect,
          idInput,
          confirmBtn,
        );
        showContentModal("關聯既有 FAQ", modalBody);
      });
      actions.append(linkFaq);

      const linkDoc = el("button", "", "連結既有文件");
      linkDoc.addEventListener("click", async () => {
        let docs = [];
        if (getCapabilities()?.knowledgeBridgeEnabled) {
          try {
            const listRes = await api("/api/knowledge/documents");
            docs = listRes.items || listRes.documents || [];
          } catch {
            docs = [];
          }
        }
        const modalBody = el("div");
        const docSelect = document.createElement("select");
        docSelect.className = "input";
        docSelect.style.width = "100%";
        docSelect.style.marginBottom = "0.75rem";

        const defaultOpt = document.createElement("option");
        defaultOpt.value = "";
        defaultOpt.textContent = "-- 請選擇既有文件（或於下方手動輸入 ID）--";
        docSelect.append(defaultOpt);

        for (const doc of docs) {
          const opt = document.createElement("option");
          const dId = doc.document_id || doc.documentId;
          opt.value = dId;
          opt.textContent = `${doc.title} (${dId}｜${doc.status || "草稿"})`;
          docSelect.append(opt);
        }
        const idInput = el("input", "input");
        idInput.type = "text";
        idInput.placeholder = "輸入文件 ID (例如 doc-xxx)";
        idInput.style.width = "100%";
        idInput.style.marginBottom = "1rem";

        docSelect.addEventListener("change", () => {
          if (docSelect.value) idInput.value = docSelect.value;
        });

        const confirmBtn = el("button", "button-primary", "確認關聯文件");
        confirmBtn.addEventListener("click", async () => {
          const docId = idInput.value.trim();
          if (!docId) {
            showToast("請選擇或輸入文件 ID", { tone: "error" });
            idInput.focus();
            return;
          }
          try {
            await api(`/api/quality-cases/${caseId}/content`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_etag: qualityCase.etag, document_id: docId }),
            });
            closeContentModal();
            await showQualityCaseDetail(caseId);
          } catch (err) {
            showToast(`關聯失敗：${err.message || err}`, { tone: "error" });
          }
        });

        modalBody.append(
          el("p", "", "選擇或輸入要關聯至此品質案件的知識文件："),
          docSelect,
          idInput,
          confirmBtn,
        );
        showContentModal("關聯既有知識文件", modalBody);
      });
      actions.append(linkDoc);

      if (
        getCapabilities()?.knowledgeBridgeEnabled &&
        (getCapabilities()?.knowledgeCapabilities || []).includes("knowledge.create")
      ) {
        const draftDoc = el("button", "", "建立文件草稿");
        draftDoc.addEventListener("click", () => {
          const form = document.createElement("form");
          form.className = "form-grid";

          const titleInput = el("input", "input");
          titleInput.value = qualityCase.title || "";
          titleInput.required = true;
          titleInput.style.width = "100%";

          const ownerDisplay = el("input", "input");
          ownerDisplay.value = qualityCase.owner_unit_id || "";
          ownerDisplay.disabled = true;
          ownerDisplay.style.width = "100%";

          const contactInput = el("input", "input");
          contactInput.value = getCapabilities()?.userId || "IT Service Desk";
          contactInput.style.width = "100%";

          const summaryInput = el("input", "input");
          summaryInput.value = `由品質案件 ${caseId} 建立之改善文件草稿。`;
          summaryInput.style.width = "100%";

          const contentArea = document.createElement("textarea");
          contentArea.className = "input";
          contentArea.rows = 8;
          contentArea.style.width = "100%";
          contentArea.value = `# ${qualityCase.title || "知識文件草稿"}\n\n## 適用問題背景\n\n${qualityCase.description || ""}\n\n## 處理指引步驟\n\n1. 確認系統設定。\n2. 重設並驗證連線狀態。\n`;

          form.append(
            el("label", "form-label", "文件標題："),
            titleInput,
            el("label", "form-label", "負責單位："),
            ownerDisplay,
            el("label", "form-label", "業務聯絡人："),
            contactInput,
            el("label", "form-label", "文件摘要："),
            summaryInput,
            el("label", "form-label", "內容正文草稿（Markdown）："),
            contentArea,
          );

          const submitBtn = el("button", "button-primary", "建立並連結草稿");
          submitBtn.type = "submit";
          submitBtn.style.marginTop = "0.75rem";
          form.append(submitBtn);

          form.addEventListener("submit", async (e) => {
            e.preventDefault();
            submitBtn.disabled = true;
            submitBtn.textContent = "建立中...";
            try {
              const res = await api(`/api/quality-cases/${caseId}/document-draft`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  expected_case_etag: qualityCase.etag,
                  title: titleInput.value.trim(),
                  summary: summaryInput.value.trim(),
                  business_contact: contactInput.value.trim(),
                  markdown_content: contentArea.value,
                }),
              });
              closeContentModal();
              const createdDocId = res.document?.document_id || "";
              if (res.partialSuccess) {
                showContentModal(
                  "部分成功注意",
                  el("div", "warning", res.message || "文件建立成功但關聯失敗。"),
                );
              } else {
                const promptBox = el("div");
                promptBox.append(
                  el("p", "", `已成功建立文件草稿並關聯至案件（文件 ID：${createdDocId}）！`),
                );
                const goEdit = el("button", "button-primary", "前往編輯草稿");
                goEdit.addEventListener("click", () => {
                  closeContentModal();
                  navigateTo(
                    "knowledgePortal",
                    withReturnTo(
                      {
                        k: `/knowledge/${createdDocId}?caseId=${encodeURIComponent(caseId)}`,
                      },
                      "quality",
                      { caseId, tab: "cases" },
                    ),
                  );
                });
                promptBox.append(goEdit);
                showContentModal("草稿建立成功", promptBox);
              }
              await showQualityCaseDetail(caseId);
            } catch (err) {
              submitBtn.disabled = false;
              submitBtn.textContent = "建立並連結草稿";
              showToast(`建立草稿失敗：${err.message || err}`, { tone: "error" });
            }
          });

          showContentModal("由品質案件建立知識文件草稿", form);
        });
        actions.append(draftDoc);
      }
      if (allowed.has("ops.faq.write") && qualityCase.issue_type_id) {
        const draftFaq = el("button", "", "建立 FAQ 草稿");
        draftFaq.addEventListener("click", () => {
          const form = buildFaqForm({
            owner_unit_id: qualityCase.owner_unit_id,
            issue_type_ids: [qualityCase.issue_type_id],
            question: qualityCase.description || qualityCase.title || "",
          });
          const submit = el("button", "button-primary", "建立並連結草稿");
          submit.type = "submit";
          form.append(submit);
          form.addEventListener("submit", async (event) => {
            event.preventDefault();
            submit.disabled = true;
            submit.textContent = "建立中…";
            try {
              const payload = faqPayload(form);
              await api(`/api/quality-cases/${caseId}/faq-draft`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  expected_case_etag: qualityCase.etag,
                  faq_key: payload.faq_key,
                  question: payload.question,
                  answer: payload.answer,
                  category: payload.category,
                  keywords: payload.keywords,
                  business_contact: payload.business_contact,
                  audience_type: payload.audience_type,
                  audience_group_ids: payload.audience_group_ids,
                }),
              });
              closeContentModal();
              await showQualityCaseDetail(caseId);
            } catch (err) {
              submit.disabled = false;
              submit.textContent = "建立並連結草稿";
              showToast(`建立草稿失敗：${err.message || err}`, { tone: "error" });
            }
          });
          showContentModal("由品質案件建立 FAQ 草稿", form);
        });
        actions.append(draftFaq);
      }
      if (qualityCase.status === "OBSERVING") {
        const refresh = el("button", "", "刷新觀察指標");
        refresh.addEventListener("click", async () => {
          await api(`/api/quality-cases/${caseId}/observation/refresh`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ expected_etag: qualityCase.etag }),
          });
          await showQualityCaseDetail(caseId);
        });
        actions.append(refresh);
      }
    }
    for (const status of transitions[qualityCase.status] || []) {
      const terminal = ["RESOLVED", "WONT_FIX", "DUPLICATE"].includes(status);
      const capability = terminal ? "ops.quality.resolve" : "ops.quality.write";
      if (!allowed.has(capability)) continue;
      const button = el("button", "", transitionLabels[status] || status);
      button.addEventListener("click", async () => {
        const reason = await showTextPrompt({
          title: `案件狀態轉換：${transitionLabels[status] || status}`,
          message: terminal
            ? "請輸入狀態轉換原因（至少 3 個字元）。"
            : "可選填狀態轉換原因。",
          minLength: terminal ? 3 : 0,
          required: terminal,
        });
        if (reason == null) return;
        try {
          await api(`/api/quality-cases/${caseId}/transition`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              expected_etag: qualityCase.etag,
              status,
              reason: reason?.trim() || null,
              resolution_type: terminal ? "MANUAL_REVIEW" : null,
            }),
          });
          await refreshQuality();
          await showQualityCaseDetail(caseId);
        } catch (error) {
          showContentModal("品質案件操作失敗", el("div", "error", error.message));
        }
      });
      actions.append(button);
    }
    if (qualityCase.observation_baseline) {
      content.append(
        el("h3", "", "觀察指標"),
        el("pre", "json-block", JSON.stringify({
          baseline: qualityCase.observation_baseline,
          latest: qualityCase.observation_latest,
        }, null, 2)),
      );
    }
    content.append(actions, el("h3", "", `操作紀錄（${detail.audit.length}）`));
    if (detail.audit.length) {
      const aTable = el("table");
      aTable.innerHTML = "<thead><tr><th>時間</th><th>操作</th><th>執行人員</th></tr></thead>";
      const aBody = el("tbody");
      for (const event of detail.audit) {
        const row = el("tr");
        const occurred = (event.occurred_at || "").replace("T", " ").slice(0, 19);
        const actCell = el("td");
        actCell.append(statusBadge(event.action));
        row.append(
          el("td", "", occurred),
          actCell,
          el("td", "", event.actor_id || "-"),
        );
        aBody.append(row);
      }
      aTable.append(aBody);
      const aScroll = el("div", "table-responsive");
      aScroll.append(aTable);
      content.append(aScroll);
    } else {
      content.append(el("p", "empty", "尚無操作紀錄"));
    }
    if (pageMode) {
      const app = document.getElementById("app");
      const page = el("div", "bu-case-page");
      const crumb = el("div", "bu-case-crumb");
      const back = el("a", "", "← 返回");
      back.href = "#";
      back.addEventListener("click", (event) => {
        event.preventDefault();
        navigateReturnTo("quality", {});
      });
      crumb.append(back, document.createTextNode(" / "), document.createTextNode(qualityCase.title || caseId));
      const layout = el("div", "bu-case-layout");
      const main = el("section", "bu-case-main");
      while (content.firstChild) {
        main.append(content.firstChild);
      }
      const side = el("aside", "bu-case-side");
      side.append(
        el("h3", "", "處理進度"),
        el("p", "metric-label", `狀態：${statusLabels[qualityCase.status] || qualityCase.status}`),
        el("p", "metric-label", `負責人：${qualityCase.owner_unit_id || "未指派"}`),
        el("p", "metric-label", `承辦：${qualityCase.assignee_id || "未指派"}`),
      );
      layout.append(main, side);
      page.append(crumb, el("h2", "", qualityCase.title || "改善案件"), layout);
      app.replaceChildren(page);
      return;
    }
    showContentModal(qualityCase.title, content);
  } catch (error) {
    if (pageMode) {
      document.getElementById("app")?.replaceChildren(el("div", "error", error.message));
      return;
    }
    showContentModal("品質案件", el("div", "error", error.message));
  }
}
