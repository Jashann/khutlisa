"""Runs one whole payout on the Airwallex sandbox. Usage: uv run python scripts/first_payout.py PHP|MXN [usd]"""
import sys
import time

from khutlisa.airwallex import (EXAMPLE_BENEFICIARIES, AirwallexClient, AirwallexError, Payout, SandboxSimulator,
                                advance, load_credentials)

cur = sys.argv[1] if len(sys.argv) > 1 else "MXN"
usd = sys.argv[2] if len(sys.argv) > 2 else "742.18"
client = AirwallexClient(*load_credentials())
sim = SandboxSimulator(client)
p = Payout(path=f"data/payout_{cur}_{int(time.time())}.json", usd_amount=usd, target_currency=cur,
           deposit_reference=f"KHUTLISA-{int(time.time())}", beneficiary=EXAMPLE_BENEFICIARIES[cur])
p.save()
stuck = 0
for step in range(40):
    before = p.state
    try:
        p = advance(p, client, sim)
    except AirwallexError as e:
        print(f"step {step}: {before} -> ERROR {e.status} {e.code}: {str(e.message)[:300]}")
        d = getattr(e, "details", None)
        if d:
            print("   details:", str(d)[:600])
        break
    print(f"step {step}: {before} -> {p.state}")
    if p.state in ("PAID", "FAILED"):
        break
    stuck = stuck + 1 if p.state == before else 0
    if stuck >= 8:
        break
    if p.state == before:
        time.sleep(2)
print("final:", p.state, "| target", p.target_amount, cur, "| rate", p.client_rate, "| transfer", p.transfer_status, "| failure", p.failure)
if p.proof:
    print("proof keys:", list(p.proof)[:8])
print("saved to", p.path)
