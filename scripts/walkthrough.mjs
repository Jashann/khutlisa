// Walks the whole product in a real browser at 1920x1080 and saves every step as one numbered sequence of
// screenshots in docs/shots/walk/.
//
//     node scripts/walkthrough.mjs
//
// The story is one: a company that owes money to someone who has gone home to another country (the holder) finds
// her, checks that it is really her, and pays her at home, with an agent that acts within limits the holder sets
// once. The walk follows that main journey, then each capability in turn, all on one server, so a claim opened in
// one part is in the queue, the funnel and the risk view of the next:
//
//   1. the main journey: the opening, who is owed (with Queensland's register searched beside California's), for
//      holders, "What is real here", the holder's limits; Marisol's spoken history, her proof, the holder's
//      approval, the payout, a refused transfer and its replacement, Airwallex's lines at zero; the same refusal
//      on a small claim that stops and asks; Amihan's small claim under the fee rule; the handover date deciding;
//   2. the whole book of the largest holder, two other books, and a slice of a plan run as a batch on the sandbox;
//   3. funding a claim on Metal testnet: the approval signs a mandate, Metal refuses pulls outside it, the pull
//      funds the Airwallex payout (skipped, with the reason, when Metal testnet cannot be reached);
//   4. the holder's own list: the invented file, the queue owed abroad, the notices in the owner's language, the
//      funnel, and Marisol answering hers with the code on the letter, proven and paid;
//   5. an estate: the family in the widow's words, the shares, the proof for each heir, one settlement to heirs
//      in several countries (scripts/walkthrough_heirs.mjs);
//   6. the risk view: planted rings copied into the same queue, held before any money moves, a release with a
//      reason, and an approval refused because the claim is held (scripts/walkthrough_rings.mjs).
//
// Every screen is checked for internal state names, long dashes, emoji, text under 13px, text cut off, sideways
// scrolling, errors in the browser console and server errors, and the main path for anything that says the claim
// goes to the State. A server pointed at a register database that does not exist is checked last, on port 8022.
//
// It starts its servers and stops them (and nothing else) at the end: port 8021, the built app on California's
// file, Queensland's register and the demonstration records, with a fresh claims folder (data/samples/walk-claims).
// It needs the built front end (cd web && npm run build), data/registers.duckdb, data/queensland.duckdb
// (scripts/load_queensland.py), data/books.parquet (scripts/make_books.py), the corridors Airwallex was asked about
// (scripts/discover_corridors.py), the claude program for the intake and the document reading, the Airwallex
// sandbox keys, the Metal testnet setup (scripts/metal_setup.py) for part 3, and pdftoppm for the pictures of the
// fallback packet and the notice letter. The holder's view is opened with a key made for this run. Playwright is
// taken from PLAYWRIGHT_DIR (a folder with node_modules/playwright). KHUTLISA_DB names the register database when
// it is not at data/registers.duckdb. WALK_KEEP=1 leaves the server running at the end.
//
// WALK_BASE=https://name runs the same walk against a public copy that is already running (public demonstration
// mode), from outside: no server is started, the holder's key is the one the public copy gives its pages
// (/api/mode), and the pictures go to docs/shots/live/. The steps that public demonstration mode refuses by design,
// or that need the server's own folders, are skipped and listed with the reason: funding on Metal (switched off in
// the public copy), the risk view (its rings are planted by writing claims into the server's folder), the estate's
// run log (read from the server's claims folder) and the server started without the register database.
//
// No picture holds a real person's record: before every picture, the cards of real owners are blurred. Their
// names are masked on the page itself in any case.
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT, apiOf, chromium, nearHandoverDate, portFree, startServer, stopServers, waitFor } from "./demo_lib.mjs";
import { walkHeirs } from "./walkthrough_heirs.mjs";
import { walkRings } from "./walkthrough_rings.mjs";

const REMOTE = (process.env.WALK_BASE ?? "").replace(/\/+$/, "");
const SHOTS = join(ROOT, "docs", "shots", REMOTE ? "live" : "walk");
const SAMPLES = join(ROOT, "data", "samples");
const CLAIMS = join(SAMPLES, "walk-claims");
const PORT = 8021;
const BARE_PORT = 8022;
const BASE = REMOTE || `http://localhost:${PORT}`;
const BARE = `http://localhost:${BARE_PORT}`;
let PAYER_KEY = `walk-${randomBytes(12).toString("hex")}`;
let api = apiOf(BASE, PAYER_KEY);
const DATABASE = process.env.KHUTLISA_DB || join(ROOT, "data", "registers.duckdb");
// Pictures from before the walk was one sequence. They are removed so that only this run's pictures remain.
const STALE = ["outreach", "heirs", "rings", "metal_1_approve.png", "metal_2_mandate_and_refusals.png", "metal_3_holder_after.png",
  "metal_4_payment_screen.png"].map((name) => join(ROOT, "docs", "shots", name));
const shotsDir = SHOTS;
const base = BASE;
const OUTREACH = BASE;

const problems = [];
const notes = [];
// The steps skipped against a public copy, each with the reason (WALK_BASE).
const skipped = [];
let shotNumber = 0;
let page;

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const fail = (text) => {
  problems.push(text);
  log("PROBLEM:", text);
};
const check = (ok, text) => {
  if (!ok) fail(text);
  return ok;
};

// Words that must never reach a screen: internal state names, long dashes, emoji.
const STATE_NAMES = /\b(FOUND|PROOF_NEEDED|PROOF_READY|PACKET_READY|FILED|APPROVED|PAYING|REJECTED|PAYMENT_HELD|PLANNED|HELD|DEPOSIT_EXPECTED|DEPOSIT_CONFIRMED|BENEFICIARY_READY|TRANSFER_CREATED)\b/;
const DASHES = /[\u2013\u2014]/;
const EMOJI = /\p{Extended_Pictographic}/u;
// A masked owner: every word is its first character and the same three dots, whatever its length.
const MASKED = /^\S·{3}( \S·{3})*$/;
// Nothing on the main path may say or imply that the claim is being sent to the State.
const TO_THE_STATE = /signed (it )?and sent|send (it|the packet) to (the State|California)|held by the California State Controller|claim packet/i;

/** Looks at the page the way a viewer of a recording would: wording, cut-off text, sideways scrolling. */
async function audit(name, { tall = false } = {}) {
  const found = await page.evaluate(() => {
    // textContent, because innerText gives labels in the capitals the style sheet shows them in
    // The screen in front (the search stays loaded behind a claim). What California's file itself says about a
    // record, in capitals, is left out of the wording check: it is the State's text, not ours.
    const main = [...document.querySelectorAll("main")].find((m) => m.offsetParent !== null)?.cloneNode(true);
    main?.querySelectorAll(".match-facts, .owner, .owed-by, .owed-name").forEach((el) => el.remove());
    const out = { text: main?.textContent ?? "", sideways: document.documentElement.scrollWidth > window.innerWidth + 1, cut: [], small: [] };
    for (const el of document.querySelectorAll("body *")) {
      if (!(el instanceof HTMLElement) || !el.offsetParent) continue;
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!own) continue;
      const style = getComputedStyle(el);
      if (el.scrollWidth > el.clientWidth + 2 && style.overflowX !== "visible" && el.clientWidth > 0 && style.display !== "inline")
        out.cut.push(el.innerText.slice(0, 60));
      if (parseFloat(style.fontSize) < 13) out.small.push(`${style.fontSize} "${el.innerText.slice(0, 40)}"`);
    }
    return out;
  });
  const state = found.text.match(STATE_NAMES);
  check(!state, `${name}: the state name ${state?.[0]} is on screen`);
  check(!DASHES.test(found.text), `${name}: a long dash is on screen`);
  check(!EMOJI.test(found.text), `${name}: an emoji is on screen`);
  check(!found.sideways, `${name}: the page scrolls sideways`);
  check(found.cut.length === 0, `${name}: text is cut off: ${found.cut.slice(0, 3).join(" | ")}`);
  check(found.small.length === 0, `${name}: text under 13px: ${found.small.slice(0, 3).join(" | ")}`);
  const marks = await page.evaluate(() => ({
    badges: document.querySelectorAll(".demo-badge").length,
    old: document.querySelectorAll(".sample-tag, .sample-note").length,
    tall: document.documentElement.scrollHeight > window.innerHeight + 1,
  }));
  check(marks.badges <= 1 && marks.old === 0, `${name}: more than the one demonstration badge is on screen (${marks.badges} badges, ${marks.old} other notices)`);
  if (!tall) check(!marks.tall, `${name}: the page as a whole scrolls`);
}

/** The same checks for a picture taken by one of the walks in their own files (heirs, rings). Those screens are
 *  allowed to be taller than the window, and are checked for everything else. */
async function auditOf(other, file) {
  const mine = page;
  page = other;
  try {
    await audit(file, { tall: true });
  } finally {
    page = mine;
  }
}

/** Errors in the browser console, pages that throw, and server errors, on any page of the walk. */
function watch(p) {
  p.on("console", (m) => m.type() === "error" && !/status of 4\d\d/.test(m.text()) && fail(`browser console: ${m.text().slice(0, 200)}`));
  p.on("pageerror", (e) => fail(`page error: ${e.message.slice(0, 200)}`));
  p.on("response", (r) => r.status() >= 500 && fail(`${r.status()} from ${r.url()}`));
}

async function shot(name, { full = false, checks = true } = {}) {
  shotNumber += 1;
  const file = `${String(shotNumber).padStart(3, "0")}-${name}.png`;
  await page.evaluate(() => document.body.classList.add("blur-real"));   // real owners never reach a picture
  await page.screenshot({ path: join(shotsDir, file), fullPage: full });
  await page.evaluate(() => document.body.classList.remove("blur-real"));
  if (checks) await audit(file);
  log("shot", file);
  return file;
}

const settle = (ms = 500) => page.waitForTimeout(ms);

const cents = (text) => Math.round(Number(text) * 100);
const words = (text) => (text ?? "").replace(/\s+/g, " ").trim();

/** The payment as the API reports it, and whether Airwallex's own lines for the claim add up to zero. */
async function payoutResult(claimId) {
  const p = await (await fetch(`${BASE}/api/claims/${claimId}/payout`)).json();
  const books = p.reconciliation ?? { lines: [], sums: [], balanced: false };
  const usd = books.lines.filter((l) => l.currency === "USD");
  const deposit = usd.filter((l) => l.type === "DEPOSIT").reduce((n, l) => n + cents(l.amount), 0);
  const feeIn = -usd.filter((l) => l.type === "FEE").reduce((n, l) => n + cents(l.amount), 0);
  const sentUsd = -usd.filter((l) => l.type === "PAYOUT").reduce((n, l) => n + cents(l.amount), 0);
  return {
    claim: claimId, state: p.state, route: p.route, what_if: p.what_if ?? null,
    approved_usd: p.deposit?.expected, arrived_usd: p.deposit?.amount, incoming_fee_usd: p.incoming_fee?.amount,
    left_khutlisas_account: p.left_wallet ? `${p.left_wallet.amount} ${p.left_wallet.currency}` : null,
    payout_fee: p.payout_fee ? `${p.payout_fee.amount} ${p.payout_fee.currency}, taken from the amount sent` : null,
    rate: p.rate, received: p.received ? `${p.received.amount} ${p.received.currency}` : null,
    airwallex_transfer_id: p.transfer_id, airwallex_status: p.proof?.transfer?.status,
    airwallex_reference: p.proof?.transfer?.short_reference_id,
    earlier_transfers: (p.attempts ?? []).map((a) => ({ id: a.transfer_id, status: a.status, fate: a.fate, came_back: `${a.came_back.amount} ${a.came_back.currency}` })),
    ledger_lines: books.lines.map((l) => `${l.part}: ${l.type} ${l.amount} ${l.currency}`),
    ledger_sums: books.sums, ledger_adds_up_to_zero: books.balanced,
    deposit_less_fee_equals_sent_usd: deposit - feeIn === sentUsd,
    environment: p.environment,
    claim_usd: p.claim_usd ?? null,
    agreed_and_paid: p.agreed_and_paid ?? null,
    decided_without_asking: (p.agent_report ?? []).map((d) => d.kind),
    agent_report: (p.agent_report ?? []).map((d) => `${d.title} (${d.rule_name}): ${d.text}`),
  };
}

// ---------------------------------------------------------------------------------------------------------------

/** The main path never says the claim goes to the State. Checked on the screens of that path. */
async function notToTheState(name) {
  const text = await page.evaluate(() => [...document.querySelectorAll("main")].find((m) => m.offsetParent !== null)?.innerText ?? "");
  const hit = text.match(TO_THE_STATE);
  check(!hit, `${name}: the main path says "${hit?.[0]}"`);
}

/** Adds the demonstration person's documents by the buttons on the proof screen, and waits until each is read. */
async function addDocuments(labels, expected) {
  for (const label of labels) {
    await page.locator(".demo-docs li", { hasText: label }).getByRole("button", { name: "Add" }).click();
    await page.locator(".demo-docs li", { hasText: label }).getByRole("button", { name: "Added" }).waitFor({ timeout: 30000 });
  }
  await page.waitForFunction(
    (n) => document.querySelectorAll(".doc").length === n && document.querySelectorAll(".doc-state-reading").length === 0,
    expected, { timeout: 300000, polling: 1000 });
  const bad = await page.locator(".doc-state-failed, .doc-state-unreadable").count();
  check(bad === 0, `${bad} document(s) could not be read`);
  await settle(1800); // the claim is asked for again every 1.5 seconds; let the proof catch up
}

/** From the matches to an open claim: choose the record, fill the claimant's details with the one control, open. */
async function openClaimOn(amount, shortName) {
  await page.locator(".match", { hasText: amount }).getByRole("button", { name: "Prove this is mine" }).click();
  await page.getByRole("heading", { name: "Open your claim" }).waitFor();
  await page.getByRole("button", { name: `Fill this in for ${shortName}` }).click();
  await settle(300);
  await page.getByRole("button", { name: "Open my claim" }).click();
  await page.getByRole("heading", { name: "Proof file" }).waitFor({ timeout: 30000 });
  return page.url().split("#claim/")[1];
}

async function proofReady(label) {
  await page.waitForFunction(() => document.querySelector(".verdict")?.textContent === "Ready", null, { timeout: 30000 })
    .catch(() => fail(`${label}: the proof did not become ready`));
}

const RULES = { tolerance_percent: "0.5", small_claim_usd: "250", route_rule: "most_to_claimant", deadline_days: 14 };

async function openHolderView() {
  await page.goto(`${base}/payer`);
  if (await page.getByRole("heading", { name: "The holder's view is locked" }).isVisible().catch(() => false)) {
    await page.getByLabel("Holder's key").fill(PAYER_KEY);
    await page.getByRole("button", { name: "Open the holder's view" }).click();
  }
  await page.getByRole("heading", { name: "Your limits, set once" }).waitFor();
  await settle();
}

const pick = (amount) => page.locator(".payer-pick", { hasText: amount }).first();

async function waitForPaid(label) {
  const started = Date.now();
  await page.waitForFunction(() => document.querySelector(".received") || /could not go ahead/.test(document.body.innerText),
    null, { timeout: 300000, polling: 1000 });
  check((await page.locator(".received").count()) === 1, `${label}: the payment did not reach "paid"`);
  log(label, "paid after", Math.round((Date.now() - started) / 1000), "seconds");
}

/** A decision card on screen, as its four lines. */
async function card(scope, kind) {
  const el = page.locator(`${scope} .decision[data-kind="${kind}"]`).first();
  if (!(await el.count())) return null;
  const lines = await el.locator(".decision-line dd").allInnerTexts();
  check(lines.length === 4 && lines.every((l) => l.length > 0 && l.length <= 140), `the ${kind} card is not four short lines: ${JSON.stringify(lines)}`);
  return lines.map(words);
}

async function journey(browser) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, acceptDownloads: true });
  page = await context.newPage();
  page.on("console", (m) => m.type() === "error" && !/status of 4\d\d/.test(m.text()) && fail(`browser console: ${m.text().slice(0, 200)}`));
  page.on("pageerror", (e) => fail(`page error: ${e.message.slice(0, 200)}`));
  const sounds = [];
  page.on("response", (r) => {
    if (r.status() >= 500) fail(`${r.status()} from ${r.url()}`);
    if (/\/demo\/.*\.m4a/.test(r.url()) && r.status() < 300) sounds.push(r.url().split("/").pop());
  });

  // 1. The opening makes its point in ten seconds: Stanford's money reported by Harvard, the whole file, the part
  //    owed to people abroad, one real search with its own time, the cheque, and what Khutlisa does.
  const totals = await api.get("/api/totals");
  const queensland = (await api.get("/api/register")).queensland ?? null;
  check(!!queensland && queensland.matches_portal === true && queensland.currency === "AUD", "Queensland's register is not loaded, or does not match the portal's count and total (run scripts/load_queensland.py)");
  check(totals.abroad_amount > 250e6 && totals.abroad_amount < 300e6 && totals.abroad_properties > 200000 && /California State Controller/.test(totals.source),
    "the opening totals are not California's real figures, counted once per property");
  await page.goto(BASE);
  await page.locator(".lead-fact").waitFor();
  const counters = [];
  const frames = [];
  let waited = 0;
  for (const [at, name] of [[1000, "opening-1s-stanford-and-harvard"], [6000, "opening-6s-the-totals-and-the-live-search"], [9600, "opening-10s-the-whole-point"]]) {
    await page.waitForTimeout(at - waited);
    waited = at;
    counters.push(Number((await page.locator(".counter").innerText().catch(() => "0")).replace(/[^0-9]/g, "")));
    frames.push((await page.locator("canvas.globe").screenshot()).toString("base64"));
    await shot(name);
  }
  check(counters[0] < counters[1], `the counter does not run up: ${counters.join(", ")}`);
  check(counters[2] === Math.round(totals.abroad_amount), `the counter stops at ${counters[2]}, not at the real total ${Math.round(totals.abroad_amount)}`);
  check(new Set(frames).size === 3, "the globe does not change between screenshots");
  const opening = words(await page.locator(".opening-panel").innerText());
  const liveLine = words(await page.locator(".live-line").innerText().catch(() => ""));
  check(/Stanford University is owed \$55,690\.09/.test(opening) && /Harvard reported it/.test(opening), `the opening does not lead with Stanford's money reported by Harvard: "${opening.slice(0, 200)}"`);
  check(/\$12\.74 billion in 89 million properties/.test(opening), "the opening does not give the whole file: $12.74 billion in 89 million properties");
  check(/234,883 properties/.test(opening) && /another country/.test(opening), "the opening does not give the part owed to people abroad");
  check(/95,425,821 owner records searched in [\d.]+ seconds?/.test(liveLine), `the opening does not report a real search with its own time: "${liveLine}"`);
  check(/only way to pay is a cheque in the post/.test(opening) && /pay her at home/.test(opening), "the opening does not say how the State pays and what Khutlisa does");
  check(!/California is holding/.test(opening), "the opening says California is holding the money");
  check(await page.getByRole("button", { name: /Begin/ }).isVisible() && await page.getByRole("button", { name: "For holders" }).isVisible()
    && (await page.locator(".opening-actions-in").count()) === 1, "the buttons are not on screen within ten seconds");
  notes.push(`Opening: ${opening}`);

  // 2. Who is owed: the evidence of what happens when holders cannot reach owners. Real organisations only.
  await page.getByRole("button", { name: "See who is owed" }).click();
  await page.getByRole("heading", { name: "Real organisations that are owed money" }).waitFor();
  await page.locator(".owed-list li").first().waitFor();
  await settle();
  check(/Harvard/i.test(await page.locator(".owed-list").innerText()), "the leading examples do not include Stanford's money reported by Harvard");
  check((await page.locator('.owed-check a[href^="https://claimit.ca.gov/"]').count()) === 1, "the screen does not point to California's own site");
  await shot("who-is-owed-one-well-known-name-reported-by-another");
  await page.getByLabel(/Type the name/).fill("university of tokyo");
  await page.locator(".owed-results .owed-list li").first().waitFor({ timeout: 30000 });
  await settle();
  const typed = await api.get("/api/organisations?q=university");
  check(typed.results.length > 0 && typed.results.every((r) => r.owner_is_organisation), "the organisation search returned something that is not an organisation");
  notes.push(`Typed search: ${words(await page.locator(".owed-line").innerText())}`);
  await shot("who-is-owed-a-typed-name");
  // A second register: Queensland's, searched in the same pass, in Australian dollars, kept apart.
  if (queensland) {
    await page.getByLabel(/Type the name/).fill("");
    await page.getByRole("tab", { name: "Queensland" }).click();
    await page.locator(".owed-qld").first().waitFor();
    const second = words(await page.locator(".owed-second").innerText());
    check(second.includes(queensland.owner_records.toLocaleString("en-US")) && /AUD/.test(second) && /kept apart/.test(second) && /Public Trustee of Queensland/.test(second) && /Creative Commons Attribution 4\.0/.test(second),
      `Queensland's register is not shown with its own count, its currency and its attribution: "${second}"`);
    const listed = await page.locator(".owed-qld .owed-amount").allInnerTexts();
    check(listed.length >= 5 && listed.every((a) => /AUD$/.test(a) && !/\$/.test(a)), `Queensland's amounts are not all in Australian dollars: ${listed.join(", ")}`);
    await shot("who-is-owed-queensland-in-australian-dollars");
    await page.getByLabel(/Type the name/).fill("telstra");
    await page.locator(".owed-results .owed-qld").first().waitFor({ timeout: 30000 });
    await settle();
    const both = await api.get("/api/organisations?q=telstra");
    check(both.queensland.results.length > 0 && both.queensland.results.every((r) => r.owner_is_organisation && r.currency === "AUD") && both.results.every((r) => r.currency === "USD"),
      "a typed name does not search both registers with each currency on its own list");
    notes.push(`Queensland: ${second} A typed name ("telstra") found ${both.results.length} properties in California's file and ${both.queensland.results.length} in Queensland's register.`);
    await shot("who-is-owed-a-typed-name-in-both-registers");
  }

  // 3. For holders: who reported the money, the law in a sentence, and the days to the next handover.
  await page.goto(`${BASE}/#holders`);
  await page.getByRole("heading", { name: "The money sits with holders first" }).waitFor();
  await page.locator(".holder-list li").first().waitFor();
  await settle();
  const holders = await api.get("/api/holders");
  check(holders.figures.properties === totals.abroad_properties && Math.round(holders.figures.amount) === Math.round(totals.abroad_amount),
    "the holder figures do not add up to the opening's total for owners abroad");
  const law = words(await page.locator(".law-short").innerText());
  check(/1532\(b\)/.test(law) && /1560\(b\)/.test(law) && /1 and 15 June/.test(law) && /cheque in the post/.test(law), `the law in a sentence is not on the holders screen: "${law}"`);
  check(law.includes(String(holders.in_short.days_to_handover)) && (await page.locator(".law-short a[href^='https://www.sco.ca.gov/']").count()) >= 3, "the days to the handover and the sources are not on the holders screen");
  notes.push(`For holders: ${holders.figures.holders_with_an_owner_abroad.toLocaleString("en-US")} holders, ${holders.figures.properties.toLocaleString("en-US")} properties, $${Math.round(holders.figures.amount).toLocaleString("en-US")}. Largest: ${holders.figures.by_amount.slice(0, 5).map((h) => h.name).join(", ")}. The law in a sentence: ${law}`);
  await shot("for-holders-the-top-holders-and-the-law-in-a-sentence");
  // Why a holder pays, from the data: who can pay and what the law already asks, each with its source; the
  // kinds of money and the kinds of holder, organisations only.
  const buyer = words(await page.locator(".buyer").innerText());
  check(/Any holder with a bank account can pay by transfer today/.test(buyer) && /no figure for it is given/.test(buyer)
    && (await page.locator(".buyer a[href^='https://www.sco.ca.gov/']").count()) === holders.buyer.why.length && !/none has been asked/i.test(buyer + law),
    `the holders screen does not state the buyer with its sources: "${buyer}"`);
  await page.getByRole("tab", { name: "By kind of money" }).click();
  await settle(300);
  const money = words(await page.locator(".holder-list").innerText());
  const wagesKind = holders.figures.kinds_of_money.find((k) => k.key === "wages");
  check(/Wages, payroll and commissions/.test(money) && money.includes(`$${Math.round(wagesKind.amount).toLocaleString("en-US")}`) && /unverified/.test(money)
    && holders.figures.kinds_of_money.reduce((n, k) => n + k.properties, 0) === holders.figures.properties,
    `the kinds of money are not on the holders screen, adding up to the same properties: "${money.slice(0, 300)}"`);
  await shot("for-holders-by-kind-of-money");
  await page.getByRole("tab", { name: "By kind of holder" }).click();
  await settle(300);
  const kinds = words(await page.locator(".holder-list").innerText());
  check(/Employers and payroll companies, by what they reported/.test(kinds) && /Marketplaces, platforms and money transfer companies/.test(kinds) && /none is guessed/.test(kinds),
    `the kinds of holder are not on the holders screen: "${kinds.slice(0, 300)}"`);
  notes.push(`Why a holder pays: ${buyer} Kinds of money: ${holders.figures.kinds_of_money.map((k) => `${k.label} $${Math.round(k.amount).toLocaleString("en-US")} in ${k.properties.toLocaleString("en-US")}`).join("; ")}.`);
  await shot("for-holders-by-kind-of-holder");

  // The caveats are said once, in one panel reachable from the top bar of every screen.
  await page.getByRole("button", { name: "What is real here" }).click();
  await page.locator(".real-panel").waitFor();
  await settle(400);
  const real = words(await page.locator(".real-panel").innerText());
  check(/demonstration/i.test(real) && /sandbox/i.test(real) && /No holder uses Khutlisa yet/i.test(real) && /our reading/i.test(real) && !/none has been asked/i.test(real)
    && /Queensland/.test(real) && /Metal testnet/.test(real) && /100 US dollars/.test(real) && /invented file/.test(real) && /never sent/.test(real),
    `the "what is real here" panel does not carry the caveats: "${real.slice(0, 300)}"`);
  notes.push(`What is real here: ${real}`);
  await shot("what-is-real-here-said-once");
  await page.getByRole("button", { name: "Close" }).click();

  // 4. The holder's view is locked. With the key, the holder sets its limits once and sees the days left.
  const locked = await fetch(`${BASE}/api/payer/queue`);
  const guessed = await fetch(`${BASE}/api/payer/instructions`, { method: "PUT", headers: { "X-Payer-Key": "guess", "Content-Type": "application/json" }, body: JSON.stringify(RULES) });
  check(locked.status === 401 && guessed.status === 401, `the holder's routes answered without the key (${locked.status}, ${guessed.status})`);
  await openHolderView();
  // A public copy may have had visitors: its limits may be set already, and they are set again here.
  check(REMOTE || /None set/.test(await page.locator(".instructions").innerText()), "a fresh server does not say that no limits are set");
  await page.getByRole("button", { name: /^(Set them|Change them)$/ }).click();
  await page.getByLabel(/Amount tolerance/).fill(RULES.tolerance_percent);
  await page.getByLabel(/Small-claim line/).fill(RULES.small_claim_usd);
  await page.getByLabel(/Days to send the money/).fill(String(RULES.deadline_days));
  await shot("the-holder-sets-its-limits-once");
  await page.getByRole("button", { name: "Save the limits" }).click();
  await page.locator(".limits li").first().waitFor({ timeout: 15000 });
  const limits = words(await page.locator(".limits").innerText());
  check(/0\.5%/.test(limits) && /\$250\.00/.test(limits) && /14 days/.test(limits) && /Best route/.test(limits) && /30 days/.test(limits), `the limits are not shown as figures: "${limits}"`);
  const handover = (await api.queue()).handover;
  const banner = words(await page.locator(".handover").innerText());
  check(banner.includes(`${handover.days_left} days`) && banner.includes(handover.date_words) && /1532\(b\)/.test(banner) && /1560\(b\)/.test(banner),
    `the holder's screen does not show the days left to the handover and the law in a sentence: "${banner}"`);
  notes.push(`The holder's screen: ${banner} Limits: ${limits}`);
  await shot("the-days-left-and-the-limits");

  // 4b. The whole book: the agent plans how to pay everything one holder owes abroad, the plan changes when the
  //     limits change, and a slice of it runs as a real batch on the sandbox.
  const batchResult = await wholeBook(holders);

  // 5. Marisol's history. A synthetic voice reads a prepared account, and the words shown are what the speech
  //    recogniser on this machine heard from that sound. The first search finds only possible matches.
  await page.goto(`${BASE}/#history`);
  await page.getByRole("heading", { name: "Tell us your history" }).waitFor();
  await settle();
  await page.getByRole("button", { name: /Hear Marisol, in Spanish/ }).click();
  await page.locator(".heard-speaking").waitFor();
  await settle(6000);
  const partial = await page.locator(".heard-speaking .heard-own").innerText();
  check(partial.length > 20 && !/Guadalajara/.test(partial), `the Spanish words do not appear with the voice: "${partial}"`);
  check(await page.locator(".bars").isVisible(), "no sound is playing while the Spanish account is shown");
  const source = page.locator(".voice-source").first();
  const voiceNote = words(`${await source.innerText().catch(() => "")} ${(await source.getAttribute("title").catch(() => "")) ?? ""}`);
  check(/synthetic voice/i.test(voiceNote) && /prepared account/.test(voiceNote), `the spoken example is not labelled as a synthetic voice reading a prepared account: "${voiceNote}"`);
  await shot("a-synthetic-voice-reads-and-the-recogniser-hears");
  await page.locator(".summary").waitFor({ timeout: 180000 });
  await page.locator(".heard:not(.heard-stale) .timeline").waitFor({ timeout: 60000 });
  await settle(900);
  check(sounds.includes("marisol_history_es.m4a"), "the Spanish sound file was not played");
  check(/Spanish/i.test(await page.locator(".heard").innerText()), "the intake did not recognise Spanish");
  const searchedLine = await page.locator(".searched-line").innerText();
  check(/demonstration records/.test(searchedLine) && /[\d.]+ seconds?/.test(searchedLine)
    && (queensland ? searchedLine.includes(`${(95425821 + queensland.owner_records).toLocaleString("en-US")} owner records in California's and Queensland's public files`)
      : /95,425,821 owner records/.test(searchedLine)),
    `the results do not say what was searched: "${searchedLine}"`);
  const wages = page.locator(".match", { hasText: "$2,316.40" });
  check((await wages.locator(".score-label").textContent()).trim() === "Possible match", "the wages record is not a possible match before the follow-up answer");
  const firstCards = await page.locator(".match").evaluateAll((els) => els.map((el) => ({
    real: el.classList.contains("match-real"), owner: el.querySelector(".owner").textContent.trim(),
    masked: el.querySelector(".owner").classList.contains("owner-masked"), note: el.querySelector(".owner-note").textContent,
    lines: el.querySelector(".lines").textContent, marks: (el.textContent.match(/Demonstration record/g) ?? []).length })));
  const realCards = firstCards.filter((c) => c.real);
  check(realCards.every((c) => (c.masked && MASKED.test(c.owner)) || /Organisation/.test(c.note)), "a real owner's name is not masked to one width");
  check(firstCards.every((c) => !/\d+ [A-Z]+ (ST|AVE|RD|BLVD|DR|LN)\b/.test(c.lines) && !/(address|street) (you|they) gave/i.test(c.lines)), "the search confirms or denies a street");
  check(firstCards.filter((c) => !c.real).every((c) => c.marks === 1), "a demonstration record is not marked exactly once on its card");
  check((await page.locator(".match-local").count()) === 0, "a possible match is given an amount in local currency");
  notes.push(`First search: ${words(searchedLine)} ${firstCards.length} cards shown, ${realCards.length} of them real owners from California's file (masked on the page and blurred in the pictures).`);
  await shot("first-matches-possible-only");

  // 6. The follow-up answer names the postcode. With the holder she named, that lifts the wages record to strong,
  //    and the strong card says what the amount would become in Mexican pesos today.
  if (await page.locator(".follow").count()) {
    // What the screen says is asked, and what is asked, are the same thing: her old postcode.
    const followLabel = words(await page.locator(".follow .panel-label").innerText());
    const followAsked = words(`${await page.locator(".follow-own").innerText()} ${await page.locator(".follow-english").innerText().catch(() => "")}`);
    check(/the old postcode/i.test(followLabel) && /c[oó]digo postal|postcode|zip code/i.test(followAsked) && !/\b(street|calle|direcci[oó]n)\b|\b(full|street) address\b/i.test(followAsked),
      `the follow-up question does not ask for the old postcode and only for that: "${followLabel}" / "${followAsked}"`);
    notes.push(`Follow-up question asked: ${(await page.locator(".follow-english").innerText().catch(() => page.locator(".follow-own").innerText())).slice(0, 300)}`);
    await page.getByRole("button", { name: "Hear Marisol's answer" }).click();
    await page.locator(".lift").first().waitFor({ timeout: 180000 });
    await settle(2500);
    check(sounds.includes("marisol_answer_es.m4a"), "the spoken answer was not played");
    const lift = words(await wages.locator(".lift").innerText());
    check(/possible match, 0\.\d\d/.test(lift) && /strong match, [01]\.\d\d/.test(lift) && /holder/i.test(lift) && /postcode/i.test(lift) && !/address/i.test(lift),
      `the card does not show the lift from possible to strong with its true reason: "${lift}"`);
    notes.push(`The answer changed the wages record: ${lift}`);
    await page.locator(".match-local").first().waitFor({ timeout: 20000 }).catch(() => undefined);
    const local = words(await wages.locator(".match-local").innerText().catch(() => ""));
    check(/MXN/.test(local) && /not locked/i.test(local), `the strong card does not give the amount in Mexican pesos, labelled as not locked: "${local}"`);
    notes.push(`In pesos today, on the strong card: ${local}`);
    await page.locator(".history-form").evaluate((el) => el.scrollTo(0, 0));
    await page.locator(".results").evaluate((el) => el.scrollTo(0, 0));
    await settle();
    await shot("the-answer-lifts-the-match-to-strong-with-pesos-today");
  } else {
    fail("the model asked no follow-up question on this run, so the lift could not be shown");
  }

  // 7. The proof. An expired staff badge is refused as photo identification, and with time in hand the agent asks
  //    for what is missing; the passport, read twice and checked in code, fixes it.
  const claimA = await openClaimOn("$2,316.40", "Marisol");
  await addDocuments(["Staff badge"], 1);
  check((await page.locator(".verdict").innerText()) === "Not ready", "a staff badge alone must not make the proof ready");
  const badge = words(await page.locator(".doc").first().innerText());
  check(/expired/i.test(badge) && /government/i.test(badge), `the staff badge is not refused with its reason: "${badge.slice(0, 300)}"`);
  const asked = await card(".claim-deadline", "deadline");
  check(asked && /Time in hand/.test(asked[2]) && /asked the owner for/.test(asked[2]), `with time in hand the agent does not ask the owner for the missing document: ${JSON.stringify(asked)}`);
  notes.push(`With the badge refused and ${handover.days_left} days in hand, the deadline card on her claim: ${JSON.stringify(asked)}`);
  await notToTheState("the proof tab");
  await shot("the-staff-badge-refused-and-the-agent-asks-for-what-is-missing");
  await addDocuments(["Passport photo page"], 2);
  check(/Proven/.test(await page.locator(".check", { hasText: "photo identification" }).first().innerText()), "the passport did not prove the photo identification");
  const passport = words(await page.locator(".doc", { hasText: /passport/i }).first().innerText());
  check(/Read twice/i.test(passport), `the passport card does not say it was read twice: "${passport.slice(0, 300)}"`);
  await shot("the-passport-read-twice-and-checked-in-code");
  await addDocuments(["Taxpayer number letter", "Bank statement"], 4);
  await proofReady("Marisol");
  await page.locator("#proof-file").evaluate((el) => el.scrollTo(0, 0));
  await settle();
  const opened = await api.claim(claimA);
  check(opened.address_check?.status === "matches", `after photo identification was read the claim does not say that the street she gave matches the record: ${JSON.stringify(opened.address_check)}`);
  check(opened.deadline?.choice === "pay", `with the proof ready the deadline choice is "${opened.deadline?.choice}", not to pay`);
  await notToTheState("the proof tab, ready");
  await shot("proof-ready");

  // 8. Her bank account, then the holder's approval. Nothing here goes to the State.
  await page.getByRole("tab", { name: "Bank account" }).click();
  await page.getByRole("button", { name: "Fill this in for Marisol" }).click();
  await settle(300);
  await page.getByRole("button", { name: "Save this bank account" }).click();
  await page.locator("#payee-on-file").waitFor({ timeout: 30000 });
  await settle();
  check(/The holder decides next/.test(await page.locator(".claim-body").innerText()), "after the bank account the claim does not say that the holder decides next");
  await notToTheState("the bank tab");
  await shot("her-bank-account-and-the-holder-decides-next");
  check((await api.claim(claimA)).state === "PROOF_READY", "the main path passed through the packet for the State");

  await openHolderView();
  await pick("$2,316.40").click();
  await settle();
  const risk = words(await page.locator(".queue-row .risk").innerText().catch(() => ""));
  check(/has not verified them with the issuing authority/.test(risk) && /The holder, not Khutlisa, approves/.test(risk),
    `the holder's screen does not state the remaining risk and who decides: "${risk.slice(0, 200)}"`);
  const terms = words(await page.locator(".queue-row .terms").innerText());
  check(/\$2,316\.40/.test(terms) && /7771/.test(terms) && /0\.5%/.test(terms), `the approval does not show the exact terms and the limits it carries: "${terms}"`);
  const feeA = await card(".queue-row", "fee_rule");
  check(feeA && /\$2,316\.40/.test(feeA[2]), `the holder is not shown what the fee rule means for this claim: ${JSON.stringify(feeA)}`);
  const holderText = await page.locator(".payer-cols").innerText();
  check(!/\byou gave\b|\byou added\b|\byour photo\b|\byour current\b|\bYour Social\b/i.test(holderText), "the holder's view speaks to the claimant");
  await shot("the-holders-approval-with-the-exact-terms-and-the-limits");
  await page.getByRole("button", { name: "Approve these terms" }).click();
  await page.locator(".queue-row .state", { hasText: "Approved" }).waitFor({ timeout: 30000 });
  await settle();

  // Her second property, 95.00 US dollars from another holder, is set up through the same routes off screen, to
  // the same first account, so the same refusal can meet both claims.
  const claimB = await api.openClaim("marisol", 95, ["Passport photo page", "Taxpayer number letter", "Bank statement"]);
  check((await api.claim(claimB)).proof.ready, "the proof of the 95.00 dollar claim did not become ready");
  await api.approve(claimB);

  // 9. The plan compares the routes; the receiving bank then refuses the transfer; the money comes back; the
  //    agent decides inside the limits; the replacement goes to a corrected account.
  await page.goto(`${BASE}/#payout/${claimA}`);
  await page.getByRole("heading", { name: "The payout plan" }).waitFor({ timeout: 30000 });
  await page.getByLabel("The receiving bank refuses the transfer").check();
  await page.getByRole("button", { name: "Show the payout plan" }).click();
  await page.locator(".plan-receive").waitFor({ timeout: 60000 });
  await settle();
  check(/MXN/.test(await page.locator(".plan-receive").innerText()), "the payout plan for Marisol is not in Mexican pesos");
  const routeCard = await card(".plan-stage", "route_chosen");
  const feeCard = await card(".plan-stage", "fee_rule");
  check(routeCard && /Two routes/.test(routeCard[0]) && /MXN/.test(routeCard[3]), `the plan does not show the route choice as a card: ${JSON.stringify(routeCard)}`);
  // The difference between the routes is a figure only when it matters (a tenth of a percent of the amount).
  const [bestRoute, otherRoute] = [...(await api.payout(claimA)).plan.routes_compared].filter((r) => r.available).sort((a, b) => b.would_receive.amount - a.would_receive.amount)
    .map((r) => Number(r.would_receive.amount));
  const material = otherRoute !== undefined && (bestRoute - otherRoute) / bestRoute >= 0.001;
  check(routeCard && /more than the other route/.test(routeCard[3]) === material, `the route card ${material ? "leaves out" : "shows"} a difference of ${(bestRoute - otherRoute).toFixed(2)} MXN on ${bestRoute}: ${JSON.stringify(routeCard)}`);
  const planBefore = await api.payout(claimA);
  check(planBefore.plan.routes_compared.length === 2 && planBefore.plan.rate.locked_for === "1 hour", "the plan did not compare two routes with a one-hour lock");
  notes.push(`The route card: ${JSON.stringify(routeCard)}. The fee card: ${JSON.stringify(feeCard)}. In full: ${planBefore.plan.route_reason}`);
  await shot("the-payout-plan-two-decision-cards-and-the-amount");
  await page.getByRole("button", { name: /I agree\. Start the payment/ }).click();
  await page.locator(".moneyline").waitFor({ timeout: 120000 });
  await page.waitForFunction(() => document.querySelector(".hold") || document.querySelector(".received"), null, { timeout: 300000, polling: 1000 });
  check((await page.locator(".hold").count()) === 1, "the bank did not refuse the transfer, so no change of circumstance was shown");
  await page.getByRole("button", { name: "Use this account for the replacement" }).waitFor({ timeout: 120000 });
  await page.waitForFunction(() => /did not ask the owner to confirm|stopped and asked/.test(document.querySelector(".refusal-cards")?.textContent ?? ""), null, { timeout: 120000, polling: 1000 }).catch(() => undefined);
  await settle(1200);
  const stopped = await api.payout(claimA);
  check(stopped.state === "FAILED" && stopped.hold.kind === "transfer_failed" && JSON.stringify(stopped.hold.needs) === JSON.stringify(["bank_details", "payer"]),
    `after the refusal the agent asks for ${JSON.stringify(stopped.hold?.needs)}, not for a new account and the holder's approval only`);
  const refusalA = await card(".refusal-cards", "refusal");
  check(refusalA && /7771/.test(refusalA[0]) && /came back/.test(refusalA[0]) && /0\.5%/.test(refusalA[1]) && /confirm the amount/.test(refusalA[1])
    && /did not ask the owner to confirm the amount/.test(refusalA[2]) && /Still asked: the corrected account and the holder's approval/.test(refusalA[2]) && /MXN/.test(refusalA[3]),
    `the refusal is not shown as a decision card: ${JSON.stringify(refusalA)}`);
  const line = words(await page.locator(".moneyline").innerText());
  check(/STOP/.test(line) && /The bank refuses it/.test(line) && /The money comes back/.test(line) && (await page.locator(".leg-stop").count()) === 1,
    `the refusal is not a red stop on the money's line: "${line}"`);
  notes.push(`The bank refused the transfer. The money's line: ${line}. The decision card: ${JSON.stringify(refusalA)}`);
  await page.locator(".pay-pane").evaluate((el) => el.scrollTo(0, 0));
  await shot("the-bank-refuses-the-money-comes-back-the-agent-decides");
  await page.locator(".hold").getByRole("button", { name: "Fill this in for Marisol" }).click();
  await settle(300);
  const corrected = await page.locator(".hold").getByLabel(/account number|CLABE/i).first().inputValue().catch(() => "");
  await page.locator(".hold .payout-form").scrollIntoViewIfNeeded();
  await shot("she-gives-the-corrected-account");
  await page.getByRole("button", { name: "Use this account for the replacement" }).click();
  await page.locator(".hold-wait").waitFor({ timeout: 60000 });
  await settle();
  // The holder approves the corrected account. A new account always comes back to the holder.
  await openHolderView();
  await pick("$2,316.40").click();
  await settle();
  const again = words(await page.locator(".queue-row").innerText());
  check(/corrected account, ending 7823/.test(again) && /the first ended 7771/.test(again), `the holder is not shown that the corrected account differs from the first: "${again.slice(0, 300)}"`);
  await shot("the-holder-approves-the-corrected-account");
  await page.getByRole("button", { name: "Approve the new terms" }).click();
  await page.goto(`${BASE}/#payout/${claimA}`);
  await waitForPaid("MXN");
  await settle(1500);
  await page.locator(".pay-pane").evaluate((el) => el.scrollTo(0, 0));
  const paidLine = words(await page.locator(".moneyline").innerText());
  check(/account ending 7771/.test(paidLine) && /account ending 7823/.test(paidLine), `the replacement does not visibly go to a different account: "${paidLine}"`);
  await shot("the-replacement-is-paid-to-the-corrected-account");
  await page.getByRole("tab", { name: /Airwallex's records/ }).click();
  await settle();
  const tab = await page.getByRole("tab", { name: /Airwallex's records/ }).innerText();
  const rows = await page.locator(".books .ledger tbody tr").count();
  check(tab.includes(`(${rows})`), `the tab says "${tab}" above ${rows} lines`);
  check(/add up to zero/.test(await page.locator(".books-big").innerText()), "Airwallex's lines are not said to add up to zero");
  await shot("airwallex-records-add-up-to-zero");
  const mxn = await payoutResult(claimA);
  check(mxn.state === "PAID" && /MXN$/.test(mxn.received ?? "") && mxn.ledger_adds_up_to_zero, `the MXN payment did not end paid with books that add up: ${JSON.stringify(mxn).slice(0, 300)}`);
  check(mxn.earlier_transfers.length === 1 && mxn.earlier_transfers[0].status !== "PAID", "the refused transfer is not on record as dead");
  check(mxn.decided_without_asking.includes("replacement_cleared") && mxn.decided_without_asking.includes("replacement_within_tolerance") && mxn.decided_without_asking.includes("route_chosen"),
    `the agent's report is incomplete: ${mxn.decided_without_asking.join(", ")}`);
  check(corrected && !corrected.endsWith("7771"), `the corrected account is the same as the first: ${corrected.slice(-4)}`);

  // 10. The same event on the small claim: the replacement falls outside the limit, so the agent stops and asks.
  await page.goto(`${BASE}/#payout/${claimB}`);
  await page.getByRole("heading", { name: "The payout plan" }).waitFor({ timeout: 30000 });
  await page.getByLabel("The receiving bank refuses the transfer").check();
  await page.getByRole("button", { name: "Show the payout plan" }).click();
  await page.locator(".plan-receive").waitFor({ timeout: 60000 });
  await page.getByRole("button", { name: /I agree\. Start the payment/ }).click();
  await page.getByRole("button", { name: "Use this account for the replacement" }).waitFor({ timeout: 300000 });
  await page.waitForFunction(() => /did not ask the owner to confirm|stopped and asked/.test(document.querySelector(".refusal-cards")?.textContent ?? ""), null, { timeout: 120000, polling: 1000 }).catch(() => undefined);
  await settle(1200);
  const refusalB = await card(".refusal-cards", "refusal");
  check(refusalB && /Outside the limit: it stopped and asked/.test(refusalB[2]), `on the small claim the same refusal does not stop and ask: ${JSON.stringify(refusalB)}`);
  notes.push(`The same refusal on the 95.00 dollar claim: ${JSON.stringify(refusalB)}`);
  await page.locator(".pay-pane").evaluate((el) => el.scrollTo(0, 0));
  await shot("the-same-refusal-on-a-small-claim-stops-and-asks");
  await page.locator(".hold").getByRole("button", { name: "Fill this in for Marisol" }).click();
  await page.getByRole("button", { name: "Use this account for the replacement" }).click();
  await page.locator(".hold-wait").waitFor({ timeout: 60000 });
  await api.approve(claimB);
  await page.getByRole("button", { name: /I agree to .* Carry on/ }).waitFor({ timeout: 60000 });
  const waiting = await api.payout(claimB);
  check(JSON.stringify(waiting.hold?.needs) === JSON.stringify(["claimant"]), `the small claim is not waiting for the owner alone: ${JSON.stringify(waiting.hold?.needs)}`);

  // 11. Two claims side by side in the holder's view: the same event, the same limits, two outcomes.
  await openHolderView();
  await page.getByRole("button", { name: "Two refused transfers, side by side" }).click();
  await page.locator(".compare").waitFor();
  await settle();
  const compare = words(await page.locator(".compare").innerText());
  check(/\$2,316\.40/.test(compare) && /\$95\.00/.test(compare) && /not asked about the amount again/.test(compare) && /stopped and asked the owner/.test(compare)
    && /corrected account is always asked for/.test(compare),
    `the two claims are not side by side with their different outcomes: "${compare.slice(0, 300)}"`);
  notes.push(`Side by side: ${compare}`);
  await shot("two-claims-side-by-side-the-same-event-two-outcomes");
  // She agrees to the smaller amount, and the replacement is paid.
  await page.goto(`${BASE}/#payout/${claimB}`);
  await page.getByRole("button", { name: /I agree to .* Carry on/ }).click();
  await waitForPaid("MXN, small claim");
  const small = await payoutResult(claimB);
  check(small.state === "PAID" && small.ledger_adds_up_to_zero && small.earlier_transfers.length === 1, `the small MXN payment did not end paid with books that add up: ${JSON.stringify(small).slice(0, 300)}`);

  // 12. A small claim under the fee rule. Amihan's account is typed in Tagalog. Her 120.00 deposit is below the
  //     holder's small-claim line, so the holder bears Airwallex's fees and the claim arrives whole.
  await page.goto(`${BASE}/#history`);
  await page.getByRole("heading", { name: "Tell us your history" }).waitFor();
  await page.getByRole("button", { name: /Read Amihan's account, typed in Tagalog/ }).click();
  await page.locator(".heard-speaking").waitFor();
  await page.locator(".summary").waitFor({ timeout: 180000 });
  await page.locator(".heard:not(.heard-stale) .timeline").waitFor({ timeout: 60000 });
  await settle(900);
  check(/Tagalog|Filipino/i.test(await page.locator(".heard").innerText()), "the intake did not recognise Tagalog");
  await page.locator(".match-local").first().waitFor({ timeout: 20000 }).catch(() => undefined);
  await settle();
  await shot("amihan-typed-in-tagalog-with-her-matches");
  const claimC = await openClaimOn("$120.00", "Amihan");
  await addDocuments(["Passport photo page", "Taxpayer number letter", "Bank statement"], 3);
  await proofReady("Amihan");
  await page.getByRole("tab", { name: "Bank account" }).click();
  await page.getByRole("button", { name: "Fill this in for Amihan" }).click();
  await page.getByRole("button", { name: "Save this bank account" }).click();
  await page.locator("#payee-on-file").waitFor({ timeout: 30000 });
  await openHolderView();
  await pick("$120.00").click();
  await settle();
  const feeC = await card(".queue-row", "fee_rule");
  check(feeC && /4\.5%/.test(feeC[0]) && /\$125\.38/.test(feeC[2]) && /whole \$120\.00/.test(feeC[3]), `the fee rule on the small claim is not shown as a card: ${JSON.stringify(feeC)}`);
  notes.push(`The fee card on the 120.00 dollar claim: ${JSON.stringify(feeC)}`);
  await shot("a-small-claim-the-holder-bears-the-fees");
  await page.getByRole("button", { name: "Approve these terms" }).click();
  await page.locator(".queue-row .state", { hasText: "Approved" }).waitFor({ timeout: 30000 });
  await page.goto(`${BASE}/#payout/${claimC}`);
  await page.getByRole("heading", { name: "The payout plan" }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "Show the payout plan" }).click();
  await page.locator(".plan-receive").waitFor({ timeout: 60000 });
  check(/PHP/.test(await page.locator(".plan-receive").innerText()), "the payout plan for Amihan is not in Philippine pesos");
  await page.getByRole("button", { name: /I agree\. Start the payment/ }).click();
  await waitForPaid("PHP");
  await settle(1500);
  await shot("the-small-claim-paid-whole");
  const php = await payoutResult(claimC);
  check(php.state === "PAID" && /PHP$/.test(php.received ?? "") && php.ledger_adds_up_to_zero, `the PHP payment did not end paid with books that add up: ${JSON.stringify(php).slice(0, 300)}`);
  check(php.arrived_usd === "125.38" && php.claim_usd === "120.00", `the holder did not send the claim plus the fees: arrived ${php.arrived_usd} for a claim of ${php.claim_usd}`);

  // 13. The handover date decides. Amihan's wages claim has only a staff badge. With time in hand the agent asks
  //     her for what is missing. When the holder's date is close, it stops waiting: what is proven is paid, and
  //     this property is released to the State process, where she can claim it herself with the fallback packet.
  const claimD = await api.openClaim("amihan", 1840.55, ["Staff badge"], { bank: false });
  const refusedApproval = await fetch(`${BASE}/api/payer/claims/${claimD}/approve`, { method: "POST", headers: { "X-Payer-Key": PAYER_KEY } });
  check(refusedApproval.status === 409, `the API approved a claim with incomplete proof (status ${refusedApproval.status})`);
  await openHolderView();
  await pick("$1,840.55").click();
  await settle();
  check(await page.getByRole("button", { name: "Approve these terms" }).isDisabled(), "a claim with incomplete proof can be approved");
  const ask = await card(".queue-row", "deadline");
  check(ask && /Time in hand: it asked the owner for photo identification/.test(ask[2]), `with time in hand the holder is not shown that the agent asks for the missing document: ${JSON.stringify(ask)}`);
  notes.push(`The deadline choice with ${handover.days_left} days left: ${JSON.stringify(ask)}`);
  await shot("time-in-hand-the-agent-asks-for-the-missing-document");
  const near = nearHandoverDate();
  await page.getByRole("button", { name: "Change them" }).click();
  await page.getByLabel("Your handover date to the State").fill(near);
  await page.getByRole("button", { name: "Save the limits" }).click();
  await page.waitForFunction(() => document.querySelector(".handover-near"), null, { timeout: 15000 });
  await settle(3500);   // the queue is read again every three seconds
  const release = await card(".queue-row", "deadline");
  check(release && /Too close to wait/.test(release[2]) && /Remit Report/.test(release[3]), `near the handover the agent does not release the unproven claim: ${JSON.stringify(release)}`);
  const across = await card(".payer-left", "deadline");
  check(across && /pays what is proven/.test(across[2]) && /releases the rest/.test(across[2]), `near the handover the holder is not told that it pays what is proven and releases the rest: ${JSON.stringify(across)}`);
  notes.push(`With the handover date set to ${near}: ${JSON.stringify(release)}. Across the queue: ${JSON.stringify(across)}`);
  await shot("near-the-handover-it-releases-what-is-not-proven");

  // The fallback, off the main path: if the holder does not pay, she claims it from the State herself.
  await page.goto(`${BASE}/#claim/${claimD}`);
  await page.getByRole("heading", { name: "Proof file" }).waitFor({ timeout: 30000 });
  const released = await card(".claim-deadline", "deadline");
  check(released && /released to the State process/.test(released[2]), `the owner is not told that her property is released to the State process: ${JSON.stringify(released)}`);
  await page.getByRole("tab", { name: "If the holder does not pay" }).click();
  await page.getByRole("heading", { name: /If the holder does not pay: claim it from the State yourself/ }).waitFor();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download the claim packet" }).click(),
  ]);
  const packetDir = join(SHOTS, "packet");
  mkdirSync(packetDir, { recursive: true });
  const pdf = join(packetDir, "claim-packet.pdf");
  await download.saveAs(pdf);
  const made = spawnSync("pdftoppm", ["-r", "80", "-png", pdf, join(packetDir, "page")]);
  const pages = readdirSync(packetDir).filter((f) => f.endsWith(".png"));
  check(made.status === 0 && pages.length >= 3, "the packet PDF could not be turned into pictures");
  notes.push(`The fallback packet for the State: ${pages.length} pages rendered to docs/shots/walk/packet/.`);
  await settle(1500);
  await shot("the-fallback-claim-it-from-the-state-yourself");

  // The keyboard: Tab from the top of the history screen must reach a control with a visible focus ring.
  await page.goto(`${BASE}/#history`);
  await page.getByRole("heading", { name: "Tell us your history" }).waitFor();
  for (let i = 0; i < 4; i++) await page.keyboard.press("Tab");
  const ring = await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
  check(ring !== "none", "keyboard focus has no visible ring");

  // The last picture is the paid claim with its whole history.
  await page.goto(`${BASE}/#claim/${claimA}`);
  await page.locator(".state", { hasText: "Paid" }).waitFor({ timeout: 30000 });
  await page.getByRole("tab", { name: "History" }).click();
  await settle();
  check(!(await api.claim(claimA)).history.some((e) => /signed the packet/.test(e.note)), "the paid claim's history passes through the packet for the State");
  await shot("the-claim-paid-with-its-whole-history");

  await context.close();
  return { book_and_batch: batchResult, queensland,
    claims: { mxn_refused_and_replaced: claimA, mxn_small_refused_stopped_and_asked: claimB, php_small_claim: claimC, proof_not_ready_at_the_handover: claimD },
    standing_instructions: RULES, handover: { at_the_start: handover, set_near: near, schedule: handover.schedule },
    payouts: { MXN_transfer_refused_and_replaced: mxn, MXN_small_claim_refused_stopped_and_asked: small, PHP_small_claim_under_the_fee_rule: php },
    opening_search_line: liveLine };
}

/** Sets a range control the way a person dragging it would: the value, then the events React listens for. */
async function slide(label, value) {
  await page.getByLabel(label, { exact: true }).evaluate((el, v) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, String(v));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }, value);
}

const bookOf = (holder, inputs = {}) => api.get(`/api/book?${new URLSearchParams({ holder, ...inputs })}`);

/** The Book screen for the largest holder and two others, the plan under changed limits, and a batch run from it. */
async function wholeBook(holders) {
  const key = { headers: { "X-Payer-Key": PAYER_KEY } };
  const largest = holders.figures.by_amount[0].name;
  await page.goto(`${BASE}/#holders`);
  await page.locator(".holder-list li").first().waitFor();
  check(words(await page.locator(".holder-list .holder-open").first().innerText()).endsWith(largest), "the largest holder is not first on the holders screen");
  await page.locator(".holder-list .holder-open").first().click();
  await page.locator(".book-list li").first().waitFor({ timeout: 30000 });
  await settle(700);
  const plan = await bookOf(largest);
  const t = plan.totals;
  const us = (n) => `$${Math.round(n).toLocaleString("en-US")}`;
  const screen = words(await page.locator(".book-body").innerText());
  check(screen.includes(us(t.local.usd)) && screen.includes(us(t.swift.usd)) && screen.includes(us(t.unpayable.usd)) && screen.includes(us(t.cost.usd)),
    `the Book screen does not show the plan's totals for ${largest}: local ${us(t.local.usd)}, SWIFT ${us(t.swift.usd)}, not payable ${us(t.unpayable.usd)}, fees ${us(t.cost.usd)}`);
  check(/public file/.test(screen) && /Airwallex's sandbox/.test(screen) && /did not ask for this plan/.test(screen), "the Book screen does not say that this is a plan from public figures that the holder did not ask for");
  check(Math.abs(t.local.usd + t.swift.usd + t.unpayable.usd + t.too_small.usd - t.usd) < 0.01 && t.owners === plan.holder.properties,
    "the routes of the book do not add up to the holder's own total");
  const kindsOfCard = ["book_routes", "book_fees", "book_small", "book_funding", "book_order", "book_tolerance"];
  const cardsNow = {};
  for (const kind of kindsOfCard) cardsNow[kind] = await card(".book-cards", kind);
  check(kindsOfCard.every((k) => cardsNow[k]), `a decision of the plan is not shown as a card: ${kindsOfCard.filter((k) => !cardsNow[k]).join(", ")}`);
  check((await page.locator(".book-list li").count()) === plan.corridors.length && plan.corridors.length >= 100, `the corridors are not all listed (${plan.corridors.length})`);
  notes.push(`The book of ${largest}: ${t.owners.toLocaleString("en-US")} properties, ${us(t.usd)}, ${t.countries} countries. ${us(t.local.usd)} by local rails in ${t.local.countries} countries, ${us(t.swift.usd)} by SWIFT in ${t.swift.countries}, ${us(t.unpayable.usd)} not payable in ${t.unpayable.countries}; ${t.too_small.owners.toLocaleString("en-US")} claims smaller than their fees. Fees ${us(t.cost.usd)}, ${t.cost.percent}% of ${us(t.planned.usd)}. The holder funds ${us(plan.funding.holder_funds_usd)}; ${plan.funding.batch_currencies} currencies converted once, saving $${plan.funding.saving_usd.toFixed(2)} on the rate and ${(plan.funding.conversions_if_each - plan.funding.conversions_planned).toLocaleString("en-US")} conversions.`);
  notes.push(`The plan's decision cards: ${JSON.stringify(cardsNow)}`);
  await shot("the-whole-book-of-the-largest-holder");
  await page.getByRole("tab", { name: /Order of work/ }).click();
  await settle(300);
  check(words(await page.locator(".book-list li").first().innerText()).includes(plan.order.work[0].name) && /a day/.test(await page.locator(".book-list li").first().innerText()),
    "the order of work does not start with the corridor that reaches the most dollars a day");
  await shot("the-order-of-work-most-dollars-a-day-first");
  await page.getByRole("tab", { name: /Funding/ }).click();
  await settle(300);
  const funding = words(await page.locator(".book-list").innerText());
  check(/Convert once/.test(funding) && /Each payment/.test(funding) && /Quoted at 6 sizes/.test(funding) && /one-hour lock costs/.test(funding) && /Turning unspent money back costs/.test(funding),
    `the funding decision is not shown with what was measured: "${funding.slice(0, 300)}"`);
  await shot("the-funding-decision-from-real-quotes");

  // The decisions change when the inputs change. First the small-claim line, then the handover date.
  await page.getByRole("tab", { name: /Corridors/ }).click();
  await slide("Small-claim line", 1000);
  await page.locator(".book-changes").waitFor({ timeout: 15000 });
  await settle(700);
  const raised = await bookOf(largest, { small_claim_usd: "1000" });
  const changed = words(await page.locator(".book-changes").innerText());
  check(raised.totals.holder_bears.owners - t.holder_bears.owners >= 100 && changed.includes(raised.totals.holder_bears.owners.toLocaleString("en-US")) && changed.includes(t.holder_bears.owners.toLocaleString("en-US"))
    && raised.totals.holder_funds_usd > t.holder_funds_usd,
    `raising the small-claim line does not visibly move claims to the holder: "${changed}"`);
  notes.push(`Small-claim line raised from $250 to $1,000: ${raised.changes.slice(1).map((c) => `${c.what}: ${c.before} to ${c.after}`).join("; ")}.`);
  await shot("raising-the-small-claim-line-moves-claims-to-the-holder");
  await page.getByRole("button", { name: "back to the saved limits" }).click();
  await page.locator(".book-changes").waitFor({ state: "detached", timeout: 15000 });
  await page.getByRole("button", { name: "In 34 days" }).click();
  await page.locator(".book-changes").waitFor({ timeout: 15000 });
  await settle(700);
  const nearDate = new Date(Date.now() + 34 * 86400000).toISOString().slice(0, 10);
  const closer = await bookOf(largest, { handover_date: nearDate });
  const dropped = words(await page.locator(".book-changes").innerText());
  check(closer.order.dropped.length > 0 && closer.order.dropped.every((c) => c.needs_days > closer.days_left) && closer.order.work.every((c) => c.needs_days <= closer.days_left)
    && dropped.includes(String(closer.totals.planned.countries)) && /too close/i.test(dropped),
    `moving the handover date closer does not drop the slow corridors: "${dropped}"`);
  const orderCard = await card(".book-cards", "book_order");
  check(orderCard && /cannot finish in time/.test(orderCard[2]), `the order card does not say what is dropped: ${JSON.stringify(orderCard)}`);
  notes.push(`Handover date moved to ${nearDate} (${closer.days_left} days): ${closer.changes.slice(1).map((c) => `${c.what}: ${c.before ? `${c.before} to ` : ""}${c.after}`).join("; ")}.`);
  await shot("moving-the-handover-date-closer-drops-the-slow-corridors");
  await page.getByRole("button", { name: "back to the saved limits" }).click();
  await slide("Tolerance", 2);
  await page.locator(".book-changes").waitFor({ timeout: 15000 });
  await settle(700);
  const wider = await bookOf(largest, { tolerance_percent: "2" });
  check(wider.totals.refusal.inside > t.refusal.inside, "a wider tolerance does not move claims inside it");
  notes.push(`Tolerance raised from 0.5% to 2%: ${wider.changes.slice(1).map((c) => `${c.what}: ${c.before} to ${c.after}`).join("; ")}.`);
  await page.getByRole("button", { name: "back to the saved limits" }).click();

  // Two other holders: one chosen from the list, one typed.
  const others = {};
  await page.getByLabel("Choose a holder").selectOption({ label: "APPLE INC" });
  await page.waitForFunction(() => document.querySelector(".book-holder")?.textContent === "APPLE INC", null, { timeout: 15000 });
  await settle(700);
  others["APPLE INC"] = await bookOf("APPLE INC");
  check(others["APPLE INC"].totals.too_small.owners > 10000, "Apple's book does not show its many claims that are smaller than their fees");
  await shot("another-book-many-claims-smaller-than-their-fees");
  await page.getByLabel("or type a holder's name").fill("herbalife");
  await page.locator(".book-match").first().waitFor({ timeout: 15000 });
  await page.locator(".book-match").first().click();
  await page.waitForFunction(() => /HERBALIFE/.test(document.querySelector(".book-holder")?.textContent ?? ""), null, { timeout: 15000 });
  await settle(700);
  const typedName = (await page.locator(".book-holder").innerText()).trim();
  others[typedName] = await bookOf(typedName);
  await shot("a-typed-holder-name-opens-its-book");
  for (const [name, p] of Object.entries(others))
    notes.push(`The book of ${name}: ${p.totals.owners.toLocaleString("en-US")} properties, ${us(p.totals.usd)}. ${us(p.totals.local.usd)} local, ${us(p.totals.swift.usd)} SWIFT, ${us(p.totals.unpayable.usd)} not payable; ${p.totals.too_small.owners.toLocaleString("en-US")} claims (${us(p.totals.too_small.usd)}) smaller than their fees. Fees ${us(p.totals.cost.usd)}, ${p.totals.cost.percent}%.`);
  const unlisted = await fetch(`${BASE}/api/book/holders?q=dds`).then((r) => r.json());
  check(unlisted.matches.every((m) => !/\bDDS\b/.test(m.name)), "a holder whose name could be a person's can be opened by typing it");

  // A slice of the largest holder's plan, run as a real batch on the sandbox.
  await page.getByLabel("Choose a holder").selectOption({ label: largest });
  await page.waitForFunction((name) => document.querySelector(".book-holder")?.textContent === name, largest, { timeout: 15000 });
  await settle(500);
  const refused = await fetch(`${BASE}/api/payer/batches`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ holder: largest }) });
  check(refused.status === 401, `a batch can be made without the holder's key (${refused.status})`);
  await page.getByRole("button", { name: "Run a slice on the sandbox" }).click();
  await page.locator(".batch-item").first().waitFor({ timeout: 120000 });
  const batchId = page.url().split("#batch/")[1];
  const view = () => fetch(`${BASE}/api/payer/batches/${batchId}`, key).then((r) => r.json());
  const before = await view();
  check(before.payments >= 5 && new Set(before.items.map((i) => i.country)).size >= 5 && new Set(before.items.map((i) => i.currency)).size >= 5,
    `the batch does not cover five countries and currencies: ${before.items.map((i) => `${i.country} ${i.currency}`).join(", ")}`);
  check(before.deposit.amount === null && before.reconciliation.rows === 0, "money moved before the holder approved the batch");
  const planned = words(await page.locator(".batch-body").innerText());
  check(/invented/.test(planned) && /What an approval would cover/i.test(planned) && planned.includes(`${before.payments}`), `the batch is not shown as a plan that waits for the holder: "${planned.slice(0, 200)}"`);
  await settle(600);
  await shot("a-batch-written-from-the-plan-waits-for-the-holder");
  await page.getByRole("button", { name: "Approve these terms and start" }).click();
  await page.waitForFunction(() => document.querySelectorAll(".item-paid").length >= 2, null, { timeout: 300000, polling: 1000 });
  await shot("the-batch-running-each-payment-live");
  // The refused transfers stop for people; everything else is paid.
  await page.waitForFunction(() => document.querySelectorAll(".batch-act").length >= 1 && document.querySelectorAll(".item-moving").length === 0, null, { timeout: 300000, polling: 1000 });
  await settle(1500);
  const stoppedView = await view();
  const waitingFor = stoppedView.items.filter((i) => i.needs.length);
  check(waitingFor.length === 2 && waitingFor.every((i) => i.needs[0] === "bank_details" && i.attempts.length === 1) && stoppedView.paid === stoppedView.payments - 2,
    `the two refused payments are not the only ones waiting: ${JSON.stringify(stoppedView.items.map((i) => [i.n, i.state_words]))}`);
  const outcomes = waitingFor.map((i) => i.attempts[0].outcome?.claimant_asked);
  check(outcomes.includes(true) && outcomes.includes(false), `the two refusals do not show both outcomes of the tolerance: ${JSON.stringify(outcomes)}`);
  await shot("two-transfers-refused-the-rest-paid");
  // The script plays the people each refusal waits for, on the screen: the owner gives her second account, the
  // holder approves it, and where the replacement is outside the tolerance the owner agrees to the amount.
  const played = [];
  for (const item of waitingFor) {
    const cardOf = page.locator(`.batch-item[data-country="${item.country}"]`);
    for (let step = 0; step < 4 && (await cardOf.locator(".batch-act").count()) > 0; step++) {
      const label = words(await cardOf.locator(".batch-act").innerText());
      played.push(`${item.owner.name}: ${label}`);
      await cardOf.locator(".batch-act").click();
      await page.waitForFunction(([country, was]) => {
        const now = document.querySelector(`.batch-item[data-country="${country}"] .batch-act`);
        return !now || now.textContent.trim() !== was;
      }, [item.country, label], { timeout: 180000, polling: 500 });
      await settle(600);
      if (/give the corrected account/.test(label) && item === waitingFor[0]) {
        check(/Holder: approve the account ending/.test(await cardOf.innerText()), "a corrected account in the batch does not go to the holder for approval");
        await shot("a-corrected-account-waits-for-the-holder");
      }
    }
  }
  check(played.filter((l) => /give the corrected account/.test(l)).length === 2 && played.filter((l) => /Holder: approve/.test(l)).length === 2
    && played.filter((l) => /agree to the smaller amount/.test(l)).length === 1,
    `the refusals were not put right by the people they wait for, in order: ${JSON.stringify(played)}`);
  notes.push(`What was done for the two refused payments, in order: ${played.join("; ")}.`);
  await page.locator(".batch-progress-done").waitFor({ timeout: 300000 });
  await page.locator(".batch-books-zero").waitFor({ timeout: 60000 });
  await settle(1500);
  const done = await view();
  check(done.reconciliation.balanced && done.reconciliation.sums.every((s) => Number(s.left) === 0) && done.paid === done.payments,
    `the batch did not end with every currency at zero: ${JSON.stringify(done.reconciliation.sums)}`);
  check(done.items.filter((i) => i.attempts.length === 1).every((i) => i.account_last4 !== i.attempts[0].account_last4 && i.refused_last4 === i.attempts[0].account_last4),
    "a replacement in the batch went to the account the bank had refused");
  check(done.funding.filter((f) => f.mode === "batch").every((f) => f.conversion_id) && done.costs.actual.transfers === done.payments + 2,
    "the batch was not funded with one conversion for each held currency, or its transfers do not count the two replacements");
  const doneText = words(await page.locator(".batch-left").innerText());
  check(/Every currency adds up to zero/.test(doneText) && /Planned cost beside actual cost/i.test(doneText) && doneText.includes(`$${done.costs.planned.usd}`) && doneText.includes(`$${done.costs.actual.usd}`),
    `the Batch screen does not end on the reconciliation and the planned cost beside the actual cost: "${doneText.slice(0, 300)}"`);
  notes.push(`The batch ${batchId}: ${done.items.map((i) => `${i.owner.name} (${i.owner.country_name}) ${i.paid.amount} ${i.paid.currency}${i.attempts.length ? `, after a refusal (${i.attempts[0].outcome.claimant_asked ? "outside the tolerance: the owner was asked about the amount" : "inside the tolerance: the owner was not asked about the amount"})` : ""}`).join("; ")}. Deposit ${done.deposit.amount} USD, Airwallex's fee ${done.deposit.fee} USD. Planned cost ${done.costs.planned.usd} USD, booked ${done.costs.actual.usd} USD. Ledger: ${done.reconciliation.sums.map((s) => `${s.currency} left ${s.left}`).join(", ")}. ${done.api_calls} calls to Airwallex.`);
  await shot("the-batch-paid-and-reconciled-to-zero");
  return { holder: largest, plan: { inputs: plan.inputs, totals: plan.totals, funding: { ...plan.funding, currencies: plan.funding.currencies.length }, order: plan.order.work.slice(0, 5).map((c) => `${c.name}: $${c.usd_per_day} a day`) },
    small_claim_line_1000: raised.changes, handover_in_34_days: closer.changes, tolerance_2_percent: wider.changes,
    others: Object.fromEntries(Object.entries(others).map(([name, p]) => [name, { totals: p.totals, saving_usd: p.funding.saving_usd }])),
    batch: { id: batchId, payments: done.items.map((i) => ({ n: i.n, owner: i.owner.name, country: i.country, currency: i.currency, rail: i.method, owed_usd: i.claim_usd, paid: i.paid, fee: i.fee, refused_once: i.attempts.length === 1, transfer: i.transfer_id })),
      deposit: done.deposit, funding: done.funding, costs: done.costs, ledger: done.reconciliation.sums, balanced: done.reconciliation.balanced, api_calls: done.api_calls } };
}

// ---------------------------------------------------------------------------------------------------------------
// The holder's own list: before the money ever reaches the State.

async function openHolderList(tab) {
  await page.goto(`${OUTREACH}/#list`);
  if (await page.getByRole("heading", { name: "The holder's list is locked" }).isVisible().catch(() => false)) {
    await page.getByLabel("Holder's key").fill(PAYER_KEY);
    await page.getByRole("button", { name: "Open the holder's list" }).click();
  }
  await page.locator(".outreach-top").waitFor({ timeout: 30000 });
  if (tab) await page.getByRole("tab", { name: new RegExp(tab) }).click();
  await settle(700);
}

async function outreachJourney(browser) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, acceptDownloads: true });
  page = await context.newPage();
  page.on("console", (m) => m.type() === "error" && !/status of 4\d\d/.test(m.text()) && fail(`browser console: ${m.text().slice(0, 200)}`));
  page.on("pageerror", (e) => fail(`page error: ${e.message.slice(0, 200)}`));
  page.on("response", (r) => r.status() >= 500 && fail(`${r.status()} from ${r.url()}`));
  const holder = { "X-Payer-Key": PAYER_KEY };
  const asHolder = async (path, init = {}) => (await fetch(OUTREACH + path, { ...init, headers: { ...(init.headers ?? {}), ...holder } })).json();
  const numbers = {};

  // 1. From the "For holders" screen to the holder's own list. The routes are behind the holder's key.
  const locked = await fetch(`${OUTREACH}/api/holder/outreach`);
  check(locked.status === 401, `the holder's list answered without the key (${locked.status})`);
  await page.goto(`${OUTREACH}/#holders`);
  await page.getByRole("link", { name: "Bring your own list" }).waitFor();
  await openHolderList();
  await page.getByRole("heading", { name: "Your own list, before the State" }).waitFor();
  await shot("the-holders-own-list-starts-with-its-file");

  // 2. The upload. The invented file is written by the generator and uploaded like any holder's file.
  const made = spawnSync("uv", ["run", "python", "scripts/make_invented_holder_file.py", "--out", join(SAMPLES, "holder")], { cwd: ROOT });
  if (made.status !== 0) throw new Error(`make_invented_holder_file.py failed: ${made.stderr}`);
  const file = join(SAMPLES, "holder", "valle-sereno-outstanding-payroll-INVENTED.csv");
  await page.locator('input[type="file"]').setInputFiles(file);
  await page.getByRole("button", { name: "Read my file" }).click();
  await page.getByRole("heading", { name: "Which column is which" }).waitFor({ timeout: 180000 });
  await settle();
  let view = await asHolder("/api/holder/outreach");
  const proposal = view.list.proposal;
  check(view.list.invented === true && view.list.header_row === 5, `the invented file was not recognised, or its column titles were not found on row 5: ${JSON.stringify([view.list.invented, view.list.header_row])}`);
  check(proposal.fields.owner_name?.column === "Employee Name (Last, First MI)" && proposal.fields.amount?.column === "Net Amt"
    && proposal.fields.last_activity?.column === "Chk Date" && proposal.fields.country?.column === "Ctry" && proposal.fields.reference?.column === "EE ID",
    `the proposed columns are wrong: ${JSON.stringify(proposal.fields)}`);
  check(proposal.by !== "model" || (proposal.sample_rows_sent > 0 && proposal.sample_rows_sent <= 20), `more than 20 rows went to the model: ${proposal.sample_rows_sent}`);
  numbers.mapping_proposed_by = proposal.by === "model" ? `a language model, from the column titles and ${proposal.sample_rows_sent} masked rows` : `code (${proposal.model_note})`;
  notes.push(`Outreach, the columns: proposed by ${numbers.mapping_proposed_by}. ${Object.entries(proposal.fields).map(([f, c]) => `${f} = ${c.column}`).join("; ")}. Not used: ${proposal.unused_columns.join(", ")}.`);
  await shot("the-agent-proposes-which-column-is-which");

  // 3. Confirmed: every row is checked in code, and the queue is what is owed abroad and when it goes to the State.
  await page.getByRole("button", { name: "Confirm the columns" }).click();
  await page.getByRole("heading", { name: "Owed abroad, and due to the State" }).waitFor({ timeout: 60000 });
  await page.locator(".queue-item").first().waitFor();
  await settle();
  view = await asHolder("/api/holder/outreach");
  const pic = view.picture;
  Object.assign(numbers, { rows: view.list.rows_read, usable: view.list.valid, failed: view.list.failed, failures: view.list.failures.map((f) => `${f.rows}: ${f.reason}`),
    owed_abroad: `${pic.abroad.balances} owners, ${pic.abroad.amount} USD`, due_soon: `${pic.abroad_due_soon.balances} owners, ${pic.abroad_due_soon.amount} USD, to the State in ${pic.abroad_due_soon.days} days (${pic.abroad_due_soon.handover})`,
    in_the_notice_window_now: `${pic.abroad_window_open.balances} owners, ${pic.abroad_window_open.amount} USD`, under_50_dollars: `${pic.abroad_under_minimum.balances} owners`,
    countries: pic.by_country.length, top_countries: pic.by_country.slice(0, 5).map((c) => `${c.name} ${c.amount}`) });
  check(view.list.valid + view.list.failed === view.list.rows_read && view.list.failed > 0, "the usable and failed rows do not add up to the rows read");
  const figures = words(await page.locator(".big-figures").innerText());
  check(figures.includes(view.list.rows_read.toLocaleString("en-US")) && figures.includes(`${pic.abroad_due_soon.days} days`), `the queue does not lead with its figures: "${figures}"`);
  const firstRow = words(await page.locator(".queue-item").first().innerText());
  check(/days/.test(firstRow) && /\$/.test(firstRow), `the first row of the queue does not say the days and the amount: "${firstRow}"`);
  notes.push(`Outreach, the queue: ${figures}`);
  await shot("the-working-queue-owed-abroad-due-to-the-state-in-n-days");
  await page.locator(".fold-panel summary", { hasText: "rows failed" }).click();
  await settle(300);
  await shot("the-rows-that-failed-and-why");
  await page.locator(".fold-panel summary", { hasText: "rows failed" }).click();
  await page.locator(".fold-panel summary", { hasText: "The rules" }).click();
  await settle(300);
  check((await page.locator('.law-list a[href^="https://www.sco.ca.gov/"]').count()) >= 5, "the rules are not shown with their sources on the Controller's site");
  await shot("the-rules-with-their-sources");

  // 4. The notices. The agent decides who is notified first, inside the holder's limits; nothing is sent.
  await page.getByRole("button", { name: "Go to the notices" }).click();
  await page.getByRole("heading", { name: "The notice the law requires" }).waitFor();
  await settle();
  const sendsNothing = words(await page.locator(".sends-nothing").innerText());
  check(/Nothing is sent from here/.test(sendsNothing) && /mark it sent/.test(sendsNothing), `the screen does not say that nothing is sent: "${sendsNothing}"`);
  const first = await card(".decision-stack", "notify_first");
  check(first && /owners abroad are owed/.test(first[0]) && /to prepare/.test(first[2]), `the "who is notified first" card is missing or wrong: ${JSON.stringify(first)}`);
  await shot("who-is-notified-first-a-decision-card");
  await page.getByRole("button", { name: /^Prepare [\d,]+ notices$/ }).click();
  await page.locator(".notice-list li").first().waitFor({ timeout: 180000 });
  await settle(800);
  view = await asHolder("/api/holder/outreach");
  Object.assign(numbers, { notices_prepared: view.notices.count, notices_ready: view.notices.ready, notices_held_back: view.notices.held,
    languages: view.notices.languages.map((l) => `${l.language} ${l.notices}`) });
  check(view.notices.ready > 0 && view.notices.to_prepare === 0, "the notices were not prepared");
  notes.push(`Outreach, the notices: ${view.notices.count} prepared, ${view.notices.ready} ready, ${view.notices.held} held back. ${numbers.languages.join(", ")}.`);
  notes.push(`Outreach, the decision cards: ${JSON.stringify(view.notices.cards.map((c) => [c.title, c.happened, c.allowed, c.did, c.money]))}`);
  await shot("the-notices-prepared-in-the-agents-order");

  // 5. Marisol's notice: every element the law requires, in Spanish and in English, and the letter as a PDF.
  await page.getByLabel("Find an owner by name").fill("Tolmedo");
  await page.getByRole("button", { name: "Find" }).click();
  await page.locator(".notice-list .payer-pick", { hasText: "Tolmedo" }).click();
  await page.locator(".notice-detail").waitFor();
  await settle();
  const found = (await asHolder("/api/holder/notices?q=Tolmedo")).rows[0];
  const detail = await asHolder(`/api/holder/notices/${found.id}`);
  check(detail.elements.length >= 9 && detail.elements.every((e) => e.present), `a required element is missing from her notice: ${JSON.stringify(detail.elements.filter((e) => !e.present))}`);
  check(detail.language.code === "es" && detail.language.translated, `her notice is not in Spanish: ${JSON.stringify(detail.language)}`);
  const spanish = words(await page.locator(".notice-text").innerText());
  check(/EL ESTADO DE CALIFORNIA/.test(spanish) && spanish.includes("USD 1,284.60") && spanish.includes(detail.handover) && spanish.includes("4471"),
    `the Spanish notice does not carry the heading and the facts: "${spanish.slice(0, 300)}"`);
  check((await page.locator(".element-yes").count()) === detail.elements.length, "the required elements are not all shown as present");
  await shot("her-notice-in-spanish-with-every-required-element-checked", { checks: false });
  await audit("her-notice-in-spanish");
  await page.getByRole("button", { name: "Show it in English" }).click();
  await settle(300);
  const english = words(await page.locator(".notice-text").innerText());
  check(/THE STATE OF CALIFORNIA REQUIRES US TO NOTIFY YOU/.test(english) && english.includes("USD 1,284.60") && english.includes(detail.handover) && english.includes("4471"),
    "the English notice does not carry the heading and the same facts");
  await shot("the-same-notice-in-english-with-the-same-facts");
  const letterDir = join(shotsDir, "letter");
  mkdirSync(letterDir, { recursive: true });
  const pdf = Buffer.from(await (await fetch(`${OUTREACH}/api/holder/notices/${found.id}/letter.pdf`, { headers: holder })).arrayBuffer());
  writeFileSync(join(letterDir, "notice.pdf"), pdf);
  const drawn = spawnSync("pdftoppm", ["-r", "80", "-png", join(letterDir, "notice.pdf"), join(letterDir, "page")]);
  const pages = readdirSync(letterDir).filter((f) => f.endsWith(".png"));
  check(drawn.status === 0 && pages.length === 2, `the letter is not two pages, English then Spanish (${pages.length})`);
  const batch = await fetch(`${OUTREACH}/api/holder/notices/batch.pdf?which=unsent&limit=40`, { headers: holder });
  check(batch.status === 200 && Number(batch.headers.get("content-length")) > 50000, "the batch of letters could not be made");
  notes.push(`Outreach, her letter: ${pages.length} pages rendered to docs/shots/walk/letter/ (invented person). A batch of 40 letters is ${batch.headers.get("content-length")} bytes.`);

  // 6. Before the holder marks it sent, the code opens nothing. Then the holder marks them all sent.
  const early = await fetch(`${OUTREACH}/api/notices/${found.code}`);
  check(early.status === 404, `a notice that was not marked sent opened with its code (${early.status})`);
  await page.getByRole("button", { name: "Back to the list" }).click();
  await page.getByRole("button", { name: "I have sent them all" }).click();
  await page.getByRole("tab", { name: /Funnel/ }).waitFor();
  await page.waitForFunction(() => !document.querySelector(".outreach .waiting"), null, { timeout: 60000 });
  await page.getByRole("tab", { name: /Funnel/ }).click();
  await page.locator(".funnel").waitFor();
  await settle();
  view = await asHolder("/api/holder/outreach");
  const stage = (v, key) => v.notices.funnel.stages.find((s) => s.key === key).notices;
  check(stage(view, "sent") === view.notices.ready && stage(view, "opened") === 0, "marking sent did not record the delivery of every ready notice");
  await shot("the-funnel-once-the-holder-has-marked-them-sent");

  // 7. Marisol, at home in Guadalajara, opens her notice with the code on the letter and answers it in Spanish.
  await page.goto(`${OUTREACH}/n`);
  await page.getByRole("heading", { name: "A notice about your money" }).waitFor();
  await page.getByLabel("The code from your letter").fill(found.code.toLowerCase().replace("-", " "));
  await shot("the-owner-types-the-code-from-her-letter");
  await page.getByRole("button", { name: "Open my notice" }).click();
  await page.locator(".owner-notice").waitFor({ timeout: 30000 });
  await settle();
  const owner = words(await page.locator(".owner-notice").innerText());
  check(/EL ESTADO DE CALIFORNIA/.test(owner) && /Responder a este aviso/i.test(owner) && owner.includes("1,284.60"), `her notice is not shown to her in Spanish: "${owner.slice(0, 300)}"`);
  check(!/Tolmedo|Calle Fresno/.test(owner), "the notice on screen carries the owner's name or street");
  check(page.url().endsWith(`/n/${found.code}`), `the address bar does not hold her personal link: ${page.url()}`);
  await shot("the-owner-reads-her-notice-in-spanish");
  await page.getByRole("button", { name: "Fill this in for Marisol" }).click();
  await settle(300);
  await shot("she-answers-it");
  await page.locator(".answer-form button[type=submit]").click();
  await page.getByRole("heading", { name: "Proof file" }).waitFor({ timeout: 30000 });
  const claimId = page.url().split("#claim/")[1];
  const opened = await api.claim(claimId);
  check(opened.record.amount === 1284.6 && opened.record.holder_name === "Empacadora Valle Sereno" && opened.sample === true && MASKED.test(opened.record.owner),
    `the claim was not opened on her exact record: ${JSON.stringify(opened.record)}`);
  await settle(800);
  await shot("her-claim-opens-on-that-exact-record");
  view = await asHolder("/api/holder/outreach");
  check(stage(view, "opened") === 1 && stage(view, "responded") === 1, "her answer was not recorded against the notice");

  // 8. The existing journey takes over: documents read and checked, her bank account, the holder's approval, the payment.
  await addDocuments(["Passport photo page", "Taxpayer number letter", "Bank statement"], 3);
  await proofReady("Marisol, from her notice");
  await page.locator("#proof-file").evaluate((el) => el.scrollTo(0, 0));
  await settle();
  await shot("her-proof-is-ready");
  await page.getByRole("tab", { name: "Bank account" }).click();
  await page.getByRole("button", { name: "Fill this in for Marisol" }).click();
  await settle(300);
  await page.getByRole("button", { name: "Save this bank account" }).click();
  await page.locator("#payee-on-file").waitFor({ timeout: 30000 });
  await openHolderList("Funnel");
  view = await asHolder("/api/holder/outreach");
  check(stage(view, "proven") === 1, "the funnel does not count her claim as proven");
  const hold = view.notices.cards.find((c) => c.kind === "deadline_outreach");
  check(hold.groups.pay.balances === 1, `the deadline card does not put her proven claim under "pay": ${JSON.stringify(hold.groups)}`);
  await shot("the-funnel-opened-answered-proven");

  await api.setLimits(RULES);
  await openHolderView();
  await pick("$1,284.60").click();
  await settle();
  await shot("the-holder-approves-the-claim-that-came-from-its-notice");
  await page.getByRole("button", { name: "Approve these terms" }).click();
  await page.locator(".queue-row .state", { hasText: "Approved" }).waitFor({ timeout: 30000 });
  await page.goto(`${OUTREACH}/#payout/${claimId}`);
  await page.getByRole("heading", { name: "The payout plan" }).waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "Show the payout plan" }).click();
  await page.locator(".plan-receive").waitFor({ timeout: 60000 });
  await page.getByRole("button", { name: /I agree\. Start the payment/ }).click();
  await waitForPaid("Marisol, from her notice");
  await settle(1500);
  const paid = await api.payout(claimId);
  numbers.payment = { state: paid.state, received: paid.received ? `${paid.received.amount} ${paid.received.currency}` : null, environment: paid.environment };
  await shot("paid-at-home-in-pesos", { checks: false });

  // 9. The funnel after the demonstration response, and the choice at the handover date.
  await openHolderList("Funnel");
  view = await asHolder("/api/holder/outreach");
  numbers.funnel = Object.fromEntries(view.notices.funnel.stages.map((s) => [s.key, `${s.notices} (${s.amount} USD)`]));
  numbers.days_left = view.notices.funnel.days_left;
  check(stage(view, "paid") === 1, `the funnel does not count her claim as paid: ${JSON.stringify(numbers.funnel)}`);
  const funnelText = words(await page.locator(".funnel").innerText());
  check(/Prepared/i.test(funnelText) && /Paid/i.test(funnelText), `the funnel is not on screen: "${funnelText}"`);
  notes.push(`Outreach, the funnel after her answer: ${JSON.stringify(numbers.funnel)}, ${numbers.days_left} days to the handover.`);
  await shot("the-funnel-after-the-demonstration-response");
  const near = nearHandoverDate();
  await api.setLimits({ ...RULES, handover_date: near });
  await openHolderList("Funnel");
  view = await asHolder("/api/holder/outreach");
  const last = view.notices.cards.find((c) => c.kind === "deadline_outreach");
  check(last.final === true && /At the date/.test(last.did) && last.groups.release.balances > 0 && last.groups.paid.balances === 1,
    `near the handover the agent does not decide what to pay, hold and release: ${JSON.stringify([last.did, last.groups])}`);
  numbers.at_the_handover_date = { date: near, did: last.did, money: last.money };
  notes.push(`Outreach, at the handover date (${near}): ${last.happened} ${last.did} ${last.money}`);
  await shot("at-the-handover-date-pay-hold-or-release");

  await context.close();
  return numbers;
}

// ---------------------------------------------------------------------------------------------------------------
// Funding a claim on Metal testnet. The holder's approval signs a mandate with the approval's own terms; Metal,
// not our code, refuses a pull outside it; the pull funds the Airwallex payout and its hash is the deposit's
// reference. Skipped, with the reason, when Metal testnet is not set up or cannot be reached.

async function metalJourney(browser) {
  const status = await api.get("/api/metal");
  if (!status.available) {
    const why = `the Metal journey was skipped: ${status.problem || "Metal is not set up on this server"}`;
    notes.push(why);
    log(why);
    return { skipped: status.problem || "not set up" };
  }
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  page = await context.newPage();
  watch(page);
  const holder = { "X-Payer-Key": PAYER_KEY };
  const metal = async (id) => (await fetch(`${BASE}/api/payer/claims/${id}/metal`, { headers: holder })).json();
  // Amihan's third record, 412.07 US dollars at a credit union, with her documents read and her bank account given.
  const claimId = await api.openClaim("amihan", 412.07, ["Passport photo page", "Taxpayer number letter", "Bank statement"]);
  await openHolderView();
  await pick("$412.07").click();
  const approve = page.getByRole("button", { name: "Approve and fund on Metal" });
  await approve.waitFor({ timeout: 60000 });
  await settle();
  await shot("metal-the-holder-can-approve-and-fund-on-metal");
  await approve.click();
  let seen;
  for (let i = 0; i < 90; i++) {
    seen = await metal(claimId);
    if (seen.mandate?.bind_transaction || seen.problem) break;
    await page.waitForTimeout(2000);
  }
  if (!seen?.mandate?.bind_transaction) {
    const why = `the Metal journey stopped: no mandate was bound (${JSON.stringify(seen?.problem ?? seen?.events?.slice(-1) ?? "").slice(0, 200)})`;
    fail(why);
    await context.close();
    return { stopped: why };
  }
  check(seen.mandate.all_same === true, "the mandate's terms are not the approval's");
  await page.locator(".metal-status-bound").waitFor({ timeout: 60000 }).catch(() => fail("the Metal panel does not show the bound mandate"));
  await settle();
  await shot("metal-the-approval-signed-a-mandate-with-the-same-terms");
  const refusals = [];
  for (const [label, n] of [["Pull one *USDZ cent more than the cap", 1], ["Pull to an address other than Khutlisa's settlement address", 2]]) {
    await page.getByRole("button", { name: label }).click();
    await page.locator(`.metal-refusals li:nth-child(${n})`).waitFor({ timeout: 180000 });
    const r = (await metal(claimId)).refusals[n - 1];
    refusals.push({ asked: label, reason: r.reason, transaction: r.transaction });
  }
  check(refusals.length === 2 && refusals.every((r) => r.transaction), "Metal's refusals have no transaction on chain");
  await settle();
  await shot("metal-refuses-a-pull-over-the-cap-and-to-another-payee");
  const plan = await api.plan(claimId);
  await api.confirm(claimId, plan.plan.id);
  let payout;
  for (let i = 0; i < 180; i++) {
    payout = await api.payout(claimId);
    if (payout.state === "PAID" || (["HELD", "FAILED"].includes(payout.state) && !payout.running)) break;
    if (payout.problem && !payout.running) await fetch(`${BASE}/api/claims/${claimId}/payout/resume`, { method: "POST" });
    await page.waitForTimeout(2000);
  }
  seen = await metal(claimId);
  check(payout.state === "PAID", `the claim funded on Metal did not end paid: ${payout.state} ${payout.problem ?? ""}`);
  check(seen.pull?.transaction && payout.deposit?.reference === seen.pull.transaction, "the Airwallex deposit's reference is not the Metal pull's transaction");
  await page.goto(`${BASE}/#payout/${claimId}`);
  await page.locator(".metal-pull").waitFor({ timeout: 30000 }).catch(() => fail("the payment screen does not show the Metal pull"));
  await settle(800);
  await shot("metal-the-pull-funded-the-payout-paid-at-home");
  const result = { claim: claimId, scale: status.scale?.words, mandate: seen.mandate?.mandate_id, bind: seen.mandate?.bind_transaction, refusals,
    pull: seen.pull?.transaction, pulled_usdz: seen.pull?.amount_usdz, deposit_reference: payout.deposit?.reference, state: payout.state,
    received: payout.received && `${payout.received.amount} ${payout.received.currency}`, ledger_adds_up_to_zero: payout.reconciliation?.balanced };
  notes.push(`Metal: ${JSON.stringify(result)}`);
  await context.close();
  return result;
}

/** A server whose register database is not there must still start, search the demonstration records and say so. */
async function withoutTheDatabase(browser) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  page = await context.newPage();
  const info = await (await fetch(`${BARE}/api/register`)).json();
  check(info.loaded === false && info.owner_records === 0 && info.demonstration_records > 0, `the server without the database does not say so: ${JSON.stringify(info)}`);
  await page.goto(`${BARE}/#history`);
  await page.getByRole("heading", { name: "Tell us your history" }).waitFor();
  await page.getByRole("tab", { name: "The form" }).click();
  await page.getByLabel("Given names").fill("Amihan");
  await page.getByLabel("Family name").fill("Dalisay");
  await page.getByRole("button", { name: "Search the register" }).click();
  await page.locator(".summary").waitFor({ timeout: 30000 });
  const line = await page.locator(".searched-line").innerText();
  check(/California's file is not loaded on this server/.test(line), `without the database the results do not say so: "${line}"`);
  notes.push(`Without the register database: ${line}`);
  await settle();
  // Kept apart from the numbered story: the walk ends on a paid claim, not on a server without its data.
  await page.screenshot({ path: join(SHOTS, "extra-without-the-database-it-says-so.png") });
  await audit("extra-without-the-database-it-says-so.png");
  await context.close();
}

/** Against a public copy: no server of our own. The copy must be in public demonstration mode and on California's
 *  file; the holder's key is the one it gives its pages. */
async function remoteSetup() {
  const mode = await (await fetch(`${BASE}/api/mode`)).json();
  if (!mode.public_demo || !mode.holder_key) throw new Error(`${BASE} is not a public demonstration copy that gives its pages the holder's key`);
  PAYER_KEY = mode.holder_key;
  api = apiOf(BASE, PAYER_KEY);
  const register = await waitFor(`${BASE}/api/register`, 60);
  check(register.loaded === true && register.owner_records > 90e6 && register.demonstration_records > 0, "the public copy is not on California's file with the demonstration records beside it");
  notes.push(`Public copy at ${BASE}: public demonstration mode, model ${JSON.stringify(mode.model)}`);
}

const skip = (name, why) => {
  skipped.push({ step: name, why });
  log(`skipped: ${name}: ${why}`);
  return { skipped: why };
};

async function main() {
  if (REMOTE) return remoteMain();
  check(existsSync(join(ROOT, "web", "dist", "index.html")), "web/dist is missing: run npm run build in web/ first");
  if (!existsSync(DATABASE)) throw new Error(`${DATABASE} is missing. Load California's file first (see the README), or name it with KHUTLISA_DB.`);
  for (const port of [PORT, BARE_PORT])
    if (!(await portFree(port))) throw new Error(`Port ${port} is already in use. Stop that server first.`);
  const totals = existsSync(join(ROOT, "data", "totals.json")) ? {} : { KHUTLISA_TOTALS: join(DATABASE, "..", "totals.json") };
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const result = {};
  const parts = {};
  try {
    for (const old of STALE) rmSync(old, { recursive: true, force: true });
    rmSync(SHOTS, { recursive: true, force: true });
    mkdirSync(SHOTS, { recursive: true });
    rmSync(CLAIMS, { recursive: true, force: true });
    const drawn = spawnSync("uv", ["run", "python", "scripts/make_sample_documents.py"], { cwd: ROOT });
    if (drawn.status !== 0) throw new Error(`make_sample_documents.py failed: ${drawn.stderr}`);
    rmSync(join(SAMPLES, "walk-claims-bare"), { recursive: true, force: true });
    startServer(PORT, { KHUTLISA_DB: DATABASE, ...totals, KHUTLISA_CLAIMS: CLAIMS, KHUTLISA_PAYER_KEY: PAYER_KEY, KHUTLISA_PUBLIC_URL: BASE,
      KHUTLISA_READ_DOCUMENTS: "1", KHUTLISA_DEMONSTRATION: "1" });
    const register = await waitFor(`${BASE}/api/register`, 120);
    check(register.loaded === true && register.owner_records > 90e6 && register.demonstration_records > 0, "the server is not on California's file with the demonstration records beside it");

    const run = async (name, walk) => {
      log(`--- ${name}`);
      try {
        parts[name] = await walk();
      } catch (e) {
        fail(`${name}: the walk stopped: ${e.message.split("\n")[0]}`);
        await page?.screenshot({ path: join(SHOTS, `999-where-${name.replace(/\W+/g, "-")}-stopped.png`) }).catch(() => undefined);
        parts[name] = { stopped: e.message.split("\n")[0] };
      }
    };
    await run("main journey, book, batch and Queensland", async () => Object.assign(result, await journey(browser)));
    await run("Metal funding", () => metalJourney(browser));
    await run("holder's own list and an answered notice", () => outreachJourney(browser));
    const shared = { base: BASE, key: PAYER_KEY, claims: CLAIMS };
    await run("estate settlement", async () => {
      const done = await walkHeirs({ server: shared, claims: CLAIMS, shots: SHOTS, start: shotNumber, audit: auditOf, watch });
      for (const text of done.problems) fail(`estate: ${text}`);
      shotNumber = done.last;
      return done.result;
    });
    await run("risk view", async () => {
      const done = await walkRings({ server: shared, claims: join(SAMPLES, "walk-rings-planted"), shots: SHOTS, start: shotNumber, audit: auditOf, watch });
      for (const text of done.problems) fail(`risk: ${text}`);
      shotNumber = done.last;
      return { counts: done.counts, screenshots: done.screenshots };
    });

    startServer(BARE_PORT, { KHUTLISA_DB: join(SAMPLES, "no-such-register.duckdb"), KHUTLISA_TOTALS: join(DATABASE, "..", "totals.json"),
      KHUTLISA_CLAIMS: join(SAMPLES, "walk-claims-bare"), KHUTLISA_PAYER_KEY: PAYER_KEY });
    await waitFor(`${BARE}/api/register`, 60);
    await withoutTheDatabase(browser);
  } catch (e) {
    fail(`the walk stopped: ${e.message.split("\n")[0]}`);
    await page?.screenshot({ path: join(SHOTS, "999-where-it-stopped.png") }).catch(() => undefined);
  } finally {
    writeFileSync(join(SHOTS, "summary.json"), JSON.stringify({ ...result, parts, notes, problems, screenshots: shotNumber }, null, 2));
    await browser.close();
    if (!process.env.WALK_KEEP) stopServers();
  }
  console.log("\nNotes:\n" + notes.map((n) => `  ${n}`).join("\n"));
  console.log("\nParts:\n" + Object.entries(parts).map(([k, v]) => `  ${k}: ${v?.skipped ? `skipped (${v.skipped})` : v?.stopped ? `stopped (${v.stopped})` : "ran"}`).join("\n"));
  console.log(problems.length ? `\n${problems.length} problem(s):\n` + problems.map((p) => `  ${p}`).join("\n") : "\nThe walk ran clean.");
  process.exit(problems.length ? 1 : 0);
}

async function remoteMain() {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const result = {};
  const parts = {};
  try {
    rmSync(SHOTS, { recursive: true, force: true });
    mkdirSync(SHOTS, { recursive: true });
    await remoteSetup();
    const run = async (name, walk) => {
      log(`--- ${name}`);
      try {
        parts[name] = await walk();
      } catch (e) {
        fail(`${name}: the walk stopped: ${e.message.split("\n")[0]}`);
        await page?.screenshot({ path: join(SHOTS, `999-where-${name.replace(/\W+/g, "-")}-stopped.png`) }).catch(() => undefined);
        parts[name] = { stopped: e.message.split("\n")[0] };
      }
    };
    await run("main journey, book, batch and Queensland", async () => Object.assign(result, await journey(browser)));
    parts["Metal funding"] = (await api.get("/api/metal")).available ? await metalJourney(browser)
      : skip("Metal funding", `funding on Metal is switched off in the public copy: ${(await api.get("/api/metal")).problem}`);
    await run("holder's own list and an answered notice", () => outreachJourney(browser));
    await run("estate settlement", async () => {
      const done = await walkHeirs({ server: { base: BASE, key: PAYER_KEY, remote: true }, shots: SHOTS, start: shotNumber, audit: auditOf, watch });
      for (const text of done.problems) fail(`estate: ${text}`);
      shotNumber = done.last;
      return done.result;
    });
    skip("the estate's run log (docs/SANDBOX_RUN_LOG_ESTATE.md)", "it is written from the server's own claims folder, which is not reachable from outside");
    parts["risk view"] = skip("risk view", "its rings are planted by writing claims into the server's claims folder; a visitor cannot open claims on real records, so they cannot be made through the public routes");
    skip("a server without the register database", "it is a second server started by the walk on this machine");
  } catch (e) {
    fail(`the walk stopped: ${e.message.split("\n")[0]}`);
    await page?.screenshot({ path: join(SHOTS, "999-where-it-stopped.png") }).catch(() => undefined);
  } finally {
    writeFileSync(join(SHOTS, "summary.json"), JSON.stringify({ base: BASE, ...result, parts, skipped, notes, problems, screenshots: shotNumber }, null, 2));
    await browser.close();
  }
  console.log("\nNotes:\n" + notes.map((n) => `  ${n}`).join("\n"));
  console.log("\nSkipped against the public copy:\n" + skipped.map((s) => `  ${s.step}: ${s.why}`).join("\n"));
  console.log("\nParts:\n" + Object.entries(parts).map(([k, v]) => `  ${k}: ${v?.skipped ? `skipped (${v.skipped})` : v?.stopped ? `stopped (${v.stopped})` : "ran"}`).join("\n"));
  console.log(problems.length ? `\n${problems.length} problem(s):\n` + problems.map((p) => `  ${p}`).join("\n") : "\nThe walk ran clean.");
  process.exit(problems.length ? 1 : 0);
}

process.on("SIGINT", () => {
  stopServers();
  process.exit(130);
});
main().catch((e) => {
  console.error(e);
  stopServers();
  process.exit(1);
});
