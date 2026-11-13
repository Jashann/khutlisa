import type { DecisionCardData } from "../types";

const LABELS: [keyof Pick<DecisionCardData, "happened" | "allowed" | "did" | "money">, string][] = [
  ["happened", "What happened"],
  ["allowed", "The limits allowed"],
  ["did", "What the agent did"],
  ["money", "Result"],
];

/** One decision of the agent: four short lines in large type. The longer explanation folds away behind "Why". */
export default function DecisionCard({ card, compact = false }: { card: DecisionCardData; compact?: boolean }) {
  return (
    <article className={`decision decision-${card.tone}${compact ? " decision-compact" : ""}`} data-kind={card.kind}>
      <p className="decision-title">{card.title}</p>
      <dl className="decision-lines">
        {LABELS.map(([key, label]) => (
          <div key={key} className={`decision-line decision-${key}`}>
            <dt>{label}</dt>
            <dd>{card[key]}</dd>
          </div>
        ))}
      </dl>
      {card.why.length > 0 && (
        <details className="decision-why">
          <summary>Why</summary>
          {card.why.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </details>
      )}
    </article>
  );
}
