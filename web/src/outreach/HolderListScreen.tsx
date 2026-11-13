import { useEffect, useRef, useState } from "react";
import { LockedError, payerKey, setPayerKey } from "../api";
import DecisionCard from "../components/DecisionCard";
import Masthead from "../components/Masthead";
import Waiting from "../components/Waiting";
import { count, exact, money } from "../format";
import {
  confirmMapping, findNotices, getNotice, getOutreach, getQueuePage, loadInvented, markSent, openPdf, prepareNotices, saveOutreachSettings, uploadList,
  type HolderDetails, type NoticeDetail, type NoticeRow, type NoticeText, type Outreach, type OutreachRules, type QueueRow,
} from "./api";

type Tab = "file" | "columns" | "queue" | "notices" | "funnel";
const TABS: [Tab, string][] = [["file", "Your file"], ["columns", "Columns"], ["queue", "Queue"], ["notices", "Notices"], ["funnel", "Funnel"]];
const SOURCE_WORDS: Record<string, string> = { model: "Proposed by the model", title: "Read from the title", values: "Read from the values", remembered: "Remembered" };
const dollars = (amount: string) => money(Number(amount));

/** The text of one notice in one language, as the owner will read it. */
export function NoticeBody({ text, lang }: { text: NoticeText; lang?: string }) {
  return (
    <div className="notice-text" lang={lang}>
      <p className="notice-heading">{text.heading}</p>
      {text.reminder && <p className="notice-strong">{text.reminder}</p>}
      <dl className="notice-facts">
        {text.facts.map((f) => (
          <div key={f.label}>
            <dt>{f.label}</dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>
      {text.paragraphs.map((p) => (
        <p key={p.key} className={p.strong ? "notice-strong" : undefined}>{p.text}</p>
      ))}
    </div>
  );
}

/** The holder's own list: upload, columns, the working queue, the notices and the funnel. Behind the holder's key. */
export default function HolderListScreen({ onHome }: { onHome: () => void }) {
  const [view, setView] = useState<Outreach | null>(null);
  const [tab, setTab] = useState<Tab>("file");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState("");
  const [unlocked, setUnlocked] = useState(() => payerKey() !== "");
  const [typedKey, setTypedKey] = useState("");
  const [keyProblem, setKeyProblem] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [kind, setKind] = useState("");
  const [chosen, setChosen] = useState<NoticeDetail | null>(null);
  const [inEnglish, setInEnglish] = useState(false);
  const [more, setMore] = useState<QueueRow[]>([]);
  const [wanted, setWanted] = useState("");
  const [found, setFound] = useState<NoticeRow[] | null>(null);
  const [rules, setRules] = useState<OutreachRules | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const settled = useRef(false);
  const listKey = useRef("");

  const lock = (e: LockedError) => {
    setPayerKey("");
    setUnlocked(false);
    setView(null);
    setKeyProblem(e.message || "The holder's key is missing or wrong.");
  };
  const take = (next: Outreach, go?: Tab) => {
    setView(next);
    // The column choices are taken from the server once per list and state. The screen asks again every few
    // seconds, and that must not undo a correction the holder is in the middle of.
    const key = next.list ? `${next.list.id}:${next.list.state}:${next.list.confirmed_at ?? ""}` : "";
    const fresh = key !== listKey.current;
    listKey.current = key;
    if (!fresh) {
      // nothing to take over
    } else if (next.list && next.list.state === "uploaded") {
      const proposed: Record<string, string> = {};
      for (const [field, choice] of Object.entries(next.list.proposal.fields)) proposed[field] = choice.column;
      setMapping(proposed);
      setKind(next.list.proposal.defaults?.property_class ?? "");
    } else if (next.list?.mapping) {
      setMapping(next.list.mapping);
      setKind(next.list.defaults?.property_class ?? "");
    }
    if (go) setTab(go);
    else if (!settled.current) {
      setTab(!next.list ? "file" : next.list.state === "uploaded" ? "columns" : next.notices && next.notices.count > 0 ? "notices" : "queue");
    }
    settled.current = true;
  };
  const run = async (label: string, work: () => Promise<Outreach>, go?: Tab) => {
    setBusy(label);
    setProblem("");
    try {
      take(await work(), go);
    } catch (e) {
      if (e instanceof LockedError) lock(e);
      else setProblem((e as Error).message);
    } finally {
      setBusy("");
    }
  };
  const refresh = () => getOutreach().then((next) => take(next)).catch((e: Error) => (e instanceof LockedError ? lock(e) : setProblem(e.message)));

  useEffect(() => {
    if (!unlocked) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);     // an owner's answer shows up in the funnel
    return () => window.clearInterval(timer);
  }, [unlocked]);

  const note = "The holder's own list: before the money reaches the State";
  if (!unlocked) {
    return (
      <main className="flow onescreen">
        <Masthead onHome={onHome} note={note} />
        <div className="flow-body flow-narrow">
          <h1>The holder's list is locked</h1>
          <p className="quiet">Type the key that was set on this server. It is kept for this browser tab only.</p>
          {keyProblem && <p className="notice">{keyProblem}</p>}
          <form className="key-form" onSubmit={(e) => { e.preventDefault(); setKeyProblem(""); setProblem(""); setPayerKey(typedKey.trim()); setUnlocked(typedKey.trim() !== ""); }}>
            <label className="field">
              <span>Holder's key</span>
              <input type="password" value={typedKey} onChange={(e) => setTypedKey(e.target.value)} autoComplete="off" autoFocus />
            </label>
            <button type="submit" className="primary primary-small" disabled={typedKey.trim() === ""}>Open the holder's list</button>
          </form>
        </div>
      </main>
    );
  }
  if (!view) {
    return (
      <main className="flow onescreen">
        <Masthead onHome={onHome} note={note} />
        <div className="flow-body flow-narrow">
          {problem ? <p className="notice">{problem}</p> : <div className="results-empty"><Waiting counted={false}>Reading your list.</Waiting></div>}
        </div>
      </main>
    );
  }

  const list = view.list;
  const picture = view.picture;
  const notices = view.notices;
  const can: Record<Tab, boolean> = { file: true, columns: Boolean(list), queue: Boolean(picture), notices: Boolean(picture), funnel: Boolean(notices && notices.count > 0) };
  const soon = picture?.abroad_due_soon;
  const openNotice = (id: string) => {
    setProblem("");
    getNotice(id).then((d) => { setChosen(d); setInEnglish(false); }).catch((e: Error) => setProblem(e.message));
  };
  const queue = [...view.queue, ...more];

  return (
    <main className="flow onescreen outreach">
      <Masthead onHome={onHome} note={note} />
      <div className="outreach-top">
        <div className="tabs" role="tablist" aria-label="The steps of the holder's list">
          {TABS.map(([key, label], i) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key} disabled={!can[key]} className={tab === key ? "tab tab-on" : "tab"} onClick={() => setTab(key)}>
              {i + 1}. {label}
            </button>
          ))}
        </div>
        <p className="outreach-links">
          <a href="/payer">The holder's view</a>
        </p>
      </div>
      {problem && <p className="notice outreach-problem">{problem}</p>}

      {tab === "file" && (
        <div className="outreach-cols">
          <section className="pane">
            <h1>Your own list, before the State</h1>
            <p className="outreach-lead">Upload the dormant balances from your payroll or banking system. Khutlisa reads the columns, finds the owners abroad, and counts the days until each balance goes to the State.</p>
            <div className="panel upload-panel">
              <label className="field">
                <span>Your file of dormant balances, as CSV or Excel</span>
                <input ref={fileInput} type="file" accept=".csv,.txt,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />
              </label>
              <div className="actions">
                <button type="button" className="primary primary-small" disabled={busy !== ""} onClick={() => {
                  const file = fileInput.current?.files?.[0];
                  if (!file) setProblem("Choose a file first.");
                  else void run("Reading the file.", () => uploadList(file), "columns");
                }}>Read my file</button>
                <button type="button" className="secondary secondary-flat" disabled={busy !== ""} onClick={() => void run("Reading the invented file.", loadInvented, "columns")}>
                  Use the invented file
                </button>
              </div>
              {busy && <Waiting>{busy}</Waiting>}
            </div>
            <p className="quiet">
              The invented file is an employer's export of uncashed pay for about 3,200 former workers. Every person in it is made up.{" "}
              <a href={view.invented_file.url}>Download it</a>.
            </p>
            {view.demo_only && <p className="quiet">This is a public demonstration, so only the invented file can be loaded here.</p>}
          </section>
          <aside className="pane outreach-side">
            <div className="panel">
              <p className="panel-label">What happens to the file</p>
              <ul className="plain-list">
                <li>The file stays on this server.</li>
                <li>A language model proposes which column is which. It sees the column titles and at most 20 rows, with every name, address, contact detail and reference replaced by its shape.</li>
                <li>You confirm or correct the columns. Every row is then checked in code, and rows that fail are listed with the reason.</li>
              </ul>
            </div>
            {list && (
              <div className="panel">
                <p className="panel-label">The list on file</p>
                <p className="list-name">{list.filename}</p>
                {list.invented && <p className="invented-mark">Invented file: no real person is in it.</p>}
                <p className="quiet">{count(list.rows_read)} rows read. {list.state === "confirmed" ? `${count(list.valid)} usable, ${count(list.failed)} failed.` : "The columns are not confirmed yet."}</p>
              </div>
            )}
          </aside>
        </div>
      )}

      {tab === "columns" && list && (
        <div className="outreach-cols">
          <section className="pane">
            <h1>Which column is which</h1>
            <p className="outreach-lead">
              {list.proposal.by === "model" && `A language model proposed this from the column titles and ${list.proposal.sample_rows_sent} masked rows. `}
              {list.proposal.by === "code" && "This was read in code from the column titles and the shapes of the values. "}
              {list.proposal.by === "remembered" && "You confirmed these columns for this export before, so they are remembered. "}
              Confirm it, or correct it first.
            </p>
            <div className="map-grid">
              {list.fields.map((f) => {
                const at = list.header.indexOf(mapping[f.key] ?? "");
                const sample = at >= 0 ? list.first_rows.map((r) => r[at]).filter(Boolean).slice(0, 2).join(", ").slice(0, 36) : "";
                const source = list.proposal.fields[f.key];
                return (
                  <label className="field map-field" key={f.key} title={f.about}>
                    <span>{f.label}{source && mapping[f.key] === source.column && <em className="map-source">{SOURCE_WORDS[source.source]}</em>}</span>
                    <select value={mapping[f.key] ?? ""} onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value })}>
                      <option value="">Not in this file</option>
                      {list.header.map((h) => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <span className="map-sample">{sample || "No column chosen"}</span>
                  </label>
                );
              })}
            </div>
          </section>
          <aside className="pane outreach-side">
            <div className="panel">
              <p className="panel-label">The file</p>
              <p className="list-name">{list.filename}</p>
              {list.invented && <p className="invented-mark">Invented file: no real person is in it.</p>}
              <p className="big-line"><strong>{count(list.rows_read)}</strong> rows under the column titles</p>
              {list.file_notes.map((n) => <p className="quiet" key={n}>{n}</p>)}
              {list.proposal.model_note && <p className="quiet">{list.proposal.model_note}</p>}
              {list.proposal.notes && <p className="quiet">The model noted: {list.proposal.notes}</p>}
              {list.proposal.unused_columns.length > 0 && <p className="quiet">Not used: {list.proposal.unused_columns.join(", ")}.</p>}
            </div>
            {!mapping.property_type && (
              <label className="field">
                <span>The file has no column for the kind of property. Everything in it is</span>
                <select value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="">Other property (three years)</option>
                  {list.kinds.filter((k) => k.key !== "other").map((k) => <option key={k.key} value={k.key}>{k.label} ({k.years} {k.years === 1 ? "year" : "years"})</option>)}
                </select>
              </label>
            )}
            <div className="actions">
              <button type="button" className="primary" disabled={busy !== ""} onClick={() => void run("Checking every row.", () => confirmMapping(list.id, mapping, { property_class: kind || null }), "queue")}>
                Confirm the columns
              </button>
            </div>
            {busy && <Waiting>{busy}</Waiting>}
            {list.state === "confirmed" && <p className="quiet">Confirmed. Confirming again reads every row again.</p>}
          </aside>
        </div>
      )}

      {tab === "queue" && list && picture && soon && (
        <div className="outreach-cols outreach-wide">
          <section className="pane queue-pane">
            <h1>Owed abroad, and due to the State</h1>
            <div className="big-figures">
              <div><p className="big-number">{count(list.rows_read)}</p><p className="big-caption">rows read</p></div>
              <div><p className="big-number">{count(list.valid)}</p><p className="big-caption">usable</p></div>
              <div><p className="big-number big-bad">{count(list.failed)}</p><p className="big-caption">failed, with reasons</p></div>
              <div><p className="big-number big-gold">{dollars(picture.abroad.amount)}</p><p className="big-caption">owed to {count(picture.abroad.balances)} owners abroad</p></div>
              <div><p className="big-number big-gold">{dollars(soon.amount)}</p><p className="big-caption">of it goes to the State in {soon.days ?? 0} days</p></div>
            </div>
            <ol className="queue-list" aria-label="The working queue">
              {queue.map((b) => (
                <li key={b.row} className={`queue-item queue-${b.status}`}>
                  <span className="queue-days"><strong>{count(Math.max(b.days_to_state, 0))}</strong> days</span>
                  <span className="queue-who">{b.name}<em>{b.city ? `${b.city}, ` : ""}{b.country_name}</em></span>
                  <span className="queue-amount">{exact(b.amount, "USD")}</span>
                  <span className="queue-what">{b.kind}, {b.years} {b.years === 1 ? "year" : "years"}. {b.status_words}, {b.handover_words}.{!b.notice_required && " Under 50 dollars: no notice required."}</span>
                </li>
              ))}
            </ol>
            {view.queue_total !== undefined && queue.length < view.queue_total && (
              <button type="button" className="plain" onClick={() => getQueuePage(list.id, queue.length).then((p) => setMore([...more, ...p.rows])).catch((e: Error) => setProblem(e.message))}>
                Show more of the {count(view.queue_total)}
              </button>
            )}
          </section>
          <aside className="pane outreach-side">
            <div className="panel">
              <p className="panel-label">By country, owners abroad</p>
              <ul className="bar-list">
                {picture.by_country.slice(0, 8).map((c) => (
                  <li key={c.code}>
                    <span className="bar-name">{c.name}</span>
                    <span className="bar-track"><span style={{ width: `${Math.max(3, (Number(c.amount) / Number(picture.by_country[0].amount)) * 100)}%` }} /></span>
                    <span className="bar-amount">{dollars(c.amount)}</span>
                    <span className="bar-count">{count(c.balances)}</span>
                  </li>
                ))}
              </ul>
              {picture.by_country.length > 8 && <p className="quiet">And {picture.by_country.length - 8} more countries.</p>}
            </div>
            <div className="panel">
              <p className="panel-label">By the date it goes to the State</p>
              <ul className="due-list">
                {picture.by_due_date.slice(0, 4).map((d) => (
                  <li key={d.handover}>
                    <strong>{count(Math.max(d.days, 0))} days</strong>
                    <span>{dollars(d.abroad.amount)} abroad, {count(d.abroad.balances)} owners. {dollars(d.amount)} in all.</span>
                  </li>
                ))}
              </ul>
            </div>
            <details className="panel fold-panel">
              <summary>{count(list.failed)} rows failed, and why</summary>
              <ul className="fail-list">
                {list.failures.map((f) => (
                  <li key={f.reason}><strong>{count(f.rows)}</strong> {f.reason} <span className="quiet">Rows {f.first_rows.join(", ")}{f.rows > f.first_rows.length ? " and more" : ""}.</span></li>
                ))}
              </ul>
              {list.notes.map((n) => <p className="quiet" key={n}>{n}</p>)}
            </details>
            <details className="panel fold-panel">
              <summary>The rules, and their sources</summary>
              <ul className="law-list">
                {view.law.map((l) => (
                  <li key={l.title}>
                    <p className="law-title">{l.title}<span className={l.mark === "verified" ? "mark mark-verified" : "mark mark-reading"}>{l.mark === "verified" ? "Read at the source" : "Our reading"}</span></p>
                    <p>{l.text}</p>
                    <p className="quiet">{l.source}. <a href={l.url} target="_blank" rel="noreferrer">Open the source</a></p>
                  </li>
                ))}
              </ul>
              <p className="quiet">{picture.calendar.assumption}</p>
            </details>
            <div className="actions">
              <button type="button" className="primary" onClick={() => setTab("notices")}>Go to the notices</button>
            </div>
          </aside>
        </div>
      )}

      {tab === "notices" && list && picture && notices && (
        <div className="outreach-cols outreach-wide">
          <section className="pane">
            <h1>The notice the law requires</h1>
            <p className="sends-nothing">{view.sends_nothing}</p>
            {!view.holder && <HolderForm onSave={(holder) => run("Saving.", () => saveOutreachSettings({ holder }))} />}
            <div className="actions notice-actions">
              <button type="button" className="primary primary-small" disabled={busy !== "" || !view.holder || (notices.to_prepare === 0 && notices.stale === 0)} onClick={() => void run("Preparing the notices.", prepareNotices)}>
                {notices.to_prepare > 0 ? `Prepare ${count(notices.to_prepare)} notices` : notices.stale > 0 ? `Prepare ${count(notices.stale)} notices again` : "Every notice is prepared"}
              </button>
              <button type="button" className="secondary secondary-flat" disabled={notices.unsent === 0} onClick={() => openPdf("/api/holder/notices/batch.pdf?which=unsent&limit=500").catch((e: Error) => setProblem(e.message))}>
                Print the unsent letters
              </button>
              <button type="button" className="secondary secondary-flat" disabled={busy !== "" || notices.unsent === 0} onClick={() => void run("Recording.", () => markSent({ all_unsent: true, channel: "post" }))}>
                I have sent them all
              </button>
            </div>
            {busy && <Waiting>{busy}</Waiting>}
            {notices.count > 0 && (
              <p className="language-line">
                <strong>{count(notices.ready)}</strong> ready{notices.held > 0 && <>, <strong>{count(notices.held)}</strong> held back</>}. English always, and:{" "}
                {notices.languages.map((l) => `${l.language} ${count(l.notices)}`).join(", ")}.
              </p>
            )}
            <div className="decision-stack">
              {notices.cards.map((card) => <DecisionCard key={card.kind} card={card} compact />)}
            </div>
            <LimitsPanel view={view} rules={rules} setRules={setRules} onSave={(next) => run("Saving.", () => saveOutreachSettings({ rules: next })).then(() => setRules(null))} />
          </section>
          <aside className="pane outreach-side notice-side">
            {!chosen && notices.count > 0 && (
              <>
                <form className="find-form" onSubmit={(e) => { e.preventDefault(); if (wanted.trim()) findNotices(wanted).then((p) => setFound(p.rows)).catch((err: Error) => setProblem(err.message)); else setFound(null); }}>
                  <label className="field">
                    <span>Find an owner by name</span>
                    <input value={wanted} onChange={(e) => { setWanted(e.target.value); if (!e.target.value.trim()) setFound(null); }} autoComplete="off" />
                  </label>
                  <button type="submit" className="secondary secondary-flat">Find</button>
                </form>
                <p className="panel-label">{found ? `${found.length} found` : "Prepared, in the agent's order"}</p>
                <ul className="payer-list notice-list">
                  {(found ?? notices.rows.slice(0, 30)).map((n) => (
                    <li key={n.id}>
                      <button type="button" className="payer-pick" onClick={() => openNotice(n.id)}>
                        <span className="payer-pick-name">{n.name}<em>{n.country_name}, {n.language.translated ? n.language.name : "English only"}</em></span>
                        <span className="payer-pick-amount">{exact(n.amount, "USD")}</span>
                        <span className={`state notice-state notice-state-${n.stage}`}>{n.stage_words}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                {!found && notices.count > 30 && <p className="quiet">The first 30 of {count(notices.count)}.</p>}
              </>
            )}
            {!chosen && notices.count === 0 && <p className="results-empty">No notice is prepared yet.</p>}
            {chosen && (
              <article className="notice-detail">
                <header className="notice-detail-head">
                  <div>
                    <p className="notice-detail-name">{chosen.name}</p>
                    <p className="quiet">{chosen.country_name}. {exact(chosen.amount, "USD")}. To the State in {count(Math.max(chosen.days_to_state, 0))} days.</p>
                  </div>
                  <button type="button" className="plain" onClick={() => setChosen(null)}>Back to the list</button>
                </header>
                <ul className="element-list" aria-label="What the law requires in the notice">
                  {chosen.elements.map((e) => (
                    <li key={e.key} className={e.present ? "element element-yes" : "element element-no"} title={e.source}>{e.title}</li>
                  ))}
                </ul>
                {chosen.problems.map((p) => <p className="notice" key={p}>{p}</p>)}
                <p className="quiet">{chosen.timing.text}</p>
                <ul className="delivery-list">
                  {chosen.delivery.map((d) => (
                    <li key={d.channel}><strong>{d.channel === "post" ? "By post" : d.channel === "email" ? "By email" : "By telephone"}</strong> {d.basis}</li>
                  ))}
                </ul>
                <p className="notice-link">Personal link: <strong>{chosen.link}</strong></p>
                <div className="actions notice-actions">
                  {chosen.views.other && (
                    <button type="button" className="secondary secondary-flat" onClick={() => setInEnglish(!inEnglish)}>
                      {inEnglish ? `Show it in ${chosen.language.name}` : "Show it in English"}
                    </button>
                  )}
                  <button type="button" className="secondary secondary-flat" disabled={chosen.state !== "ready"} onClick={() => openPdf(chosen.letter_url).catch((e: Error) => setProblem(e.message))}>
                    The letter as a PDF
                  </button>
                  {chosen.sent.length === 0 && chosen.state === "ready" && (
                    <button type="button" className="primary primary-small" disabled={busy !== ""} onClick={() => void run("Recording.", () => markSent({ ids: [chosen.id], channel: "post" })).then(() => openNotice(chosen.id))}>
                      I have sent this one
                    </button>
                  )}
                </div>
                {chosen.sent.length > 0 && <p className="quiet">Marked sent on {chosen.sent[0].on}, by {chosen.sent[0].channel}.</p>}
                <NoticeBody text={chosen.views.other && !inEnglish ? chosen.views.other : chosen.views.english} lang={chosen.views.other && !inEnglish ? chosen.language.code : "en"} />
              </article>
            )}
          </aside>
        </div>
      )}

      {tab === "funnel" && notices && (
        <div className="outreach-cols outreach-wide">
          <section className="pane">
            <h1>From notice to money at home</h1>
            <div className="handover">
              <p className="handover-days">{count(Math.max(notices.funnel.days_left, 0))}<span> days</span></p>
              <div>
                <p className="handover-what">until you hand unclaimed property to the State, on {notices.funnel.date_words}.</p>
                <p className="quiet handover-law">{view.sends_nothing}</p>
              </div>
            </div>
            <ol className="funnel" aria-label="How far the notices have got">
              {notices.funnel.stages.map((s) => (
                <li key={s.key} className={s.notices > 0 ? "funnel-stage funnel-on" : "funnel-stage"}>
                  <p className="funnel-count">{count(s.notices)}</p>
                  <p className="funnel-words">{s.words}</p>
                  <p className="funnel-amount">{dollars(s.amount)}</p>
                </li>
              ))}
            </ol>
            {notices.cards.filter((c) => c.kind === "deadline_outreach").map((card) => <DecisionCard key={card.kind} card={card} />)}
          </section>
          <aside className="pane outreach-side">
            <p className="panel-label">Owners who have opened or answered</p>
            <ul className="payer-list notice-list">
              {notices.rows.filter((n) => n.opened_at || n.claim_id).map((n) => (
                <li key={n.id}>
                  <a className="payer-pick" href={n.claim_id ? "/payer" : undefined}>
                    <span className="payer-pick-name">{n.name}<em>{n.country_name}, {n.language.translated ? n.language.name : "English only"}</em></span>
                    <span className="payer-pick-amount">{exact(n.amount, "USD")}</span>
                    <span className={`state notice-state notice-state-${n.stage}`}>{n.stage_words}</span>
                  </a>
                </li>
              ))}
            </ul>
            {notices.rows.every((n) => !n.opened_at && !n.claim_id) && <p className="results-empty">No owner has opened a notice yet.</p>}
            <p className="quiet">An answer opens a claim on that exact balance. You approve it in the holder's view, and the money goes out through Airwallex.</p>
            {notices.cards.filter((c) => c.kind === "reminder").map((card) => {
              const due = (card as typeof card & { due?: string[] }).due?.length ?? 0;
              return (
                <div key={card.kind}>
                  <DecisionCard card={card} compact />
                  {due > 0 && (
                    <div className="actions notice-actions">
                      <button type="button" className="secondary secondary-flat" onClick={() => openPdf("/api/holder/notices/batch.pdf?which=reminders&limit=500").catch((e: Error) => setProblem(e.message))}>
                        Print the {count(due)} reminders
                      </button>
                      <button type="button" className="secondary secondary-flat" disabled={busy !== ""} onClick={() => void run("Recording.", () => markSent({ all_unsent: true, channel: "post", reminder: true }))}>
                        I have sent the reminders
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </aside>
        </div>
      )}
    </main>
  );
}

/** The holder's limits for outreach: set once, shown as figures, and used by every decision card on this screen. */
function LimitsPanel({ view, rules, setRules, onSave }: { view: Outreach; rules: OutreachRules | null; setRules: (r: OutreachRules | null) => void; onSave: (r: OutreachRules) => Promise<void> }) {
  const r = view.settings.rules;
  return (
    <section className="instructions" aria-label="Limits for outreach">
      <div className="instructions-head">
        <h2>Your limits for notices, set once</h2>
        {!rules && <button type="button" className="secondary secondary-flat" onClick={() => setRules({ ...r })}>Change them</button>}
      </div>
      {!rules && (
        <ul className="limits" aria-label="The limits in force">
          <li><strong>{exact(r.notice_minimum_usd, "USD")}</strong><span>and up: the owner gets a notice</span></li>
          <li><strong>{r.reminders_most === 0 ? "None" : `${r.reminder_after_days} days`}</strong><span>{r.reminders_most === 0 ? "no reminders" : "with no answer, then a reminder"}</span></li>
          <li><strong>{r.reminders_most}</strong><span>{r.reminders_most === 1 ? "reminder at most" : "reminders at most"}</span></li>
          <li><strong>{r.hold_answered ? "Hold" : "Release"}</strong><span>a balance whose owner answered without proof, at the date</span></li>
        </ul>
      )}
      {rules && (
        <form className="instruction-form" onSubmit={(e) => { e.preventDefault(); void onSave(rules); }}>
          <label className="field">
            <span>Smallest balance to notify, in US dollars (50 at most)</span>
            <input value={rules.notice_minimum_usd} onChange={(e) => setRules({ ...rules, notice_minimum_usd: e.target.value })} inputMode="decimal" />
          </label>
          <label className="field">
            <span>Days with no answer before a reminder</span>
            <input value={String(rules.reminder_after_days)} onChange={(e) => setRules({ ...rules, reminder_after_days: Number(e.target.value.replace(/\D/g, "")) || 0 })} inputMode="numeric" />
          </label>
          <label className="field">
            <span>Reminders at most</span>
            <input value={String(rules.reminders_most)} onChange={(e) => setRules({ ...rules, reminders_most: Number(e.target.value.replace(/\D/g, "")) || 0 })} inputMode="numeric" />
          </label>
          <label className="field">
            <span>At the handover date, a balance whose owner answered without proof</span>
            <select value={rules.hold_answered ? "hold" : "release"} onChange={(e) => setRules({ ...rules, hold_answered: e.target.value === "hold" })}>
              <option value="hold">Hold it while the proof is completed</option>
              <option value="release">Release it to the State</option>
            </select>
          </label>
          <div className="actions">
            <button type="submit" className="primary primary-small">Save the limits</button>
            <button type="button" className="plain" onClick={() => setRules(null)}>Cancel</button>
          </div>
        </form>
      )}
    </section>
  );
}

const HOLDER_FIELDS: [keyof HolderDetails, string][] = [
  ["name", "Your company's name, as it stands on the letter"], ["street", "Street"], ["city", "City"], ["region", "State"],
  ["postcode", "ZIP code"], ["contact", "Who answers owners"], ["email", "Email for owners"], ["phone", "Telephone for owners"],
];

/** The holder's own details for the letter. The notice must carry a way to reach the holder. */
function HolderForm({ onSave }: { onSave: (holder: HolderDetails) => Promise<void> }) {
  const [holder, setHolder] = useState<HolderDetails>({ name: "", street: "", city: "", region: "", postcode: "", country: "US", contact: "", email: "", phone: "" });
  return (
    <form className="panel holder-form" onSubmit={(e) => { e.preventDefault(); void onSave(holder); }}>
      <p className="panel-label">Your details for the letter</p>
      <div className="map-grid">
        {HOLDER_FIELDS.map(([key, label]) => (
          <label className="field" key={key}>
            <span>{label}</span>
            <input value={holder[key]} onChange={(e) => setHolder({ ...holder, [key]: e.target.value })} />
          </label>
        ))}
      </div>
      <button type="submit" className="primary primary-small">Save these details</button>
    </form>
  );
}
