// Walks the estate journey in a real browser at 1920x1080. scripts/walkthrough.mjs runs it as part 5 of the one
// walk, with its pictures in the numbered sequence of docs/shots/walk/. Run alone it saves them to
// data/samples/shots-heirs/.
//
//     node scripts/walkthrough_heirs.mjs
//
// The story: the owner of a demonstration record has died. His widow says, in Spanish, who the family is; a
// model turns her words into the family structure and the shares are worked out in code, with one follow-up
// question for what the rule still needs. Each heir is tied to the owner by documents that are read twice. The
// holder approves the estate on the exact shares. One settlement then pays the widow in Mexico, a daughter in
// the Philippines and a son in the United Kingdom, each in their own currency, while the share of a
// granddaughter in Japan, who is not proven yet, stays with the holder. The widow's bank refuses her transfer:
// the others are paid all the same, she corrects the account, the holder approves it and one replacement is
// sent. The granddaughter is then proven and paid in a second round, and Airwallex's lines add up to zero in
// every currency.
//
// It starts its own server on port 8047, on California's file (read only) and the demonstration records, with a
// fresh claims folder (data/samples/walk-heirs-claims), and stops it (and nothing else) at the end. It needs the
// built front end, the claude program for the intake and the document reading, and the Airwallex sandbox keys.
// The search itself is not shown: the claim is opened on the demonstration record through the API, so no
// picture holds a real person's record. Playwright is taken from PLAYWRIGHT_DIR, as in scripts/demo_lib.mjs.
// WALK_KEEP=1 leaves the server running. At the end it writes docs/SANDBOX_RUN_LOG_ESTATE.md from the run's files.
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, chromium, portFree, sleep, waitFor } from "./demo_lib.mjs";

const PYTHON = join(ROOT, ".venv", "bin", "python");
const STATE_NAMES = /\b(FOUND|PROOF_NEEDED|PROOF_READY|PACKET_READY|FILED|APPROVED|PAYING|REJECTED|PAYMENT_HELD|PLANNED|HELD|DEPOSIT_EXPECTED|DEPOSIT_CONFIRMED|BENEFICIARY_READY|TRANSFER_CREATED|FUNDING|RUNNING)\b/;
const DASHES = /[\u2013\u2014]/;
const EMOJI = /\p{Extended_Pictographic}/u;

/** Walks the estate journey and returns {problems, screenshots, result}.
 *  scripts/walkthrough.mjs runs it on its own server: it passes `server` ({base, key}), the claims folder of that
 *  server, the shared screenshots folder, the number of the last picture so far (`start`), and its own `audit`
 *  of each screen. Run alone, it starts a server of its own and numbers its pictures from 1. */
export async function walkHeirs({ shots = join(ROOT, "data", "samples", "shots-heirs"), claims = join(ROOT, "data", "samples", "walk-heirs-claims"), port = 8047,
  log: logFile = join(ROOT, "docs", "SANDBOX_RUN_LOG_ESTATE.md"), server: shared = null, start = 0, audit = null, watch = null } = {}) {
  const base = shared ? shared.base : `http://localhost:${port}`;
  const key = shared ? shared.key : `walk-${randomBytes(12).toString("hex")}`;
  const problems = [];
  const say = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
  const check = (ok, text) => {
    if (!ok) {
      problems.push(text);
      say("PROBLEM:", text);
    }
    return ok;
  };
  const data = existsSync(join(ROOT, "data", "registers.duckdb")) ? join(ROOT, "data") : join(ROOT, "data-shared");
  const remote = Boolean(shared?.remote);      // a public copy, reached from outside (scripts/walkthrough.mjs WALK_BASE)
  if (!remote && !existsSync(join(ROOT, "web", "dist", "index.html"))) throw new Error("The front end is not built. Run: cd web && npm run build");
  if (!shared && !(await portFree(port))) throw new Error(`Port ${port} is in use.`);
  mkdirSync(shots, { recursive: true });
  if (!shared) {
    for (const f of readdirSync(shots)) if (/^\d{2,3}-.*\.png$/.test(f) || f === "summary.json") rmSync(join(shots, f));
    rmSync(claims, { recursive: true, force: true });
  }

  const server = shared ? null : spawn(PYTHON, ["-m", "uvicorn", "khutlisa.server:app", "--port", String(port), "--log-level", "warning"], {
    cwd: ROOT, detached: true, stdio: ["ignore", "ignore", "inherit"],
    env: { ...process.env, KHUTLISA_DB: join(data, "registers.duckdb"), KHUTLISA_TOTALS: join(data, "totals.json"), KHUTLISA_CLAIMS: claims,
      KHUTLISA_PAYER_KEY: key, KHUTLISA_READ_DOCUMENTS: "1", KHUTLISA_DEMONSTRATION: "1" },
  });
  const stop = () => {
    if (!server) return;
    try {
      process.kill(-server.pid, "SIGTERM");
    } catch {
      // already gone
    }
  };
  const call = async (path, init = {}) => {
    const r = await fetch(base + path, init);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(`${init.method ?? "GET"} ${path} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
    return body;
  };
  const json = (method, body, headers = {}) => ({ method, headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body ?? {}) });
  const estate = (id) => call(`/api/claims/${id}/estate`);
  const until = async (id, test, what, seconds = 420) => {
    for (let i = 0; i < seconds; i++) {
      const view = await estate(id);
      if (test(view)) return view;
      await sleep(1000);
    }
    throw new Error(`the estate did not reach "${what}" within ${seconds} seconds`);
  };

  let browser;
  let page;
  let n = start;
  const result = {};
  const shot = async (name, { full = true } = {}) => {
    n += 1;
    await page.waitForTimeout(400);
    const text = await page.evaluate(() => [...document.querySelectorAll("main")].find((m) => m.offsetParent !== null)?.textContent ?? "");
    check(!STATE_NAMES.test(text), `${name}: an internal state name is on the screen (${text.match(STATE_NAMES)?.[0]})`);
    check(!DASHES.test(text), `${name}: a long dash is on the screen`);
    check(!EMOJI.test(text), `${name}: an emoji is on the screen`);
    check(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name}: the page scrolls sideways`);
    const file = `${String(n).padStart(3, "0")}-${name}.png`;
    await page.screenshot({ path: join(shots, file), fullPage: full && !audit });
    if (audit) await audit(page, file);
    say("shot", file);
  };
  const tab = (id) => page.click(`[data-tab="${id}"]`);
  const idle = () => page.waitForFunction(() => !document.querySelector(".estate .waiting"), null, { timeout: 420000 });

  try {
    await waitFor(`${base}/api/register`, 90);
    const sample = await call("/api/estate/sample");
    await call("/api/payer/instructions", json("PUT", { tolerance_percent: "0.5", small_claim_usd: "250.00", route_rule: "most_to_claimant", deadline_days: 14 }, { "X-Payer-Key": key }));
    browser = await chromium.launch();
    page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
    if (watch) watch(page);
    let id;
    if (shared) {
      // From the navigation: the estates page, and the demonstration family opened from it.
      await page.goto(`${base}/#estates`);
      await page.getByRole("button", { name: "Follow the demonstration estate" }).waitFor();
      await shot("estates-when-the-owner-has-died", { full: false });
      await page.getByRole("button", { name: "Follow the demonstration estate" }).click();
      await page.waitForSelector(".estate-intake", { timeout: 60000 });
      id = decodeURIComponent(page.url().split("#estate/")[1] ?? "");
      const opened = await call(`/api/claims/${id}`);
      check(Math.abs(Number(opened.record.amount) - 4618.37) < 0.005, `the estates page opened a claim on ${opened.record.amount}, not on the demonstration estate's 4,618.37`);
    } else {
      const found = await call("/api/search", json("POST", sample.search));
      const match = found.matches.find((m) => m.source === "DEMO" && Math.abs(m.amount - 4618.37) < 0.005);
      if (!match) throw new Error("the demonstration record of the estate was not found by the search");
      const claim = await call("/api/claims", json("POST", { record_id: match.record_id, claimant: sample.claimant, history: sample.search }));
      id = claim.id;
      await page.goto(`${base}/#estate/${id}`);
      await page.waitForSelector(".estate-intake");
    }
    result.claim = id;
    await shot("the-owner-has-died");

    // 1. The widow's words, in Spanish; the model reads them; the code asks for what the rule still needs.
    await page.click("text=Use the demonstration family's words");
    await page.click("text=Read my words");
    await page.waitForSelector(".estate-question", { timeout: 240000 });
    await idle();
    let view = await estate(id);
    check(view.question?.key === "children_of", `the follow-up should ask whether the son who died left children; it asked for "${view.question?.key}"`);
    check(view.heirs.length === 0, "no share should be shown while a fact the rule needs is missing");
    await shot("her-words-and-the-one-question");
    await page.click("text=Use the demonstration answer");
    await page.click(".estate-answer >> text=Answer");
    await page.waitForSelector(".family-tree .node-heir", { timeout: 240000 });
    await idle();
    view = await estate(id);
    const shares = Object.fromEntries(view.heirs.map((h) => [h.name, h.share]));
    result.shares = shares;
    check(JSON.stringify(view.heirs.map((h) => h.share)) === JSON.stringify(["1/3", "2/9", "2/9", "2/9"]), `the shares should be 1/3 and three of 2/9; they are ${JSON.stringify(shares)}`);
    check(view.heirs.reduce((sum, h) => sum + Math.round(Number(h.entitlement) * 100), 0) === 461837, "the entitlements should add up to 4,618.37 US dollars, to the cent");
    await shot("the-family-tree-with-each-share");
    await page.click('[data-heir="c3.1"]');
    await page.waitForSelector('[data-why="c3.1"]');
    await shot("the-statute-steps-behind-a-share", { full: false });

    // An owner who lived elsewhere: California's default is computed and flagged, not decided.
    await page.click("text=Correct the family by hand");
    await page.fill('[data-field="domicile_country"]', "MX");
    await page.fill('[data-field="domicile_state"]', "");
    await page.click("text=Work out the shares");
    await page.waitForSelector('[data-flag="other_law"]');
    await idle();
    await shot("an-owner-who-lived-elsewhere-is-flagged");
    await page.fill('[data-field="domicile_country"]', "US");
    await page.fill('[data-field="domicile_state"]', "CA");
    await page.click("text=Work out the shares");
    await page.waitForFunction(() => !document.querySelector('[data-flag="other_law"]'));
    await idle();

    // 2. The proof: the death certificate, and for three heirs their chain, identification, statement and account.
    await tab("proof");
    await shot("the-proof-before-any-document");
    await page.click('[data-demo="estate-docs"]');
    await idle();
    for (const heir of ["s1", "c1", "c2"]) {
      await page.click(`[data-demo="docs-${heir}"]`);
      await idle();
      await page.click(`[data-demo="details-${heir}"]`);
      await idle();
    }
    view = await until(id, (v) => v.documents.every((d) => d.status !== "reading"), "every document read");
    await page.reload();
    await page.waitForSelector(".estate-head");
    await tab("proof");
    check(JSON.stringify(view.payable.sort()) === JSON.stringify(["c1", "c2", "s1"]), `three heirs should be proven and payable; payable is ${JSON.stringify(view.payable)}: ${JSON.stringify(view.heirs.map((h) => [h.id, h.missing]))}`);
    check(JSON.stringify(view.held) === JSON.stringify(["c3.1"]), "the granddaughter should not be proven yet");
    await shot("three-heirs-proven-one-not-yet");

    // 3. The holder approves on the exact shares.
    await tab("holder");
    // A public copy gives its pages the holder's key, so its holder tab is open already.
    if (!remote || await page.locator('[aria-label="The holder\'s key"]').isVisible().catch(() => false)) {
      await page.fill('[aria-label="The holder\'s key"]', key);
      await page.click("text=Unlock");
    }
    await page.waitForSelector(".holder-shares");
    await shot("what-the-holder-approves", { full: false });
    await page.click('[data-action="approve-estate"]');
    await page.waitForSelector('[data-approved="yes"]');
    await idle();
    await shot("approved-on-the-shares", { full: false });

    // 4. The settlement: the plan, then the money fanning out. The widow's bank refuses her transfer.
    await tab("settlement");
    await page.selectOption('[data-field="fail-heir"]', "s1");
    await page.click('[data-action="plan"]');
    await page.waitForSelector("[data-plan]", { timeout: 120000 });
    await idle();
    view = await estate(id);
    result.plan_round_1 = { holder_sends: view.settlement.plan.holder_sends, incoming_fee_expected: view.settlement.plan.expected_incoming_fee,
      legs: view.settlement.plan.legs.map((l) => ({ name: l.name, share: l.share, usd: l.leg_usd, currency: l.currency, route: l.route_name, expected: l.expected_local.amount })),
      held: view.settlement.plan.held.map((h) => ({ name: h.name, usd: h.entitlement })) };
    check(new Set(view.settlement.plan.legs.map((l) => l.currency)).size === 3, "the first round should pay in three currencies");
    await shot("the-settlement-plan");
    await page.click('[data-action="confirm"]');
    await page.waitForSelector(".fan");
    await page.waitForSelector('.fan-leg-moving, .fan-leg-paid', { timeout: 120000 });
    await shot("the-money-fanning-out", { full: false });
    view = await until(id, (v) => !v.settlement.running && v.settlement.rounds[0].legs.every((l) => ["PAID", "FAILED", "HELD"].includes(l.state))
      && v.settlement.rounds[0].legs.some((l) => l.hold?.replacement), "the first round at rest");
    await page.waitForSelector("[data-correct]");
    const first = Object.fromEntries(view.settlement.rounds[0].legs.map((l) => [l.heir, l]));
    check(first.s1.state === "FAILED" && first.c1.state === "PAID" && first.c2.state === "PAID", `the widow's transfer should be refused and the other two paid; states are ${JSON.stringify(view.settlement.rounds[0].legs.map((l) => [l.name, l.state]))}`);
    check(view.settlement.reconciliation.accounted_for && !view.settlement.reconciliation.balanced, "after the refusal, all that is left at Airwallex should be the widow's returned pesos");
    await shot("one-bank-refuses-the-others-are-paid");

    // The widow corrects the account; the holder approves it; one replacement is sent.
    await page.click('[data-demo="corrected"]');
    await page.click('[data-action="save-corrected"]');
    await idle();
    await tab("holder");
    await page.waitForSelector('[data-action="approve-estate"]');
    await shot("the-holder-approves-the-corrected-account", { full: false });
    await page.click('[data-action="approve-estate"]');
    await idle();
    view = await until(id, (v) => !v.settlement.running && v.settlement.rounds[0].legs.every((l) => l.state === "PAID"), "the replacement paid");
    await tab("settlement");
    await page.waitForSelector('[data-leg="s1"][data-leg-state="PAID"]');
    check(view.state === "PAYMENT_HELD", `with one share still held the claim should wait for the holder; its state is ${view.state}`);
    check(view.settlement.reconciliation.balanced, "after the replacement every currency should add up to zero");
    await shot("the-replacement-is-paid-one-share-still-held");

    // 5. The granddaughter is proven, the holder approves again, and a second round pays her alone.
    await tab("proof");
    await page.click('[data-demo="docs-c3.1"]');
    await idle();
    await page.click('[data-demo="details-c3.1"]');
    await idle();
    view = await until(id, (v) => v.documents.every((d) => d.status !== "reading"), "the granddaughter's documents read");
    check(JSON.stringify(view.payable) === JSON.stringify(["c3.1"]), `the granddaughter should now be proven; missing: ${JSON.stringify(view.heirs.find((h) => h.id === "c3.1")?.missing)}`);
    await page.reload();
    await page.waitForSelector(".estate-head");
    await tab("proof");
    await shot("the-granddaughter-is-proven-link-by-link");
    await tab("holder");
    await page.click('[data-action="approve-estate"]');
    await idle();
    await tab("settlement");
    await page.click('[data-action="plan"]');
    await page.waitForSelector("[data-plan]", { timeout: 120000 });
    await idle();
    await shot("the-second-round-plan");
    await page.click('[data-action="confirm"]');
    view = await until(id, (v) => v.state === "PAID", "every heir paid");
    await page.waitForSelector('[data-balanced="yes"]', { timeout: 60000 });
    await page.waitForTimeout(1600);
    check(view.settlement.reconciliation.balanced && view.settlement.reconciliation.sums.every((s) => Number(s.left) === 0), "at the end every currency should add up to zero");
    check(view.heirs.every((h) => h.paid), "every heir should be paid");
    await shot("every-heir-paid-and-the-ledger-at-zero");
    await tab("family");
    await page.waitForSelector(".node-paid");
    await shot("the-family-tree-at-the-end");

    result.heirs = view.heirs.map((h) => ({ name: h.name, relation: h.relation, country: h.country, share: h.share, entitlement_usd: h.entitlement, paid: h.paid && `${h.paid.amount} ${h.paid.currency}` }));
    result.rounds = view.settlement.rounds.map((r) => ({ round: r.n, deposit: r.arrived?.deposit, incoming_fee: r.arrived?.incoming_fee, net: r.arrived?.net,
      legs: r.legs.map((l) => ({ name: l.name, sent_usd: l.leg_usd, route: l.route_name, payout_fee: l.payout_fee && `${l.payout_fee.amount} ${l.payout_fee.currency}`, received: l.received && `${l.received.amount} ${l.received.currency}`, refused_first: (l.attempts ?? []).length })) }));
    result.reconciliation = { sums: view.settlement.reconciliation.sums, statement: view.settlement.reconciliation.statement };
    if (!remote) {
      const made = spawnSync(PYTHON, [join(ROOT, "scripts", "estate_log.py"), join(claims, id), logFile], { cwd: ROOT, encoding: "utf8" });
      check(made.status === 0, `the run log could not be written: ${made.stderr?.slice(0, 200)}`);
    }
  } catch (e) {
    check(false, `the walk stopped: ${e.message.split("\n")[0]}`);
    await page?.screenshot({ path: join(shots, "999-where-it-stopped.png"), fullPage: true }).catch(() => undefined);
  } finally {
    await browser?.close();
    if (!process.env.WALK_KEEP) stop();
  }
  if (!shared) writeFileSync(join(shots, "summary.json"), JSON.stringify({ ...result, problems, screenshots: n }, null, 2));
  return { problems, screenshots: n - start, last: n, result };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  walkHeirs().then(({ problems, result }) => {
    console.log(JSON.stringify(result, null, 2));
    console.log(problems.length ? `\n${problems.length} problem(s):\n` + problems.map((p) => `  ${p}`).join("\n") : "\nThe walk ran clean.");
    process.exit(problems.length ? 1 : 0);
  });
}
