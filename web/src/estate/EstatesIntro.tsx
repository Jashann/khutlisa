import { useEffect, useState } from "react";
import { createClaim, search } from "../api";
import Masthead from "../components/Masthead";
import type { Claimant, History } from "../types";
import { getSample } from "./api";
import type { EstateSample } from "./types";

/** Where estates begin: what happens when the owner has died, and the demonstration family to follow. */
export default function EstatesIntro({ onHome, onEstate }: { onHome: () => void; onEstate: (claimId: string) => void }) {
  const [sample, setSample] = useState<EstateSample | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  useEffect(() => { getSample().then(setSample).catch((e: Error) => setProblem(e.message)); }, []);

  const follow = async () => {
    if (!sample?.search || !sample.claimant) return;
    setBusy(true);
    setProblem("");
    try {
      const found = await search(sample.search as unknown as History);
      // The strongest demonstration match for the family's search is the owner's own record.
      const match = found.matches.find((m) => m.source === "DEMO");
      if (!match) throw new Error("The demonstration estate's record is not on this server.");
      const claim = await createClaim(match, sample.claimant as unknown as Claimant, sample.search as unknown as History);
      onEstate(claim.id);
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flow onescreen">
      <Masthead onHome={onHome} note="When the owner has died" />
      <div className="flow-body flow-narrow estates-intro">
        <h1>When the owner has died, the family is paid as one estate</h1>
        <p>
          The money then belongs to the heirs. One of them says, in her own language, who the family is. The shares are worked out
          in code under California's rules, each heir is tied to the owner by documents, and the holder approves the estate on those
          exact shares. One settlement then pays every proven heir at home, each in their own currency, from one deposit. An heir who
          is not proven yet is held, and paid in a later round.
        </p>
        <ol>
          <li>The family, in the claimant's words, and one question for what the rule still needs.</li>
          <li>The proof for each heir: the owner's death certificate, then each heir's chain of civil records and identification.</li>
          <li>The holder approves the exact shares, after the checks across every claim in the queue.</li>
          <li>One settlement to every proven heir, with Airwallex's lines added up to zero in every currency.</li>
        </ol>
        {sample && (
          <p className="quiet">
            The demonstration family is invented: {sample.owner}. {sample.about} Every document is marked SAMPLE, and the payments run on the
            Airwallex sandbox. An estate is funded by a bank deposit, never on Metal.
          </p>
        )}
        {problem && <p className="notice">{problem}</p>}
        <div className="actions">
          <button type="button" className="primary" disabled={busy || !sample?.search} onClick={() => void follow()}>
            {busy ? "Opening the estate" : "Follow the demonstration estate"}
          </button>
        </div>
      </div>
    </main>
  );
}
