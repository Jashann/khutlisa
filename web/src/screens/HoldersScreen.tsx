import { useEffect, useState } from "react";
import { getBookHolders, getHolders } from "../api";
import Masthead from "../components/Masthead";
import Waiting from "../components/Waiting";
import { count, money, plainPropertyType } from "../format";
import type { BookHolder, HolderRow, HoldersView } from "../types";

interface Props {
  onHome: () => void;
  onOwed?: () => void;
  /** Opens the whole book of one holder: the plan to pay everything it owes abroad. */
  onBook: (holder: string) => void;
}

type Order = "amount" | "properties" | "money" | "kind";

const dated = (iso: string) => {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? iso : when.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

/** For holders: the companies that reported the property, what they reported for owners abroad, and what
 *  California's law asks of them. Every figure is computed from California's file; nothing here is a customer. */
export default function HoldersScreen({ onHome, onBook }: Props) {
  const [view, setView] = useState<HoldersView | null>(null);
  const [problem, setProblem] = useState("");
  const [order, setOrder] = useState<Order>("amount");
  const [typed, setTyped] = useState("");
  const [matches, setMatches] = useState<BookHolder[] | null>(null);

  useEffect(() => {
    getHolders().then(setView).catch((e: Error) => setProblem(e.message));
  }, []);

  useEffect(() => {
    if (typed.trim().length < 2) {
      setMatches(null);
      return;
    }
    const timer = window.setTimeout(() => {
      getBookHolders(typed.trim()).then((h) => setMatches(h.matches)).catch(() => setMatches([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const head = <Masthead onHome={onHome} note="For holders: the companies that reported the property" />;
  if (!view) {
    return (
      <main className="flow onescreen holders">
        {head}
        <div className="flow-body flow-narrow">
          {problem ? <p className="notice">{problem}</p> : <div className="results-empty"><Waiting counted={false}>Reading the figures.</Waiting></div>}
        </div>
      </main>
    );
  }
  const f = view.figures;
  const short = view.in_short;
  const rows: HolderRow[] = order === "properties" ? f.by_properties : f.by_amount;
  const buyer = view.buyer;
  return (
    <main className="flow onescreen holders">
      {head}
      <div className="owed-body holders-body">
        <section className="owed-main">
          <h1>The money sits with holders first</h1>
          <p className="quiet owed-intro">The holder is the company that reported a property. It owed the money, and it can pay by bank transfer.</p>
          <div className="holder-figures">
            <div>
              <p className="holder-number">{count(f.holders_with_an_owner_abroad)}</p>
              <p className="holder-caption">holders reported property for an owner abroad</p>
            </div>
            <div>
              <p className="holder-number">{count(f.properties)}</p>
              <p className="holder-caption">properties</p>
            </div>
            <div>
              <p className="holder-number">{money(f.amount)}</p>
              <p className="holder-caption">in all. The ten largest holders account for {f.share_of_top_ten.amount_percent} percent</p>
            </div>
          </div>
          <div className="tabs" role="tablist" aria-label="Order of the list">
            <button type="button" role="tab" aria-selected={order === "amount"} className={order === "amount" ? "tab tab-on" : "tab"} onClick={() => setOrder("amount")}>
              Most dollars for owners abroad
            </button>
            <button type="button" role="tab" aria-selected={order === "properties"} className={order === "properties" ? "tab tab-on" : "tab"} onClick={() => setOrder("properties")}>
              Most properties
            </button>
            {f.kinds_of_money && (
              <button type="button" role="tab" aria-selected={order === "money"} className={order === "money" ? "tab tab-on" : "tab"} onClick={() => setOrder("money")}>
                By kind of money
              </button>
            )}
            {f.kinds_of_holder && (
              <button type="button" role="tab" aria-selected={order === "kind"} className={order === "kind" ? "tab tab-on" : "tab"} onClick={() => setOrder("kind")}>
                By kind of holder
              </button>
            )}
            <label className="holder-type">
              <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type a holder's name to open its book" autoComplete="off" aria-label="Type a holder's name" />
            </label>
          </div>
          {matches !== null ? (
            <ol className="owed-list holder-list" aria-live="polite">
              {matches.length === 0 && <li><span className="owed-by">No holder of that name can be opened. A holder whose name could be a person's is counted and never listed.</span></li>}
              {matches.map((h) => (
                <li key={h.key}>
                  <button type="button" className="holder-open owed-name" onClick={() => onBook(h.key)}>{h.name}</button>
                  <span className="owed-amount">{money(h.amount)}</span>
                  <span className="owed-by">{count(h.properties)} {h.properties === 1 ? "property" : "properties"} for owners in {h.countries} {h.countries === 1 ? "country" : "countries"}. Open its book.</span>
                </li>
              ))}
            </ol>
          ) : order === "money" && f.kinds_of_money ? (
            <ol className="owed-list holder-list">
              {f.kinds_of_money.map((k) => (
                <li key={k.key}>
                  <span className="owed-name">{k.label}</span>
                  <span className="owed-amount">{money(k.amount)}</span>
                  <span className="owed-by">
                    {count(k.properties)} properties for owners abroad
                    {k.unverified_properties > 0 && `. ${money(k.unverified_amount)} of it under old numeric codes the Controller's list does not describe (unverified)`}
                  </span>
                </li>
              ))}
            </ol>
          ) : order === "kind" && f.kinds_of_holder ? (
            <ol className="owed-list holder-list">
              {f.wages && (
                <li>
                  <span className="owed-name">Employers and payroll companies, by what they reported</span>
                  <span className="owed-amount">{money(f.wages.amount)}</span>
                  <span className="owed-by">{count(f.wages.holders)} holders reported wages for an owner abroad: {count(f.wages.properties)} properties</span>
                </li>
              )}
              {f.kinds_of_holder.map((k) => (
                <li key={k.key}>
                  <span className="owed-name">{k.label}</span>
                  <span className="owed-amount">{money(k.amount)}</span>
                  <span className="owed-by">
                    {count(k.holders)} holders, {count(k.properties)} properties{k.top.length > 0 && `. The largest: ${k.top.map((t) => t.name).join("; ")}`}
                    {k.key === "unclassified" && ". The name does not say what kind of organisation it is, and none is guessed"}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <ol className="owed-list holder-list">
              {rows.map((h, i) => (
                <li key={h.name}>
                  <button type="button" className="holder-open owed-name" onClick={() => onBook(h.name)} title="Open this holder's book">
                    <span className="holder-rank">{i + 1}</span>{h.name}
                  </button>
                  <span className="owed-amount">{money(h.amount)}</span>
                  <span className="owed-by">{count(h.properties)} {h.properties === 1 ? "property" : "properties"} for owners abroad. Open its book.</span>
                </li>
              ))}
            </ol>
          )}
          <p className="quiet holder-source">
            Computed from {f.source.replace("California State Controller, unclaimed property records, ", "California's ")} on {dated(f.generated_at)}.
            {f.kinds_source && (order === "money" || order === "kind") && (
              <> Kinds of money follow <a href={f.kinds_source.url} target="_blank" rel="noreferrer">the Controller's list of property type codes</a>.</>
            )}
          </p>
        </section>

        <aside className="owed-side holders-side">
          {buyer && (
            <div className="panel buyer">
              <p className="panel-label">Who can pay, and why it would</p>
              <p className="buyer-who">{buyer.who}</p>
              <ul className="buyer-why">
                {buyer.why.map((w) => (
                  <li key={w.title}>
                    <a href={w.url} target="_blank" rel="noreferrer" title={`${w.text} ${w.source}`}>{w.title}</a>
                  </li>
                ))}
              </ul>
              <p className="quiet buyer-note">{buyer.not_stated}</p>
            </div>
          )}
          {short && (
            <div className="panel law-short">
              <p className="panel-label">The law in a sentence</p>
              <p className="law-pay">{short.pay}</p>
              <p className="law-days">
                <span className="law-days-number">{count(short.days_to_handover)}</span>
                <span className="law-days-words">days to the next handover, {short.handover_words}</span>
              </p>
              <p className="law-line">{short.schedule}</p>
              <p className="law-line law-cheque">{short.cheque}</p>
              <p className="law-sources">
                Sources:{" "}
                {short.sources.map((src, i) => (
                  <span key={src.url}>
                    {i > 0 && ", "}
                    <a href={src.url} target="_blank" rel="noreferrer">{src.label}</a>
                  </span>
                ))}
              </p>
            </div>
          )}
          <div className="actions holders-actions">
            <button type="button" className="primary primary-small" onClick={() => onBook(f.by_amount[0]?.name ?? "")}>Plan a whole book</button>
            <a className="secondary secondary-link" href="/payer">Open the holder's view</a>
            <a className="secondary secondary-flat holder-list-link" href="/#list">Bring your own list</a>
          </div>
          <details className="panel holder-detail">
            <summary>Sources and detail</summary>
            {buyer && (
              <>
                <p className="panel-label">What the law already asks of a holder</p>
                <ul className="holder-rules">
                  {buyer.why.map((w) => (
                    <li key={w.title}>
                      <p className="holder-rule-title">{w.title}</p>
                      <p>{w.text}</p>
                      <p className="quiet">{w.source}. <a href={w.url} target="_blank" rel="noreferrer">Open the source</a></p>
                    </li>
                  ))}
                </ul>
                <p className="quiet">{buyer.already_with_the_state}</p>
              </>
            )}
            <p className="panel-label">How a holder would use it</p>
            <ol className="holder-steps">
              {view.how_it_would_work.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ol>
            <p className="panel-label">{view.proposed_pricing.label}</p>
            <p>{view.proposed_pricing.text}</p>
            <p className="panel-label">What kind of money it is</p>
            <ul className="owed-ranking holder-kinds">
              {f.property_types.slice(0, 6).map((k) => (
                <li key={k.type}>
                  <span>{plainPropertyType(k.type)}</span>
                  <span className="rank-amount">{money(k.amount)}</span>
                </li>
              ))}
            </ul>
            <p className="panel-label">What California's law asks</p>
            <ul className="holder-rules">
              {view.law.map((rule) => (
                <li key={rule.title}>
                  <p className="holder-rule-title">
                    {rule.title}
                    <span className={rule.mark === "verified" ? "mark mark-verified" : "mark mark-reading"}>
                      {rule.mark === "verified" ? "Read at the source" : "Our reading"}
                    </span>
                  </p>
                  <p>{rule.text}</p>
                  <p className="quiet">
                    {rule.source}. <a href={rule.url} target="_blank" rel="noreferrer">Open the source</a>
                  </p>
                </li>
              ))}
            </ul>
            <p className="panel-label">How the figures are counted</p>
            <p className="quiet">{view.rule}</p>
          </details>
        </aside>
      </div>
    </main>
  );
}
