import type { DecisionCardData } from "../types";

export interface Amount { amount: string; currency: string }
export interface Step { n: number; section: string; url: string; text: string; gives: Record<string, string> }
export interface Person { id: string; name: string; alive: boolean | null; country?: string; children?: Person[]; children_known?: boolean }
export interface Family {
  decedent: { name: string; died_on: string; domicile_country: string; domicile_state: string };
  disposition: "intestate" | "will" | "court_order" | null;
  named_shares: { id: string; name: string; share: string; country?: string }[];
  property: "separate" | "community" | "quasi_community" | null;
  has_spouse: boolean | null;
  spouse: Person | null;
  children: Person[]; children_known: boolean;
  parents: Person[]; parents_known: boolean;
  siblings: Person[]; siblings_known: boolean;
  predeceased_spouse_recent: boolean | null;
  unusual: string[];
}
export interface TreeNode {
  id: string; parent: string | null; kind: "owner" | "spouse" | "child" | "parent" | "sibling" | "named";
  name: string; alive: boolean | null; country?: string; died_on?: string;
  heir?: boolean; relation?: string; share?: string; amount_usd?: string; currency?: string | null;
  indicative_local?: Amount | null; steps?: number[]; proven?: boolean; payable?: boolean; missing?: number;
  paid?: { amount: string; currency: string; at: string } | null;
}
export interface Link { label: string; basis?: string; status: string; files: string[]; facts: string[]; problems: string[] }
export interface HeirView {
  id: string; name: string; relation: string; share: string; country: string | null; country_name: string;
  email: string; entitlement: string; currency: string | null; can_be_paid_here: boolean;
  identity: Link; links: Link[];
  declaration: { label: string; needed: boolean; status: string; at: string | null; note: string };
  account: { label: string; status: string; currency: string | null };
  payee: { currency: string; account_name: string; account_number: string; bank_country: string; checked_by?: string } | null;
  proven: boolean; payable: boolean; paid: { amount: string; currency: string; at: string; transfer_id: string } | null;
  missing: string[];
}
export interface PlanLeg {
  heir: string; name: string; relation: string; share: string; entitlement: string; covered: boolean; leg_usd: string;
  currency: string; country: string; place: string; route: string; route_name: string; per_dollar: string;
  payout_fee: { amount: string; currency: string; basis: string }; expected_local: Amount;
  account: { name: string; number: string; country: string }; what_if: string | null;
}
export interface Plan {
  id: string; round: number; property_amount: string; holder_sends: string; holder_adds: string;
  expected_incoming_fee: string; net: string; paying_total: string; held_total: string;
  legs: PlanLeg[]; held: { heir: string; name: string; share: string; entitlement: string; missing: string[] }[];
  rounding_rule: string; fee_rule: string; if_things_change: string[]; tolerance_percent: string;
}
export interface LegView {
  heir: string; name: string; relation: string; share: string; currency: string; country: string; place: string;
  entitlement: string; planned_usd: string; leg_usd?: string; expected_local: Amount; route_name: string; state: string;
  refused_not_back?: boolean; transfer_status?: string | null; failure?: string | null; problem: string | null;
  local?: Amount | null; received?: Amount | null; payout_fee?: Amount | null; funds?: Amount | null;
  account: { name: string; number: string; country: string };
  hold?: { kind: string; needs: string[]; needs_words: string[]; replacement?: { would_receive: Amount; agreed: string; shortfall_percent: string; family_asked: boolean; tolerance_percent: string | null } } | null;
  journey: { key: string; label: string; done: boolean; at?: string | null }[];
  attempts?: { account_last4: string | null; reason: string; came_back: Amount }[];
  decisions?: { kind: string; text: string }[];
}
export interface RoundView {
  n: number; state: string; plan: Plan; cards: DecisionCardData[]; reference?: string;
  arrived?: { deposit: string; incoming_fee: string; net: string } | null; held_because?: string | null;
  events: { at: string; text: string; heir: string | null }[]; legs: LegView[]; waiting: string[];
}
export interface Reconciliation {
  lines: { id: string; who: string; part: string; type: string; description: string; amount: string; currency: string; at: string }[];
  sums: { currency: string; came_in: string; went_out: string; left: string }[];
  balanced: boolean; accounted_for: boolean; statement: string;
  held: { name: string; amount: string; currency: string }[];
}
export interface SettlementView {
  started: boolean; rounds: RoundView[]; plan: Plan | null; plan_cards?: DecisionCardData[]; running: boolean;
  problem: string | null; reconciliation: Reconciliation | null; paid: Record<string, { amount: string; currency: string }>;
}
export interface EstateDocument {
  id: string; kind: string; kind_label: string; filename: string; status: string; summary?: string;
  people: { name: string; role: string }[]; agreement?: string;
}
export interface EstateView {
  claim_id: string; state: string; sample: boolean; amount: string; currency: string;
  record: { owner: string; holder_name: string; property_type: string; owner_city?: string; owner_region?: string };
  claimant: { name: string };
  family: Family; tree: TreeNode[];
  succession: { computed: boolean; basis: string | null; steps: Step[]; flags: { key: string; text: string; url: string; section: string }[];
    refusal: { reason: string; section: string | null; url: string | null } | null; needs_person: boolean };
  question: { key: string; about: string | null; english: string; question: string; in_their_language: boolean; remaining: number } | null;
  intake: { words: string; language: string; english: string };
  heirs: HeirView[];
  estate_proof: { items: (Link & { key: string })[]; ready: boolean };
  proof_ready: boolean; payable: string[]; held: string[]; remaining_risk: string; decided_by: string;
  documents: EstateDocument[]; document_kinds: { kind: string; label: string }[];
  approval: { at: string; amount: string; shares: Record<string, string>; proven: Record<string, boolean>; documents: number; terms_hash: string; deadline_at: string | null } | null;
  approvals_withdrawn: { at: string; because: string }[];
  other_law: { flag: { text: string; url: string } | null; acknowledged: { reason: string; at: string } | null };
  fee_rule: { small_claim_usd: string | null; words: string }; rounding_rule: string;
  declaration: { points: string[]; note: string };
  corridors: { currency: string; country: string; place: string }[];
  settlement: SettlementView;
  history: { at: string; note: string }[];
}
export interface SampleBank { currency: string; first_name: string; last_name: string; account_number: string; [key: string]: string }
export interface EstateSample {
  owner: string; about: string; language: string; words: string; answer: string; family: Partial<Family>;
  record_id?: string; claimant?: { name: string; address: string; country: string; email: string; relationship: "heir" };
  search?: Record<string, unknown>;
  estate_documents: { file: string; kind: string; label: string }[];
  heirs: { id: string; name: string; country: string; email: string; later?: boolean; bank: SampleBank; bank_corrected?: SampleBank;
    documents: { file: string; kind: string; label: string }[] }[];
}
