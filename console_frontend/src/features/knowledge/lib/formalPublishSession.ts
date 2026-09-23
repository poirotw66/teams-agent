/** Session-scoped formal-publish progress (survives soft refresh in the same tab). */

const STORAGE_KEY = 'knowledge.formalPublish.inFlight';
const MAX_AGE_MS = 20 * 60 * 1000;

export type FormalPublishInFlight = {
  documentId: string;
  documentTitle: string;
  startedAtMs: number;
};

export function readFormalPublishInFlight(): FormalPublishInFlight | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as FormalPublishInFlight;
    if (
      !parsed ||
      typeof parsed.documentId !== 'string' ||
      typeof parsed.startedAtMs !== 'number'
    ) {
      return null;
    }
    if (Date.now() - parsed.startedAtMs > MAX_AGE_MS) {
      sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return {
      documentId: parsed.documentId,
      documentTitle: String(parsed.documentTitle || ''),
      startedAtMs: parsed.startedAtMs,
    };
  } catch {
    return null;
  }
}

export function startFormalPublishInFlight(
  documentId: string,
  documentTitle: string,
): FormalPublishInFlight {
  const payload: FormalPublishInFlight = {
    documentId,
    documentTitle,
    startedAtMs: Date.now(),
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  return payload;
}

export function clearFormalPublishInFlight(documentId?: string): void {
  const current = readFormalPublishInFlight();
  if (documentId && current && current.documentId !== documentId) {
    return;
  }
  sessionStorage.removeItem(STORAGE_KEY);
}
