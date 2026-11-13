"""One real run of the Metal funding: Metal testnet for the holder's money, the Airwallex sandbox for the payout.

    uv run python scripts/metal_run.py            all three parts
    uv run python scripts/metal_run.py 2 3        only the parts named, added to the run already on file

It starts the application in this process, with the real Metal command line (keys under ~/.khutlisa_metal, set up
by scripts/metal_setup.py) and the real Airwallex sandbox (keys in ~/.airwallex_sandbox), and plays every part
through the application's own routes: the owner, the holder and the agent. Only the demonstration records are
searched, so no real person is involved; document reading is off, so no language model is called.

  1. An owner in Mexico claims 2,316.40 US dollars. The holder approves and funds the claim on Metal: a mandate is
     signed and bound. The agent is told to overstep it twice (over the cap, another payee) and Metal refuses.
     The agent then pulls under the mandate, the settlement is read from the chain, the Airwallex deposit carries
     the transaction hash, and the owner is paid in Mexican pesos. A second pull is tried and refused.
  2. An owner in the Philippines claims 120.00 US dollars. The holder approves on Metal, then revokes the mandate
     before the payment starts: the claim goes back to the holder. The holder approves again and revokes on
     chain while the payment is starting: Metal refuses the agent's pull and the claim goes back again.
  3. A mandate signed with a deadline one minute away is pulled after the minute: Metal refuses it as expired.

What happened is written to data/metal_run/run.json. scripts/metal_log.py turns that into docs/METAL_RUN_LOG.md.
"""
from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from khutlisa import demo, metal as mt  # noqa: E402
from khutlisa.server import create_app  # noqa: E402

OUT = ROOT / "data" / "metal_run"
KEY = "metal-run"
PAYER = {"X-Payer-Key": KEY}
RULES = {"tolerance_percent": "0.5", "small_claim_usd": "250", "route_rule": "most_to_claimant", "deadline_days": 14}
run: dict = {"started_at": mt.now(), "steps": []}


def step(text: str, **facts) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {mt.redact(text)}", flush=True)
    run["steps"].append({"at": mt.now(), "text": mt.redact(text), **facts})
    (OUT / "run.json").write_text(json.dumps(run, indent=2))


def keep() -> None:
    (OUT / "run.json").write_text(json.dumps(run, indent=2))


def ok(response):
    if response.status_code >= 400:
        step(f"HTTP {response.status_code}: {response.text[:500]}")
        raise SystemExit(1)
    return response.json()


def open_claim(api, person: dict) -> str:
    names = person["name"].split()
    main = next(r for r in demo.records() if r["record_id"] == person["main_record"])
    history = {"given_names": names[:1], "family_names": names[1:],
               "places": [{"city": main["owner_city"], "region": main["owner_region"],
                           "postcode": main["owner_postcode"], "country": "US", "street": ""}],
               "employers": [main["holder_name"]], "current_country": person["claimant"]["country"]}
    found = ok(api.post("/api/search", json=history))
    match = next(m for m in found["matches"] if abs(float(m["amount"]) - float(main["amount"])) < 0.005
                 and m.get("holder_name") == main["holder_name"])
    claim = ok(api.post("/api/claims", json={"record_id": match["record_id"], "claimant": person["claimant"],
                                             "history": history}))
    ok(api.put(f"/api/claims/{claim['id']}/payee", json=person["bank"]))
    step(f"{person['short_name']} opened claim {claim['id']} on a demonstration record of "
         f"{main['amount']:,.2f} USD held by {main['holder_name']}, and gave a bank account in "
         f"{person['bank']['currency']}.", claim_id=claim["id"])
    return claim["id"]


def wait_for(api, claim_id: str, until, seconds: int = 240) -> dict:
    ends = time.time() + seconds
    view = {}
    while time.time() < ends:
        view = ok(api.get(f"/api/claims/{claim_id}/payout"))
        if until(view):
            return view
        if view.get("problem") and not view.get("running"):
            step(f"the payment reports: {view['problem']}; carrying on from the same step")
            ok(api.post(f"/api/claims/{claim_id}/payout/resume"))
        time.sleep(2)
    step(f"timed out waiting; state {view.get('state')}")
    return view


def panel(api, claim_id: str) -> dict:
    return ok(api.get(f"/api/payer/claims/{claim_id}/metal", headers=PAYER))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parts = {int(a) for a in sys.argv[1:]} or {1, 2, 3}
    if parts != {1, 2, 3} and (OUT / "run.json").exists():
        run.update(json.loads((OUT / "run.json").read_text()))
    people = {p["key"]: p for p in demo.people()}
    app = create_app(db_path=OUT / "no-register.duckdb", claims_dir=OUT / f"claims-{int(time.time())}",
                     demonstration=True, read_documents=False, payer_key=KEY, payout_pause=1.0,
                     search_per_minute=0, search_per_hour=0)
    with TestClient(app) as api:
        status = ok(api.get("/api/metal"))
        if not status["available"]:
            step(f"Metal is not set up: {status['problem']}")
            raise SystemExit(1)
        funding = app.state.metal
        chain = funding.chain
        claims_folder = str(funding.store.folder.relative_to(ROOT))
        run.update({"network": status["network"], "chain": status["chain"], "scale": status["scale"],
                    "accounts": status["accounts"], "agent": chain.config.agent_address,
                    "cli": chain.version()})
        step(f"Metal: {status['network']} ({status['chain']}), metal-agent {run['cli']}. {status['scale']['words']}")
        step(f"The holder's Metal account {funding.holder_account} holds {chain.balance(funding.holder_account)} *USDZ. "
             f"Khutlisa's settlement address {funding.settlement} holds {chain.balance(funding.settlement)} *USDZ.")
        ok(api.put("/api/payer/instructions", json=RULES, headers=PAYER))

        if 1 in parts:
            # ---- 1. funded on Metal, paid in Mexican pesos ------------------------------------------------------
            first = open_claim(api, people["marisol"])
            row = ok(api.post(f"/api/payer/claims/{first}/approve", json={"funding": "metal"}, headers=PAYER))
            seen = panel(api, first)
            m = seen["mandate"]
            step(f"The holder approved {row['approval']['amount']} USD and signed mandate {m['mandate_id']}, bound in "
                 f"{m['bind_transaction']}. Every term matches the approval: {m['all_same']}.",
                 transaction=m["bind_transaction"], terms=m["terms"])
            for case in ("over_cap", "wrong_payee"):
                r = ok(api.post(f"/api/payer/claims/{first}/metal/attempt", json={"case": case}, headers=PAYER))["refusal"]
                step(f"Staged: {r['case']} ({r['amount_usdz']} *USDZ to {r['payee']}). Metal refused: {r['reason']}. "
                     f"Recorded on chain in {r['transaction']}.", transaction=r["transaction"], refusal=r)
            plan = ok(api.post(f"/api/claims/{first}/payout/plan", json={}))["plan"]
            step(f"The plan: {plan['route_name']}; the owner should receive {plan['expected_local']['amount']} "
                 f"{plan['expected_local']['currency']}. The owner agrees.")
            ok(api.post(f"/api/claims/{first}/payout/confirm", json={"plan_id": plan["id"]}))
            done = wait_for(api, first, lambda v: v["state"] in ("PAID", "HELD", "FAILED") and not v.get("running") or v["state"] == "PAID")
            seen = panel(api, first)
            pull = seen["pull"] or {}
            step(f"Pull: {pull.get('amount_usdz')} *USDZ, transaction {pull.get('transaction')}; Metal's verification "
                 f"passed: {(pull.get('verification') or {}).get('verified')}.", transaction=pull.get("transaction"))
            step(f"Airwallex: deposit {done['deposit']['id']} of {done['deposit']['amount']} USD with reference "
                 f"{done['deposit']['reference']}; payout state {done['state']}; transfer {done.get('transfer_id')} "
                 f"{done.get('transfer_status')}; received {(done.get('received') or {}).get('amount')} "
                 f"{(done.get('received') or {}).get('currency')}; ledger balanced: {done['reconciliation']['balanced']}.")
            r = ok(api.post(f"/api/payer/claims/{first}/metal/attempt", json={"case": "second_pull"}, headers=PAYER))["refusal"]
            step(f"Staged: {r['case']}. Metal refused: {r['reason']}. Recorded on chain in {r['transaction']}.",
                 transaction=r["transaction"], refusal=r)
            # The same payment id again: the command line reports the first payment and sends nothing.
            credential = funding.load(first)["mandates"][-1]["credential"]
            same = chain.pull(credential, funding.settlement, pull.get("amount_usdz"), payment_id=first)
            step(f"The same pull under the same payment id again: outcome {same['outcome']}, already paid: "
                 f"{same['already_paid']}, transaction {same['transaction']} (the first one). Nothing was sent.")
            checked = ok(api.post(f"/api/payer/claims/{first}/metal/verify", headers=PAYER))["mandate"]["verification"]
            step(f"metal-agent mandate verify over the whole mandate: verified {checked['verified']}; "
                 + "; ".join(f"{l['kind']}{' ' + l['reason'] if l['reason'] else ''} {l['amount_usdz']} *USDZ" for l in checked["lines"]),
                 verification=checked)
            step(f"After the run the holder's account holds {chain.balance(funding.holder_account)} *USDZ and the "
                 f"settlement address {chain.balance(funding.settlement)} *USDZ.")
            run["first"] = {"claims_folder": claims_folder, "claim_id": first, "payout": done, "metal": panel(api, first)}
            keep()

        if 2 in parts:
            # ---- 2. revoked before the pull ---------------------------------------------------------------------
            second = open_claim(api, people["amihan"])
            row = ok(api.post(f"/api/payer/claims/{second}/approve", json={"funding": "metal"}, headers=PAYER))
            m = panel(api, second)["mandate"]
            step(f"The holder approved and signed mandate {m['mandate_id']} (cap {m['terms'][1]['mandate']}), bound in "
                 f"{m['bind_transaction']}.", transaction=m["bind_transaction"])
            after = ok(api.post(f"/api/payer/claims/{second}/metal/revoke", headers=PAYER))
            row = next(c for c in ok(api.get("/api/payer/queue", headers=PAYER))["claims"] if c["id"] == second)
            step(f"The holder revoked it before the payment started, in {after['mandate']['revoke_transaction']}. The "
                 f"claim is {row['state']} again; the approval was withdrawn because "
                 f"{row['approvals_withdrawn'][0]['because']}.", transaction=after["mandate"]["revoke_transaction"])
            ok(api.post(f"/api/payer/claims/{second}/approve", json={"funding": "metal"}, headers=PAYER))
            m = panel(api, second)["mandate"]
            step(f"The holder approved again and signed mandate {m['mandate_id']} (number {m['seq']}), bound in "
                 f"{m['bind_transaction']}.", transaction=m["bind_transaction"])
            plan = ok(api.post(f"/api/claims/{second}/payout/plan", json={}))["plan"]
            gone = chain.revoke(funding.load(second)["mandates"][-1]["credential"])   # from the holder's own wallet
            step(f"The holder revoked that mandate on chain, outside the application, in {gone['transaction']}. The "
                 "owner then agrees to the plan and the agent tries to pull.", transaction=gone["transaction"])
            ok(api.post(f"/api/claims/{second}/payout/confirm", json={"plan_id": plan["id"]}))
            held = wait_for(api, second, lambda v: v["state"] in ("HELD", "PAID", "FAILED") and (v["state"] == "PAID" or (v.get("hold") or {}).get("ready")))
            seen = panel(api, second)
            refusal = (seen["refusals"] or [{}])[-1]
            step(f"Metal refused the pull: {refusal.get('reason')}, recorded on chain in {refusal.get('transaction')}. "
                 f"Payout state {held['state']}, claim state {held['claim_state']}. {(held.get('hold') or {}).get('explanation')} "
                 f"Deposits made at Airwallex for this claim: {'none' if not held['deposit']['arrived'] else 'ONE'}.",
                 transaction=refusal.get("transaction"), refusal=refusal)
            run["second"] = {"claims_folder": claims_folder, "claim_id": second, "payout": held, "metal": seen}
            keep()

        if 3 in parts:
            # ---- 3. expired -------------------------------------------------------------------------------------
            folder = funding.keys_folder / f"expiry-{int(time.time())}"
            issued = chain.create_credential(folder, cap="1.00", budget="1.00", expires_in=60,
                                             description="Khutlisa: a deadline one minute away", max_occurrences=1)
            bound = chain.bind(issued["credential"])
            step(f"A mandate with a deadline one minute away: {issued['mandate_id']}, cap 1.00 *USDZ, expiry "
                 f"{mt._iso(issued['expiry'])}, bound in {bound['transaction']}.", transaction=bound["transaction"])
            time.sleep(max(issued["expiry"] - time.time(), 0) + 8)
            late = chain.pull(issued["credential"], funding.settlement, "1.00", payment_id="after-the-deadline",
                              record_refusal=True)
            step(f"A pull of 1.00 *USDZ at {mt.now()}, after the expiry. Metal's answer: {late['outcome']}, "
                 f"{late['reason']}. Recorded on chain in {late['transaction']}.", transaction=late["transaction"],
                 refusal={"reason": late["reason"], "transaction": late["transaction"], "amount_usdz": "1.00"})
            check = chain.verify(issued["credential"])
            step(f"metal-agent mandate verify over that mandate: verified {check['verified']}; "
                 + "; ".join(f"{l['kind']}{' ' + l['reason'] if l['reason'] else ''} {l['amount_usdz']} *USDZ" for l in check["lines"]))
            run["expired"] = {"mandate_id": issued["mandate_id"], "expiry": issued["expiry"], "bind": bound, "pull": late,
                              "verification": check}
            keep()
        run["finished_at"] = mt.now()
        step(f"Done. The holder's account holds {chain.balance(funding.holder_account)} *USDZ.")


if __name__ == "__main__":
    main()
