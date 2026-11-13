import type {
  BatchList, BatchView, BookHolders, BookInputs, BookPlan,
  Claim, Claimant, CountryName, Demonstration, DocumentKind, HeardWords, History, HoldersView, Indicative, InstructionRules,
  InstructionsView, IntakeResult, IntakeSample, Match, NotableSet,
  OrganisationSearch, PayeeRequest, PayerQueue, PayoutView, PlanPreview, QueueRow, RegisterInfo, SearchResult, Totals,
} from "./types";

/** The payer's routes answered 401: the key is missing or wrong. */
export class LockedError extends Error {}

async function read<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  if (response.status === 401) throw new LockedError(await response.json().then((b) => String(b.detail ?? ""), () => ""));
  let message = "Khutlisa's server could not answer. Check that it is running, then try again.";
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (typeof body.detail?.message === "string")
      message = [body.detail.message, ...(Array.isArray(body.detail.reasons) ? body.detail.reasons : [])].join(" ");
    else if (response.status === 422) message = unreadable(body.detail);
  } catch {
    // The reply was not JSON, so the general message stands.
  }
  throw new Error(message);
}

const FIELD_NAMES: Record<string, string> = {
  text: "your words",
  name: "your name", address: "your address", country: "your country", email: "your email address",
  relationship: "whether you are the owner or an heir", first_name: "the first name", last_name: "the last name",
  account_number: "the account number", swift_code: "the bank's SWIFT code", street_address: "the street address",
  city: "the city", reason: "the reason",
};

/** Turns the API's list of rejected fields into one sentence that names them. */
function unreadable(detail: unknown): string {
  const general = "Some of the details could not be read. Check the form and try again.";
  if (!Array.isArray(detail)) return general;
  const names = detail
    .map((d) => (Array.isArray(d?.loc) ? FIELD_NAMES[String(d.loc[d.loc.length - 1])] : undefined))
    .filter((n): n is string => Boolean(n));
  const unique = [...new Set(names)];
  if (!unique.length) return general;
  const list = unique.length === 1 ? unique[0] : `${unique.slice(0, -1).join(", ")} and ${unique[unique.length - 1]}`;
  return `Please fill in ${list}, then try again.`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("Khutlisa's server could not be reached. Check that it is running, then try again.");
  }
  return read<T>(response);
}

export const getTotals = () => call<Totals>("/api/totals");
export const getRegister = () => call<RegisterInfo>("/api/register");
export const getDemonstration = () => call<Demonstration>("/api/demonstration");
export const getNotable = () => call<NotableSet>("/api/organisations/notable");
export const searchOrganisations = (q: string) => call<OrganisationSearch>(`/api/organisations?q=${encodeURIComponent(q)}`);
export const getCountries = () => call<CountryName[]>("/api/countries");
export const search = (history: History) =>
  call<SearchResult>("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(history),
  });

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getDocumentKinds = () => call<DocumentKind[]>("/api/document-kinds");
export const createClaim = (match: Match, claimant: Claimant, history: History | null) =>
  call<Claim>("/api/claims", json({ record_id: match.record_id, claimant, history }));
export const getClaim = (id: string) => call<Claim>(`/api/claims/${id}`);
export const addDocument = (id: string, kind: string, file: File) => {
  const form = new FormData();
  form.append("kind", kind);
  form.append("file", file);
  return call<Claim>(`/api/claims/${id}/documents`, { method: "POST", body: form });
};
export const markFiled = (id: string) => call<Claim>(`/api/claims/${id}/filed`, { method: "POST" });
export const removeDocument = (id: string, documentId: string) =>
  call<Claim>(`/api/claims/${id}/documents/${documentId}`, { method: "DELETE" });
export const setPayee = (id: string, body: PayeeRequest) =>
  call<Claim>(`/api/claims/${id}/payee`, { ...json(body), method: "PUT" });
export const getPayout = (id: string) => call<PayoutView>(`/api/claims/${id}/payout`);
export const planPayout = (id: string, whatIf: string | null) => call<PayoutView>(`/api/claims/${id}/payout/plan`, json({ what_if: whatIf }));
export const confirmPayout = (id: string, planId: string) => call<PayoutView>(`/api/claims/${id}/payout/confirm`, json({ plan_id: planId }));
export const resumePayout = (id: string) => call<PayoutView>(`/api/claims/${id}/payout/resume`, { method: "POST" });

// ---- the payer's view. Its routes take a shared key in a header; the page asks for it once. ----
const PAYER_KEY = "khutlisa-payer-key";
export const payerKey = () => window.sessionStorage.getItem(PAYER_KEY) ?? "";
export const setPayerKey = (key: string) => (key ? window.sessionStorage.setItem(PAYER_KEY, key) : window.sessionStorage.removeItem(PAYER_KEY));
const asPayer = (init: RequestInit = {}): RequestInit => ({ ...init, headers: { ...(init.headers ?? {}), "X-Payer-Key": payerKey() } });
export const getPayerQueue = () => call<PayerQueue>("/api/payer/queue", asPayer());
export const approveClaim = (id: string) => call<QueueRow>(`/api/payer/claims/${id}/approve`, asPayer({ method: "POST" }));
export const rejectClaim = (id: string, reason: string) => call<QueueRow>(`/api/payer/claims/${id}/reject`, asPayer(json({ reason })));

export const getInstructions = () => call<InstructionsView>("/api/payer/instructions", asPayer());
export const setInstructions = (rules: InstructionRules) =>
  call<InstructionsView>("/api/payer/instructions", asPayer({ ...json(rules), method: "PUT" }));

// ---- money from the start, and the figures for holders. Nothing here locks a rate or moves money. ----
export const getHolders = () => call<HoldersView>("/api/holders");
export const getIndicative = (country: string, amounts: number[]) =>
  call<Indicative>(`/api/indicative?country=${encodeURIComponent(country)}${amounts.map((a) => `&amount=${a.toFixed(2)}`).join("")}`);
export const getPlanPreview = (id: string) => call<PlanPreview>(`/api/claims/${id}/payout/preview`);

// ---- the intake ----
export const getIntakeSample = () => call<IntakeSample>("/api/intake/sample");
export const intakeText = (text: string, earlier = "", question = "") =>
  call<IntakeResult>("/api/intake/text", json({ text, earlier, question }));
export const intakeAudio = (audio: Blob, earlier = "", question = "") => {
  const form = new FormData();
  form.append("file", audio, "recording");
  form.append("earlier", earlier);
  form.append("question", question);
  return call<IntakeResult>("/api/intake/audio", { method: "POST", body: form });
};
export const hearAudio = (audio: Blob) => {
  const form = new FormData();
  form.append("file", audio, "recording");
  return call<HeardWords>("/api/intake/heard", { method: "POST", body: form });
};

// ---- the whole book of one holder, and a batch run from it ----
export const getBookHolders = (q = "") => call<BookHolders>(`/api/book/holders${q ? `?q=${encodeURIComponent(q)}` : ""}`);
export const getBook = (holder: string, inputs: Partial<BookInputs> = {}) => {
  const params = new URLSearchParams({ holder });
  for (const [key, value] of Object.entries(inputs)) if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  return call<BookPlan>(`/api/book?${params.toString()}`);
};
export const makeBatch = (holder: string, inputs: Partial<BookInputs>) => call<BatchView>("/api/payer/batches", asPayer(json({ holder, ...inputs })));
export const makeClaimsBatch = (claimIds: string[]) => call<BatchView>("/api/payer/batches/claims", asPayer(json({ claim_ids: claimIds })));
export const getBatches = () => call<BatchList>("/api/payer/batches", asPayer());
export const getBatch = (id: string) => call<BatchView>(`/api/payer/batches/${id}`, asPayer());
export const approveBatch = (id: string) => call<BatchView>(`/api/payer/batches/${id}/approve`, asPayer({ method: "POST" }));
export const resumeBatch = (id: string) => call<BatchView>(`/api/payer/batches/${id}/resume`, asPayer({ method: "POST" }));
export const batchItemAct = (id: string, n: number, what: "account" | "approve" | "agree") =>
  call<BatchView>(`/api/payer/batches/${id}/items/${n}/${what}`, asPayer({ method: "POST" }));
