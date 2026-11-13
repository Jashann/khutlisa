import type { DecisionCardData } from "../types";

export type RiskStatus = "held" | "suspended" | "paid_before" | "released" | "closed" | "clear";

export interface RiskClaim {
  id: string;
  state: string;
  created_at: string;
  /** A first name and initials. The full name is on the holder's main view. */
  claimant: string;
  country: string;
  amount: number;
  currency: string;
  holder_name: string | null;
  owner: string | null;
  status: RiskStatus;
  group: string | null;
  group_flagged: boolean;
  since: string | null;
  release: { at: string; reason: string } | null;
  events: { at: string; kind: string; note: string }[];
  sample: boolean;
  from_notice?: boolean;
  is_estate?: boolean;
}

export interface RiskSignal {
  kind: string;
  label: string;
  element: string;
  points: number;
}

export interface RiskShared extends RiskSignal {
  linking: boolean;
  claims: string[];
}

export interface PointsRow {
  kind: string;
  points: number;
  words: string;
  pairs: number;
  claims: number;
  elements: string[];
}

export interface RiskGroup {
  id: string;
  points: number;
  flagged: boolean;
  flag_at: number;
  table: PointsRow[];
  shared: RiskShared[];
  nodes: Pick<RiskClaim, "id" | "claimant" | "country" | "amount" | "currency" | "state" | "status" | "created_at" | "holder_name">[];
  edges: { a: string; b: string; linked: boolean; points: number; signals: RiskSignal[] }[];
  card: DecisionCardData;
  held_usd: number;
}

export interface RiskMeasurement {
  seed: number | null;
  ring_claims: number | null;
  ring_claims_caught: number | null;
  ring_claims_paid_before: number | null;
  honest_claims: number | null;
  honest_claims_held: number | null;
  rings: number | null;
  rings_flagged: number | null;
  measured_at: string | null;
}

export interface RiskView {
  counts: {
    claims: number;
    groups_flagged: number;
    groups_linked: number;
    held: number;
    suspended: number;
    released: number;
    paid_before: number;
    held_usd: number;
    paid_before_usd: number;
    from_notice?: number;
    estates?: number;
  };
  claims: RiskClaim[];
  groups: RiskGroup[];
  rule: { text: string; fixed: string; link_at: number; flag_at: number; points: { kind: string; points: number; words: string; linking: boolean }[] };
  demonstration: boolean;
  measurement: RiskMeasurement | null;
}
