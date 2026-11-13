// Records the demonstration as video clips: the real app, the real register database and the real Airwallex
// sandbox, driven in a real browser at 1920x1080 at the pace of a person (a visible cursor that moves smoothly,
// about a second on each result, typing at a natural speed).
//
//     node scripts/record_demo.mjs
//
// The clips go to a folder outside the repository (RECORD_OUT, by default ../khutlisa-video/clips), each named
// with a number and a short name, with scenes.json beside them: for each clip its file, its length in seconds,
// what happens at which second, the waits an editor can cut, and the figures a narrator might read.
//
// How it records. Playwright records one video per browser context, so each stretch that has to stay on one page
// (the spoken history, the answer and the documents, for example) is one context, and its video is cut into
// scenes afterwards with ffmpeg at the seconds this script noted. Playwright captures at 25 frames a second;
// the clips are written at 30. Sound is not captured: the seconds at which each sound file starts, and how long
// it runs, are in scenes.json so the sound can be laid under the clip.
//
// What is set up off screen, through the same API routes the screens use: Marisol's second claim (95.00 US
// dollars) with the same refusal staged, Amihan's two claims up to the bank account, and the holder's approval of
// a corrected bank account. scenes.json says so where it applies.
//
// No real individual is visible: the cards of real owners are blurred for the whole recording (their names are
// masked on the page in any case).
//
// It starts its own server (port 8031, a fresh claims folder) and stops it, and nothing else, when it ends. It
// needs the built front end, data/registers.duckdb, the claude program, the Airwallex sandbox keys and ffmpeg.
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { ROOT, apiOf, chromium, nearHandoverDate, portFree, sleep, startServer, stopServers, waitFor } from "./demo_lib.mjs";

const OUT = resolve(process.env.RECORD_OUT || join(ROOT, "..", "khutlisa-video", "clips"));
const RAW = join(OUT, "raw");
const FRAMES = join(OUT, "frames");
const CLAIMS = join(ROOT, "data", "samples", "record-claims");
const PORT = 8031;
const BASE = `http://localhost:${PORT}`;
const KEY = `record-${randomBytes(12).toString("hex")}`;
const api = apiOf(BASE, KEY);
const RULES = { tolerance_percent: "0.5", small_claim_usd: "250", route_rule: "most_to_claimant", deadline_days: 14 };

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const round = (n) => Math.round(n * 10) / 10;

// ---- one recorded context, with a cursor drawn in the page ------------------------------------------------------

/** Runs in the page before anything else: the cursor, a ring on each click, real owners blurred, and a note of
 *  every sound that starts playing. */
function inPage(key) {
  try {
    window.sessionStorage.setItem("khutlisa-payer-key", key);
  } catch {
    // no storage on this page
  }
  window.__plays = [];
  // Sounds are played from elements that are not in the page, so the call itself is noted, not a page event.
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    window.__plays.push({ src: String(this.currentSrc || this.src).split("/").pop(), at: Date.now() });
    return play.apply(this, args);
  };
  const ready = () => {
    document.body.classList.add("blur-real");
    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    cursor.innerHTML = '<svg width="34" height="34" viewBox="0 0 24 24"><path d="M4 2 L4 20 L9 15.5 L12.2 22.5 L15 21.2 L11.8 14.4 L18.5 14.4 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    cursor.style.cssText = "position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate(-200px,-200px);will-change:transform;filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))";
    document.documentElement.appendChild(cursor);
    const place = (x, y) => (cursor.style.transform = `translate(${x - 5}px, ${y - 3}px)`);
    const last = JSON.parse(window.sessionStorage.getItem("demo-cursor") || "null");
    if (last) place(last.x, last.y);
    window.addEventListener("mousemove", (e) => {
      place(e.clientX, e.clientY);
      window.sessionStorage.setItem("demo-cursor", JSON.stringify({ x: e.clientX, y: e.clientY }));
    }, true);
    window.addEventListener("mousedown", (e) => {
      const ring = document.createElement("div");
      ring.style.cssText = `position:fixed;left:${e.clientX - 22}px;top:${e.clientY - 22}px;width:44px;height:44px;border-radius:50%;border:3px solid #f2b84b;z-index:2147483646;pointer-events:none;opacity:.9;transition:transform .45s ease-out,opacity .45s ease-out`;
      document.documentElement.appendChild(ring);
      requestAnimationFrame(() => {
        ring.style.transform = "scale(1.9)";
        ring.style.opacity = "0";
      });
      setTimeout(() => ring.remove(), 500);
    }, true);
  };
  if (document.body) ready();
  else document.addEventListener("DOMContentLoaded", ready);
}

class Session {
  constructor(browser, name) {
    this.browser = browser;
    this.name = name;
    this.scenes = [];
    this.at = { x: 960, y: 620 };
  }

  async open() {
    this.dir = join(RAW, this.name);
    mkdirSync(this.dir, { recursive: true });
    this.context = await this.browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: this.dir, size: { width: 1920, height: 1080 } }, acceptDownloads: true });
    await this.context.addInitScript(inPage, KEY);
    this.page = await this.context.newPage();
    this.t0 = Date.now();
    this.page.on("pageerror", (e) => log("page error:", e.message.slice(0, 200)));
    return this.page;
  }

  now() {
    return (Date.now() - this.t0) / 1000;
  }

  /** Starts a scene. Everything noted until the next `scene` or `close` belongs to it. */
  scene(number, name, title) {
    this.endScene();
    this.current = { number, name, title, from: this.now(), events: [], waits: [], sounds: [], numbers: {}, notes: [] };
    this.scenes.push(this.current);
    log(`scene ${number}: ${title}`);
  }

  endScene() {
    if (this.current && this.current.to === undefined) this.current.to = this.now();
  }

  mark(what) {
    this.current.events.push({ at: this.now(), what });
  }

  note(text) {
    this.current.notes.push(text);
  }

  numbers(found) {
    Object.assign(this.current.numbers, found);
  }

  /** Waits for something slow and writes the wait down, so an editor can cut it. */
  async wait(what, work) {
    const from = this.now();
    const result = await work();
    const to = this.now();
    if (to - from >= 1.5) this.current.waits.push({ from, to, what });
    return result;
  }

  async pause(ms = 1000) {
    await this.page.waitForTimeout(ms);
  }

  /** Moves the cursor in a smooth, eased line. */
  async moveTo(x, y) {
    const from = this.at;
    const far = Math.hypot(x - from.x, y - from.y);
    const steps = Math.max(8, Math.min(48, Math.round(far / 22)));
    for (let i = 1; i <= steps; i++) {
      const k = i / steps;
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      await this.page.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e);
      await this.page.waitForTimeout(16);
    }
    this.at = { x, y };
  }

  async point(locator, { dx = 0.5, dy = 0.5 } = {}) {
    await locator.scrollIntoViewIfNeeded().catch(() => undefined);
    const box = await locator.boundingBox();
    if (!box) throw new Error("nothing to point at");
    await this.moveTo(box.x + box.width * dx, box.y + Math.min(box.height * dy, 400));
  }

  async click(locator, what, { after = 500 } = {}) {
    await this.point(locator);
    await this.pause(220);
    if (what) this.mark(what);
    await this.page.mouse.down();
    await this.page.waitForTimeout(70);
    await this.page.mouse.up();
    await this.pause(after);
  }

  async type(locator, text, what) {
    await this.click(locator, null, { after: 200 });
    await locator.fill("");
    if (what) this.mark(what);
    for (const ch of text) {
      await this.page.keyboard.type(ch);
      await this.page.waitForTimeout(60 + Math.random() * 80);
    }
  }

  async sounds() {
    const plays = await this.page.evaluate(() => window.__plays ?? []).catch(() => []);
    return plays.map((p) => ({ file: p.src, at: (p.at - this.t0) / 1000 }));
  }

  async close() {
    this.endScene();
    const video = this.page.video();
    await this.context.close();
    this.video = await video.path();
  }
}

// ---- the scenes ----------------------------------------------------------------------------------------------

const text = async (locator) => ((await locator.innerText().catch(() => "")) ?? "").replace(/\s+/g, " ").trim();
const cardLines = async (page, scope, kind) => (await page.locator(`${scope} .decision[data-kind="${kind}"]`).first().locator(".decision-line dd").allInnerTexts().catch(() => [])).map((l) => l.replace(/\s+/g, " "));

function soundLength(file) {
  const out = spawnSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", join(ROOT, "web", "public", "demo", file)]);
  return round(Number(String(out.stdout).trim()) || 0);
}

async function record(browser) {
  const sessions = [];
  const begin = async (name) => {
    const s = new Session(browser, name);
    await s.open();
    sessions.push(s);
    return s;
  };
  const totals = await api.get("/api/totals");
  const holders = await api.get("/api/holders");

  // ---- 1 and 2: the opening, and who is owed ----
  let s = await begin("a-opening");
  let page = s.page;
  s.scene(1, "opening", "The opening: the facts, the totals, the live search line");
  await page.goto(BASE);
  await page.locator(".lead-fact").waitFor();
  s.mark("Stanford University is owed $55,690.09. Harvard reported it.");
  await page.locator(".opening-whole").waitFor({ state: "visible" });
  await page.waitForFunction(() => getComputedStyle(document.querySelector(".opening-whole")).opacity > 0.5).catch(() => undefined);
  s.mark("The whole file: $12.74 billion in 89 million properties");
  await page.waitForFunction(() => Number((document.querySelector(".counter")?.textContent ?? "").replace(/[^0-9]/g, "")) > 1000).catch(() => undefined);
  s.mark("The counter starts running up to the part owed to people abroad");
  await page.waitForFunction((n) => Number((document.querySelector(".counter")?.textContent ?? "").replace(/[^0-9]/g, "")) === n, Math.round(totals.abroad_amount), { timeout: 20000 });
  s.mark(`The counter stops at $${Math.round(totals.abroad_amount).toLocaleString("en-US")} in ${totals.abroad_properties.toLocaleString("en-US")} properties`);
  await page.waitForFunction(() => /searched in/.test(document.querySelector(".live-line")?.textContent ?? "") && getComputedStyle(document.querySelector(".live-line")).opacity > 0.5, null, { timeout: 30000 }).catch(() => undefined);
  s.mark(`The live search line: ${await text(page.locator(".live-line"))}`);
  await page.waitForFunction(() => getComputedStyle(document.querySelector(".opening-cheque")).opacity > 0.5).catch(() => undefined);
  s.mark("The State's only way to pay is a cheque in the post.");
  await page.waitForFunction(() => getComputedStyle(document.querySelector(".opening-does")).opacity > 0.5).catch(() => undefined);
  s.mark("What Khutlisa does, in one line");
  await page.locator(".opening-actions-in").waitFor({ timeout: 20000 });
  s.mark("The buttons");
  await s.moveTo(1500, 760);
  await s.pause(2500);
  s.numbers({ stanford_is_owed: "$55,690.09, reported by President and Fellows of Harvard College", whole_file: `$${(totals.all_amount / 1e9).toFixed(2)} billion in ${totals.all_properties.toLocaleString("en-US")} properties`,
    owed_abroad: `$${Math.round(totals.abroad_amount).toLocaleString("en-US")} in ${totals.abroad_properties.toLocaleString("en-US")} properties`, live_search: await text(page.locator(".live-line")),
    also_on_screen: await text(page.locator(".owed-three")) });

  s.scene(2, "who-is-owed", "Who is owed: the well-known pairs, then a famous name typed live");
  await s.click(page.getByRole("button", { name: "See who is owed" }), "Click: See who is owed");
  await page.getByRole("heading", { name: "Real organisations that are owed money" }).waitFor();
  await page.locator(".owed-list li").first().waitFor();
  s.mark("The well-known pairs: one well-known name reported by another");
  await s.pause(1200);
  const pairs = page.locator(".owed-list li");
  for (let i = 0; i < Math.min(4, await pairs.count()); i++) {
    await s.point(pairs.nth(i), { dx: 0.3 });
    await s.pause(900);
  }
  s.numbers({ pairs: (await pairs.allInnerTexts()).slice(0, 6).map((t) => t.replace(/\s+/g, " ")) });
  await s.type(page.getByLabel(/Type the name/), "netflix", "Typing a famous name: netflix");
  await page.locator(".owed-results .owed-list li").first().waitFor({ timeout: 30000 });
  await s.pause(900);
  s.mark(`Results from the whole file: ${await text(page.locator(".owed-line"))}`);
  await s.point(page.locator(".owed-results .owed-list li").first(), { dx: 0.3 });
  await s.pause(2600);
  s.numbers({ typed: "netflix", result_line: await text(page.locator(".owed-line")), first_results: (await page.locator(".owed-results .owed-list li").allInnerTexts()).slice(0, 3).map((t) => t.replace(/\s+/g, " ")) });
  await s.close();

  // ---- 3: for holders, the law in a sentence, and the limits set once ----
  s = await begin("b-holders");
  page = s.page;
  s.scene(3, "for-holders", "For holders: the top holders, the law in a sentence, setting the limits once");
  await page.goto(`${BASE}/#holders`);
  await page.locator(".holder-list li").first().waitFor();
  s.mark(`The top holders: ${holders.figures.by_amount.slice(0, 3).map((h) => h.name).join(", ")}`);
  await s.pause(1000);
  const rowsH = page.locator(".holder-list li");
  for (let i = 0; i < 4; i++) {
    await s.point(rowsH.nth(i), { dx: 0.25 });
    await s.pause(700);
  }
  await s.point(page.locator(".law-pay"), { dx: 0.4 });
  s.mark("The law in a sentence: sections 1532(b) and 1560(b)");
  await s.pause(3200);
  await s.point(page.locator(".law-days"), { dx: 0.2 });
  s.mark(`${holders.in_short.days_to_handover} days to the next handover, ${holders.in_short.handover_words}`);
  await s.pause(2400);
  await s.click(page.getByRole("link", { name: "Open the holder's view" }), "Click: Open the holder's view");
  await page.getByRole("heading", { name: "Your limits, set once" }).waitFor();
  s.mark("The holder's view: the days left until the handover");
  await s.point(page.locator(".handover-days"));
  await s.pause(2200);
  await s.click(page.getByRole("button", { name: "Set them" }), "Click: Set them");
  await s.type(page.getByLabel(/Amount tolerance/), RULES.tolerance_percent, "Typing the amount tolerance: 0.5 percent");
  await s.pause(350);
  await s.type(page.getByLabel(/Small-claim line/), RULES.small_claim_usd, "Typing the small-claim line: 250 US dollars");
  await s.pause(350);
  await s.type(page.getByLabel(/Days to send the money/), String(RULES.deadline_days), "Typing the days to send the money: 14");
  await s.pause(350);
  await s.point(page.getByLabel("Your handover date to the State"));
  s.mark("The handover date, set by the holder: it starts at the next 1 June");
  await s.pause(1300);
  await s.click(page.getByRole("button", { name: "Save the limits" }), "Click: Save the limits");
  await page.locator(".limits li").first().waitFor({ timeout: 15000 });
  s.mark("The limits as five figures");
  await s.point(page.locator(".limits"), { dx: 0.5 });
  await s.pause(3000);
  const handover = (await api.queue()).handover;
  s.numbers({ holders: holders.figures.holders_with_an_owner_abroad, top_holders: holders.figures.by_amount.slice(0, 5).map((h) => `${h.name}: $${Math.round(h.amount).toLocaleString("en-US")}`),
    law: `${holders.in_short.pay} ${holders.in_short.schedule} ${holders.in_short.cheque}`, days_to_handover: handover.days_left, handover_date: handover.date_words,
    limits: "0.5 percent tolerance; 250 US dollars small-claim line; best route; 14 days to send; stop waiting for documents 30 days before the handover" });
  await s.close();

  // ---- 4, 5 and 6: the spoken history, the answer, the documents ----
  s = await begin("c-owner");
  page = s.page;
  s.scene(4, "spoken-history", "The spoken history in Spanish: the transcript appears, the first matches are possible");
  await page.goto(`${BASE}/#history`);
  await page.getByRole("heading", { name: "Tell us your history" }).waitFor();
  await s.pause(1200);
  await s.click(page.getByRole("button", { name: /Hear Marisol, in Spanish/ }), "Click: Hear Marisol, in Spanish (the sound starts)");
  await page.locator(".heard-speaking").waitFor();
  s.mark("The words the recogniser heard appear with the voice");
  await s.moveTo(520, 640);
  await s.wait("the intake reads her words and the search runs", async () => {
    await page.locator(".summary").waitFor({ timeout: 180000 });
    await page.locator(".heard:not(.heard-stale) .timeline").waitFor({ timeout: 60000 });
  });
  s.mark(`The matches: ${await text(page.locator(".searched-line"))}`);
  await s.pause(1200);
  const wages = page.locator(".match", { hasText: "$2,316.40" });
  await s.point(wages.locator(".score-label"));
  s.mark("Her wages record, 2,316.40 US dollars: a possible match");
  await s.pause(2600);
  if (await page.locator(".follow").count()) {
    await s.point(page.locator(".follow"), { dx: 0.3 });
    // What is said about this moment must be what the screen asks: her old postcode, and nothing about a street.
    s.mark(/postcode/i.test(await text(page.locator(".follow .panel-label"))) ? "One follow-up question, in Spanish: it asks for her old postcode" : "One follow-up question, in Spanish");
    await s.pause(2200);
  }
  s.numbers({ searched: await text(page.locator(".searched-line")), wages_record: "$2,316.40, possible match", follow_up_question: await text(page.locator(".follow-english")) });

  s.scene(5, "the-answer-lifts-it", "The follow-up answer lifts the match to strong, with the amount in pesos today");
  await s.click(page.getByRole("button", { name: "Hear Marisol's answer" }), "Click: Hear Marisol's answer (the sound starts)");
  await s.moveTo(1380, 420);
  await s.wait("her answer is read and the search runs again", () => page.locator(".lift").first().waitFor({ timeout: 180000 }));
  s.mark("The wages record is now a strong match");
  await page.locator(".match-local").first().waitFor({ timeout: 20000 }).catch(() => undefined);
  await page.locator(".results").evaluate((el) => el.scrollTo({ top: 0, behavior: "smooth" }));
  await s.pause(800);
  await s.point(wages.locator(".lift"), { dx: 0.3 });
  s.mark("What changed: possible before, strong now, and why");
  await s.pause(3000);
  await s.point(wages.locator(".match-local"), { dx: 0.3 });
  s.mark("The amount in Mexican pesos today");
  await s.pause(2600);
  s.numbers({ lift: await text(wages.locator(".lift")), in_pesos_today: await text(wages.locator(".match-local")) });

  s.scene(6, "documents", "Documents: the staff badge refused, the passport read twice and checked, proof ready");
  await s.click(wages.getByRole("button", { name: "Prove this is mine" }), "Click: Prove this is mine");
  await page.getByRole("heading", { name: "Open your claim" }).waitFor();
  await s.click(page.getByRole("button", { name: "Fill this in for Marisol" }), "Her details are filled in");
  await s.pause(600);
  await s.click(page.getByRole("button", { name: "Open my claim" }), "Click: Open my claim");
  await page.getByRole("heading", { name: "Proof file" }).waitFor({ timeout: 30000 });
  await s.pause(1000);
  const add = async (label, expected, what) => {
    await s.click(page.locator(".demo-docs li", { hasText: label }).getByRole("button", { name: "Add" }), what);
    await s.wait(`the document is read twice by the model (${label.toLowerCase()})`, () => page.waitForFunction(
      (n) => document.querySelectorAll(".doc").length === n && document.querySelectorAll(".doc-state-reading").length === 0, expected, { timeout: 300000, polling: 500 }));
    await s.pause(1800);
  };
  await add("Staff badge", 1, "She adds her old staff badge as identification");
  s.mark("The staff badge is refused: not issued by a government, and expired");
  await s.point(page.locator(".doc").first(), { dx: 0.3 });
  await s.pause(3200);
  if (await page.locator(".claim-deadline .decision").count()) {
    await s.point(page.locator(".claim-deadline .decision-did"), { dx: 0.3 });
    s.mark("The deadline card: time in hand, so the agent asks her for what is missing");
    await s.pause(2600);
  }
  const askedCard = await cardLines(page, ".claim-deadline", "deadline");
  await add("Passport photo page", 2, "She adds her passport");
  s.mark("The passport: read twice, the two readings agree, the machine-readable lines checked in code");
  await s.point(page.locator(".doc", { hasText: /passport/i }).first(), { dx: 0.3 });
  await s.pause(3400);
  await s.click(page.locator(".demo-docs li", { hasText: "Taxpayer number letter" }).getByRole("button", { name: "Add" }), "She adds the taxpayer number letter");
  await add("Bank statement", 4, "She adds a bank statement at her address");
  await s.wait("the proof is worked out", () => page.waitForFunction(() => document.querySelector(".verdict")?.textContent === "Ready", null, { timeout: 60000 }));
  await page.locator("#proof-file").evaluate((el) => el.scrollTo({ top: 0, behavior: "smooth" }));
  await s.point(page.locator(".verdict"));
  s.mark("The proof is ready: three of three proven");
  await s.pause(3000);
  await s.click(page.getByRole("tab", { name: "Bank account" }), "The bank account tab");
  await s.click(page.getByRole("button", { name: "Fill this in for Marisol" }), "Her own bank account, ending 7771");
  await s.pause(900);
  await s.click(page.getByRole("button", { name: "Save this bank account" }), "Click: Save this bank account");
  await s.wait("Airwallex validates the bank details", () => page.locator("#payee-on-file").waitFor({ timeout: 30000 }));
  s.mark("The holder decides next");
  await s.pause(2200);
  const claimA = page.url().split("#claim/")[1];
  s.numbers({ staff_badge: "refused as photo identification", passport: "read twice, readings agree, checks in code passed", proof: "ready, 3 of 3 proven", bank_account: "ending 7771",
    deadline_card_while_the_badge_was_the_only_document: askedCard });
  const played = await s.sounds();
  for (const scene of s.scenes)
    scene.sounds = played.filter((p) => p.at >= scene.from - 0.5 && p.at < (scene.to ?? Infinity)).map((p) => ({ ...p, seconds: soundLength(p.file), path: `web/public/demo/${p.file}` }));
  await s.close();

  // ---- 7: the holder's approval ----
  s = await begin("d-approval");
  page = s.page;
  s.scene(7, "the-holders-approval", "The holder's approval, carrying the limits and the exact terms");
  await page.goto(`${BASE}/payer`);
  await page.getByRole("heading", { name: "Your limits, set once" }).waitFor();
  await page.locator(".payer-pick", { hasText: "$2,316.40" }).waitFor();
  await s.pause(1000);
  await s.click(page.locator(".payer-pick", { hasText: "$2,316.40" }), "The holder opens her claim");
  await s.point(page.locator(".queue-row .proof-line"), { dx: 0.3 });
  s.mark("The proof is ready, 3 of 3 proven; Khutlisa read the documents, the holder approves");
  await s.pause(2600);
  await s.point(page.locator('.queue-row .decision[data-kind="deadline"]'), { dx: 0.4 });
  s.mark("The deadline card: the proof is ready, so it can be paid now");
  await s.pause(2600);
  await s.point(page.locator('.queue-row .decision[data-kind="fee_rule"]'), { dx: 0.4 });
  s.mark("The fee card: from 250 dollars up, the fees come out of the claim");
  await s.pause(2400);
  await s.point(page.locator(".queue-row .terms-tiles"), { dx: 0.4 });
  s.mark("What the approval covers: the amount, the person and account, the documents, the limits");
  await s.pause(3200);
  s.numbers({ terms: await text(page.locator(".queue-row .terms")), deadline_card: await cardLines(page, ".queue-row", "deadline"), fee_card: await cardLines(page, ".queue-row", "fee_rule") });
  await s.click(page.getByRole("button", { name: "Approve these terms" }), "Click: Approve these terms");
  await page.locator(".queue-row .state", { hasText: "Approved" }).waitFor({ timeout: 30000 });
  s.mark("Approved");
  await s.pause(2400);
  await s.close();

  // Off screen, through the same routes: her second claim (95.00 US dollars, the same first account), approved;
  // Amihan's small claim up to the bank account; Amihan's wages claim with only a staff badge.
  log("setting up the other claims off screen");
  const [claimB, claimC, claimD] = await Promise.all([
    api.openClaim("marisol", 95, ["Passport photo page", "Taxpayer number letter", "Bank statement"]),
    api.openClaim("amihan", 120, ["Passport photo page", "Taxpayer number letter", "Bank statement"]),
    api.openClaim("amihan", 1840.55, ["Staff badge"], { bank: false }),
  ]);
  for (const id of [claimB, claimC]) if (!(await api.claim(id)).proof.ready) throw new Error(`the proof of claim ${id} did not become ready`);
  await api.approve(claimB);

  // ---- 8, 9 and 10: the plan, the payment with the refusal, Airwallex's lines ----
  s = await begin("e-payment");
  page = s.page;
  s.scene(8, "the-payout-plan", "The payout plan comparing routes");
  await page.goto(`${BASE}/#payout/${claimA}`);
  await page.getByRole("heading", { name: "The payout plan" }).waitFor({ timeout: 30000 });
  await s.pause(1000);
  await s.click(page.locator("label.choice", { hasText: "The receiving bank refuses the transfer" }), "A sandbox test is chosen: the receiving bank will refuse the transfer");
  await s.pause(500);
  await s.click(page.getByRole("button", { name: "Show the payout plan" }), "Click: Show the payout plan");
  await s.wait("Airwallex quotes both routes", () => page.locator(".plan-receive").waitFor({ timeout: 60000 }));
  s.mark("The plan: two decision cards and the amount");
  await s.pause(900);
  await s.point(page.locator('.plan-stage .decision[data-kind="fee_rule"] .decision-did'), { dx: 0.3 });
  s.mark("The fee card");
  await s.pause(2600);
  await s.point(page.locator('.plan-stage .decision[data-kind="route_chosen"] .decision-money'), { dx: 0.3 });
  s.mark("The route card: two routes compared with Airwallex's own quote, the better one chosen");
  await s.pause(3400);
  await s.point(page.locator(".plan-receive .received-amount"), { dx: 0.4 });
  s.mark("What she should receive, at a rate locked for one hour");
  await s.pause(2600);
  const planned = await api.payout(claimA);
  s.numbers({ fee_card: await cardLines(page, ".plan-stage", "fee_rule"), route_card: await cardLines(page, ".plan-stage", "route_chosen"),
    should_receive: `${planned.plan.expected_local.amount} ${planned.plan.expected_local.currency}`, rate: planned.plan.rate.client_rate,
    routes: planned.plan.routes_compared.map((r) => `${r.route_name}: ${r.would_receive ? `${r.would_receive.amount} ${r.would_receive.currency}` : "not open"}${r.chosen ? " (chosen)" : ""}`) });

  s.scene(9, "the-payment-refused-and-replaced", "The payment: the transfer leaves, the bank refuses, the money returns, the decision card, the replacement is paid");
  await s.click(page.getByRole("button", { name: /I agree\. Start the payment/ }), "Click: I agree. Start the payment");
  await page.locator(".moneyline").waitFor({ timeout: 120000 });
  s.mark("The money's line: the holder sends 2,316.40 US dollars");
  await s.moveTo(960, 420);
  await s.wait("Airwallex books the deposit and its fee, and the first transfer leaves", () => page.waitForFunction(() => document.querySelector(".leg-stop") || document.querySelector(".received"), null, { timeout: 300000, polling: 300 }));
  s.mark("The bank refuses the transfer: a red stop on the line");
  await s.point(page.locator(".leg-stop .leg-dot"));
  await s.pause(1800);
  await s.wait("the replacement is worked out", () => page.waitForFunction(() => /did not ask the owner to confirm|stopped and asked/.test(document.querySelector(".refusal-cards")?.textContent ?? ""), null, { timeout: 120000, polling: 300 }));
  await s.point(page.locator(".moneyline .leg-back .leg-figure"));
  s.mark("The money comes back, in Mexican pesos");
  await s.pause(1800);
  await s.point(page.locator(".refusal-cards .decision-did"), { dx: 0.3 });
  s.mark("The decision card: 0.18 percent less, inside the 0.5 percent limit, so she is not asked to confirm the amount. The corrected account is still asked for, and the holder approves it");
  await s.pause(4200);
  const refusalCard = await cardLines(page, ".refusal-cards", "refusal");
  await page.getByRole("button", { name: "Use this account for the replacement" }).waitFor({ timeout: 120000 });
  await s.click(page.locator(".hold").getByRole("button", { name: "Fill this in for Marisol" }), "She gives a corrected account");
  const clabe = page.locator(".hold").getByLabel(/CLABE|Account number/i).first();
  await s.point(clabe, { dx: 0.3 });
  s.mark("The corrected account ends 7823; the first ended 7771");
  await s.pause(2400);
  await s.click(page.getByRole("button", { name: "Use this account for the replacement" }), "Click: Use this account for the replacement");
  await s.wait("Airwallex validates the corrected account", () => page.locator(".hold-wait").waitFor({ timeout: 60000 }));
  s.mark("Waiting for the holder to approve the corrected account");
  await page.locator(".pay-pane").evaluate((el) => el.scrollTo({ top: 0, behavior: "smooth" }));
  await s.pause(2000);
  await api.approve(claimA);
  s.mark("The holder approves the corrected account (off screen, through the holder's own route)");
  s.note("The holder's approval of the corrected account is given off screen, through the same API route the holder's view calls. A new account always needs the holder.");
  await s.moveTo(1400, 300);
  await s.wait("the replacement leaves and is paid", () => page.waitForFunction(() => document.querySelector(".received"), null, { timeout: 300000, polling: 300 }));
  s.mark("The replacement is paid to the corrected account");
  await page.locator(".pay-pane").evaluate((el) => el.scrollTo({ top: 0, behavior: "smooth" }));
  await s.point(page.locator(".moneyline .leg").last());
  await s.pause(2200);
  await s.point(page.locator(".received .received-amount"), { dx: 0.4 });
  s.mark("The amount paid, beside the amount agreed");
  await s.pause(3600);
  const paidA = await api.payout(claimA);
  const attempt = paidA.attempts[0];
  s.numbers({ holder_sent: `${paidA.deposit.amount} USD`, airwallex_incoming_fee: `${paidA.incoming_fee.amount} USD`, first_transfer: `to account ending ${attempt.account_last4}, refused: ${attempt.reason}`,
    came_back: `${attempt.came_back.amount} ${attempt.came_back.currency}`, fee_kept_by_airwallex: attempt.fee_kept ? `${attempt.fee_kept.amount} ${attempt.fee_kept.currency}` : null,
    decision_card: refusalCard, shortfall_percent: attempt.outcome?.shortfall_percent, tolerance_percent: attempt.outcome?.tolerance_percent,
    agreed: `${paidA.agreed_and_paid.agreed.amount} MXN`, paid: `${paidA.agreed_and_paid.paid.amount} MXN`, replacement_account: "ending 7823",
    first_transfer_id: attempt.transfer_id, replacement_transfer_id: paidA.transfer_id });

  s.scene(10, "airwallex-ledger", "Airwallex's own lines add up to zero, and the amount paid");
  await s.click(page.getByRole("tab", { name: /Airwallex's records/ }), "Click: Airwallex's records");
  await page.locator(".books-big").waitFor();
  s.mark("Airwallex's own lines add up to zero");
  await s.point(page.locator(".books-big"), { dx: 0.2 });
  await s.pause(2400);
  const sums = page.locator(".books-sum");
  for (let i = 0; i < (await sums.count()); i++) {
    await s.point(sums.nth(i), { dx: 0.4 });
    await s.pause(1700);
  }
  s.mark("Each line as Airwallex booked it");
  await s.point(page.locator(".books .ledger tbody tr").first(), { dx: 0.3 });
  await s.pause(1200);
  await s.point(page.locator(".books .ledger tbody tr").last(), { dx: 0.3 });
  await s.pause(2600);
  s.numbers({ lines: paidA.reconciliation.lines.map((l) => `${l.part}: ${l.type} ${l.amount} ${l.currency}`), sums: paidA.reconciliation.sums, adds_up_to_zero: paidA.reconciliation.balanced,
    paid: `${paidA.received.amount} ${paidA.received.currency}` });
  await s.close();

  // Off screen: the same refusal on the 95.00 dollar claim. It falls outside the limit, so after the corrected
  // account and the holder's approval it waits for her to agree to the smaller amount.
  log("staging the same refusal on the small claim, off screen");
  const planB = await api.plan(claimB, "transfer_fails");
  await api.confirm(claimB, planB.plan.id);
  await api.until(claimB, (p) => p.hold?.ready && p.hold.kind === "transfer_failed" && p.claim_state === "PAYMENT_HELD");
  const corrected = (await api.people()).find((p) => p.key === "marisol").bank_corrected;
  await api.setBank(claimB, corrected);
  await api.approve(claimB);
  const heldB = await api.until(claimB, (p) => JSON.stringify(p.hold?.needs) === JSON.stringify(["claimant"]));

  // ---- 11: two claims side by side ----
  s = await begin("f-side-by-side");
  page = s.page;
  s.scene(11, "two-claims-side-by-side", "Two claims side by side: the same event, the same limits, different outcomes");
  await page.goto(`${BASE}/payer`);
  await page.getByRole("button", { name: "Two refused transfers, side by side" }).waitFor({ timeout: 30000 });
  await s.pause(1200);
  await s.click(page.getByRole("button", { name: "Two refused transfers, side by side" }), "Click: Two refused transfers, side by side");
  await page.locator(".compare").waitFor();
  s.mark("The same refusal on two claims, under the same 0.5 percent limit");
  await s.point(page.locator(".compare-rule"), { dx: 0.3 });
  await s.pause(2600);
  await s.point(page.locator(".compare-go .compare-verdict"), { dx: 0.4 });
  s.mark("2,316.40 US dollars: 0.18 percent less, inside the limit, the owner was not asked about the amount again");
  await s.pause(3800);
  await s.point(page.locator(".compare-stop .compare-verdict"), { dx: 0.4 });
  s.mark("95.00 US dollars: the same fee is a far larger share, outside the limit, it stopped and asked the owner");
  await s.pause(4200);
  const attemptB = heldB.attempts[0];
  s.numbers({ left: await text(page.locator(".compare-go")), right: await text(page.locator(".compare-stop")),
    small_claim: { holder_sent: `${heldB.deposit.amount} USD`, came_back: `${attemptB.came_back.amount} ${attemptB.came_back.currency}`, agreed: `${attemptB.outcome.agreed_local} MXN`,
      replacement_would_bring: `${attemptB.outcome.replacement_local} MXN`, shortfall_percent: attemptB.outcome.shortfall_percent, tolerance_percent: attemptB.outcome.tolerance_percent,
      state: "waiting for the owner to agree to the smaller amount", first_transfer_id: attemptB.transfer_id } });
  s.note("The 95.00 dollar claim was set up and its refusal staged off screen, through the same API routes the screens use, on the same sandbox.");
  await s.close();

  // ---- 12: the small claim where the holder bears the fees ----
  s = await begin("g-small-claim");
  page = s.page;
  s.scene(12, "small-claim-holder-bears-the-fees", "The small claim where the holder bears the fees");
  await page.goto(`${BASE}/payer`);
  await page.locator(".payer-pick", { hasText: "$120.00" }).waitFor({ timeout: 30000 });
  await s.pause(1000);
  await s.click(page.locator(".payer-pick", { hasText: "$120.00" }), "The holder opens Amihan's claim of 120.00 US dollars");
  await s.point(page.locator('.queue-row .decision[data-kind="fee_rule"] .decision-did'), { dx: 0.3 });
  s.mark("The fee card: fees would take 4.5 percent, so the holder sends 125.38 and she gets the whole 120.00");
  await s.pause(4200);
  const feeSmall = await cardLines(page, ".queue-row", "fee_rule");
  await s.click(page.getByRole("button", { name: "Approve these terms" }), "Click: Approve these terms");
  await page.locator(".queue-row .state", { hasText: "Approved" }).waitFor({ timeout: 30000 });
  await s.pause(1200);
  await page.goto(`${BASE}/#payout/${claimC}`);
  s.mark("Her payment screen");
  await page.getByRole("heading", { name: "The payout plan" }).waitFor({ timeout: 30000 });
  await s.click(page.getByRole("button", { name: "Show the payout plan" }), "Click: Show the payout plan");
  await s.wait("Airwallex quotes the route", () => page.locator(".plan-receive").waitFor({ timeout: 60000 }));
  await s.point(page.locator(".plan-receive .received-amount"), { dx: 0.4 });
  s.mark("The plan: the whole 120.00 US dollars, in Philippine pesos");
  await s.pause(2600);
  await s.click(page.getByRole("button", { name: /I agree\. Start the payment/ }), "Click: I agree. Start the payment");
  await page.locator(".moneyline").waitFor({ timeout: 120000 });
  await s.moveTo(960, 420);
  await s.wait("the money moves on the sandbox", () => page.waitForFunction(() => document.querySelector(".received"), null, { timeout: 300000, polling: 300 }));
  s.mark("Paid whole");
  await s.point(page.locator(".received .received-amount"), { dx: 0.4 });
  await s.pause(3800);
  const paidC = await api.payout(claimC);
  s.numbers({ fee_card: feeSmall, claim: "120.00 USD", holder_sent: `${paidC.deposit.amount} USD`, airwallex_incoming_fee: `${paidC.incoming_fee.amount} USD`,
    payout_fee: paidC.payout_fee ? `${paidC.payout_fee.amount} ${paidC.payout_fee.currency}` : null, rate: paidC.rate, paid: `${paidC.received.amount} ${paidC.received.currency}`,
    transfer_id: paidC.transfer_id, adds_up_to_zero: paidC.reconciliation.balanced });
  s.note("Amihan's claim was opened, her three documents read and her bank account given off screen, through the same API routes the screens use.");

  // ---- 13: what is real here ----
  s.scene(13, "what-is-real-here", "The one panel that says what is real here");
  await s.click(page.getByRole("button", { name: "What is real here" }), "Click: What is real here");
  await page.locator(".real-panel").waitFor();
  s.mark("Real: California's whole file, the organisations and holder figures, the document reading, every Airwallex call on the sandbox");
  await s.point(page.locator(".real-yes"), { dx: 0.4 });
  await s.pause(4200);
  s.mark("Not real yet: a demonstration person and documents, sandbox money, no holder uses it yet");
  await s.point(page.locator(".real-no"), { dx: 0.4 });
  await s.pause(5200);
  s.numbers({ panel: await text(page.locator(".real-panel")) });
  await s.click(page.getByRole("button", { name: "Close" }), "Close");
  await s.pause(600);
  await s.close();

  // ---- 14 (extra): the handover date decides ----
  s = await begin("h-deadline");
  page = s.page;
  s.scene(14, "the-handover-date-decides", "Extra: the handover date decides. Time in hand, the agent asks; near the date, it pays what is proven and releases the rest");
  await page.goto(`${BASE}/payer`);
  await page.locator(".payer-pick", { hasText: "$1,840.55" }).waitFor({ timeout: 30000 });
  await s.pause(1000);
  await s.click(page.locator(".payer-pick", { hasText: "$1,840.55" }), "A claim whose proof is not ready: only a staff badge");
  await s.point(page.locator(".handover-days"));
  s.mark("The days left until the handover to the State");
  await s.pause(2000);
  await s.point(page.locator('.queue-row .decision[data-kind="deadline"] .decision-did'), { dx: 0.3 });
  s.mark("Time in hand: the agent asked the owner for the missing document");
  await s.pause(3600);
  const asking = await cardLines(page, ".queue-row", "deadline");
  const near = nearHandoverDate();
  await s.click(page.getByRole("button", { name: "Change them" }), "The holder changes its handover date");
  await s.point(page.getByLabel("Your handover date to the State"));
  await s.pause(500);
  await page.getByLabel("Your handover date to the State").fill(near);
  s.mark(`The handover date is set to ${near}`);
  await s.pause(1500);
  await s.click(page.getByRole("button", { name: "Save the limits" }), "Click: Save the limits");
  await s.wait("the queue is read again", () => page.waitForFunction(() => /Too close to wait/.test(document.querySelector(".queue-row")?.textContent ?? ""), null, { timeout: 20000, polling: 300 }));
  await s.point(page.locator(".handover-days"));
  s.mark("Few days left");
  await s.pause(2000);
  await s.point(page.locator('.queue-row .decision[data-kind="deadline"] .decision-did'), { dx: 0.3 });
  s.mark("Too close to wait: this property is released to the State process");
  await s.pause(3600);
  await s.point(page.locator('.payer-left .decision[data-kind="deadline"] .decision-did'), { dx: 0.3 });
  s.mark("Across the queue: it pays what is proven and releases the rest");
  await s.pause(3800);
  s.numbers({ with_time_in_hand: asking, near_the_date: await cardLines(page, ".queue-row", "deadline"), across_the_queue: await cardLines(page, ".payer-left", "deadline"),
    handover_date_set: near, schedule: handover.schedule });
  s.note("The date is a setting the holder keeps. California's schedule (Code of Civil Procedure 1532(a)) puts the handover between 1 and 15 June, or 1 and 15 December for life insurance companies.");
  await s.close();

  return { sessions, claims: { marisol_2316: claimA, marisol_95: claimB, amihan_120: claimC, amihan_1840_proof_not_ready: claimD } };
}

// ---- cutting the session videos into clips -----------------------------------------------------------------------

function ffmpeg(args) {
  const made = spawnSync("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", ...args]);
  if (made.status !== 0) throw new Error(`ffmpeg failed: ${String(made.stderr).slice(0, 400)}`);
}

function cut(sessions) {
  mkdirSync(FRAMES, { recursive: true });
  const clips = [];
  for (const session of sessions) {
    for (const scene of session.scenes) {
      const file = `${String(scene.number).padStart(2, "0")}-${scene.name}.mp4`;
      const from = Math.max(scene.from - 0.15, 0);
      const length = scene.to - from;
      ffmpeg(["-ss", from.toFixed(3), "-i", session.video, "-t", length.toFixed(3), "-vf", "fps=30", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-an", join(OUT, file)]);
      const shots = [0.15, 0.5, 0.9].map((share, i) => {
        const frame = join(FRAMES, `${file.replace(".mp4", "")}-${i + 1}.jpg`);
        ffmpeg(["-ss", (length * share).toFixed(3), "-i", join(OUT, file), "-frames:v", "1", "-q:v", "3", frame]);
        return frame;
      });
      ffmpeg(["-i", shots[0], "-i", shots[1], "-i", shots[2], "-filter_complex", "[0][1][2]hstack=inputs=3,scale=2880:-1", "-q:v", "4", join(FRAMES, `${file.replace(".mp4", "")}-sheet.jpg`)]);
      const rel = (t) => round(t - from);
      clips.push({
        clip: scene.number, file, title: scene.title, duration_seconds: round(length),
        what_happens: scene.events.map((e) => ({ second: rel(e.at), what: e.what })),
        waits_an_editor_can_cut: scene.waits.map((w) => ({ from_second: rel(w.from), to_second: rel(w.to), seconds: round(w.to - w.from), what: w.what })),
        seconds_without_the_waits: round(length - scene.waits.reduce((n, w) => n + (w.to - w.from), 0)),
        sound_not_in_the_clip: scene.sounds.map((p) => ({ starts_at_second: rel(p.at), runs_for_seconds: p.seconds, file: p.path })),
        numbers_on_screen: scene.numbers, notes: scene.notes,
        frames_checked: shots.map((f) => f.replace(OUT + "/", "")),
      });
    }
  }
  return clips.sort((a, b) => a.clip - b.clip);
}

async function main() {
  if (!existsSync(join(ROOT, "web", "dist", "index.html"))) throw new Error("web/dist is missing: run npm run build in web/ first");
  if (!existsSync(join(ROOT, "data", "registers.duckdb"))) throw new Error("data/registers.duckdb is missing. Load California's file first (see the README).");
  if (!(await portFree(PORT))) throw new Error(`Port ${PORT} is already in use. Stop that server first.`);
  mkdirSync(OUT, { recursive: true });
  for (const f of readdirSync(OUT)) if (/\.(mp4|json)$/.test(f)) rmSync(join(OUT, f));
  rmSync(RAW, { recursive: true, force: true });
  rmSync(FRAMES, { recursive: true, force: true });
  rmSync(CLAIMS, { recursive: true, force: true });

  startServer(PORT, { KHUTLISA_CLAIMS: CLAIMS, KHUTLISA_PAYER_KEY: KEY });
  const register = await waitFor(`${BASE}/api/register`, 120);
  if (!(register.loaded && register.owner_records > 90e6)) throw new Error("the server is not on California's file");
  await sleep(500);

  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  let result;
  try {
    result = await record(browser);
  } finally {
    await browser.close();
    stopServers();
  }
  for (const session of result.sessions) {
    const kept = join(RAW, `${session.name}.webm`);
    renameSync(session.video, kept);
    session.video = kept;
  }
  const clips = cut(result.sessions);
  writeFileSync(join(OUT, "scenes.json"), JSON.stringify({
    recorded_at: new Date().toISOString(), size: "1920x1080", frames_per_second: 30,
    note: "Captured by Playwright at 25 frames a second from the real app, the real register database and the real Airwallex sandbox, then written at 30. No sound is in the clips; where a sound file plays, its start and length are given. Cards of real owners are blurred throughout. Seconds are counted from the start of each clip.",
    claims: result.claims, clips }, null, 2));
  for (const c of clips) log(`${c.file}  ${c.duration_seconds}s (${c.seconds_without_the_waits}s without the waits)`);
  log(`scenes.json and ${clips.length} clips are in ${OUT}`);
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
