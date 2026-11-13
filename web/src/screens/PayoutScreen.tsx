import { useEffect, useState } from "react";
import { confirmPayout, getClaim, getPayout, planPayout, resumePayout, setPayee } from "../api";
import BankDetails from "../components/BankDetails";
import DecisionCard from "../components/DecisionCard";
import MetalPanel from "../components/MetalPanel";
import Masthead from "../components/Masthead";
import { useDemo } from "../demo";
import Waiting from "../components/Waiting";
import { clock, dateTime, exact, stateWords } from "../format";
import type { Amount, Claim, PayoutHold, PayoutPlan, PayoutView, WhatIf } from "../types";

interface Props {
  claimId: string;
  onHome: () => void;
  onClaim: (id: string) => void;
  onBackToSearch: () => void;
}

const amount = (a: Amount | null | undefined) => (a ? exact(a.amount, a.currency) : "");

const last4 = (masked: string | null | undefined) => (masked ?? "").replace(/[^0-9A-Za-z]/g, "").slice(-4);

interface Leg {
  key: string;
  label: string;
  figure: string;
  state: "done" | "now" | "todo";
  tone?: "stop" | "back" | "go" | "ask";
}

/** The money's way as one line: what the holder sends, each transfer that left, a refusal as a red stop, the money
 *  coming back, the agent's decision, and the replacement to the corrected account. Every figure is the API's. */
function legs(p: PayoutView): Leg[] {
  const done = (key: string) => Boolean(p.journey.find((j) => j.key === key)?.done);
  const out: Leg[] = [
    { key: "arrived", label: "The holder sends", figure: done("arrived") ? amount(p.deposit) : "", state: done("arrived") ? "done" : "todo" },
    { key: "fee", label: "Airwallex's fee", figure: p.incoming_fee ? amount(p.incoming_fee) : "", state: done("fee") ? "done" : "todo" },
  ];
  const attempts = p.attempts ?? [];
  attempts.forEach((a, i) => {
    out.push({ key: `left${i}`, label: i === 0 ? "First transfer leaves" : "Transfer leaves", figure: a.account_last4 ? `to account ending ${a.account_last4}` : "", state: "done" });
    out.push({ key: `stop${i}`, label: a.fate.startsWith("returned") ? "The bank returns it" : "The bank refuses it", figure: a.reason.replace(/^[A-Z_]+ \d+: /, ""), state: "done", tone: "stop" });
    out.push({ key: `back${i}`, label: "The money comes back", figure: amount(a.came_back), state: "done", tone: "back" });
    out.push({ key: `agent${i}`, label: "The agent decides", figure: !a.outcome ? "working it out" : a.outcome.claimant_asked ? `${a.outcome.shortfall_percent}% less: stops and asks` : `${a.outcome.shortfall_percent}% less: amount not asked about again`,
      state: a.outcome ? "done" : "now", tone: a.outcome?.claimant_asked ? "ask" : "go" });
  });
  const sent = done("sent");
  const paid = p.state === "PAID";
  const stopped = p.state === "FAILED" || p.state === "HELD";
  const to = last4(p.account?.number);
  // Until she has given the corrected account, the replacement has no destination to show.
  const awaitingAccount = Boolean(p.hold?.needs.includes("bank_details"));
  out.push({ key: "sent", label: attempts.length ? "Replacement leaves" : "Transfer leaves",
    figure: awaitingAccount ? "to a corrected account" : sent || attempts.length ? (to ? `to account ending ${to}` : "") : "",
    state: sent ? "done" : !stopped && done("fee") && p.running ? "now" : "todo" });
  out.push({ key: "paid", label: "Paid at home", figure: paid ? amount(p.received ?? p.local) : "", state: paid ? "done" : sent && !stopped ? "now" : "todo", tone: paid ? "go" : undefined });
  return out;
}

function MoneyLine({ payout }: { payout: PayoutView }) {
  const line = legs(payout);
  return (
    <ol className="moneyline" aria-label="The money's way" style={{ ["--legs" as string]: line.length }}>
      {line.map((leg) => (
        <li key={leg.key} className={`leg leg-${leg.state}${leg.tone ? ` leg-${leg.tone}` : ""}`}>
          <span className="leg-dot" aria-hidden="true">{leg.tone === "stop" ? "STOP" : ""}</span>
          <p className="leg-label">{leg.label}</p>
          <p className="leg-figure">{leg.figure}</p>
        </li>
      ))}
    </ol>
  );
}

const HOLD_TITLES: Record<PayoutHold["kind"], string> = {
  short_deposit: "Less money arrived than was approved",
  deposit_differs: "A different amount arrived from the one approved",
  rate_lock_expired: "The rate lock ran out before the money was converted",
  amount_changed: "The amount you would receive has changed",
  transfer_failed: "The receiving bank refused the transfer",
  transfer_returned: "The receiving bank sent the money back after it was paid",
  deadline_passed: "The holder's deadline passed before the money was sent",
  mandate_revoked: "The holder revoked its mandate on Metal before any money was pulled",
  metal_refused: "Metal refused the pull under the holder's mandate",
  metal_settlement_differs: "The settlement on Metal is not the payment that was approved",
};
const STEP_WORDS: Record<string, string> = {
  bank_details: "You correct the bank details",
  payer: "The holder approves the new terms",
  claimant: "You agree to the new amount",
};
const HOLD_STEPS: Record<PayoutHold["kind"], string[]> = {
  short_deposit: ["payer", "claimant"], deposit_differs: ["payer", "claimant"],
  rate_lock_expired: ["claimant"], amount_changed: ["claimant"],
  transfer_failed: ["bank_details", "payer", "claimant"], transfer_returned: ["bank_details", "payer", "claimant"],
  deadline_passed: ["payer"],
  mandate_revoked: ["payer"], metal_refused: ["payer"], metal_settlement_differs: ["payer"],
};

/** The written plan in full, folded away behind "The whole plan": every line, each fee, the rate, and what happens if
 *  things change. The decision cards above it carry the parts that matter. */
function Plan({ plan }: { plan: PayoutPlan }) {
  return (
    <div className="plan">
      <p className="plan-route">
        <strong>Route: {plan.route_name}.</strong> {plan.route_reason}
      </p>
      {plan.routes_compared && (
        <table className="ledger plan-table routes-table" aria-label="The routes that were compared">
          <thead>
            <tr>
              <th>Route compared</th>
              <th>Payout fee</th>
              <th>Would deliver</th>
            </tr>
          </thead>
          <tbody>
            {plan.routes_compared.map((r) => (
              <tr key={r.route} className={r.chosen ? "route-chosen" : undefined}>
                <td>{r.route_name}{r.chosen ? " (chosen)" : ""}</td>
                <td className="quiet">{r.payout_fee ? `${amount(r.payout_fee)}, ${r.payout_fee.basis}` : "Not open for this currency"}</td>
                <td className="num">{r.would_receive ? amount(r.would_receive) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <table className="ledger plan-table">
        <tbody>
          {plan.lines.map((line) => (
            <tr key={line.label}>
              <td>{line.label}</td>
              <td className="num">{amount(line)}</td>
              <td className="quiet">{line.basis}</td>
            </tr>
          ))}
          {plan.incoming_fee && (
            <tr>
              <td>Airwallex's incoming fee</td>
              <td className="num">{amount(plan.incoming_fee)}</td>
              <td className="quiet">{plan.incoming_fee.basis}</td>
            </tr>
          )}
          <tr>
            <td>Leaves Khutlisa's Airwallex account for you</td>
            <td className="num">{amount(plan.to_send)}</td>
            <td className="quiet">Never more than arrived for this claim</td>
          </tr>
          <tr>
            <td>Airwallex's payout fee, inside that amount</td>
            <td className="num">{amount(plan.payout_fee)}</td>
            <td className="quiet">{plan.payout_fee.basis}</td>
          </tr>
          {plan.rate && (
            <tr>
              <td>Rate, {plan.rate.pair}</td>
              <td className="num">{plan.rate.client_rate}</td>
              <td className="quiet">
                Locked for {plan.rate.locked_for}, until {dateTime(plan.rate.locked_until)}
              </td>
            </tr>
          )}
          <tr className="plan-total">
            <td>You should receive</td>
            <td className="num">{amount(plan.expected_local)}</td>
            <td className="quiet">Expected. The booked figure is shown once Airwallex has made the transfer</td>
          </tr>
        </tbody>
      </table>
      {plan.fee_rule ? (
        <div className="plan-fees fee-rule">
          <p className="panel-label">{plan.fee_rule.bearer === "holder" ? "Fee rule: the holder bears Airwallex's fees on this claim" : "Fee rule: Airwallex's fees come out of this claim"}</p>
          {plan.fee_rule.arithmetic.map((line) => (
            <p key={line} className="quiet">{line}</p>
          ))}
        </div>
      ) : (
        <p className="quiet plan-fees">
          Both fees are Airwallex's, and they come out of the claim's own money. Khutlisa takes nothing from the
          claimant: its customer is the holder.
        </p>
      )}
      {plan.deadline_at && <p className="quiet plan-deadline">The holder's deadline for sending this money: {dateTime(plan.deadline_at)}.</p>}
      <p className="panel-label">If things change</p>
      <ul className="plain-list plan-changes">
        {plan.if_things_change.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

export default function PayoutScreen({ claimId, onHome, onClaim, onBackToSearch }: Props) {
  const [payout, setPayout] = useState<PayoutView | null>(null);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [whatIf, setWhatIf] = useState<WhatIf | null>(null);
  const [tab, setTab] = useState<"payment" | "records">("payment");
  const { people } = useDemo();

  useEffect(() => {
    getClaim(claimId).then(setClaim).catch(() => setClaim(null));
  }, [claimId]);

  // Ask every second, so the line fills in as Airwallex completes each step. A paid transfer is still read
  // every few seconds, because the receiving bank can send the money back.
  useEffect(() => {
    let live = true;
    let timer = 0;
    const load = () =>
      getPayout(claimId)
        .then((p) => {
          if (!live) return;
          setPayout(p);
          const settled = p.state === "PAID" && !p.watching_for_return;
          if (!settled) timer = window.setTimeout(load, p.state === "PAID" || p.state === "PLANNED" || p.state === null ? 4000 : 1000);
        })
        .catch((e: Error) => {
          if (!live) return;
          setProblem(e.message);
          timer = window.setTimeout(load, 4000);
        });
    void load();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [claimId]);

  const act = async (work: () => Promise<PayoutView | void>) => {
    setBusy(true);
    setProblem("");
    try {
      const next = await work();
      if (next) setPayout(next);
    } catch (e) {
      setProblem((e as Error).message);
      getPayout(claimId).then(setPayout).catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  const head = (
    <Masthead
      now="payment"
      onHome={onHome}
      go={{ history: onBackToSearch, matches: onBackToSearch, proof: () => onClaim(claimId), claim: () => onClaim(claimId) }}
    />
  );

  if (!payout) {
    return (
      <main className="flow onescreen">
        {head}
        <div className="flow-body flow-narrow">
          {problem ? <p className="notice">{problem}</p> : <div className="results-empty"><Waiting counted={false}>Reading the payment.</Waiting></div>}
        </div>
      </main>
    );
  }

  if (payout.in_batch) {
    return (
      <main className="flow onescreen">
        {head}
        <div className="flow-body flow-narrow">
          <p className="summary-label">Payment for claim number {payout.claim_id}</p>
          <h1>{payout.claim_state === "PAID" ? "Paid at home" : "Paid together with other claims"}</h1>
          <p className={`state state-${payout.claim_state.toLowerCase()}`}>{stateWords(payout.claim_state)}</p>
          <p>{payout.in_batch.note}</p>
          <p className="quiet">The claim's history shows each step, and when the transfer is paid.</p>
          <div className="actions">
            <button type="button" className="secondary secondary-flat" onClick={() => onClaim(claimId)}>Back to the claim</button>
          </div>
        </div>
      </main>
    );
  }

  const hold = payout.hold;
  const plan = payout.plan;
  const books = payout.reconciliation;
  const transfer = payout.proof?.transfer;
  const attempts = payout.attempts ?? [];
  const heldIn = payout.funds && payout.funds.currency !== "USD" ? (payout.funds.currency as "PHP" | "MXN") : undefined;
  const canPlan = !payout.started && payout.claim_state === "APPROVED" && payout.approved;

  const person = claim?.sample ? (people.find((p) => p.claimant.name === claim.claimant.name) ?? null) : null;
  // After a refusal the form is filled with her second account, so the replacement visibly goes somewhere else.
  const fill = person && attempts.length > 0 && person.bank_corrected ? { ...person, bank: person.bank_corrected } : person;
  // The number on the tab is the number of Airwallex's own lines, which is what the tab lists first.
  const recordLines = books?.lines.length ?? 0;
  const anyRecord = recordLines + attempts.length + (payout.decisions ?? []).length > 0;
  const report = payout.agent_report ?? [];
  const cards = payout.cards ?? [];
  const refusals = cards.filter((c) => c.kind === "refusal");
  const planCards = cards.filter((c) => c.kind !== "refusal");
  const holdSteps = hold ? HOLD_STEPS[hold.kind].filter((who) => !(who === "claimant" && hold.facts?.claimant_asked === false)) : [];
  const refused = hold?.kind === "transfer_failed" || hold?.kind === "transfer_returned";
  const planShown = plan && (plan.what_if ?? null) === whatIf;
  const to = last4(payout.account?.number);
  const awaitingAccount = Boolean(hold?.needs.includes("bank_details"));
  return (
    <main className="flow onescreen">
      {head}
      <div className="flow-body claim-body">
        <header className="claim-head claim-head-tight">
          <div>
            <p className="summary-label">Payment for claim number {payout.claim_id}</p>
            <p className="summary-text">
              <span className="summary-amount">{exact(payout.record_amount, payout.record_currency)}</span>{" "}
              {payout.account ? `to ${payout.account.name}, ${awaitingAccount ? "to a corrected account" : `account ending ${to}`}.` : "to be paid at home."}
            </p>
          </div>
          <div className="tabs" role="tablist" aria-label="Parts of the payment">
            {([["payment", "The payment"], ["records", `Airwallex's records${recordLines ? ` (${recordLines})` : ""}`]] as const).map(([id, words]) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "tab tab-on" : "tab"} onClick={() => setTab(id)}>
                {words}
              </button>
            ))}
          </div>
          <p className="sandbox-badge">{payout.environment}</p>
        </header>

        {tab === "payment" && (
        <div className="pane pay-pane">

        {payout.problem && <p className="notice">{payout.problem}</p>}
        {problem && <p className="notice">{problem}</p>}
        {payout.state === "FAILED" && !hold && payout.failure && (
          <p className="notice">The payment could not go ahead, and nothing was sent. Airwallex reported: {payout.failure}</p>
        )}

        {!payout.started && !canPlan && (
          <section className="callout">
            <div>
              <h2>{payout.account ? "The holder has not approved this yet" : "The bank account comes first"}</h2>
              <p>{payout.account ? "A payment starts only after the holder approves the exact amount, person and account." : "Give the account the money should reach. The holder then approves that exact account."}</p>
            </div>
            <button type="button" className="secondary" onClick={() => onClaim(claimId)}>
              Back to the proof
            </button>
          </section>
        )}

        {canPlan && (
          <section className="plan-stage">
            <div className="plan-stage-head">
              <div>
                <h2>The payout plan</h2>
                <p className="quiet">
                  The holder approved {payout.approval ? exact(payout.approval.amount, payout.approval.currency) : "this claim"}. Nothing moves until you agree.
                </p>
              </div>
              {payout.what_if_options.length > 0 && (
                <fieldset className="whatif whatif-row">
                  <legend>Sandbox test: stage a problem on the way</legend>
                  <label className="choice">
                    <input type="radio" name="whatif" checked={whatIf === null} onChange={() => setWhatIf(null)} />
                    <span>None</span>
                  </label>
                  {payout.what_if_options.map((o) => (
                    <label className="choice" key={o.key}>
                      <input type="radio" name="whatif" checked={whatIf === o.key} onChange={() => setWhatIf(o.key)} />
                      <span>{o.label}</span>
                    </label>
                  ))}
                </fieldset>
              )}
            </div>
            {busy ? (
              <Waiting>Asking Airwallex.</Waiting>
            ) : planShown ? (
              <>
                <div className="decision-row">
                  {planCards.map((c) => (
                    <DecisionCard key={c.kind} card={c} />
                  ))}
                </div>
                <div className="plan-receive">
                  <div>
                    <p className="panel-label">You should receive</p>
                    <p className="received-amount">{amount(plan.expected_local)}</p>
                    {plan.rate && <p className="quiet">1 USD = {plan.rate.client_rate} {plan.expected_local.currency}, locked for {plan.rate.locked_for}.</p>}
                  </div>
                  <div className="actions">
                    <button type="button" className="primary" disabled={!payout.credentials_ready} onClick={() => act(() => confirmPayout(claimId, plan.id))}>
                      I agree. Start the payment
                    </button>
                    <button type="button" className="plain" onClick={() => act(() => planPayout(claimId, whatIf))}>
                      Make the plan again with a new rate
                    </button>
                  </div>
                </div>
                <details className="fold">
                  <summary>The whole plan</summary>
                  <Plan plan={plan} />
                </details>
              </>
            ) : (
              <div className="actions">
                <button type="button" className="primary" disabled={!payout.credentials_ready} onClick={() => act(() => planPayout(claimId, whatIf))}>
                  Show the payout plan
                </button>
              </div>
            )}
          </section>
        )}

        {payout.started && (
          <>
            <section className="journey-wrap" aria-live="polite">
              <MoneyLine payout={payout} />
            </section>

            {payout.what_if_label && payout.state !== "PAID" && (
              <p className="quiet whatif-note">Staged on the sandbox: {payout.what_if_label.toLowerCase()}.</p>
            )}

            {refusals.length > 0 && (
              <div className="decision-stack refusal-cards">
                {refusals.map((c, i) => (
                  <DecisionCard key={i} card={c} />
                ))}
              </div>
            )}

            {hold && (
              <section className="hold" aria-live="polite">
                {!refused && (
                  <>
                    <p className="panel-label">The payment has stopped</p>
                    <h2>{HOLD_TITLES[hold.kind]}</h2>
                    <p className="hold-words">{hold.explanation}</p>
                  </>
                )}
                <ol className="hold-steps hold-steps-row">
                  {holdSteps.map((who) => {
                    const open = hold.needs.includes(who as PayoutHold["needs"][number]);
                    const next = open && hold.needs[0] === who;
                    return (
                      <li key={who} className={open ? (next ? "hold-step hold-step-next" : "hold-step") : "hold-step hold-step-done"}>
                        <span className="hold-step-state">{open ? (next ? "Next" : "After that") : "Done"}</span>
                        {STEP_WORDS[who]}
                      </li>
                    );
                  })}
                </ol>

                {hold.needs[0] === "bank_details" && claim && payout.claim_state !== "PAYMENT_HELD" && (
                  <Waiting>Recording what happened.</Waiting>
                )}
                {hold.needs[0] === "bank_details" && claim && payout.claim_state === "PAYMENT_HELD" && (
                  <>
                    <h3>The corrected account</h3>
                    <BankDetails claimantName={claim.claimant.name} fill={fill} onlyCurrency={heldIn} submitLabel="Use this account for the replacement"
                      onSubmit={async (details) => {
                        setClaim(await setPayee(claimId, details));
                        setPayout(await getPayout(claimId));
                      }} />
                  </>
                )}
                {hold.needs[0] === "payer" && (
                  <p className="hold-wait">
                    Waiting for the holder to approve {refused ? `the corrected account, ending ${to}` : "the new terms"}.{" "}
                    <a href="/payer" target="_blank" rel="noreferrer">Open the holder's view</a>
                  </p>
                )}
                {!hold.ready && <Waiting>Working the plan out again on the new figures.</Waiting>}
                {hold.needs[0] === "claimant" && hold.ready && plan && (
                  <>
                    {busy ? (
                      <Waiting>Carrying on with the payment.</Waiting>
                    ) : (
                      <div className="actions">
                        <button type="button" className="primary" onClick={() => act(() => confirmPayout(claimId, plan.id))}>
                          I agree to {amount(plan.expected_local)}. Carry on
                        </button>
                      </div>
                    )}
                    <details className="fold">
                      <summary>{plan.replacement ? "The plan for the replacement" : "The plan, worked out again"}</summary>
                      <Plan plan={plan} />
                    </details>
                  </>
                )}
              </section>
            )}

            <MetalPanel claimId={claimId} refresh={`${payout.state}-${payout.steps?.length ?? 0}`} />

            {!hold && !payout.running && payout.state !== "PAID" && payout.state !== "FAILED" && (
              <div className="actions">
                <button type="button" className="secondary" onClick={() => act(() => resumePayout(claimId))} disabled={busy}>
                  Carry on with the payment
                </button>
              </div>
            )}

            {payout.state === "PAID" && transfer && (
              <section className="received">
                <div className="received-main">
                  <div>
                    <p className="panel-label">Paid into her account{to ? `, ending ${to}` : ""}</p>
                    <p className="received-amount">{amount(payout.received)}</p>
                  </div>
                  {payout.agreed_and_paid && (
                    <p className="agreed-paid">
                      Agreed {amount(payout.agreed_and_paid.agreed)}. Paid {amount(payout.agreed_and_paid.paid)}.
                    </p>
                  )}
                </div>
                <details className="fold">
                  <summary>Airwallex's transfer and why the amounts differ</summary>
                  {payout.agreed_and_paid && <p className="quiet">{payout.agreed_and_paid.note}</p>}
                  <dl className="facts">
                    <div>
                      <dt>Airwallex transfer id</dt>
                      <dd className="mono">{transfer.id}</dd>
                    </div>
                    <div>
                      <dt>Airwallex reference</dt>
                      <dd className="mono">{transfer.short_reference_id ?? "Not given"}</dd>
                    </div>
                    <div>
                      <dt>Airwallex payout fee</dt>
                      <dd>{payout.payout_fee ? amount(payout.payout_fee) : "Not reported"}</dd>
                    </div>
                  </dl>
                  <p className="quiet">
                    Airwallex reports the transfer as {transfer.status}, last updated {dateTime(transfer.updated_at)}.
                    {payout.watching_for_return && " Khutlisa keeps reading it, in case the bank sends it back."}
                  </p>
                </details>
              </section>
            )}

            {planCards.length > 0 && (
              <div className={refusals.length || hold ? "decision-row decision-row-small" : "decision-row"}>
                {planCards.map((c) => (
                  <DecisionCard key={c.kind} card={c} compact={Boolean(refusals.length || hold)} />
                ))}
              </div>
            )}

            {report.length > 0 && (
              <details className="fold agent-report" aria-label="Decided without asking">
                <summary>Everything decided without asking ({report.length}), in full</summary>
                <ol className="agent-lines">
                  {report.map((d, i) => (
                    <li key={i}>
                      <p className="agent-title">
                        <span className="agent-when">{clock(d.at)}</span> {d.title}
                        <span className="agent-rule">{d.rule_name}</span>
                      </p>
                      <p className="agent-text">{d.text}</p>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </>
        )}
        </div>
        )}
        {tab === "records" && (
          <div className="pane">
            {!anyRecord && <p className="quiet">Airwallex has no record for this claim yet.</p>}
            {books && books.lines.length > 0 && (
              <section className="books">
                <p className={books.balanced ? "books-statement books-balanced books-big" : "books-statement books-big"}>{books.balanced ? "Airwallex's own lines add up to zero." : books.statement}</p>
                <div className="books-sums">
                  {books.sums.map((s) => (
                    <div key={s.currency} className="books-sum">
                      <p className="panel-label">In {s.currency}</p>
                      <p className="books-figures">
                        <span>{exact(s.came_in, s.currency)} in</span>
                        <span>{exact(s.went_out, s.currency)} out</span>
                        <strong>{exact(s.left, s.currency)} left</strong>
                      </p>
                    </div>
                  ))}
                  {payout.state === "PAID" && payout.received && (
                    <div className="books-sum books-paid">
                      <p className="panel-label">Paid to the owner</p>
                      <p className="books-figures"><strong>{amount(payout.received)}</strong></p>
                    </div>
                  )}
                </div>
                <table className="ledger">
                  <thead>
                    <tr>
                      <th>For</th>
                      <th>Type</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Airwallex's note</th>
                      <th>Entry id</th>
                    </tr>
                  </thead>
                  <tbody>
                    {books.lines.map((row) => (
                      <tr key={row.id}>
                        <td>{row.part}</td>
                        <td>{row.type.replace(/_/g, " ").toLowerCase()}</td>
                        <td className="num">{exact(row.amount, row.currency)}</td>
                        <td>{row.status.toLowerCase()}</td>
                        <td>{row.description}</td>
                        <td className="mono">{row.id}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}
            {attempts.length > 0 && (
              <section className="attempts">
                <p className="panel-label">Earlier transfers for this claim</p>
                <ul className="plain-list">
                  {attempts.map((a) => (
                    <li key={a.transfer_id}>
                      Transfer <span className="mono">{a.transfer_id}</span> was {a.fate}. Airwallex reports it as {a.status} and booked{" "}
                      {amount(a.came_back)} back{a.fee_kept ? `, keeping its payout fee of ${amount(a.fee_kept)}` : ""}.
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {(payout.decisions ?? []).length > 0 && (
              <details className="fold">
                <summary>What changed, and what was decided, with times</summary>
                <ol className="events">
                  {(payout.decisions ?? []).map((d, i) => (
                    <li key={i}>
                      <span className="event-when">{dateTime(d.at)}</span>
                      <span>{d.by === "agent" ? "Decided without asking. " : ""}{d.text}</span>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
