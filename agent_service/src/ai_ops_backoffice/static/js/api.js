const DEFAULT_HEADERS = {
  "X-Backoffice-User-Id": "ops.analyst.demo",
  "X-Backoffice-User-Name": "Ops Analyst Demo",
  "X-Backoffice-Role": "SERVICE_OWNER",
  "X-Backoffice-Owner-Units": "IT Service Desk",
};

export { DEFAULT_HEADERS };

export async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...DEFAULT_HEADERS, ...(options.headers || {}) },
  });
  if (response.status === 403) {
    throw new Error("FORBIDDEN");
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
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
