import { api } from "../../api.js";
import { navigate } from "../../router.js";
import {
  confirmDialog,
  escapeHtml,
  openDialog,
  promptDialog,
  showToast,
} from "../../ui.js?v=20260831e";
import { captureDraftBaseline } from "./editor-state.js";

export async function handleAction(documentId, action, detail) {
  if (action === "validate") {
    const result = await api(`/api/documents/${documentId}/validate`, { method: "POST" });
    showToast(`檢查完成：${result.issues?.length || 0} 項結果`);
  }
  if (action === "add-test") {
    const question = await promptDialog("新增測試問題", "問題內容");
    if (!question) return false;
    await api(`/api/documents/${documentId}/test-cases`, {
      method: "POST",
      body: JSON.stringify({ question, simulated_audience: [], notes: "" }),
    });
    showToast("已新增測試問題");
  }
  if (action === "draft-search") {
    const query = await promptDialog("進階診斷", "請輸入測試問題");
    if (!query) return false;
    const result = await api(`/api/documents/${documentId}/draft-search`, {
      method: "POST",
      body: JSON.stringify({ query, groups: [], limit: 4 }),
    });
    const hits = (result.hits || [])
      .map((hit) => `${hit.title}: ${hit.content.slice(0, 80)}…`)
      .join("\n");
    await openDialog({
      title: "診斷結果",
      bodyHtml: `
        <p>草稿可找到：${result.matchedDraft ? "是" : "否"}</p>
        <p>正式版洩漏：${result.leakedFromActiveRelease ? "是" : "否"}</p>
        <pre class="content-preview">${escapeHtml(hits || "草稿索引沒有命中")}</pre>`,
      confirmLabel: "關閉",
      cancelLabel: "關閉",
    });
    return false;
  }
  if (action === "start-revision") {
    await api(`/api/documents/${documentId}/start-revision`, { method: "POST" });
    showToast("已建立新版本草稿");
  }
  if (action === "save-draft") {
    const markdown = document.getElementById("draftMarkdown")?.value;
    const title = document.getElementById("draftTitle")?.value?.trim();
    if (!markdown?.trim() || !title) {
      showToast("標題與正文內容不可為空", true);
      return false;
    }
    const audienceType = document.getElementById("draftAudienceType")?.value;
    const originalAudience = document.getElementById("draftAudienceType")?.dataset.original;
    if (audienceType !== originalAudience) {
      const ok = await confirmDialog(
        "變更適用範圍",
        "變更適用範圍可能影響引用權限，並可能需要額外審核。確定要繼續？",
        { confirmLabel: "繼續儲存" },
      );
      if (!ok) return false;
    }
    const audienceGroups = (document.getElementById("draftAudienceGroups")?.value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const draftVersion = detail.draft_version;
    await api(`/api/documents/${documentId}/draft`, {
      method: "PUT",
      body: JSON.stringify({
        etag: detail.document.etag,
        title,
        summary: document.getElementById("draftSummary")?.value || "",
        category: document.getElementById("draftCategory")?.value || "",
        owner_unit_id: document.getElementById("draftOwnerUnit")?.value || detail.document.owner_unit_id,
        business_contact: detail.document.business_contact || "",
        audience_type: audienceType,
        audience_group_ids: audienceGroups,
        effective_at: document.getElementById("draftEffectiveAt")?.value || draftVersion.effective_at,
        review_due_at: document.getElementById("draftReviewDueAt")?.value || draftVersion.review_due_at,
        change_summary: draftVersion.change_summary || "",
        change_reason: document.getElementById("draftChangeReason")?.value || "更新草稿內容",
        markdown_content: markdown,
      }),
    });
    captureDraftBaseline();
    showToast("草稿已儲存");
  }
  if (action === "insert-asset-ref") {
    const filename = await promptDialog("插入圖片", "圖片檔名（留空則自動命名）", { required: false });
    if (filename === null) return false;
    const altText = await promptDialog("插入圖片", "替代文字（可留空）", { required: false, defaultValue: "" });
    if (altText === null) return false;
    const suggestion = await api(
      `/api/documents/${documentId}/draft/asset-ref?filename=${encodeURIComponent(filename)}&alt_text=${encodeURIComponent(altText || "")}`,
      { method: "POST" },
    );
    const textarea = document.getElementById("draftMarkdown");
    if (textarea) {
      const suffix = textarea.value.endsWith("\n") || !textarea.value ? "" : "\n";
      textarea.value = `${textarea.value}${suffix}${suggestion.markdown}\n`;
    }
    showToast("已產生 Markdown 參考");
    return false;
  }
  if (action === "submit" || action === "edit-draft") {
    if (action === "edit-draft") {
      navigate(`#/knowledge/${documentId}/content`);
      return false;
    }
    const ok = await confirmDialog("送審", "確定要將此草稿送交審核？", { confirmLabel: "確認送審" });
    if (!ok) return false;
    await api(`/api/documents/${documentId}/submit-review`, {
      method: "POST",
      body: JSON.stringify({
        etag: detail.document.etag,
        change_reason: detail.draft_version?.change_reason || "送審",
      }),
    });
    showToast("已送審");
  }
  if (action === "approve" || action === "reject") {
    const decision = action === "approve" ? "APPROVED" : "CHANGES_REQUESTED";
    const comment = await promptDialog(
      action === "approve" ? "核准" : "退回修改",
      "審核意見",
      {
        defaultValue: action === "approve" ? "內容與測試結果可接受。" : "請依意見修正後再送審。",
        multiline: true,
      },
    );
    if (comment === null) return false;
    await api(`/api/reviews/${detail.open_review.review_id}/decision`, {
      method: "POST",
      body: JSON.stringify({
        decision,
        comment,
        policy_exceptions: [],
      }),
    });
    showToast(action === "approve" ? "已核准" : "已退回修改");
  }
  if (action === "publish") {
    const ok = await confirmDialog(
      "發布正式版本",
      "發布後 Teams 將引用此版本。確定要發布？",
      { confirmLabel: "發布" },
    );
    if (!ok) return false;
    const versionId = detail.draft_version?.version_id || detail.document.current_published_version_id;
    const idempotencyKey = "pub-" + Date.now() + "-" + Math.random().toString(36).substring(2, 9);
    await api(`/api/documents/${documentId}/publish`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        version_id: versionId,
        reason: "核准後發布正式版本",
      }),
    });
    showToast("發布成功");
  }
  if (action === "discard-draft") {
    const reason = await promptDialog("放棄草稿", "請說明原因", { defaultValue: "放棄草稿" });
    if (reason === null) return false;
    const ok = await confirmDialog("放棄草稿", "此操作無法復原。確定要放棄草稿？", { danger: true, confirmLabel: "放棄" });
    if (!ok) return false;
    await api(`/api/documents/${documentId}/discard-draft`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    showToast("已放棄草稿");
    navigate("#/knowledge");
    return false;
  }
  if (action === "unpublish") {
    const reason = await promptDialog("下架正式文件", "請說明原因", { defaultValue: "下架正式文件" });
    if (reason === null) return false;
    const ok = await confirmDialog(
      "下架正式文件",
      "下架後 Teams 將無法引用此文件。確定要下架？",
      { danger: true, confirmLabel: "下架" },
    );
    if (!ok) return false;
    await api(`/api/documents/${documentId}/unpublish`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    showToast("已下架");
  }
  if (action === "view") {
    navigate(`#/knowledge/${documentId}/overview`);
  }
}
