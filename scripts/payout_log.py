"""Writes a redacted record of one payout from its payout file.

    uv run python scripts/payout_log.py data/samples/walk-claims/<claim>/payout.json docs/SANDBOX_RUN_LOG.md

The payout file holds only what Airwallex answered at each step and the request bodies' ids. It holds no key and
no token. Bank account numbers are cut to their last four digits here, in the beneficiary and wherever Airwallex
repeats one in a description.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from khutlisa import payouts  # noqa: E402


def main(source: str, target: str) -> None:
    p = json.loads(Path(source).read_text())
    bank = p["beneficiary"]["beneficiary"]["bank_details"]
    books = payouts.reconciliation(p)
    out = ["# One payout on the Airwallex sandbox, as recorded", "",
           "Written by `scripts/payout_log.py` from the payout file of a real run through the application on the "
           "Airwallex sandbox. The claimant is the made-up person of the walk-through, and a script played every "
           "part (claimant and holder), which is why the steps follow each other within seconds. No real money moved. Bank "
           "account numbers are cut to their last four digits; the file never held a key or a token. Each record in "
           "`docs/` is of a separate run, so the amounts differ from one record to another with the rate of the "
           "moment.", "",
           "## The payout", "",
           f"- Deposit reference: `{p['deposit_reference']}`",
           f"- Expected from the holder: {p['usd_amount']} USD. Arrived: {p.get('deposit_amount')} USD. Incoming fee booked by "
           f"Airwallex: {p.get('deposit_fee')} USD.",
           f"- Route: {payouts.ROUTE_NAMES.get(p.get('route'), p.get('route'))}.",
           f"- Rate: {p.get('client_rate')} (USD to {p['target_currency']}).",
           f"- Left Khutlisa's Airwallex account for the transfer: {p.get('payer_pays')}. Payout fee, inside that "
           f"amount: {(p.get('transfer_fee') or {}).get('amount')} {(p.get('transfer_fee') or {}).get('currency')}.",
           f"- Received: {p.get('target_amount')} {p['target_currency']}, to {bank.get('account_name')}, account "
           f"{payouts._mask_account(bank.get('account_number') or '')} ({bank.get('bank_country_code')}).",
           f"- Final state: {p['state']}. Airwallex transfer `{p.get('transfer_id')}`, status "
           f"{p.get('transfer_status')}.",
           f"- Staged change of circumstance: {payouts.WHAT_IF_LABELS.get(p.get('what_if') or '', 'none')}.", ""]
    rules = p.get("instructions")
    out += ["## The holder's standing instructions bound into the approval", ""]
    out += [f"- {line}" for line in payouts.ins.in_words(rules)]
    if p.get("claim_usd"):
        out += [f"- The claim is {p['claim_usd']} USD; under the fee rule the holder sends {p['usd_amount']} USD."]
    out += [""]
    plan = p.get("plan") or {}
    if plan:
        out += ["## The plan the claimant agreed to", "",
                f"- {plan['route_name']}. {plan['route_reason']}",
                f"- To send: {plan['to_send']['amount']} {plan['to_send']['currency']}. Expected payout fee: "
                f"{plan['payout_fee']['amount']} {plan['payout_fee']['currency']}. Expected to be received: "
                f"{plan['expected_local']['amount']} {plan['expected_local']['currency']}.", ""]
    out += ["## Steps", "", "| Time (UTC) | State | Note |", "| --- | --- | --- |"]
    out += [f"| {e['at']} | {e['state']} | {payouts.mask_digits(e['note'])} |" for e in p.get("history", [])]
    if p.get("attempts"):
        out += ["", "## Earlier transfers", ""]
        out += [f"- `{a['transfer_id']}`, sent to the account ending {a.get('account_last4') or 'not recorded'}: {a['fate']}; "
                f"now {a['status']} ({a['reason']}). Came back: {a['came_back']['amount']} {a['came_back']['currency']}."
                for a in p["attempts"]]
        first = {a.get("account_last4") for a in p["attempts"]}
        now = str(bank.get("account_number") or "")[-4:]
        out += ["", f"The transfer that was paid went to the account ending {now}, "
                    + ("which is a different account from the one the bank refused." if now not in first else
                       "the SAME account the bank refused: this must not happen.")]
    if p.get("decisions"):
        out += ["", "## What changed, and what was decided", "",
                "Lines marked \"decided without asking\" were settled by the payment machine inside the standing "
                "instructions. The others stopped the payment or record that a person agreed.", ""]
        out += [f"- {d['at']}: {'decided without asking (' + d.get('rule', '') + '). ' if d.get('by') == 'agent' else ''}"
                f"{payouts.mask_digits(d['text'])}" for d in sorted(p["decisions"], key=lambda d: d.get("at") or "")]
    out += ["", "## Airwallex's ledger rows for this claim (GET /financial_transactions)", "",
            "| For | Type | Amount | Currency | Status | Airwallex's note | Entry id |", "| --- | --- | --- | --- | --- | --- | --- |"]
    out += [f"| {r['part']} | {r['type']} | {r['amount']} | {r['currency']} | {r['status']} | {r['description']} | {r['id']} |"
            for r in books["lines"]]
    out += ["", "| Currency | Came in | Went out | Left |", "| --- | --- | --- | --- |"]
    out += [f"| {s['currency']} | {s['came_in']} | {s['went_out']} | {s['left']} |" for s in books["sums"]]
    out += ["", books["statement"], ""]
    Path(target).write_text("\n".join(out))
    print(f"wrote {target}: {len(out)} lines")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
