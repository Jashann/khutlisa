import { useEffect, useMemo, useState, type ReactNode } from "react";
import { getNotable, search } from "../api";
import Globe from "../components/Globe";
import SiteNav from "../components/SiteNav";
import { useDemo } from "../demo";
import { count, money, quick } from "../format";
import type { NotableOrganisation, NotableSet, SearchResult, Totals } from "../types";

const RUN_UP = 2.4;       // seconds the counter takes to reach the real total
// When each part of the opening comes in, in seconds after the totals arrive. The whole point is made in ten.
const AT = { whole: 1.6, abroad: 2.8, search: 5.4, cheque: 6.4, does: 7.4, actions: 8.4 };

function useRunUp(target: number, run: number, still: boolean, delay = 0): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (still) {
      setValue(target);
      return;
    }
    let frame = 0;
    const started = performance.now() + delay * 1000;
    const tick = (now: number) => {
      const x = Math.min(Math.max((now - started) / 1000 / RUN_UP, 0), 1);
      setValue(target * (1 - Math.pow(1 - x, 4)));
      if (x < 1) frame = requestAnimationFrame(tick);
    };
    setValue(0);
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, run, still, delay]);
  return value;
}

interface Props {
  totals: Totals | null;
  problem: string;
  onBegin: () => void;
  onOwed: () => void;
  onHolders: () => void;
}

export default function Opening({ totals, problem, onBegin, onOwed, onHolders }: Props) {
  const [run, setRun] = useState(0);
  const still = useMemo(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);
  const amount = useRunUp(totals?.abroad_amount ?? 0, run, still, AT.abroad);
  const properties = useRunUp(totals?.abroad_properties ?? 0, run, still, AT.abroad);
  const { person } = useDemo();
  const [live, setLive] = useState<SearchResult | null>(null);
  const [liveProblem, setLiveProblem] = useState(false);
  const [notable, setNotable] = useState<NotableSet | null>(null);
  const [clock, setClock] = useState(still ? 99 : 0);

  useEffect(() => {
    getNotable().then(setNotable).catch(() => setNotable(null));
  }, []);

  // One real search, made as the screen opens: the demonstration person's names over every owner record. The
  // server times it and the line below repeats the server's own figure.
  useEffect(() => {
    if (!person) return;
    const names = person.claimant.name.split(/\s+/);
    setLive(null);
    setLiveProblem(false);
    search({ given_names: names.slice(0, 2), family_names: names.slice(2), places: [], employers: [], current_country: person.claimant.country })
      .then(setLive)
      .catch(() => setLiveProblem(true));
  }, [person, run]);

  useEffect(() => {
    if (!totals || still) return;
    setClock(0);
    const started = performance.now();
    const timer = window.setInterval(() => setClock((performance.now() - started) / 1000), 100);
    return () => window.clearInterval(timer);
  }, [totals, run, still]);

  const examples = notable?.examples.filter((e) => e.opening) ?? [];
  // The fact that leads: Stanford's money, reported by Harvard. The other prepared pairs follow in small type.
  const lead = examples.find((e) => /harvard/i.test(e.holder)) ?? examples[0];
  const rest = examples.filter((e) => e !== lead);
  const searched = live?.searched;
  const seen = (at: number) => (clock >= at ? "beat beat-in" : "beat");

  return (
    <main className="opening">
      <header className="masthead">
        <span className="wordmark">Khutlisa</span>
        <span className="masthead-note">The word means "return" in Sesotho.</span>
        <SiteNav />
      </header>

      <section className="opening-globe" aria-hidden={!totals}>
        {totals && <Globe origin={totals.origin} countries={totals.countries} run={run} still={still} />}
      </section>

      <section className="opening-panel">
        {problem && <p className="notice">{problem}</p>}
        {!totals && !problem && <p className="quiet">Reading the register totals.</p>}
        {totals && (
          <>
            {lead && (
              <div className="opening-lead" key={`lead-${run}`}>
                <p className="lead-fact">
                  {lead.name} is owed <span className="lead-amount">{money(lead.amount, "USD", true)}</span>.
                </p>
                <p className="lead-by">
                  <strong>Harvard</strong> reported it. <span className="lead-source">Both are in California's public file.</span>
                </p>
              </div>
            )}
            {rest.length > 0 && (
              <ol className="owed-three" key={run}>
                {rest.map((e, i) => (
                  <li key={e.owner} className={clock >= 0.6 + i * 0.4 ? "owed-in" : ""}>
                    <span className="owed-by owed-reported">
                      <strong>{e.name}</strong> is owed {money(e.amount, "USD", true)}, reported by <strong>{holderName(e)}</strong>.
                    </span>
                  </li>
                ))}
              </ol>
            )}

            <p className={`${seen(AT.whole)} opening-whole`}>
              The whole file lists <strong>${(totals.all_amount / 1e9).toFixed(2)} billion</strong> in{" "}
              <strong>{Math.round(totals.all_properties / 1e6)} million</strong> properties.
            </p>

            <div className={`${seen(AT.abroad)} opening-abroad`}>
              <p className="counter" aria-label={money(totals.abroad_amount)}>
                {money(Math.round(amount))}
              </p>
              <p className="lede">
                of it, in <strong>{count(properties)}</strong> properties, is owed to people whose last known address is in another country.
              </p>
            </div>

            <div className={clock >= AT.search ? "live live-in" : "live"} aria-live="polite">
              {searched?.register_loaded && live ? (
                <p className="live-line">
                  <strong>{count(searched.owner_records)}</strong> owner records searched in{" "}
                  <strong>{quick(live.elapsed_ms)}</strong>, just now
                  {searched.queensland_records ? <span className="live-more">, with Queensland's {count(searched.queensland_records)} beside them</span> : null}
                </p>
              ) : live || liveProblem ? (
                <p className="live-note">California's file is not loaded on this server, so the live search cannot be shown here.</p>
              ) : (
                <p className="live-note">Searching {count(totals.owner_rows)} owner records now.</p>
              )}
            </div>

            <p className={`${seen(AT.cheque)} opening-cheque`}>The State's only way to pay is a cheque in the post.</p>
            <p className={`${seen(AT.does)} opening-does`}>
              Khutlisa lets the company that owes the money find the owner abroad, check it is really her, and pay her at home.
            </p>

            <div className={clock >= AT.actions ? "opening-actions opening-actions-in" : "opening-actions"}>
              <button className="primary" onClick={onBegin}>
                Begin: follow one payment
              </button>
              <button className="secondary opening-second" onClick={onOwed}>
                See who is owed
              </button>
              <button className="secondary opening-second" onClick={onHolders}>
                For holders
              </button>
              <button className="plain" onClick={() => setRun((n) => n + 1)}>
                Play again
              </button>
            </div>
          </>
        )}
        <p className="source">
          California State Controller, public unclaimed property records, 4 Nov 2026
          {live?.searched?.queensland_records ? ". Queensland: unclaimed monies register, The Public Trustee of Queensland, CC BY 4.0" : ""}
        </p>
      </section>
    </main>
  );
}

/** The holder of a prepared example: the name a person wrote out where there is one, the file's own otherwise. */
export const holderName = (e: NotableOrganisation) => e.holder_shown || titled(e.holder);

/** One prepared example as a plain fact: who is owed, how much, who reported it, and where anyone can check. */
export function OwedFact({ example, children }: { example: NotableOrganisation; children?: ReactNode }) {
  return (
    <>
      <span className="owed-name owed-fact">
        {example.name} is owed <span className="owed-amount">{money(example.amount, "USD", true)}</span>.
      </span>
      <span className="owed-by owed-reported">
        It was reported by <strong>{holderName(example)}</strong>. This is in California's public file.{children}
      </span>
    </>
  );
}

/** "PRESIDENT AND FELLOWS OF HARVARD COLLEGE" as a reader would write it. Short words of a company form stay capital. */
export function titled(text: string): string {
  const keep = new Set(["LLC", "LLP", "NA", "USA", "US", "FDIC", "DC", "BMO", "WM", "OFOS", "N", "A"]);
  const small = new Set(["AND", "OF", "THE", "FOR", "BY"]);
  return text
    .replace(/[.\s]+$/, "")
    .split(/\s+/)
    .map((w, i) => {
      const bare = w.replace(/[^A-Za-z]/g, "").toUpperCase();
      if (keep.has(bare)) return w.toUpperCase();
      if (i > 0 && small.has(bare)) return w.toLowerCase();
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
    })
    .join(" ");
}
