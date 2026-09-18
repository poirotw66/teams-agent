import { apiClient } from "../client";
import { ItTicketItem } from "../types";

export async function fetchTickets(): Promise<ItTicketItem[]> {
  return apiClient<ItTicketItem[]>("/api/console/workbench/tickets");
}

export async function postTicket(params: {
  conversationId?: string;
  title: string;
  reporterName: string;
  reporterDept: string;
  reporterExt?: string;
  category: "HARDWARE" | "ACCESS" | "NETWORK" | "SOFTWARE";
  assignedTeam: string;
  notes?: string;
}): Promise<ItTicketItem> {
  return apiClient<ItTicketItem>("/api/console/workbench/tickets", {
    method: "POST",
    body: JSON.stringify(params),
  });
}
