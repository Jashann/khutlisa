// Shared by scripts/walkthrough.mjs and scripts/record_demo.mjs: starting and stopping the servers a script owns,
// and the same API calls the screens make, for the parts of a run that are set up off screen.
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const PLAYWRIGHT_DIR = process.env.PLAYWRIGHT_DIR || "";
export const { chromium } = createRequire(join(PLAYWRIGHT_DIR, "x.js"))("playwright");

const servers = [];

export function startServer(port, env) {
  const child = spawn("uv", ["run", "uvicorn", "khutlisa.server:app", "--port", String(port), "--log-level", "warning"], {
    cwd: ROOT, env: { ...process.env, ...env }, detached: true, stdio: ["ignore", "ignore", "inherit"],
  });
  servers.push(child);
  return child;
}

/** Stops the servers this script started (uv and the uvicorn under it), and nothing else. */
export function stopServers() {
  for (const child of servers.splice(0)) {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {
      // already gone
    }
  }
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function waitFor(url, seconds = 60) {
  for (let i = 0; i < seconds * 2; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return r.json();
    } catch {
      // not up yet
    }
    await sleep(500);
  }
  throw new Error(`${url} did not answer within ${seconds} seconds`);
}

export async function portFree(port) {
  try {
    await fetch(`http://localhost:${port}/api/countries`);
    return false;
  } catch {
    return true;
  }
}

/** What each demonstration person tells the search, in the shape the form produces. */
export const HISTORIES = {
  marisol: { given_names: ["Marisol", "Elena"], family_names: ["Tolmedo", "Peralmonte"], employers: ["Empacadora Valle Sereno"],
    places: [{ city: "Salinas", region: "CA", postcode: "93905", country: "US", street: "" }], current_country: "MX" },
  amihan: { given_names: ["Amihan"], family_names: ["Dalisay", "Villareal"], employers: ["Bayview Mercy Hospital"],
    places: [{ city: "Daly City", region: "CA", postcode: "94015", country: "US", street: "" }], current_country: "PH" },
};

/** The API of one server, called the way the screens call it. `key` is the holder's key. */
export function apiOf(base, key) {
  const call = async (path, init = {}) => {
    const r = await fetch(base + path, init);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(`${init.method ?? "GET"} ${path} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
    return body;
  };
  const json = (method, body, headers = {}) => ({ method, headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body ?? {}) });
  const holder = { "X-Payer-Key": key };
  const api = {
    get: (path) => call(path),
    claim: (id) => call(`/api/claims/${id}`),
    payout: (id) => call(`/api/claims/${id}/payout`),
    queue: () => call("/api/payer/queue", { headers: holder }),
    setLimits: (rules) => call("/api/payer/instructions", json("PUT", rules, holder)),
    approve: (id) => call(`/api/payer/claims/${id}/approve`, { method: "POST", headers: holder }),
    plan: (id, whatIf = null) => call(`/api/claims/${id}/payout/plan`, json("POST", { what_if: whatIf })),
    confirm: (id, planId) => call(`/api/claims/${id}/payout/confirm`, json("POST", { plan_id: planId })),
    setBank: (id, bank) => call(`/api/claims/${id}/payee`, json("PUT", bank)),
    async people() {
      return (await call("/api/demonstration")).people;
    },
    /** Opens a claim for a demonstration person on her record of `amount`, adds the named documents, waits until
     *  each has been read, and gives her bank account. Everything goes through the routes the screens use. */
    async openClaim(personKey, amount, documentLabels, { bank = true } = {}) {
      const person = (await api.people()).find((p) => p.key === personKey);
      const found = await call("/api/search", json("POST", HISTORIES[personKey]));
      const match = found.matches.find((m) => m.source === "DEMO" && Math.abs(m.amount - amount) < 0.005);
      if (!match) throw new Error(`no demonstration record of ${amount} was found for ${personKey}`);
      const claim = await call("/api/claims", json("POST", { record_id: match.record_id, claimant: person.claimant, history: HISTORIES[personKey] }));
      for (const label of documentLabels) {
        const doc = person.documents.find((d) => d.label.startsWith(label));
        const form = new FormData();
        form.append("kind", doc.kind);
        form.append("file", new Blob([readFileSync(join(ROOT, "web", "public", "samples", doc.file))], { type: "image/png" }), doc.file);
        await call(`/api/claims/${claim.id}/documents`, { method: "POST", body: form });
      }
      for (let i = 0; i < 300; i++) {
        const now = await api.claim(claim.id);
        if (now.documents.every((d) => d.reading.status !== "reading")) break;
        await sleep(1000);
      }
      if (bank) await api.setBank(claim.id, person.bank);
      return claim.id;
    },
    /** Waits until the payout satisfies `test`, reading it once a second. */
    async until(id, test, seconds = 300) {
      for (let i = 0; i < seconds; i++) {
        const p = await api.payout(id);
        if (test(p)) return p;
        await sleep(1000);
      }
      throw new Error(`the payout of claim ${id} did not reach the expected point within ${seconds} seconds`);
    },
  };
  return api;
}

/** A handover date close enough that the agent stops waiting for documents: 1 December when that is within the
 *  next 30 days (the window for life insurance companies), otherwise 20 days from today. */
export function nearHandoverDate(now = new Date()) {
  const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const december = new Date(Date.UTC(today.getUTCFullYear(), 11, 1));
  const days = (december - today) / 86400000;
  const day = days >= 5 && days <= 30 ? december : new Date(today.getTime() + 20 * 86400000);
  return day.toISOString().slice(0, 10);
}
