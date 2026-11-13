import { useEffect, useState, type FormEvent } from "react";
import { getCountries } from "../api";
import Masthead from "../components/Masthead";
import VoiceIntake from "../components/VoiceIntake";
import Waiting from "../components/Waiting";
import { useDemo } from "../demo";
import { exact } from "../format";
import type { Claimant, CountryName, History } from "../types";
import { answerNotice, getOwnerNotice, type OwnerNotice } from "./api";
import { NoticeBody } from "./HolderListScreen";

/** The words of this screen before a notice is open, when the owner's language is not yet known. */
const START = {
  title: "A notice about your money",
  lead: "If you received a letter with a code, type the code here. You will see your notice in your language.",
  label: "The code from your letter",
  open: "Open my notice",
};

/**
 * The owner's side of a notice: opened with the code on the letter, shown in the owner's language with English
 * one press away, and answered here. The answer opens a claim on that exact record, and the claim screen takes over.
 */
export default function NoticeScreen({ code, onHome }: { code: string; onHome: () => void }) {
  const [typed, setTyped] = useState(code);
  const [notice, setNotice] = useState<OwnerNotice | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [inEnglish, setInEnglish] = useState(false);
  const [countries, setCountries] = useState<CountryName[]>([]);
  const [claimant, setClaimant] = useState<Claimant>({ name: "", address: "", country: "", email: "", relationship: "self" });
  const [history, setHistory] = useState<History | null>(null);
  const { person } = useDemo();

  const open = (wanted: string) => {
    if (!wanted.trim()) return;
    setBusy(true);
    setProblem("");
    getOwnerNotice(wanted.trim())
      .then((n) => {
        setNotice(n);
        setClaimant((c) => ({ ...c, country: c.country || n.country }));
        window.history.replaceState(null, "", `/n/${n.code}`);
      })
      .catch((e: Error) => setProblem(e.message))
      .finally(() => setBusy(false));
  };
  useEffect(() => {
    getCountries().then(setCountries).catch(() => setCountries([]));
    if (code) open(code);
  }, []);

  const head = <Masthead onHome={onHome} note="A notice from a company that holds money for you" />;
  if (!notice) {
    return (
      <main className="flow onescreen">
        {head}
        <div className="flow-body flow-narrow">
          <h1>{START.title}</h1>
          <p className="quiet">{START.lead}</p>
          {problem && <p className="notice">{problem}</p>}
          <form className="key-form" onSubmit={(e) => { e.preventDefault(); open(typed); }}>
            <label className="field">
              <span>{START.label}</span>
              <input value={typed} onChange={(e) => setTyped(e.target.value.toUpperCase())} placeholder="ABCD-EFGH" autoComplete="off" autoFocus />
            </label>
            <button type="submit" className="primary primary-small" disabled={busy || typed.trim() === ""}>{START.open}</button>
          </form>
          {busy && <Waiting counted={false}>Opening the notice.</Waiting>}
        </div>
      </main>
    );
  }

  const own = notice.views.other && !inEnglish ? notice.views.other : notice.views.english;
  const ui = own.ui;
  const lead = ui.lead.replace("{HOLDER}", notice.holder).replace("{AMOUNT}", `USD ${Number(notice.amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}`).replace("{DEADLINE}", notice.deadline);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const made = await answerNotice(notice.code, claimant, history);
      window.location.assign(`/#claim/${made.claim_id}`);
    } catch (err) {
      setProblem((err as Error).message);
      setBusy(false);
    }
  };
  const said = (h: History) => {
    setHistory(h);
    const name = [...h.given_names, ...h.family_names].join(" ");
    setClaimant((c) => ({ ...c, name: c.name || name, country: h.current_country || c.country }));
  };
  const fits = person && notice.demonstration && person.claimant.country === notice.country ? person : null;

  return (
    <main className="flow onescreen outreach">
      {head}
      <div className="outreach-cols outreach-wide owner-notice">
        <section className="pane">
          <div className="owner-top">
            <h1>{ui.title}</h1>
            {notice.views.other && (
              <button type="button" className="secondary secondary-flat" onClick={() => setInEnglish(!inEnglish)}>
                {inEnglish ? notice.views.other.ui.own_language : notice.views.other.ui.other_language}
              </button>
            )}
          </div>
          <div className="owner-figures">
            <div><p className="big-number big-gold">{exact(notice.amount, "USD")}</p><p className="big-caption">{notice.holder}</p></div>
            <div><p className="big-number">{notice.deadline}</p><p className="big-caption">{own.facts[own.facts.length - 1].label}</p></div>
          </div>
          <p className="owner-lead">{lead}</p>
          <NoticeBody text={own} lang={notice.views.other && !inEnglish ? notice.language.code : "en"} />
        </section>
        <aside className="pane outreach-side">
          {notice.claim_id ? (
            <div className="panel">
              <p className="owner-answered">{ui.answered}</p>
              <a className="primary primary-link" href={`/#claim/${notice.claim_id}`}>{ui.continue}</a>
            </div>
          ) : (
            <form className="panel answer-form" onSubmit={submit}>
              <h2>{ui.answer_title}</h2>
              <p className="quiet">{ui.answer_lead.replace("{HOLDER}", notice.holder)}</p>
              {fits && (
                <button type="button" className="secondary secondary-flat" onClick={() => setClaimant(fits.claimant)}>
                  Fill this in for {fits.short_name}
                </button>
              )}
              <label className="field">
                <span>{ui.name}</span>
                <input value={claimant.name} onChange={(e) => setClaimant({ ...claimant, name: e.target.value })} autoComplete="name" required />
              </label>
              <label className="field">
                <span>{ui.address}</span>
                <textarea value={claimant.address} onChange={(e) => setClaimant({ ...claimant, address: e.target.value })} rows={2} required />
              </label>
              <label className="field">
                <span>{ui.country}</span>
                <select value={claimant.country} onChange={(e) => setClaimant({ ...claimant, country: e.target.value })} required>
                  <option value="" />
                  {countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                </select>
              </label>
              <label className="field">
                <span>{ui.email}</span>
                <input type="email" value={claimant.email} onChange={(e) => setClaimant({ ...claimant, email: e.target.value })} autoComplete="email" required />
              </label>
              {problem && <p className="notice">{problem}</p>}
              <button type="submit" className="primary" disabled={busy}>{ui.submit}</button>
              {busy && <Waiting counted={false}>{ui.answer_title}</Waiting>}
              <p className="quiet">{ui.next} {notice.views.other && !inEnglish && ui.english_steps}</p>
              <details className="fold answer-voice">
                <summary>{ui.voice}</summary>
                <VoiceIntake onHistory={said} settled />
              </details>
            </form>
          )}
        </aside>
      </div>
    </main>
  );
}
