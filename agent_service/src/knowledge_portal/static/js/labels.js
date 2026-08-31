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
