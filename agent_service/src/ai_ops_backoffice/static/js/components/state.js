import { el } from "../api.js";

/**
 * Render a compact loading state that communicates progress without implying
 * that the result set is empty.
 */
export function loadingState(message = "正在載入…", rows = 3) {
  const root = el("div", "bu-loading-state");
  root.setAttribute("role", "status");
  root.setAttribute("aria-live", "polite");
  root.setAttribute("aria-busy", "true");
  root.append(el("span", "bu-loading-label", message));
  const skeleton = el("div", "bu-skeleton-list");
  for (let index = 0; index < rows; index += 1) {
    const row = el("div", "bu-skeleton-row");
    row.append(
      el("span", "bu-skeleton-block bu-skeleton-block-wide"),
      el("span", "bu-skeleton-block"),
      el("span", "bu-skeleton-block bu-skeleton-block-short"),
    );
    skeleton.append(row);
  }
  root.append(skeleton);
  return root;
}
