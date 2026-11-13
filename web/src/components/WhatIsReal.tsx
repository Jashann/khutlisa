import { useEffect, useState } from "react";
import { getMode } from "../outreach/api";

const REAL = [
  "California's whole public unclaimed property file: 95,425,821 owner records, searched live on this server.",
  "Queensland's public unclaimed money register: 2,566,684 records, searched in the same pass. Its amounts stay in Australian dollars.",
  "The organisations that are owed money, the figures by kind of money and of holder, and every holder's book, read from those two files.",
  "California's rules for holders: the notice a holder must send, the dormancy periods and the handover calendar, read on the State Controller's pages, and the checks every notice passes in code.",
  "Every Airwallex call, made on the Airwallex sandbox: the corridors, rates, quotes, fees, transfers, refusals and ledger lines are what it returned.",
  "Metal testnet: each mandate, pull and refusal is a real signed transaction on the testnet, with a link to its explorer. In the public copy funding on Metal is switched off.",
  "The shares of an estate, the checks across claims, the fee rule and the deadlines are worked out in code, from the holder's standing instructions.",
];
const NOT_YET = [
  "Sandbox and testnet money only. No real money moves anywhere.",
  "On Metal testnet one *USDZ stands for 100 US dollars of a claim, because the testnet faucet gives at most 100 *USDZ. The scale is shown beside every amount on Metal.",
  "The people followed through a claim, the families of the estates, the owners in a batch and every document they show are a demonstration: invented, marked SAMPLE, and the voice is synthetic.",
  "The holder's own list is an invented file of invented owners. Notices are prepared here and never sent: the holder sends them and marks them sent.",
  "No holder uses Khutlisa yet. A holder's book is a plan made from public figures; the holder's view is this same app behind a key, and its deposit is staged on the sandbox.",
  "Documents are read, not verified with the issuing authority. The holder approves every payment.",
  "In the public copy the language model's answers for the demonstration were recorded in advance and are replayed. A copy run with a model key, or on a developer's machine, calls the model live.",
  "Paying an owner abroad by bank transfer under sections 1532(b) and 1560(b) is our reading of the law. The main path is the holder paying the owner directly; claiming from the State yourself is the fallback.",
];

/** The one place that says what is real and what is not. Opened from the top bar of every screen. */
export default function WhatIsReal({ small = false }: { small?: boolean }) {
  const [open, setOpen] = useState(false);
  const [publicCopy, setPublicCopy] = useState<boolean | null>(null);
  useEffect(() => {
    if (open && publicCopy === null) getMode().then((m) => setPublicCopy(m.public_demo), () => setPublicCopy(false));
  }, [open, publicCopy]);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open]);
  return (
    <>
      <button type="button" className={small ? "demo-badge real-button real-button-small" : "demo-badge real-button"} onClick={() => setOpen(true)} aria-haspopup="dialog">
        What is real here
      </button>
      {open && (
        <div className="real-veil" onClick={() => setOpen(false)}>
          <section className="real-panel" role="dialog" aria-modal="true" aria-label="What is real here" onClick={(e) => e.stopPropagation()}>
            <header className="real-head">
              <h2>What is real here</h2>
              <button type="button" className="secondary secondary-flat real-close" onClick={() => setOpen(false)} autoFocus>
                Close
              </button>
            </header>
            {publicCopy && (
              <p className="real-copy">
                This is the public copy. The language model's answers for the demonstration journeys were recorded in advance and are replayed here; funding on Metal is switched off.
              </p>
            )}
            <div className="real-cols">
              <div className="real-col real-yes">
                <h3>Real</h3>
                <ul>
                  {REAL.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
              <div className="real-col real-no">
                <h3>Not real yet</h3>
                <ul>
                  {NOT_YET.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
