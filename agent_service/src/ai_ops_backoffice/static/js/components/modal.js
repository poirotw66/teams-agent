import { el } from "../api.js";

export function showContentModal(title, content) {
  // A few detail views naturally have a DOM node but no separate heading.
  // Keep the helper tolerant of that call shape so the modal never renders
  // `[object HTMLDivElement]` or an undefined body.
  const isDomNode = (value) => value && typeof value === "object" && value.nodeType === 1;
  if (content === undefined && isDomNode(title)) {
    content = title;
    title = "詳細內容";
  }
  if (!isDomNode(content)) {
    content = el("div", "empty", content == null ? "目前沒有可顯示的內容。" : String(content));
  }
  title = title == null || title === "" ? "詳細內容" : String(title);
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.replaceChildren();
  root.onclick = (e) => {
    if (e.target === root) {
      root.hidden = true;
      root.replaceChildren();
    }
  };
  const modal = el("section", "modal");
  const header = el("div", "modal-header");
  header.style.display = "flex";
  header.style.justifyContent = "space-between";
  header.style.alignItems = "center";
  header.style.marginBottom = "1rem";
  header.style.paddingBottom = "0.75rem";
  header.style.borderBottom = "1px solid var(--border-subtle, #e2e8f0)";

  const heading = el("h2", "", title);
  heading.style.margin = "0";

  const close = el("button", "btn-modal-close", "✕ 關閉");
  close.addEventListener("click", () => {
    root.hidden = true;
    root.replaceChildren();
  });
  header.append(heading, close);
  modal.append(header, content);
  root.append(modal);
}

export function closeContentModal() {
  const root = document.getElementById("modal-root");
  if (!root) return;
  root.hidden = true;
  root.replaceChildren();
}
