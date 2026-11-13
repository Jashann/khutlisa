"""Runs a slice of one holder's plan as a real batch on the Airwallex sandbox, and writes the record of it.

    uv run python scripts/run_batch.py ["Holder name"] [--refuse 1,7] [--no-refusal] [--out docs/SANDBOX_RUN_LOG_BATCH.md]

It plans the holder's book (khutlisa.book) with the saved limits, takes one demonstration owner in each corridor
the plan works for which an example bank account exists (khutlisa.batch.choose_slice), checks every example
account against the schema Airwallex returns for the corridor today, writes the batch, approves it as the holder
would, and runs it: one deposit, one conversion for each currency the plan chose to convert once, and one transfer
for each owner. The sandbox is asked to refuse two of the transfers (the largest and the smallest unless --refuse
names others). The script then plays the people a refusal waits for, in order: the owner gives her second
example account, the holder approves it, and the owner agrees to the amount where the replacement is outside
the tolerance. At the end every row Airwallex booked for the batch is read again and added up by currency.

The owners are invented and their bank details are examples. Account numbers are cut to their last four digits
in the record, and the sandbox keys are never printed. The batch is kept in data/claims/batches, where the
"Batch" screen of a server on this machine shows it. The fees the sandbox charged are written back to
src/khutlisa/airwallex_corridors.json, so the next plan uses what was seen in place of an estimate.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import airwallex as awx  # noqa: E402
from khutlisa import batch as bt  # noqa: E402
from khutlisa import book as bk  # noqa: E402
from khutlisa import corridors as co  # noqa: E402
from khutlisa import instructions as ins  # noqa: E402
from khutlisa.registers import DB_PATH  # noqa: E402


def money(amount, currency: str) -> str:
    return f"{float(amount):,.2f} {currency}"


def write_log(batch: bt.Batch, view: dict, plan: dict, seconds: float, played: list[str], out: Path) -> None:
    t = plan["totals"]
    lines = [
        "# A batch on the Airwallex sandbox: the record of one real run",
        "",
        f"Batch `{batch.batch_id}`, started {batch.created_at}, finished {batch.finished_at}. Written by "
        "`scripts/run_batch.py` from the batch file and from Airwallex's own answers. Nothing here was typed in by "
        "hand.",
        "",
        "The owners are invented people and their bank details are examples built from Airwallex's live schema for "
        "each country. No real owner was paid and no real money moved: every call went to the Airwallex sandbox. "
        "Account numbers are cut to their last four digits.",
        "",
        "## The plan it is a slice of",
        "",
        f"The book of {plan['holder']['name']} in California's public file: {t['owners']:,} properties worth "
        f"${t['usd']:,.2f} for owners in {t['countries']} countries. The holder did not ask for this plan. Limits: "
        f"tolerance {plan['inputs']['tolerance_percent']} percent, small-claim line "
        f"{float(plan['inputs']['small_claim_usd']):,.2f} USD, handover {plan['handover_words']}.",
        "",
        "Each demonstration owner is owed the median payable claim of her corridor in that book; the owner in the "
        "largest corridor is owed the claim at the ninetieth percentile.",
        "",
        "## The payments",
        "",
        "| # | Owner (invented) | Country | Rail | Owed | Holder sends | Funded | Paid | Airwallex's fee | Account | Transfer |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i in view["items"]:
        fee = f"{float(i['fee']['amount']):,.2f} {i['fee']['currency']}" if i.get("fee") else ""
        funded = {"batch": "one conversion for the batch", "each": "inside its own transfer", "none": "in US dollars"}[i["funded_by"]]
        lines.append(f"| {i['n']} | {i['owner']['name']} | {i['owner']['country_name']} | "
                     f"{'SWIFT' if i['method'] == 'SWIFT' else i.get('scheme') or 'local rails'}, {i['currency']} | "
                     f"{money(i['claim_usd'], 'USD')} | {money(i['holder_sends'], 'USD')} | {funded} | "
                     f"{money(i['paid']['amount'], i['paid']['currency']) if i.get('paid') else i['state_words']} | {fee} | "
                     f"ending {i['account_last4']} | `{i.get('transfer_id') or ''}` |")
    lines += ["", "## The funding", "",
              f"- One deposit of {money(view['deposit']['amount'], 'USD')}, reference `{view['deposit']['reference']}`. "
              f"Airwallex's incoming fee: {money(view['deposit']['fee'], 'USD')}. Left to share out: "
              f"{money(view['deposit']['pool'], 'USD')}."]
    for f in view["funding"]:
        if f["mode"] == "batch" and f.get("buy"):
            lines.append(f"- {f['currency']}: converted once, {money(f['sell_usd'], 'USD')} into {money(f['buy'], f['currency'])} "
                         f"(conversion `{f.get('conversion_id')}`), for {f['payments']} payment{'s' if f['payments'] != 1 else ''}.")
        elif f["mode"] == "each":
            lines.append(f"- {f['currency']}: converted inside each transfer. {f.get('why') or ''}".rstrip())
        else:
            lines.append(f"- {f['currency']}: paid in US dollars, nothing converted.")
    for d in view["decisions"]:
        lines.append(f"- Decided in code ({d.get('rule', '')}): {d['text']}")
    refused = [i for i in view["items"] if i["attempts"]]
    if refused:
        lines += ["", "## The refusals", "",
                  "The sandbox was asked to refuse these transfers after they were sent. The replacement path is the "
                  "ordinary one: the money comes back, the owner gives another account, the holder approves it, and "
                  "the tolerance decides whether the owner is also asked to confirm the smaller amount.", ""]
        for i in refused:
            for a, card in zip(i["attempts"], i["cards"]):
                lines.append(f"- Payment {i['n']} ({i['owner']['name']}): transfer `{a['transfer_id']}` to the account ending "
                             f"{a['account_last4']} ended {a['status']} ({a['reason']}). "
                             f"{money(a['came_back']['amount'], a['came_back']['currency'])} came back. {card['did']} "
                             f"{card['money']} The replacement went to the account ending {i['account_last4']}.")
        lines += ["", "What the script did in place of the people, in order:", ""] + [f"- {p}" for p in played]
    books = view["reconciliation"]
    lines += ["", "## The whole batch against Airwallex's ledger", "",
              f"{books['rows']} rows, read again from `GET /api/v1/financial_transactions` for the deposit, every "
              "conversion and every transfer. " + ("Every currency adds up to zero." if books["balanced"] else
                                                   "NOT balanced: see the sums."), "",
              "| Currency | Came in | Went out | Left |", "| --- | --- | --- | --- |"]
    lines += [f"| {s['currency']} | {float(s['came_in']):,.2f} | {float(s['went_out']):,.2f} | {float(s['left']):,.2f} |" for s in books["sums"]]
    c = view["costs"]
    lines += ["", "## Planned cost beside actual cost", "",
              "| | Incoming fee | Payout fees | In all | Transfers |", "| --- | --- | --- | --- | --- |",
              f"| Planned | {money(c['planned']['incoming_usd'], 'USD')} | {money(c['planned']['payout_usd'], 'USD')} | "
              f"{money(c['planned']['usd'], 'USD')} | {c['planned']['transfers']} |",
              f"| Booked by Airwallex | {money(c['actual']['incoming_usd'], 'USD')} | {money(c['actual']['payout_usd'], 'USD')} | "
              f"{money(c['actual']['usd'], 'USD')} | {c['actual']['transfers']} |",
              "", f"Difference: {money(c['difference_usd'], 'USD')}. {c['note']} Payout fees as Airwallex charged them, by "
              "currency: " + ", ".join(money(f["amount"], f["currency"]) for f in c["actual"]["payout_fees"]) + ". "
              "Fees charged in another currency are counted in US dollars at the mid rate of the payment's own quote.",
              "", "## The run", "",
              f"{view['api_calls']} calls to Airwallex in {seconds:.0f} seconds, paced under the sandbox's limit of ten "
              "requests a second for one endpoint.", ""]
    lines += ["| When | State | What happened |", "| --- | --- | --- |"]
    lines += [f"| {h['at']} | {bt.STATE_WORDS.get(h['state'], h['state'])} | {h['note']} |" for h in view["history"]]
    out.write_text("\n".join(lines) + "\n")


def main(argv: list[str]) -> int:
    names = [a for a in argv if not a.startswith("--") and (argv.index(a) == 0 or not argv[argv.index(a) - 1] in ("--refuse", "--out"))]
    holder = names[0] if names else "Bank of America"
    out = Path(next((argv[i + 1] for i, a in enumerate(argv) if a == "--out"), ROOT / "docs" / "SANDBOX_RUN_LOG_BATCH.md"))
    refuse_arg = next((argv[i + 1] for i, a in enumerate(argv) if a == "--refuse"), None)
    books, found = bk.books(), co.load()
    if books is None or found is None:
        print("Run scripts/make_books.py and scripts/discover_corridors.py first.")
        return 1
    got = books.get(holder)
    if got is None:
        print(f"No holder named {holder!r} can be opened.")
        return 1
    plan = bk.plan(got[0], got[1], found)
    chosen = bt.choose_slice(plan)
    if len(chosen) < 5:
        print(f"The plan works only {len(chosen)} corridors with a demonstration owner; a batch needs five.")
        return 1
    try:
        client = awx.AirwallexClient(*awx.load_credentials())
    except awx.CredentialsError as err:
        print(f"The Airwallex sandbox keys are not set up: {err}")
        return 1
    simulator = awx.SandboxSimulator(client)
    started = time.time()
    for row in chosen:       # the example bank details against the schema Airwallex returns for the corridor today
        payload = bt.example_beneficiary(row["country"], row["currency"], row["method"])
        problems = awx.schema_problems(client.beneficiary_schema(row["country"], row["currency"], row["method"]), payload)
        if problems:
            print(f"The example account for {row['country']} no longer fits the schema: {problems}")
            return 1
        client.validate_beneficiary(payload)
    rules = ins.clean({"tolerance_percent": plan["inputs"]["tolerance_percent"], "small_claim_usd": plan["inputs"]["small_claim_usd"]})
    if "--no-refusal" in argv:
        refuse: tuple[int, ...] = ()
    elif refuse_arg:
        refuse = tuple(int(n) for n in refuse_arg.split(",") if n.strip())
    else:
        order = sorted(range(len(chosen)), key=lambda i: float(chosen[i]["claim_usd"]))
        refuse = tuple(sorted({order[-1] + 1, order[0] + 1}))
    batch = bt.new_batch(DB_PATH.parent / "claims" / "batches", plan["holder"], chosen, plan, rules, refuse=refuse)
    print(f"batch {batch.batch_id}: {len(batch.items)} payments, {batch.plan['holder_funds_usd']} USD to fund; refusals staged on {list(refuse)}")
    bt.approve(batch)
    played: list[str] = []
    idle = 0
    while batch.state not in (bt.DONE, bt.STOPPED) and idle < 240:
        before = bt.BatchRunner._mark(batch)
        try:
            bt.advance(batch, client, simulator)
        except awx.AirwallexError as err:
            print(f"  Airwallex refused a step ({err.code or err.status}): {(err.message or '')[:200]}")
            idle += 20
        for item in batch.items:       # the people a refusal waits for, played in order
            payout = batch.payout(item["n"])
            needs = (payout.hold or {}).get("needs") if payout else None
            if not needs or not (payout.hold or {}).get("plan"):
                continue
            if needs[0] == "bank_details":
                bt.give_corrected_account(batch, item["n"])
                played.append(f"Payment {item['n']}: the owner gave her second example account, ending {item['account_last4']}.")
            elif needs[0] == "payer":
                bt.approve_item(batch, item["n"])
                played.append(f"Payment {item['n']}: the holder approved the corrected account.")
            elif needs == ["claimant"]:
                bt.owner_agrees(batch, item["n"])
                played.append(f"Payment {item['n']}: the owner agreed to the smaller amount, because it was outside the tolerance.")
        after = bt.BatchRunner._mark(batch)
        if after == before:
            idle += 1
            time.sleep(1.0)
        else:
            idle = 0
            states = " ".join(f"{i['n']}:{(batch.payout(i['n']).state if batch.payout(i['n']) else '-')[:4]}" for i in batch.items)
            print(f"  {batch.state:17} {states}", flush=True)
    batch.api_calls = client.calls
    batch.save()
    seconds = time.time() - started
    view = bt.view(batch)
    write_log(batch, view, plan, seconds, played, out)
    try:      # what the sandbox charged is kept, so the next plan uses it in place of an estimate
        transfers = client._pages("/api/v1/transfers", {"page_size": 200}, max_pages=3)
        found["observed_fees"] = {**(found.get("observed_fees") or {}), **co.observed_fees(transfers)}
        found["observed_fees_at"] = co.now_iso()
        found["calls_per_payment"] = round(client.calls / max(len(batch.items), 1), 1)
        co.save(found)
    except (awx.AirwallexError, OSError):
        pass
    client.close()
    books_ = view["reconciliation"]
    print(f"{view['state_words']}: {view['paid']} of {view['payments']} paid in {seconds:.0f} seconds, {client.calls} calls.")
    print("ledger: " + ("every currency adds up to zero" if books_["balanced"] else "NOT balanced") + "; " +
          "; ".join(f"{s['currency']} left {s['left']}" for s in books_["sums"]))
    print(f"planned cost {view['costs']['planned']['usd']} USD, booked {view['costs']['actual']['usd']} USD")
    print(f"wrote {out}")
    return 0 if batch.state == bt.DONE and books_["balanced"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
