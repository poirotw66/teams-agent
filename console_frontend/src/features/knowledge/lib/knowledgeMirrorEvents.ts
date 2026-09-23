/** Browser event after Console-connected Agent Sync Now refreshes the GCS mirror. */

export const KNOWLEDGE_MIRROR_UPDATED_EVENT = 'knowledge-mirror-updated';

export function notifyKnowledgeMirrorUpdated(): void {
  window.dispatchEvent(new Event(KNOWLEDGE_MIRROR_UPDATED_EVENT));
}
