import { useEffect, useRef, useState, type FormEvent } from "react";
import { hearAudio, intakeAudio, intakeText } from "../api";
import { useDemo } from "../demo";
import type { DemoPerson, History, IntakeResult } from "../types";
import Waiting from "./Waiting";

interface Props {
  /**
   * Called with what the person said, in the same shape the form produces. The history screen fills the form
   * with it and runs the search straight away.
   */
  onHistory: (history: History, answeredAQuestion: boolean) => void;
  /** True once the search has a strong match. No further question is put to the person after that. */
  settled?: boolean;
}

type Phase = "idle" | "recording" | "hearing" | "understanding" | "speaking";

/**
 * Where the words of a demonstration person's account on screen came from: "heard" is what the speech recogniser
 * on the server heard from her sound file, "prepared" is the prepared text shown because the sound could not be
 * transcribed there, and "typed" is an account that has no sound at all.
 */
type Source = "heard" | "prepared" | "typed";

/**
 * Shows words one at a time while a sound file of them plays, and ends when the sound ends. The time for each
 * word is its share of the letters, so the words keep pace with the voice. `words` is asked again on every
 * step, because the words the recogniser heard arrive a moment after the sound has started. With no sound file,
 * or when the browser will not play it, the words are typed out at a steady pace instead.
 */
function sayAloud(words: () => string, sound: string | null, onWords: (shown: string, playing: HTMLAudioElement | null) => void): Promise<void> {
  const upTo = (share: number) => {
    const all = words().split(/\s+/).filter(Boolean);
    const ends: number[] = [];
    let total = 0;
    for (const w of all) {
      total += w.length + (/[.,]$/.test(w) ? 6 : 1);
      ends.push(total);
    }
    return all.filter((_, i) => (i === 0 ? 0 : ends[i - 1]) / total <= share).join(" ");
  };
  return new Promise((resolve) => {
    // Heard words may not have arrived yet; a sound that will not play is then paced as a short account.
    const count = Math.max(20, words().split(/\s+/).filter(Boolean).length);
    const typed = (seconds: number) => {
      const started = performance.now();
      const timer = window.setInterval(() => {
        const share = (performance.now() - started) / 1000 / seconds;
        onWords(upTo(share), null);
        if (share >= 1) {
          window.clearInterval(timer);
          onWords(words(), null);
          resolve();
        }
      }, 60);
    };
    if (!sound) return typed(Math.min(6, count * 0.09));
    const audio = new Audio(sound);
    let frame = 0;
    const follow = () => {
      if (audio.duration > 0) onWords(upTo(audio.currentTime / audio.duration), audio);
      frame = window.requestAnimationFrame(follow);
    };
    audio.onended = () => {
      window.cancelAnimationFrame(frame);
      onWords(words(), null);
      resolve();
    };
    audio.onerror = () => {
      window.cancelAnimationFrame(frame);
      typed(Math.min(6, count * 0.09));
    };
    audio.play().then(() => {
      frame = window.requestAnimationFrame(follow);
    }, () => typed(Math.min(6, count * 0.09)));
  });
}
const LIMIT_SECONDS = 180;

const clockText = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

/** The search takes the plain place fields. The years and the kind of stay are only for the timeline here. */
function forSearch(result: IntakeResult): History {
  return {
    ...result.history,
    places: result.history.places.map((p) => ({
      city: p.city, region: p.region, postcode: p.postcode, country: p.country ?? "", street: p.street ?? "",
    })),
  };
}

/** The server joins a follow-up answer to the earlier words in its own note form. Show it as a conversation. */
const said = (transcript: string) =>
  transcript.replace(/\(They were then asked: ([^]*?)\)\n/g, "Khutlisa asked: $1\n").replace(/^They answered: /gm, "You answered: ");

function years(from: number | null, to: number | null): string {
  if (from && to) return from === to ? `${from}` : `${from} to ${to}`;
  if (from) return `from ${from}`;
  if (to) return `until ${to}`;
  return "years not said";
}

export default function VoiceIntake({ onHistory, settled = false }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [seconds, setSeconds] = useState(0);
  const [problem, setProblem] = useState("");
  const [result, setResult] = useState<IntakeResult | null>(null);
  const { people, follow, speechReady } = useDemo();
  const [speaker, setSpeaker] = useState<DemoPerson | null>(null);
  const [source, setSource] = useState<Source>("typed");
  const [spoken, setSpoken] = useState("");
  const [sounding, setSounding] = useState(false);
  const [typing, setTyping] = useState(false);
  const [words, setWords] = useState("");
  const [answer, setAnswer] = useState("");

  const meter = useRef<HTMLCanvasElement>(null);
  const live = useRef<{ stream: MediaStream; recorder: MediaRecorder; audio: AudioContext; frame: number; timer: number } | null>(null);
  const latest = useRef<IntakeResult | null>(null);
  latest.current = result;

  const release = () => {
    const now = live.current;
    if (!now) return;
    window.cancelAnimationFrame(now.frame);
    window.clearInterval(now.timer);
    now.stream.getTracks().forEach((t) => t.stop());
    void now.audio.close().catch(() => undefined);
    live.current = null;
  };
  useEffect(() => release, []);

  /** Takes a finished intake result, shows it, fills the form and starts the search. */
  const take = (next: IntakeResult, answered: boolean) => {
    setResult(next);
    setAnswer("");
    setWords("");
    if (next.history.family_names.length > 0) onHistory(forSearch(next), answered);
  };

  const run = async (work: (earlier: string, question: string) => Promise<IntakeResult>, fresh = false, alongside?: Promise<void>) => {
    const before = fresh ? null : latest.current;
    setProblem("");
    try {
      const understood = work(before?.full_transcript ?? "", before?.follow_up ?? "");
      understood.catch(() => undefined);      // a failure is reported below, once the voice has finished
      if (alongside) {
        await alongside;
        setPhase("understanding");
      }
      take(await understood, Boolean(before));
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setPhase("idle");
    }
  };

  /** Draws the last few seconds of loudness as bars, newest on the right. */
  const drawLevels = (levels: number[]) => {
    const canvas = meter.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth * ratio;
    const height = canvas.clientHeight * ratio;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    ctx.clearRect(0, 0, width, height);
    const step = width / levels.length;
    levels.forEach((level, i) => {
      const bar = Math.max(2 * ratio, level * height);
      ctx.fillStyle = level > 0.04 ? "#f2b84b" : "#3a4d7a";
      ctx.fillRect(i * step + step * 0.2, (height - bar) / 2, step * 0.6, bar);
    });
  };

  const record = async (fresh: boolean) => {
    setProblem("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setProblem("This browser cannot record sound. You can type your history instead.");
      setTyping(true);
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setProblem("The microphone is not available or was not allowed. You can type your history instead.");
      setTyping(true);
      return;
    }
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
    const recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    recorder.onstop = () => {
      release();
      const audio = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      setPhase("hearing");
      // Hearing the words is quick; understanding them takes longer. Move the message on after a moment.
      const moveOn = window.setTimeout(() => setPhase((p) => (p === "hearing" ? "understanding" : p)), 2500);
      setSpeaker(null);
      void run((earlier, question) => intakeAudio(audio, earlier, question), fresh).finally(() => window.clearTimeout(moveOn));
    };

    const audio = new AudioContext();
    const analyser = audio.createAnalyser();
    analyser.fftSize = 1024;
    audio.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    const levels: number[] = new Array(48).fill(0);
    let lastPush = 0;
    const tick = (at: number) => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const v of samples) sum += ((v - 128) / 128) ** 2;
      const level = Math.min(1, Math.sqrt(sum / samples.length) * 4);
      if (at - lastPush > 70) {
        levels.push(level);
        levels.shift();
        lastPush = at;
      } else {
        levels[levels.length - 1] = Math.max(levels[levels.length - 1], level);
      }
      drawLevels(levels);
      if (live.current) live.current.frame = window.requestAnimationFrame(tick);
    };
    const started = Date.now();
    const timer = window.setInterval(() => {
      const passed = Math.floor((Date.now() - started) / 1000);
      setSeconds(passed);
      if (passed >= LIMIT_SECONDS && recorder.state === "recording") recorder.stop();
    }, 250);
    live.current = { stream, recorder, audio, frame: window.requestAnimationFrame(tick), timer };
    setSeconds(0);
    setPhase("recording");
    recorder.start();
  };

  const stop = () => {
    if (live.current?.recorder.state === "recording") live.current.recorder.stop();
  };

  const sendTyped = (event: FormEvent) => {
    event.preventDefault();
    if (!words.trim()) return;
    setPhase("understanding");
    setSpeaker(null);
    void run((earlier, question) => intakeText(words, earlier, question), true);
  };

  const sendAnswer = (event: FormEvent) => {
    event.preventDefault();
    if (!answer.trim()) return;
    setPhase("understanding");
    void run((earlier, question) => intakeText(answer, earlier, question));
  };

  /**
   * Plays one of a demonstration person's sound files and takes it through the same path a microphone recording
   * takes. The file the browser plays is the file sent to the server: first for the words alone, so that what
   * the recogniser heard can be shown while the sound is still playing, then to /api/intake/audio, which
   * transcribes it again and hands the words to the language model. Nothing of the prepared text is sent.
   *
   * When the server has no speech engine, or the sound cannot be transcribed there, the prepared text is shown
   * and sent instead, and the screen says so. An account with no sound file is typed out and sent as text.
   */
  const playAccount = (prepared: string, sound: string | null, show: (words: string) => void, fresh: boolean) => {
    const shown = { words: prepared };
    let understood = (earlier: string, question: string) => intakeText(prepared, earlier, question);
    let heardAll: Promise<void> = Promise.resolve();
    if (sound && speechReady) {
      shown.words = "";
      setSource("heard");
      const file = fetch(sound).then((r) => {
        if (!r.ok) throw new Error("The sound file could not be loaded.");
        return r.blob();
      });
      const heard = file.then(hearAudio);
      heardAll = heard.then(
        (h) => {
          shown.words = h.transcript;
        },
        () => {
          shown.words = prepared;
          setSource("prepared");
        },
      );
      understood = (earlier, question) =>
        heard.then(
          () => file.then((blob) => intakeAudio(blob, earlier, question)),
          () => intakeText(prepared, earlier, question),
        );
    } else {
      setSource(sound ? "prepared" : "typed");
    }
    setPhase("speaking");
    const voice = sayAloud(() => shown.words, sound, (words, playing) => {
      show(words);
      setSounding(Boolean(playing));
    });
    void run(understood, fresh, Promise.all([voice, heardAll]).then(() => show(shown.words)));
  };

  /** A demonstration person's account: a synthetic voice reading it from a sound file, or the typed text. */
  const example = (person: DemoPerson) => {
    follow(person.key);
    setSpeaker(person);
    setResult(null);
    setSpoken("");
    playAccount(person.words, person.audio, setSpoken, true);
  };

  /** Her answer to the follow-up question, played and transcribed the same way and sent as the answer. */
  const answerFor = (person: DemoPerson) => {
    setAnswer("");
    playAccount(person.answer, person.answer_audio, setAnswer, false);
  };

  /** One line, shown while a demonstration account plays, that says what the sound and the words are. */
  const sourceNote = (person: DemoPerson) =>
    source === "heard" ? person.spoken_note
      : source === "prepared" ? person.prepared_note
        : `Typed, not spoken: no ${person.language} voice is installed on this computer.`;

  const busy = phase === "hearing" || phase === "understanding" || phase === "speaking";
  const speaking = phase === "speaking";
  const recording = phase === "recording";
  const h = result?.history;

  return (
    <aside className="voice" aria-label="Tell your history aloud">
      <div className="voice-top">
        <button
          type="button"
          className={recording ? "mic mic-live" : "mic"}
          onClick={recording ? stop : () => void record(true)}
          disabled={busy}
          aria-label={recording ? "Stop recording" : "Start recording"}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            {recording ? (
              <rect x="7" y="7" width="10" height="10" rx="2" />
            ) : (
              <path d="M12 15a3.5 3.5 0 0 0 3.5-3.5v-5a3.5 3.5 0 0 0-7 0v5A3.5 3.5 0 0 0 12 15Zm6-3.5a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.9V20H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.6a6 6 0 0 0 5-5.9Z" />
            )}
          </svg>
        </button>
        <div className="voice-say">
          {phase === "idle" && (
            <>
              <p className="voice-title">{result ? "Tell it again, or add to it below" : "Tell us aloud, in your own language"}</p>
              {!result && <p className="voice-hint">Say your names, where you lived and worked, and who paid you. It is turned into words on this computer.</p>}
            </>
          )}
          {recording && (
            <>
              <p className="voice-title">
                Listening <span className="voice-clock">{clockText(seconds)}</span>
              </p>
              <canvas ref={meter} className="voice-meter" role="img" aria-label="Sound level" />
              <p className="voice-hint">Press the square when you have finished. Recording stops by itself after three minutes.</p>
            </>
          )}
          {phase === "hearing" && <Waiting>Turning your recording into words.</Waiting>}
          {phase === "understanding" && (
            <Waiting>Reading the words and building the history.</Waiting>
          )}
          {speaking && speaker && (
            <>
              <p className="voice-title">
                {sounding
                  ? `A synthetic voice is reading ${speaker.short_name}'s account, in ${speaker.language}`
                  : `${speaker.short_name}'s account, in ${speaker.language}`}
                {sounding && <span className="bars" aria-hidden="true"><i /><i /><i /><i /><i /></span>}
              </p>
              <p className="voice-hint voice-source" title={sourceNote(speaker) ?? undefined}>
                {source === "typed" || !speaker.audio ? sourceNote(speaker) : source === "prepared" ? "Synthetic voice, prepared account. Not transcribed here." : "Synthetic voice, prepared account. The words are what the recogniser heard."}
              </p>
            </>
          )}
        </div>
      </div>

      {!recording && !busy && (
        <div className="voice-other">
          {people.map((person) => (
            <button type="button" className="secondary secondary-flat example" key={person.key} onClick={() => example(person)}>
              {person.audio ? `Hear ${person.short_name}, in ${person.language} (synthetic voice)` : `Read ${person.short_name}'s account, typed in ${person.language}`}
            </button>
          ))}
          <button type="button" className="plain" onClick={() => setTyping(!typing)}>
            {typing ? "Hide the typing box" : "Type it instead"}
          </button>
        </div>
      )}

      {typing && !recording && !busy && (
        <form className="voice-typed" onSubmit={sendTyped}>
          <label className="field">
            <span>Your history in your own words, in any language</span>
            <textarea rows={4} value={words} onChange={(e) => setWords(e.target.value)} maxLength={4000} />
          </label>
          <button type="submit" className="secondary secondary-flat" disabled={!words.trim()}>
            Read my words
          </button>
        </form>
      )}

      {problem && <p className="notice voice-notice">{problem}</p>}

      {speaking && !result && speaker && (
        <div className="heard heard-speaking">
          <p className="panel-label">
            {source === "heard" ? `What the speech recogniser heard, in ${speaker.language}`
              : source === "prepared" ? `The prepared text, in ${speaker.language}. The sound was not transcribed here`
                : `Her account, typed in ${speaker.language}`}
          </p>
          <p className="heard-own" lang={speaker.language_code}>{spoken}</p>
        </div>
      )}

      {result && h && !recording && (
        <div className={busy && !speaking ? "heard heard-stale" : "heard"} aria-busy={busy}>
          <div className="heard-words">
            <div>
              <p className="panel-label">
                {!speaker ? "Your words"
                  : source === "heard" ? "Heard from the synthetic voice"
                    : source === "prepared" ? "The prepared text, not transcribed here"
                      : "Her typed account"}
                {result.language ? `, in ${result.language}` : ""}
              </p>
              <p className="heard-own" lang="und">{said(result.full_transcript)}</p>
            </div>
            <div>
              <p className="panel-label">In English</p>
              <p className="heard-english">{result.english || "No translation came back."}</p>
            </div>
          </div>

          <p className="panel-label">What Khutlisa took from it</p>
          <dl className="timeline">
            <div>
              <dt>Names used</dt>
              <dd>
                {h.given_names.length + h.family_names.length === 0 && <span className="quiet">No name was heard.</span>}
                {h.given_names.map((n) => (
                  <span className="chip" key={`g-${n}`}>{n}<small>given name</small></span>
                ))}
                {h.family_names.map((n) => (
                  <span className="chip chip-gold" key={`f-${n}`}>{n}<small>family name</small></span>
                ))}
              </dd>
            </div>
            <div>
              <dt>Places</dt>
              <dd>
                {h.places.length === 0 && <span className="quiet">No place was heard.</span>}
                <ol className="timeline-places">
                  {h.places.map((p, i) => (
                    <li key={i}>
                      <span className="timeline-years">{years(p.from_year, p.to_year)}</span>
                      <span>
                        {[p.street, p.city, [p.region, p.postcode].filter(Boolean).join(" "), p.country].filter(Boolean).join(", ")}
                        {p.what ? ` (${p.what})` : ""}
                      </span>
                    </li>
                  ))}
                </ol>
              </dd>
            </div>
            <div>
              <dt>Organisations</dt>
              <dd>
                {h.employers.length === 0 && <span className="quiet">No employer or bank was heard.</span>}
                {h.employers.map((n) => (
                  <span className="chip" key={n}>{n}</span>
                ))}
              </dd>
            </div>
          </dl>

          {h.family_names.length > 0 ? null : (
            <p className="notice voice-notice">No family name was heard, so there is nothing to search for yet. Say or type your family name below.</p>
          )}

          {result.follow_up && !settled && (!busy || speaking) && (
            <form className="follow" onSubmit={sendAnswer}>
              <p className="panel-label">{result.follow_up_asks_for === "postcode" ? "One more question: the old postcode" : "One more question"}</p>
              <p className="follow-own">{result.follow_up}</p>
              {result.follow_up_english && result.follow_up_english !== result.follow_up && (
                <p className="follow-english">{result.follow_up_english}</p>
              )}
              <div className="follow-answer">
                <textarea rows={2} value={answer} onChange={(e) => setAnswer(e.target.value)} aria-label="Your answer" placeholder="Type your answer in any language" maxLength={4000} readOnly={speaking} />
                {speaker && (
                  <button type="button" className="secondary secondary-flat fill-for-me" disabled={busy} onClick={() => answerFor(speaker)}>
                    {speaker.answer_audio ? `Hear ${speaker.short_name}'s answer` : `Fill in ${speaker.short_name}'s answer`}
                  </button>
                )}
                <button type="submit" className="secondary secondary-flat" disabled={!answer.trim() || busy}>
                  Send my answer
                </button>
                <button type="button" className="secondary secondary-flat" disabled={busy} onClick={() => void record(false)}>
                  Answer aloud
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </aside>
  );
}
