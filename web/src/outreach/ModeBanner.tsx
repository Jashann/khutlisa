import { useEffect, useState } from "react";
import { payerKey, setPayerKey } from "../api";
import { getMode, type Mode } from "./api";

/**
 * In the public demonstration: one line at the foot of every screen that says so, and the holder's key taken
 * from the server, because everything behind it there is a demonstration. Elsewhere this shows nothing.
 */
export default function ModeBanner() {
  const [mode, setMode] = useState<Mode | null>(null);
  useEffect(() => {
    getMode()
      .then((m) => {
        if (m.public_demo && m.holder_key && !payerKey()) setPayerKey(m.holder_key);
        setMode(m);
      })
      .catch(() => setMode(null));
  }, []);
  if (!mode?.public_demo) return null;
  return (
    <p className="mode-banner" role="note">
      {mode.notice}
      {mode.model.calls_left_today === 0 && " Today's budget of language model calls is used up, so new words and documents are not read until midnight UTC."}
      {!mode.model.available && " No language model is connected to this copy."}
    </p>
  );
}
