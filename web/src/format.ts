const whole = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export const count = (n: number) => whole.format(Math.round(n));

export function money(amount: number, currency = "USD", cents = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  }).format(amount);
}

/** "$46.4M" for map labels, where there is no room for the full figure. */
export function shortMoney(amount: number): string {
  if (amount >= 1e9) return `$${(amount / 1e9).toFixed(1)}B`;
  if (amount >= 1e6) return `$${(amount / 1e6).toFixed(1)}M`;
  if (amount >= 1e3) return `$${(amount / 1e3).toFixed(0)}K`;
  return `$${amount.toFixed(0)}`;
}

/** California prefixes each type with a code ("82: Non Standard NAUPA Code for - Savings accts"). Keep the words. */
export function plainPropertyType(raw: string): string {
  const text = raw
    .replace(/^\s*\w+\s*:\s*/, "")
    .replace(/^Non Standard NAUPA Code for\s*-\s*/i, "")
    .trim();
  return text || raw;
}

export function sentence(line: string): string {
  const text = line.trim();
  if (!text) return text;
  const first = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(first) ? first : `${first}.`;
}

/** An amount the API sent as text ("13625.86"), with its currency code spelled out: "13,625.86 MXN". */
export function exact(amount: string | number, currency: string): string {
  if (currency === "USD")
    return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(amount));
  return `${new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(amount))} ${currency}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** "42 seconds", "3 minutes", "5 hours", "12 days": the largest unit that gives a whole number of one or more. */
export function duration(seconds: number): string {
  const units: [number, string][] = [[86400, "day"], [3600, "hour"], [60, "minute"]];
  for (const [size, name] of units) {
    if (seconds >= size) {
      const n = Math.round((seconds / size) * 10) / 10;
      return `${n} ${name}${n === 1 ? "" : "s"}`;
    }
  }
  const n = Math.round(seconds);
  return `${n} second${n === 1 ? "" : "s"}`;
}

export function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

const STATE_WORDS: Record<string, string> = {
  FOUND: "Record found",
  PROOF_NEEDED: "Proof still needed",
  PROOF_READY: "Proof ready",
  PACKET_READY: "Packet ready to sign",
  FILED: "Signed and sent by the claimant",
  APPROVED: "Approved by the holder",
  PAYING: "Payment under way",
  PAID: "Paid",
  REJECTED: "Rejected by the holder",
  PAYMENT_HELD: "Payment on hold",
};
export const stateWords = (state: string) => STATE_WORDS[state] ?? state;

/** The matcher writes its reasons about "they". On the claimant's own screens that person is "you". */
export const toYou = (line: string) => line.replace(/\bthey\b/g, "you").replace(/\bThey\b/g, "You");

/** The same reasons for the payer, who is reading about someone else. */
export const toClaimant = (line: string) =>
  line.replace(/\bthey live\b/g, "the claimant lives").replace(/\bthey\b/g, "the claimant").replace(/\bThey\b/g, "The claimant");

/** "0.4 seconds", or "under a tenth of a second" when the figure would round to nothing. */
export function quick(ms: number): string {
  if (ms < 100) return "under a tenth of a second";
  const s = (ms / 1000).toFixed(1);
  return `${s} ${s === "1.0" ? "second" : "seconds"}`;
}
