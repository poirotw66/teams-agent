import { clearDirtyChecker, confirmLeaveIfDirty, isNavigationDirty } from "./dirty-state.js";

let onRoute = null;
let lastCommittedHash = window.location.hash || "#/work";
let suppressHashChange = false;

export function navigate(hash) {
  const next = hash.startsWith("#") ? hash : `#${hash}`;
  void attemptNavigation(next);
}

export async function attemptNavigation(next) {
  let target = next.startsWith("#") ? next : `#${next}`;
  if (target === lastCommittedHash && target === window.location.hash) {
    return true;
  }
  if (isNavigationDirty()) {
    const ok = await confirmLeaveIfDirty();
    if (!ok) {
      if (window.location.hash !== lastCommittedHash) {
        suppressHashChange = true;
        window.location.hash = lastCommittedHash;
      }
      return false;
    }
    clearDirtyChecker();
  }
  lastCommittedHash = target;
  if (window.location.hash !== target) {
    window.location.hash = target;
  } else {
    await renderCurrentRoute();
  }
  return true;
}

export function parseRoute() {
  const raw = window.location.hash.replace(/^#/, "") || "/work";
  const [pathPart, queryPart = ""] = raw.split("?");
  const segments = pathPart.split("/").filter(Boolean);
  const query = new URLSearchParams(queryPart);
  return { segments, query, path: `/${segments.join("/")}` };
}

async function renderCurrentRoute() {
  const context = parseRoute();
  const app = document.getElementById("app");
  if (!app || !onRoute) return;
  await onRoute({ ...context, app });
}

export function startRouter(renderShell) {
  onRoute = renderShell;
  lastCommittedHash = window.location.hash || "#/work";

  window.addEventListener("hashchange", () => {
    if (suppressHashChange) {
      suppressHashChange = false;
      return;
    }
    const next = window.location.hash || "#/work";
    if (next === lastCommittedHash) {
      void renderCurrentRoute();
      return;
    }
    void attemptNavigation(next);
  });

  void renderCurrentRoute();
}

export function currentRoute() {
  return parseRoute();
}

export function syncCommittedHash(hash) {
  lastCommittedHash = hash.startsWith("#") ? hash : `#${hash}`;
}
