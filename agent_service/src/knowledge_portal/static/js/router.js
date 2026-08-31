let onRoute = null;

export function navigate(hash) {
  window.location.hash = hash.startsWith("#") ? hash : `#${hash}`;
}

export function parseRoute() {
  const raw = window.location.hash.replace(/^#/, "") || "/work";
  const [pathPart, queryPart = ""] = raw.split("?");
  const segments = pathPart.split("/").filter(Boolean);
  const query = new URLSearchParams(queryPart);
  return { segments, query, path: `/${segments.join("/")}` };
}

export function startRouter(renderShell) {
  onRoute = renderShell;
  async function render() {
    const context = parseRoute();
    const app = document.getElementById("app");
    if (!app || !onRoute) return;
    await onRoute({ ...context, app });
  }
  window.addEventListener("hashchange", render);
  render();
}

export function currentRoute() {
  return parseRoute();
}
