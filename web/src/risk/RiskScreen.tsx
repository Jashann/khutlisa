import { useEffect, useState } from "react";
import { LockedError, payerKey, setPayerKey } from "../api";
import DecisionCard from "../components/DecisionCard";
import Masthead from "../components/Masthead";
import Waiting from "../components/Waiting";
import { count, dateTime, exact, stateWords } from "../format";
import { getRisk, releaseClaim } from "./api";
import RingGraph, { STATUS_WORDS } from "./RingGraph";
import type { RiskClaim, RiskGroup, RiskView } from "./types";
import "./risk.css";

const claimsWord = (n: number) => `${count(n)} ${n === 1 ? "claim" : "claims"}`;

/** What a group is about, in a few words: its strongest shared thing. */
const TITLES: Record<string, string> = {
  account: "one bank account", document: "one document file", image: "one card picture", email: "one email address",
  phone: "one phone number", name_variant: "names a letter apart",
};
const groupTitle = (g: RiskGroup) => `${claimsWord(g.nodes.length)}, ${TITLES[g.shared[0]?.kind ?? ""] ?? "linked"}`;

type Tab = "picture" | "points" | "claims";

/** The holder's risk view: the queue, the groups of linked claims and the counts. */
export default function RiskScreen({ onHome }: { onHome: () => void }) {
  const [view, setView] = useState<RiskView | null>(null);
  const [problem, setProblem] = useState("");
  // The same key as the holder's main view, kept in the same place, so it is typed once for both.
  const [unlocked, setUnlocked] = useState(() => payerKey() !== "");
  const [typedKey, setTypedKey] = useState("");
  const [keyProblem, setKeyProblem] = useState("");
  const [groupId, setGroupId] = useState<string | null>(null);
  const [claimId, setClaimId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("picture");
  const [releasing, setReleasing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const lock = (e: LockedError) => {
    setPayerKey("");
    setUnlocked(false);
    setView(null);
    setKeyProblem(e.message || "The holder's key is missing or wrong.");
  };
  const load = () =>
    getRisk()
      .then(setView)
      .catch((e: Error) => (e instanceof LockedError ? lock(e) : setProblem(e.message)));

  useEffect(() => {
    document.title = "Khutlisa: risk";
    if (!unlocked) return;
    void load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [unlocked]);

  const release = async (id: string) => {
    setBusy(true);
    setProblem("");
    try {
      setView(await releaseClaim(id, reason.trim()));
      setReleasing(null);
      setReason("");
    } catch (e) {
      if (e instanceof LockedError) lock(e);
      else setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const note = "The holder's risk view: claims linked across the whole queue";
  if (!unlocked) {
    return (
      <main className="flow onescreen">
        <Masthead onHome={onHome} note={note} />
        <div className="flow-body flow-narrow">
          <h1>The risk view is locked</h1>
          <p className="quiet">Type the key that was set on this server. It is kept for this browser tab only.</p>
          {keyProblem && <p className="notice">{keyProblem}</p>}
          <form className="key-form" onSubmit={(e) => { e.preventDefault(); setKeyProblem(""); setProblem(""); setPayerKey(typedKey.trim()); setUnlocked(typedKey.trim() !== ""); }}>
            <label className="field">
              <span>Holder's key</span>
              <input type="password" value={typedKey} onChange={(e) => setTypedKey(e.target.value)} autoComplete="off" autoFocus />
            </label>
            <button type="submit" className="primary primary-small" disabled={typedKey.trim() === ""}>
              Open the risk view
            </button>
          </form>
        </div>
      </main>
    );
  }

  const c = view?.counts;
  const m = view?.measurement;
  const groups = view?.groups ?? [];
  const group = groups.find((g) => g.id === groupId) ?? groups[0] ?? null;
  const byId = new Map((view?.claims ?? []).map((row) => [row.id, row]));
  const members = group ? group.nodes.map((n) => byId.get(n.id)).filter((row): row is RiskClaim => Boolean(row)) : [];
  const open = (g: RiskGroup, next: Tab = "picture") => { setGroupId(g.id); setTab(next); setReleasing(null); };
  const stopped = (view?.claims ?? []).filter((row) => row.status !== "clear");
  const clear = (view?.claims.length ?? 0) - stopped.length;

  return (
    <main className="flow onescreen payer riskview">
      <Masthead onHome={onHome} note={note} />
      {c && (
        <div className="risk-strip" aria-label="Counts">
          <div className="risk-count"><p className="risk-figure">{count(c.claims)}</p><p className="risk-label">claims looked at</p></div>
          <div className="risk-count"><p className="risk-figure">{count(c.groups_flagged)}</p><p className="risk-label">{c.groups_flagged === 1 ? "group held" : "groups held"}</p></div>
          <div className="risk-count"><p className="risk-figure">{count(c.held + c.suspended)}</p><p className="risk-label">claims held{c.suspended > 0 ? `, ${count(c.suspended)} with an approval` : ""}</p></div>
          <div className="risk-count risk-count-money"><p className="risk-figure">{exact(c.held_usd, "USD")}</p><p className="risk-label">held before it moved</p></div>
          {m && m.ring_claims !== null && m.honest_claims !== null && (
            <>
              <div className="risk-count risk-count-measured"><p className="risk-figure">{count(m.ring_claims_caught ?? 0)} of {count(m.ring_claims)}</p><p className="risk-label">planted ring claims held before payment, measured</p></div>
              <div className="risk-count risk-count-measured"><p className="risk-figure">{count(m.honest_claims_held ?? 0)} of {count(m.honest_claims)}</p><p className="risk-label">honest claims wrongly held, measured</p></div>
            </>
          )}
        </div>
      )}
      <div className="risk-cols">
        <section className="pane payer-left">
          <div className="risk-head">
            <h1>Claims held for risk</h1>
            <a className="risk-link" href="/payer">The queue</a>
          </div>
          {view?.demonstration && <p className="quiet risk-demo">Demonstration claims: every person here is invented.</p>}
          {problem && <p className="notice">{problem}</p>}
          {!view && !problem && <div className="results-empty"><Waiting counted={false}>Looking across the claims.</Waiting></div>}
          {groups.length > 0 && (
            <ul className="payer-list risk-groups" aria-label="Groups of linked claims">
              {groups.map((g) => (
                <li key={g.id}>
                  <button type="button" className={g.id === group?.id ? "payer-pick payer-pick-on" : "payer-pick"} onClick={() => open(g)}>
                    <span className="payer-pick-name">{groupTitle(g)}</span>
                    <span className="payer-pick-amount">{g.flagged ? exact(g.held_usd, "USD") : ""}</span>
                    <span className={g.flagged ? "state risk-state-held" : "state"}>{g.flagged ? `Held, ${g.points} points` : `Not held, ${g.points} points`}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {view && groups.length === 0 && <p className="results-empty">No claims are linked. Nothing is held.</p>}
          {view && (
            <div className="risk-queue">
              <p className="panel-label">The queue</p>
              {c && (
                <p className="risk-chips">
                  <span className="state risk-state-held">{count(c.held)} held</span>
                  <span className="state risk-state-suspended">{count(c.suspended)} approval suspended</span>
                  <span className="state risk-state-paid_before">{count(c.paid_before)} paid before</span>
                  <span className="state risk-state-released">{count(c.released)} released</span>
                  <span className="state">{count(clear)} clear</span>
                </p>
              )}
              <ul className="risk-rows" aria-label="Claims that are held, suspended or released">
                {stopped.map((row) => (
                  <li key={row.id}>
                    <button type="button" className={row.id === claimId ? "risk-row risk-row-on" : "risk-row"}
                      onClick={() => { const g = groups.find((x) => x.id === row.group); if (g) open(g, "claims"); setClaimId(row.id); }}>
                      <span className="risk-row-name">{row.claimant}</span>
                      <span className="risk-row-amount">{exact(row.amount, row.currency)}</span>
                      <span className={`state risk-state-${row.status}`}>{STATUS_WORDS[row.status]}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <p className="quiet risk-clear">
                {clear === 0 ? "No claim is clear." : `${claimsWord(clear)} ${clear === 1 ? "is" : "are"} clear: not in any held group.`}
                {c && (c.from_notice || c.estates) ? ` Every claim is looked at here, including ${[
                  c.from_notice ? `${claimsWord(c.from_notice)} opened from your notices` : "",
                  c.estates ? `${count(c.estates)} ${c.estates === 1 ? "estate" : "estates"}` : "",
                ].filter(Boolean).join(" and ")}.` : ""}
                {c && c.paid_before > 0 && ` ${exact(c.paid_before_usd, "USD")} had already left on ${claimsWord(c.paid_before)} before the link showed. It is recorded and not called back.`}
              </p>
            </div>
          )}
        </section>

        <section className="pane payer-right">
          {group && (
            <article className="match risk-group" key={group.id}>
              <header className="match-head">
                <div>
                  <p className="owner payer-claimant">{groupTitle(group)}</p>
                  <p className="owner-note">{group.flagged ? "Every claim in this group is held until a person releases it." : "These claims are linked, and nothing is held."}</p>
                </div>
                <div className="queue-right">
                  <p className="match-amount">{group.points} points</p>
                  <p className={group.flagged ? "state risk-state-held" : "state"}>{group.flagged ? `Held from ${group.flag_at} points` : `Held only from ${group.flag_at} points`}</p>
                </div>
              </header>
              <div className="risk-tabs" role="tablist">
                {([["picture", "The picture"], ["points", "The points"], ["claims", "The claims and the release"]] as [Tab, string][]).map(([key, label]) => (
                  <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "risk-tab risk-tab-on" : "risk-tab"} onClick={() => setTab(key)}>
                    {label}
                  </button>
                ))}
              </div>

              {tab === "picture" && (
                <>
                  <RingGraph group={group} chosen={claimId} onChoose={(id) => { setClaimId(id); setTab("claims"); }} />
                  <p className="quiet risk-legend">
                    In the middle is what the claims share. A solid line is a signal that links claims. A dashed line only adds points.
                  </p>
                  <DecisionCard card={group.card} />
                </>
              )}

              {tab === "points" && (
                <>
                  <table className="risk-points">
                    <thead>
                      <tr><th>Signal</th><th>What is shared</th><th className="risk-num">Claims</th><th className="risk-num">Points</th></tr>
                    </thead>
                    <tbody>
                      {group.table.map((row) => (
                        <tr key={row.kind}>
                          <td>{row.words.charAt(0).toUpperCase() + row.words.slice(1)}</td>
                          <td className="quiet">{row.elements.slice(0, 2).join("; ")}{row.elements.length > 2 ? `; ${row.elements.length - 2} more` : ""}</td>
                          <td className="risk-num">{row.claims}</td>
                          <td className="risk-num risk-points-value">{row.points}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr><td colSpan={3}>The sum. Each signal counts once, at a fixed value.</td><td className="risk-num risk-points-total">{group.points}</td></tr>
                    </tfoot>
                  </table>
                  {view && <p className="quiet risk-rule">{view.rule.text}</p>}
                </>
              )}

              {tab === "claims" && (
                <ul className="risk-members">
                  {members.map((row) => (
                    <li key={row.id} className={row.id === claimId ? "risk-member risk-member-on" : "risk-member"}>
                      <div className="risk-member-head">
                        <p className="risk-member-name">{row.claimant}<span className="quiet">, {stateWords(row.state).toLowerCase()}</span></p>
                        <p className="risk-member-amount">{exact(row.amount, row.currency)}</p>
                        <p className={`state risk-state-${row.status}`}>{STATUS_WORDS[row.status]}</p>
                      </div>
                      {row.release && <p className="risk-released">Released on {dateTime(row.release.at)}. Reason on file: {row.release.reason}</p>}
                      {!row.release && row.events.length > 0 && <p className="quiet risk-event">{row.events[row.events.length - 1].note}</p>}
                      {(row.status === "held" || row.status === "suspended") && releasing !== row.id && (
                        <button type="button" className="secondary secondary-flat risk-release" disabled={busy} onClick={() => { setReleasing(row.id); setReason(""); setClaimId(row.id); }}>
                          Release this claim
                        </button>
                      )}
                      {releasing === row.id && (
                        <form className="actions risk-release-form" onSubmit={(e) => { e.preventDefault(); void release(row.id); }}>
                          <label className="field">
                            <span>Your reason for releasing it, kept with the claim</span>
                            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoFocus />
                          </label>
                          <button type="submit" className="primary primary-small" disabled={busy || reason.trim().length < 3}>Release with this reason</button>
                          <button type="button" className="plain" onClick={() => setReleasing(null)}>Cancel</button>
                        </form>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          )}
        </section>
      </div>
    </main>
  );
}
