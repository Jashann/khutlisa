// The path a person takes through Khutlisa, as the top bar shows it. The history and the matches share one
// screen (src/screens/HistoryScreen.tsx); the proof file and the claim packet share another (ClaimScreen.tsx).
export type StepId = "history" | "matches" | "proof" | "claim" | "payment";

export const STEPS: { id: StepId; label: string }[] = [
  { id: "history", label: "Her history" },
  { id: "matches", label: "Matches" },
  { id: "proof", label: "Proof" },
  { id: "claim", label: "Bank account" },
  { id: "payment", label: "Payment" },
];

/** For each step the person can move to from where they are: what to do when they choose it. */
export type StepLinks = Partial<Record<StepId, () => void>>;
