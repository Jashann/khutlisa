"""Decision cards: each thing the agent decides, as four short lines for the screen.

  happened   what happened
  allowed    what the holder's limits allowed
  did        what the agent did
  money      the result in money

`why` carries the longer explanation, which the screen folds away. Every line is built in code from figures the
payout file already holds (the plan, the decisions, the attempts). No language model is involved.
"""
from __future__ import annotations

from decimal import Decimal

MATERIAL_PERCENT = Decimal("0.1")     # a difference between two routes is shown from this share of the amount

ROUTE_WORDS = {"pay_with_quote": "pay with a locked quote", "convert_then_pay": "convert first, then pay",
               "pay_from_balance": "pay from the balance already held"}


def _money(amount, currency: str = "USD") -> str:
    value = Decimal(str(amount))
    return f"${value:,.2f}" if currency == "USD" else f"{value:,.2f} {currency}"


def _amount(a: dict | None) -> str:
    return _money(a["amount"], a["currency"]) if a and a.get("amount") not in (None, "") else "an unknown amount"


def _percent(text) -> str:
    return f"{Decimal(str(text)).normalize():f}"


def fee_card(fee_rule: dict | None, at: str | None = None) -> dict | None:
    """The fee rule on one claim."""
    if not fee_rule or fee_rule.get("threshold") is None:
        return None
    claim, line = _money(fee_rule["claim"]), _money(fee_rule["threshold"])
    fees, share = _money(fee_rule["without_rule"]["fees"]), fee_rule["without_rule"]["share_percent"]
    if fee_rule["bearer"] == "holder":
        return {"kind": "fee_rule", "tone": "go", "title": "The fee rule", "at": at,
                "happened": f"A claim of {claim}. Fees would take {fees}, {share}% of it.",
                "allowed": f"Below {line} the holder bears the fees.",
                "did": f"The holder sends {_money(fee_rule['holder_sends'])}.",
                "money": f"The owner gets the whole {claim}.",
                "why": list(fee_rule["arithmetic"])}
    return {"kind": "fee_rule", "tone": "go", "title": "The fee rule", "at": at,
            "happened": f"A claim of {claim}. Fees are about {fees}, {share}% of it.",
            "allowed": f"From {line} up, fees come out of the claim.",
            "did": f"The holder sends {_money(fee_rule['holder_sends'])}.",
            "money": f"{_money(fee_rule['left_for_claimant_usd'])} is left to convert for the owner.",
            "why": list(fee_rule["arithmetic"])}


def route_card(plan: dict | None, at: str | None = None) -> dict | None:
    """The choice of route in a plan that compared routes."""
    compared = (plan or {}).get("routes_compared")
    if not compared:
        return None
    chosen = next((r for r in compared if r["chosen"]), None)
    if chosen is None:
        return None
    currency = chosen["would_receive"]["currency"]
    others = [r for r in compared if not r["chosen"] and r["available"]]
    if others:
        best = Decimal(chosen["would_receive"]["amount"])
        more = best - Decimal(others[0]["would_receive"]["amount"])
        happened = f"Two routes to {currency}, priced with Airwallex's own quote and fees."
        # The difference between the routes is given only when it matters: at least MATERIAL_PERCENT of the
        # amount. A few cents on thousands is not a decision worth a figure.
        material = best > 0 and more / best * 100 >= MATERIAL_PERCENT
        money = (f"{_amount(chosen['would_receive'])}: {more:,.2f} {currency} more than the other route." if material
                 else f"{_amount(chosen['would_receive'])} expected. The other route would bring about the same.")
    else:
        happened = f"One route is open for {currency}."
        money = f"{_amount(chosen['would_receive'])} expected."
    return {"kind": "route_chosen", "tone": "go", "title": "The route", "at": at,
            "happened": happened, "allowed": "Take the route that delivers the most to the owner.",
            "did": f"Chose: {ROUTE_WORDS.get(chosen['route'], chosen['route'])}.", "money": money,
            "why": [plan.get("route_reason") or ""]}


def refusal_card(attempt: dict, payout: dict) -> dict:
    """A transfer the receiving bank refused or returned, and what the limits made of the replacement."""
    rules = payout.get("instructions") or {}
    hold = payout.get("hold") or {}
    outcome = attempt.get("outcome") or {}
    back = _amount(attempt.get("came_back"))
    to = f" to account ending {attempt['account_last4']}" if attempt.get("account_last4") else ""
    returned = "returned" in (attempt.get("fate") or "")
    happened = (f"The bank returned the transfer{to}. {back} came back." if returned else
                f"The bank refused the transfer{to}. {back} came back.")
    limit = rules.get("tolerance_percent")
    allowed = (f"Up to {_percent(limit)}% less than agreed, without asking the owner to confirm the amount." if limit is not None else
               "No limits are on file, so every change is put to a person.")
    currency = (attempt.get("came_back") or {}).get("currency") or payout.get("target_currency")
    why = [f"Airwallex reported: {attempt.get('reason')}."]
    if attempt.get("fee_kept"):
        why.append(f"Airwallex kept its payout fee of {_amount(attempt['fee_kept'])} for the refused transfer and "
                   "charges it again on the replacement. That is the whole difference.")
    why.append("A corrected account always comes from the owner and is approved by the holder. One replacement is "
               "sent, and only once Airwallex reports the first transfer as failed or cancelled.")
    why.append("The fee rule decides what the holder sends when it approves. The second payout fee after a refusal "
               "is not part of that approval, and a larger amount is never inside the limits, so it comes out of "
               "the replacement and the tolerance decides whether the owner is asked about it.")
    if not outcome:
        return {"kind": "refusal", "tone": "ask", "title": "The refused transfer", "at": attempt.get("at"),
                "happened": happened, "allowed": allowed, "did": "Working out the replacement.",
                "money": f"{back} is held for this claim.", "why": why, "asked": None}
    short, asked = outcome["shortfall_percent"], outcome["claimant_asked"]
    agreed = _money(outcome["agreed_local"], currency)
    now = _money(outcome["replacement_local"], currency)
    paid = payout.get("state") == "PAID" and payout.get("target_amount")
    waiting = "claimant" in hold.get("needs", [])
    if asked:
        did = f"The replacement is {short}% less. Outside the limit: it stopped and asked the owner."
        money = (f"Paid {_money(payout['target_amount'], currency)} after the owner agreed, in place of {agreed}." if paid
                 else f"{now} in place of {agreed}" + (", waiting for the owner's answer." if waiting else "."))
    else:
        # What was skipped is one confirmation of the amount. The account and the holder's approval were still asked.
        did = (f"{short}% less, inside the limit: did not ask the owner to confirm the amount. Still asked: the "
               "corrected account and the holder's approval.")
        money = (f"Paid {_money(payout['target_amount'], currency)}, in place of {agreed}." if paid
                 else f"{now} in place of {agreed}.")
    return {"kind": "refusal", "tone": "stop" if asked else "go", "title": "The refused transfer",
            "at": attempt.get("at"), "happened": happened, "allowed": allowed, "did": did, "money": money,
            "why": why, "asked": bool(asked), "shortfall_percent": short,
            "tolerance_percent": limit, "paid": bool(paid), "waiting_for_owner": waiting}


def payout_cards(payout: dict | None, plan: dict | None = None) -> list[dict]:
    """The cards for one payout, in the order things happened: the fee rule, the route, each refused transfer."""
    if not payout:
        return []
    first = payout.get("plan") or plan or {}
    when = {d.get("kind"): d.get("at") for d in payout.get("decisions") or []}
    cards = [fee_card(first.get("fee_rule") or (plan or {}).get("fee_rule"), when.get("fee_rule")),
             route_card(first if first.get("routes_compared") else plan, when.get("route_chosen"))]
    cards += [refusal_card(a, payout) for a in payout.get("attempts") or []]
    return [c for c in cards if c]
