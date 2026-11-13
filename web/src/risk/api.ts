import { LockedError, payerKey } from "../api";
import type { RiskView } from "./types";

// The risk routes sit behind the holder's key, the same key the holder's main view asks for and keeps.
async function call(path: string, init: RequestInit = {}): Promise<RiskView> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers: { ...(init.headers ?? {}), "X-Payer-Key": payerKey() } });
  } catch {
    throw new Error("Khutlisa's server could not be reached. Check that it is running, then try again.");
  }
  const body = await response.json().catch(() => ({}));
  if (response.ok) return body as RiskView;
  if (response.status === 401) throw new LockedError(String(body.detail ?? ""));
  if (response.status === 422) throw new Error("Give a reason of 3 to 500 characters, then try again.");
  throw new Error(typeof body.detail === "string" ? body.detail : "Khutlisa's server could not answer. Try again in a moment.");
}

export const getRisk = () => call("/api/payer/risk");
export const releaseClaim = (id: string, reason: string) =>
  call(`/api/payer/risk/claims/${id}/release`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
