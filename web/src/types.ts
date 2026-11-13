// The shapes the API sends and accepts. Keep these in step with src/khutlisa/server.py.

export interface PlaceEntry {
  city: string;
  region: string;
  postcode: string;
  country?: string;
  street?: string;
}

/** What a person tells us about their life. The form and the voice intake both produce this. */
export interface History {
  given_names: string[];
  family_names: string[];
  places: PlaceEntry[];
  employers: string[];
  current_country: string;
}

/** A place as the intake heard it: the search fields plus the years and the kind of stay, for the timeline. */
export interface HeardPlace extends PlaceEntry {
  from_year: number | null;
  to_year: number | null;
  what: string;
}

/** What POST /api/intake/text and /api/intake/audio return. Keep in step with intake.understand in intake.py. */
export interface IntakeResult {
  transcript: string;
  /** Everything said so far, sent back as `earlier` when a follow-up question is answered. */
  full_transcript: string;
  language: string;
  heard_language?: string;
  english: string;
  history: Omit<History, "places"> & { places: HeardPlace[] };
  follow_up: string;
  follow_up_english: string;
  /** What the question is for, told in code: "postcode" when a place was named without one. */
  follow_up_asks_for?: "postcode" | "more" | "";
  seconds: { understand: number; transcribe?: number };
}

/** What POST /api/intake/heard returns: the words the recogniser heard, and nothing from the language model. */
export interface HeardWords {
  transcript: string;
  heard_language: string;
  seconds: number;
}

export interface IntakeSample {
  language: string;
  text: string;
  speech_ready: boolean;
}

export interface CountryTotal {
  code: string;
  name: string;
  lat: number;
  lon: number;
  /** Properties with at least one owner in this country. A property is counted once however many owners it has. */
  properties: number;
  amount: number;
}

/** GET /api/totals. Every figure counts properties, each one once; `rule` says how in words. */
export interface Totals {
  source: string;
  /** True when these are the totals of the sample register of invented records. */
  sample?: boolean;
  /** Rows the search runs over: one for each owner of a property. */
  owner_rows: number;
  all_properties: number;
  all_amount: number;
  /** Properties with at least one owner whose last known address is in another country. */
  abroad_properties: number;
  abroad_amount: number;
  /** Properties listed under more than one country, and what they are worth counted once. */
  multi_country_properties: number;
  multi_country_amount: number;
  /** How much more the country lines add up to than `abroad_amount`. */
  multi_country_extra_amount: number;
  us_territories?: { properties: number; amount: number };
  rule: string;
  origin: { code: string; name: string; lat: number; lon: number };
  countries: CountryTotal[];
  other: { code: string; name: string; properties: number; amount: number; codes: number };
}

/** GET /api/register: the register the search runs over. `sample` is true for the register of invented records. */
export interface RegisterInfo {
  /** One owner record for each owner of a property. */
  owner_records: number;
  /** The same number under its older name. */
  records: number;
  sample: boolean;
  /** True when California's file is loaded on this server. Missing on servers without demonstration records. */
  loaded?: boolean;
  /** How many demonstration records are searched beside California's. They are never counted as California's. */
  demonstration_records?: number;
  /** Queensland's register, where it is loaded on this server. */
  queensland?: QueenslandFacts;
}

/** What one search ran over, for the line above the results. */
export interface Searched {
  register_loaded: boolean;
  owner_records: number;
  demonstration_records: number;
  /** Queensland's owner records, where its register is loaded. They were searched in the same pass. */
  queensland_records?: number;
  queensland_attribution?: string;
}

/** A demonstration person: invented, with prepared words and details for the "fill for me" controls. */
export interface DemoDocument {
  file: string;
  kind: string;
  label: string;
  order: "first" | "then" | "extra";
}
export interface DemoPerson {
  key: string;
  name: string;
  short_name: string;
  about: string;
  language: string;
  language_code: string;
  words: string;
  audio: string | null;
  answer: string;
  answer_audio: string | null;
  voice: string | null;
  /** Shown while her sound plays: the voice is synthetic and the words are what the recogniser heard. */
  spoken_note: string | null;
  /** Shown instead when the server has no speech engine: the words are the prepared text. */
  prepared_note: string | null;
  claimant: Claimant;
  bank: PayeeRequest;
  /** A second account in her own name, for the corrected details after a refused transfer. */
  bank_corrected?: PayeeRequest;
  main_record: string;
  documents: DemoDocument[];
}
export interface Demonstration {
  people: DemoPerson[];
  records: number;
  speech_ready?: boolean;
}

/** One prepared example of an organisation that appears as an owner in California's file. */
export interface NotableOrganisation {
  category: string;
  name: string;
  owner: string;
  amount: number;
  holder: string;
  city: string;
  region: string;
  country: string;
  country_name: string;
  abroad: boolean;
  property_type: string;
  properties_in_this_name: number;
  total_in_this_name: number;
  opening: boolean;
  /** Set in the leading group: a well-known owner whose money was reported by another well-known organisation. */
  pair?: boolean;
  /** The holder's name as a reader would write it, read by a person. */
  holder_shown?: string;
  properties_from_this_holder?: number;
  owners_on_record?: number;
}
export interface NotableSet {
  source: string;
  /** The date on California's file, and when the prepared set was read from it. */
  register_file_dated?: string;
  made_at?: string;
  rule: string;
  owner_records: number;
  categories: string[];
  examples: NotableOrganisation[];
  total: number;
  count: number;
  properties_in_these_names: number;
  total_in_these_names: number;
  check_url: string;
  queensland?: QueenslandExamples;
}
export interface OrganisationSearch {
  query: string;
  results: Match[];
  check_url: string;
  elapsed_ms: number;
  owner_records: number;
  /** The same search in Queensland's register, in Australian dollars, kept apart. */
  queensland?: { results: Match[]; currency: string; owner_records: number; attribution: string; claim_url: string };
}

export interface CountryName {
  code: string;
  name: string;
}

export interface Match {
  record_id: string;
  source: string;
  /** Masked to first letters unless the owner is an organisation. The API never sends a private full name. */
  owner: string;
  owner_is_organisation: boolean;
  amount: number;
  currency: string;
  holder_name: string;
  property_type: string;
  owner_city: string;
  owner_region: string;
  owner_country: string;
  /** The match strength number, 0 to 1: a sum of fixed points for named pieces of evidence. It orders the list. */
  score: number;
  /** The label, decided by the rule in `SearchResult.strength_rule` and never by the number. */
  strength: "strong" | "possible";
  /** True exactly when `strength` is "strong". The older name for the same thing. */
  above_line: boolean;
  reasons: string[];
  doubts: string[];
  /** On a strong match only: the one line saying that the proof file, not this label, decides. */
  note?: string;
  /** Added in the browser from /api/indicative: what the amount would become in the person's currency today. */
  indicative?: IndicativeAmount & { rate: number; label: string };
}

export interface SearchResult {
  /** No longer decides anything. Kept in the reply for older clients. */
  confidence_line: number;
  /** One sentence that states when a match is called strong. Shown on screen as it is. */
  strength_rule: string;
  /** The line every strong match carries. The same words are on each strong match as `note`. */
  strong_note?: string;
  found: number;
  found_is_capped: boolean;
  strong_count: number;
  strong_amount: number;
  possible_count: number;
  /** The same figures as `strong_count` and `strong_amount`, under their older names. */
  confident_count: number;
  confident_amount: number;
  currency: string;
  elapsed_ms: number;
  /** What this search ran over. Missing on older servers. */
  searched?: Searched;
  matches: Match[];
}

// ---- claims, payout and the payer's view. Keep in step with src/khutlisa/claims_api.py and payouts.py. ----

export type ClaimState =
  | "FOUND" | "PROOF_NEEDED" | "PROOF_READY" | "PACKET_READY" | "FILED" | "APPROVED" | "PAYING" | "PAID" | "REJECTED"
  | "PAYMENT_HELD";

export interface PublicRecord {
  /** Khutlisa's own id for the row. The State's property number is never sent to the browser. */
  record_id: string;
  source: string;
  owner: string;
  owner_is_organisation: boolean;
  amount: number;
  currency: string;
  holder_name: string;
  property_type: string;
  owner_city: string;
  owner_region: string;
  owner_country: string;
}

export interface Claimant {
  name: string;
  address: string;
  country: string;
  email: string;
  relationship: "self" | "heir";
}

export interface ChecklistItem {
  key: string;
  title: string;
  detail: string;
  required: boolean;
  kinds: string[];
  kind_labels: string[];
  status: "attached" | "still needed";
  files: string[];
  /** Set when the documents are read: what the proof file decided for this requirement. */
  proof?: ProofStatus;
  supports?: Support[];
}

// ---- document reading and the proof file. Keep in step with documents.py and proof.py. ----

export type ProofStatus = "satisfied" | "partly" | "missing";

export interface ReadAddress {
  street: string;
  city: string;
  region: string;
  postcode: string;
  country: string;
  whose: string;
}

/** What was read from one document. Only `status` is always there. Identity numbers are never included. */
export interface Reading {
  status: "reading" | "read" | "unreadable" | "failed" | "not_read";
  problem?: string;
  document_type?: string;
  names?: string[];
  addresses?: ReadAddress[];
  dates?: { label: string; value: string }[];
  issuer?: string;
  identifiers_present?: string[];
  legible?: boolean;
  concerns?: string[];
  concern_kinds?: string[];
  presents_as_government_photo_id?: boolean;
  photo_present?: boolean;
  marked_sample?: boolean;
  signs_of_editing?: boolean;
  summary?: string;
  /** Copied from the document for the checks in code: the main name field, the dates and the issuer. */
  holder_name?: string;
  issue_date?: string;
  expiry_date?: string;
  date_of_birth?: string;
  issuing_authority?: string;
  issuing_country?: string;
  /** The machine-readable lines of a passport, parsed in code, with the numbers hidden. */
  mrz?: { parsed: boolean; surname?: string; given_names?: string; issuing_state?: string; lines?: string[] } | null;
  /** The compared fields of the two separate readings. Missing on a document read before that was done. */
  readings?: Record<string, string>[];
  agreement?: { status: "agree" | "disagree" | "one_reading"; disagreed: string[] };
}

/** One check code makes on a document beside the reading. "held" means held for a person to look at. */
export interface DocumentCheck {
  key: "dates" | "name_two_places" | "issuer" | "two_readings";
  title: string;
  status: "passed" | "failed" | "held" | "not_applicable" | "not_checked";
  text: string;
}

/** Where a document stands. Held is its own answer, different from refused. */
export type DocumentStanding = "accepted" | "refused" | "held for a person to look at" | "read" | "being read" | "not read";

/** A document that is held for a person to look at, with the reasons. */
export interface HeldDocument {
  document_id: string;
  filename: string;
  kind_label: string;
  reasons: string[];
}

/** One document offered for one requirement: whether it settles it, and the visible facts and problems. */
export interface Support {
  document_id: string;
  filename: string;
  kind_label: string;
  settles: boolean;
  facts: string[];
  problems: string[];
}

export interface ProofGap {
  key: string;
  title: string;
  required: boolean;
  text: string;
  how: string;
}

export interface ProofCard {
  id: string;
  filename: string;
  kind_label: string;
  status: Reading["status"];
  supports: { key: string; title: string; settles: boolean; facts: string[]; problems: string[] }[];
  concerns: string[];
  marked_sample: boolean;
  /** What a document of this kind can carry as evidence, in words. */
  weight: string;
  /** True when a concern on this document stops the whole proof file until the document is removed. */
  holds_the_file_back: boolean;
  standing: DocumentStanding;
  /** Whether two separate readings were made ("once" only for a document read before that was done). */
  read: "twice" | "once" | null;
  checks: DocumentCheck[];
  held: boolean;
  held_reasons: string[];
}

export interface Proof {
  assessed: boolean;
  ready: boolean;
  readiness: "ready" | "not ready";
  /** The same verdict with "held for a person to look at" told apart from "not ready". */
  status: "ready" | "held for a person to look at" | "not ready";
  held: HeldDocument[];
  /** Two fixed sentences: what the reading does not show, and who decides. */
  remaining_risk: string;
  decided_by: string;
  reasons: string[];
  summary: string;
  required: number;
  satisfied: number;
  reading: number;
  requirements: { key: string; title: string; required: boolean; status: ProofStatus; supports: Support[] }[];
  record_link: { status: "matched" | "not shown"; text: string; document_ids: string[]; rests_on: string | null } | null;
  gaps: ProofGap[];
  documents: ProofCard[];
  samples: number;
}

/** The proof as the payer queue carries it. */
export interface ProofSummary {
  assessed: boolean;
  ready: boolean;
  readiness: "ready" | "not ready";
  status: Proof["status"];
  held: HeldDocument[];
  remaining_risk: string;
  decided_by: string;
  /** Each document with where it stands and the checks code made on it. */
  documents: Pick<ProofCard, "filename" | "kind_label" | "standing" | "read" | "checks" | "held" | "held_reasons">[];
  reasons: string[];
  summary: string;
  samples: number;
  record_link: Proof["record_link"];
  requirements: { key: string; title: string; required: boolean; status: ProofStatus; facts: string[]; problems: string[]; files: string[] }[];
  concerns: { filename: string; concerns: string[] }[];
}

export interface GuideStep {
  title: string;
  detail: string;
}

export interface Checklist {
  items: ChecklistItem[];
  required: number;
  attached: number;
  complete: boolean;
  missing: string[];
  notary: { required: boolean; title: string; detail: string };
  signing: GuideStep[];
  payment: string[];
  mail_to: string[];
  sources: { title: string; url: string }[];
}

export interface ClaimDocument {
  id: string;
  kind: string;
  kind_label: string;
  filename: string;
  content_type: string;
  size: number;
  uploaded_at: string;
  reading: Reading;
}

export interface ClaimEvent {
  state: ClaimState;
  at: string;
  note: string;
}

export interface MatchExplanation {
  score: number;
  strength?: "strong" | "possible" | null;
  reasons: string[];
  doubts: string[];
}

export interface Claim {
  /** The deadline choice while the holder has not decided: pay, ask for a document, or release to the State. */
  deadline?: DeadlineCard | null;
  id: string;
  state: ClaimState;
  created_at: string;
  record: PublicRecord;
  claimant: Claimant;
  match: MatchExplanation | null;
  /** The streets the person gave with their history, in their own words. Missing on older claims. */
  address_given?: { street: string; city: string; region: string; postcode: string }[];
  /**
   * Whether a street they gave matches the street on the record. It is compared on the server only once photo
   * identification that carries the name on the record has been read; until then the status is "waiting". The
   * street on the record is never sent.
   */
  address_check?: { status: "not_given" | "waiting" | "matches" | "does_not_match" | "no_street_on_record"; text: string };
  documents: ClaimDocument[];
  history: ClaimEvent[];
  rejection_reason: string | null;
  /** True when the record comes from the sample register of invented records. */
  sample: boolean;
  checklist: Checklist;
  /** `assessed` is false when the server runs with document reading switched off. */
  proof: Proof | { assessed: false };
  packet_url: string;
  payout_started: boolean;
  /** The bank account to be paid, with the number cut to its last four digits. */
  payee: Payee | null;
  /** The payer's approval and exactly what it covers. Any change to one of these withdraws it. */
  approval: Approval | null;
  approvals_withdrawn: { at: string; because: string }[];
  line: PropertyLine;
}

export interface Payee {
  currency: "PHP" | "MXN";
  account_name: string;
  account_number: string;
  bank_country: string;
  swift_code?: string | null;
  city?: string | null;
  set_at: string;
  checked_by: string;
}

/** The holder's standing instructions, as rules and as sentences. */
export interface InstructionRules {
  tolerance_percent: string;
  small_claim_usd: string;
  route_rule: "most_to_claimant" | "fixed";
  deadline_days: number;
  /** Sent with the instructions when the holder changes its handover date; kept beside them on the server. */
  handover_date?: string;
  document_days?: number;
}

export interface InstructionsView {
  handover: HandoverView;
  set: boolean;
  rules: InstructionRules | null;
  set_at: string | null;
  defaults: InstructionRules;
  in_words: string[];
  applies_to: string;
}

/** Who bears Airwallex's fees on one claim, what the holder sends, and the arithmetic in sentences. */
export interface FeeRule {
  bearer: "holder" | "claim";
  threshold: string | null;
  claim: string;
  holder_sends: string;
  holder_adds: string;
  expected_incoming_fee: string;
  expected_payout_fee_usd: string;
  left_for_claimant_usd: string;
  without_rule: { fees: string; share_percent: string };
  arithmetic: string[];
}

export interface IndicativeAmount {
  usd: string;
  holder_sends: Amount;
  fees: { incoming: string; payout: string; currency: string; borne_by: "holder" | "claim" };
  would_receive: Amount;
}

export interface Indicative {
  available: boolean;
  reason?: string;
  currency?: string;
  pair?: string;
  rate?: number;
  age_seconds?: number;
  label?: string;
  fees_note?: string;
  amounts: IndicativeAmount[];
}

/** The payout plan in summary, before the holder has approved. A plan: nothing has moved, no rate is locked. */
export interface PlanPreview {
  available: boolean;
  is_plan: true;
  label: string;
  reason?: string;
  claim: Amount;
  currency?: string;
  currency_from: string;
  rate?: number;
  pair?: string;
  rate_label?: string;
  holder_sends?: Amount;
  fees?: IndicativeAmount["fees"];
  fee_rule?: FeeRule;
  would_receive?: Amount;
  route?: string;
  state_fallback?: string;
  before_it_can_start: { what: string; done: boolean }[];
}

export interface HolderRow {
  name: string;
  properties: number;
  amount: number;
  spellings: number;
  as_written: string[];
}

export interface HoldersView {
  figures: {
    source: string;
    url: string;
    generated_at: string;
    properties: number;
    amount: number;
    holders_with_an_owner_abroad: number;
    passed_over_as_possibly_a_person: number;
    by_amount: HolderRow[];
    by_properties: HolderRow[];
    share_of_top_ten: { amount_percent: number; properties_percent: number };
    property_types: { type: string; properties: number; amount: number }[];
    families: { name: string; starts_with: string[] }[];
    kinds_of_money?: MoneyKind[];
    kinds_of_holder?: HolderKind[];
    wages?: { holders: number; properties: number; amount: number; top: { name: string; properties: number; amount: number }[] };
    kinds_source?: { label: string; url: string; read_on: string };
  };
  /** Who can pay by transfer today, what the law lets them do, and what it already asks of them. Each line has
   *  its source. Nothing here is a customer's figure. */
  buyer?: { who: string; why: { title: string; text: string; source: string; url: string }[]; not_stated: string; already_with_the_state: string };
  rule: string;
  /** The law in one or two plain sentences, with the handover schedule, each as verified at its source. */
  in_short: { pay: string; schedule: string; cheque: string; days_to_handover: number; handover_words: string; sources: { label: string; url: string }[] };
  status: string;
  law: { title: string; text: string; source: string; url: string; mark: "verified" | "our reading" }[];
  how_it_would_work: string[];
  proposed_pricing: { label: string; text: string };
  law_notes: string;
}

export interface Approval {
  instructions: { rules: InstructionRules; in_words: string[] } | null;
  deadline_at: string | null;
  fee_rule: FeeRule | null;
  at: string;
  amount: string;
  currency: string;
  claimant_name: string;
  documents: number;
  payee_currency: string | null;
  terms_hash: string;
  replaces_earlier_approval: boolean;
}

/** Where a claim stands among the claims on the same property. No other claimant is named. */
export interface PropertyLine {
  others: number;
  ahead: number;
  paid_elsewhere: boolean;
  held_elsewhere: boolean;
}

export interface DocumentKind {
  kind: string;
  label: string;
  weight: string;
}

export interface Amount {
  amount: string;
  currency: string;
}

export interface LedgerEntry {
  id: string;
  source_type?: string;
  transaction_type?: string;
  amount: number;
  currency: string;
  status?: string;
  settled_at?: string | null;
  created_at?: string | null;
  description?: string | null;
}

export interface TransferProof {
  id: string;
  short_reference_id?: string;
  status: string;
  transfer_amount?: number;
  transfer_currency?: string;
  amount_beneficiary_receives?: number;
  amount_payer_pays?: number;
  fee_amount?: number;
  fee_currency?: string;
  transfer_method?: string;
  reference?: string;
  dispatch_date?: string;
  updated_at?: string;
}

export interface JourneyStep {
  key: "arrived" | "fee" | "rate_locked" | "converted" | "sent" | "paid";
  label: string;
  done: boolean;
  at: string | null;
}

export interface PlanLine extends Amount {
  label: string;
  basis: string;
}

/** The written payout plan. Each figure says whether Airwallex has booked it or it is expected. */
export interface PayoutPlan {
  id: string;
  made_at: string;
  replacement: boolean;
  route: "pay_with_quote" | "convert_then_pay" | "pay_from_balance";
  route_name: string;
  route_reason: string;
  lines: PlanLine[];
  incoming_fee: (Amount & { basis: string }) | null;
  to_send: Amount;
  payout_fee: Amount & { basis: string };
  rate: { pair: string; client_rate: number; quote_id: string; locked_from: string | null; locked_until: string | null; locked_for: string } | null;
  expected_local: Amount;
  tolerance_percent: string;
  what_if: string | null;
  if_things_change: string[];
  /** Under standing instructions: every route that was compared, with what each would deliver. */
  routes_compared?: {
    route: string; route_name: string; available: boolean; chosen: boolean; why_not: string | null;
    payout_fee: (Amount & { basis: string }) | null; would_receive: Amount | null;
  }[] | null;
  fee_rule?: FeeRule | null;
  deadline_at?: string | null;
  instructions?: { rules: InstructionRules; in_words: string[] } | null;
}

/** One thing the payment machine decided by itself, inside the holder's standing instructions. */
export interface AgentDecision {
  at: string;
  kind: string;
  title: string;
  text: string;
  rule: string;
  rule_name: string;
}

export type WhatIf = "short_deposit" | "transfer_fails" | "transfer_returned" | "rate_lock_expires";

/** Why a payment has stopped, and who has to act before it carries on. */
export interface PayoutHold {
  kind: "short_deposit" | "deposit_differs" | "rate_lock_expired" | "amount_changed" | "transfer_failed" | "transfer_returned" | "deadline_passed"
    | "mandate_revoked" | "metal_refused" | "metal_settlement_differs";
  facts?: { claimant_asked?: boolean; shortfall_percent?: string; tolerance_percent?: string } | null;
  at: string;
  needs: ("bank_details" | "payer" | "claimant")[];
  needs_words: string[];
  explanation: string;
  worded_by: string;
  /** False for the first moments of a stop, while the plan is being worked out again. */
  ready: boolean;
  plan_id: string | null;
}

export interface PayoutAttempt {
  transfer_id: string;
  status: string;
  reason: string;
  fate: string;
  was_to_receive: Amount;
  came_back: Amount;
  fee_kept: (Amount & { paid_by?: string }) | null;
  at: string;
  /** The last four digits of the account the dead transfer went to. */
  account_last4?: string | null;
  outcome?: { agreed_local: string; replacement_local: string; shortfall_percent: string; tolerance_percent: string; claimant_asked: boolean };
}

/** A refused transfer as the holder's view shows it: the decision card with the two accounts. */
export interface RefusalCard extends DecisionCardData {
  asked: boolean | null;
  shortfall_percent?: string;
  tolerance_percent?: string | null;
  paid?: boolean;
  waiting_for_owner?: boolean;
  first_account: string | null;
  now_account: string | null;
  payout_state: string | null;
  needs: string[];
}

export interface ReconciliationLine {
  id: string;
  part: string;
  type: string;
  description: string;
  amount: string;
  currency: string;
  status: string;
  at: string | null;
}

export interface Reconciliation {
  lines: ReconciliationLine[];
  sums: { currency: string; came_in: string; went_out: string; left: string }[];
  balanced: boolean;
  statement: string;
}

export interface PayoutView {
  claim_id: string;
  claim_state: ClaimState;
  /** Paid as one payment of a batch the holder approved, from one deposit shared with other approved claims. */
  in_batch?: { id: string; n: number; note: string };
  environment: string;
  credentials_ready: boolean;
  running: boolean;
  problem: string | null;
  record_amount: number;
  record_currency: string;
  approved: boolean;
  approval: { at: string; amount: string; currency: string } | null;
  what_if_options: { key: WhatIf; label: string }[];
  started: boolean;
  /** PLANNED, DEPOSIT_EXPECTED ... PAID, HELD (paused for agreement) or FAILED (the bank refused or returned it). */
  state: string | null;
  plan: PayoutPlan | null;
  hold: PayoutHold | null;
  failure?: string | null;
  started_at?: string | null;
  steps?: { state: string; at: string; note: string }[];
  journey: JourneyStep[];
  confirmed?: { plan_id: string; local_amount: string; at: string; by?: string } | null;
  /** What the machine decided without asking, in the order it happened. */
  agent_report?: AgentDecision[];
  /** Each decision as four short lines. */
  cards?: DecisionCardData[];
  instructions?: { rules: InstructionRules; in_words: string[]; deadline_at: string | null } | null;
  /** The claim's own amount; the deposit can be larger when the holder bears the fees. */
  claim_usd?: string | null;
  agreed_and_paid?: { agreed: Amount; paid: Amount; difference: Amount; note: string } | null;
  route?: string | null;
  route_name?: string | null;
  what_if?: WhatIf | null;
  what_if_label?: string | null;
  decisions?: { at: string; kind: string; text: string; by?: string; rule?: string }[];
  attempts?: PayoutAttempt[];
  funds?: Amount | null;
  deposit?: Amount & { reference: string; id: string | null; expected: string; arrived: boolean };
  incoming_fee?: Amount | null;
  after_fee?: Amount | null;
  rate?: number | null;
  rate_pair?: string;
  rate_locked_until?: string | null;
  local?: Amount | null;
  payout_fee?: (Amount & { paid_by?: string | null }) | null;
  /** What left Khutlisa's Airwallex account for the transfer, the payout fee included, in its own currency. */
  left_wallet?: Amount | null;
  received?: Amount | null;
  transfer_status?: string | null;
  transfer_id?: string | null;
  paid_at?: string | null;
  watching_for_return?: boolean;
  account: { name: string; number: string; country: string; currency: string } | null;
  reconciliation?: Reconciliation;
  proof?: { transfer: TransferProof; financial_transactions: LedgerEntry[] } | null;
}

export interface PayeeRequest {
  currency: "PHP" | "MXN";
  first_name: string;
  last_name: string;
  account_number: string;
  swift_code: string;
  street_address: string;
  city: string;
  postcode: string;
  state: string;
}

export interface QueueRow {
  id: string;
  state: ClaimState;
  created_at: string;
  updated_at: string;
  amount: number;
  currency: string;
  /** Masked exactly as the search masks it, unless the owner is an organisation. */
  owner: string;
  owner_is_organisation: boolean;
  holder_name: string;
  property_type: string;
  record_id: string;
  sample: boolean;
  payout_started: boolean;
  claimant: { name: string; country: string; relationship: "self" | "heir" };
  claimant_country_name: string;
  proof: { required: number; attached: number; complete: boolean; missing: string[]; documents: number };
  proof_file: ProofSummary | { assessed: false };
  match: MatchExplanation | null;
  reasons: string[];
  doubts: string[];
  rejection_reason: string | null;
  payee: Payee | null;
  approval: Approval | null;
  approvals_withdrawn: { at: string; because: string }[];
  line: PropertyLine;
  /** Set while a payment is on hold: what changed, and what is held for the claim now. */
  hold: { kind: string; needs: string[]; explanation: string; funds: Amount | null; waiting_for_bank_details: boolean; expected_local: Amount | null } | null;
  /** The deadline choice while the claim is undecided, and the last refused transfer, as decision cards. */
  deadline?: DeadlineCard | null;
  refusal?: RefusalCard | null;
  fee_card?: DecisionCardData | null;
  can_decide: boolean;
  can_reject: boolean;
  last_event: ClaimEvent | null;
  /** What the standing instructions would mean for this claim if it were approved now. */
  fee_rule: FeeRule;
  is_estate?: boolean;
  risk?: { status?: string; events?: { at: string; kind: string; note: string }[] } | null;
  /** Paid together with other approved claims, as payment `n` of batch `id`. */
  batch?: { id: string; n: number } | null;
  /** Opened by the owner with the code on a notice the holder sent. */
  from_notice?: boolean;
  funding?: "bank" | "metal";
  /** Approved, with its account, and not yet paid: it can go into a batch with other approved claims. */
  can_batch?: boolean;
}

export interface PayerResults {
  claims: number;
  currency: string;
  rejected: number;
  payment_held: number;
  stages: { stage: "found" | "proven" | "filed" | "approved" | "paid"; count: number; amount: number }[];
  medians: { from: string; to: string; claims: number; median_seconds: number | null }[];
}

export interface PayerQueue {
  claims: QueueRow[];
  results: PayerResults;
  instructions: InstructionsView;
  handover: HandoverView;
  deadline_summary: (DeadlineCard & { near: boolean }) | null;
}

/** One decision of the agent as four short lines: what happened, what the limits allowed, what it did, the result
 *  in money. `why` is the longer explanation, folded away on screen. */
export interface DecisionCardData {
  kind: string;
  tone: "go" | "stop" | "ask";
  title: string;
  happened: string;
  allowed: string;
  did: string;
  money: string;
  why: string[];
  at?: string | null;
}

/** The deadline choice for one claim: a decision card with the days left before the handover to the State. */
export interface DeadlineCard extends DecisionCardData {
  choice: "pay" | "ask" | "release";
  days_left: number;
  date: string;
  date_words: string;
  document_days: number;
}

/** The holder's date for handing unclaimed property to the State, and California's schedule with its source. */
export interface HandoverView {
  handover_date: string;
  date_words: string;
  document_days: number;
  days_left: number;
  set_by: string;
  schedule: { notice: string; remit: string; source: string; url: string };
}

// ---- more than one register -------------------------------------------------------------------------------

/** Queensland's register as it is loaded on this server. Its money is Australian dollars and is never added to
 *  California's US dollars. */
export interface QueenslandFacts {
  source: string;
  name: string;
  owner_records: number;
  amount: number;
  currency: string;
  matches_portal?: boolean | null;
  loaded_at?: string | null;
  attribution: string;
  licence: string;
  licence_url: string;
  dataset: string;
  claim_url: string;
}

export interface QueenslandExample {
  owner: string;
  amount: number;
  currency: string;
  sent_by: string;
  received: string;
}

export interface QueenslandExamples {
  currency: string;
  owner_records: number;
  amount: number;
  examples: QueenslandExample[];
  attribution: string;
  licence: string;
  licence_url: string;
  dataset: string;
  claim_url: string;
  note: string;
}

// ---- the whole book of one holder, and a batch run from it ---------------------------------------------------

export interface BookHolder {
  key: string;
  name: string;
  properties: number;
  amount: number;
  countries: number;
  kind: string;
}

export interface BookHolders {
  top: BookHolder[];
  matches: BookHolder[];
  query: string;
  corridors_ready: boolean;
  discovered_at: string | null;
}

export interface BookInputs {
  tolerance_percent: string;
  small_claim_usd: string;
  handover_date: string;
  document_days: number;
}

interface Part {
  owners: number;
  usd: number;
}

export interface BookFee {
  usd: string;
  basis: "observed" | "estimate";
  documented_usd: string;
  seen: number;
  text: string;
}

export interface BookCorridor {
  country: string;
  name: string;
  currency: string | null;
  pay_currency: string | null;
  owners: number;
  usd: number;
  route: "LOCAL" | "SWIFT" | null;
  route_words: string;
  scheme: string | null;
  flight: { min: number; max: number; scheme: string; basis: string } | null;
  needs_days: number | null;
  in_time: boolean;
  fee: BookFee | null;
  fees: number;
  cost_per_payment: number | null;
  local: Part;
  swift: Part;
  unpayable: Part;
  too_small: Part & { would_cost: number };
  holder_bears: Part & { adds: number };
  from_claim: Part & { fees: number };
  over_local_limit: Part;
  planned: Part;
  too_late: Part;
  no_cash: number;
  owners_receive: { amount: number; currency: string } | null;
  why_not_local: string | null;
  why_unpayable: string | null;
  median_usd: number | null;
  rate: number | null;
}

export interface BookFundingLine {
  currency: string;
  payments: number;
  holder_sends: number;
  to_convert_usd: number;
  mode: "batch" | "each" | "none" | "unknown";
  mode_words: string;
  saving_usd: number;
  conversions: number;
  can_hold?: boolean | null;
  can_hold_basis?: string;
  quote?: { sell_usd: number; client_rate: number; mid_rate: number; at: string };
  each?: { buys: number; conversions: number };
  batch?: { buys: number; conversions: number };
  sizes?: { sell_usd: number; client_rate: number; mid_rate: number; spread_percent: number; at: string }[];
  rate_depends_on_size?: boolean;
  lock?: { min_1: number; hr_1: number; percent: number } | null;
  round_trip?: { sold_usd: number; back_usd: number; percent: number } | null;
}

export interface BookOrderLine {
  rank?: number;
  country: string;
  name: string;
  route: string;
  scheme: string | null;
  owners: number;
  usd: number;
  needs_days: number;
  rail_days: string;
  rail_basis: string;
  start_by_words: string;
  spare_days: number;
  usd_per_day: number;
}

export interface BookTotals {
  owners: number;
  usd: number;
  countries: number;
  local: Part & { countries: number };
  swift: Part & { countries: number };
  unpayable: Part & { countries: number };
  too_small: Part & { would_cost: number };
  no_cash: { owners: number };
  over_local_limit: Part;
  too_late: Part & { countries: number };
  planned: Part & { countries: number };
  holder_bears: Part & { adds: number };
  from_claim: { owners: number; fees: number };
  cost: { usd: number; percent: number; borne_by_holder: number; out_of_claims: number };
  holder_funds_usd: number;
  refusal: { inside: number; outside: number; inside_usd: number; outside_usd: number };
  estimated_fee_corridors: number;
  observed_fee_corridors: number;
}

export interface BookChange {
  what: string;
  before: string;
  after: string;
  delta: number;
}

export interface BookSliceRow {
  country: string;
  name: string;
  currency: string;
  method: string;
  claim_usd: string;
  scheme: string | null;
  amount_is: string;
}

export interface BookPlan {
  holder: BookHolder;
  statement: string;
  inputs: BookInputs;
  days_left: number;
  handover_words: string;
  corridors: BookCorridor[];
  totals: BookTotals;
  funding: {
    holder_funds_usd: number;
    incoming_fee_usd: number;
    currencies: BookFundingLine[];
    saving_usd: number;
    conversions_if_each: number;
    conversions_planned: number;
    batch_currencies: number;
    each_currencies: number;
    rate_depends_on_size: boolean;
    ahead_of_approvals: string;
  };
  order: { work: BookOrderLine[]; dropped: BookOrderLine[]; days_left: number; document_days: number; payments: number; machine: { text: string } };
  cards: DecisionCardData[];
  discovered_at: string | null;
  sandbox: string | null;
  sources: Record<string, { label: string; url: string }>;
  baseline: { inputs: BookInputs; totals: BookTotals; work: number };
  changes: BookChange[];
  slice: BookSliceRow[];
}

export interface BatchItem {
  n: number;
  /** Set when the payment is for a claim in the holder's own queue; a batch from the book pays demonstration owners. */
  claim_id: string | null;
  owner: { name: string; city: string; country: string; country_name: string; demonstration?: boolean };
  country: string;
  currency: string;
  method: string;
  scheme: string | null;
  claim_usd: string;
  amount_is: string | null;
  holder_sends: string;
  fees_borne_by: "holder" | "claim";
  planned: { incoming_fee_usd: string; payout_fee_usd: string; payout_fee_basis: string; owner_gets_usd: string };
  funded_by: "batch" | "each" | "none";
  allocation_usd: string | null;
  allocation_local: string | null;
  expected_local: Amount | null;
  account_last4: string;
  refused_last4: string | null;
  staged: string | null;
  state: string | null;
  state_words: string;
  needs: string[];
  transfer_id: string | null;
  paid: Amount | null;
  fee: { amount: string; currency: string } | null;
  attempts: { transfer_id: string; status: string; reason: string; account_last4: string | null; came_back: Amount; outcome?: { claimant_asked: boolean; shortfall_percent: string } }[];
  cards: DecisionCardData[];
  approved: boolean;
}

export interface BatchView {
  batch_id: string;
  holder: { key: string; name: string };
  state: string;
  state_words: string;
  created_at: string;
  finished_at: string | null;
  checked_at: string | null;
  statement: string;
  plan: { holder_funds_usd: string; fees_usd: string; payments: number; claims_usd: string; source?: "queue" };
  rules: InstructionRules;
  approval: { at: string; holds: boolean } | null;
  deposit: { reference: string; id: string | null; amount: string | null; fee: string | null; pool: string | null };
  funding: { currency: string; mode: "batch" | "each" | "none"; why: string; sell_usd?: string; buy?: string; client_rate?: number; payments?: number; conversion_id?: string }[];
  items: BatchItem[];
  paid: number;
  payments: number;
  waiting_for_people: number[];
  running: boolean;
  problem: string | null;
  reconciliation: {
    rows: number;
    sums: { currency: string; came_in: string; went_out: string; left: string }[];
    all_paid: boolean;
    balanced: boolean;
    lines: { id: string; type: string; amount: string; currency: string; part: string; at: string }[];
  };
  costs: {
    planned: { incoming_usd: string; payout_usd: string; usd: string; transfers: number };
    actual: { incoming_usd: string; payout_usd: string; usd: string; transfers: number; payout_fees: Amount[] };
    difference_usd: string;
    note: string;
  };
  decisions: { at: string; kind: string; text: string }[];
  api_calls: number;
}

export interface BatchList {
  batches: { batch_id: string; holder: { name: string }; state: string; state_words: string; payments: number; created_at: string }[];
}

/** The kinds of money and of holder on the "For holders" screen, computed from California's file. */
export interface MoneyKind {
  key: string;
  label: string;
  properties: number;
  amount: number;
  unverified_properties: number;
  unverified_amount: number;
}

export interface HolderKind {
  key: string;
  label: string;
  holders: number;
  properties: number;
  amount: number;
  top: { name: string; properties: number; amount: number }[];
}
