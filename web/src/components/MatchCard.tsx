import { isDemonstration } from "../demo";
import { exact, money, plainPropertyType, sentence, toYou } from "../format";
import type { Match } from "../types";

interface Props {
  match: Match;
  /** The same record as the search before the last answer found it, when there was one. */
  before?: Match;
  /** Opens the claim for this record. When it is missing the card shows no button. */
  onChoose?: (match: Match) => void;
}

const label = (m: Match) => (m.strength === "strong" ? "Strong match" : "Possible match");

export default function MatchCard({ match, before, onChoose }: Props) {
  const place = [match.owner_city, match.owner_region, match.owner_country].filter(Boolean).join(", ");
  const demonstration = isDemonstration(match.source);
  // Queensland's register is searched in the same pass. Its amounts are Australian dollars, and a claim on one
  // of its records goes to the Public Trustee of Queensland, not through a holder here.
  const queensland = match.source === "AU-QLD";
  const file = queensland ? "Queensland's register" : "California's file";
  // The label is the API's, decided by its stated rule. The number only orders the list.
  const strong = match.strength === "strong";
  const lifted = before && (before.strength !== match.strength || before.score !== match.score);
  const gained = lifted ? match.reasons.filter((r) => !before.reasons.includes(r)) : [];
  return (
    <article className={`match ${strong ? "" : "match-below"}${demonstration ? " match-demo" : " match-real"}`}>
      <header className="match-head">
        <div>
          <p className={match.owner_is_organisation ? "owner" : "owner owner-masked"}>{match.owner}</p>
          <p className="owner-note">
            {demonstration
              ? "Demonstration record"
              : match.owner_is_organisation
                ? `Organisation named in ${file}`
                : `A real owner in ${file}, name hidden`}
          </p>
        </div>
        <div className="match-money">
          <p className="match-amount">{money(match.amount, match.currency, true)}</p>
          {/* Money from the start: what this would become at home today. Indicative, and labelled so. */}
          {strong && match.indicative && (
            <p className="match-local" title={match.indicative.label}>
              about <strong>{exact(match.indicative.would_receive.amount, match.indicative.would_receive.currency)}</strong> today
              <span className="match-local-note">
                Indicative Airwallex rate {match.indicative.rate}, not locked
                {match.indicative.fees.borne_by === "holder" ? ", fees borne by the holder" : ""}
              </span>
            </p>
          )}
        </div>
      </header>

      <p className="match-facts">
        {queensland ? "Sent to the Public Trustee by" : "Reported by"} {match.holder_name || "a holder that is not named"}. {plainPropertyType(match.property_type) || "Kind of money not stated"}.{" "}
        {place ? `Last known place: ${place}.` : ""}
      </p>

      {lifted && (
        <div className={before.strength !== match.strength ? "lift lift-up" : "lift"} aria-live="polite">
          <p className="lift-steps">
            <span className="lift-before">Before the answer: {label(before).toLowerCase()}, {before.score.toFixed(2)}</span>
            <span className="lift-arrow" aria-hidden="true" />
            <span className="lift-after">Now: {label(match).toLowerCase()}, {match.score.toFixed(2)}</span>
          </p>
          {gained.length > 0 && <p className="lift-why">What changed: {gained.map((g) => sentence(toYou(g))).join(" ")}</p>}
        </div>
      )}

      <div className="score" role="img"
        aria-label={`${label(match)}. Match strength ${match.score.toFixed(2)} out of 1, a sum of points for the evidence listed below`}>
        <span className="score-label">{label(match)}</span>
        <div className="score-track">
          {lifted && <span className="score-was" style={{ width: `${before.score * 100}%` }} />}
          <span className="score-fill" style={{ width: `${match.score * 100}%` }} />
        </div>
        <span className="score-number">{match.score.toFixed(2)}</span>
      </div>

      {/* One line on every strong match, in the API's own words: the label sorts, the proof file decides. */}
      {strong && match.note && <p className="match-note">{match.note}</p>}

      <ul className="lines">
        {match.reasons.map((r, i) => (
          <li key={`r${i}`} className={gained.includes(r) ? "reason reason-new" : "reason"}>
            {sentence(toYou(r))}
          </li>
        ))}
        {match.doubts.map((d, i) => (
          <li key={`d${i}`} className="doubt">
            {sentence(toYou(d))}
          </li>
        ))}
      </ul>

      {onChoose && (
        <button type="button" className="secondary" onClick={() => onChoose(match)}>
          Prove this is mine
        </button>
      )}
      {queensland && (
        <p className="match-note">
          In Australian dollars. Queensland's register is searched here; a claim on it is made to{" "}
          <a href="https://www.pt.qld.gov.au/unclaimed-money/" target="_blank" rel="noreferrer">the Public Trustee of Queensland</a>.
        </p>
      )}
    </article>
  );
}
