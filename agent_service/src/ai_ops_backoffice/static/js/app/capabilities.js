/** Shared actor capabilities loaded at boot. */

let capabilities = null;

export function getCapabilities() {
  return capabilities;
}

export function setCapabilities(next) {
  capabilities = next;
}

export function actorCapabilities() {
  return new Set(capabilities?.capabilities || []);
}

export function canUseKnowledgeUi() {
  if (!capabilities?.knowledgeBridgeEnabled) {
    return false;
  }
  return (capabilities.knowledgeCapabilities || []).includes("knowledge.read");
}

export function actorHasCapability(capability) {
  if (!capability) {
    return true;
  }
  if (capability === "knowledge.review.ui") {
    return canUseKnowledgeUi() && (capabilities.knowledgeCapabilities || []).includes("knowledge.review");
  }
  if (capability === "knowledge.ui") {
    return canUseKnowledgeUi();
  }
  if (capability === "content.hub") {
    return (
      canUseKnowledgeUi() ||
      (capabilities?.capabilities || []).includes("ops.faq.read")
    );
  }
  return (capabilities?.capabilities || []).includes(capability);
}
