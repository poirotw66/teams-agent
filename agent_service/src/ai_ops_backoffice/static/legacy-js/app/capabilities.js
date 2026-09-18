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
  if (capability === "bu.work.ui") {
    const caps = capabilities?.capabilities || [];
    return (
      canUseKnowledgeUi() ||
      caps.includes("ops.quality.read") ||
      caps.includes("ops.feedback.read") ||
      caps.includes("ops.evals.read") ||
      caps.includes("ops.faq.read")
    );
  }
  if (capability === "bu.quality.nav") {
    const caps = capabilities?.capabilities || [];
    return caps.includes("ops.quality.read") || caps.includes("ops.feedback.read");
  }
  return (capabilities?.capabilities || []).includes(capability);
}
