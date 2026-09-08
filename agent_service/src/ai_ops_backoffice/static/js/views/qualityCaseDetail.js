import { api, el, metric } from "../api.js";
import { badge, statusBadge } from "../components/badges.js";
import { showContentModal } from "../components/modal.js";
import { buildFaqForm, faqPayload } from "../components/faqForms.js";
import { actorCapabilities, getCapabilities } from "../app/capabilities.js";
import { drillLink, navigateTo } from "../app/navigation.js";
async function refreshQuality(state) {
  const { renderQuality } = await import("./quality.js");
  return renderQuality(state);
}


export async function showQualityCaseDetail(caseId) {
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
    const prioPill = badge(`優先級 P${qualityCase.priority}`, qualityCase.priority <= 2 ? "danger" : "neutral");
    const caseIdPill = badge(`ID: ${caseId.slice(0, 8)}`, "neutral");
    headerRow.append(statusPill, prioPill, caseIdPill);

    const metricsGrid = el("div", "grid");
    metricsGrid.style.marginBottom = "1rem";
    metricsGrid.append(
      metric("發生頻率", (qualityCase.frequency || 0).toLocaleString()),
      metric("負評率", `${((qualityCase.negative_rate || 0) * 100).toFixed(1)}%`),
      metric("轉人工率", `${((qualityCase.handoff_rate || 0) * 100).toFixed(1)}%`),
      metric("預估成本影響", qualityCase.cost_impact_usd != null ? `$${Number(qualityCase.cost_impact_usd).toFixed(3)}` : "USD 0.00"),
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

    const loopHints = el("div", "filter-bar");
    loopHints.style.marginBottom = "1rem";
    loopHints.append(
      el("span", "metric-label", "閉環捷徑："),
      drillLink("修正文件", "knowledgePortal"),
      drillLink("修正 FAQ", "faq"),
      drillLink("案例驗證", "examples"),
      drillLink("對話驗證", "conversations", {
        issueTypeId: qualityCase.issue_type_id || "",
      }),
    );
    if (getCapabilities()?.knowledgeBridgeEnabled) {
      for (const documentId of qualityCase.document_ids || []) {
        loopHints.append(
          drillLink("開啟關聯文件", "knowledgePortal", {
            k: `/knowledge/${documentId}?caseId=${encodeURIComponent(caseId)}`,
          }),
        );
      }
      loopHints.append(drillLink("知識文件庫", "knowledgePortal"));
    } else if (getCapabilities()?.knowledgePortalUrl) {
      const portal = el("a", "drill-link", "開啟知識入口");
      portal.href = getCapabilities().knowledgePortalUrl;
      portal.target = "_blank";
      portal.rel = "noopener noreferrer";
      loopHints.append(portal);
    }
    content.append(headerRow, metricsGrid, infoPanel, loopHints);
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
        const faqId = window.prompt("請輸入 FAQ ID");
        if (!faqId?.trim()) return;
        await api(`/api/quality-cases/${caseId}/content`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_etag: qualityCase.etag, faq_id: faqId.trim() }),
        });
        await showQualityCaseDetail(caseId);
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

        const confirmBtn = el("button", "btn primary", "確認關聯文件");
        confirmBtn.addEventListener("click", async () => {
          const docId = idInput.value.trim();
          if (!docId) {
            alert("請選擇或輸入文件 ID");
            return;
          }
          try {
            await api(`/api/quality-cases/${caseId}/content`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ expected_etag: qualityCase.etag, document_id: docId }),
            });
            const root = document.getElementById("modal-root");
            if (root) { root.hidden = true; root.replaceChildren(); }
            await showQualityCaseDetail(caseId);
          } catch (err) {
            alert(`關聯失敗：${err.message || err}`);
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

          const submitBtn = el("button", "btn primary", "建立並連結草稿");
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
              const root = document.getElementById("modal-root");
              if (root) { root.hidden = true; root.replaceChildren(); }
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
                const goEdit = el("button", "btn primary", "前往編輯草稿");
                goEdit.addEventListener("click", () => {
                  if (root) { root.hidden = true; root.replaceChildren(); }
                  navigateTo("knowledgePortal", {
                    k: `/knowledge/${createdDocId}?caseId=${encodeURIComponent(caseId)}`,
                  });
                });
                promptBox.append(goEdit);
                showContentModal("草稿建立成功", promptBox);
              }
              await showQualityCaseDetail(caseId);
            } catch (err) {
              submitBtn.disabled = false;
              submitBtn.textContent = "建立並連結草稿";
              alert(`建立草稿失敗：${err.message || err}`);
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
          });
          const submit = el("button", "", "建立並連結草稿");
          submit.type = "submit";
          form.append(submit);
          form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const payload = faqPayload(form);
            await api(`/api/quality-cases/${caseId}/faq-draft`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                expected_case_etag: qualityCase.etag,
                faq_key: payload.faq_key, question: payload.question, answer: payload.answer,
                category: payload.category, keywords: payload.keywords,
                business_contact: payload.business_contact,
                audience_type: payload.audience_type,
                audience_group_ids: payload.audience_group_ids,
              }),
            });
            await refreshQuality();
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
        const reason = window.prompt(
          `請輸入轉為「${transitionLabels[status] || status}」的原因`,
        );
        if (terminal && !reason?.trim()) return;
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
    showContentModal(qualityCase.title, content);
  } catch (error) {
    showContentModal("品質案件", el("div", "error", error.message));
  }
}
