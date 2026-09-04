const AUTH_STORAGE_KEY = "ai_ops_backoffice_auth";

export function loadAuthHeaders() {
  const raw = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export function clearAuthHeaders() {
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
}

export function saveAuthHeaders(headers) {
  sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(headers));
}

export function authHeaders() {
  const stored = loadAuthHeaders();
  if (stored.bearerToken) {
    return { Authorization: `Bearer ${stored.bearerToken}` };
  }
  return {
    "X-Backoffice-User-Id": stored.userId || "ops.admin",
    "X-Backoffice-User-Name": stored.userName || "System Administrator",
    "X-Backoffice-Role": stored.role || "SYSTEM_ADMIN",
    "X-Backoffice-Owner-Units": stored.ownerUnits || "IT Service Desk",
  };
}

export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (response.status === 401) {
    throw new Error("UNAUTHORIZED");
  }
  if (response.status === 403) {
    throw new Error("FORBIDDEN");
  }
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    if (contentType.includes("application/json")) {
      const payload = await response.json().catch(() => ({}));
      const message = payload.error?.message || payload.detail || `HTTP ${response.status}`;
      throw new Error(typeof message === "string" ? message : `HTTP ${response.status}`);
    }
    throw new Error(`HTTP ${response.status}`);
  }
  if (contentType.includes("text/csv")) {
    return response.text();
  }
  return response.json();
}

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function metric(label, value) {
  const wrap = el("div", "metric");
  wrap.append(el("div", "metric-label", label));
  wrap.append(el("div", "metric-value", String(value)));
  return wrap;
}

export async function ensureAuth(authConfig) {
  const mode = (authConfig?.authMode || "HEADER").toUpperCase();
  if (mode === "ENTRA") {
    const stored = loadAuthHeaders();
    if (stored.bearerToken) {
      return;
    }
    const token = window.prompt("請輸入 Entra Bearer Token");
    if (!token) {
      throw new Error("UNAUTHORIZED");
    }
    saveAuthHeaders({ bearerToken: token.trim() });
    return;
  }
  if (authConfig?.headerAuthAllowed === false) {
    throw new Error("UNAUTHORIZED");
  }
  const stored = loadAuthHeaders();
  if (stored.userId) {
    return;
  }
  // 本機開發與測試預設為最高權限（SYSTEM_ADMIN），不再彈出確認視窗
  saveAuthHeaders({
    userId: "ops.admin",
    userName: "System Administrator",
    role: "SYSTEM_ADMIN",
    ownerUnits: "IT Service Desk",
  });
}

export function downloadText(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
