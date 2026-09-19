import { ItTicketItem } from "../types";
import { fetchTickets, postTicket } from "./ticketsApi";
import { WorkbenchSliceContext } from "./storeCore";

export class TicketsSlice {
  constructor(private readonly ctx: WorkbenchSliceContext) {}

  public getTickets(): ItTicketItem[] {
    return [...this.ctx.state.tickets];
  }

  public async loadTickets(): Promise<void> {
    try {
      const items = await fetchTickets();
      if (Array.isArray(items)) {
        this.ctx.state.tickets = items;
        this.ctx.notify();
      }
    } catch (err) {
      console.error("Failed to load tickets:", err);
      throw err;
    }
  }

  public async escalateTicket(params: {
    conversationId?: string;
    title: string;
    reporterName: string;
    reporterDept: string;
    reporterExt?: string;
    category: "HARDWARE" | "ACCESS" | "NETWORK" | "SOFTWARE";
    assignedTeam: string;
    notes?: string;
  }): Promise<ItTicketItem> {
    const newTicket = await postTicket(params);

    this.ctx.state.tickets.unshift(newTicket);
    this.ctx.state.kpis.escalated_ticket_count += 1;

    if (params.conversationId) {
      const conv = this.ctx.state.conversations.find(
        (c) => c.id === params.conversationId,
      );
      if (conv) {
        conv.status = "ESCALATED_TICKET";
        conv.associated_ticket_id = newTicket.ticket_number;
        conv.messages.push({
          id: `msg-sys-${Date.now()}`,
          sender: "system",
          content: `已成功轉派開立 IT 工單 [${newTicket.ticket_number}]（指派：${params.assignedTeam}）`,
          timestamp: "剛剛",
        });
      }
    }

    this.ctx.notify();
    this.ctx.reloads.loadTickets().catch(() => {});
    return newTicket;
  }
}
