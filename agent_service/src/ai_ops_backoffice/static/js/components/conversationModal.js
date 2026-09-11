import { api, el } from "../api.js";
import { actorCapabilities } from "../app/capabilities.js";
import { isBuShellEnabled } from "../app/buShellConfig.js";
import { loadNavFilters, navigateTo, saveNavFilters, syncLocationHash } from "../app/navigation.js";
import { buildLocationHash, workspaceForView } from "../app/navigation.js";
import { navigateReturnTo } from "../app/returnTo.js";
import { badge } from "./badges.js";
import { showContentModal, showTextPrompt, showToast } from "./modal.js";
import { closeModalDialog, openModalDialog } from "./modalA11y.js";
import { formatAssistantHtml, formatTaipeiDateTime, labelRoute } from "../app/labels.js";

function routeLabel(route) {
  return labelRoute(route);
}

function sourceTraceStatusLabel(status) {
  if (status === "LEGACY_UNVERIFIED") return "身分未確認（不可下載原檔）";
  if (status === "LEGACY_BACKFILLED") return "歷史事件已由發布版本回填（待確認）";
  if (status === "UNRESOLVED") return "尚未能定位發布版本";
  return "已鎖定發布版本";
}

function sourcePreviewContent(source) {
  const content = el("div", "source-preview");
  const identity = el("div", "metric-label");
  identity.textContent = [
    source.documentId ? `文件：${source.documentId}` : "文件：—",
    source.versionId ? `版本：${source.versionId}` : "版本：—",
    source.releaseId ? `發布：${source.releaseId}` : "發布：—",
  ].join("｜");
  content.append(identity);
  content.append(
    el(
      "p",
      "metric-label",
      `chunk：${source.chunkId || "—"}｜追溯狀態：${sourceTraceStatusLabel(source.traceStatus)}`,
    ),
  );
  if (source.sourcePath) {
    content.append(el("p", "metric-label", `轉換來源：${source.sourcePath}`));
  }
  const locator = source.locator || {};
  const locatorBits = [];
  if (locator.locator_type || locator.locatorType) {
    locatorBits.push(`類型：${locator.locator_type || locator.locatorType}`);
  }
  if (locator.page_label || locator.pageLabel || locator.page_index != null || locator.pageIndex != null) {
    locatorBits.push(
      `頁面：${locator.page_label || locator.pageLabel || (Number(locator.page_index ?? locator.pageIndex) + 1)}`,
    );
  }
  if (locator.section_path || locator.sectionPath) {
    locatorBits.push(`章節：${locator.section_path || locator.sectionPath}`);
  }
  if (locator.sheet_name || locator.sheetName) {
    locatorBits.push(`工作表：${locator.sheet_name || locator.sheetName}`);
  }
  if (locator.cell_range || locator.cellRange) {
    locatorBits.push(`範圍：${locator.cell_range || locator.cellRange}`);
  }
  if (locatorBits.length) {
    content.append(el("p", "metric-label", `定位：${locatorBits.join("｜")}`));
  }
  if (locator.degraded_reason || locator.degradedReason) {
    content.append(el("p", "metric-label", locator.degraded_reason || locator.degradedReason));
  }
  const notice = el("div", source.originalAssetAvailable ? "callout success" : "callout warning");
  notice.append(
    el(
      "strong",
      "",
      source.originalAssetAvailable ? "原始檔可受控下載" : "原始檔尚未保存",
    ),
  );
  notice.append(
    el(
      "p",
      "",
      source.message || "目前顯示發布時使用的轉換內容。",
    ),
  );
  content.append(notice);
  const evidence = source.evidence?.excerpt || "目前沒有可顯示的段落內容。";
  content.append(el("h3", "", "回答引用的段落"));
  const evidenceBlock = el("pre", "json-block source-evidence", evidence);
  if (locator.paragraph_id || locator.paragraphId) {
    evidenceBlock.dataset.paragraphId = locator.paragraph_id || locator.paragraphId;
  }
  if (locator.bbox || (Array.isArray(locator.bbox) && locator.bbox.length)) {
    evidenceBlock.dataset.bbox = JSON.stringify(locator.bbox);
  }
  if (locator.page_index != null || locator.pageIndex != null) {
    evidenceBlock.dataset.pageIndex = String(locator.page_index ?? locator.pageIndex);
    evidenceBlock.classList.add("source-highlight-target");
  }
  content.append(evidenceBlock);
  if (source.evidence?.truncated) {
    content.append(el("p", "metric-label", "段落過長，以上為受控預覽。"));
  }
  const canDownload =
    source.downloadUrl &&
    source.actions?.canDownloadOriginal !== false &&
    source.mappingStatus !== "LEGACY_UNVERIFIED" &&
    source.traceStatus !== "LEGACY_UNVERIFIED";
  if (canDownload) {
    const download = el("a", "drill-link", `開啟原始檔${source.originalAssetName ? `：${source.originalAssetName}` : ""}`);
    download.href = source.downloadUrl;
    if (locator.page_label || locator.pageLabel || locator.page_index != null || locator.pageIndex != null) {
      const pageHash = locator.page_label || locator.pageLabel || String(Number(locator.page_index ?? locator.pageIndex) + 1);
      download.hash = `page=${encodeURIComponent(pageHash)}`;
      if (locator.bbox) {
        download.hash += `&bbox=${encodeURIComponent(JSON.stringify(locator.bbox))}`;
      }
    }
    download.target = "_blank";
    download.rel = "noopener";
    content.append(download);
  }
  if (source.documentId) {
    const documentLink = el("a", "drill-link", "開啟知識文件");
    documentLink.href = buildLocationHash(
      workspaceForView("knowledgeDocument") || "knowledge_ops",
      "knowledgeDocument",
      { documentId: source.documentId },
    );
    content.append(documentLink);
  }
  return content;
}

async function openSourcePreview(source, button) {
  if (!source?.sourceRefId) return;
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "載入來源…";
  try {
    const detail = await api(`/api/sources/${encodeURIComponent(source.sourceRefId)}`);
    showContentModal(`回答來源：${detail.title || source.title || "未命名文件"}`, sourcePreviewContent(detail));
  } catch (error) {
    showContentModal("來源預覽失敗", el("div", "error", error.message));
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

function closeModalRoot() {
  closeModalDialog();
}

function buildConversationBody(detail, conversationId, { onRefresh, onUnmask, selectedTurnId } = {}) {
  const content = el("div", "bu-conversation-detail");
  const allowed = actorCapabilities();
  const stateBadge = el(
    "div",
    "meta-chip",
    detail.dataState === "UNMASKED_WITH_REASON"
      ? "資料狀態：有理由未遮罩（已記錄稽核）"
      : "資料狀態：敏感資訊已遮罩",
  );
  content.append(stateBadge);

  const actions = el("div", "filter-bar");
  const refreshBtn = el("button", "", "重新整理");
  refreshBtn.type = "button";
  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "載入中…";
    try {
      const refreshed = await api(
        `/api/conversations/${encodeURIComponent(conversationId)}?refresh=true`,
      );
      onRefresh?.(refreshed, conversationId);
    } catch (error) {
      showToast(`重新整理失敗：${error.message}`, { tone: "error" });
      refreshBtn.disabled = false;
      refreshBtn.textContent = "重新整理";
    }
  });
  const copyUrlBtn = el("button", "button-secondary", "複製安全網址");
  copyUrlBtn.type = "button";
  copyUrlBtn.title = "只包含對話／回合識別碼，不包含提問原文或敏感查詢條件";
  copyUrlBtn.addEventListener("click", async () => {
    const safeHash = buildLocationHash(
      workspaceForView("conversations") || "knowledge_ops",
      "conversations",
      { conversationId, turnId: selectedTurnId || "" },
    );
    const safeUrl = `${window.location.origin}${window.location.pathname}${safeHash}`;
    try {
      await navigator.clipboard.writeText(safeUrl);
      copyUrlBtn.textContent = "已複製安全網址";
      setTimeout(() => { copyUrlBtn.textContent = "複製安全網址"; }, 1400);
    } catch {
      await showTextPrompt({
        title: "安全網址",
        message: "瀏覽器不允許直接寫入剪貼簿，請手動複製下列網址。",
        defaultValue: safeUrl,
        readOnly: true,
        confirmLabel: "關閉",
      });
    }
  });
  actions.append(refreshBtn, copyUrlBtn);
  if (allowed.has("ops.conversations.unmasked") && !detail.unmaskAuthorized) {
    const unmaskButton = el("button", "", "申請查看未遮罩內容");
    unmaskButton.addEventListener("click", async () => {
      const reason = await showTextPrompt({
        title: "申請查看未遮罩內容",
        message: "請輸入原因（至少 3 個字）；申請會寫入資安稽核紀錄。",
        minLength: 3,
        required: true,
      });
      if (reason == null) return;
      const refreshed = await api(
        `/api/conversations/${encodeURIComponent(conversationId)}?${new URLSearchParams({
          unmask_reason: reason.trim(),
        })}`,
      );
      onUnmask?.(refreshed, conversationId);
    });
    actions.append(unmaskButton);
  }
  content.append(actions);

  const layout = el("div", "bu-case-layout");
  const main = el("section", "bu-case-main");
  const side = el("aside", "bu-case-side");
  let selectedTurn = (detail.turns || []).find((turn) =>
    selectedTurnId && String(turn.turnId || "") === String(selectedTurnId),
  ) || (detail.turns || [])[0] || null;

  function renderSide(turn) {
    side.replaceChildren(el("h3", "", "本回合回答依據"));
    if (!turn) {
      side.append(el("p", "muted", "尚無回合資料。"));
      return;
    }
    side.append(el("p", "metric-label", `已選取回合：${turn.turnId || turn.occurredAt || "—"}`));
    side.append(el("p", "", "處理方式 "));
    side.append(badge(routeLabel(turn.route), "accent"));
    if (turn.faqKey) {
      side.append(el("p", "metric-label", `FAQ：${turn.faqKey}`));
    }
    const docs = turn.documentIds || [];
    const paths = turn.sourcePaths || [];
    const releases = turn.releaseIds || [];
    const sourceRefs = turn.sourceRefs || [];
    if (sourceRefs.length) {
      const sourceHeading = el("p", "metric-label", `已追溯 ${sourceRefs.length} 個回答來源`);
      side.append(sourceHeading);
      for (const source of sourceRefs) {
        const item = el("div", "source-ref-item");
        item.append(
          el(
            "div",
            "source-ref-title",
            `${source.title || "未命名文件"}${source.traceStatus === "LEGACY_BACKFILLED" ? "（歷史回填）" : ""}`,
          ),
        );
        item.append(
          el(
            "div",
            "metric-label",
            [source.documentId, source.versionId, source.releaseId].filter(Boolean).join("｜") || "版本資訊不足",
          ),
        );
        const button = el("button", "drill-link", "查看來源段落");
        button.type = "button";
        button.addEventListener("click", () => void openSourcePreview(source, button));
        item.append(button);
        side.append(item);
      }
    } else if (docs.length || paths.length || releases.length) {
      if (docs.length) {
        for (const docId of docs) {
          const link = el("a", "drill-link", `文件 ${String(docId).slice(0, 12)}`);
          link.href = buildLocationHash(
            workspaceForView("knowledgeDocument") || "knowledge_ops",
            "knowledgeDocument",
            { documentId: docId },
          );
          link.title = docId;
          side.append(link);
        }
      }
      if (paths.length) {
        side.append(el("p", "metric-label", `來源路徑：${paths.join("、")}`));
      }
      if (releases.length) {
        side.append(el("p", "metric-label", `版本／發布：${releases.join("、")}`));
      }
    } else {
      const noSourceMessage = turn.resultType === "NEED_MORE_INFO"
        ? "此回合是補充資訊流程，尚未產生知識庫回答，因此沒有引用來源。"
        : turn.route === "NOT_IT"
          ? "此回合被判定為非 IT 問題，因此沒有查詢企業知識庫。"
          : "此回合沒有保存可追溯的文件／段落來源。";
      side.append(el("p", "metric-label", noSourceMessage));
    }
    side.append(
      el(
        "p",
        "metric-label",
        `回饋：${turn.feedbackRating || "—"}｜解決：${turn.resolvedStatus || "—"}｜轉人工：${turn.handoffStatus || "—"}`,
      ),
    );
    if (turn.ticketId || turn.ticketStatus) {
      side.append(
        el(
          "p",
          "metric-label",
          `派工：${turn.ticketId || "—"} ${turn.ticketStatus ? `[${turn.ticketStatus}]` : ""}`,
        ),
      );
    }
    const tech = el("details");
    const summary = document.createElement("summary");
    summary.textContent = "技術詳情";
    tech.append(summary);
    tech.append(
      el(
        "pre",
        "json-block",
        JSON.stringify(
          {
            conversationId,
            turnId: turn.turnId || turn.occurredAt,
            model: turn.model,
            resultType: turn.resultType,
            events: turn.events,
          },
          null,
          2,
        ),
      ),
    );
    side.append(tech);
  }

  for (const turn of detail.turns || []) {
    const block = el("div", "message bu-turn");
    block.style.cursor = "pointer";
    block.dataset.turnId = turn.turnId || "";
    block.setAttribute("aria-pressed", selectedTurn === turn ? "true" : "false");
    if (selectedTurn === turn) block.classList.add("is-selected");
    block.append(el("div", "meta", formatTaipeiDateTime(turn.occurredAt || "")));

    const userText = turn.messageMasked || turn.userMessage || turn.message || "";
    if (userText) {
      const user = el("div", "bu-turn-user");
      user.append(el("div", "meta", "使用者提問"));
      user.append(el("p", "", userText));
      block.append(user);
    }

    const answerText = turn.answerMasked || turn.aiReply || "";
    if (answerText) {
      const assistant = el("div", "bu-turn-assistant");
      assistant.append(el("div", "meta", "AI 回答"));
      if (answerText === "[REDACTED_CREDENTIAL]") {
        assistant.append(
          el(
            "div",
            "callout warning",
            "這個回合的回答因偵測到疑似憑證資訊而被遮罩；原文未保存，無法從此紀錄還原。",
          ),
        );
      } else {
        const answer = el("div", "bu-answer-body");
        answer.innerHTML = formatAssistantHtml(answerText);
        assistant.append(answer);
      }
      assistant.append(
        el(
          "small",
          "muted",
          `處理方式：${routeLabel(turn.route)}${turn.faqKey ? `｜FAQ ${turn.faqKey}` : ""}`,
        ),
      );
      block.append(assistant);
    } else if (userText) {
      const missingAnswer = el("div", "bu-turn-assistant is-missing");
      missingAnswer.append(el("div", "meta", "AI 回答"));
      missingAnswer.append(
        el(
          "p",
          "muted",
          "此舊回合沒有保存可顯示的 AI 回答；新回合會記錄完整的實際回覆。",
        ),
      );
      block.append(missingAnswer);
    }

    if (turn.feedbackRating === "DOWN") {
      block.append(badge("負評", "danger"));
    }
    block.addEventListener("click", () => {
      selectedTurn = turn;
      for (const other of main.querySelectorAll("[data-turn-id]")) {
        other.classList.toggle("is-selected", other === block);
        other.setAttribute("aria-pressed", other === block ? "true" : "false");
      }
      renderSide(turn);
    });
    main.append(block);
  }
  if (!(detail.turns || []).length) {
    main.append(el("p", "empty", "此對話尚無可顯示的回合。"));
  }
  renderSide(selectedTurn);
  layout.append(main, side);
  content.append(layout);
  return content;
}

export function showConversationPage(detail, conversationId = detail.conversationId, options = {}) {
  const navFilters = loadNavFilters();
  const selectedTurnId = options.selectedTurnId || navFilters.turnId || "";
  const app = document.getElementById("app");
  const page = el("div", "bu-case-page");
  const crumb = el("div", "bu-case-crumb");
  const back = el("a", "", "← 返回");
  back.href = "#";
  back.addEventListener("click", (event) => {
    event.preventDefault();
    if (navFilters.returnTo) {
      navigateReturnTo("conversations", {});
      return;
    }
    const listFilters = { ...navFilters };
    delete listFilters.view;
    delete listFilters.conversationId;
    delete listFilters.turnId;
    delete listFilters.returnTo;
    void navigateTo("conversations", listFilters);
  });
  crumb.append(back, document.createTextNode(` / ${conversationId}`));
  page.append(crumb);
  page.append(el("h2", "", "對話紀錄"));
  page.append(
    el("p", "metric-label", "從使用者的提問，追到實際回答與引用依據。"),
  );
  const rerender = (nextDetail, nextId) => {
    showConversationPage(nextDetail, nextId, { selectedTurnId });
  };
  page.append(
    buildConversationBody(detail, conversationId, {
      onRefresh: rerender,
      onUnmask: rerender,
      selectedTurnId,
    }),
  );
  app.replaceChildren(page);
}

export function showConversationModal(detail, conversationId = detail.conversationId) {
  if (isBuShellEnabled()) {
    const nav = loadNavFilters();
    const selectedTurnId = detail.selectedTurnId || nav.turnId || "";
    saveNavFilters({ ...nav, view: "conversations", conversationId, turnId: selectedTurnId });
    syncLocationHash("conversations", { ...nav, conversationId, turnId: selectedTurnId });
    showConversationPage(detail, conversationId, { selectedTurnId });
    return;
  }
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  root.onclick = (e) => {
    if (e.target === root) {
      closeModalRoot();
    }
  };
  const modal = el("section", "modal");
  const header = el("div", "modal-header");
  header.style.display = "flex";
  header.style.justifyContent = "space-between";
  header.style.alignItems = "center";
  header.style.marginBottom = "1rem";
  header.style.paddingBottom = "0.75rem";
  header.style.borderBottom = "1px solid var(--border-subtle, #e2e8f0)";

  const heading = el("h2", "", `對話紀錄 ${conversationId}`);
  heading.style.margin = "0";

  const headerActions = el("div");
  headerActions.style.display = "flex";
  headerActions.style.gap = "0.5rem";
  headerActions.style.alignItems = "center";

  const close = el("button", "btn-modal-close", "關閉");
  close.type = "button";
  close.addEventListener("click", () => closeModalRoot());
  headerActions.append(close);
  header.append(heading, headerActions);
  modal.append(header);
  modal.append(
    buildConversationBody(detail, conversationId, {
      onRefresh: showConversationModal,
      onUnmask: showConversationModal,
    }),
  );
  root.append(modal);
  openModalDialog(root, modal, { titleElement: heading, initialFocus: close });
}
