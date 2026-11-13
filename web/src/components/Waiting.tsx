import { useEffect, useState } from "react";

/** A line of text with a moving bar under it and the seconds waited so far, for anything that takes a while. */
export default function Waiting({ children, counted = true }: { children: React.ReactNode; counted?: boolean }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="waiting" role="status">
      <p className="waiting-text">
        {children}
        {counted && seconds >= 2 && <span className="waiting-seconds"> {seconds} seconds so far.</span>}
      </p>
      <div className="waiting-bar" aria-hidden="true">
        <span />
      </div>
    </div>
  );
}
