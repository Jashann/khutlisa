// Funding a claim on Metal: the types of the "Funded on Metal" panel and its calls. The holder's calls carry the
// holder's key, like the rest of the holder's view.
import { LockedError, payerKey } from "./api";
import type { QueueRow } from "./types";

export interface MetalScale { usd_per_usdz: string; words: string }

export interface MetalStatus {
  available: boolean;
  problem: string | null;
  network: string;
  label?: string;
  scale?: MetalScale;
  accounts?: { holder_account: string; settlement: string };
}

export interface MetalTerm { term: string; approval: string; mandate: string; same: boolean; source: string }

export interface MetalVerification {
  verified: boolean;
  problem?: string;
  at: string;
  command?: string;
  steps: { step: number; result: string; title: string; detail: string }[];
  lines: { kind: "payment" | "refusal"; reason: string | null; transaction: string; block: string; amount_usdz: string; to: string }[];
}

export interface MetalMandate {
  seq: number;
  mandate_id: string;
  status: "issued" | "bound" | "revoked" | "spent";
  signed_at: string | null;
  bind_transaction: string | null;
  bind_explorer: string | null;
  revoke_transaction: string | null;
  revoke_explorer: string | null;
  revoked_because: string | null;
  for_current_approval: boolean;
  terms: MetalTerm[];
  all_same: boolean;
  chain: { bound: boolean; revoked: boolean; spent_usdz: string; budget_usdz: string; payments: number; read_at: string } | null;
  chain_problem: string | null;
  verification: MetalVerification | null;
}

export interface MetalRefusal {
  at: string;
  case: string;
  staged: boolean;
  reason: string;
  words: string;
  transaction: string | null;
  explorer: string | null;
  recorded_on_chain: boolean;
  amount_usdz: string;
  payee: string;
}

export interface MetalPull {
  transaction: string;
  explorer: string;
  outcome: string;
  amount_usdz: string;
  stands_for_usd: string;
  approved_usd: string;
  at: string;
  payment_id: string;
  problem: string | null;
  checked: boolean | null;
  settlement: { status: string; block: string; submitter: string | null; transfers: { amount_usdz: string; from: string; to: string }[] } | null;
  verification: MetalVerification | null;
}

export interface MetalView {
  available: boolean;
  problem: string | null;
  label?: string;
  funding: "bank" | "metal";
  network?: string;
  chain?: string;
  token?: string;
  explorer?: string;
  scale?: MetalScale;
  accounts?: { holder_account: string; holder_explorer: string; settlement: string; settlement_explorer: string };
  mandate?: MetalMandate | null;
  earlier_mandates?: MetalMandate[];
  pull?: MetalPull | null;
  refusals?: MetalRefusal[];
  events?: { at: string; text: string; transaction?: string }[];
  enforced?: { by_chain: string[]; by_code: string[] };
  can?: { sign: boolean; revoke: boolean; verify: boolean; attempts: { key: string; label: string }[] } | null;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("Khutlisa's server could not be reached. Check that it is running, then try again.");
  }
  if (response.ok) return (await response.json()) as T;
  const detail = await response.json().then((b) => (typeof b.detail === "string" ? b.detail : ""), () => "");
  if (response.status === 401) throw new LockedError(detail);
  throw new Error(detail || "Khutlisa's server could not answer. Check that it is running, then try again.");
}

const asHolder = (method = "GET", body?: unknown): RequestInit => ({
  method,
  headers: { "X-Payer-Key": payerKey(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const getMetalStatus = () => call<MetalStatus>("/api/metal");
export const getClaimMetal = (id: string) => call<MetalView>(`/api/claims/${id}/metal`);
export const getHolderMetal = (id: string) => call<MetalView>(`/api/payer/claims/${id}/metal`, asHolder());
/** The holder approves the claim and funds it on Metal: the approval signs the mandate. */
export const approveOnMetal = (id: string) => call<QueueRow>(`/api/payer/claims/${id}/approve`, asHolder("POST", { funding: "metal" }));
export const signMandate = (id: string) => call<MetalView>(`/api/payer/claims/${id}/metal/mandate`, asHolder("POST"));
export const revokeMandate = (id: string) => call<MetalView>(`/api/payer/claims/${id}/metal/revoke`, asHolder("POST"));
export const verifyMandate = (id: string) => call<MetalView>(`/api/payer/claims/${id}/metal/verify`, asHolder("POST"));
export const attemptPull = (id: string, which: string) =>
  call<MetalView>(`/api/payer/claims/${id}/metal/attempt`, asHolder("POST", { case: which }));
