import { useEffect, useRef, useState, type FormEvent } from "react";
import { addDocument, createClaim, getClaim, getCountries, getDocumentKinds, markFiled, removeDocument, setPayee, getPlanPreview } from "../api";
import BankDetails from "../components/BankDetails";
import DecisionCard from "../components/DecisionCard";
import Masthead from "../components/Masthead";
import { isDemonstration, useDemo } from "../demo";
import Waiting from "../components/Waiting";
import { dateTime, exact, fileSize, money, plainPropertyType, sentence, stateWords, toYou } from "../format";
import type { DeadlineCard, DemoDocument, DemoPerson, PlanPreview } from "../types";
import type { Claim, ClaimDocument, Claimant, CountryName, DocumentKind, History, Match, Proof, ProofCard, ProofStatus } from "../types";

const PROOF_WORDS: Record<ProofStatus, string> = { satisfied: "Proven", partly: "Partly proven", missing: "Still needed" };

const CHECK_WORDS: Record<ProofCard["checks"][number]["status"], string> = {
  passed: "passed",
  failed: "failed",
  held: "held for a person to look at",
  not_applicable: "does not apply",
  not_checked: "not checked",
};

/** One uploaded document: what was read from it, any concerns, and the requirements it is tied to. */
function DocumentCard({ doc, card, onRemove }: { doc: ClaimDocument; card?: ProofCard; onRemove?: () => void }) {
  const r = doc.reading;
  const waiting = r.status === "reading";
  const addresses = (r.addresses ?? []).map((a) => ({
    whose: a.whose === "issuer" ? "Issuer's address" : "Address",
    line: [a.street, a.city, [a.region, a.postcode].filter(Boolean).join(" "), a.country].filter(Boolean).join(", "),
  }));
  const concerns = card?.concerns ?? r.concerns ?? [];
  return (
    <li className={waiting ? "doc doc-waiting" : "doc"}>
      <header className="doc-head">
        <div>
          <p className="doc-name">{doc.filename}</p>
          <p className="doc-meta">
            Added as {doc.kind_label.toLowerCase()}, {fileSize(doc.size)}.
          </p>
        </div>
        <p className={`doc-state doc-state-${card?.held ? "held" : r.status}`}>
          {r.status === "reading" && "Being read"}
          {r.status === "read" &&
            (card?.held ? "Held for a person to look at" : card?.read === "twice" ? "Read twice" : card?.read === "once" ? "Read once" : "Read")}
          {r.status === "unreadable" && "Could not be made out"}
          {r.status === "failed" && "Not read"}
          {r.status === "not_read" && "Stored, not read"}
        </p>
      </header>

      {waiting && <Waiting>Reading what is printed on this document.</Waiting>}
      {r.status === "failed" && <p className="doc-concern">{r.problem ?? "The document could not be read."} Add it again to try once more.</p>}
      {r.status === "unreadable" && <p className="doc-concern">Nothing could be read from this file. A sharper, complete photo or scan is needed.</p>}

      {r.status === "read" && (
        <details className="doc-more">
          <summary>What was read from it</summary>
          {r.summary && <p className="doc-summary">{r.summary}</p>}
          <dl className="doc-read">
            {r.document_type && (
              <div>
                <dt>It is</dt>
                <dd>{sentence(r.document_type).replace(/\.$/, "")}</dd>
              </div>
            )}
            {(r.names ?? []).length > 0 && (
              <div>
                <dt>{r.names!.length === 1 ? "Name" : "Names"}</dt>
                <dd>{r.names!.join("; ")}</dd>
              </div>
            )}
            {r.issuer && (
              <div>
                <dt>Issued by</dt>
                <dd>{r.issuer}</dd>
              </div>
            )}
            {addresses.map((a, i) => (
              <div key={i}>
                <dt>{a.whose}</dt>
                <dd>{a.line}</dd>
              </div>
            ))}
            {(r.dates ?? []).length > 0 && (
              <div>
                <dt>Dates</dt>
                <dd>{r.dates!.map((d) => (d.label ? `${d.label} ${d.value}` : d.value)).join("; ")}</dd>
              </div>
            )}
            {(r.identifiers_present ?? []).length > 0 && (
              <div>
                <dt>Numbers on it</dt>
                <dd>{r.identifiers_present!.join(", ")}. The numbers themselves are not kept.</dd>
              </div>
            )}
          </dl>
        </details>
      )}

      {card && card.checks.length > 0 && (
        <ul className="doc-checks" aria-label="Checks made in code on this document">
          {card.checks.map((c) => (
            <li key={c.key} className={`doc-check doc-check-${c.status}`} title={c.text}>
              <strong>
                {c.title}: {CHECK_WORDS[c.status]}.
              </strong>
              {c.status !== "passed" && ` ${c.text}`}
            </li>
          ))}
        </ul>
      )}

      {concerns.length > 0 && (
        <ul className="doc-concerns" aria-label="Points a careful clerk would question">
          <li className="doc-concerns-head">
            {card?.holds_the_file_back
              ? "Points a careful clerk would question. This document holds the whole proof file back until it is removed"
              : "Points a careful clerk would question. A document with an open point settles nothing"}
          </li>
          {concerns.map((c, i) => (
            <li key={i}>{sentence(c)}</li>
          ))}
        </ul>
      )}

      {card && !waiting && card.supports.length > 0 && (
        <ul className="ties" aria-label="What this document is tied to">
          {card.supports.map((t) => (
            <li key={t.key} className={t.settles ? "tie tie-yes" : "tie"}>
              <span className="tie-line" aria-hidden="true" />
              <div className="tie-end">
                <p className="tie-title">
                  {t.settles ? "Proves" : "Offered for"}: {t.title}
                </p>
                {t.facts.map((f, i) => (
                  <p key={`f${i}`} className="tie-fact">{f}</p>
                ))}
                {t.problems.map((f, i) => (
                  <p key={`p${i}`} className="tie-problem">{f}</p>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      {card && r.status === "read" && card.supports.length === 0 && (
        <p className="doc-meta doc-untied">Nothing read from this document ties it to a requirement of this claim.</p>
      )}
      {onRemove && !waiting && (
        <button type="button" className="plain doc-remove" onClick={onRemove}>
          Remove this document from the proof file
        </button>
      )}
    </li>
  );
}

interface Props {
  /** Set once a claim exists. Without it the screen asks for the claimant's details first. */
  claimId: string | null;
  /** The record chosen on the search screen, and the history that found it. Only needed before the claim exists. */
  chosen: { match: Match; history: History } | null;
  onCreated: (id: string) => void;
  onPayout: (id: string) => void;
  onHome: () => void;
  onBackToSearch: () => void;
}

type Tab = "proof" | "bank" | "packet" | "more";
// The main path is proof, bank account, payment by the holder. The packet for the State is the fallback, kept last and apart.
const TABS: [Tab, string][] = [["proof", "Proof"], ["bank", "Bank account"], ["more", "History"], ["packet", "If the holder does not pay"]];

/** The demonstration person whose claim this is, by the name the claim is in. */
const personFor = (people: DemoPerson[], name: string | undefined) => people.find((p) => p.claimant.name === name) ?? null;

const emptyClaimant = (country: string): Claimant => ({ name: "", address: "", country, email: "", relationship: "self" });

export default function ClaimScreen({ claimId, chosen, onCreated, onPayout, onHome, onBackToSearch }: Props) {
  const [claim, setClaim] = useState<Claim | null>(null);
  const [preview, setPreview] = useState<PlanPreview | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [countries, setCountries] = useState<CountryName[]>([]);
  const [kinds, setKinds] = useState<DocumentKind[]>([]);
  const [claimant, setClaimant] = useState<Claimant>(() => emptyClaimant(chosen?.history.current_country ?? ""));
  const [kind, setKind] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [changingBank, setChangingBank] = useState(false);
  const [tab, setTab] = useState<Tab>("proof");
  const [adding, setAdding] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const { people, person: followed } = useDemo();

  /** Adds one of the demonstration person's sample documents, fetched from this server, to the proof file. */
  const addSample = async (doc: DemoDocument) => {
    if (!claim) return;
    setAdding(doc.file);
    setProblem("");
    try {
      const picture = await (await fetch(`/samples/${doc.file}`)).blob();
      setClaim(await addDocument(claim.id, doc.kind, new File([picture], doc.file, { type: picture.type || "image/png" })));
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setAdding("");
    }
  };

  useEffect(() => {
    getCountries().then(setCountries).catch(() => setCountries([]));
    getDocumentKinds().then(setKinds).catch(() => setKinds([]));
  }, []);

  // The payout plan in summary, from the start: what the amount would become today, and what has to happen first.
  const planKey = claim ? `${claim.id}|${claim.state}|${claim.payee?.account_number ?? ""}` : "";
  useEffect(() => {
    if (!claim || !["FOUND", "PROOF_NEEDED", "PROOF_READY", "PACKET_READY", "FILED"].includes(claim.state)) {
      setPreview(null);
      return;
    }
    let live = true;
    getPlanPreview(claim.id).then((p) => live && setPreview(p)).catch(() => live && setPreview(null));
    return () => {
      live = false;
    };
  }, [planKey]);

  // Keep the claim fresh, so a decision made in the holder's view shows up here without a reload.
  useEffect(() => {
    if (!claimId) return;
    let live = true;
    const load = () =>
      getClaim(claimId)
        .then((c) => live && setClaim(c))
        .catch((e: Error) => live && setProblem(e.message));
    void load();
    const timer = window.setInterval(load, 1500);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [claimId]);

  // A message about the form goes away as soon as the person changes the form.
  useEffect(() => {
    if (!claimId) setProblem("");
  }, [claimant, claimId]);

  const open = async (event: FormEvent) => {
    event.preventDefault();
    if (!chosen) return;
    setBusy(true);
    setProblem("");
    try {
      const made = await createClaim(chosen.match, claimant, chosen.history);
      setClaim(made);
      onCreated(made.id);
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!claim || !file || !kind) {
      setProblem("Choose a file and say what kind of document it is.");
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      setClaim(await addDocument(claim.id, kind, file));
      setFile(null);
      setKind("");
      if (fileInput.current) fileInput.current.value = "";
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sent = async () => {
    if (!claim) return;
    setBusy(true);
    setProblem("");
    try {
      setClaim(await markFiled(claim.id));
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // ---- before the claim exists: the claimant's own details ----
  if (!claimId) {
    if (!chosen) {
      return (
        <main className="flow">
          <Masthead now="proof" onHome={onHome} go={{ history: onBackToSearch, matches: onBackToSearch }} />
          <div className="flow-body flow-narrow">
            <p className="notice">No record has been chosen yet. Search your history first, then choose a match.</p>
            <button type="button" className="secondary" onClick={onBackToSearch}>
              Go to the search
            </button>
          </div>
        </main>
      );
    }
    const m = chosen.match;
    const sampleRecord = isDemonstration(m.source);
    // The demonstration person this search was about, by the given names searched for.
    const said = chosen.history.given_names.map((g) => g.toLowerCase());
    const fillFrom = people.find((p) => said.some((g) => g.length > 2 && p.claimant.name.toLowerCase().includes(g))) ?? followed;
    return (
      <main className="flow onescreen">
        <Masthead now="proof" onHome={onHome} go={{ history: onBackToSearch, matches: onBackToSearch }} />
        <div className="flow-body flow-two">
          <section>
            <h1>Open your claim</h1>
            <p className="quiet">Your own details. They go to the holder that pays the claim, and nowhere else.</p>
            <form onSubmit={open} noValidate>
              {sampleRecord && fillFrom && (
                <button type="button" className="fill-for-me" onClick={() => setClaimant({ ...fillFrom.claimant })}>
                  Fill this in for {fillFrom.short_name}
                </button>
              )}
              <fieldset>
                <legend>About you</legend>
                <label className="field">
                  <span>Your name as you use it now</span>
                  <input value={claimant.name} onChange={(e) => setClaimant({ ...claimant, name: e.target.value })} autoComplete="name" autoFocus />
                </label>
                <label className="field">
                  <span>Your current address</span>
                  <textarea rows={2} value={claimant.address} onChange={(e) => setClaimant({ ...claimant, address: e.target.value })} autoComplete="street-address" />
                </label>
                <div className="row row-even">
                  <label className="field">
                    <span>Country you live in</span>
                    <select value={claimant.country} onChange={(e) => setClaimant({ ...claimant, country: e.target.value })}>
                      <option value="">Choose a country</option>
                      {countries.map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Email address</span>
                    <input type="email" value={claimant.email} onChange={(e) => setClaimant({ ...claimant, email: e.target.value })} autoComplete="email" />
                  </label>
                </div>
              </fieldset>
              <fieldset>
                <legend>Whose money is it?</legend>
                <label className="choice">
                  <input type="radio" name="relationship" checked={claimant.relationship === "self"} onChange={() => setClaimant({ ...claimant, relationship: "self" })} />
                  <span>It is mine. I am the owner named on the record, or I sign for the organisation that is.</span>
                </label>
                <label className="choice">
                  <input type="radio" name="relationship" checked={claimant.relationship === "heir"} onChange={() => setClaimant({ ...claimant, relationship: "heir" })} />
                  <span>The owner has died and I am an heir.</span>
                </label>
              </fieldset>
              {problem && <p className="notice form-notice">{problem}</p>}
              <div className="actions">
                <button type="submit" className="primary" disabled={busy}>
                  {busy ? "Opening the claim" : "Open my claim"}
                </button>
                <button type="button" className="plain" onClick={onBackToSearch}>
                  Back to the matches
                </button>
              </div>
            </form>
          </section>
          <aside className="panel">
            <p className="panel-label">The record you chose</p>
            <p className="panel-amount">{money(m.amount, m.currency, true)}</p>
            <p className={m.owner_is_organisation ? "owner" : "owner owner-masked"}>{m.owner}</p>
            <p className="owner-note">
              {sampleRecord ? "Demonstration record" : m.owner_is_organisation ? "Organisation named in the public register" : "Name hidden until the claim is proven"}
            </p>
            <dl className="facts facts-stack">
              <div>
                <dt>Reported by</dt>
                <dd>{m.holder_name || "Not stated"}</dd>
              </div>
              <div>
                <dt>Kind of money</dt>
                <dd>{plainPropertyType(m.property_type) || "Not stated"}</dd>
              </div>
            </dl>
          </aside>
        </div>
      </main>
    );
  }

  if (!claim) {
    return (
      <main className="flow">
        <Masthead now="proof" onHome={onHome} go={{ history: onBackToSearch, matches: onBackToSearch }} />
        <div className="flow-body flow-narrow">
          {problem ? <p className="notice">{problem}</p> : <div className="results-empty"><Waiting counted={false}>Opening your claim.</Waiting></div>}
        </div>
      </main>
    );
  }

  // ---- the claim: proof file, packet, and where it stands ----
  const need = claim.checklist;
  const r = claim.record;
  const proof: Proof | null = claim.proof.assessed ? (claim.proof as Proof) : null;
  const done = proof ? proof.satisfied : need.attached;
  const total = proof ? proof.required : need.required;
  const complete = proof ? proof.ready : need.complete;
  const beforeDecision = ["FOUND", "PROOF_NEEDED", "PROOF_READY", "PACKET_READY", "FILED"].includes(claim.state);
  // Documents and the bank account can still be changed after an approval, but doing so withdraws it.
  const open_ = beforeDecision || claim.state === "APPROVED";
  const step = tab === "bank" || complete || ["APPROVED", "PAYING", "PAID", "PAYMENT_HELD"].includes(claim.state) ? "claim" : "proof";
  const canPay = ["APPROVED", "PAYING", "PAID", "PAYMENT_HELD"].includes(claim.state);
  const withdrawn = claim.approvals_withdrawn[claim.approvals_withdrawn.length - 1];
  const deadline = (claim as Claim & { deadline?: DeadlineCard | null }).deadline ?? null;
  const remove = async (documentId: string) => {
    setProblem("");
    try {
      setClaim(await removeDocument(claim.id, documentId));
    } catch (e) {
      setProblem((e as Error).message);
    }
  };
  const reading = claim.documents.filter((d) => d.reading.status === "reading").length;
  const demoPerson = claim.sample ? personFor(people, claim.claimant.name) : null;
  const added = new Set(claim.documents.map((d) => d.filename));
  const shownTab: Tab = tab;
  const next: [Tab, string] | null = tab === "proof" && complete && !claim.payee ? ["bank", "Next: the bank account"] : null;
  return (
    <main className="flow onescreen">
      <Masthead
        now={step}
        onHome={onHome}
        go={{
          history: onBackToSearch, matches: onBackToSearch, proof: () => setTab("proof"), claim: () => setTab("bank"),
          payment: canPay ? () => onPayout(claim.id) : undefined,
        }}
      />
      <div className="flow-body claim-body">
        <header className="claim-head claim-head-tight">
          <div>
            <p className="summary-label">Your claim, number {claim.id}</p>
            <p className="summary-text">
              <span className="summary-amount">{money(r.amount, r.currency, true)}</span> reported by {r.holder_name || "a holder that is not named"}.
            </p>
            {claim.claimant.relationship === "heir" && !r.owner_is_organisation && (
              <p className="quiet">
                Has the owner died? <a style={{ color: "var(--gold)" }} href={`#estate/${claim.id}`}>Open the estate view</a>: the family, each heir's share, and one settlement for all of them.
              </p>
            )}
          </div>
          <div className="tabs" role="tablist" aria-label="Parts of your claim">
            {TABS.map(([id, words]) => (
              <button key={id} type="button" role="tab" aria-selected={shownTab === id} className={`tab${shownTab === id ? " tab-on" : ""}${id === "packet" ? " tab-fallback" : ""}`} onClick={() => setTab(id)}>
                {words}
              </button>
            ))}
          </div>
          <p className={`state state-${claim.state.toLowerCase()}`}>{stateWords(claim.state)}</p>
        </header>

        {preview && tab !== "packet" && (
          <section className="money-strip" aria-label="The payout plan in summary">
            <p className="money-strip-main">
              {preview.available && preview.would_receive ? (
                <>
                  Paid by the holder into your own account, {exact(preview.claim.amount, preview.claim.currency)} would be about{" "}
                  <strong className="money-strip-amount">{exact(preview.would_receive.amount, preview.would_receive.currency)}</strong> today.{" "}
                  <span className="plan-tag">A plan, not a payment: the rate is not locked yet.</span>
                </>
              ) : (
                <>{preview.reason}</>
              )}
            </p>
          </section>
        )}

        {claim.state === "APPROVED" && claim.approval && (
          <section className="callout">
            <div>
              <h2>The holder has approved your claim</h2>
              <p>
                It covers exactly {exact(claim.approval.amount, claim.approval.currency)} to {claim.payee?.account_name}, account {claim.payee?.account_number}.
              </p>
            </div>
            <button type="button" className="primary" onClick={() => onPayout(claim.id)}>
              See the payout plan
            </button>
          </section>
        )}
        {claim.state === "PAYMENT_HELD" && (
          <section className="callout">
            <div>
              <h2>Your payment is on hold</h2>
              <p>Something changed after the holder approved it.</p>
            </div>
            <button type="button" className="primary" onClick={() => onPayout(claim.id)}>
              See what happened
            </button>
          </section>
        )}
        {!claim.approval && withdrawn && claim.state !== "PAYMENT_HELD" && claim.state !== "REJECTED" && (
          <p className="notice">The holder's approval was withdrawn, because {withdrawn.because}. The holder has to approve again.</p>
        )}
        {claim.line.paid_elsewhere && claim.state !== "PAID" && (
          <p className="notice">This property has already been paid out on another claim, so it cannot be paid again.</p>
        )}
        {!claim.line.paid_elsewhere && claim.line.ahead > 0 && beforeDecision && (
          <p className="notice">
            {claim.line.ahead === 1 ? "An earlier claim is" : `${claim.line.ahead} earlier claims are`} open on the same
            property. A property is paid once, so this claim waits until the holder has decided{" "}
            {claim.line.ahead === 1 ? "that one" : "those"}.
          </p>
        )}
        {(claim.state === "PAYING" || claim.state === "PAID") && (
          <section className="callout">
            <div>
              <h2>{claim.state === "PAID" ? "This claim has been paid on the Airwallex sandbox" : "Your payment is under way"}</h2>
            </div>
            <button type="button" className="primary" onClick={() => onPayout(claim.id)}>
              See the payment
            </button>
          </section>
        )}
        {claim.state === "REJECTED" && (
          <p className="notice">The holder rejected this claim and gave this reason: {claim.rejection_reason}</p>
        )}
        {problem && <p className="notice">{problem}</p>}

        {shownTab === "proof" && deadline && deadline.choice !== "pay" && beforeDecision && (
          <div className="claim-deadline">
            <DecisionCard card={deadline} />
            {deadline.choice === "release" && (
              <button type="button" className="secondary secondary-flat" onClick={() => setTab("packet")}>
                Claim it from the State yourself
              </button>
            )}
          </div>
        )}
        {shownTab === "proof" && (
        <div className="flow-two claim-cols">
          <section id="proof-file" className="pane">
            <div className="proof-head">
              <h2>Proof file</h2>
              {proof && <p className={proof.ready ? "verdict verdict-ready" : "verdict"}>{proof.ready ? "Ready" : proof.status === "held for a person to look at" ? "Held for a person to look at" : "Not ready"}</p>}
            </div>
            <p className="quiet">
              {proof
                ? proof.summary
                : need.complete
                  ? `All ${need.required} documents this claim needs are attached.`
                  : `${need.attached} of ${need.required} documents this claim needs are attached.`}
            </p>
            <div className="meter" role="img" aria-label={`${done} of ${total} required items ${proof ? "proven" : "attached"}`}>
              <span style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
            </div>
            {proof?.record_link && (
              <p className={proof.record_link.status === "matched" ? "record-link record-link-yes" : "record-link"}>{proof.record_link.text}</p>
            )}

            <ul className="checklist">
              {need.items.map((item) => {
                const status: ProofStatus = item.proof ?? (item.status === "attached" ? "satisfied" : "missing");
                return (
                  <li key={item.key} className={`check check-${status}`}>
                    <span className="check-status">{proof ? PROOF_WORDS[status] : item.status === "attached" ? "Attached" : "Still needed"}</span>
                    <div>
                      <p className="check-title">{item.title}</p>
                      {!item.required && <p className="check-optional">Asked for if you have it.</p>}
                      <p className="check-detail">{item.detail}</p>
                      {[...(item.supports ?? [])].sort((a, b) => Number(b.settles) - Number(a.settles)).map((sup) => (
                        <div key={sup.document_id} className={sup.settles ? "support support-yes" : "support"}>
                          <p className="support-file">{sup.filename}</p>
                          {sup.facts.map((f, i) => (
                            <p key={`f${i}`} className="tie-fact">{f}</p>
                          ))}
                          {sup.problems.map((f, i) => (
                            <p key={`p${i}`} className="tie-problem">{f}</p>
                          ))}
                        </div>
                      ))}
                      {!proof && item.files.length > 0 && <p className="check-files">File: {item.files.join(", ")}</p>}
                      {status === "missing" && <p className="check-files">Add it as: {item.kind_labels.join(" or ")}.</p>}
                    </div>
                  </li>
                );
              })}
            </ul>

            {proof && proof.gaps.length > 0 && (
              <div className="missing">
                <p className="panel-label">What is still missing</p>
                <ul className="gaps">
                  {proof.gaps.map((g) => (
                    <li key={g.key}>
                      <p>{g.text}</p>
                      <p className="gap-how">
                        {g.how}
                        {!g.required && " Asked for if you have it. It does not hold the claim back."}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!proof && !need.complete && (
              <div className="missing">
                <p className="panel-label">What is missing</p>
                <ul>
                  {need.missing.map((title) => (
                    <li key={title}>{title}</li>
                  ))}
                </ul>
              </div>
            )}

          </section>
          <section className="pane" id="documents">
            {open_ && (
              <form className="upload" onSubmit={upload}>
                <p className="panel-label">Add a document</p>
                {demoPerson && (
                  <div className="demo-docs">
                    <p className="demo-docs-title">{demoPerson.short_name}'s documents. Choose one to add it.</p>
                    <ul>
                      {demoPerson.documents.map((d) => (
                        <li key={d.file}>
                          <a href={`/samples/${d.file}`} target="_blank" rel="noreferrer" title="Open the picture">
                            <img src={`/samples/${d.file}`} alt="" />
                          </a>
                          <button type="button" className="fill-for-me" disabled={added.has(d.file) || adding !== ""} onClick={() => void addSample(d)}>
                            {added.has(d.file) ? "Added" : adding === d.file ? "Adding" : "Add"}
                          </button>
                          <span>{d.label}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <details className="own-file" open={!demoPerson}>
                <summary>Add a file from this computer</summary>
                <div className="row">
                  <label className="field">
                    <span>Photo or PDF, up to 15 MB</span>
                    <input ref={fileInput} type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                  </label>
                  <label className="field field-kind">
                    <span>What it is</span>
                    <select value={kind} onChange={(e) => setKind(e.target.value)}>
                      <option value="">Choose a kind</option>
                      {kinds.map((k) => (
                        <option key={k.kind} value={k.kind}>
                          {k.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button type="submit" className="secondary" disabled={busy || !file || !kind}>
                  {busy ? "Adding the document" : "Add to the proof file"}
                </button>
                {!busy && (!file || !kind) && <span className="upload-hint">Choose a file and say what it is first.</span>}
                <p className="slot-note">
                  {proof
                    ? "Each document is read by a hosted language model, then compared in code with your details and the record."
                    : "Document reading is switched off on this server, so each file is stored and the kind you choose is trusted."}
                  {claim.state === "APPROVED" && " Adding or removing a document now withdraws the holder's approval."}
                </p>
                </details>
              </form>
            )}

            {claim.documents.length > 0 && (
              <>
                <p className="panel-label">
                  Your documents{reading > 0 ? `, ${reading} still being read` : ""}
                </p>
                <ul className="docs">
                  {claim.documents.map((d) => (
                    <DocumentCard key={d.id} doc={d} card={proof?.documents.find((c) => c.id === d.id)}
                      onRemove={open_ ? () => void remove(d.id) : undefined} />
                  ))}
                </ul>
              </>
            )}
            {next && (
              <div className="actions">
                <button type="button" className="primary primary-small" onClick={() => setTab(next[0])}>{next[1]}</button>
              </div>
            )}
          </section>
        </div>
        )}

        {shownTab === "bank" && (
          <section id="bank-account" className="pane claim-single">
            <h2>Where the money should go</h2>
            <p className="quiet">Your own account. The holder approves this exact account, and a payment can go nowhere else.</p>
            {claim.payee && (
              <dl className="facts terms" id="payee-on-file">
                <div>
                  <dt>Account holder</dt>
                  <dd>{claim.payee.account_name}</dd>
                </div>
                <div>
                  <dt>Account</dt>
                  <dd>
                    <span className="mono">{claim.payee.account_number}</span>, {claim.payee.bank_country}, paid in {claim.payee.currency}
                  </dd>
                </div>
                <div>
                  <dt>Checked by</dt>
                  <dd>{claim.payee.checked_by}</dd>
                </div>
              </dl>
            )}
            {open_ && (!claim.payee || changingBank) && (
              <BankDetails claimantName={claim.claimant.name} fill={demoPerson} submitLabel={claim.payee ? "Use this account instead" : "Save this bank account"}
                onSubmit={async (details) => {
                  setClaim(await setPayee(claim.id, details));
                  setChangingBank(false);
                }} />
            )}
            {open_ && claim.payee && !changingBank && (
              <div className="actions">
                <button type="button" className="plain" onClick={() => setChangingBank(true)}>
                  Change the bank account
                </button>
                {claim.state === "APPROVED" && <p className="quiet">Changing it withdraws the holder's approval.</p>}
              </div>
            )}
            {claim.state === "PAYMENT_HELD" && <p className="quiet">The payment is on hold. Bank details are corrected on the payment screen.</p>}
            {claim.payee && beforeDecision && !changingBank && (
              <div className="sent-box holder-next">
                <p>{complete ? "The holder decides next." : "The holder decides once the proof is ready."}</p>
                <a className="secondary secondary-flat" href="/payer" target="_blank" rel="noreferrer">Open the holder's view</a>
              </div>
            )}
          </section>
        )}

        {shownTab === "packet" && (
        <div className="flow-two claim-cols">
          <section id="claim-packet" className="pane fallback">
            <p className="panel-label fallback-label">The fallback, off the main path</p>
            <h2>If the holder does not pay: claim it from the State yourself</h2>
            <p className="quiet">
              Khutlisa prepares a packet for you to sign and send to the State of California. The State pays by a cheque in the post.
            </p>
            <div className="actions">
              <a className="secondary secondary-flat fallback-link" href={claim.packet_url} onClick={() => window.setTimeout(() => getClaim(claim.id).then(setClaim).catch(() => undefined), 1200)}>
                Download the claim packet
              </a>
            </div>
            {claim.state === "PACKET_READY" && (
              <div className="sent-box">
                <p>If you have signed California's form and sent it yourself, you can note it here.</p>
                <button type="button" className="secondary secondary-flat" onClick={sent} disabled={busy}>
                  I have signed it and sent it myself
                </button>
              </div>
            )}

            <div className={need.notary.required ? "notary notary-yes" : "notary"}>
              <p className="check-title">{need.notary.title}</p>
              <p className="check-detail">{need.notary.detail}</p>
            </div>
          </section>
          <section className="pane">
            <h2>Signing and sending to the State</h2>
            <p className="panel-label">How California pays</p>
            <ul className="plain-list">
              {need.payment.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <p className="panel-label">The steps</p>
            <ol className="guide">
              {need.signing.map((s) => (
                <li key={s.title}>
                  <p className="check-title">{s.title}</p>
                  <p className="check-detail">{s.detail}</p>
                </li>
              ))}
            </ol>
          </section>
        </div>
        )}

        {shownTab === "more" && (
        <div className="flow-two claim-cols">
          <section className="pane">
            {claim.match && (
              <>
                <p className="panel-label">Why this record matches you</p>
                <ul className="lines">
                  {claim.match.reasons.map((line, i) => (
                    <li key={`r${i}`} className="reason">{sentence(toYou(line))}</li>
                  ))}
                  {claim.match.doubts.map((line, i) => (
                    <li key={`d${i}`} className="doubt">{sentence(toYou(line))}</li>
                  ))}
                </ul>
                {/* The street is compared on the server once photo identification has been read. Until then
                    this line says so; afterwards the result is one of the reasons or doubts above. */}
                {claim.address_check?.status === "waiting" && (
                  <p className="quiet">{toYou(claim.address_check.text)}</p>
                )}
              </>
            )}

          </section>
          <section className="pane">
            <p className="panel-label">What has happened so far</p>
            <ol className="events">
              {claim.history.map((e, i) => (
                <li key={i}>
                  <span className="event-when">{dateTime(e.at)}</span>
                  <span>{e.note}</span>
                </li>
              ))}
            </ol>

            <p className="source">
              Rules read on the California State Controller's own pages:{" "}
              {need.sources.map((s, i) => (
                <span key={s.url}>
                  {i > 0 && ", "}
                  <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
                </span>
              ))}
              .
            </p>
          </section>
        </div>
        )}
      </div>
    </main>
  );
}
