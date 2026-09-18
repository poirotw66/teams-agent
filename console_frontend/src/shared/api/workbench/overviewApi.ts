import { apiClient } from "../client";
import { OverviewApiResponse } from "./types";

export async function fetchOverview(): Promise<OverviewApiResponse> {
  return apiClient<OverviewApiResponse>("/api/console/workbench/overview");
}

export async function postBroadcast(
  message: string,
  durationHours: number,
): Promise<void> {
  await apiClient("/api/console/workbench/broadcast", {
    method: "POST",
    body: JSON.stringify({ message, durationHours }),
  });
}
