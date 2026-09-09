import { api, el } from "../api.js";
import { formatCount, formatPercent, routeBadge } from "./analyticsUi.js";
import { attributionCell } from "./badges.js";
import { showConversationModal } from "./conversationModal.js";
import { navigateTo } from "../app/navigation.js";
import { periodParams } from "./period.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { withReturnTo } from "../app/returnTo.js";

function periodToNavFilters(period) {
  if (period?.preset === "custom") {
    return { preset: "custom", start: period.start || "", end: period.end || "" };
  }
  return { preset: period?.preset || "30d" };
}

function periodLabel(period) {
  if (period?.preset === "today") return "今天";
  if (period?.preset === "1d") return "最近 1 日";
  if (period?.preset === "7d") return "最近 1 週";
  if (period?.preset === "30d") return "最近 30 天";
  if (period?.preset === "month") return "本月";
  if (period?.preset === "6m") return "最近 6 個月";
  if (period?.preset === "1y") return "最近 1 年";
  if (period?.preset === "custom") {
    return `${period.start || "起"} 至 ${period.end || "迄"}`;
  }
  return period?.preset || "30d";
}

function closeIssueModalRoot() {
  const root = document.getElementById("modal-root");
  if (!root) return;
  root.hidden = true;
  root.replaceChildren();
}

export async function showIssueDetailModal(issueTypeId, period = { preset: "30d" }) {
  const periodFilters = periodToNavFilters(period);
  // BU shell: reuse the full-page issueType drill (renderIssueRouteDrill), not a second modal UI.
  if (isBuShellEnabled()) {
    await navigateTo("issues", { issueTypeId, ...periodFilters });
    return;
  }

  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();

  root.onclick = (e) => {
    if (e.target === root) {
      closeIssueModalRoot();
    }
  };

  const modal = el("section", "modal");
  modal.style.maxWidth = "860px";
  modal.style.width = "95%";
  modal.style.maxHeight = "90vh";
  modal.style.overflowY = "auto";

  const header = el("div", "modal-header");
  header.style.display = "flex";
  header.style.justifyContent = "space-between";
  header.style.alignItems = "flex-start";
  header.style.marginBottom = "1rem";
  header.style.paddingBottom = "0.75rem";
  header.style.borderBottom = "1px solid var(--border-subtle, #e2e8f0)";

  const titleWrap = el("div");
  const heading = el("h2", "", "載入問題分析詳情…");
  heading.style.margin = "0 0 0.25rem 0";
  titleWrap.append(heading);

  const close = el("button", "btn-modal-close", "✕ 關閉");
  close.addEventListener("click", () => closeIssueModalRoot());
  header.append(titleWrap, close);

  const body = el("div", "modal-body");
  body.append(el("p", "empty", "正在分析此問題之處理分流、回答依據與負評反饋…"));
  modal.append(header, body);
  root.append(modal);

  try {
    const params = periodParams(period);
    const data = await api(`/api/issues/${encodeURIComponent(issueTypeId)}/routes?${params.toString()}`);

    heading.textContent = `🏷️ ${data.displayName || issueTypeId}`;
    titleWrap.replaceChildren(heading);

    const metaRow = el("div", "filter-bar");
    metaRow.style.marginTop = "0.25rem";
    metaRow.style.gap = "0.5rem";

    const idBadge = el("span", "badge badge-neutral", `代碼：${data.issueTypeId}`);
    const unitBadge = el(
      "span",
      "badge badge-accent",
      `權責單位：${data.ownerUnitId || "未指定 / 跨單位"}`,
    );
    const timeBadge = el("span", "badge badge-neutral", `期間：${periodLabel(period)}`);
    metaRow.append(idBadge, unitBadge, timeBadge);
    titleWrap.append(metaRow);

    if (data.description) {
      const descPara = el("p", "metric-label", `說明：${data.description}`);
      descPara.style.margin = "0.35rem 0 0 0";
      titleWrap.append(descPara);
    }

    body.replaceChildren();

    // 1. KPI Cards Strip
    const kpiWrap = el("div", "kpi-strip");
    kpiWrap.style.display = "grid";
    kpiWrap.style.gridTemplateColumns = "repeat(auto-fit, minmax(160px, 1fr))";
    kpiWrap.style.gap = "0.75rem";
    kpiWrap.style.marginBottom = "1.25rem";

    const makeCard = (label, value, subtext = "", isWarn = false) => {
      const card = el("div", "kpi-card");
      card.style.padding = "0.75rem 1rem";
      card.style.background = isWarn ? "var(--bg-warning-subtle, #fffbeb)" : "var(--bg-card, #ffffff)";
      card.style.border = isWarn ? "1px solid var(--border-warning, #fef3c7)" : "1px solid var(--border-subtle, #e2e8f0)";
      card.style.borderRadius = "8px";

      const lbl = el("div", "kpi-label", label);
      lbl.style.fontSize = "0.825rem";
      lbl.style.color = "var(--text-muted, #64748b)";
      const val = el("div", "kpi-value", value);
      val.style.fontSize = "1.35rem";
      val.style.fontWeight = "700";
      val.style.color = isWarn ? "var(--text-danger, #dc2626)" : "var(--text-primary, #0f172a)";
      card.append(lbl, val);
      if (subtext) {
        const sub = el("div", "metric-label", subtext);
        sub.style.fontSize = "0.75rem";
        sub.style.marginTop = "0.2rem";
        card.append(sub);
      }
      return card;
    };

    const totalCount = data.totalCount || 0;
    const negCount = data.negativeFeedbackCount || 0;
    const handoffCount = data.handoffCount || 0;
    const noAnsCount = data.noAnswerCount || 0;

    const negRate = totalCount > 0 ? formatPercent(negCount / totalCount) : "0%";
    const handoffRate = totalCount > 0 ? formatPercent(handoffCount / totalCount) : "0%";

    kpiWrap.append(
      makeCard("出現次數", `${formatCount(totalCount)} 次`, "問題擷取事件數"),
      makeCard(
        "負評次數",
        negCount > 0 ? `${formatCount(negCount)} 筆` : "尚無負評",
        negCount > 0 ? `負評率 ${negRate}` : "無負面意見",
        negCount > 0,
      ),
      makeCard(
        "轉人工客服",
        `${formatCount(handoffCount)} 筆`,
        `轉人工率 ${handoffRate}`,
        handoffCount > 0,
      ),
      makeCard("未能回答", `${formatCount(noAnsCount)} 筆`, "無答案或處置失敗", noAnsCount > 0),
    );
    body.append(kpiWrap);

    // 2. Section: 處理方式 (Route Distribution)
    const secRoutes = el("section", "analytics-section");
    secRoutes.style.marginBottom = "1.5rem";
    const routeTitle = el("div", "analytics-section-title");
    routeTitle.append(
      el("h3", "", "處理方式（AI 處置分流分布）"),
      el("span", "metric-label", "AI 如何處理此問題：FAQ、知識檢索 HYBRID、轉真人客服 HANDOFF 等"),
    );
    secRoutes.append(routeTitle);

    const routes = data.routes || [];
    if (!routes.length) {
      secRoutes.append(el("p", "empty", "選定期間內尚無分流紀錄。"));
    } else {
      const routeTable = el("table");
      routeTable.innerHTML = `
        <thead>
          <tr>
            <th>處理方式 (Route)</th>
            <th>次數</th>
            <th>佔比</th>
            <th>回答依據（FAQ／知識庫文件）</th>
          </tr>
        </thead>
      `;
      const tbody = el("tbody");
      for (const rt of routes) {
        const row = el("tr");
        const rtCell = el("td");
        rtCell.append(routeBadge(rt.route));
        row.append(rtCell);
        row.append(el("td", "", formatCount(rt.count)));
        const sharePct = totalCount > 0 ? formatPercent(rt.count / totalCount) : "-";
        row.append(el("td", "", sharePct));
        row.append(attributionCell(rt.attribution, { issueTypeId: data.issueTypeId }));
        tbody.append(row);
      }
      routeTable.append(tbody);
      const wrap = el("div", "table-responsive");
      wrap.append(routeTable);
      secRoutes.append(wrap);
    }
    body.append(secRoutes);

    // 3. Section: 回答依據與來源清單 (Attribution & Knowledge Sources)
    const secSources = el("section", "analytics-section");
    secSources.style.marginBottom = "1.5rem";
    const srcTitle = el("div", "analytics-section-title");
    srcTitle.append(
      el("h3", "", "回答依據與知識文件（改善入口）"),
      el("span", "metric-label", "AI 回答此問題時引用的知識庫文件或 FAQ 項目，可快速檢視或修訂"),
    );
    secSources.append(srcTitle);

    // Aggregate sources across all routes
    const allDocIds = new Set();
    const allSourcePaths = new Set();
    const allFaqKeys = new Set();
    for (const rt of routes) {
      const attr = rt.attribution || {};
      (attr.documentIds || []).forEach((item) => item.id && allDocIds.add(item.id));
      (attr.sourcePaths || []).forEach((item) => item.id && allSourcePaths.add(item.id));
      (attr.faqKeys || []).forEach((item) => item.id && allFaqKeys.add(item.id));
    }

    const sourcesBox = el("div");
    sourcesBox.style.padding = "0.75rem 1rem";
    sourcesBox.style.background = "var(--bg-subtle, #f8fafc)";
    sourcesBox.style.border = "1px solid var(--border-subtle, #e2e8f0)";
    sourcesBox.style.borderRadius = "8px";

    if (!allDocIds.size && !allSourcePaths.size && !allFaqKeys.size) {
      sourcesBox.append(el("p", "empty", "未引用具體文件或 FAQ（可能多由對話模型直接回覆或直接轉人工）。"));
    } else {
      if (allSourcePaths.size || allDocIds.size) {
        const docGroup = el("div");
        docGroup.style.marginBottom = "0.75rem";
        const docHeading = el("div", "", "📚 引用的知識庫文件：");
        docHeading.style.fontWeight = "600";
        docHeading.style.marginBottom = "0.35rem";
        docGroup.append(docHeading);

        const list = el("ul");
        list.style.margin = "0";
        list.style.paddingLeft = "1.25rem";

        const combinedDocs = Array.from(allSourcePaths.size ? allSourcePaths : allDocIds);
        for (const doc of combinedDocs) {
          const li = el("li");
          li.style.marginBottom = "0.35rem";
          li.append(el("span", "analytics-mono", doc));
          li.append(document.createTextNode(" "));

          const actionBtn = el("button", "btn-secondary btn-small", "📄 前往知識庫檢視／修訂");
          actionBtn.style.fontSize = "0.75rem";
          actionBtn.style.padding = "0.15rem 0.5rem";
          actionBtn.style.marginLeft = "0.5rem";
          actionBtn.addEventListener("click", () => {
            root.hidden = true;
            root.replaceChildren();
            navigateTo("knowledge", { query: doc });
          });
          li.append(actionBtn);
          list.append(li);
        }
        docGroup.append(list);
        sourcesBox.append(docGroup);
      }

      if (allFaqKeys.size) {
        const faqGroup = el("div");
        const faqHeading = el("div", "", "❓ 引用的 FAQ 項目：");
        faqHeading.style.fontWeight = "600";
        faqHeading.style.marginBottom = "0.35rem";
        faqGroup.append(faqHeading);

        const list = el("ul");
        list.style.margin = "0";
        list.style.paddingLeft = "1.25rem";
        for (const key of allFaqKeys) {
          const li = el("li");
          li.style.marginBottom = "0.35rem";
          li.append(el("span", "analytics-mono", key));
          li.append(document.createTextNode(" "));

          const actionBtn = el("button", "btn-secondary btn-small", "❓ 前往 FAQ 編輯");
          actionBtn.style.fontSize = "0.75rem";
          actionBtn.style.padding = "0.15rem 0.5rem";
          actionBtn.style.marginLeft = "0.5rem";
          actionBtn.addEventListener("click", () => {
            root.hidden = true;
            root.replaceChildren();
            navigateTo("faq", { query: key });
          });
          li.append(actionBtn);
          list.append(li);
        }
        faqGroup.append(list);
        sourcesBox.append(faqGroup);
      }
    }
    secSources.append(sourcesBox);
    body.append(secSources);

    // 4. Section: 負評紀錄 (Negative Feedback Records)
    const secFeedback = el("section", "analytics-section");
    secFeedback.style.marginBottom = "1.5rem";
    const fbTitle = el("div", "analytics-section-title");
    fbTitle.append(
      el("h3", "", `使用者負評紀錄 (${negCount} 筆)`),
      el("span", "metric-label", "查看使用者對此問題回答的不滿原因與上下文，協助確認需補充之知識"),
    );
    secFeedback.append(fbTitle);

    const feedbacks = data.negativeFeedbacks || [];
    if (!feedbacks.length) {
      secFeedback.append(el("p", "empty", "選定期間內尚無負評紀錄。"));
    } else {
      const fbList = el("div");
      fbList.style.display = "flex";
      fbList.style.flexDirection = "column";
      fbList.style.gap = "0.75rem";

      for (const fb of feedbacks) {
        const item = el("div");
        item.style.padding = "0.75rem 1rem";
        item.style.borderLeft = "4px solid var(--text-danger, #ef4444)";
        item.style.background = "var(--bg-subtle, #f8fafc)";
        item.style.borderRadius = "4px";

        const topRow = el("div");
        topRow.style.display = "flex";
        topRow.style.justifyContent = "space-between";
        topRow.style.fontSize = "0.8rem";
        topRow.style.color = "var(--text-muted, #64748b)";

        topRow.append(
          el("span", "", `時間：${fb.occurredAt ? fb.occurredAt.replace("T", " ").slice(0, 19) : "-"}`),
          fb.resolvedStatus ? el("span", "badge badge-neutral", fb.resolvedStatus) : el("span"),
        );
        item.append(topRow);

        const reasonRow = el("div");
        reasonRow.style.marginTop = "0.35rem";
        reasonRow.style.fontSize = "0.9rem";
        reasonRow.style.fontWeight = "600";
        reasonRow.style.color = "var(--text-danger, #b91c1c)";
        reasonRow.textContent = `❌ 負評原因：${fb.reason || "未填寫原因"}`;
        item.append(reasonRow);

        if (fb.userMessage) {
          const uMsg = el("div");
          uMsg.style.fontSize = "0.85rem";
          uMsg.style.marginTop = "0.25rem";
          uMsg.innerHTML = `<span style="color:var(--text-muted);">提問：</span> ${fb.userMessage}`;
          item.append(uMsg);
        }

        if (fb.aiReply) {
          const aReply = el("div");
          aReply.style.fontSize = "0.85rem";
          aReply.style.marginTop = "0.2rem";
          aReply.innerHTML = `<span style="color:var(--text-muted);">回覆：</span> ${fb.aiReply.slice(0, 120)}${fb.aiReply.length > 120 ? "…" : ""}`;
          item.append(aReply);
        }

        if (fb.conversationId) {
          const viewConvBtn = el("button", "btn-secondary btn-small", "🔍 查看該筆對話");
          viewConvBtn.style.fontSize = "0.75rem";
          viewConvBtn.style.marginTop = "0.4rem";
          viewConvBtn.addEventListener("click", async () => {
            try {
              const detail = await api(`/api/conversations/${encodeURIComponent(fb.conversationId)}`);
              showConversationModal(detail, fb.conversationId);
            } catch (err) {
              alert(`無法載入對話：${err.message}`);
            }
          });
          item.append(viewConvBtn);
        }

        fbList.append(item);
      }
      secFeedback.append(fbList);
    }
    body.append(secFeedback);

    // 5. Action Footer
    const footer = el("div", "modal-footer");
    footer.style.display = "flex";
    footer.style.justifyContent = "space-between";
    footer.style.alignItems = "center";
    footer.style.marginTop = "1.5rem";
    footer.style.paddingTop = "1rem";
    footer.style.borderTop = "1px solid var(--border-subtle, #e2e8f0)";

    const leftActions = el("div");
    leftActions.style.display = "flex";
    leftActions.style.gap = "0.75rem";

    const returnCtx = {
      issueTypeId: data.issueTypeId,
      ...periodFilters,
    };
    const convBtn = el("button", "btn-primary", `💬 查看相關對話 (${formatCount(totalCount)} 筆)`);
    convBtn.addEventListener("click", () => {
      closeIssueModalRoot();
      navigateTo(
        "conversations",
        withReturnTo(
          {
            issueTypeId: data.issueTypeId,
            ...periodFilters,
          },
          "issues",
          returnCtx,
        ),
      );
    });
    leftActions.append(convBtn);

    if (negCount > 0) {
      const qualBtn = el("button", "btn-warning", `⚠️ 前往品質案件處理 (${formatCount(negCount)} 筆負評)`);
      qualBtn.style.background = "var(--bg-warning, #f59e0b)";
      qualBtn.style.color = "#ffffff";
      qualBtn.addEventListener("click", () => {
        closeIssueModalRoot();
        navigateTo(
          "quality",
          withReturnTo(
            {
              rating: "DOWN",
              issueTypeId: data.issueTypeId,
              ...periodFilters,
            },
            "issues",
            returnCtx,
          ),
        );
      });
      leftActions.append(qualBtn);
    }

    const closeBtn = el("button", "btn-secondary", "✕ 關閉");
    closeBtn.addEventListener("click", () => closeIssueModalRoot());
    footer.append(leftActions, closeBtn);
    body.append(footer);
  } catch (err) {
    body.replaceChildren(el("div", "error", `無法載入問題詳情：${err.message}`));
  }
}
