import { useState, type FormEvent } from "react";
import Waiting from "./Waiting";
import type { DemoPerson, PayeeRequest } from "../types";

const CURRENCIES: { code: "PHP" | "MXN"; label: string }[] = [
  { code: "PHP", label: "Philippine pesos, to a bank account in the Philippines" },
  { code: "MXN", label: "Mexican pesos, to a bank account in Mexico" },
];

interface Props {
  /** The name the claim is in. The account must be in this name, and the server refuses any other. */
  claimantName: string;
  /** Set when the claim's money is already held in one currency, so the account must take that one. */
  onlyCurrency?: "PHP" | "MXN";
  /** The demonstration person whose claim this is, when it is one: a button then fills the form with her account. */
  fill?: DemoPerson | null;
  submitLabel: string;
  onSubmit: (details: PayeeRequest) => Promise<void>;
}

/** The claimant's own bank account. Used before the payer decides, and again to correct it after a failed payment. */
export default function BankDetails({ claimantName, onlyCurrency, fill, submitLabel, onSubmit }: Props) {
  const [form, setForm] = useState<PayeeRequest>({
    currency: onlyCurrency ?? "PHP", first_name: "", last_name: "", account_number: "", swift_code: "", street_address: "", city: "", postcode: "", state: "",
  });
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const set = (key: keyof PayeeRequest, value: string) => setForm({ ...form, [key]: value });
  const mexico = form.currency === "MXN";

  const send = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      await onSubmit(form);
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="payout-form" onSubmit={send} noValidate>
      {fill && (!onlyCurrency || onlyCurrency === fill.bank.currency) && (
        <button type="button" className="fill-for-me" onClick={() => setForm({ ...fill.bank })}>
          Fill this in for {fill.short_name}
        </button>
      )}
      <fieldset>
        <legend>Currency</legend>
        {CURRENCIES.filter((c) => !onlyCurrency || c.code === onlyCurrency).map((c) => (
          <label className="choice" key={c.code}>
            <input type="radio" name="currency" checked={form.currency === c.code} onChange={() => set("currency", c.code)} />
            <span>{c.label}</span>
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Account holder</legend>
        <div className="row">
          <label className="field">
            <span>First name</span>
            <input value={form.first_name} onChange={(e) => set("first_name", e.target.value)} autoComplete="given-name" />
          </label>
          <label className="field">
            <span>Last name</span>
            <input value={form.last_name} onChange={(e) => set("last_name", e.target.value)} autoComplete="family-name" />
          </label>
        </div>
        <p className="quiet field-hint">
          The claim is in the name of {claimantName}. A claim is paid only into an account in that name.
        </p>
      </fieldset>
      <fieldset>
        <legend>Bank account</legend>
        <div className="row">
          <label className="field">
            <span>{mexico ? "CLABE, 18 digits" : "Account number, 8 to 16 digits"}</span>
            <input value={form.account_number} onChange={(e) => set("account_number", e.target.value)} inputMode="numeric" autoComplete="off" />
          </label>
          {!mexico && (
            <label className="field field-kind">
              <span>Bank's SWIFT code</span>
              <input value={form.swift_code} onChange={(e) => set("swift_code", e.target.value)} autoComplete="off" />
            </label>
          )}
        </div>
      </fieldset>
      <fieldset>
        <legend>Your address</legend>
        <label className="field">
          <span>Street address</span>
          <input value={form.street_address} onChange={(e) => set("street_address", e.target.value)} autoComplete="address-line1" />
        </label>
        <div className="row">
          <label className="field">
            <span>City</span>
            <input value={form.city} onChange={(e) => set("city", e.target.value)} autoComplete="address-level2" />
          </label>
          <label className="field field-short">
            <span>{mexico ? "State code, such as MX-CMX" : "Province"}</span>
            <input value={form.state} onChange={(e) => set("state", e.target.value)} autoComplete="address-level1" />
          </label>
          <label className="field field-short">
            <span>Postcode</span>
            <input value={form.postcode} onChange={(e) => set("postcode", e.target.value)} autoComplete="postal-code" />
          </label>
        </div>
      </fieldset>
      {problem && <p className="notice">{problem}</p>}
      {busy ? (
        <Waiting>The bank details are being checked.</Waiting>
      ) : (
        <button type="submit" className="secondary secondary-flat">
          {submitLabel}
        </button>
      )}
    </form>
  );
}
