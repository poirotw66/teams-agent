import { apiClient } from "../client";
import { OverviewApiResponse } from "./types";

export async function fetchOverview(): Promise<OverviewApiResponse> {
  return apiClient<OverviewApiResponse>("/api/console/workbench/overview");
}

export type BroadcastResponse = {
  ok: boolean;
  expires_at: string;
};

export async function postBroadcast(
  message: string,
  durationHours: number,
): Promise<BroadcastResponse> {
  return apiClient<BroadcastResponse>("/api/console/workbench/broadcast", {
    method: "POST",
    body: JSON.stringify({ message, durationHours }),
  });
}
