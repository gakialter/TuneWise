import type { ProcessAwareDemoResponse } from "./types";

const PROCESS_AWARE_DEMO_ENDPOINT = "/api/demos/process-aware";

export async function fetchProcessAwareDemo(
  signal?: AbortSignal,
): Promise<ProcessAwareDemoResponse> {
  const response = await fetch(PROCESS_AWARE_DEMO_ENDPOINT, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });

  if (!response.ok) {
    throw new Error(`Request failed with HTTP ${response.status}.`);
  }

  return (await response.json()) as ProcessAwareDemoResponse;
}
