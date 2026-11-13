"""Writes docs/METAL_RUN_LOG.md from the record of a real run (scripts/metal_run.py).

    uv run python scripts/metal_log.py

It reads data/metal_run/run.json, data/metal_run/setup.json when it is there, and the payout file of the claim
that was paid. None of them holds a key, a credential or the RPC endpoint. Bank account numbers are cut to their
last four digits. Every transaction hash can be opened on the testnet explorer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from khutlisa import metal as mt, payouts  # noqa: E402

OUT = ROOT / "data" / "metal_run"


def link(tx: str | None) -> str:
    return f"[`{tx}`]({mt.explorer_tx(tx)})" if tx else "not recorded on chain"


def clean(text: str) -> str:
    return payouts.mask_digits(mt.redact(str(text))).replace("|", "/")


def main() -> None:
    run = json.loads((OUT / "run.json").read_text())
    first, second, expired = run.get("first"), run.get("second"), run.get("expired")
    scale = run["scale"]
    out = ["# One claim funded on Metal testnet and paid out through the Airwallex sandbox, as recorded", "",
           "Written by `scripts/metal_log.py` from the record of a real run of `scripts/metal_run.py` on "
           f"{run['started_at'][:10]}. The run went through the application's own routes against {run['network']} "
           f"(`{run['chain']}`, `metal-agent` {run['cli']}) and the Airwallex sandbox. A script played every part: the "
           "owner, the holder and the agent, which is why the steps follow each other within seconds. The owners "
           "are the invented people of the walk-through and only the demonstration records were searched. Document "
           "reading was off, so no language model was called. No real money moved. Bank account numbers are cut to "
           "their last four digits, and no key, credential file or RPC endpoint is in this file.", "",
           f"**{scale['words']}**", "",
           "Every transaction hash below opens on the testnet explorer, "
           f"{mt.EXPLORER}. The addresses:", "",
           f"- The holder's Metal account (pays under the mandate): [`{run['accounts']['holder_account']}`]"
           f"({mt.explorer_address(run['accounts']['holder_account'])})",
           f"- Khutlisa's settlement address (the only payee a mandate names): [`{run['accounts']['settlement']}`]"
           f"({mt.explorer_address(run['accounts']['settlement'])})",
           f"- Khutlisa's agent address (pays the gas that records a refusal; used as the wrong payee): "
           f"[`{run['agent']}`]({mt.explorer_address(run['agent'])})",
           f"- The token: *USDZ, `{mt.TOKEN}`, 18 decimals", ""]

    out += ["## What Metal refused, in one table", "",
            "Each refusal was made by the holder's Metal account in the transaction named, which moved nothing. "
            "`metal-agent mandate pull --record-refusal` sends a refused pull so that the refusal is on chain.", "",
            "| Attempt | Amount | Metal's reason | Transaction |", "| --- | --- | --- | --- |"]
    rows = []
    if first:
        for r in first["metal"]["refusals"]:
            rows.append((r["case"], f"{r['amount_usdz']} *USDZ", r["reason"], r.get("transaction")))
    if expired:
        rows.append(("Pull after the mandate's expiry", "1.00 *USDZ", expired["pull"]["reason"], expired["pull"]["transaction"]))
    if second:
        for r in second["metal"]["refusals"]:
            rows.append(("Pull after the holder revoked the mandate", f"{r['amount_usdz']} *USDZ", r["reason"], r.get("transaction")))
    out += [f"| {a} | {b} | `{c}` | {link(d)} |" for a, b, c, d in rows]
    out += [""]

    if first:
        metal, pay = first["metal"], first["payout"]
        m, pull = metal["mandate"], metal["pull"]
        out += ["## 1. A claim funded by a pull under a mandate and paid in Mexican pesos", "",
                f"Claim `{first['claim_id']}`. The holder approved {pay['approval']['amount']} {pay['approval']['currency']} "
                "and chose Metal, so the approval signed a mandate.", "",
                f"- Mandate `{m['mandate_id']}`, bound on the holder's account in {link(m['bind_transaction'])}.", "",
                "### The approval's terms beside the mandate's, as the chain holds them", "",
                "| Term | The approval | The mandate | Same |", "| --- | --- | --- | --- |"]
        out += [f"| {t['term']} | {clean(t['approval'])} | {clean(t['mandate'])} | {'yes' if t['same'] else 'NO'} |" for t in m["terms"]]
        out += ["", "### The pull", "",
                f"- The agent pulled {pull['amount_usdz']} *USDZ under payment id `{pull['payment_id']}` (the claim "
                f"number). It stands for {pull['approved_usd']} USD of the claim at the scale above "
                f"({pull['stands_for_usd']} USD when the cent on chain is counted whole).",
                f"- Transaction: {link(pull['transaction'])}.",
                f"- Read back from the chain (`metal-agent status`): status {pull['settlement']['status']}, block "
                f"{pull['settlement']['block']}, submitted by `{pull['settlement']['submitter']}` ("
                + ("Khutlisa's agent address, which submitted the pull itself and paid the gas, so that a refusal "
                   "would have been recorded on chain too" if pull['settlement']['submitter'].lower() == run['agent'].lower()
                   else "Metal's facilitator, which paid the gas") + "); "
                + "; ".join(f"transfer of {t['amount_usdz']} *USDZ from `{t['from']}` to `{t['to']}`" for t in pull["settlement"]["transfers"]) + ".",
                f"- Metal's own verification of that transaction against the mandate (`{pull['verification']['command']}`): "
                f"verified {'yes' if pull['verification']['verified'] else 'NO'}."]
        out += [f"  - step {s['step']} {s['result']}: {clean(s['title'])}" for s in pull["verification"]["steps"]]
        out += ["", "### The bridge to Airwallex, and the payout", "",
                "The Airwallex sandbox cannot receive *USDZ. Once the pull had settled and been verified, the "
                "application looked the transaction hash up among Airwallex's deposits (`GET /api/v1/deposits`), "
                "found none, and made one simulated deposit of the approved dollars with the hash as its reference.", "",
                f"- Deposit `{pay['deposit']['id']}`: {pay['deposit']['amount']} USD, reference `{pay['deposit']['reference']}`.",
                f"- Incoming fee booked by Airwallex: {pay['incoming_fee']['amount']} USD.",
                f"- Route: {pay['route_name']}. Rate: {pay['rate']} ({pay['rate_pair']}).",
                f"- Transfer `{pay['transfer_id']}`: {pay['transfer_status']}. Received: {pay['received']['amount']} "
                f"{pay['received']['currency']}, to {pay['account']['name']}, account {pay['account']['number']} "
                f"({pay['account']['country']}).",
                f"- Final state: {pay['state']}. {pay['reconciliation']['statement']}", "",
                "| Time (UTC) | State | Note |", "| --- | --- | --- |"]
        out += [f"| {e['at']} | {e['state']} | {clean(e['note'])} |" for e in pay["steps"]]
        out += ["", "Airwallex's ledger rows for this claim (`GET /financial_transactions`):", "",
                "| For | Type | Amount | Currency | Status | Airwallex's note | Entry id |", "| --- | --- | --- | --- | --- | --- | --- |"]
        out += [f"| {r['part']} | {r['type']} | {r['amount']} | {r['currency']} | {r['status']} | {clean(r['description'])} | {r['id']} |"
                for r in pay["reconciliation"]["lines"]]
        out += ["", "| Currency | Came in | Went out | Left |", "| --- | --- | --- | --- |"]
        out += [f"| {s['currency']} | {s['came_in']} | {s['went_out']} | {s['left']} |" for s in pay["reconciliation"]["sums"]]
        out += ["", "What the agent decided without asking:", ""]
        out += [f"- {d['at']}: {d['title']} ({d['rule_name']}). {clean(d['text'])}" for d in pay["agent_report"]]
        out += ["", "### The attempts to overstep, and the double pull", "",
                "Before the pull the agent was told to overstep the mandate twice; after it, to pull a second time. "
                "Each attempt was signed with the mandate key and sent."]
        out += [f"- {r['at']}: {r['case']}: {r['amount_usdz']} *USDZ to `{r['payee']}`. Refused: `{r['reason']}` "
                f"({r['words']}). {link(r.get('transaction'))}" for r in metal["refusals"]]
        again = next((s for s in run["steps"] if s["text"].startswith("The same pull under the same payment id")), None)
        if again:
            out += [f"- {again['at']}: {again['text']}"]
        whole = m.get("verification")
        if whole:
            out += ["", f"`metal-agent mandate verify` over the whole mandate afterwards: verified "
                        f"{'yes' if whole['verified'] else 'NO'}. What it listed from the chain:", ""]
            out += [f"- {l['kind']}{' (' + l['reason'] + ')' if l['reason'] else ''}: {l['amount_usdz']} *USDZ to "
                    f"`{l['to']}`, block {l['block']}, {link(l['transaction'])}" for l in whole["lines"]]
            chain = m.get("chain") or {}
            out += ["", f"The mandate on chain after all of it: spent {chain.get('spent_usdz')} of "
                        f"{chain.get('budget_usdz')} *USDZ, {chain.get('payments')} payment."]
        out += [""]

    if second:
        metal, pay = second["metal"], second["payout"]
        out += ["## 2. A mandate revoked before the pull", "",
                f"Claim `{second['claim_id']}`, 120.00 USD to the Philippines. Under the holder's fee rule it sends "
                "125.38 USD, so the mandate's cap was 1.26 *USDZ.", ""]
        out += [f"- {s['at']}: {s['text']}" for s in run["steps"]
                if any(k in s["text"] for k in ("revoked", "approved again", "Metal refused the pull"))
                or ("signed mandate" in s["text"] and "cap 1.26" in s["text"])]
        out += ["", "The mandates on this claim, oldest first:", ""]
        for mm in sorted(metal["earlier_mandates"] + [metal["mandate"]], key=lambda x: x["seq"]):
            out += [f"- Mandate {mm['seq']} `{mm['mandate_id']}`: {mm['status']}. Bound in {link(mm['bind_transaction'])}"
                    + (f", revoked in {link(mm['revoke_transaction'])}" if mm.get("revoke_transaction") else "")
                    + (f" (on chain: revoked {'yes' if (mm.get('chain') or {}).get('revoked') else 'no'}, spent "
                       f"{(mm.get('chain') or {}).get('spent_usdz')} *USDZ)" if mm.get("chain") else "") + "."]
        out += ["", f"Payout state at the end: {pay['state']}; claim state: {pay['claim_state']}. No deposit was made "
                    "at Airwallex for this claim and nothing left the holder's Metal account.", ""]

    if expired:
        out += ["## 3. A pull after the expiry", "",
                "A claim's mandate expires at the holder's deadline, 14 days after the approval in this run, so the "
                "expiry cannot be waited for on a claim. A mandate with the same shape and a deadline one minute "
                "away was signed on the same account instead.", "",
                f"- Mandate `{expired['mandate_id']}`: cap and budget 1.00 *USDZ, one payment, payee the settlement "
                f"address, expiry {mt._iso(expired['expiry'])}. Bound in {link(expired['bind']['transaction'])}."]
        out += [f"- {s['at']}: {s['text']}" for s in run["steps"] if "after the expiry" in s["text"] or "over that mandate" in s["text"]]
        out += [""]

    screens = OUT / "browser.json"
    if screens.exists():
        seen = json.loads(screens.read_text())
        pay, metal = seen["payout"], seen["metal"]
        out += ["## 4. The same through the holder's screen, paid in Philippine pesos", "",
                "Written from the record of a browser run that drove the holder's view against a running server: the "
                "approval, the attempts to overstep and the verification were clicks on the screen. The owner's steps "
                "went through the routes the owner's screens use. The same steps are now part 3 of "
                "`scripts/walkthrough.mjs`, whose screens are in `docs/shots/walk/`.", "",
                f"Claim `{seen['claim_id']}`: {pay['approval']['amount']} {pay['approval']['currency']} to "
                f"{pay['account']['name']}, account {pay['account']['number']} ({pay['account']['country']}).", ""]
        out += [f"- {s['at']}: {clean(s['text'])}" for s in seen["steps"]]
        out += ["", "| What | Transaction or id |", "| --- | --- |",
                f"| Mandate bound | {link(metal['mandate']['bind_transaction'])} |",
                f"| Pull of {metal['pull']['amount_usdz']} *USDZ, standing for {metal['pull']['approved_usd']} USD | {link(metal['pull']['transaction'])} |"]
        out += [f"| Refused: `{r['reason']}` ({r['case'].lower()}) | {link(r.get('transaction'))} |" for r in metal["refusals"]]
        out += [f"| Airwallex deposit, reference the pull's hash | `{pay['deposit']['id']}` |",
                f"| Airwallex transfer, {pay['transfer_status']}: {pay['received']['amount']} {pay['received']['currency']} | `{pay['transfer_id']}` |",
                "", pay["reconciliation"]["statement"], ""]

    setup = OUT / "setup.json"
    if setup.exists():
        held = json.loads(setup.read_text())
        out += ["## Setting up, the same day", "",
                "Done once, by hand and then by `scripts/metal_setup.py`. Three faucet grants were used.", ""]
        out += [f"- {s['what']}: {link(s['transaction'])}" for s in held["steps"]]
        out += [""]

    out += ["## The run, line by line", "", "| Time (UTC) | What happened |", "| --- | --- |"]
    out += [f"| {s['at']} | {clean(s['text'])} |" for s in run["steps"]]
    out += [""]
    target = ROOT / "docs" / "METAL_RUN_LOG.md"
    text = "\n".join(out)
    assert "rpc-testnet.metalntwx.com/v1/" not in text.replace("/v1/<endpoint id>", "") and "privateKey" not in text
    target.write_text(text)
    print(f"wrote {target}: {len(out)} lines")


if __name__ == "__main__":
    main()
