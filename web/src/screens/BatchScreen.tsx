import { useEffect, useState } from "react";
import { LockedError, approveBatch, batchItemAct, getBatch, payerKey, resumeBatch, setPayerKey } from "../api";
import Masthead from "../components/Masthead";
import Waiting from "../components/Waiting";
import { exact, money } from "../format";
import type { BatchItem, BatchView } from "../types";

interface Props {
  batchId: string;
  onHome: () => void;
  onBook: (holder: string) => void;
}

const usd = (text: string | null | undefined) => (text ? money(Number(text), "USD", true) : "");
/** An amount in its own currency; a currency with no minor unit (the yen) is shown without decimals. */
const WHOLE = new Set(["JPY", "KRW", "VND", "CLP", "ISK", "PYG", "UGX", "RWF", "XOF", "XAF", "XPF"]);
const own = (amount: string | number, currency: string) =>
  WHOLE.has(currency) ? `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(Number(amount))} ${currency}` : exact(amount, currency);

function tone(item: BatchItem): string {
  if (item.state === "PAID") return "item-paid";
  if (item.needs.length > 0) return "item-stopped";
  if (item.attempts.length > 0) return "item-again";
  return item.state ? "item-moving" : "item-waiting";
}

function Item({ item, busy, act }: { item: BatchItem; busy: boolean; act: (n: number, what: "account" | "approve" | "agree") => void }) {
  const refusal = item.cards[item.cards.length - 1];
  const last = item.attempts[item.attempts.length - 1];
  return (
    <li className={`batch-item ${tone(item)}`} data-country={item.country}>
      <div className="batch-item-head">
        <p className="batch-owner">{item.owner.name}</p>
        <p className="batch-where">{item.owner.city ? `${item.owner.city}, ` : ""}{item.owner.country_name}</p>
      </div>
      <p className="batch-state"><span className="batch-dot" aria-hidden="true" />{item.state_words}</p>
      <p className="batch-amount">
        {item.paid ? own(item.paid.amount, item.paid.currency) : item.expected_local ? `about ${own(item.expected_local.amount, item.expected_local.currency)}` : usd(item.claim_usd)}
      </p>
      <p className="batch-facts">
        Owed {usd(item.claim_usd)}. {item.method === "SWIFT" ? "SWIFT" : item.scheme ?? "Local rails"}, {item.currency}. Account ending {item.account_last4}.{" "}
        {item.fees_borne_by === "holder" ? "The holder bears the fees." : "Fees come out of the claim."}
      </p>
      {last && refusal && (
        <p className="batch-refusal">
          The bank refused the account ending {last.account_last4}. {refusal.did}
        </p>
      )}
      {item.needs[0] === "bank_details" && (
        <button type="button" className="secondary batch-act" disabled={busy} onClick={() => act(item.n, "account")}>
          {item.claim_id ? "Use the account the claimant has given since" : "Demonstration owner: give the corrected account"}
        </button>
      )}
      {item.claim_id && <a className="batch-claim-link" href={`/payer#claim-${item.claim_id}`}>Its claim in the queue</a>}
      {item.needs[0] === "payer" && (
        <button type="button" className="secondary batch-act" disabled={busy} onClick={() => act(item.n, "approve")}>
          Holder: approve the account ending {item.account_last4}
        </button>
      )}
      {item.needs.length === 1 && item.needs[0] === "claimant" && (
        <button type="button" className="secondary batch-act" disabled={busy} onClick={() => act(item.n, "agree")}>
          Demonstration owner: agree to the smaller amount
        </button>
      )}
    </li>
  );
}

/** A batch running on the Airwallex sandbox: each payment's state as it moves, and at the end the whole batch
 *  against Airwallex's own ledger, with the planned cost beside the actual cost. */
export default function BatchScreen({ batchId, onHome, onBook }: Props) {
  const [view, setView] = useState<BatchView | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [unlocked, setUnlocked] = useState(() => payerKey() !== "");
  const [key, setKey] = useState("");

  const failed = (e: unknown) => {
    if (e instanceof LockedError) {
      setPayerKey("");
      setUnlocked(false);
      setProblem(e.message || "The holder's key is missing or wrong.");
    } else setProblem((e as Error).message);
  };
  const load = () => getBatch(batchId).then((v) => { setView(v); setProblem(""); }).catch(failed);

  useEffect(() => {
    if (!unlocked) return;
    void load();
    const timer = window.setInterval(load, 1500);
    return () => window.clearInterval(timer);
  }, [unlocked, batchId]);

  const doing = async (work: () => Promise<BatchView>) => {
    setBusy(true);
    try {
      setView(await work());
      setProblem("");
    } catch (e) {
      failed(e);
    } finally {
      setBusy(false);
    }
  };

  const head = <Masthead onHome={onHome} note="A batch on the Airwallex sandbox" />;
  if (!unlocked) {
    return (
      <main className="flow onescreen batch">
        {head}
        <div className="flow-body flow-narrow">
          <h1>The holder's view is locked</h1>
          <p className="quiet">A batch is decided by the holder. Type the holder's key to open it.</p>
          <form className="book-key" onSubmit={(e) => { e.preventDefault(); setPayerKey(key.trim()); setUnlocked(true); }}>
            <label className="field">
              <span>Holder's key</span>
              <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoFocus aria-label="Holder's key" />
            </label>
            <button type="submit" className="primary primary-small">Open the batch</button>
          </form>
          {problem && <p className="notice">{problem}</p>}
        </div>
      </main>
    );
  }
  if (!view) {
    return (
      <main className="flow onescreen batch">
        {head}
        <div className="flow-body flow-narrow">
          {problem ? <p className="notice">{problem}</p> : <div className="results-empty"><Waiting counted={false}>Reading the batch.</Waiting></div>}
        </div>
      </main>
    );
  }

  const books = view.reconciliation;
  const planned = view.state === "PLANNED";
  const done = view.state === "DONE";
  const stopped = view.state === "STOPPED";
  const converted = view.funding.filter((f) => f.mode === "batch");
  const inside = view.funding.filter((f) => f.mode === "each");
  const fromQueue = view.plan.source === "queue";
  return (
    <main className="flow onescreen batch">
      {head}
      <div className="batch-body">
        <section className="batch-left">
          <h1 className="book-holder">{fromQueue ? "Approved claims, paid together" : `A slice of the plan for ${view.holder.name}`}</h1>
          <p className="book-statement">{view.statement}</p>

          <div className={done ? "batch-progress batch-progress-done" : "batch-progress"}>
            <p className="batch-count">{view.paid} <span>of {view.payments} paid</span></p>
            <p className="batch-words">{view.state_words}{view.waiting_for_people.length > 0 && !done ? `. ${view.waiting_for_people.length} waiting for a person` : ""}</p>
          </div>

          {planned && (
            <div className="panel batch-approve">
              <p className="panel-label">What an approval would cover</p>
              <ul className="terms-tiles batch-tiles">
                <li><span>Payments</span><strong>{view.payments}</strong><em>each owner, amount and account as listed</em></li>
                <li><span>To fund</span><strong>{usd(view.plan.holder_funds_usd)}</strong><em>for claims of {usd(view.plan.claims_usd)}</em></li>
                <li><span>Funding</span><strong>{converted.length} converted once</strong><em>{inside.length} inside each transfer</em></li>
                <li><span>Limits</span><strong>{view.rules.tolerance_percent}%</strong><em>small-claim line {usd(view.rules.small_claim_usd)}</em></li>
              </ul>
              <div className="actions">
                <button type="button" className="primary primary-small" disabled={busy} onClick={() => void doing(() => approveBatch(view.batch_id))}>
                  Approve these terms and start
                </button>
              </div>
            </div>
          )}

          {!planned && (
            <div className="panel batch-funding">
              <p className="panel-label">The funding</p>
              <p className="batch-line">
                {view.deposit.amount ? <>The holder's <strong>{usd(view.deposit.amount)}</strong> arrived. Airwallex's fee: <strong>{usd(view.deposit.fee)}</strong>.</> : "Waiting for the holder's US dollars."}
              </p>
              {converted.map((f) => (
                <p key={f.currency} className="batch-line">
                  {f.buy ? <>Converted once: {usd(f.sell_usd)} into <strong>{own(f.buy, f.currency)}</strong> for {f.payments} {f.payments === 1 ? "payment" : "payments"}.</> : <>{f.currency}: to be converted once for the batch.</>}
                </p>
              ))}
              {inside.length > 0 && <p className="batch-line quiet">{inside.map((f) => f.currency).join(", ")}: converted inside each transfer, because Airwallex does not hold {inside.length === 1 ? "it" : "them"} for this account.</p>}
            </div>
          )}

          {!planned && (
            <div className={books.balanced ? "panel batch-books batch-books-zero" : "panel batch-books"}>
              <p className="panel-label">The whole batch against Airwallex's ledger</p>
              <p className="books-big">
                {books.balanced ? "Every currency adds up to zero" : books.all_paid ? "Paid, and not yet at zero" : `${books.rows} lines so far`}
              </p>
              <ul className="batch-sums">
                {books.sums.map((s) => (
                  <li key={s.currency}>
                    <span className="batch-cur">{s.currency}</span>
                    <span>in {own(s.came_in, s.currency)}</span>
                    <span>out {own(s.went_out, s.currency)}</span>
                    <strong className={Number(s.left) === 0 ? "sum-zero" : "sum-open"}>left {own(s.left, s.currency)}</strong>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!planned && (
            <div className="panel batch-costs">
              <p className="panel-label">Planned cost beside actual cost</p>
              <div className="batch-cost-row">
                <div><span>Planned</span><strong>{usd(view.costs.planned.usd)}</strong><em>{view.costs.planned.transfers} transfers</em></div>
                <div><span>Booked by Airwallex</span><strong>{usd(view.costs.actual.usd)}</strong><em>{view.costs.actual.transfers} transfers</em></div>
                <div><span>Difference</span><strong>{usd(view.costs.difference_usd)}</strong><em>a refusal costs a second fee</em></div>
              </div>
            </div>
          )}

          {(problem || view.problem) && <p className="notice">{problem || view.problem}</p>}
          <div className="actions batch-actions">
            {fromQueue
              ? <a className="secondary secondary-flat secondary-link" href="/payer">Back to the queue</a>
              : <button type="button" className="secondary secondary-flat" onClick={() => onBook(view.holder.key)}>Back to the plan</button>}
            {!planned && !done && !stopped && !view.running && view.waiting_for_people.length === 0 && (
              <button type="button" className="secondary" disabled={busy} onClick={() => void doing(() => resumeBatch(view.batch_id))}>Carry on</button>
            )}
          </div>
        </section>

        <section className="batch-right">
          <ul className="batch-items" aria-label="Payments">
            {view.items.map((item) => (
              <Item key={item.n} item={item} busy={busy} act={(n, what) => void doing(() => batchItemAct(view.batch_id, n, what))} />
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
