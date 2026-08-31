import { identityHeaders } from "./session.js";

const ERROR_MAPPING = {
  "Reviewers cannot approve their own submissions.":
    "審核者不能核准自己送審的內容。請切換為其他審核者身分。",
  "At least three test questions are required before review.":
    "送審前請先新增至少 3 個測試問題。",
  "Validation failed.":
    "內容檢查未通過，請修正標示的問題後再試。",
};

function translatePortalError(message) {
  return ERROR_MAPPING[message] || message;
}

function buildApiError(response, payload) {
  const raw = payload.detail?.message || payload.detail || "操作失敗";
  const message = typeof raw === "string" ? translatePortalError(raw) : JSON.stringify(raw);
  return Object.assign(new Error(message), {
    status: response.status,
    code: payload.detail?.code,
    issues: payload.detail?.issues,
  });
}

export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...identityHeaders(true), ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 403) {
    const raw = payload.detail?.message || payload.detail || "你沒有權限執行此操作";
    throw Object.assign(new Error(translatePortalError(typeof raw === "string" ? raw : JSON.stringify(raw))), {
      status: 403,
    });
  }
  if (!response.ok) {
    throw buildApiError(response, payload);
  }
  return payload;
}

export async function apiForm(path, formData, method = "POST") {
  const response = await fetch(path, {
    method,
    headers: identityHeaders(false),
    body: formData,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw buildApiError(response, payload);
  }
  return payload;
}

const previewUrls = new Set();

export async function loadAssetPreviewUrl(documentId, filename) {
  const response = await fetch(
    `/api/documents/${documentId}/draft/assets/${encodeURIComponent(filename)}`,
    { headers: identityHeaders(false) },
  );
  if (!response.ok) {
    throw new Error("無法載入圖片預覽");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  previewUrls.add(url);
  return url;
}

export function revokeAssetPreviewUrls() {
  for (const url of previewUrls) {
    URL.revokeObjectURL(url);
  }
  previewUrls.clear();
}
