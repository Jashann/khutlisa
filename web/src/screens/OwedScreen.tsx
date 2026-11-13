import { useEffect, useRef, useState } from "react";
import { getNotable, searchOrganisations } from "../api";
import Masthead from "../components/Masthead";
import { count, money, plainPropertyType, quick } from "../format";
import type { NotableSet, OrganisationSearch, Totals } from "../types";
import { OwedFact, holderName, titled } from "./Opening";

interface Props {
  totals: Totals | null;
  onHome: () => void;
  onBegin: () => void;
}

const QUEENSLAND = "Queensland";
/** Australian dollars, spelled out so they are never read as US dollars. */
const aud = (amount: number) => `${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(amount)} AUD`;

const place = (city: string, region: string, country: string) => {
  const town = city && city.toUpperCase() !== "UNKNOWN" ? titled(city) : "";
  return [town, region, country && country !== "US" ? country : ""].filter(Boolean).join(", ") || "No city on the record";
};

/** Who Khutlisa's customer is, in one sentence, with the size read from California's file. */
export function WhoPays({ totals }: { totals: Totals | null }) {
  return (
    <aside className="who-pays">
      <p className="panel-label">Who Khutlisa is for: the holders</p>
      <p>
        The company that reported each property, the holder, can pay the owner by bank transfer. The State can only
        post a cheque{totals ? (
          <>
            . The file lists <strong>{count(totals.abroad_properties)}</strong> properties worth{" "}
            <strong>{money(totals.abroad_amount)}</strong> for owners abroad.
          </>
        ) : "."}{" "}
        <a href="#holders">See the holders</a>.
      </p>
    </aside>
  );
}

export default function OwedScreen({ totals, onHome, onBegin }: Props) {
  const [notable, setNotable] = useState<NotableSet | null>(null);
  const [problem, setProblem] = useState("");
  const [category, setCategory] = useState("");
  const [typed, setTyped] = useState("");
  const [found, setFound] = useState<OrganisationSearch | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchProblem, setSearchProblem] = useState("");
  const latest = useRef(0);

  useEffect(() => {
    getNotable()
      .then((n) => {
        setNotable(n);
        setCategory(n.categories[0] ?? "");
      })
      .catch((e: Error) => setProblem(e.message));
  }, []);

  // Results as the person types: one request a quarter of a second after the last key, and only the newest answer is shown.
  useEffect(() => {
    const q = typed.trim();
    setSearchProblem("");
    if (q.replace(/[^A-Za-z0-9]/g, "").length < 3) {
      setFound(null);
      setSearching(false);
      return;
    }
    const mine = ++latest.current;
    setSearching(true);
    const timer = window.setTimeout(() => {
      searchOrganisations(q)
        .then((r) => mine === latest.current && setFound(r))
        .catch((e: Error) => {
          if (mine !== latest.current) return;
          setFound(null);
          setSearchProblem(e.message);
        })
        .finally(() => mine === latest.current && setSearching(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const shown = notable?.examples.filter((e) => e.category === category) ?? [];
  const checkUrl = notable?.check_url ?? found?.check_url ?? "https://claimit.ca.gov/app/claim-search";
  const listed = totals?.countries.slice(0, 6) ?? [];

  return (
    <main className="flow onescreen owed">
      <Masthead onHome={onHome} note="Who is owed: organisations in the public files" />
      <div className="owed-body">
        <section className="owed-main">
          <h1>Real organisations that are owed money</h1>
          <p className="quiet owed-intro">Owners in California's own file, with the amounts it gives. Only organisations are named, never people.</p>

          <label className="field owed-search">
            <span>Type the name of a university, a city, a company, a hospital or a charity</span>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="For example: university of tokyo" autoComplete="off" autoFocus />
          </label>

          {typed.trim() ? (
            <div className="owed-results" aria-live="polite">
              {searchProblem && <p className="notice">{searchProblem}</p>}
              {!searchProblem && !found && (
                <p className="quiet">{searching ? "Searching the files." : "Type at least three letters."}</p>
              )}
              {found && (
                <>
                  <p className="owed-line">
                    {found.results.length === 0
                      ? `No organisation with "${typed.trim()}" in its name is an owner in the file.`
                      : `${found.results.length === 20 ? "The 20 largest properties" : `${count(found.results.length)} ${found.results.length === 1 ? "property" : "properties"}`} owned by an organisation with "${typed.trim()}" in its name.`}{" "}
                    Searched {count(found.owner_records)} owner records in {quick(found.elapsed_ms)}.
                  </p>
                  <ul className="owed-list">
                    {found.results.map((r, i) => (
                      <li key={`${r.record_id}-${i}`}>
                        <span className="owed-name">{r.owner}</span>
                        <span className="owed-amount">{money(r.amount, r.currency, true)}</span>
                        <span className="owed-by">
                          Reported by {titled(r.holder_name || "a holder that is not named")}. {place(r.owner_city, r.owner_region, r.owner_country)}.{" "}
                          {plainPropertyType(r.property_type)}.
                        </span>
                      </li>
                    ))}
                    {found.queensland && found.queensland.results.length > 0 && (
                      <li className="owed-divider">
                        <span className="owed-by">
                          In Queensland's register, in Australian dollars ({count(found.queensland.owner_records)} owner records, searched in the same request):
                        </span>
                      </li>
                    )}
                    {found.queensland?.results.map((r, i) => (
                      <li key={`q-${r.record_id}-${i}`} className="owed-qld">
                        <span className="owed-name">{r.owner}</span>
                        <span className="owed-amount">{aud(r.amount)}</span>
                        <span className="owed-by">Sent to the Public Trustee of Queensland by {titled(r.holder_name || "a sender that is not named")}.</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          ) : (
            <>
              {problem && <p className="notice">{problem}</p>}
              {notable && (
                <>
                  <div className="tabs" role="tablist" aria-label="Kinds of organisation">
                    {notable.categories.map((c) => (
                      <button key={c} type="button" role="tab" aria-selected={c === category} className={c === category ? "tab tab-on" : "tab"} onClick={() => setCategory(c)}>
                        {c}
                      </button>
                    ))}
                    {notable.queensland && (
                      <button type="button" role="tab" aria-selected={category === QUEENSLAND} className={category === QUEENSLAND ? "tab tab-on" : "tab"} onClick={() => setCategory(QUEENSLAND)}>
                        Queensland
                      </button>
                    )}
                  </div>
                  <ul className="owed-list">
                    {category === QUEENSLAND && notable.queensland?.examples.map((e) => (
                      <li key={e.owner} className="owed-qld">
                        <span className="owed-name">{e.owner}</span>
                        <span className="owed-amount">{aud(e.amount)}</span>
                        <span className="owed-by">Sent to the Public Trustee of Queensland by {e.sent_by}, received {e.received}. Australian dollars.</span>
                      </li>
                    ))}
                    {shown.map((e) => e.pair ? (
                      <li key={e.owner}>
                        <OwedFact example={e}> {place(e.city, e.region, e.abroad ? e.country_name || e.country : "")}.</OwedFact>
                      </li>
                    ) : (
                      <li key={e.owner}>
                        <span className="owed-name">{e.name}</span>
                        <span className="owed-amount">{money(e.amount, "USD", true)}</span>
                        <span className="owed-by">
                          Reported by {holderName(e)}. {place(e.city, e.region, e.abroad ? e.country_name || e.country : "")}.{" "}
                          {e.properties_in_this_name > 1
                            ? `The largest of ${count(e.properties_in_this_name)} properties in this exact name, worth ${money(e.total_in_this_name, "USD", true)} together.`
                            : "The only property in this exact name."}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </section>

        <aside className="owed-side">
          {notable && (
            <div className="panel owed-total">
              <p className="panel-label">The {count(notable.count)} examples listed</p>
              <p className="panel-amount">{money(notable.total, "USD", true)}</p>
            </div>
          )}
          <div className="panel owed-check">
            <p className="panel-label">Check any of these yourself</p>
            <p>
              Look the names up on California's own site,{" "}
              <a href={checkUrl} target="_blank" rel="noreferrer">claimit.ca.gov</a>.
            </p>
          </div>
          {notable?.queensland && (
            <div className="panel owed-second">
              <p className="panel-label">A second register: Queensland</p>
              <p>
                <strong>{count(notable.queensland.owner_records)}</strong> records worth <strong>{aud(notable.queensland.amount)}</strong>, searched in the same pass. Australian dollars,
                kept apart from California's US dollars.
              </p>
              <p className="quiet owed-credit">
                {notable.queensland.attribution}{" "}
                <a href={notable.queensland.dataset} target="_blank" rel="noreferrer">The data</a>,{" "}
                <a href={notable.queensland.licence_url} target="_blank" rel="noreferrer">the licence</a>.
              </p>
            </div>
          )}
          <WhoPays totals={totals} />
          {listed.length > 0 && totals && (
            <div className="panel owed-countries">
              <p className="panel-label">Where the owners abroad are</p>
              <ol className="owed-ranking">
                {listed.map((c) => (
                  <li key={c.code}>
                    <span>{c.name}</span>
                    <span className="rank-amount">{money(c.amount)}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          <button type="button" className="primary primary-small" onClick={onBegin}>
            Follow one payment
          </button>
        </aside>
      </div>
    </main>
  );
}
