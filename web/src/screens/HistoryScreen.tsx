import { useEffect, useRef, useState, type FormEvent } from "react";
import { getCountries, search, getIndicative } from "../api";
import MatchCard from "../components/MatchCard";
import Masthead from "../components/Masthead";
import VoiceIntake from "../components/VoiceIntake";
import Waiting from "../components/Waiting";
import { count, money, quick } from "../format";
import type { CountryName, History, Match, PlaceEntry, RegisterInfo, SearchResult } from "../types";

const emptyPlace = (): PlaceEntry => ({ city: "", region: "", postcode: "" });

interface Props {
  /** The register the search runs over. Null until the server has answered. */
  register: RegisterInfo | null;
  /** False while another screen is in front of this one. */
  shown: boolean;
  onBack: () => void;
  /** Takes the person back to the claim they had open. Missing when there is none yet. */
  onOpenClaim?: () => void;
  /** The way on to the proof file and the claim. App.tsx passes this in. */
  onChooseMatch?: (match: Match, history: History) => void;
}

/** The one line above the results: what was searched, and how long it took, as the server measured it. */
function searchedLine(result: SearchResult): string {
  const s = result.searched;
  if (!s) return `Searched the register in ${quick(result.elapsed_ms)}.`;
  const demo = s.demonstration_records > 0 ? `${count(s.demonstration_records)} demonstration records` : "";
  if (!s.register_loaded)
    return `California's file is not loaded on this server, so only the ${demo || "records on hand"} were searched, in ${quick(result.elapsed_ms)}.`;
  if (s.queensland_records)
    return `Searched ${count(s.owner_records + s.queensland_records)} owner records in California's and Queensland's public files${demo ? `, and ${demo},` : ""} in ${quick(result.elapsed_ms)}.`;
  return `Searched ${count(s.owner_records)} owner records from California's public file${demo ? ` and ${demo}` : ""} in ${quick(result.elapsed_ms)}.`;
}

export default function HistoryScreen({ register, shown, onBack, onOpenClaim, onChooseMatch }: Props) {
  const [given, setGiven] = useState("");
  const [families, setFamilies] = useState<string[]>([""]);
  const [places, setPlaces] = useState<PlaceEntry[]>([emptyPlace()]);
  const [employers, setEmployers] = useState<string[]>([""]);
  const [country, setCountry] = useState("");
  const [countries, setCountries] = useState<CountryName[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [asked, setAsked] = useState<History | null>(null);
  // The matches as they stood before the last follow-up answer, so a card can show what the answer changed.
  const [before, setBefore] = useState<SearchResult | null>(null);
  const [mode, setMode] = useState<"voice" | "form">("voice");
  const resultsRef = useRef<HTMLElement>(null);
  const ownerRecords = register ? (register.owner_records ?? register.records) : 0;
  const loaded = register ? register.loaded !== false : true;
  const where = register && loaded ? `${count(ownerRecords)} ${ownerRecords === 1 ? "owner record" : "owner records"}` : "";

  const toTop = () => setMode("voice");
  const toMatches = () => resultsRef.current?.scrollTo({ top: 0, behavior: "smooth" });

  useEffect(() => {
    getCountries().then(setCountries).catch(() => setCountries([]));
  }, []);

  const fromForm = (): History => ({
    given_names: given.split(/[\s,]+/).filter(Boolean),
    family_names: families.map((f) => f.trim()).filter(Boolean),
    places: places
      .map((p) => ({ city: p.city.trim(), region: p.region.trim(), postcode: p.postcode.trim() }))
      .filter((p) => p.city || p.region || p.postcode),
    employers: employers.map((e) => e.trim()).filter(Boolean),
    current_country: country,
  });

  /** For each strong match, what the amount would become in the person's own currency today. One request for
   *  the whole list, at Airwallex's indicative rate. The cards say that it is indicative. */
  const addLocalAmounts = async (found: SearchResult, where: string) => {
    const strongOnes = found.matches.filter((m) => m.strength === "strong" && m.amount > 0);
    if (!where || strongOnes.length === 0) return;
    try {
      const local = await getIndicative(where, strongOnes.map((m) => m.amount));
      if (!local.available || local.rate === undefined) return;
      const byAmount = new Map(local.amounts.map((a) => [Number(a.usd).toFixed(2), a]));
      setResult((now) => now !== found ? now : {
        ...found,
        matches: found.matches.map((m) => {
          const row = m.strength === "strong" ? byAmount.get(m.amount.toFixed(2)) : undefined;
          return row ? { ...m, indicative: { ...row, rate: local.rate as number, label: local.label ?? "" } } : m;
        }),
      });
    } catch {
      // No rate, no line. The search result stands as it is.
    }
  };

  const run = async (history: History, answered = false) => {
    if (history.family_names.length === 0) {
      setProblem("Give at least one family name, so there is something to look for.");
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      const next = await search(history);
      setBefore(answered ? result : null);
      setResult(next);
      void addLocalAmounts(next, history.current_country);
      setAsked(history);
      requestAnimationFrame(toMatches);
    } catch (e) {
      setResult(null);
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** The voice intake calls this. It fills the form with what was heard, then searches. */
  const onHistory = (history: History, answered: boolean) => {
    setGiven(history.given_names.join(" "));
    setFamilies(history.family_names.length ? history.family_names : [""]);
    setPlaces(history.places.length ? history.places : [emptyPlace()]);
    setEmployers(history.employers.length ? history.employers : [""]);
    setCountry(history.current_country);
    void run(history, answered);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void run(fromForm());
  };

  const setAt = <T,>(list: T[], index: number, value: T) => list.map((item, i) => (i === index ? value : item));
  const without = <T,>(list: T[], index: number) => list.filter((_, i) => i !== index);

  // "Strong" and "possible" come from the API, which decides them by a stated rule and not by the number.
  // Strong matches are listed largest amount first, so the record that matters most keeps its place at the top
  // when an answer lifts several records at once. The possible ones stay in the order the search gave them.
  const strong = (result?.matches.filter((m) => m.strength === "strong") ?? []).sort((a, b) => b.amount - a.amount);
  const possible = result?.matches.filter((m) => m.strength !== "strong") ?? [];
  const strongCount = result ? (result.strong_count ?? result.confident_count) : 0;
  const strongAmount = result ? (result.strong_amount ?? result.confident_amount) : 0;

  return (
    <main className="history onescreen">
      {shown && (
        <Masthead
          now={result ? "matches" : "history"}
          onHome={onBack}
          go={{ history: toTop, matches: result ? toMatches : undefined, proof: onOpenClaim, claim: onOpenClaim }}
        />
      )}

      <div className="history-body">
        <section className="history-form pane">
          <div className="history-title">
            <h1>Tell us your history</h1>
            <div className="tabs" role="tablist" aria-label="How to give your history">
              <button type="button" role="tab" aria-selected={mode === "voice"} className={mode === "voice" ? "tab tab-on" : "tab"} onClick={() => setMode("voice")}>
                Say it or type it
              </button>
              <button type="button" role="tab" aria-selected={mode === "form"} className={mode === "form" ? "tab tab-on" : "tab"} onClick={() => setMode("form")}>
                The form
              </button>
            </div>
          </div>

          <div hidden={mode !== "voice"}>
            <VoiceIntake onHistory={onHistory} settled={!busy && strongCount > 0} />
          </div>

          <div hidden={mode !== "form"}>
          <p className="quiet">What the search is using{where ? `, across ${where}.` : "."}</p>
          <form onSubmit={submit} noValidate>
            <fieldset>
              <legend>Your names</legend>
              <label className="field">
                <span>Given names</span>
                <input value={given} onChange={(e) => setGiven(e.target.value)} placeholder="All of them, in any order" autoComplete="off" />
              </label>
              {families.map((family, i) => (
                <div className="row" key={i}>
                  <label className="field">
                    <span>{i === 0 ? "Family name" : "Another family name"}</span>
                    <input
                      value={family}
                      onChange={(e) => setFamilies(setAt(families, i, e.target.value))}
                      placeholder={i === 0 ? "The name you were born with" : "A married or earlier name"}
                      autoComplete="off"
                    />
                  </label>
                  {families.length > 1 && (
                    <button type="button" className="remove" onClick={() => setFamilies(without(families, i))} aria-label="Remove this family name">
                      Remove
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="add" onClick={() => setFamilies([...families, ""])}>
                Add another family name
              </button>
            </fieldset>

            <fieldset>
              <legend>Places you have lived</legend>
              {places.map((place, i) => (
                <div className="row row-place" key={i}>
                  <label className="field">
                    <span>City</span>
                    <input value={place.city} onChange={(e) => setPlaces(setAt(places, i, { ...place, city: e.target.value }))} autoComplete="off" />
                  </label>
                  <label className="field field-short">
                    <span>State or region</span>
                    <input value={place.region} onChange={(e) => setPlaces(setAt(places, i, { ...place, region: e.target.value }))} autoComplete="off" />
                  </label>
                  <label className="field field-short">
                    <span>Postcode</span>
                    <input value={place.postcode} onChange={(e) => setPlaces(setAt(places, i, { ...place, postcode: e.target.value }))} autoComplete="off" />
                  </label>
                  {places.length > 1 && (
                    <button type="button" className="remove" onClick={() => setPlaces(without(places, i))} aria-label="Remove this place">
                      Remove
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="add" onClick={() => setPlaces([...places, emptyPlace()])}>
                Add another place
              </button>
            </fieldset>

            <fieldset>
              <legend>Employers and banks</legend>
              {employers.map((employer, i) => (
                <div className="row" key={i}>
                  <label className="field">
                    <span>{i === 0 ? "Employer, bank, insurer or landlord" : "Another one"}</span>
                    <input value={employer} onChange={(e) => setEmployers(setAt(employers, i, e.target.value))} autoComplete="off" />
                  </label>
                  {employers.length > 1 && (
                    <button type="button" className="remove" onClick={() => setEmployers(without(employers, i))} aria-label="Remove this employer or bank">
                      Remove
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="add" onClick={() => setEmployers([...employers, ""])}>
                Add another employer or bank
              </button>
            </fieldset>

            <fieldset>
              <legend>Where you live now</legend>
              <label className="field">
                <span>Country</span>
                <select value={country} onChange={(e) => setCountry(e.target.value)}>
                  <option value="">Choose a country</option>
                  {countries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            </fieldset>

            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Searching the register" : "Search the register"}
            </button>

          </form>
          </div>
        </section>

        <section className="results pane" aria-live="polite" ref={resultsRef}>
          {problem && <p className="notice">{problem}</p>}
          {!result && !problem && !busy && (
            <div className="results-empty">
              <p className="results-empty-title">The matches will appear here</p>
              <p>Every record that could be hers is listed with the reasons.</p>
            </div>
          )}
          {busy && (
            <div className="results-empty">
              <Waiting>{where ? `Searching ${where}.` : "Searching the register."}</Waiting>
            </div>
          )}

          {result && !busy && (
            <>
              <div className="summary">
                <p className="searched-line">{searchedLine(result)}</p>
                {result.searched?.queensland_attribution && result.matches.some((m) => m.source === "AU-QLD") && (
                  <p className="searched-credit">{result.searched.queensland_attribution}</p>
                )}
                {strongCount > 0 ? (
                  <p className="summary-text">
                    <span className="summary-amount">{money(strongAmount, result.currency, true)}</span> in {count(strongCount)}{" "}
                    {strongCount === 1 ? "record that matches" : "records that match"} this history strongly.
                  </p>
                ) : (
                  <p className="summary-text">
                    <span className="summary-none">No strong match yet.</span>{" "}
                    {result.matches.length > 0
                      ? "These records share the name. One more fact, such as the postcode, is needed to tie one to this history."
                      : "Nothing in the register is close to this history."}
                  </p>
                )}
                <details className="rule">
                  <summary>
                    {result.found_is_capped ? "More than " : ""}
                    {count(result.found)} possible {result.found === 1 ? "match" : "matches"} found
                    {result.found > result.matches.length ? `, the first ${count(result.matches.length)} shown` : ""}. How a match is called strong
                  </summary>
                  <p className="quiet">
                    {result.strength_rule} The match strength number on each record adds fixed points for each piece of
                    evidence listed under it. It puts the records in order and is not a measured chance.
                  </p>
                </details>
              </div>

              {result.matches.length === 0 && (
                <p className="results-empty">
                  No record matches this history closely enough. Try another family name or an employer.
                </p>
              )}

              {strong.map((m, i) => (
                <MatchCard key={`${m.record_id}-${i}`} match={m} before={before?.matches.find((b) => b.record_id === m.record_id)}
                  onChoose={onChooseMatch && asked && m.source !== "AU-QLD" ? (match) => onChooseMatch(match, asked) : undefined} />
              ))}
              {possible.length > 0 && (
                <p className="divider">
                  <span>Possible matches: the name fits, and nothing else ties them to this history yet.</span>
                </p>
              )}
              {possible.map((m, i) => (
                <MatchCard key={`${m.record_id}-${i}`} match={m} before={before?.matches.find((b) => b.record_id === m.record_id)}
                  onChoose={onChooseMatch && asked && m.source !== "AU-QLD" ? (match) => onChooseMatch(match, asked) : undefined} />
              ))}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
