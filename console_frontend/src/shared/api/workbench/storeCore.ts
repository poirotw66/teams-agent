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

export type WorkbenchDomain =
  | "overview"
  | "conversations"
  | "faqs"
  | "documents"
  | "tickets";

export const ALL_WORKBENCH_DOMAINS: readonly WorkbenchDomain[] = [
  "overview",
  "conversations",
  "faqs",
  "documents",
  "tickets",
] as const;

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
  loadFaqs: () => Promise<void>;
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
    loadFaqs: notWired("loadFaqs"),
    loadTickets: notWired("loadTickets"),
    loadDocuments: notWired("loadDocuments"),
  };
}

/**
 * Owns subscription, notification, and domain-load flags for the workbench store.
 * Domain data lives on the shared mutable state object passed to slices.
 */
export class StoreCore {
  readonly state: WorkbenchMutableState = createInitialWorkbenchState();
  private listeners: Set<() => void> = new Set();
  private loading: boolean = false;
  private loadError: string | null = null;
  private readonly loadedDomains = new Set<WorkbenchDomain>();
  private readonly inflightDomains = new Set<WorkbenchDomain>();
  private readonly domainErrors = new Map<WorkbenchDomain, string>();

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    listener();
    return () => this.listeners.delete(listener);
  }

  public notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  public getIsLoaded(): boolean {
    return this.loadedDomains.size > 0;
  }

  public getIsLoading(): boolean {
    return this.loading;
  }

  public getLoadError(): string | null {
    return this.loadError;
  }

  public getDomainErrors(): Partial<Record<WorkbenchDomain, string>> {
    return Object.fromEntries(this.domainErrors.entries());
  }

  public isDomainLoaded(domain: WorkbenchDomain): boolean {
    return this.loadedDomains.has(domain);
  }

  public clearLoadError(): void {
    this.loadError = null;
  }

  public setLoadError(message: string): void {
    this.loadError = message;
  }

  public beginLoad(): void {
    this.loading = true;
    this.loadError = null;
  }

  public endLoad(): void {
    this.loading = false;
    this.notify();
  }

  public markDomainLoaded(domain: WorkbenchDomain): void {
    this.loadedDomains.add(domain);
    this.domainErrors.delete(domain);
  }

  public markDomainFailed(domain: WorkbenchDomain, message: string): void {
    this.domainErrors.set(domain, message);
  }

  public beginDomainFetch(domain: WorkbenchDomain): boolean {
    if (this.loadedDomains.has(domain) || this.inflightDomains.has(domain)) {
      return false;
    }
    this.inflightDomains.add(domain);
    return true;
  }

  public endDomainFetch(domain: WorkbenchDomain): void {
    this.inflightDomains.delete(domain);
  }

  public domainsNeedingFetch(domains: readonly WorkbenchDomain[]): WorkbenchDomain[] {
    return domains.filter(
      (domain) => !this.loadedDomains.has(domain) && !this.inflightDomains.has(domain),
    );
  }

  public forceDomainsNeedingFetch(
    domains: readonly WorkbenchDomain[],
  ): WorkbenchDomain[] {
    for (const domain of domains) {
      this.loadedDomains.delete(domain);
      this.inflightDomains.delete(domain);
    }
    return [...domains];
  }

  public rebuildAggregateLoadError(): void {
    if (this.domainErrors.size === 0) {
      this.loadError = null;
      return;
    }
    const parts = [...this.domainErrors.entries()].map(
      ([domain, message]) => `${domain}: ${message}`,
    );
    this.loadError =
      this.domainErrors.size === ALL_WORKBENCH_DOMAINS.length
        ? "Workbench data load failed"
        : `Partial workbench load failure (${parts.join("; ")})`;
  }

  /** Clear identity-bound server caches without removing subscribers. */
  public resetServerState(): void {
    Object.assign(this.state, createInitialWorkbenchState());
    this.loading = false;
    this.loadError = null;
    this.loadedDomains.clear();
    this.inflightDomains.clear();
    this.domainErrors.clear();
    this.notify();
  }
}
