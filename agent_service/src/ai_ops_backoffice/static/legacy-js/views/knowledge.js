import { el } from "../api.js";
import { createPageController } from "../app/lifecycle.js";

import {
  renderKnowledge,
  renderKnowledgeInventory,
  openDocumentPerformanceModal,
  renderDocumentPerformance,
} from "./knowledge/knowledgeList.js";
import {
  renderFaqManagement,
  showFaqCreateModal,
  showFaqEditModal,
  showFaqDetail,
  showFaqPerformanceModal,
} from "./knowledge/knowledgeEdit.js";
import {
  renderSyncManagement,
  showSyncDetail,
  showCreateSyncModal,
} from "./knowledge/knowledgeVersions.js";
import {
  renderKnowledgePortalEntry,
  renderKnowledgeDocument,
} from "./knowledge/knowledgePublish.js";
import { openSourceCitationModal } from "./knowledge/knowledgeSources.js";

export {
  renderKnowledgePortalEntry,
  renderKnowledgeDocument,
  renderFaqManagement,
  renderKnowledge,
  renderKnowledgeInventory,
  openDocumentPerformanceModal,
  renderDocumentPerformance,
  showFaqCreateModal,
  showFaqEditModal,
  showFaqDetail,
  showFaqPerformanceModal,
  renderSyncManagement,
  showSyncDetail,
  showCreateSyncModal,
  openSourceCitationModal,
};

function standaloneKnowledgePage(render) {
  const show = async () => {
    const panel = el("section", "panel");
    document.getElementById("app").replaceChildren(panel);
    await render(panel);
  };
  return createPageController({ enter: show, update: show, leave: async () => {} });
}

export const knowledgePage = createPageController({
  enter: async () => renderKnowledge(),
  update: async () => renderKnowledge(),
  leave: async () => {},
});

export const knowledgePortalPage = createPageController({
  enter: async () => renderKnowledgePortalEntry(),
  update: async () => renderKnowledgePortalEntry(),
  leave: async () => {},
});

export const knowledgeDocumentPage = createPageController({
  enter: async () => renderKnowledgeDocument(),
  update: async () => renderKnowledgeDocument(),
  leave: async () => {},
});

export const faqPage = standaloneKnowledgePage(renderFaqManagement);
export const syncPage = standaloneKnowledgePage(renderSyncManagement);

export function knowledgeSectionPage(sub) {
  return createPageController({
    enter: async () => renderKnowledgePortalEntry(sub),
    update: async () => renderKnowledgePortalEntry(sub),
    leave: async () => {},
  });
}
