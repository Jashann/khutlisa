import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getDemonstration } from "./api";
import type { DemoPerson } from "./types";

// The demonstration people the server offers, and the one this browser tab is following. The top bar shows one
// badge while there are any, and the "fill for me" controls take their details from the person followed.
interface DemoState {
  people: DemoPerson[];
  person: DemoPerson | null;
  follow: (key: string) => void;
  /** True when the server has a speech engine, so a sound file can be transcribed there. */
  speechReady: boolean;
}

const KEY = "khutlisa-demonstration-person";
const Context = createContext<DemoState>({ people: [], person: null, follow: () => undefined, speechReady: false });

export function DemoProvider({ children }: { children: ReactNode }) {
  const [people, setPeople] = useState<DemoPerson[]>([]);
  const [key, setKey] = useState(() => window.sessionStorage.getItem(KEY) ?? "");
  const [speechReady, setSpeechReady] = useState(false);
  useEffect(() => {
    getDemonstration().then((d) => {
      setPeople(d.people);
      setSpeechReady(Boolean(d.speech_ready));
    }).catch(() => setPeople([]));
  }, []);
  const follow = (next: string) => {
    window.sessionStorage.setItem(KEY, next);
    setKey(next);
  };
  const person = people.find((p) => p.key === key) ?? people[0] ?? null;
  return <Context.Provider value={{ people, person, follow, speechReady }}>{children}</Context.Provider>;
}

export const useDemo = () => useContext(Context);

/** True for a record Khutlisa added itself. "SAMPLE" is the older mark for the same thing. */
export const isDemonstration = (source: string | null | undefined) => source === "DEMO" || source === "SAMPLE";
