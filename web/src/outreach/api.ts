// The holder's own list, the notices, and the owner's answer: the calls and the shapes they return.
import { LockedError, payerKey } from "../api";
import type { Claimant, DecisionCardData, History } from "../types";

export interface FieldChoice { column: string; source: "model" | "title" | "values" | "remembered" }
export interface Proposal {
  by: "model" | "code" | "remembered";
  fields: Record<string, FieldChoice>;
  notes: string;
  model_note: string;
  sample_rows_sent: number;
  missing: string[];
  unused_columns: string[];
  defaults: Record<string, string>;
}
export interface FailureKind { reason: string; rows: number; first_rows: number[] }
export interface ListView {
  id: string; filename: string; uploaded_at: string; kind: "csv" | "excel"; invented: boolean;
  header: string[]; header_row: number; rows_read: number; file_notes: string[]; proposal: Proposal;
  state: "uploaded" | "confirmed"; confirmed_at?: string | null; mapping: Record<string, string> | null; defaults: Record<string, string>;
  notes: string[]; fields: { key: string; label: string; about: string }[];
  kinds: { key: string; label: string; years: number }[]; first_rows: string[][];
  valid: number; failed: number; failures: FailureKind[];
}
export interface Group { balances: number; amount: string }
export interface Picture {
  today: string; all: Group; abroad: Group; home: Group;
  abroad_due_soon: Group & { handover: string | null; days: number | null };
  abroad_under_minimum: Group; abroad_window_open: Group;
  by_status: (Group & { status: string; words: string; abroad: Group })[];
  by_country: (Group & { code: string; name: string; due_soon: Group })[];
  by_due_date: (Group & { handover: string; days: number; abroad: Group })[];
  by_kind: (Group & { kind: string; label: string; years: number })[];
  calendar: { next_notice_report: string; notice_window: [string, string]; next_handover: string; assumption: string };
}
export interface QueueRow {
  row: number; name: string; city: string; country: string; country_name: string; amount: string; kind: string;
  years: number; last_activity: string; status: string; status_words: string; handover: string; handover_words: string;
  days_to_state: number; notice_required: boolean; window: string; has_email: boolean; has_phone: boolean;
  notice: { id: string; state: string; sent: boolean } | null;
}
export interface NoticeLanguage { code: string; name: string; native: string; reason: string; translated: boolean; note: string }
export interface Delivery { channel: string; counts: boolean; basis: string }
export interface NoticeRow {
  id: string; row: number; name: string; country: string; country_name: string; amount: string; handover: string;
  handover_words: string; days_to_state: number; language: NoticeLanguage; state: "ready" | "held";
  problems: string[]; warnings: string[]; delivery: Delivery[]; timing: { kind: string; text: string };
  stage: string; stage_words: string; sent: { on: string; channel: string; reminder: boolean }[];
  opened_at: string | null; responded_at: string | null; claim_id: string | null; code: string; reminders_sent: number;
}
export interface NoticeText {
  heading: string; reminder: string; facts: { label: string; value: string }[];
  paragraphs: { key: string; text: string; strong: boolean }[]; ui: Record<string, string>;
}
export interface NoticeDetail extends NoticeRow {
  elements: { key: string; title: string; source: string; present: boolean }[];
  views: { english: NoticeText; other?: NoticeText }; link: string; letter_url: string;
}
export interface Funnel {
  stages: { key: string; words: string; notices: number; amount: string }[];
  held: number; days_left: number; handover_date: string; date_words: string;
}
export interface OutreachRules { notice_minimum_usd: string; reminder_after_days: number; reminders_most: number; hold_answered: boolean }
export interface HolderDetails { name: string; street: string; city: string; region: string; postcode: string; country: string; contact: string; email: string; phone: string }
export interface LawLine { title: string; mark: string; text: string; source: string; url: string }
export interface Outreach {
  list: ListView | null; picture: Picture | null; queue: QueueRow[]; queue_total?: number;
  notices: null | {
    count: number; ready: number; held: number; stale: number; to_prepare: number; unsent: number;
    languages: { language: string; notices: number }[]; funnel: Funnel; cards: DecisionCardData[]; rows: NoticeRow[];
  };
  settings: { holder: HolderDetails | null; rules: OutreachRules; rules_set: boolean; in_words: string[] };
  holder: HolderDetails | null;
  handover: { handover_date: string; document_days: number; days_left: number; date_words: string };
  sends_nothing: string; demo_only: boolean; public_url: string; invented_file: { name: string; url: string }; law: LawLine[];
  prepared?: { notices: number; ready: number; held: number; amount: string; card: DecisionCardData };
  marked?: number;
}
export interface OwnerNotice {
  code: string; language: NoticeLanguage; views: { english: NoticeText; other?: NoticeText };
  amount: string; currency: string; holder: string; deadline: string; deadline_words: string; days_left: number;
  country: string; claim_id: string | null; demonstration: boolean;
}
export interface Mode { public_demo: boolean; notice: string; holder_key: string | null; model: { available: boolean; calls_left_today: number | null; note?: string }; register_loaded: boolean }

async function read<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  const body = await response.json().catch(() => ({}));
  const detail = typeof body.detail === "string" ? body.detail : "";
  if (response.status === 401) throw new LockedError(detail);
  throw new Error(detail || "Khutlisa's server could not answer. Check that it is running, then try again.");
}
const asHolder = (init: RequestInit = {}): RequestInit => ({ ...init, headers: { ...(init.headers ?? {}), "X-Payer-Key": payerKey() } });
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const call = <T,>(path: string, init?: RequestInit) => fetch(path, init).then((r) => read<T>(r));

export const getOutreach = () => call<Outreach>("/api/holder/outreach", asHolder());
export const uploadList = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return call<Outreach>("/api/holder/list", asHolder({ method: "POST", body: form }));
};
export const loadInvented = () => call<Outreach>("/api/holder/list/invented", asHolder({ method: "POST" }));
export const confirmMapping = (id: string, mapping: Record<string, string | null>, defaults: Record<string, string | null>) =>
  call<Outreach>(`/api/holder/list/${id}/mapping`, asHolder(json("PUT", { mapping, defaults })));
export const saveOutreachSettings = (body: { holder?: HolderDetails; rules?: OutreachRules }) =>
  call<Outreach>("/api/holder/outreach/settings", asHolder(json("PUT", body)));
export const prepareNotices = () => call<Outreach>("/api/holder/notices/prepare", asHolder(json("POST", {})));
export const getNotice = (id: string) => call<NoticeDetail>(`/api/holder/notices/${id}`, asHolder());
export const markSent = (body: { ids?: string[]; all_unsent?: boolean; channel?: string; reminder?: boolean }) =>
  call<Outreach>("/api/holder/notices/sent", asHolder(json("POST", body)));
export const findNotices = (q: string) =>
  call<{ total: number; rows: NoticeRow[] }>(`/api/holder/notices?q=${encodeURIComponent(q)}`, asHolder());
export const getQueuePage = (id: string, offset: number) =>
  call<{ total: number; rows: QueueRow[] }>(`/api/holder/list/${id}/queue?offset=${offset}`, asHolder());
/** A PDF behind the holder's key, opened in a new tab. */
export async function openPdf(path: string): Promise<void> {
  const response = await fetch(path, asHolder());
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? "The letter could not be made.");
  const url = URL.createObjectURL(await response.blob());
  window.open(url, "_blank", "noopener");
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export const getOwnerNotice = (code: string) => call<OwnerNotice>(`/api/notices/${encodeURIComponent(code)}`);
export const answerNotice = (code: string, claimant: Claimant, history: History | null) =>
  call<{ claim_id: string; already: boolean }>(`/api/notices/${encodeURIComponent(code)}/answer`, json("POST", { claimant, history }));
export const getMode = () => call<Mode>("/api/mode");
