import { useEffect, useRef, useState } from "react";
import { LockedError, getBook, getBookHolders, makeBatch, payerKey, setPayerKey } from "../api";
import DecisionCard from "../components/DecisionCard";
import Masthead from "../components/Masthead";
import Waiting from "../components/Waiting";
import { count, money } from "../format";
import type { BookCorridor, BookHolder, BookInputs, BookPlan } from "../types";

interface Props {
  holder: string | null;
  onHome: () => void;
  onHolders: () => void;
  onChoose: (key: string) => void;
  onBatch: (id: string) => void;
}

type Tab = "corridors" | "order" | "funding";

const dollars = (n: number) => money(n, "USD", n < 1000);
const local = (amount: number, currency: string) =>
  `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(amount)} ${currency}`;
const day = (iso: string | null | undefined) => {
  const when = iso ? new Date(iso) : null;
  // A date without a time is a day, not a moment: it is shown as written, whatever the reader's time zone.
  return when && !Number.isNaN(when.getTime()) ? when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "";
};
const plusDays = (days: number) => new Date(Date.now() + days * 86400000).toISOString().slice(0, 10);

/** One corridor in a line of short sentences. */
function detail(c: BookCorridor): string {
  const parts = [`${count(c.owners)} ${c.owners === 1 ? "property" : "properties"}`];
  if (c.route && c.fee) parts.push(`${c.scheme}, ${c.pay_currency}`, `Fee ${dollars(Number(c.fee.usd))} a payment (${c.fee.basis === "observed" ? "seen on the sandbox" : "an estimate"})`);
  if (c.route && c.owners_receive)
    parts.push(`Owners receive ${c.owners_receive.currency === "USD" ? dollars(c.owners_receive.amount) : local(c.owners_receive.amount, c.owners_receive.currency)}`);
  if (c.swift.owners > 0 && c.route === "LOCAL") parts.push(`${count(c.swift.owners)} over the rail's limit go by SWIFT`);
  if (c.too_small.owners > 0) parts.push(`${count(c.too_small.owners)} smaller than their fees`);
  if (!c.route && c.why_unpayable) parts.push(c.why_unpayable);
  if (c.route === "SWIFT" && c.why_not_local) parts.push(c.why_not_local);
  if (c.route && !c.in_time) parts.push(`Too close to the handover: it needs ${c.needs_days} days`);
  return parts.map((p) => p.replace(/\.$/, "")).join(". ") + ".";
}

function Route({ row }: { row: BookCorridor }) {
  const kind = row.route === "LOCAL" ? "route-local" : row.route === "SWIFT" ? "route-swift" : "route-none";
  return <span className={`route ${kind}`}>{row.route ? row.route_words : "Not payable by transfer"}</span>;
}

/** The whole book of one holder: a plan to pay everything it owes abroad, recomputed as the limits change. */
export default function BookScreen({ holder, onHome, onHolders, onChoose, onBatch }: Props) {
  const [holders, setHolders] = useState<BookHolder[]>([]);
  const [typed, setTyped] = useState("");
  const [matches, setMatches] = useState<BookHolder[]>([]);
  const [plan, setPlan] = useState<BookPlan | null>(null);
  const [inputs, setInputs] = useState<Partial<BookInputs>>({});
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("corridors");
  const [asking, setAsking] = useState(false);
  const [key, setKey] = useState("");
  const [batchProblem, setBatchProblem] = useState("");
  const [making, setMaking] = useState(false);
  const latest = useRef(0);

  useEffect(() => {
    getBookHolders()
      .then((h) => {
        setHolders(h.top);
        if (!holder && h.top.length) onChoose(h.top[0].key);
      })
      .catch((e: Error) => setProblem(e.message));
  }, []);

  useEffect(() => {
    if (typed.trim().length < 2) {
      setMatches([]);
      return;
    }
    const timer = window.setTimeout(() => {
      getBookHolders(typed.trim()).then((h) => setMatches(h.matches)).catch(() => setMatches([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [typed]);

  // A new holder starts from the holder's saved limits.
  useEffect(() => {
    setInputs({});
    setPlan(null);
  }, [holder]);

  useEffect(() => {
    if (!holder) return;
    const mine = ++latest.current;
    setBusy(true);
    const timer = window.setTimeout(() => {
      getBook(holder, inputs)
        .then((p) => {
          if (mine !== latest.current) return;
          setPlan(p);
          setProblem("");
        })
        .catch((e: Error) => mine === latest.current && setProblem(e.message))
        .finally(() => mine === latest.current && setBusy(false));
    }, plan ? 200 : 0);
    return () => window.clearTimeout(timer);
  }, [holder, inputs]);

  const run = async () => {
    if (!plan) return;
    setBatchProblem("");
    setMaking(true);
    try {
      const made = await makeBatch(plan.holder.key, plan.inputs);
      onBatch(made.batch_id);
    } catch (e) {
      if (e instanceof LockedError) {
        setPayerKey("");
        setAsking(true);
        setBatchProblem(e.message || "The holder's key is missing or wrong.");
      } else setBatchProblem((e as Error).message);
    } finally {
      setMaking(false);
    }
  };

  const head = <Masthead onHome={onHome} note="The whole book: everything one holder owes to owners abroad" />;
  if (!plan) {
    return (
      <main className="flow onescreen book">
        {head}
        <div className="flow-body flow-narrow">
          {problem ? <p className="notice">{problem}</p> : <div className="results-empty"><Waiting counted={false}>Working out the plan.</Waiting></div>}
        </div>
      </main>
    );
  }

  const t = plan.totals;
  const now = plan.inputs;
  const base = plan.baseline.inputs;
  const set = (patch: Partial<BookInputs>) => setInputs((old) => ({ ...now, ...old, ...patch }));
  const widest = Math.max(...plan.corridors.map((c) => c.usd), 1);
  const list = [...holders, ...matches.filter((m) => !holders.some((h) => h.key === m.key))];
  const known = list.some((h) => h.key === plan.holder.key) ? list : [plan.holder, ...list];

  return (
    <main className="flow onescreen book">
      {head}
      <div className="book-body">
        <section className="book-left">
          <h1 className="book-holder">{plan.holder.name}</h1>
          <p className="book-size">
            <strong>{dollars(t.usd)}</strong> in {count(t.owners)} properties for owners in {count(t.countries)} countries
          </p>
          <p className="book-statement">{plan.statement}</p>

          <div className="book-pick">
            <label className="field">
              <span>Choose a holder</span>
              <select value={plan.holder.key} onChange={(e) => onChoose(e.target.value)} aria-label="Choose a holder">
                {known.map((h) => (
                  <option key={h.key} value={h.key}>{h.name}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>or type a holder's name</span>
              <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="For example: herbalife" autoComplete="off" />
            </label>
            {typed.trim().length >= 2 && (
              <ul className="book-matches" aria-live="polite">
                {matches.length === 0 && <li className="quiet">No holder of that name can be opened.</li>}
                {matches.slice(0, 5).map((m) => (
                  <li key={m.key}>
                    <button type="button" className="book-match" onClick={() => { onChoose(m.key); setTyped(""); }}>
                      <span>{m.name}</span>
                      <span className="rank-amount">{dollars(m.amount)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel book-controls" aria-label="The holder's limits">
            <p className="panel-label book-controls-head">
              Change a limit
              <button type="button" className="book-reset" onClick={() => setInputs({})}>back to the saved limits</button>
            </p>
            <label className="book-control">
              <span>Small-claim line: below it the holder bears the fees</span>
              <span className="book-control-row">
                <input type="range" min={0} max={2000} step={50} value={Number(now.small_claim_usd)} aria-label="Small-claim line"
                  onChange={(e) => set({ small_claim_usd: e.target.value })} />
                <strong>{dollars(Number(now.small_claim_usd))}</strong>
              </span>
            </label>
            <label className="book-control">
              <span>Tolerance: less than agreed, without asking about the amount</span>
              <span className="book-control-row">
                <input type="range" min={0} max={5} step={0.1} value={Number(now.tolerance_percent)} aria-label="Tolerance"
                  onChange={(e) => set({ tolerance_percent: e.target.value })} />
                <strong>{Number(now.tolerance_percent)}%</strong>
              </span>
            </label>
            <label className="book-control">
              <span>Handover date: the day the property goes to the State</span>
              <span className="book-control-row">
                <input type="date" value={now.handover_date} aria-label="Handover date" onChange={(e) => e.target.value && set({ handover_date: e.target.value })} />
                <strong>{count(plan.days_left)} days</strong>
              </span>
            </label>
            <div className="book-quick">
              <button type="button" className="tab" onClick={() => set({ handover_date: base.handover_date })}>{day(base.handover_date)}</button>
              <button type="button" className="tab" onClick={() => set({ handover_date: plusDays(34) })}>In 34 days</button>
              <button type="button" className="tab" onClick={() => set({ handover_date: plusDays(31) })}>In 31 days</button>
            </div>
          </div>

          {plan.changes.length > 0 && (
            <div className="panel book-changes" aria-live="polite">
              <p className="panel-label">What that changed</p>
              <ul>
                {plan.changes.slice(1).map((c) => (
                  <li key={c.what}>
                    <span>{c.what}</span>
                    <span className="book-change-figures">
                      {c.before && <span className="book-before">{c.before}</span>}
                      <strong>{c.after}</strong>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section className="book-mid">
          <div className="book-totals">
            <div className="book-total total-local">
              <p className="book-number">{dollars(t.local.usd)}</p>
              <p className="book-caption">by local rails, {count(t.local.owners)} owners in {t.local.countries} countries</p>
            </div>
            <div className="book-total total-swift">
              <p className="book-number">{dollars(t.swift.usd)}</p>
              <p className="book-caption">by SWIFT, {count(t.swift.owners)} owners in {t.swift.countries} countries</p>
            </div>
            <div className="book-total total-none">
              <p className="book-number">{dollars(t.unpayable.usd)}</p>
              <p className="book-caption">not payable by transfer: stays with the State process</p>
            </div>
            <div className="book-total">
              <p className="book-number">{dollars(t.cost.usd)}</p>
              <p className="book-caption">in fees, {t.cost.percent}% of {dollars(t.planned.usd)} paid in time to {count(t.planned.owners)} owners</p>
            </div>
          </div>

          <div className="tabs" role="tablist" aria-label="Parts of the plan">
            <button type="button" role="tab" aria-selected={tab === "corridors"} className={tab === "corridors" ? "tab tab-on" : "tab"} onClick={() => setTab("corridors")}>
              Corridors ({plan.corridors.length})
            </button>
            <button type="button" role="tab" aria-selected={tab === "order"} className={tab === "order" ? "tab tab-on" : "tab"} onClick={() => setTab("order")}>
              Order of work ({plan.order.work.length})
            </button>
            <button type="button" role="tab" aria-selected={tab === "funding"} className={tab === "funding" ? "tab tab-on" : "tab"} onClick={() => setTab("funding")}>
              Funding ({plan.funding.currencies.length} currencies)
            </button>
            {busy && <span className="book-busy">working it out</span>}
          </div>

          {tab === "corridors" && (
            <ol className="book-list" aria-label="Corridors">
              {plan.corridors.map((c, i) => (
                <li key={c.country} className={c.in_time || !c.route ? "book-row" : "book-row book-row-late"}>
                  <span className="book-rank">{i + 1}</span>
                  <span className="book-country">{c.name}</span>
                  <Route row={c} />
                  <span className="book-usd">{dollars(c.usd)}</span>
                  <span className="book-bar"><span style={{ width: `${Math.max((c.usd / widest) * 100, 0.6)}%` }} className={c.route === "LOCAL" ? "bar-local" : c.route === "SWIFT" ? "bar-swift" : "bar-none"} /></span>
                  <span className="book-detail">{detail(c)}</span>
                </li>
              ))}
            </ol>
          )}

          {tab === "order" && (
            <ol className="book-list" aria-label="Order of work">
              {plan.order.work.length === 0 && <li className="book-row"><span className="book-detail">No corridor can finish before the handover. The whole book stays with the State process.</span></li>}
              {plan.order.work.map((c) => (
                <li key={c.country} className="book-row">
                  <span className="book-rank">{c.rank}</span>
                  <span className="book-country">{c.name}</span>
                  <span className={c.route === "SWIFT" ? "route route-swift" : "route route-local"}>{c.route}</span>
                  <span className="book-usd">{dollars(c.usd_per_day)} a day</span>
                  <span className="book-detail">
                    {dollars(c.usd)} for {count(c.owners)} owners. Needs {c.needs_days} days: {plan.order.document_days} for the owner's documents, then {c.rail_days} on {c.scheme}
                    {c.rail_basis === "estimate" ? " (an estimate)" : ""}. Start by {c.start_by_words}; {c.spare_days} days to spare.
                  </span>
                </li>
              ))}
              {plan.order.dropped.map((c) => (
                <li key={c.country} className="book-row book-row-late">
                  <span className="book-rank">x</span>
                  <span className="book-country">{c.name}</span>
                  <span className="route route-none">Too close</span>
                  <span className="book-usd">{dollars(c.usd)}</span>
                  <span className="book-detail">Needs {c.needs_days} days and {count(plan.days_left)} are left. Released to the State process with the Remit Report.</span>
                </li>
              ))}
            </ol>
          )}

          {tab === "funding" && (
            <ol className="book-list" aria-label="Funding">
              <li className="book-row book-row-head">
                <span className="book-detail">
                  The holder funds <strong>{money(plan.funding.holder_funds_usd, "USD", true)}</strong> in US dollars. {plan.funding.ahead_of_approvals}
                </span>
              </li>
              {plan.funding.currencies.map((c) => (
                <li key={c.currency} className="book-row">
                  <span className="book-rank">{c.currency}</span>
                  <span className="book-country">{dollars(c.holder_sends)}</span>
                  <span className={c.mode === "batch" ? "route route-local" : c.mode === "none" ? "route route-none" : "route route-swift"}>
                    {c.mode === "batch" ? "Convert once" : c.mode === "none" ? "No conversion" : "Each payment"}
                  </span>
                  <span className="book-usd">{count(c.payments)} payments</span>
                  <span className="book-detail">
                    {c.mode_words}
                    {c.sizes && c.sizes.length > 0 && <> Quoted at {c.sizes.length} sizes: {c.rate_depends_on_size ? "the spread differs by size" : `the same spread, ${c.sizes[0].spread_percent.toFixed(2)}% from the mid rate`}.</>}
                    {c.mode === "batch" && <> Saves {money(c.saving_usd, "USD", true)} and {count(c.payments - 1)} conversions.</>}
                    {c.lock && <> A one-hour lock costs {c.lock.percent.toFixed(2)}% against a one-minute quote.</>}
                    {c.round_trip && <> Turning unspent money back costs {c.round_trip.percent.toFixed(2)}%.</>}
                  </span>
                </li>
              ))}
            </ol>
          )}

          <p className="book-source">
            Routes, rates and quotes: asked of Airwallex's sandbox on {day(plan.discovered_at)}. Fees seen on the sandbox in {t.observed_fee_corridors} corridors, estimated from{" "}
            <a href={plan.sources.fee_schedule.url} target="_blank" rel="noreferrer">Airwallex's published prices</a> in {t.estimated_fee_corridors}. Rail times from{" "}
            <a href={plan.sources.payout_guides.url} target="_blank" rel="noreferrer">its country guides</a>.
          </p>
        </section>

        <aside className="book-cards" aria-label="What the agent decided">
          <div className="book-run">
            <button type="button" className="primary primary-small" onClick={() => (payerKey() ? void run() : setAsking(true))} disabled={making || plan.slice.length < 2}>
              {making ? "Writing the batch" : "Run a slice on the sandbox"}
            </button>
            <button type="button" className="secondary secondary-flat" onClick={onHolders}>For holders</button>
            <p className="quiet book-run-note">
              {plan.slice.length < 2 ? "This plan works too few corridors for a demonstration batch." : `${plan.slice.length} demonstration owners in ${plan.slice.length} countries. Invented people; no real owner is paid.`}
            </p>
            {asking && (
              <form className="book-key" onSubmit={(e) => { e.preventDefault(); setPayerKey(key.trim()); setAsking(false); void run(); }}>
                <label className="field">
                  <span>Holder's key</span>
                  <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoFocus aria-label="Holder's key" />
                </label>
                <button type="submit" className="secondary">Open</button>
              </form>
            )}
            {batchProblem && <p className="notice">{batchProblem}</p>}
          </div>
          <div className="book-card-list">
            {plan.cards.map((card) => (
              <DecisionCard key={card.kind} card={card} compact />
            ))}
          </div>
        </aside>
      </div>
    </main>
  );
}
