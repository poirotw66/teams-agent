import {
  DashboardKpiMetrics,
  SpikeAlertItem,
  TopFrequentTopic,
  KnowledgeBlindSpot,
  KnowledgeGapItem,
} from "../types";
import { fetchOverview, postBroadcast } from "./overviewApi";
import { WorkbenchSliceContext } from "./storeCore";

export class OverviewSlice {
  constructor(private readonly ctx: WorkbenchSliceContext) {}

  public getKpis(): DashboardKpiMetrics {
    return { ...this.ctx.state.kpis };
  }

  public getSpikeAlert(): SpikeAlertItem | null {
    return this.ctx.state.spikeAlert ? { ...this.ctx.state.spikeAlert } : null;
  }

  public getTopTopics(): TopFrequentTopic[] {
    return [...this.ctx.state.topTopics];
  }

  public getBlindSpots(): KnowledgeBlindSpot[] {
    return [...this.ctx.state.blindSpots];
  }

  public getKnowledgeGaps(): KnowledgeGapItem[] {
    return [...this.ctx.state.gaps];
  }

  public async loadOverview(): Promise<void> {
    try {
      const data = await fetchOverview();
      if (data.kpis) {
        this.ctx.state.kpis = { ...this.ctx.state.kpis, ...data.kpis };
      }
      if (data.spikeAlert !== undefined) {
        this.ctx.state.spikeAlert = data.spikeAlert;
      }
      if (Array.isArray(data.topTopics)) {
        this.ctx.state.topTopics = data.topTopics;
      }
      if (Array.isArray(data.blindSpots)) {
        this.ctx.state.blindSpots = data.blindSpots;
      }
      if (Array.isArray(data.gaps)) {
        this.ctx.state.gaps = data.gaps;
      }
      this.ctx.notify();
    } catch (err) {
      console.error("Failed to load overview:", err);
      throw err;
    }
  }

  public async setSpikeBroadcast(
    message: string,
    durationHours: number = 2,
  ): Promise<{ expiresAt: string }> {
    const response = await postBroadcast(message, durationHours);
    const expiresAt =
      typeof response.expires_at === "string" && response.expires_at.trim()
        ? response.expires_at
        : new Date(Date.now() + durationHours * 3600 * 1000).toISOString();

    const displayExpires = expiresAt.includes("T")
      ? expiresAt.slice(0, 16).replace("T", " ")
      : expiresAt;

    if (this.ctx.state.spikeAlert) {
      this.ctx.state.spikeAlert.active_broadcast = {
        message,
        expires_at: displayExpires,
      };
      this.ctx.state.spikeAlert.is_active = true;
      this.ctx.notify();
    }
    void this.ctx.reloads.loadOverview();
    return { expiresAt: displayExpires };
  }

  public dismissSpikeAlert(): void {
    if (this.ctx.state.spikeAlert) {
      this.ctx.state.spikeAlert.is_active = false;
      this.ctx.notify();
    }
  }
}
