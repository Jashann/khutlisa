import SiteNav from "./SiteNav";
import { STEPS, type StepId, type StepLinks } from "../steps";

interface Props {
  /** The step the person is on. Leave it out on screens that are not part of the claimant's path. */
  now?: StepId;
  /** The steps the person can go to from here. A step with no entry is shown but cannot be chosen. */
  go?: StepLinks;
  note?: string;
  /** No longer used: the one demonstration badge is shown whenever the server offers demonstration people. */
  sample?: boolean;
  /** No longer used: the "What is real here" button is in the navigation on every screen. */
  real?: boolean;
  onHome: () => void;
}

export default function Masthead({ now, go = {}, note, onHome }: Props) {
  const at = STEPS.findIndex((s) => s.id === now);
  return (
    <header className="masthead masthead-bar">
      <div className="masthead-left">
        <button className="wordmark wordmark-button" onClick={onHome} title="Back to the opening">
          Khutlisa
        </button>
        <SiteNav />
      </div>
      {!now && note && <p className="masthead-note">{note}</p>}
      {now && (
        <nav aria-label="Where you are">
          <ol className="steps">
            {STEPS.map((step, i) => {
              const state = i === at ? "step step-now" : i < at ? "step step-done" : "step";
              const open = go[step.id];
              const inside = (
                <>
                  <span className="step-number">{i + 1}</span>
                  {step.label}
                </>
              );
              return (
                <li key={step.id} className={state} aria-current={i === at ? "step" : undefined}>
                  {open ? (
                    <button type="button" className="step-link" onClick={open} title={i === at ? undefined : `Go to ${step.label.toLowerCase()}`}>
                      {inside}
                    </button>
                  ) : (
                    <span className="step-link step-off">{inside}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      )}
    </header>
  );
}
