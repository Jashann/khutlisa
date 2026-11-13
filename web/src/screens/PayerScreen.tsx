import { useEffect, useState } from "react";
import { LockedError, approveClaim, getPayerQueue, makeClaimsBatch, payerKey, rejectClaim, setInstructions, setPayerKey } from "../api";
import DecisionCard from "../components/DecisionCard";
import MetalPanel from "../components/MetalPanel";
import Masthead from "../components/Masthead";
import Waiting from "../components/Waiting";
import { count, dateTime, duration, exact, plainPropertyType, sentence, stateWords, toClaimant } from "../format";
import { approveOnMetal, getMetalStatus } from "../metal";
import type { MetalStatus } from "../metal";
import type { HandoverView, InstructionRules, InstructionsView, PayerQueue, ProofSummary, QueueRow } from "../types";

const STAGE_WORDS: Record<string, string> = { found: "Found", proven: "Proven", filed: "Claimed from the State", approved: "Approved", paid: "Paid" };
const STAGE_LOWER: Record<string, string> = { found: "found", proven: "proven", filed: "claimed from the State", approved: "approved", paid: "paid" };

/** "Wages, payroll, salaries" from the file's "MS01: WAGES, PAYROLL, SALARIES". */
const kindWords = (raw: string) => {
  const text = plainPropertyType(raw).toLowerCase();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Money";
};

/** The holder's limits: set once, shown as five figures, and bound into every approval given afterwards. */
function Instructions({ held, handover, onSaved, onLocked }: { held: InstructionsView; handover: HandoverView; onSaved: () => Promise<unknown>; onLocked: (e: LockedError) => void }) {
  const start = (): InstructionRules => ({ ...(held.rules ?? held.defaults), handover_date: handover.handover_date, document_days: handover.document_days });
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<InstructionRules>(start);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const save = async () => {
    setBusy(true);
    setProblem("");
    try {
      await setInstructions(draft);
      await onSaved();
      setOpen(false);
    } catch (e) {
      if (e instanceof LockedError) onLocked(e);
      else setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const r = held.rules;
  return (
    <section className="instructions" id="limits" aria-label="Standing instructions">
      <div className="instructions-head">
        <h2>Your limits, set once</h2>
        {!open && (
          <button type="button" className="secondary secondary-flat" onClick={() => { setDraft(start()); setOpen(true); }}>
            {held.set ? "Change them" : "Set them"}
          </button>
        )}
      </div>
      {!open && !r && <p className="quiet">None set. Until you set them, every change stops the payment and asks a person.</p>}
      {!open && r && (
        <ul className="limits" aria-label="The limits in force">
          <li><strong>{r.tolerance_percent}%</strong><span>less than agreed, without asking the owner to confirm the amount</span></li>
          <li><strong>{exact(r.small_claim_usd, "USD")}</strong><span>below this, you bear the fees</span></li>
          <li><strong>{r.route_rule === "most_to_claimant" ? "Best route" : "Fixed route"}</strong><span>{r.route_rule === "most_to_claimant" ? "the one that delivers most" : "the one the currency dictates"}</span></li>
          <li><strong>{r.deadline_days} days</strong><span>to send the money after you approve</span></li>
          <li><strong>{handover.document_days} days</strong><span>before the handover, stop waiting for documents</span></li>
        </ul>
      )}
      {!open && r && <p className="quiet limits-never">Never inside them: another bank account, a larger amount, a second payment.</p>}
      {open && (
        <form className="instruction-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <label className="field">
            <span>Amount tolerance, in percent</span>
            <input value={draft.tolerance_percent} onChange={(e) => setDraft({ ...draft, tolerance_percent: e.target.value })} inputMode="decimal" />
          </label>
          <label className="field">
            <span>Small-claim line, in US dollars</span>
            <input value={draft.small_claim_usd} onChange={(e) => setDraft({ ...draft, small_claim_usd: e.target.value })} inputMode="decimal" />
          </label>
          <label className="field">
            <span>Route</span>
            <select value={draft.route_rule} onChange={(e) => setDraft({ ...draft, route_rule: e.target.value as InstructionRules["route_rule"] })}>
              <option value="most_to_claimant">The route that delivers most to the owner</option>
              <option value="fixed">The route the currency dictates</option>
            </select>
          </label>
          <label className="field">
            <span>Days to send the money after approval</span>
            <input value={String(draft.deadline_days)} onChange={(e) => setDraft({ ...draft, deadline_days: Number(e.target.value.replace(/\D/g, "")) || 0 })} inputMode="numeric" />
          </label>
          <label className="field">
            <span>Your handover date to the State</span>
            <input type="date" value={draft.handover_date ?? ""} onChange={(e) => setDraft({ ...draft, handover_date: e.target.value })} />
          </label>
          <label className="field">
            <span>Days an owner needs to send a document</span>
            <input value={String(draft.document_days ?? "")} onChange={(e) => setDraft({ ...draft, document_days: Number(e.target.value.replace(/\D/g, "")) || 0 })} inputMode="numeric" />
          </label>
          {problem && <p className="notice">{problem}</p>}
          <div className="actions">
            <button type="submit" className="primary primary-small" disabled={busy}>Save the limits</button>
            <button type="button" className="plain" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      )}
    </section>
  );
}

/** Two claims on which the bank refused the transfer, side by side: the same event under the same limits. */
function Compare({ rows, limit }: { rows: QueueRow[]; limit: string | null }) {
  return (
    <section className="compare" aria-label="The same event on two claims">
      <h2>The same event, the same limits, two outcomes</h2>
      <p className="compare-rule">
        The bank refused both transfers. Your limit: up to <strong>{limit ?? "0"}%</strong> less than agreed without asking the owner to confirm the amount. A corrected account is always asked for, and you always approve it.
      </p>
      <div className="compare-cols">
        {rows.map((c) => {
          const r = c.refusal!;
          return (
            <article key={c.id} className={r.asked ? "compare-col compare-stop" : "compare-col compare-go"}>
              <header>
                <p className="compare-amount">{exact(c.amount, c.currency)}</p>
                <p className="compare-who">{c.claimant.name}, {kindWords(c.property_type).toLowerCase()}</p>
              </header>
              <p className="compare-short">{r.shortfall_percent ?? "?"}% less</p>
              <p className="compare-verdict">{r.asked === null ? "Working it out" : r.asked ? "Outside the limit: it stopped and asked the owner" : "Inside the limit: the owner was not asked about the amount again"}</p>
              <DecisionCard card={r} compact />
              <p className="compare-accounts quiet">
                First account ending {r.first_account ?? "unknown"}{r.now_account && r.now_account !== r.first_account ? `, corrected to ${r.now_account}` : ""}. {stateWords(c.state)}.
              </p>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export default function PayerScreen({ onHome }: { onHome: () => void }) {
  const [queue, setQueue] = useState<PayerQueue | null>(null);
  const [problem, setProblem] = useState("");
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  // The holder's routes need a shared key. It is asked for once and kept for this browser tab only.
  const [unlocked, setUnlocked] = useState(() => payerKey() !== "");
  const [typedKey, setTypedKey] = useState("");
  const [keyProblem, setKeyProblem] = useState("");
  // "/payer#claim-<id>" opens on that claim (a link from a batch or from the risk view).
  const [chosenId, setChosenId] = useState<string | null>(() => window.location.hash.match(/^#claim-([0-9a-f]+)$/)?.[1] ?? null);
  // Approved claims the holder has ticked, to be paid together from one deposit.
  const [together, setTogether] = useState<string[]>([]);
  const [view, setView] = useState<"claim" | "compare">("claim");
  // Whether a claim can be funded on Metal on this server, and at what scale. Asked once.
  const [metal, setMetal] = useState<MetalStatus | null>(null);
  useEffect(() => { getMetalStatus().then(setMetal).catch(() => setMetal(null)); }, []);

  const lock = (e: LockedError) => {
    setPayerKey("");
    setUnlocked(false);
    setQueue(null);
    setKeyProblem(e.message || "The holder's key is missing or wrong.");
  };
  const load = () =>
    getPayerQueue()
      .then(setQueue)
      .catch((e: Error) => (e instanceof LockedError ? lock(e) : setProblem(e.message)));

  // "/payer#limits" opens on the standing instructions, once the queue is there to scroll in.
  const loaded = queue !== null;
  useEffect(() => {
    if (loaded && window.location.hash === "#limits") document.getElementById("limits")?.scrollIntoView({ block: "start" });
  }, [loaded]);

  useEffect(() => {
    if (!unlocked) return;
    void load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [unlocked]);

  const decide = async (work: () => Promise<QueueRow>) => {
    setBusy(true);
    setProblem("");
    try {
      await work();
      setRejecting(null);
      setReason("");
      await load();
    } catch (e) {
      if (e instanceof LockedError) lock(e);
      else setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const note = "The holder's view: the company that owes the money";
  if (!unlocked) {
    return (
      <main className="flow onescreen">
        <Masthead onHome={onHome} note={note} />
        <div className="flow-body flow-narrow">
          <h1>The holder's view is locked</h1>
          <p className="quiet">Type the key that was set on this server. It is kept for this browser tab only.</p>
          {keyProblem && <p className="notice">{keyProblem}</p>}
          <form className="key-form" onSubmit={(e) => { e.preventDefault(); setKeyProblem(""); setProblem(""); setPayerKey(typedKey.trim()); setUnlocked(typedKey.trim() !== ""); }}>
            <label className="field">
              <span>Holder's key</span>
              <input type="password" value={typedKey} onChange={(e) => setTypedKey(e.target.value)} autoComplete="off" autoFocus />
            </label>
            <button type="submit" className="primary primary-small" disabled={typedKey.trim() === ""}>
              Open the holder's view
            </button>
          </form>
        </div>
      </main>
    );
  }

  const results = queue?.results;
  const claims = queue?.claims ?? [];
  const chosen = claims.find((c) => c.id === chosenId) ?? claims.find((c) => c.can_decide) ?? claims[0] ?? null;
  // Times between stages mean something only for real claims. A demonstration claim is clicked through in seconds.
  const rehearsal = claims.length > 0 && claims.every((c) => c.sample);
  const handover = queue?.handover;
  const summary = queue?.deadline_summary;
  const refused = claims.filter((c) => c.refusal && c.refusal.asked !== null);
  // The pair to compare: one that carried on alone and one that stopped and asked, when both exist.
  const pair = [refused.find((c) => c.refusal!.asked === false), refused.find((c) => c.refusal!.asked === true)].filter((c): c is QueueRow => Boolean(c));
  const comparing = view === "compare" && pair.length === 2;
  return (
    <main className="flow onescreen payer">
      <Masthead onHome={onHome} note={note} />
      <div className="payer-cols">
        <section className="pane payer-left">
        <h1>Money you owe to owners abroad</h1>
        <p className="quiet">
          <a className="risk-link" href="/risk">
            Risk view: {count(claims.filter((c) => ["held", "suspended"].includes((c as { risk?: { status?: string } | null }).risk?.status ?? "")).length)} held
          </a>
        </p>
        {handover && (
          <div className={handover.days_left <= handover.document_days ? "handover handover-near" : "handover"}>
            <p className="handover-days">{count(Math.max(handover.days_left, 0))}<span> days</span></p>
            <div>
              <p className="handover-what">until you must hand unclaimed property to the State, on {handover.date_words}.</p>
              <p className="quiet handover-law">
                Before that date you pay the owner yourself (Code of Civil Procedure 1532(b)). After it you may still pay,
                and the State repays you (1560(b)).
              </p>
            </div>
          </div>
        )}
        {claims.length > 0 && (
          <ul className="payer-list" aria-label="Claims">
            {claims.map((c) => (
              <li key={c.id}>
                <button type="button" className={c.id === chosen?.id && !comparing ? "payer-pick payer-pick-on" : "payer-pick"} onClick={() => { setChosenId(c.id); setView("claim"); }}>
                  <span className="payer-pick-name">{c.claimant.name}</span>
                  <span className="payer-pick-amount">{exact(c.amount, c.currency)}</span>
                  <span className={`state state-${c.state.toLowerCase()}`}>{stateWords(c.state)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {pair.length === 2 && (
          <button type="button" className={comparing ? "compare-open compare-open-on" : "compare-open"} onClick={() => setView(comparing ? "claim" : "compare")}>
            Two refused transfers, side by side
          </button>
        )}
        {summary && <DecisionCard card={summary} compact />}
        {claims.some((c) => c.can_batch) && (
          <section className="panel pay-together" aria-label="Pay approved claims together">
            <p className="panel-label">Pay approved claims together</p>
            <p className="quiet">One deposit for all of them. Each claim keeps its own approval, its own fee rule and its own account, and is checked again before any money moves.</p>
            <ul className="pay-together-list">
              {claims.filter((c) => c.can_batch).map((c) => (
                <li key={c.id}>
                  <label>
                    <input type="checkbox" checked={together.includes(c.id)}
                      onChange={(e) => setTogether((now) => (e.target.checked ? [...now, c.id] : now.filter((x) => x !== c.id)))} />
                    <span>{c.claimant.name}</span>
                    <span className="quiet">{exact(c.amount, c.currency)}{c.from_notice ? ", from a notice" : ""}</span>
                  </label>
                </li>
              ))}
            </ul>
            <button type="button" className="primary primary-small" disabled={busy || together.length < 2}
              onClick={() => {
                setBusy(true);
                setProblem("");
                makeClaimsBatch(together)
                  .then((b) => window.location.assign(`/#batch/${b.batch_id}`))
                  .catch((e: Error) => (e instanceof LockedError ? lock(e) : setProblem(e.message)))
                  .finally(() => setBusy(false));
              }}>
              {together.length < 2 ? "Tick two or more" : `Write a batch of ${together.length}`}
            </button>
          </section>
        )}
        {queue && handover && <Instructions held={queue.instructions} handover={handover} onSaved={load} onLocked={lock} />}
        {problem && <p className="notice">{problem}</p>}
        {!queue && !problem && <div className="results-empty"><Waiting counted={false}>Reading the claims.</Waiting></div>}
        {queue && queue.claims.length === 0 && <p className="results-empty">No owner has opened a claim yet.</p>}

        {results && claims.length > 0 && (
          <details className="fold results-panel" aria-label="Results">
            <summary>Results so far</summary>
            <div className="stages">
              {results.stages.filter((s) => s.stage !== "filed").map((s) => (
                <div className="stage" key={s.stage}>
                  <p className="panel-label">{STAGE_WORDS[s.stage]}</p>
                  <p className="stage-count">{count(s.count)}</p>
                  <p className="stage-amount">{exact(s.amount, results.currency)}</p>
                </div>
              ))}
            </div>
            {!rehearsal && (
            <ul className="medians">
              {results.medians.filter((m) => m.from !== "filed" && m.to !== "filed").map((m) => (
                <li key={m.from}>
                  <span className="median-label">From {STAGE_LOWER[m.from] ?? m.from} to {STAGE_LOWER[m.to] ?? m.to}</span>
                  <span className="median-value">
                    {m.median_seconds === null
                      ? "No claim yet"
                      : `${duration(m.median_seconds)}${m.claims > 1 ? ` (median of ${count(m.claims)} claims)` : " (one claim)"}`}
                  </span>
                </li>
              ))}
            </ul>
            )}
            <p className="quiet medians-note">
              {results.rejected === 0 ? "No claim has been rejected." : `${count(results.rejected)} ${results.rejected === 1 ? "claim has" : "claims have"} been rejected.`}
              {results.payment_held > 0 && ` ${count(results.payment_held)} ${results.payment_held === 1 ? "payment is" : "payments are"} on hold.`}
            </p>
          </details>
        )}
        </section>

        <section className="pane payer-right">
        {comparing && <Compare rows={pair} limit={queue?.instructions.rules?.tolerance_percent ?? null} />}
        {!comparing && (chosen ? [chosen] : []).map((c) => {
          const file: ProofSummary | null = c.proof_file.assessed ? (c.proof_file as ProofSummary) : null;
          const proven = file ? file.requirements.filter((q) => q.required && q.status === "satisfied").length : c.proof.attached;
          const wanted = file ? file.requirements.filter((q) => q.required).length : c.proof.required;
          const bound = c.approval ? c.approval.instructions : null;
          const rules = bound?.rules ?? (c.approval ? null : queue?.instructions.rules ?? null);
          const amountNow = c.approval ? exact(c.approval.amount, c.approval.currency) : c.hold?.funds ? exact(c.hold.funds.amount, c.hold.funds.currency) : exact(c.amount, c.currency);
          return (
          <article className="match queue-row" key={c.id} id={`claim-${c.id}`}>
            <header className="match-head">
              <div>
                <p className="owner payer-claimant">{c.claimant.name}</p>
                <p className="owner-note">
                  {c.claimant_country_name}. {kindWords(c.property_type)} reported by {c.holder_name || "a holder that is not named"}.
                </p>
              </div>
              <div className="queue-right">
                <p className="match-amount">{exact(c.amount, c.currency)}</p>
                <p className={`state state-${c.state.toLowerCase()}`}>{stateWords(c.state)}</p>
              </div>
            </header>

            <div className="proof-line">
              <div className="meter" role="img" aria-label={`${proven} of ${wanted} required items ${file ? "proven" : "attached"}`}>
                <span style={{ width: `${wanted ? (proven / wanted) * 100 : 0}%` }} />
              </div>
              <p>
                <strong className={file ? (file.ready ? "ready-word" : "not-ready-word") : undefined}>
                  {file ? (file.ready ? "The proof is ready." : "The proof is not ready.") : `${c.proof.attached} of ${c.proof.required} documents attached.`}
                </strong>{" "}
                {proven} of {wanted} proven.
              </p>
            </div>
            {file && (
              <div className="risk">
                <p className="risk-line">{file.remaining_risk} <span className="risk-who">{file.decided_by}</span></p>
              </div>
            )}

            {c.rejection_reason && <p className="notice queue-notice">You rejected this claim: {c.rejection_reason}</p>}

            <div className={c.refusal ? "decision-stack payer-cards" : "payer-cards payer-cards-two"}>
              {c.refusal && <DecisionCard card={c.refusal} />}
              {c.deadline && <DecisionCard card={c.deadline} compact />}
              {c.fee_card && !c.refusal && (!c.deadline || c.deadline.choice === "pay") && <DecisionCard card={c.fee_card} compact />}
            </div>

            {c.refusal && c.hold && (
              <p className="hold-wait payer-hold">
                {c.hold.waiting_for_bank_details
                  ? "Waiting for the owner to give a corrected account."
                  : c.can_decide
                    ? `The owner gave a corrected account, ending ${c.refusal.now_account ?? "unknown"} (the first ended ${c.refusal.first_account ?? "unknown"}). A new account always needs your approval.`
                    : "Waiting for the owner to agree to the new amount."}
              </p>
            )}
            {c.hold && !c.refusal && (
              <div className="hold">
                <p className="panel-label">This payment is on hold</p>
                <p className="hold-words">{c.hold.explanation}</p>
              </div>
            )}

            <div className="terms">
              <p className="panel-label">{c.approval ? "What your approval covers" : "What an approval would cover"}</p>
              <ul className="terms-tiles">
                <li><span>Amount</span><strong>{amountNow}</strong></li>
                <li>
                  <span>Paid to</span>
                  <strong>{c.payee ? <>{c.payee.account_name}, account ending <span className="mono">{c.payee.account_number.replace(/[^0-9A-Za-z]/g, "").slice(-4)}</span></> : "No bank account yet"}</strong>
                  {c.payee && <em>{c.payee.bank_country}, in {c.payee.currency}</em>}
                </li>
                <li><span>Documents</span><strong>{c.approval ? c.approval.documents : c.proof.documents}</strong><em>each fixed by its fingerprint</em></li>
                <li>
                  <span>Limits</span>
                  <strong>{rules ? `${rules.tolerance_percent}% · ${exact(rules.small_claim_usd, "USD")} · ${rules.route_rule === "most_to_claimant" ? "best route" : "fixed route"}` : "None"}</strong>
                  <em>{c.approval?.deadline_at ? `send by ${dateTime(c.approval.deadline_at)}` : rules ? `send within ${rules.deadline_days} days` : "every change is put to a person"}</em>
                </li>
              </ul>
              {c.approvals_withdrawn.map((w, i) => (
                <p key={i} className="tie-problem">An earlier approval was withdrawn on {dateTime(w.at)}, because {w.because}.</p>
              ))}
              {c.line.others > 0 && (
                <p className={c.line.ahead > 0 || c.line.paid_elsewhere ? "tie-problem" : "quiet"}>
                  {c.line.paid_elsewhere
                    ? "This property has already been paid on another claim. It cannot be paid again."
                    : c.line.ahead > 0
                      ? `${count(c.line.ahead)} earlier ${c.line.ahead === 1 ? "claim is" : "claims are"} open on this same property. Decide ${c.line.ahead === 1 ? "that one" : "those"} first.`
                      : `${count(c.line.others)} other ${c.line.others === 1 ? "claim has" : "claims have"} been opened on this property. A property is paid once.`}
                </p>
              )}
            </div>

            {(c.risk?.status === "held" || c.risk?.status === "suspended") && (
              <p className="queue-notice risk-hold-line">
                {c.risk.events?.[c.risk.events.length - 1]?.note ?? "This claim is held by the checks across claims."}{" "}
                <a style={{ color: "var(--gold)" }} href="/risk">Open the risk view</a>
              </p>
            )}
            {c.from_notice && <p className="queue-notice">The owner opened this claim with the code on a notice you sent from your own list, before the money goes to the State.</p>}
            {c.batch && (
              <p className="queue-notice">
                Paid together with other approved claims, as payment {c.batch.n} of <a style={{ color: "var(--gold)" }} href={`/#batch/${c.batch.id}`}>batch {c.batch.id}</a>.
              </p>
            )}
            {(c as { is_estate?: boolean }).is_estate && (
              <p className="queue-notice">
                The owner has died and this is an estate claim. <a style={{ color: "var(--gold)" }} href={`/#estate/${c.id}`}>Open the estate</a> to see each heir's share and to approve it.
              </p>
            )}
            {c.can_decide && !(c as { is_estate?: boolean }).is_estate && rejecting !== c.id && (
              <div className="actions">
                <button type="button" className="primary primary-small"
                  disabled={busy || (file !== null && !file.ready) || !c.payee || c.line.ahead > 0 || c.line.paid_elsewhere || c.line.held_elsewhere}
                  title={file && !file.ready ? "The proof is not ready, so this claim cannot be approved yet." : !c.payee ? "The owner has not given a bank account yet." : undefined}
                  onClick={() => decide(() => approveClaim(c.id))}>
                  {c.hold ? "Approve the new terms" : "Approve these terms"}
                </button>
                {!c.hold && metal?.available && (
                  <button type="button" className="primary primary-small approve-metal"
                    disabled={busy || (file !== null && !file.ready) || !c.payee || c.line.ahead > 0 || c.line.paid_elsewhere || c.line.held_elsewhere}
                    title="Your approval signs a mandate on Metal with these exact terms. The agent can pull only what the mandate allows."
                    onClick={() => decide(() => approveOnMetal(c.id))}>
                    Approve and fund on Metal
                  </button>
                )}
                {c.can_reject && (
                  <button type="button" className="secondary secondary-flat" disabled={busy} onClick={() => { setRejecting(c.id); setReason(""); }}>
                    Reject this claim
                  </button>
                )}
                {file && !file.ready && <p className="quiet">Approval is off until the proof is ready.</p>}
                {(!file || file.ready) && !c.payee && <p className="quiet">Approval is off until the owner gives a bank account.</p>}
                {!c.hold && metal?.available && <p className="quiet">On Metal your approval signs a mandate: the chain, not Khutlisa's code, then holds the agent to these terms. {metal.scale?.words}</p>}
                {busy && <p className="quiet">Working. Signing a mandate on Metal takes a few seconds.</p>}
              </div>
            )}
            <MetalPanel claimId={c.id} holder refresh={`${c.state}-${c.updated_at ?? ""}`} onChanged={load} onLocked={lock} />
            {c.can_decide && rejecting === c.id && (
              <form className="actions" onSubmit={(e) => { e.preventDefault(); void decide(() => rejectClaim(c.id, reason)); }}>
                <label className="field">
                  <span>Reason for rejecting, shown to the owner</span>
                  <input value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
                </label>
                <button type="submit" className="secondary secondary-flat" disabled={busy || reason.trim().length < 3}>
                  Reject the claim
                </button>
                <button type="button" className="plain" onClick={() => setRejecting(null)}>
                  Cancel
                </button>
              </form>
            )}
            {c.state === "APPROVED" && !c.batch && <p className="queue-last ready-word">Approved. The owner agrees to the payout plan, then the agent pays inside your limits. Or pay it together with other approved claims.</p>}

            {file && (
              <details className="fold payer-proof">
                <summary>What the documents show</summary>
                {!file.ready && (
                  <div className="blocked">
                    <p className="panel-label">{c.can_decide ? "Why this claim cannot be approved yet" : "What the proof was missing"}</p>
                    <ul className="lines">
                      {file.reasons.map((line, i) => (
                        <li key={i} className="doubt">{line}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(file.held ?? []).map((h) => (
                  <p key={h.document_id} className="tie-problem">
                    Held for a person to look at: {h.kind_label.toLowerCase()} ({h.filename}). {h.reasons.join(" ")}
                  </p>
                ))}
                <ul className="payer-reqs">
                  {file.requirements.map((q) => (
                    <li key={q.title} className={`payer-req payer-req-${q.status}`}>
                      <p>
                        <span className="payer-req-status">{q.status === "satisfied" ? "Proven" : q.status === "partly" ? "Not proven" : "Missing"}</span>
                        {q.title}
                        {!q.required && " (asked for, not required)"}
                        {q.files.length > 0 && <span className="quiet"> from {q.files.join(", ")}</span>}
                      </p>
                      {q.facts.map((f, i) => (
                        <p key={i} className="tie-fact">{f}</p>
                      ))}
                      {!q.required && q.problems.map((f, i) => (
                        <p key={`p${i}`} className="tie-problem">{f}</p>
                      ))}
                    </li>
                  ))}
                </ul>
                {file.record_link && <p className={file.record_link.status === "matched" ? "record-link record-link-yes" : "record-link"}>{file.record_link.text}</p>}
                {file.concerns.map((d) => (
                  <div key={d.filename}>
                    <p className="support-file">{d.filename}</p>
                    {d.concerns.map((line, i) => (
                      <p key={i} className="tie-problem">{sentence(line)}</p>
                    ))}
                  </div>
                ))}
                <p className="quiet">
                  Checked in code on each document:{" "}
                  {(file.documents ?? []).map((d) => `${d.kind_label.toLowerCase()} ${d.standing}${d.read ? `, read ${d.read}` : ""}`).join("; ")}.
                </p>
              </details>
            )}
            {c.match && (
              <details className="fold">
                <summary>Why the search tied the owner to this record</summary>
                <ul className="lines">
                  {c.reasons.map((line, i) => (
                    <li key={`r${i}`} className="reason">{sentence(toClaimant(line))}</li>
                  ))}
                  {c.doubts.map((line, i) => (
                    <li key={`d${i}`} className="doubt">{sentence(toClaimant(line))}</li>
                  ))}
                </ul>
              </details>
            )}
          </article>
          );
        })}
        </section>
      </div>
    </main>
  );
}
