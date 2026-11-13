// Walks the holder's risk view in a real browser at 1920x1080. scripts/walkthrough.mjs runs it as part 6 of the one
// walk, with its pictures in the numbered sequence of docs/shots/walk/. Run alone it saves them to
// data/samples/shots-rings/.
//
//     node scripts/walkthrough_rings.mjs
//
// It makes a fresh set of demonstration claims with three planted rings (scripts/make_ring_claims.py, seed 7) in
// data/ring_demo/walk-claims, starts its own server on that folder (port 8033) and stops it at the end. Nothing
// else is touched: no register database is needed, no model is called and no money moves. Every person in the
// claims is invented.
// The walk: the counts; a held group as a picture with its decision card; the points table; the other two
// groups; a release with a reason; and, on the holder's main view, an approval refused because the claim is held.
// To choose which held group to release, the walk reads ground_truth.json beside the claims (it picks the held group
// that holds no planted ring claim). The server and the detector never read that file.
// It needs the built front end (cd web && npm run build). Playwright is taken from PLAYWRIGHT_DIR, as in
// scripts/demo_lib.mjs. WALK_KEEP=1 leaves the server running.
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { ROOT, chromium, portFree, sleep, waitFor } from "./demo_lib.mjs";

const PYTHON = join(ROOT, ".venv", "bin", "python");
const STATE_NAMES = /\b(FOUND|PROOF_NEEDED|PROOF_READY|PACKET_READY|FILED|APPROVED|PAYING|REJECTED|PAYMENT_HELD)\b/;

/** Walks the risk journey and returns {problems, screenshots, counts}.
 *  scripts/walkthrough.mjs runs it on its own server, where the claims of the whole walk are already in the queue:
 *  it passes `server` ({base, key, claims}), the shared screenshots folder, `start`, `audit` and `watch`. The
 *  planted claims are then made in a folder of their own and copied into that server's claims folder, beside
 *  the claims the walk opened, so the risk view looks across all of them. */
export async function walkRings({ shots = join(ROOT, "data", "samples", "shots-rings"), claims = join(ROOT, "data", "ring_demo", "walk-claims"), port = 8033, seed = 7,
  server: shared = null, start = 0, audit = null, watch = null } = {}) {
  const base = shared ? shared.base : `http://localhost:${port}`;
  const key = shared ? shared.key : `walk-${randomBytes(12).toString("hex")}`;
  const problems = [];
  const check = (ok, text) => {
    if (!ok) {
      problems.push(text);
      console.log("PROBLEM:", text);
    }
    return ok;
  };
  if (!existsSync(join(ROOT, "web", "dist", "index.html"))) throw new Error("The front end is not built. Run: cd web && npm run build");
  if (!shared && !(await portFree(port))) throw new Error(`Port ${port} is in use.`);
  mkdirSync(shots, { recursive: true });
  if (!shared) for (const f of readdirSync(shots)) if (/^\d{2,3}-.*\.png$/.test(f) || f === "summary.json") rmSync(join(shots, f));

  const made = spawnSync(PYTHON, ["scripts/make_ring_claims.py", "--out", claims, "--seed", String(seed), "--other-seeds"], { cwd: ROOT, encoding: "utf8" });
  if (made.status !== 0) throw new Error(`make_ring_claims.py failed: ${made.stderr}`);
  console.log(made.stdout.trim());
  if (shared) {
    // Every claim file and its folder of documents, and the measurement, into the shared server's claims folder.
    for (const f of readdirSync(claims)) {
      if (/^[0-9a-f]{16}(\.json)?$/.test(f) || f === "ring_measurement.json") cpSync(join(claims, f), join(shared.claims, f), { recursive: true });
    }
  }

  const server = shared ? null : spawn(PYTHON, ["-m", "uvicorn", "khutlisa.server:app", "--port", String(port), "--log-level", "warning"], {
    cwd: ROOT, detached: true, stdio: ["ignore", "ignore", "inherit"],
    env: { ...process.env, KHUTLISA_CLAIMS: claims, KHUTLISA_PAYER_KEY: key, KHUTLISA_READ_DOCUMENTS: "0", KHUTLISA_DB: join(claims, "no-register.duckdb") },
  });
  const stop = () => {
    if (!server) return;
    try {
      process.kill(-server.pid, "SIGTERM");
    } catch {
      // already gone
    }
  };
  process.on("SIGINT", () => { stop(); process.exit(130); });

  const holder = { "X-Payer-Key": key };
  const api = async (path, init = {}) => {
    const r = await fetch(base + path, { ...init, headers: { ...holder, ...(init.headers ?? {}) } });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  };
  let number = start;
  let page;
  const shot = async (name) => {
    number += 1;
    await page.waitForTimeout(400);
    const found = await page.evaluate(() => ({
      text: [...document.querySelectorAll("main")].find((m) => m.offsetParent !== null)?.textContent ?? "",
      sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
      tall: document.documentElement.scrollHeight > window.innerHeight + 1,
      small: [...document.querySelectorAll("body *")].filter((el) => el instanceof HTMLElement && el.offsetParent && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(el).fontSize) < 13).length,
      notes: document.querySelectorAll(".risk-demo").length,
    }));
    check(!STATE_NAMES.test(found.text), `${name}: an internal state name is on screen`);
    check(!/[\u2013\u2014]/.test(found.text), `${name}: a long dash is on screen`);
    check(!/\p{Extended_Pictographic}/u.test(found.text), `${name}: an emoji is on screen`);
    check(!found.sideways && !found.tall, `${name}: the page scrolls`);
    check(found.small === 0, `${name}: text under 13px`);
    check(found.notes <= 1, `${name}: the demonstration note is on screen more than once`);
    check(!/\d{8,}/.test(found.text), `${name}: a long number (an account number?) is on screen`);
    const file = `${String(number).padStart(3, "0")}-${name}.png`;
    await page.screenshot({ path: join(shots, file) });
    if (audit) await audit(page, file);
    console.log("shot", file);
  };

  const result = { problems, screenshots: 0 };
  let browser;
  try {
    await waitFor(`${base}/api/countries`, 90);
    check((await fetch(`${base}/api/payer/risk`)).status === 401, "the risk view answers without the holder's key");
    browser = await chromium.launch();
    page = await (await browser.newContext({ viewport: { width: 1920, height: 1080 } })).newPage();
    if (watch) watch(page);

    await page.goto(`${base}/risk`);
    await page.getByLabel("Holder's key").fill(key);
    await page.getByRole("button", { name: "Open the risk view" }).click();
    await page.waitForSelector(".risk-strip");
    const group = (words) => page.locator(".risk-groups .payer-pick", { hasText: words }).first();
    const tab = (words) => page.getByRole("tab", { name: words });
    await group("one bank account").click();
    await shot("the-counts-and-a-held-group");
    result.counts = (await api("/api/payer/risk")).body.counts;

    await tab("The points").click();
    await shot("the-points-of-the-group");

    await group("one card picture").click();
    await shot("one-identity-card-used-under-several-names");
    await group("4 claims, one email address").click();
    await shot("one-mailbox-and-one-device-behind-name-variants");
    await tab("The points").click();
    await shot("the-points-of-the-name-variants");
    const below = page.locator(".risk-groups .payer-pick", { hasText: "Not held" }).first();
    if (await below.count()) {
      await below.click();
      await shot("linked-but-below-the-line-nothing-held");
    }

    // a release, with a reason: the honest group that is held (a daughter who opened three relatives' claims)
    const view = (await api("/api/payer/risk")).body;
    const truth = JSON.parse(readFileSync(join(claims, "ground_truth.json"), "utf8"));
    const ringIds = new Set(Object.values(truth.rings).flat());
    const planted = new Set([...ringIds, ...(truth.honest ?? [])]);
    const honest = view.groups.find((g) => g.flagged && g.nodes.every((n) => !ringIds.has(n.id) && planted.has(n.id)));
    if (!honest) throw new Error("no held group of honest planted claims was found to release");
    const toRelease = honest.nodes.find((n) => n.status === "held");
    await page.locator(".risk-groups .payer-pick").nth(view.groups.indexOf(honest)).click();
    await shot("an-honest-group-that-is-held");
    await tab("The claims and the release").click();
    await page.locator(".risk-member", { hasText: toRelease.claimant }).first().getByRole("button", { name: "Release this claim" }).click();
    await page.getByLabel("Your reason for releasing it, kept with the claim").fill("Her daughter opened the claim for her. Phoned the owner on the number in our payroll file.");
    await shot("a-release-with-a-reason");
    await page.getByRole("button", { name: "Release with this reason" }).click();
    await page.waitForSelector(".risk-released");
    await shot("released-by-a-person-the-rest-stay-held");
    const after = (await api("/api/payer/risk")).body;
    check(after.claims.find((c) => c.id === toRelease.id)?.status === "released", "the released claim is not shown as released");
    check(after.counts.released === 1, "the count of released claims is not 1");

    // an approval refused because the claim is held
    const queue = (await api("/api/payer/queue")).body.claims;
    const held = after.groups.find((g) => g.shared[0]?.kind === "email" && g.nodes.length === 4).nodes.find((n) => n.status === "held");
    const name = queue.find((c) => c.id === held.id).claimant.name;
    await page.goto(`${base}/payer`);
    await page.locator(".payer-pick", { hasText: name }).first().click();
    await page.locator(".risk-hold-line").first().waitFor();
    const line = await page.locator(".risk-hold-line").first().innerText();
    check(/Held by the fixed safety rule/.test(line), `the holder's card does not say the claim is held: ${line}`);
    const approve = page.getByRole("button", { name: "Approve these terms" });
    const refusedOnScreen = await approve.isEnabled();
    if (refusedOnScreen) {
      // Where the proof is ready, the approval is asked for and refused with the hold sentence. Where the
      // documents are read and the proof is not ready, the button is off already, and the hold is said above it.
      await approve.click();
      await page.waitForSelector(".notice");
      const notice = await page.locator(".notice").first().innerText();
      check(/This claim is held/.test(notice), `the approval was not refused with the hold sentence: ${notice}`);
      await page.locator(".notice").first().scrollIntoViewIfNeeded();
    } else {
      await page.locator(".risk-hold-line").first().scrollIntoViewIfNeeded();
    }
    await shot(refusedOnScreen ? "an-approval-refused-because-the-claim-is-held" : "a-held-claim-says-so-on-the-holders-card");
    check((await api(`/api/payer/claims/${held.id}/approve`, { method: "POST" })).status === 409, "a held claim could be approved");
    // Released, the claim is no longer refused for the hold. On a server that reads documents its proof decides
    // the rest: a planted claim's SAMPLE pictures do not tie to a record, so it may still wait for its proof.
    const freed = await api(`/api/payer/claims/${toRelease.id}/approve`, { method: "POST" });
    const why = JSON.stringify(freed.body.detail ?? "");
    check(freed.status === 200 || (freed.status === 409 && !/This claim is held/.test(why) && (!shared || /proof is not ready/.test(why))),
      `the released claim was refused for something other than its proof: ${freed.status} ${why.slice(0, 200)}`);
    const suspended = after.claims.find((c) => c.status === "suspended");
    check((await api(`/api/claims/${suspended.id}/payout/plan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).status === 409,
      "a payment could be planned on a claim whose approval is suspended");
  } catch (e) {
    check(false, `the walk stopped: ${e.message.split("\n")[0]}`);
    await page?.screenshot({ path: join(shots, "999-where-it-stopped.png") }).catch(() => undefined);
  } finally {
    await browser?.close();
    if (!process.env.WALK_KEEP) stop();
  }
  result.screenshots = number - start;
  result.last = number;
  if (!shared) writeFileSync(join(shots, "summary.json"), JSON.stringify(result, null, 2));
  return result;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  walkRings()
    .then((result) => {
      console.log(result.problems.length ? `\n${result.problems.length} problem(s):\n` + result.problems.map((p) => `  ${p}`).join("\n") : "\nThe walk ran clean.");
      return sleep(200).then(() => process.exit(result.problems.length ? 1 : 0));
    })
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
}
