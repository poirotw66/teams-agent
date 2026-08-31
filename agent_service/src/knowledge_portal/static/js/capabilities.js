import { getSession } from "./session.js";

const DEFAULT_CAPABILITIES = {
  create_document: false,
  import_markdown: false,
  list_pending_reviews: false,
  decide_review: false,
  publish: false,
  list_releases: false,
  manage_releases: false,
  view_audit: false,
};

export function getCapabilities() {
  return { ...DEFAULT_CAPABILITIES, ...(getSession().capabilities || {}) };
}

export function can(capability) {
  return Boolean(getCapabilities()[capability]);
}
