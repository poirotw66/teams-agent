import {
  DashboardKpiMetrics,
  SpikeAlertItem,
  TopFrequentTopic,
  KnowledgeBlindSpot,
  ConversationDetail,
  ItTicketItem,
  FaqItem,
  ManualDocumentItem,
  KnowledgeGapItem,
} from "../types";

/** Mutable workbench data shared by every domain slice. */
export type WorkbenchMutableState = {
  kpis: DashboardKpiMetrics;
  spikeAlert: SpikeAlertItem | null;
  topTopics: TopFrequentTopic[];
  blindSpots: KnowledgeBlindSpot[];
  conversations: ConversationDetail[];
  tickets: ItTicketItem[];
  faqs: FaqItem[];
  documents: ManualDocumentItem[];
  gaps: KnowledgeGapItem[];
};

export type NotifyFn = () => void;

/**
 * Cross-slice reload hooks filled by the facade after slices are constructed.
 * Placeholders avoid circular construction while preserving identical call sites.
 */
export type WorkbenchReloadHooks = {
  loadAll: () => Promise<void>;
  loadOverview: () => Promise<void>;
  loadTickets: () => Promise<void>;
  loadDocuments: () => Promise<void>;
};

export type WorkbenchSliceContext = {
  state: WorkbenchMutableState;
  notify: NotifyFn;
  reloads: WorkbenchReloadHooks;
};

const EMPTY_KPI: DashboardKpiMetrics = {
  total_inquiries_today: 0,
  inquiries_trend_percentage: 0,
  ai_resolution_rate: 0,
  ai_resolved_count: 0,
  escalated_ticket_count: 0,
  satisfaction_rate: 0,
  negative_feedback_count: 0,
  urgent_attention_count: 0,
};

/** Production-safe empty state — never seed demo/mock rows into the live store. */
export function createInitialWorkbenchState(): WorkbenchMutableState {
  return {
    kpis: { ...EMPTY_KPI },
    spikeAlert: null,
    topTopics: [],
    blindSpots: [],
    conversations: [],
    tickets: [],
    faqs: [],
    documents: [],
    gaps: [],
  };
}

export function createReloadHooksPlaceholder(): WorkbenchReloadHooks {
  const notWired = (name: string): (() => Promise<void>) => {
    return async () => {
      throw new Error(`Workbench reload hook "${name}" is not wired yet`);
    };
  };
  return {
    loadAll: notWired("loadAll"),
    loadOverview: notWired("loadOverview"),
    loadTickets: notWired("loadTickets"),
    loadDocuments: notWired("loadDocuments"),
  };
}

/**
 * Owns subscription, notification, and first-load flags for the workbench store.
 * Domain data lives on the shared mutable state object passed to slices.
 */
export class StoreCore {
  readonly state: WorkbenchMutableState = createInitialWorkbenchState();
  private listeners: Set<() => void> = new Set();
  private isLoaded: boolean = false;
  private loading: boolean = false;
  private loadStarted: boolean = false;
  private loadError: string | null = null;
  private loadAllHandler: (() => Promise<void>) | null = null;

  public setLoadAllHandler(handler: () => Promise<void>): void {
    this.loadAllHandler = handler;
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    this.ensureLoaded();
    listener();
    return () => this.listeners.delete(listener);
  }

  /** Start the first fetch when a UI surface actually subscribes. */
  public ensureLoaded(): void {
    if (this.isLoaded || this.loadStarted) {
      return;
    }
    if (!this.loadAllHandler) {
      return;
    }
    this.loadStarted = true;
    this.loadAllHandler().catch((err) => {
      this.loadStarted = false;
      const message =
        err instanceof Error ? err.message : "Workbench data load failed";
      this.setLoadError(message);
      console.warn("Workbench data load failed:", err);
      this.notify();
    });
  }

  public notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  public getIsLoaded(): boolean {
    return this.isLoaded;
  }

  public getIsLoading(): boolean {
    return this.loading;
  }

  public getLoadError(): string | null {
    return this.loadError;
  }

  public clearLoadError(): void {
    this.loadError = null;
  }

  public setLoadError(message: string): void {
    this.loadError = message;
  }

  public beginLoadAll(): void {
    this.loading = true;
    this.loadError = null;
  }

  public markLoaded(): void {
    this.isLoaded = true;
  }

  public endLoadAll(): void {
    this.loading = false;
    this.notify();
  }
}
