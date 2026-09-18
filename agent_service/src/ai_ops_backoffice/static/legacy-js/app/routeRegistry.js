/**
 * Canonical route aliases for BU IA (U1).
 * Keeps legacy workspace/view hashes working; maps friendly aliases → view ids.
 */

const VIEW_ALIASES = {
  work: "workHub",
  "my-work": "workHub",
  workHub: "workHub",
  cases: "quality",
  improve: "quality",
  "improve-cases": "quality",
  // Keep `knowledge` as 內容成效 (classic). Content editing uses contentLists.
  "knowledge-content": "contentLists",
  docs: "contentLists",
  content: "contentLists",
  "content-lists": "contentLists",
  conversations: "conversations",
  chat: "conversations",
  evaluations: "evaluations",
  golden: "evaluations",
  analytics: "overview",
  analysis: "overview",
  "content-performance": "knowledge",
  performance: "knowledge",
};

/** Workspace used for hash URLs of BU-only views. */
const BU_VIEW_WORKSPACE = {
  workHub: "knowledge_ops",
  contentLists: "knowledge_ops",
};

/**
 * Map a raw path segment to a registered view id when it is an alias.
 * Unknown values pass through unchanged.
 */
export function resolveViewAlias(view) {
  const key = String(view || "").trim();
  if (!key) {
    return view;
  }
  return VIEW_ALIASES[key] || VIEW_ALIASES[key.toLowerCase()] || view;
}

export function workspaceForBuView(view) {
  return BU_VIEW_WORKSPACE[view] || null;
}

export function listViewAliases() {
  return { ...VIEW_ALIASES };
}
