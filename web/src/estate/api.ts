import { payerKey } from "../api";
import type { EstateSample, EstateView, Family, SampleBank } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("Khutlisa's server could not be reached. Check that it is running, then try again.");
  }
  if (response.ok) return (await response.json()) as T;
  let message = response.status === 401 ? "The holder's key is missing or wrong." : "Khutlisa's server could not answer. Try again.";
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (typeof body.detail?.message === "string") message = [body.detail.message, ...(Array.isArray(body.detail.reasons) ? body.detail.reasons : [])].join(" ");
    else if (response.status === 422) message = "Some of the details could not be read. Check them and try again.";
  } catch {
    // The reply was not JSON, so the general message stands.
  }
  throw new Error(message);
}

const json = (body: unknown, method = "POST"): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const asHolder = (init: RequestInit = {}): RequestInit => ({ ...init, headers: { ...(init.headers ?? {}), "X-Payer-Key": payerKey() } });
const at = (id: string) => `/api/claims/${id}/estate`;

export const getSample = () => call<EstateSample>("/api/estate/sample");
export const openEstate = (id: string) => call<EstateView>(at(id), { method: "POST" });
export const getEstate = (id: string) => call<EstateView>(at(id));
export const sayFamily = (id: string, text: string, earlier = "", question = "") => call<EstateView>(`${at(id)}/intake`, json({ text, earlier, question }));
export const putFamily = (id: string, family: Partial<Family>) => call<EstateView>(`${at(id)}/family`, json({ family }, "PUT"));
export const putHeir = (id: string, heir: string, body: { country?: string; email?: string; declared?: boolean }) =>
  call<EstateView>(`${at(id)}/heirs/${heir}`, json(body, "PUT"));
export const putHeirPayee = (id: string, heir: string, bank: SampleBank) => call<EstateView>(`${at(id)}/heirs/${heir}/payee`, json(bank, "PUT"));
export const addEstateDocument = (id: string, kind: string, file: File) => {
  const form = new FormData();
  form.append("kind", kind);
  form.append("file", file);
  return call<EstateView>(`${at(id)}/documents`, { method: "POST", body: form });
};
export const removeEstateDocument = (id: string, documentId: string) => call<unknown>(`/api/claims/${id}/documents/${documentId}`, { method: "DELETE" });
export const planSettlement = (id: string, failHeir: string | null) => call<EstateView>(`${at(id)}/settlement/plan`, json({ fail_heir: failHeir }));
export const confirmSettlement = (id: string, planId: string) => call<EstateView>(`${at(id)}/settlement/confirm`, json({ plan_id: planId }));
export const resumeSettlement = (id: string) => call<EstateView>(`${at(id)}/settlement/resume`, { method: "POST" });
export const agreeForHeir = (id: string, heir: string) => call<EstateView>(`${at(id)}/settlement/heirs/${heir}/agree`, { method: "POST" });
export const approveEstate = (id: string, otherLawReason: string) =>
  call<EstateView>(`/api/payer/estates/${id}/approve`, asHolder(json({ other_law_reason: otherLawReason })));

/** A sample document from the public folder, as a file ready to upload. */
export async function sampleFile(name: string): Promise<File> {
  const response = await fetch(`/samples/${name}`);
  if (!response.ok) throw new Error(`The sample document ${name} is not on this server. Run scripts/make_sample_documents.py.`);
  return new File([await response.blob()], name, { type: "image/png" });
}
