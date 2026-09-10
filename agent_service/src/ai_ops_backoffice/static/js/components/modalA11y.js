const FOCUSABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "object",
  "embed",
  "[contenteditable=\"true\"]",
  "[tabindex]:not([tabindex=\"-1\"])",
].join(",");

let activeModal = null;

function focusableElements(modal) {
  return [...modal.querySelectorAll(FOCUSABLE_SELECTOR)].filter((node) => {
    const style = window.getComputedStyle(node);
    return style.visibility !== "hidden" && style.display !== "none";
  });
}

function focusWithoutScroll(node) {
  if (!node || typeof node.focus !== "function") return;
  node.focus({ preventScroll: true });
}

function removeActiveModal(root, { restoreFocus = false } = {}) {
  if (!activeModal || activeModal.root !== root) return;
  root.removeEventListener("keydown", activeModal.onKeyDown, true);
  const previousFocus = activeModal.previousFocus;
  activeModal = null;
  if (restoreFocus && previousFocus?.isConnected) {
    focusWithoutScroll(previousFocus);
  }
}

/**
 * Apply the shared keyboard contract to any modal rendered into modal-root.
 * The helper is deliberately DOM-only so the auth bootstrap can use it too.
 */
export function openModalDialog(root, modal, { titleElement, initialFocus } = {}) {
  if (!root || !modal) return;

  const previousFocus =
    activeModal?.root === root
      ? activeModal.previousFocus
      : document.activeElement instanceof HTMLElement && !root.contains(document.activeElement)
        ? document.activeElement
        : null;
  removeActiveModal(root);

  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  if (!modal.hasAttribute("tabindex")) modal.setAttribute("tabindex", "-1");
  if (titleElement) {
    if (!titleElement.id) {
      titleElement.id = `modal-title-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    modal.setAttribute("aria-labelledby", titleElement.id);
  }

  const onKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeModalDialog(root);
      return;
    }
    if (event.key !== "Tab") return;

    const items = focusableElements(modal);
    if (!items.length) {
      event.preventDefault();
      focusWithoutScroll(modal);
      return;
    }

    const current = document.activeElement;
    const currentIndex = items.indexOf(current);
    if (event.shiftKey && (currentIndex <= 0 || currentIndex === -1)) {
      event.preventDefault();
      focusWithoutScroll(items.at(-1));
    } else if (!event.shiftKey && (currentIndex === items.length - 1 || currentIndex === -1)) {
      event.preventDefault();
      focusWithoutScroll(items[0]);
    }
  };

  activeModal = { root, modal, previousFocus, onKeyDown };
  root.addEventListener("keydown", onKeyDown, true);
  root.dataset.modalOpen = "true";

  queueMicrotask(() => {
    if (activeModal?.root !== root || root.hidden) return;
    const requested = typeof initialFocus === "function" ? initialFocus() : initialFocus;
    focusWithoutScroll(requested || focusableElements(modal)[0] || modal);
  });
}

export function closeModalDialog(root = document.getElementById("modal-root")) {
  if (!root) return;
  removeActiveModal(root, { restoreFocus: true });
  root.hidden = true;
  root.removeAttribute("data-modal-open");
  root.replaceChildren();
}
