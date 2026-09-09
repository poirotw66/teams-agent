/**
 * Shared chrome for system-admin pages under BU shell.
 */

import { el } from "../api.js";
import { isBuShellEnabled } from "./buShellConfig.js";

/**
 * Present a system-management page. Under BU shell, wraps with a consistent header.
 * Classic shell keeps the provided nodes as-is.
 */
export function presentSystemPage(title, subtitle, ...nodes) {
  const app = document.getElementById("app");
  if (!isBuShellEnabled()) {
    app.replaceChildren(...nodes.filter(Boolean));
    return;
  }
  const header = el("div", "bu-system-header");
  header.append(el("h2", "", title));
  if (subtitle) {
    header.append(el("p", "metric-label", subtitle));
  }
  const body = el("div", "bu-system-body");
  for (const node of nodes) {
    if (!node) continue;
    // Drop the first legacy page title so BU chrome owns the heading.
    if (node.querySelector) {
      const firstH2 = node.querySelector("h2");
      if (firstH2) {
        firstH2.remove();
      }
    } else if (node.tag === "h2" || node.tagName === "H2") {
      continue;
    }
    body.append(node);
  }
  app.replaceChildren(header, body);
}
