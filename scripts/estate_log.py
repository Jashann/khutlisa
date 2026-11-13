"""Writes a redacted record of one estate settlement from its files.

    .venv/bin/python scripts/estate_log.py data/samples/walk-heirs-claims/<claim> docs/SANDBOX_RUN_LOG_ESTATE.md

The folder is a claim's own folder: `estate_settlement.json` and one payout file per heir beside it, with the
claim file one level up. They hold only what Airwallex answered at each step and the ids of the requests. They
hold no key and no token. Bank account numbers are cut to their last four digits here, in each beneficiary and
wherever Airwallex repeats one in a description.
"""
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from khutlisa import estate_settlement as es  # noqa: E402
from khutlisa import payouts  # noqa: E402


def main(folder: str, target: str) -> None:
    folder = Path(folder)
    claim = json.loads(folder.with_suffix(".json").read_text())
    settlement = es.Settlement.open(folder / "estate_settlement.json", claim["id"])
    estate = claim["estate"]
    owed = es.entitlements(claim["record"]["amount"], estate["heirs"])
    books = es.reconciliation(settlement)
    paid = settlement.paid_heirs()
    out = ["# One estate settlement on the Airwallex sandbox, as recorded", "",
           "Written by `scripts/estate_log.py` from the files of a real run through the application on the Airwallex "
           "sandbox (`scripts/walkthrough_heirs.mjs`). The owner, the family and every document are invented, and a "
           "script played every part (the family and the holder), which is why the steps follow each other within "
           "seconds. No real money moved. Bank account numbers are cut to their last four digits; the files never "
           "held a key or a token.", "",
           "## The estate", "",
           f"- Property: {Decimal(str(claim['record']['amount'])):,.2f} USD, held by {claim['record']['holder_name']}.",
           f"- Owner (invented): {estate['family']['decedent']['name']}, died {estate['family']['decedent']['died_on']}, "
           f"living in {estate['family']['decedent']['domicile_state'] or estate['family']['decedent']['domicile_country']}.",
           f"- Basis: {estate['succession']['basis']}; the money was the owner's {estate['family']['property']} property.",
           f"- Final state of the claim: {claim['state']}.", "",
           "| Heir | Relation | Lives in | Fraction | Entitlement (USD) | Paid |", "| --- | --- | --- | --- | --- | --- |"]
    for heir in estate["heirs"]:
        got = paid.get(heir["id"])
        out.append(f"| {heir['name']} | {heir['relation']} | {heir.get('country')} | {heir['share']} | "
                   f"{es.dollars(owed[heir['id']])} | {es.figure(got['amount'], got['currency']) if got else 'not paid'} |")
    out += ["", f"The entitlements add up to {es.dollars(sum(owed.values()))} USD. {es.ROUNDING_RULE}", "",
            "## The statute steps behind the fractions", ""]
    out += [f"{s['n']}. Probate Code {s['section']}: {s['text']}" for s in estate["succession"]["steps"]]
    for flag in estate["succession"].get("flags") or []:
        out += ["", f"Flag: {flag['text']}"]
    for rnd in settlement.rounds:
        if rnd["state"] == es.PLANNED:
            continue
        plan, arrived = rnd["plan"], rnd.get("arrived") or {}
        out += ["", f"## Round {rnd['n']}", "",
                f"- Deposit reference: `{rnd['reference']}`. Planned from the holder: {plan['holder_sends']} USD "
                f"(of which the holder adds {plan['holder_adds']} USD under its fee rule). Arrived: "
                f"{arrived.get('deposit')} USD. Incoming fee booked by Airwallex: {arrived.get('incoming_fee')} USD. "
                f"Left to divide: {arrived.get('net')} USD.",
                f"- Held in this round, not sent: {', '.join(h['name'] + ' ' + h['entitlement'] + ' USD' for h in plan['held']) or 'nobody'}.",
                f"- Final state of the round: {rnd['state']}.", "",
                "| Heir | Sent for them (USD) | Fees borne by | Route | One dollar bought | Payout fee | Planned | Received | "
                "Account | Transfer | Status |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for meta, leg in settlement.legs(rnd):
            planned = meta["planned"]
            if leg is None:
                continue
            bank = leg.beneficiary["beneficiary"]["bank_details"]
            fee = leg.transfer_fee or {}
            out.append(
                f"| {meta['name']} | {leg.usd_amount} | {'the holder' if planned['covered'] else 'the heir'} | "
                f"{payouts.ROUTE_NAMES.get(leg.route, leg.route)} | {planned['per_dollar']} {leg.target_currency} | "
                f"{fee.get('amount')} {fee.get('currency')} | {es.figure(planned['expected_local']['amount'], leg.target_currency)} | "
                f"{es.figure(leg.target_amount, leg.target_currency) if leg.target_amount else ''} | "
                f"{payouts._mask_account(bank.get('account_number') or '')} ({bank.get('bank_country_code')}) | "
                f"`{leg.transfer_id}` | {leg.state} |")
        for meta, leg in settlement.legs(rnd):
            if leg is None or not leg.attempts:
                continue
            out += ["", f"Earlier transfers for {meta['name']}:", ""]
            out += [f"- `{a['transfer_id']}` to the account ending {a.get('account_last4')}: {a['fate']}; now {a['status']} "
                    f"({a['reason']}). Came back: {a['came_back']['amount']} {a['came_back']['currency']}. Airwallex kept "
                    f"its fee of {(a.get('fee_kept') or {}).get('amount')} {(a.get('fee_kept') or {}).get('currency')}."
                    for a in leg.attempts]
            out += [f"- {d['at']}: decided without asking ({d.get('rule')}). {payouts.mask_digits(d['text'])}"
                    for d in leg.decisions if d.get("by") == "agent"]
        out += ["", "What happened, in order:", ""]
        out += [f"- {e['at']}: {payouts.mask_digits(e['text'])}" for e in rnd["events"]]
    rules = (settlement.rounds[0].get("rules") if settlement.rounds else None)
    out += ["", "## The holder's standing instructions bound into the approval", ""]
    out += [f"- {line}" for line in payouts.ins.in_words(rules)]
    out += [f"- {es.FEE_RULE_WORDS}"]
    out += ["", "## Airwallex's ledger rows for this estate (GET /financial_transactions)", "",
            "| For | Type | Amount | Currency | Status | Airwallex's note | Entry id |", "| --- | --- | --- | --- | --- | --- | --- |"]
    out += [f"| {r['who']} | {r['type']} | {r['amount']} | {r['currency']} | {r['status']} | {r['description']} | {r['id']} |"
            for r in books["lines"]]
    out += ["", "| Currency | Came in | Went out | Left |", "| --- | --- | --- | --- |"]
    out += [f"| {s['currency']} | {s['came_in']} | {s['went_out']} | {s['left']} |" for s in books["sums"]]
    out += ["", books["statement"], ""]
    Path(target).write_text("\n".join(out))
    print(f"wrote {target}: {len(out)} lines")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
