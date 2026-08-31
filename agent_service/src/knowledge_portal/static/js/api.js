import { identityHeaders } from "./session.js";

const ERROR_MAPPING = {
  "Reviewers cannot approve their own submissions.":
    "審核者不能核准自己送審的內容。請切換為其他審核者身分。",
  "At least three test questions are required before review.":
    "送審前請先新增至少 3 個測試問題。",
};

function translatePortalError(message) {
  return ERROR_MAPPING[message] || message;
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
    const raw = payload.detail?.message || payload.detail || "操作失敗";
    const message = typeof raw === "string" ? translatePortalError(raw) : JSON.stringify(raw);
    throw Object.assign(new Error(message), { status: response.status });
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
    const raw = payload.detail?.message || payload.detail || "操作失敗";
    const message = typeof raw === "string" ? translatePortalError(raw) : JSON.stringify(raw);
    throw new Error(message);
  }
  return payload;
}

export async function loadAssetPreviewUrl(documentId, filename) {
  const response = await fetch(
    `/api/documents/${documentId}/draft/assets/${encodeURIComponent(filename)}`,
    { headers: identityHeaders(false) },
  );
  if (!response.ok) {
    throw new Error("無法載入圖片預覽");
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
