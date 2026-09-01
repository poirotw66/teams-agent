import { escapeHtml } from "./ui.js?v=20260831e";

const FLUENT_BUNDLE = "/static/vendor/fluent-web-components.min.js";

let fluentPromise = null;

export function loadFluentComponents() {
  if (customElements.get("fluent-button")) {
    return Promise.resolve();
  }
  if (!fluentPromise) {
    fluentPromise = import(FLUENT_BUNDLE).then(() => {
      window.__fluentComponentsLoaded = true;
    });
  }
  return fluentPromise;
}

export function fluentButton(
  label,
  {
    appearance = "accent",
    id = "",
    className = "",
    dataset = {},
    type = "button",
    disabled = false,
  } = {},
) {
  const dataAttrs = Object.entries(dataset)
    .map(([key, value]) => ` data-${key}="${escapeHtml(value)}"`)
    .join("");
  return `<fluent-button appearance="${appearance}" type="${type}"${id ? ` id="${escapeHtml(id)}"` : ""}${className ? ` class="${escapeHtml(className)}"` : ""}${disabled ? " disabled" : ""}${dataAttrs}>${escapeHtml(label)}</fluent-button>`;
}

export function fluentTextField(label, { id, value = "", type = "text", multiline = false, rows = 3 } = {}) {
  if (multiline) {
    return `
      <fluent-text-area id="${escapeHtml(id)}" rows="${rows}">${escapeHtml(value)}</fluent-text-area>
      <span slot="label">${escapeHtml(label)}</span>`;
  }
  return `
    <fluent-text-field id="${escapeHtml(id)}" type="${type}" value="${escapeHtml(value)}">
      ${escapeHtml(label)}
    </fluent-text-field>`;
}

export function fluentBadge(label, { appearance = "neutral" } = {}) {
  return `<fluent-badge appearance="${appearance}">${escapeHtml(label)}</fluent-badge>`;
}
