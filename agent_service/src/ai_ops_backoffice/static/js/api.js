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
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("backoffice:unauthorized", { detail: { path } }));
    }
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

let expiryTimer = null;

export function parseJwt(token) {
  if (!token || typeof token !== "string") return null;
  try {
    const parts = token.trim().split(".");
    if (parts.length < 2) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    const decoded = new TextDecoder().decode(bytes);
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

export function isTokenExpired(token, bufferSeconds = 10) {
  const payload = parseJwt(token);
  if (!payload || typeof payload.exp !== "number") return false;
  return payload.exp * 1000 <= Date.now() + bufferSeconds * 1000;
}

export function getTokenExpiryDetails(token) {
  const payload = parseJwt(token);
  if (!payload || typeof payload.exp !== "number") return null;
  const expiryDate = new Date(payload.exp * 1000);
  const remainingMs = expiryDate.getTime() - Date.now();
  const isExpired = remainingMs <= 0;
  return {
    expiryDate,
    remainingMs,
    isExpired,
    formatted: expiryDate.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" }),
    name: payload.name || payload.preferred_username || payload.upn || payload.sub || "Entra 使用者",
    upn: payload.preferred_username || payload.upn || payload.email || "",
    roles: Array.isArray(payload.roles) ? payload.roles : (payload.roles ? [payload.roles] : []),
  };
}

export function scheduleExpiryWatcher(token, onExpiredCallback) {
  if (expiryTimer) {
    clearTimeout(expiryTimer);
    expiryTimer = null;
  }
  const details = getTokenExpiryDetails(token);
  if (!details) return;
  if (details.isExpired) {
    if (typeof onExpiredCallback === "function") {
      onExpiredCallback();
    } else if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("backoffice:token-expired"));
    }
    return;
  }
  expiryTimer = setTimeout(() => {
    if (typeof onExpiredCallback === "function") {
      onExpiredCallback();
    } else if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("backoffice:token-expired"));
    }
  }, Math.max(1000, details.remainingMs));
}

export function clearExpiryWatcher() {
  if (expiryTimer) {
    clearTimeout(expiryTimer);
    expiryTimer = null;
  }
}

export function logout() {
  clearAuthHeaders();
  clearExpiryWatcher();
  if (typeof window !== "undefined") {
    window.location.reload();
  }
}

export function showEntraLoginModal({ message, reauth = false } = {}) {
  return new Promise((resolve, reject) => {
    if (typeof document === "undefined") {
      reject(new Error("Document not available"));
      return;
    }
    let root = document.getElementById("modal-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "modal-root";
      root.className = "modal-backdrop";
      document.body.append(root);
    }
    root.hidden = false;
    root.replaceChildren();

    const box = el("div", "modal");
    box.style.maxWidth = "520px";
    box.style.width = "90vw";
    box.style.padding = "2rem";

    const header = el("div");
    header.style.display = "flex";
    header.style.alignItems = "center";
    header.style.gap = "0.85rem";
    header.style.marginBottom = "1.25rem";

    const icon = el("div");
    icon.style.width = "40px";
    icon.style.height = "40px";
    icon.style.borderRadius = "10px";
    icon.style.background = "linear-gradient(135deg, #0078d4 0%, #002050 100%)";
    icon.style.display = "grid";
    icon.style.placeItems = "center";
    icon.style.color = "#ffffff";
    icon.style.fontWeight = "700";
    icon.style.fontSize = "18px";
    icon.textContent = "⊞";

    const titleGroup = el("div");
    const h2 = el("h2", "", "Microsoft Entra ID 企業登入");
    h2.style.fontSize = "1.25rem";
    h2.style.fontWeight = "700";
    h2.style.margin = "0";
    h2.style.color = "var(--text, #0f172a)";

    const sub = el("p", "muted", "AI 資訊客服營運後台存取授權");
    sub.style.fontSize = "0.85rem";
    sub.style.margin = "0.2rem 0 0";

    titleGroup.append(h2, sub);
    header.append(icon, titleGroup);

    const notice = el("div");
    if (message || reauth) {
      notice.className = "banner is-warning";
      notice.style.marginBottom = "1rem";
      notice.style.padding = "0.75rem 1rem";
      notice.style.borderRadius = "var(--radius-sm, 8px)";
      notice.style.background = "var(--warning-soft, #fffbeb)";
      notice.style.border = "1px solid var(--warning-border, #fde68a)";
      notice.style.color = "var(--warning, #d97706)";
      notice.style.fontSize = "0.9rem";
      notice.textContent = message || "您的登入階段已過期，請重新輸入存取權杖以繼續作業。";
    }

    const form = el("form");
    form.style.display = "flex";
    form.style.flexDirection = "column";
    form.style.gap = "1rem";

    const fieldLabel = el("label");
    fieldLabel.style.display = "flex";
    fieldLabel.style.flexDirection = "column";
    fieldLabel.style.gap = "0.4rem";
    fieldLabel.style.fontWeight = "600";
    fieldLabel.style.fontSize = "0.9rem";
    fieldLabel.textContent = "Entra 存取權杖 (Bearer Token)";

    const textarea = document.createElement("textarea");
    textarea.rows = 4;
    textarea.placeholder = "請貼上 Bearer Token (eyJhbGciOi...)";
    textarea.style.fontFamily = "var(--mono, monospace)";
    textarea.style.fontSize = "0.82rem";
    textarea.style.padding = "0.75rem";
    textarea.style.borderRadius = "var(--radius-sm, 8px)";
    textarea.style.border = "1px solid var(--border-strong, #cbd5e1)";
    textarea.style.resize = "vertical";
    textarea.style.width = "100%";
    textarea.required = true;

    const preview = el("div");
    preview.style.fontSize = "0.8rem";
    preview.style.minHeight = "1.5rem";
    preview.style.color = "var(--muted, #64748b)";

    function updatePreview() {
      const val = textarea.value.trim();
      if (!val) {
        preview.textContent = "";
        return;
      }
      const parsed = parseJwt(val);
      if (!parsed) {
        preview.textContent = "非標準 JWT 格式（送出後將由後端伺服器驗證）";
        preview.style.color = "var(--muted, #64748b)";
        return;
      }
      const details = getTokenExpiryDetails(val);
      if (details.isExpired) {
        preview.textContent = `⚠️ 權杖已於 ${details.formatted} 過期 (${details.name})`;
        preview.style.color = "var(--danger, #dc2626)";
      } else {
        preview.textContent = `✓ 身分: ${details.name} ｜ ⏰ 有效期限至: ${details.formatted}`;
        preview.style.color = "var(--success, #059669)";
      }
    }
    textarea.addEventListener("input", updatePreview);
    fieldLabel.append(textarea);

    const errorBox = el("div");
    errorBox.style.color = "var(--danger, #dc2626)";
    errorBox.style.fontSize = "0.85rem";
    errorBox.style.display = "none";

    const actions = el("div");
    actions.style.display = "flex";
    actions.style.justifyContent = "flex-end";
    actions.style.gap = "0.75rem";
    actions.style.marginTop = "0.5rem";

    if (reauth) {
      const cancelBtn = el("button", "btn-secondary", "取消");
      cancelBtn.type = "button";
      cancelBtn.addEventListener("click", () => {
        root.hidden = true;
        root.replaceChildren();
        reject(new Error("UNAUTHORIZED"));
      });
      actions.append(cancelBtn);
    }

    const submitBtn = el("button", "primary-btn", "確認登入");
    submitBtn.type = "submit";
    submitBtn.style.padding = "0.6rem 1.4rem";
    actions.append(submitBtn);

    form.append(fieldLabel, preview, errorBox, actions);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const token = textarea.value.trim();
      if (!token) return;

      const details = getTokenExpiryDetails(token);
      if (details && details.isExpired) {
        errorBox.textContent = `此權杖已於 ${details.formatted} 過期，請提供有效權杖。`;
        errorBox.style.display = "block";
        return;
      }

      submitBtn.disabled = true;
      submitBtn.textContent = "驗證中...";
      errorBox.style.display = "none";

      try {
        const testRes = await fetch("/api/capabilities", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (testRes.status === 401 || testRes.status === 403) {
          throw new Error("身分驗證失敗：伺服器驗簽未通過 (401 Unauthorized)。請確認權杖是否有效。");
        }
        saveAuthHeaders({ bearerToken: token });
        root.hidden = true;
        root.replaceChildren();
        resolve(token);
      } catch (err) {
        errorBox.textContent = err.message || "驗證失敗，請檢查權杖。";
        errorBox.style.display = "block";
        submitBtn.disabled = false;
        submitBtn.textContent = "確認登入";
      }
    });

    box.append(header, notice, form);
    root.append(box);

    setTimeout(() => textarea.focus(), 50);
  });
}

export async function ensureAuth(authConfig) {
  const mode = (authConfig?.authMode || "HEADER").toUpperCase();
  if (mode === "ENTRA") {
    const stored = loadAuthHeaders();
    if (stored.bearerToken && !isTokenExpired(stored.bearerToken)) {
      scheduleExpiryWatcher(stored.bearerToken);
      return;
    }
    const token = await showEntraLoginModal({
      message: stored.bearerToken ? "您的 Entra 存取權杖已過期，請重新輸入以繼續作業。" : undefined,
      reauth: !!stored.bearerToken,
    });
    scheduleExpiryWatcher(token);
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
