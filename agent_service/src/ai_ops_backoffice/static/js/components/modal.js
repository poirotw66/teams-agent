import { el } from "../api.js";

export function showContentModal(title, content) {
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
