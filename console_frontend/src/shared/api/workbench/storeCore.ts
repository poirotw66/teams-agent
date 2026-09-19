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
import {
  initialDashboardKpi,
  initialSpikeAlert,
  initialTopTopics,
  initialBlindSpots,
  initialConversations,
  initialTickets,
  initialFaqs,
  initialDocuments,
  initialKnowledgeGaps,
} from "../mockData";

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

export function createInitialWorkbenchState(): WorkbenchMutableState {
  return {
    kpis: { ...initialDashboardKpi },
    spikeAlert: initialSpikeAlert,
    topTopics: [...initialTopTopics],
    blindSpots: [...initialBlindSpots],
    conversations: [...initialConversations],
    tickets: [...initialTickets],
    faqs: [...initialFaqs],
    documents: [...initialDocuments],
    gaps: [...initialKnowledgeGaps],
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
      console.warn("Workbench data load failed:", err);
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

  public beginLoadAll(): void {
    this.loading = true;
  }

  public markLoaded(): void {
    this.isLoaded = true;
  }

  public endLoadAll(): void {
    this.loading = false;
    this.notify();
  }
}
