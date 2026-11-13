"""Money from the start: indicative amounts for the match cards, and the payout plan in summary on the claim
screen before the proof is complete. `register` adds both routes to the app built in server.py.

Neither route locks a rate or moves money. Both are labelled: the amounts as indicative, the summary as a plan.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from . import claims as cl
from . import holders
from . import indicative as ind
from . import instructions as ins


def register(app: FastAPI, claim_store: cl.ClaimStore, source: ind.Indicative, proof_ready=None) -> None:

    def rules() -> dict | None:
        return (claim_store.instructions() or {}).get("rules")

    @app.get("/api/holders")
    def for_holders() -> dict:
        """The holders with the most properties and dollars for owners abroad, computed from California's file by
        scripts/make_holders.py, with the law in short and a plain statement that no holder uses this yet."""
        out = holders.served()
        if out is None:
            raise HTTPException(503, "The holder figures have not been made yet. Run scripts/make_holders.py "
                                     "(see the README).")
        return out

    @app.get("/api/indicative")
    def indicative(country: str = Query(..., max_length=80),
                   amount: list[str] = Query(default_factory=list, max_length=30)) -> dict:
        """What each US dollar amount would become in the currency of `country` today, at Airwallex's indicative
        rate, after the fees the payout plan expects. Nothing is locked."""
        try:
            amounts = ind.clean_amounts(amount)
        except ValueError as err:
            raise HTTPException(422, str(err)[:1].upper() + str(err)[1:] + ".") from None
        return source.amounts(country, amounts, rules())

    @app.get("/api/claims/{claim_id}/payout/preview")
    def preview(claim_id: str) -> dict:
        """The payout plan in summary, for a claim that is not approved yet. It is a plan: nothing has moved,
        no rate is locked, and the route is chosen only when the real plan is written after the approval."""
        try:
            claim = claim_store.load(claim_id)
        except cl.ClaimError as err:
            raise HTTPException(err.status, err.message) from None
        payee = claim.get("payee")
        country = (payee["beneficiary"]["beneficiary"]["bank_details"].get("bank_country_code") if payee
                   else claim["claimant"].get("country"))
        bound = ((claim.get("approval") or {}).get("terms") or {}).get("instructions")
        in_force = bound if claim.get("approval") else rules()
        amount = f"{float(claim['record'].get('amount') or 0):.2f}"
        if float(amount) <= 0:
            return {"available": False, "is_plan": True, "reason": "This record carries no amount."}
        got = source.amounts(country, [amount], in_force)
        ready = bool(proof_ready(claim)) if proof_ready is not None else claim["state"] not in (cl.FOUND, cl.PROOF_NEEDED)
        steps = [{"what": "The proof file is ready", "done": ready},
                 {"what": "You have given the bank account to be paid into", "done": bool(payee)},
                 {"what": "The holder has approved the claim on these exact terms", "done": bool(claim.get("approval"))}]
        base = {"is_plan": True, "before_it_can_start": steps,
                "label": "A plan, not a payment. Nothing has moved and no rate is locked. The real plan is "
                         "written, with a locked rate, once the holder has approved.",
                "claim": {"amount": amount, "currency": claim["record"].get("currency") or "USD"},
                "currency_from": "the bank account you gave" if payee else "the country you gave"}
        if not got["available"]:
            return {**base, "available": False, "reason": got["reason"]}
        row = got["amounts"][0]
        fees = ins.fee_plan(amount, in_force)
        return {**base, "available": True, "currency": got["currency"], "rate": got["rate"], "pair": got["pair"],
                "rate_label": got["label"], "age_seconds": got["age_seconds"],
                "holder_sends": row["holder_sends"], "fees": row["fees"], "fee_rule": fees,
                "would_receive": row["would_receive"],
                "route": "Chosen when the real plan is written: the route that delivers the most to you, by "
                         "Airwallex's own quote and fees." if in_force and in_force.get("route_rule") == "most_to_claimant"
                         else "The route the currency dictates.",
                "state_fallback": "If the holder does not pay, the claim to the State of California stays open "
                                  "to you. The State pays by posted cheque in US dollars."}
