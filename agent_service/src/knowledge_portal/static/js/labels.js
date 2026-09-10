export const STATUS_LABELS = {
  DRAFT: "草稿",
  IN_REVIEW: "待審核",
  CHANGES_REQUESTED: "待修正",
  APPROVED: "已核准",
  PUBLISHING: "發布中",
  PUBLISHED: "已發布",
  PUBLISH_FAILED: "發布失敗",
  UNPUBLISHED: "已下架",
  DISCARDED: "已放棄",
  REJECTED: "已拒絕",
};

export const TEST_RESULT_LABELS = {
  PASS: "可回答",
  NEEDS_REVIEW: "需要確認",
  FAIL: "無法回答",
};

export const NEXT_ACTION_LABELS = {
  EDIT_DRAFT: "編輯草稿",
  SUBMIT_REVIEW: "送審",
  APPROVE: "核准",
  REJECT: "退回修改",
  PUBLISH: "發布正式版本",
  START_REVISION: "建立新版本",
  VIEW: "查看內容",
};

export const ROLE_LABELS = {
  CONTRIBUTOR: "知識貢獻者",
  REVIEWER: "知識審核者",
  MANAGER: "知識管理者",
  PLATFORM: "平台管理者",
  AUDITOR: "稽核人員",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || status;
}

export function testResultLabel(status) {
  return TEST_RESULT_LABELS[status] || status;
}

export function nextActionLabel(action) {
  return action ? NEXT_ACTION_LABELS[action] || action : "";
}

/**
 * Build a short lifecycle strip for BU operators.
 * Stages: 草稿 → 已核准 → 已發布 → 索引／Agent 使用
 */
export function lifecycleStages(detail = {}) {
  const status = String(detail.document?.status || detail.status || "").toUpperCase();
  const hasPublished = Boolean(detail.published_version);
  const deployment = detail.deployment || {};
  const indexStatus = String(deployment.indexStatus || "UNKNOWN").toUpperCase();
  const agentStatus = String(deployment.agentStatus || "UNKNOWN").toUpperCase();
  const publishFailed = status === "PUBLISH_FAILED" || agentStatus === "SYNC_FAILED";
  const indexing = status === "PUBLISHING" || indexStatus === "PENDING_INDEX" || agentStatus === "SYNCING";
  const stages = [
    {
      id: "draft",
      label: "草稿／修訂",
      done: true,
      current: ["DRAFT", "CHANGES_REQUESTED", "IN_REVIEW"].includes(status),
    },
    {
      id: "approved",
      label: "已核准",
      done: ["APPROVED", "PUBLISHING", "PUBLISHED"].includes(status) || hasPublished,
      current: status === "APPROVED",
    },
    {
      id: "published",
      label: publishFailed ? "發布／同步失敗" : status === "PUBLISHING" ? "發布中" : "已發布",
      done: status === "PUBLISHED" || (hasPublished && !publishFailed && !indexing),
      current: status === "PUBLISHING" || publishFailed || (status === "PUBLISHED" && !hasPublished),
      warn: publishFailed,
    },
    {
      id: "index",
      label: indexStatusLabel(indexStatus),
      done: indexStatus === "INDEXED",
      current: indexStatus === "PENDING_INDEX" || indexStatus === "NOT_PARSED",
      warn: indexStatus === "NOT_INDEXED" || indexStatus === "NOT_PARSED",
    },
    {
      id: "agent",
      label: agentStatusLabel(agentStatus),
      done: agentStatus === "USING_VERSION",
      current: agentStatus === "SYNCING",
      warn: agentStatus === "SYNC_FAILED" || agentStatus === "STALE" || agentStatus === "UNKNOWN",
    },
  ];
  return stages;
}

export function renderLifecycleStrip(detail = {}) {
  const stages = lifecycleStages(detail);
  return `
    <ol class="lifecycle-strip" aria-label="文件生命週期">
      ${stages.map((stage) => `
        <li class="lifecycle-strip__item${stage.done ? " is-done" : ""}${stage.current ? " is-current" : ""}${stage.warn ? " is-warn" : ""}">
          <span class="lifecycle-strip__label">${stage.label}</span>
        </li>`).join("")}
    </ol>`;
}

export function audienceLabel(audienceType, groupIds = []) {
  if (audienceType === "ALL_EMPLOYEES") return "全體員工";
  if (groupIds?.length) return groupIds.join("、");
  return "特定群組";
}

export function releaseLabel(releaseId) {
  if (!releaseId) return "尚未發布";
  return "已發布至 Teams 知識庫";
}

export function indexStatusLabel(status) {
  return {
    INDEXED: "已完成索引",
    PENDING_INDEX: "索引更新中",
    NOT_INDEXED: "尚未建立索引",
    NOT_PARSED: "尚未完成解析",
    UNKNOWN: "索引狀態未知",
  }[String(status || "UNKNOWN").toUpperCase()] || String(status || "索引狀態未知");
}

export function agentStatusLabel(status) {
  return {
    USING_VERSION: "Agent 已使用新版",
    SYNCING: "Agent 同步中",
    SYNC_FAILED: "Agent 同步失敗",
    STALE: "Agent 尚未使用新版",
    NOT_APPLICABLE: "Agent 尚未使用版本",
    UNKNOWN: "Agent 使用版本未知",
  }[String(status || "UNKNOWN").toUpperCase()] || String(status || "Agent 使用版本未知");
}

export function releaseStatusLabel(status) {
  return {
    ACTIVE: "已生效（Agent 已回報）",
    DEPLOYING: "發布完成，等待生效",
    BUILDING: "建立中",
    READY: "待啟用",
    RELOAD_FAILED: "Agent 生效失敗",
    ROLLED_BACK: "已取代",
    FAILED: "建立失敗",
  }[String(status || "").toUpperCase()] || String(status || "尚無 release");
}
