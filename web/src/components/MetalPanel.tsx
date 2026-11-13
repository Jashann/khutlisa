import { useEffect, useState } from "react";
import { LockedError } from "../api";
import { dateTime } from "../format";
import { attemptPull, getClaimMetal, getHolderMetal, revokeMandate, signMandate, verifyMandate } from "../metal";
import type { MetalMandate, MetalView } from "../metal";
import "../metal.css";
import Waiting from "./Waiting";

const short = (hash: string | null | undefined) => (hash ? `${hash.slice(0, 10)}…${hash.slice(-8)}` : "");

/** A transaction or an address, cut short, linking to the testnet explorer. The whole value is in the title. */
function Chain({ value, href }: { value: string | null | undefined; href: string | null | undefined }) {
  if (!value) return <span className="quiet">not on chain</span>;
  return href ? (
    <a className="mono metal-hash" href={href} target="_blank" rel="noreferrer" title={value}>{short(value)}</a>
  ) : (
    <span className="mono metal-hash" title={value}>{short(value)}</span>
  );
}

const STATUS_WORDS: Record<MetalMandate["status"], string> = {
  issued: "Written, not yet bound on chain",
  bound: "Bound on the holder's Metal account",
  revoked: "Revoked by the holder",
  spent: "Spent: its one payment was made",
};

interface Props {
  claimId: string;
  /** The holder's view: with the holder's key, and with what the holder can do. */
  holder?: boolean;
  /** Changes whenever the claim around the panel changes, so the panel reads again at once. */
  refresh?: string | number | null;
  onChanged?: () => void | Promise<unknown>;
  onLocked?: (e: LockedError) => void;
}

/** "Funded on Metal": the mandate the holder signed, its terms beside the approval's, the agent's pull, the
 *  chain's own verification, and every refusal, each with a hash that opens on the testnet explorer. It shows
 *  nothing for a claim funded by a bank deposit. */
export default function MetalPanel({ claimId, holder = false, refresh = null, onChanged, onLocked }: Props) {
  const [view, setView] = useState<MetalView | null>(null);
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");

  const read = () =>
    (holder ? getHolderMetal(claimId) : getClaimMetal(claimId))
      .then(setView)
      .catch((e: Error) => (e instanceof LockedError ? onLocked?.(e) : undefined));

  useEffect(() => {
    setView(null);
    void read();
    const timer = window.setInterval(read, 4000);
    return () => window.clearInterval(timer);
  }, [claimId, holder]);
  useEffect(() => { void read(); }, [refresh]);

  const act = async (label: string, work: () => Promise<MetalView>) => {
    setBusy(label);
    setProblem("");
    try {
      setView(await work());
      await onChanged?.();
    } catch (e) {
      if (e instanceof LockedError) onLocked?.(e);
      else setProblem((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  if (!view || view.funding !== "metal") return null;
  if (!view.available) {
    return (
      <section className="metal" aria-label="Funded on Metal">
        <p className="metal-head"><span className="metal-title">Funded on Metal</span><span className="metal-badge">{view.label}</span></p>
        <p className="notice">{view.problem}</p>
      </section>
    );
  }
  const m = view.mandate ?? null;
  const pull = view.pull ?? null;
  const refusals = view.refusals ?? [];
  const can = view.can ?? null;
  const check = pull?.verification ?? null;
  const whole = m?.verification ?? null;
  return (
    <section className="metal" aria-label="Funded on Metal">
      <p className="metal-head">
        <span className="metal-title">Funded on Metal</span>
        <span className="metal-badge">{view.network}</span>
      </p>
      <p className="metal-scale">{view.scale?.words}</p>

      {!m && <p className="quiet">The holder chose Metal for this claim. No mandate has been signed yet.</p>}
      {m && (
        <>
          <p className="metal-line">
            <strong>{holder ? "Your mandate" : "The holder's mandate"}</strong>{" "}
            <span className={`metal-status metal-status-${m.status}`}>{STATUS_WORDS[m.status]}</span>{" "}
            <Chain value={m.bind_transaction} href={m.bind_explorer} />
            {m.revoke_transaction && <> · revoked in <Chain value={m.revoke_transaction} href={m.revoke_explorer} /></>}
          </p>
          {!m.for_current_approval && m.status === "bound" && (
            <p className="tie-problem">This mandate was signed for an earlier approval. The agent does not pull under it. A new approval replaces it.</p>
          )}
          <table className="metal-terms">
            <thead>
              <tr><th>Term</th><th>{holder ? "Your approval" : "The holder's approval"}</th><th>The mandate, {m.terms[0]?.source ?? ""}</th><th aria-label="Same" /></tr>
            </thead>
            <tbody>
              {m.terms.map((t) => (
                <tr key={t.term} className={t.same ? undefined : "metal-differs"}>
                  <th scope="row">{t.term}</th>
                  <td>{t.approval}</td>
                  <td className={t.term === "Who may be paid" ? "mono metal-wrap" : undefined}>{t.mandate}</td>
                  <td className={t.same ? "metal-same" : "metal-not-same"}>{t.same ? "Same" : "Differs"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {m.chain && (
            <p className="quiet metal-chain">
              On chain at {dateTime(m.chain.read_at)}: {m.chain.bound ? "bound" : "not bound"}, {m.chain.revoked ? "revoked" : "not revoked"},{" "}
              {m.chain.spent_usdz} of {m.chain.budget_usdz} *USDZ spent, {m.chain.payments} {m.chain.payments === 1 ? "payment" : "payments"}.{" "}
              The holder's account: <Chain value={view.accounts?.holder_account} href={view.accounts?.holder_explorer} />.
            </p>
          )}
          {m.chain_problem && <p className="tie-problem">The chain could not be read just now: {m.chain_problem}</p>}
        </>
      )}

      {pull && (
        <div className={pull.checked ? "metal-pull metal-pull-ok" : "metal-pull"}>
          <p className="metal-line">
            <strong>The pull</strong>{" "}
            {pull.amount_usdz} *USDZ, standing for {Number(pull.approved_usd).toLocaleString("en-US", { minimumFractionDigits: 2 })} USD of this claim.{" "}
            <Chain value={pull.transaction} href={pull.explorer} />
          </p>
          {pull.settlement && (
            <p className="quiet">
              Read from the chain: {pull.settlement.status}, block {pull.settlement.block}.{" "}
              {pull.settlement.transfers.map((t) => `${t.amount_usdz} *USDZ from ${short(t.from)} to ${short(t.to)}`).join("; ")}.
            </p>
          )}
          {check && (
            <p className={check.verified ? "metal-verified" : "tie-problem"}>
              Metal's own verification ({"metal-agent mandate verify"}): {check.verified ? "passed" : "did not pass"}
              {check.steps.length > 0 && `, ${check.steps.filter((s) => s.result === "pass").length} of ${check.steps.length} steps`}.
            </p>
          )}
          {check && check.steps.length > 0 && (
            <details className="fold metal-fold">
              <summary>The four steps Metal checked</summary>
              <ol className="metal-steps">
                {check.steps.map((s) => (
                  <li key={s.step}><strong>{s.result}</strong> {s.title}{s.detail && <span className="quiet"> {s.detail}</span>}</li>
                ))}
              </ol>
            </details>
          )}
          {pull.checked && (
            <p className="quiet">
              The Airwallex sandbox cannot receive *USDZ. The same amount was credited there as a simulated deposit whose reference is this transaction hash; one hash funds one claim once.
            </p>
          )}
          {pull.problem && <p className="tie-problem">Not accepted as funding: {pull.problem}</p>}
        </div>
      )}

      {refusals.length > 0 && (
        <div className="metal-refusals">
          <p className="panel-label">Refused by Metal. Nothing moved</p>
          <ul>
            {refusals.map((r, i) => (
              <li key={i}>
                <span className="metal-reason">{r.reason}</span>
                <span>{r.staged ? `Staged: ${r.case.toLowerCase()}` : "The agent's pull for this claim"}: {r.amount_usdz} *USDZ to {short(r.payee)}. Metal: {r.words}.</span>
                <Chain value={r.transaction} href={r.explorer} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {whole && (
        <p className={whole.verified ? "metal-verified" : "tie-problem"}>
          Whole mandate verified from the chain at {dateTime(whole.at)}: {whole.verified ? "passed" : "did not pass"}.{" "}
          {whole.lines.filter((l) => l.kind === "payment").length} payment, {whole.lines.filter((l) => l.kind === "refusal").length} recorded refusals.
        </p>
      )}

      {problem && <p className="notice">{problem}</p>}
      {busy && <Waiting>{busy}</Waiting>}
      {can && !busy && (
        <div className="metal-actions">
          {can.sign && (
            <button type="button" className="primary primary-small" onClick={() => act("Signing the mandate on Metal.", () => signMandate(claimId))}>
              Sign the mandate for this approval
            </button>
          )}
          {can.attempts.length > 0 && <span className="quiet">Tell the agent to overstep, and see Metal refuse:</span>}
          {can.attempts.map((a) => (
            <button key={a.key} type="button" className="secondary secondary-flat" onClick={() => act("The agent is trying. Metal decides.", () => attemptPull(claimId, a.key))}>
              {a.label}
            </button>
          ))}
          {can.verify && (
            <button type="button" className="secondary secondary-flat" onClick={() => act("Reading the chain.", () => verifyMandate(claimId))}>
              Verify the mandate from the chain
            </button>
          )}
          {can.revoke && (
            <button type="button" className="secondary secondary-flat metal-revoke" onClick={() => act("Revoking the mandate on Metal.", () => revokeMandate(claimId))}>
              Revoke the mandate
            </button>
          )}
        </div>
      )}

      {(view.earlier_mandates ?? []).length > 0 && (
        <details className="fold metal-fold">
          <summary>Earlier mandates on this claim</summary>
          <ul className="metal-earlier">
            {(view.earlier_mandates ?? []).map((e) => (
              <li key={e.seq}>
                Mandate {e.seq}: {STATUS_WORDS[e.status].toLowerCase()}{e.revoked_because ? ` (${e.revoked_because})` : ""}. Bound in{" "}
                <Chain value={e.bind_transaction} href={e.bind_explorer} />
                {e.revoke_transaction && <>, revoked in <Chain value={e.revoke_transaction} href={e.revoke_explorer} /></>}.
              </li>
            ))}
          </ul>
        </details>
      )}
      {view.enforced && (
        <details className="fold metal-fold">
          <summary>What the chain enforces, and what Khutlisa's code does</summary>
          <p className="panel-label">Enforced by the holder's Metal account, on chain</p>
          <ul className="lines">{view.enforced.by_chain.map((line) => <li key={line} className="reason">{line}</li>)}</ul>
          <p className="panel-label">Done by Khutlisa's code</p>
          <ul className="lines">{view.enforced.by_code.map((line) => <li key={line}>{line}</li>)}</ul>
        </details>
      )}
    </section>
  );
}
