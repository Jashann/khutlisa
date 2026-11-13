import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Masthead from "../components/Masthead";
import DecisionCard from "../components/DecisionCard";
import Waiting from "../components/Waiting";
import { payerKey, setPayerKey } from "../api";
import { clock } from "../format";
import {
  addEstateDocument, agreeForHeir, approveEstate, confirmSettlement, getEstate, getSample, openEstate, planSettlement,
  putFamily, putHeir, putHeirPayee, removeEstateDocument, resumeSettlement, sampleFile, sayFamily,
} from "./api";
import type { Amount, EstateSample, EstateView, Family, HeirView, LegView, Person, RoundView, SampleBank, TreeNode } from "./types";
import "./estate.css";

type Tab = "family" | "proof" | "holder" | "settlement";

const ZERO_DECIMAL = new Set(["JPY", "KRW", "VND", "CLP"]);
/** "$1,539.46", "28,128.63 MXN", "160,911 JPY": an amount with the decimals its currency has. */
function figure(amount: string | number, currency: string): string {
  const digits = ZERO_DECIMAL.has(currency) ? 0 : 2;
  const text = new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(amount));
  return currency === "USD" ? `$${text}` : `${text} ${currency}`;
}
const fig = (a: Amount | null | undefined) => (a ? figure(a.amount, a.currency) : "");
const RELATION: Record<string, string> = { spouse: "Wife or husband", child: "Child", grandchild: "Grandchild", parent: "Parent", sibling: "Brother or sister", named: "Named", owner: "The owner" };
const STATUS_WORDS: Record<string, string> = { proven: "Proven", missing: "Missing", "not proven": "Not proven", held: "Held for a person", "being read": "Being read" };
const LEG_WORDS: Record<string, string> = {
  WAITING: "Waiting for the deposit", DEPOSIT_CONFIRMED: "Share set aside", CONVERTED: "In their currency", BENEFICIARY_READY: "Account checked",
  TRANSFER_CREATED: "Transfer made", SENT: "Sent", PAID: "Paid", HELD: "Waiting for a person", FAILED: "Refused by the bank",
};
const BANK_FIELDS: Record<string, [string, string][]> = {
  MXN: [["account_number", "CLABE (18 digits)"], ["state", "State (for example MX-JAL)"]],
  PHP: [["account_number", "Account number"], ["swift_code", "Bank's SWIFT code"]],
  GBP: [["account_number", "Account number (8 digits)"], ["sort_code", "Sort code (6 digits)"]],
  JPY: [["account_number", "Account number (7 digits)"], ["bank_code", "Bank code (4 digits)"], ["branch_code", "Branch code (3 digits)"], ["account_type", "Checking or Savings"]],
};

interface Props { claimId: string; onHome: () => void; onClaim: (id: string) => void }

/** The estate claim view: the family tree with each heir's share, the proof for each heir, the holder's
 *  decision, and the one settlement that pays every heir in their own country. */
export default function EstateScreen({ claimId, onHome, onClaim }: Props) {
  const [view, setView] = useState<EstateView | null>(null);
  const [sample, setSample] = useState<EstateSample | null>(null);
  const [tab, setTab] = useState<Tab>("family");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState("");
  const [picked, setPicked] = useState<string | null>(null);
  const chosenTab = useRef(false);

  const load = useCallback(() => getEstate(claimId).then(setView, (e: Error) => {
    // A claim by an heir that has not been opened as an estate yet becomes one here.
    if (/not an estate/.test(e.message)) return openEstate(claimId).then(setView, (err: Error) => setProblem(err.message));
    setProblem(e.message);
  }), [claimId]);

  useEffect(() => { void load(); getSample().then(setSample, () => setSample(null)); }, [load]);

  // While documents are being read or money is moving, look again every second and a half.
  const moving = !!view && (view.settlement.running || view.documents.some((d) => d.status === "reading")
    || view.settlement.rounds.some((r) => r.state === "FUNDING" || (r.state === "RUNNING" && r.legs.some((l) => !["PAID", "HELD", "FAILED"].includes(l.state)))));
  useEffect(() => {
    if (!moving) return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [moving, load]);

  // Land on the part of the journey the estate has reached, once.
  useEffect(() => {
    if (!view || chosenTab.current) return;
    chosenTab.current = true;
    if (view.settlement.started || view.settlement.plan || view.state === "APPROVED") setTab("settlement");
    else if (view.succession.computed && view.documents.length) setTab("proof");
  }, [view]);

  const run = async (label: string, work: () => Promise<EstateView | void>) => {
    setBusy(label);
    setProblem("");
    try {
      const got = await work();
      if (got) setView(got);
      else await load();
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  if (!view) {
    return (
      <div className="flow">
        <Masthead onHome={onHome} />
        <main className="flow-body">{problem ? <p className="notice">{problem}</p> : <Waiting counted={false}>Opening the estate.</Waiting>}</main>
      </div>
    );
  }
  const owner = view.family.decedent.name || "the owner";
  const paidCount = view.heirs.filter((h) => h.paid).length;
  return (
    <div className="flow estate">
      <Masthead onHome={onHome} note="When the owner has died" />
      <main className="flow-body estate-body">
        <header className="estate-head">
          <div>
            <p className="panel-label">The estate of</p>
            <h1 className="estate-owner">{view.family.decedent.name || view.record.owner}</h1>
            <p className="quiet">
              Held by {view.record.holder_name}. Claim opened by {view.claimant.name}.{" "}
              <button className="link-button" onClick={() => onClaim(view.claim_id)}>The claim itself</button>
            </p>
            {view.sample && <p className="estate-sample">Demonstration: this family and every document are invented, and each document is marked SAMPLE.</p>}
          </div>
          <div className="estate-amount">
            <p className="estate-amount-figure">{figure(view.amount, "USD")}</p>
            <p className="quiet">
              {view.heirs.length ? `${view.heirs.length} heirs in ${new Set(view.heirs.map((h) => h.country).filter(Boolean)).size} countries` : "Heirs not worked out yet"}
              {paidCount > 0 && `, ${paidCount} paid`}
            </p>
          </div>
        </header>

        <nav className="tabs estate-tabs" aria-label="Parts of the estate">
          {([["family", "1. Family and shares"], ["proof", "2. Proof for each heir"], ["holder", "3. The holder's decision"], ["settlement", "4. The settlement"]] as [Tab, string][]).map(([id, label]) => (
            <button key={id} className={tab === id ? "tab tab-on" : "tab"} onClick={() => setTab(id)} data-tab={id}>{label}</button>
          ))}
        </nav>
        {problem && <p className="notice" role="alert">{problem}</p>}
        {busy && <Waiting>{busy}</Waiting>}

        {tab === "family" && <FamilyTab view={view} sample={sample} picked={picked} onPick={setPicked} run={run} busy={!!busy} claimId={claimId} />}
        {tab === "proof" && <ProofTab view={view} sample={sample} run={run} busy={!!busy} claimId={claimId} />}
        {tab === "holder" && <HolderTab view={view} run={run} busy={!!busy} claimId={claimId} owner={owner} />}
        {tab === "settlement" && <SettlementTab view={view} sample={sample} run={run} busy={!!busy} claimId={claimId} />}
      </main>
    </div>
  );
}

type Run = (label: string, work: () => Promise<EstateView | void>) => Promise<void>;
interface TabProps { view: EstateView; run: Run; busy: boolean; claimId: string }

// ---- 1. the family and the shares -------------------------------------------------------------------------------

function FamilyTab({ view, sample, picked, onPick, run, busy, claimId }: TabProps & { sample: EstateSample | null; picked: string | null; onPick: (id: string | null) => void }) {
  const [words, setWords] = useState("");
  const [answer, setAnswer] = useState("");
  const [editing, setEditing] = useState(false);
  const said = view.intake.words;
  const q = view.question;
  const chosen = view.tree.find((n) => n.id === picked && n.heir) ?? view.tree.find((n) => n.heir) ?? null;
  const steps = chosen ? view.succession.steps.filter((s) => chosen.steps?.includes(s.n)) : [];
  const locked = ["PAYING", "PAID", "REJECTED"].includes(view.state);
  return (
    <section className="estate-section">
      {!said && !view.succession.computed && (
        <div className="panel estate-intake">
          <h2>Tell us who has died, and who the family is</h2>
          <p className="quiet">In your own language. Say whether there was a will, a husband or wife, how many children, and whether any child has died leaving children.</p>
          <textarea className="estate-words" value={words} onChange={(e) => setWords(e.target.value)} rows={5} placeholder="For example: My husband died on..." />
          <div className="actions">
            <button className="primary primary-small" disabled={busy || words.trim().length < 2} onClick={() => run("Reading the words and working out the shares.", () => sayFamily(claimId, words))}>Read my words</button>
            {view.sample && sample && <button className="secondary" onClick={() => setWords(sample.words)}>Use the demonstration family's words ({sample.language})</button>}
          </div>
        </div>
      )}
      {said && (
        <details className="panel estate-heard" open={!view.succession.computed}>
          <summary className="panel-label">What was said{view.intake.language ? `, in ${view.intake.language}` : ""}</summary>
          <p className="heard-own">{said}</p>
          {view.intake.english && <p className="heard-english quiet">{view.intake.english}</p>}
        </details>
      )}
      {q && (
        <div className="panel estate-question" data-question={q.key}>
          <p className="panel-label">One more thing the rule needs</p>
          <p className="follow-own">{q.question}</p>
          {q.in_their_language && <p className="follow-english quiet">{q.english}</p>}
          {!locked && (
            <div className="estate-answer">
              <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="The answer, in your own words" aria-label="The answer" />
              <button className="primary primary-small" disabled={busy || answer.trim().length < 2}
                onClick={() => run("Reading the answer and working out the shares.", async () => { const got = await sayFamily(claimId, answer, said, q.question); setAnswer(""); return got; })}>Answer</button>
              {view.sample && sample && <button className="secondary" onClick={() => setAnswer(sample.answer)}>Use the demonstration answer</button>}
            </div>
          )}
        </div>
      )}
      {view.succession.refusal && !q && (
        <div className="notice estate-refusal">
          <strong>Khutlisa does not work this estate out.</strong> {view.succession.refusal.reason}{" "}
          {view.succession.refusal.url && <a href={view.succession.refusal.url} target="_blank" rel="noreferrer">Probate Code {view.succession.refusal.section}</a>}
        </div>
      )}
      {view.other_law.flag && (
        <div className="notice estate-flag" data-flag="other_law">
          <strong>Other law may apply.</strong> {view.other_law.flag.text}{" "}
          <a href={view.other_law.flag.url} target="_blank" rel="noreferrer">Civil Code 946</a>
        </div>
      )}

      {view.tree.length > 1 && (
        <div className="estate-tree-wrap">
          <FamilyTree nodes={view.tree} picked={chosen?.id ?? null} onPick={onPick} />
          {chosen && (
            <aside className="panel estate-why" data-why={chosen.id}>
              <p className="panel-label">Why {chosen.name.split(" ")[0]} receives</p>
              <p className="estate-fraction">{chosen.share}</p>
              <p className="estate-why-amount">{figure(chosen.amount_usd ?? 0, "USD")}</p>
              <ol className="estate-steps">
                {steps.map((s) => (
                  <li key={s.n}>
                    <a href={s.url} target="_blank" rel="noreferrer" className="estate-section-link">Probate Code {s.section}</a>
                    <span>{s.text}</span>
                  </li>
                ))}
              </ol>
              <p className="quiet estate-rule">{view.rounding_rule}</p>
            </aside>
          )}
        </div>
      )}
      {!locked && (
        <details className="fold" open={editing} onToggle={(e) => setEditing((e.target as HTMLDetailsElement).open)}>
          <summary>Correct the family by hand</summary>
          {editing && <FamilyEditor family={view.family} sample={view.sample ? sample : null} busy={busy} onSave={(family) => run("Working the shares out again.", () => putFamily(claimId, family))} />}
        </details>
      )}
    </section>
  );
}

function FamilyTree({ nodes, picked, onPick }: { nodes: TreeNode[]; picked: string | null; onPick: (id: string) => void }) {
  const below = useMemo(() => {
    const map = new Map<string, TreeNode[]>();
    for (const n of nodes) if (n.parent) map.set(n.parent, [...(map.get(n.parent) ?? []), n]);
    return map;
  }, [nodes]);
  const owner = nodes.find((n) => n.kind === "owner")!;
  const branch = (node: TreeNode): React.ReactNode => {
    const kids = below.get(node.id) ?? [];
    return (
      <li key={node.id}>
        <NodeCard node={node} picked={picked === node.id} onPick={onPick} />
        {kids.length > 0 && <ul>{kids.map(branch)}</ul>}
      </li>
    );
  };
  return <div className="family-tree" role="tree"><ul>{branch(owner)}</ul></div>;
}

function NodeCard({ node, picked, onPick }: { node: TreeNode; picked: boolean; onPick: (id: string) => void }) {
  const relation = node.kind === "child" && node.relation ? node.relation : RELATION[node.kind];
  if (!node.heir) {
    return (
      <div className={`node ${node.kind === "owner" ? "node-owner" : "node-gone"}`}>
        <p className="node-name">{node.name || "Name not given"}</p>
        <p className="node-relation">{node.kind === "owner" ? `Died ${node.died_on || "on a date not given yet"}` : node.alive === false ? `${relation}, has died` : `${relation}`}</p>
      </div>
    );
  }
  const state = node.paid ? "paid" : node.payable ? "ready" : node.proven ? "proven" : "open";
  return (
    <button className={`node node-heir node-${state}${picked ? " node-picked" : ""}`} onClick={() => onPick(node.id)} data-heir={node.id} title="Show the statute steps behind this share">
      <p className="node-name">{node.name}</p>
      <p className="node-relation">{relation ? relation.charAt(0).toUpperCase() + relation.slice(1) : ""}{node.country ? `, ${node.country}` : ""}</p>
      <p className="node-share">{node.share}</p>
      <p className="node-usd">{figure(node.amount_usd ?? 0, "USD")}</p>
      <p className="node-local">{node.paid ? `Paid ${figure(node.paid.amount, node.paid.currency)}` : node.indicative_local ? `about ${fig(node.indicative_local)}` : node.currency ? node.currency : "Country not given yet"}</p>
      <p className={`node-proof node-proof-${state}`}>{node.paid ? "Paid" : node.payable ? "Proven, account given" : node.proven ? "Proven, no account yet" : `${node.missing} still missing`}</p>
    </button>
  );
}

const blank = (): Person => ({ id: "", name: "", alive: true, children: [] });

function FamilyEditor({ family, sample, busy, onSave }: { family: Family; sample: EstateSample | null; busy: boolean; onSave: (family: Partial<Family>) => void }) {
  const [draft, setDraft] = useState<Family>(() => structuredClone(family));
  const owner = draft.decedent;
  const setOwner = (change: Partial<Family["decedent"]>) => setDraft({ ...draft, decedent: { ...owner, ...change } });
  const setChild = (i: number, change: Partial<Person>) => setDraft({ ...draft, children: draft.children.map((c, n) => (n === i ? { ...c, ...change } : c)) });
  return (
    <div className="family-editor">
      <div className="row">
        <label className="field"><span>The person who died</span><input value={owner.name} onChange={(e) => setOwner({ name: e.target.value })} /></label>
        <label className="field field-short"><span>Date of death</span><input type="date" value={owner.died_on} onChange={(e) => setOwner({ died_on: e.target.value })} /></label>
        <label className="field field-short"><span>Lived in (country code)</span><input value={owner.domicile_country} maxLength={2} onChange={(e) => setOwner({ domicile_country: e.target.value.toUpperCase() })} data-field="domicile_country" /></label>
        <label className="field field-short"><span>State, if the United States</span><input value={owner.domicile_state} maxLength={2} onChange={(e) => setOwner({ domicile_state: e.target.value.toUpperCase() })} data-field="domicile_state" /></label>
      </div>
      <div className="row">
        <label className="field"><span>Will or court order</span>
          <select value={draft.disposition ?? ""} onChange={(e) => setDraft({ ...draft, disposition: (e.target.value || null) as Family["disposition"] })}>
            <option value="">Not said yet</option><option value="intestate">No will</option><option value="will">A will</option><option value="court_order">A court order of distribution</option>
          </select></label>
        <label className="field"><span>The money was</span>
          <select value={draft.property ?? ""} onChange={(e) => setDraft({ ...draft, property: (e.target.value || null) as Family["property"] })}>
            <option value="">Not said yet</option><option value="separate">The owner's own (separate property)</option><option value="community">Earned during the marriage (community property)</option>
          </select></label>
        <label className="field"><span>Married or partnered at death</span>
          <select value={draft.has_spouse === null ? "" : draft.has_spouse ? "yes" : "no"} onChange={(e) => setDraft({ ...draft, has_spouse: e.target.value === "" ? null : e.target.value === "yes", spouse: e.target.value === "yes" ? draft.spouse ?? { ...blank(), id: "s1" } : null })}>
            <option value="">Not said yet</option><option value="yes">Yes</option><option value="no">No</option>
          </select></label>
        {draft.has_spouse && draft.spouse && (
          <label className="field"><span>Husband, wife or partner</span><input value={draft.spouse.name} onChange={(e) => setDraft({ ...draft, spouse: { ...draft.spouse!, name: e.target.value } })} /></label>
        )}
      </div>
      <p className="panel-label">Children, counting any who have died</p>
      {draft.children.map((child, i) => (
        <div key={i} className="family-child">
          <div className="row">
            <label className="field"><span>Name</span><input value={child.name} onChange={(e) => setChild(i, { name: e.target.value })} /></label>
            <label className="field field-short"><span>Alive</span>
              <select value={child.alive === null ? "" : child.alive ? "yes" : "no"} onChange={(e) => setChild(i, { alive: e.target.value === "" ? null : e.target.value === "yes", children_known: true })}>
                <option value="">Not said</option><option value="yes">Yes</option><option value="no">No</option>
              </select></label>
            <label className="field field-short"><span>Lives in</span><input value={child.country ?? ""} maxLength={2} onChange={(e) => setChild(i, { country: e.target.value.toUpperCase() })} /></label>
            <button className="secondary-flat" onClick={() => setDraft({ ...draft, children: draft.children.filter((_, n) => n !== i) })}>Remove</button>
          </div>
          {child.alive === false && (
            <div className="family-grand">
              {(child.children ?? []).map((g, k) => (
                <div key={k} className="row">
                  <label className="field"><span>Child of {child.name || "this child"}</span><input value={g.name} onChange={(e) => setChild(i, { children: child.children!.map((x, n) => (n === k ? { ...x, name: e.target.value } : x)) })} /></label>
                  <label className="field field-short"><span>Lives in</span><input value={g.country ?? ""} maxLength={2} onChange={(e) => setChild(i, { children: child.children!.map((x, n) => (n === k ? { ...x, country: e.target.value.toUpperCase() } : x)) })} /></label>
                </div>
              ))}
              <button className="add" onClick={() => setChild(i, { children: [...(child.children ?? []), blank()], children_known: true })}>Add a child of {child.name || "this child"}</button>
            </div>
          )}
        </div>
      ))}
      <div className="actions">
        <button className="add" onClick={() => setDraft({ ...draft, children: [...draft.children, blank()], children_known: true })}>Add a child</button>
        {sample && <button className="secondary" onClick={() => setDraft({ ...structuredClone(family), ...(sample.family as Family) })}>Fill in the demonstration family</button>}
        <button className="primary primary-small" disabled={busy} onClick={() => onSave({ ...draft, children_known: true })}>Work out the shares</button>
      </div>
    </div>
  );
}

// ---- 2. the proof -------------------------------------------------------------------------------------------------

function Chip({ status }: { status: string }) {
  return <span className={`proof-chip proof-${status.replace(/ /g, "-")}`}>{STATUS_WORDS[status] ?? status}</span>;
}

function ProofTab({ view, sample, run, busy, claimId }: TabProps & { sample: EstateSample | null }) {
  const [kind, setKind] = useState("death_certificate");
  const upload = (files: { file: string; kind: string }[]) => run("Adding the documents. Each one is read twice.", async () => {
    let got: EstateView | undefined;
    for (const d of files) {
      if (view.documents.some((x) => x.filename === d.file)) continue;
      got = await addEstateDocument(claimId, d.kind, await sampleFile(d.file));
    }
    return got;
  });
  const locked = ["PAYING", "PAID", "REJECTED"].includes(view.state);
  const reading = view.documents.filter((d) => d.status === "reading").length;
  if (!view.succession.computed) return <p className="notice">The shares have to be worked out first. Describe the family on the first tab.</p>;
  return (
    <section className="estate-section">
      <div className="estate-proof-top">
        <div className="panel">
          <p className="panel-label">The estate</p>
          <ul className="proof-items">
            {view.estate_proof.items.map((item) => (
              <li key={item.key} data-item={item.key}>
                <Chip status={item.status} /> <strong>{item.label}</strong>
                <span className="quiet"> {item.facts[0] ?? item.problems[0] ?? ""}</span>
              </li>
            ))}
          </ul>
          <p className="risk-line quiet">{view.remaining_risk} <span className="risk-who">{view.decided_by}</span></p>
        </div>
        {!locked && (
          <div className="panel estate-upload">
            <p className="panel-label">Add a document</p>
            <div className="row">
              <label className="field"><span>What it is</span>
                <select value={kind} onChange={(e) => setKind(e.target.value)}>{view.document_kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}</select></label>
              <label className="field"><span>Photo or PDF</span>
                <input type="file" accept="image/*,application/pdf" disabled={busy} onChange={(e) => { const file = e.target.files?.[0]; if (file) void run("Adding the document. It is read twice.", () => addEstateDocument(claimId, kind, file)); e.target.value = ""; }} /></label>
            </div>
            {view.sample && sample && (
              <div className="actions">
                <button className="secondary" disabled={busy} data-demo="estate-docs" onClick={() => upload(sample.estate_documents)}>Add the demonstration death certificate</button>
              </div>
            )}
            {reading > 0 && <Waiting>{reading === 1 ? "One document is being read, twice." : `${reading} documents are being read, twice each.`}</Waiting>}
          </div>
        )}
      </div>
      <div className="heir-cards">
        {view.heirs.map((heir) => (
          <HeirCard key={heir.id} heir={heir} view={view} locked={locked} busy={busy} claimId={claimId} run={run}
            demo={view.sample ? sample?.heirs.find((h) => h.id === heir.id) ?? null : null} onDemoDocs={upload} />
        ))}
      </div>
      <details className="fold">
        <summary>The {view.documents.length} documents on file</summary>
        <ul className="estate-docs">
          {view.documents.map((d) => (
            <li key={d.id}>
              <strong>{d.kind_label}</strong> <span className="quiet">{d.filename}. {d.status === "reading" ? "Being read." : d.status === "read" ? (d.agreement === "agree" ? "Two readings agree." : "Read.") : "Could not be read."}</span>
              {d.people.length > 0 && <span className="quiet"> Names: {d.people.map((p) => `${p.name} (${p.role})`).join(", ")}.</span>}
              {!locked && <button className="secondary-flat" onClick={() => run("Removing the document.", async () => { await removeEstateDocument(claimId, d.id); })}>Remove</button>}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function HeirCard({ heir, view, locked, busy, claimId, run, demo, onDemoDocs }: {
  heir: HeirView; view: EstateView; locked: boolean; busy: boolean; claimId: string; run: Run;
  demo: EstateSample["heirs"][number] | null; onDemoDocs: (files: { file: string; kind: string }[]) => void;
}) {
  const currency = heir.currency ?? "";
  const [bank, setBank] = useState<SampleBank>(() => ({ currency, first_name: "", last_name: "", account_number: "", street_address: "", city: "", postcode: "" }));
  const [open, setOpen] = useState(false);
  const set = (key: string, value: string) => setBank({ ...bank, [key]: value });
  const state = heir.paid ? "paid" : heir.payable ? "ready" : heir.proven ? "proven" : "open";
  const fields = BANK_FIELDS[bank.currency || currency] ?? [];
  return (
    <article className={`panel heir-card heir-${state}`} data-heir-card={heir.id}>
      <header className="heir-head">
        <div>
          <p className="heir-name">{heir.name}</p>
          <p className="quiet">{heir.relation.charAt(0).toUpperCase() + heir.relation.slice(1)}{heir.country_name ? `, ${heir.country_name}` : ""}</p>
        </div>
        <div className="heir-share">
          <p className="heir-fraction">{heir.share}</p>
          <p className="heir-usd">{figure(heir.entitlement, "USD")}</p>
        </div>
      </header>
      <ul className="proof-items">
        {[heir.identity, ...heir.links].map((link) => (
          <li key={link.label}>
            <Chip status={link.status} /> <strong>{link.label}</strong>
            <span className="quiet"> {link.facts[0] ?? link.problems[0] ?? ""}</span>
          </li>
        ))}
        {heir.declaration.needed && (
          <li><Chip status={heir.declaration.status} /> <strong>Statement of the declaration's points</strong>
            {!locked && !heir.paid && (
              <label className="choice heir-declare"><input type="checkbox" checked={heir.declaration.status === "proven"} disabled={busy}
                onChange={(e) => run("Recording the statement.", () => putHeir(claimId, heir.id, { declared: e.target.checked }))} /> {heir.name.split(" ")[0]} states that the points are true</label>
            )}
          </li>
        )}
        <li><Chip status={heir.account.status} /> <strong>Bank account in {heir.name.split(" ")[0]}'s own name</strong>
          {heir.payee && <span className="quiet"> {heir.payee.currency} account ending {heir.payee.account_number.slice(-4)}. Checked by {heir.payee.checked_by ?? "Khutlisa"}.</span>}
        </li>
      </ul>
      {heir.paid && <p className="heir-paid">Paid {figure(heir.paid.amount, heir.paid.currency)}.</p>}
      {!heir.can_be_paid_here && heir.country && <p className="notice">This build does not pay in {heir.country_name} yet.</p>}
      {!locked && !heir.paid && (
        <div className="actions heir-actions">
          {demo && (
            <>
              <button className="secondary" disabled={busy} data-demo={`docs-${heir.id}`} onClick={() => onDemoDocs(demo.documents)}>Add {heir.name.split(" ")[0]}'s demonstration documents</button>
              <button className="secondary" disabled={busy} data-demo={`details-${heir.id}`} onClick={() => run("Checking the bank account with Airwallex.", async () => {
                await putHeir(claimId, heir.id, { country: demo.country, email: demo.email, declared: true });
                return putHeirPayee(claimId, heir.id, demo.bank);
              })}>Fill in {heir.name.split(" ")[0]}'s demonstration details</button>
            </>
          )}
          <button className="secondary-flat" onClick={() => setOpen(!open)}>{open ? "Close" : heir.payee ? "Change the bank account" : "Give the bank account"}</button>
        </div>
      )}
      {open && !locked && (
        <div className="heir-bank">
          <div className="row">
            <label className="field field-short"><span>Currency</span>
              <select value={bank.currency} onChange={(e) => set("currency", e.target.value)}><option value="">Choose</option>{view.corridors.map((c) => <option key={c.currency} value={c.currency}>{c.currency}, {c.place}</option>)}</select></label>
            <label className="field"><span>First name</span><input value={bank.first_name} onChange={(e) => set("first_name", e.target.value)} /></label>
            <label className="field"><span>Last name</span><input value={bank.last_name} onChange={(e) => set("last_name", e.target.value)} /></label>
          </div>
          <div className="row">
            {fields.map(([key, label]) => <label key={key} className="field"><span>{label}</span><input value={bank[key] ?? ""} onChange={(e) => set(key, e.target.value)} /></label>)}
          </div>
          <div className="row">
            <label className="field"><span>Street address</span><input value={bank.street_address} onChange={(e) => set("street_address", e.target.value)} /></label>
            <label className="field"><span>City</span><input value={bank.city} onChange={(e) => set("city", e.target.value)} /></label>
            <label className="field field-short"><span>Postcode</span><input value={bank.postcode} onChange={(e) => set("postcode", e.target.value)} /></label>
          </div>
          <button className="primary primary-small" disabled={busy || !bank.currency} onClick={() => run("Checking the bank account with Airwallex.", async () => { const got = await putHeirPayee(claimId, heir.id, bank); setOpen(false); return got; })}>Save the bank account</button>
        </div>
      )}
    </article>
  );
}

// ---- 3. the holder's decision ---------------------------------------------------------------------------------------

function HolderTab({ view, run, busy, claimId, owner }: TabProps & { owner: string }) {
  const [key, setKey] = useState(payerKey());
  const [unlocked, setUnlocked] = useState(() => payerKey() !== "");
  const [reason, setReason] = useState("");
  const flag = view.other_law.flag;
  const waitingAccount = view.settlement.rounds.at(-1)?.legs.filter((l) => l.hold?.needs.includes("payer")) ?? [];
  const canApprove = !view.approval && ["FOUND", "PROOF_NEEDED", "PROOF_READY", "PACKET_READY", "FILED", "PAYMENT_HELD"].includes(view.state);
  return (
    <section className="estate-section">
      {!unlocked ? (
        <form className="panel estate-key" onSubmit={(e) => { e.preventDefault(); setPayerKey(key); setUnlocked(key !== ""); }}>
          <p className="panel-label">This part is the holder's</p>
          <p className="quiet">The company that holds the money decides. Enter the holder's key to act as the holder.</p>
          <div className="estate-answer">
            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="The holder's key" aria-label="The holder's key" />
            <button className="primary primary-small" type="submit">Unlock</button>
          </div>
        </form>
      ) : (
        <>
          <div className="holder-terms panel">
            <p className="panel-label">What an approval covers</p>
            <p className="holder-line">{figure(view.amount, "USD")} from the estate of {owner}, on these shares:</p>
            <table className="holder-shares">
              <tbody>
                {view.heirs.map((h) => (
                  <tr key={h.id} className={h.payable || h.paid ? "" : "holder-held"}>
                    <td>{h.name}</td><td className="quiet">{h.relation}</td><td className="holder-fraction">{h.share}</td>
                    <td className="holder-usd">{figure(h.entitlement, "USD")}</td>
                    <td>{h.paid ? "Paid" : h.payable ? `Proven. ${h.payee?.currency} account ending ${h.payee?.account_number.slice(-4)}` : `Held: ${h.missing[0] ?? "not proven yet"}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="quiet">The approval is bound to the family as described, each fraction, each bank account, which heirs are proven, and all {view.documents.length} documents. A change to any of them withdraws it.</p>
            <p className="risk-line quiet">{view.remaining_risk} <span className="risk-who">{view.decided_by}</span></p>
          </div>
          {flag && !view.other_law.acknowledged && canApprove && (
            <div className="notice estate-flag">
              <strong>Other law may apply.</strong> {flag.text}
              <label className="field estate-reason"><span>To approve on California's shares, write down why</span>
                <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} data-field="other-law-reason" /></label>
            </div>
          )}
          {view.other_law.acknowledged && <p className="quiet">The holder's reason for using California's shares: {view.other_law.acknowledged.reason}</p>}
          {view.approval ? (
            <div className="panel holder-approved" data-approved="yes">
              <p className="panel-label">Approved</p>
              <p className="holder-line">Approved at {clock(view.approval.at)} on {Object.keys(view.approval.shares).length} shares. {view.payable.length + Object.values(view.settlement.paid).length} of {view.heirs.length} heirs proven.</p>
              <p className="quiet mono">Terms {view.approval.terms_hash.slice(0, 16)}</p>
            </div>
          ) : canApprove ? (
            <div className="actions">
              <button className="primary" disabled={busy || (!!flag && !view.other_law.acknowledged && reason.trim().length < 10)} data-action="approve-estate"
                onClick={() => run("Recording the approval.", () => approveEstate(claimId, reason))}>
                {waitingAccount.length ? `Approve the corrected account for ${waitingAccount.map((l) => l.name.split(" ")[0]).join(", ")}` : view.state === "PAYMENT_HELD" ? "Approve the next round" : `Approve the estate: pay ${view.payable.length} of ${view.heirs.length} heirs`}
              </button>
            </div>
          ) : (
            <p className="quiet">Nothing here is waiting for the holder.</p>
          )}
          {view.approvals_withdrawn.length > 0 && (
            <ul className="events holder-withdrawn">
              {view.approvals_withdrawn.map((a) => <li key={a.at + a.because}><span className="event-when">{clock(a.at)}</span> An approval was withdrawn, because {a.because}.</li>)}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

// ---- 4. the settlement --------------------------------------------------------------------------------------------------

function SettlementTab({ view, sample, run, busy, claimId }: TabProps & { sample: EstateSample | null }) {
  const s = view.settlement;
  const [fail, setFail] = useState("");
  const plan = s.plan;
  const last = s.rounds.filter((r) => r.state !== "PLANNED").at(-1);
  const canPlan = !!view.approval && ["APPROVED", "PAYING"].includes(view.state) && !s.running && !plan && (!last || last.state === "DONE" || last.state === "HELD");
  const waitingFamily = last?.legs.filter((l) => l.hold?.needs.length === 1 && l.hold.needs[0] === "claimant") ?? [];
  const waitingAccount = last?.legs.filter((l) => l.hold?.needs.includes("bank_details")) ?? [];
  return (
    <section className="estate-section">
      {!view.approval && !s.started && <p className="notice">The settlement starts after the holder has approved the estate.</p>}
      {canPlan && (
        <div className="panel estate-plan-start">
          <h2>{last ? "Plan the next round" : "Plan the settlement"}</h2>
          <p className="quiet">One deposit from the holder, then one transfer to each proven heir, each in their own currency. The plan locks a rate for each heir and moves no money.</p>
          <div className="actions">
            <button className="primary" disabled={busy} data-action="plan" onClick={() => run("Taking a quote from Airwallex for each heir.", () => planSettlement(claimId, fail || null))}>Write the plan</button>
            <label className="field field-short estate-whatif"><span>On the sandbox, have one bank refuse</span>
              <select value={fail} onChange={(e) => setFail(e.target.value)} data-field="fail-heir"><option value="">Nobody</option>{view.heirs.filter((h) => h.payable).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}</select></label>
          </div>
        </div>
      )}
      {plan && (
        <div className="estate-plan" data-plan={plan.id}>
          <div className="decision-row">{(s.plan_cards ?? []).map((card) => <DecisionCard key={card.kind} card={card} compact />)}</div>
          <table className="plan-legs">
            <thead><tr><th>Heir</th><th>Share</th><th>Sent for them</th><th>Route</th><th>One dollar buys</th><th>Payout fee</th><th>They should receive</th></tr></thead>
            <tbody>
              {plan.legs.map((l) => (
                <tr key={l.heir}>
                  <td><strong>{l.name}</strong><br /><span className="quiet">{l.place}, account ending {l.account.number.slice(-4)}</span></td>
                  <td className="plan-fraction">{l.share}</td><td>{figure(l.leg_usd, "USD")}{l.covered && <><br /><span className="quiet">fees borne by the holder</span></>}</td>
                  <td>{l.route_name}{l.what_if && <><br /><span className="plan-whatif">the bank will refuse this one</span></>}</td>
                  <td>{Number(l.per_dollar).toFixed(4)} {l.currency}</td><td>{figure(l.payout_fee.amount, l.payout_fee.currency)}</td>
                  <td className="plan-receive-cell">{fig(l.expected_local)}</td>
                </tr>
              ))}
              {plan.held.map((h) => (
                <tr key={h.heir} className="plan-held"><td><strong>{h.name}</strong><br /><span className="quiet">not proven yet</span></td><td className="plan-fraction">{h.share}</td>
                  <td colSpan={5}>{figure(h.entitlement, "USD")} is held with the holder. Missing: {h.missing[0]}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="plan-receive">
            <div>
              <p className="panel-label">The holder sends, once</p>
              <p className="amount-figure amount-gold">{figure(plan.holder_sends, "USD")}</p>
              <p className="quiet">Airwallex's incoming fee is expected to be {figure(plan.expected_incoming_fee, "USD")}, leaving {figure(plan.net, "USD")} for {plan.legs.length} heirs.</p>
            </div>
            <div className="actions">
              <button className="primary" disabled={busy} data-action="confirm" onClick={() => run("Starting the settlement.", () => confirmSettlement(claimId, plan.id))}>The family agrees: start the settlement</button>
            </div>
          </div>
          <details className="fold"><summary>If things change</summary>{plan.if_things_change.map((line) => <p key={line} className="quiet">{line}</p>)}<p className="quiet">{plan.rounding_rule}</p><p className="quiet">{plan.fee_rule}</p></details>
        </div>
      )}
      {s.rounds.filter((r) => r.state !== "PLANNED").map((round) => <Round key={round.n} round={round} total={s.rounds.length} />)}
      {waitingAccount.map((leg) => (
        <CorrectAccount key={leg.heir} leg={leg} busy={busy} demo={view.sample ? sample?.heirs.find((h) => h.id === leg.heir)?.bank_corrected ?? null : null}
          onSave={(bank) => run("Checking the corrected account with Airwallex.", () => putHeirPayee(claimId, leg.heir, bank))} />
      ))}
      {waitingFamily.map((leg) => (
        <div key={leg.heir} className="notice">
          {leg.name}: the amount changed beyond the holder's tolerance. {leg.hold?.replacement ? `A replacement would bring ${fig(leg.hold.replacement.would_receive)}.` : ""}{" "}
          <button className="primary primary-small" disabled={busy} onClick={() => run("Carrying on.", () => agreeForHeir(claimId, leg.heir))}>The family agrees</button>
        </div>
      ))}
      {s.problem && <p className="notice">{s.problem} <button className="secondary-flat" onClick={() => run("Carrying on.", () => resumeSettlement(claimId))}>Carry on</button></p>}
      {s.reconciliation && s.started && <Reconcile rec={s.reconciliation} done={view.state === "PAID"} />}
    </section>
  );
}

const LEG_H = 112;

/** One round: the holder's one deposit on the left, fanning out to each heir's country on the right. */
function Round({ round, total }: { round: RoundView; total: number }) {
  const legs = round.legs;
  const held = round.plan.held;
  const rows = legs.length + held.length;
  const height = Math.max(rows * LEG_H, 280);
  const pad = (height - rows * LEG_H) / 2;
  const funded = round.state !== "FUNDING";
  const tone = (leg: LegView) => (leg.state === "PAID" ? "paid" : leg.state === "FAILED" || leg.refused_not_back ? "refused" : leg.state === "HELD" ? "waiting" : leg.state === "WAITING" ? "idle" : "moving");
  return (
    <div className="fan" data-round={round.n} data-state={round.state}>
      {total > 1 && <p className="panel-label">Round {round.n}</p>}
      <div className="fan-grid" style={{ height }}>
        <div className="fan-source">
          <p className="panel-label">One deposit from the holder</p>
          <p className="fan-deposit">{figure(round.arrived?.deposit ?? round.plan.holder_sends, "USD")}</p>
          <p className="quiet">{round.arrived ? `Airwallex's fee ${figure(round.arrived.incoming_fee, "USD")}. ${figure(round.arrived.net, "USD")} to divide.` : "Waiting for it to arrive at Airwallex."}</p>
          <p className="quiet mono">{round.reference}</p>
        </div>
        <svg className="fan-lines" viewBox={`0 0 200 ${height}`} preserveAspectRatio="none" aria-hidden="true">
          {legs.map((leg, i) => {
            const y = pad + i * LEG_H + LEG_H / 2;
            return <path key={leg.heir} className={`fan-line fan-${funded ? tone(leg) : "idle"}`} d={`M0,${height / 2} C100,${height / 2} 100,${y} 200,${y}`} />;
          })}
          {held.map((h, i) => {
            const y = pad + (legs.length + i) * LEG_H + LEG_H / 2;
            return <path key={h.heir} className="fan-line fan-held" d={`M0,${height / 2} C100,${height / 2} 100,${y} 200,${y}`} />;
          })}
        </svg>
        <ol className="fan-legs">
          {legs.map((leg) => (
            <li key={leg.heir} className={`fan-leg fan-leg-${tone(leg)}`} style={{ height: LEG_H }} data-leg={leg.heir} data-leg-state={leg.state}>
              <div className="fan-who">
                <p className="fan-name">{leg.name}</p>
                <p className="quiet">{leg.place}. {leg.share} of the estate. {figure(leg.leg_usd ?? leg.planned_usd, "USD")}</p>
              </div>
              <ol className="fan-dots">
                {leg.journey.map((j) => <li key={j.key} className={j.done ? "fan-dot fan-dot-done" : "fan-dot"} title={j.label}><span />{j.label}</li>)}
              </ol>
              <div className="fan-amount">
                <p className="fan-local">{leg.received ? fig(leg.received) : leg.state === "FAILED" && leg.funds ? fig(leg.funds) : fig(leg.local ?? leg.expected_local)}</p>
                <p className="fan-state">{leg.refused_not_back ? "Refused. Waiting for the money to come back" : leg.state === "FAILED" ? "Refused by the bank. Held for this heir" : leg.received ? "Paid" : LEG_WORDS[leg.state] ?? leg.state}</p>
                {leg.problem && <p className="fan-problem">{leg.problem}</p>}
              </div>
            </li>
          ))}
          {held.map((h) => (
            <li key={h.heir} className="fan-leg fan-leg-held" style={{ height: LEG_H }} data-leg={h.heir} data-leg-state="HELD_WITH_HOLDER">
              <div className="fan-who"><p className="fan-name">{h.name}</p><p className="quiet">{h.share} of the estate. Not proven yet.</p></div>
              <div className="fan-held-note">Held with the holder</div>
              <div className="fan-amount"><p className="fan-local">{figure(h.entitlement, "USD")}</p><p className="fan-state">Not sent</p></div>
            </li>
          ))}
        </ol>
      </div>
      {round.held_because && <p className="notice">{round.held_because}</p>}
      <details className="fold" open={round.state !== "DONE"}>
        <summary>What happened, line by line</summary>
        <ul className="events">{round.events.map((e) => <li key={e.at + e.text}><span className="event-when">{clock(e.at)}</span> {e.text}</li>)}</ul>
      </details>
    </div>
  );
}

function CorrectAccount({ leg, busy, demo, onSave }: { leg: LegView; busy: boolean; demo: SampleBank | null; onSave: (bank: SampleBank) => void }) {
  const [bank, setBank] = useState<SampleBank>({ currency: leg.currency, first_name: "", last_name: "", account_number: "", street_address: "", city: "", postcode: "" });
  const set = (key: string, value: string) => setBank({ ...bank, [key]: value });
  const r = leg.hold?.replacement;
  return (
    <div className="panel estate-correct" data-correct={leg.heir}>
      <p className="panel-label">A corrected account for {leg.name}</p>
      <p className="holder-line">The bank refused the transfer to the account ending {leg.attempts?.at(-1)?.account_last4 ?? leg.account.number.slice(-4)}. {leg.funds ? `${fig(leg.funds)} came back and is held for ${leg.name.split(" ")[0]}.` : ""}</p>
      {r && <p className="quiet">A replacement would bring {fig(r.would_receive)}, {r.shortfall_percent} percent less than planned, because Airwallex charges its payout fee again. {r.family_asked ? "That is outside the holder's tolerance, so the family is asked to agree." : "That is inside the holder's tolerance, so the family is not asked again."} The holder approves the new account before anything is sent.</p>}
      <div className="row">
        <label className="field"><span>First name</span><input value={bank.first_name} onChange={(e) => set("first_name", e.target.value)} /></label>
        <label className="field"><span>Last name</span><input value={bank.last_name} onChange={(e) => set("last_name", e.target.value)} /></label>
        {(BANK_FIELDS[leg.currency] ?? []).map(([key, label]) => <label key={key} className="field"><span>{label}</span><input value={bank[key] ?? ""} onChange={(e) => set(key, e.target.value)} /></label>)}
      </div>
      <div className="row">
        <label className="field"><span>Street address</span><input value={bank.street_address} onChange={(e) => set("street_address", e.target.value)} /></label>
        <label className="field"><span>City</span><input value={bank.city} onChange={(e) => set("city", e.target.value)} /></label>
        <label className="field field-short"><span>Postcode</span><input value={bank.postcode} onChange={(e) => set("postcode", e.target.value)} /></label>
      </div>
      <div className="actions">
        <button className="primary primary-small" disabled={busy} data-action="save-corrected" onClick={() => onSave(bank)}>Save the corrected account</button>
        {demo && <button className="secondary" data-demo="corrected" onClick={() => setBank(demo)}>Fill in the demonstration's second account</button>}
      </div>
    </div>
  );
}

function Reconcile({ rec, done }: { rec: NonNullable<EstateView["settlement"]["reconciliation"]>; done: boolean }) {
  return (
    <div className={`panel reconcile ${rec.balanced ? "reconcile-zero" : ""}`} data-balanced={rec.balanced ? "yes" : "no"}>
      <p className="panel-label">Against Airwallex's own ledger{done ? ", at the end" : ", so far"}</p>
      <div className="reconcile-sums">
        {rec.sums.map((sum) => (
          <div key={sum.currency} className="reconcile-sum">
            <p className="reconcile-left">{figure(sum.left, sum.currency)}</p>
            <p className="quiet">left in {sum.currency}. In {figure(sum.came_in, sum.currency)}, out {figure(sum.went_out, sum.currency)}.</p>
          </div>
        ))}
      </div>
      <p className="reconcile-statement">{rec.statement}</p>
      <details className="fold">
        <summary>All {rec.lines.length} ledger lines</summary>
        <table className="ledger"><tbody>
          {rec.lines.map((line) => <tr key={line.id}><td>{line.who}</td><td>{line.type}</td><td className="ledger-amount">{figure(line.amount, line.currency)}</td><td className="quiet">{line.description}</td></tr>)}
        </tbody></table>
      </details>
    </div>
  );
}
