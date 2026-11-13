"""The holder's standing instructions.

A holder (the company that reported a property and pays the claim) sets these once. Each approval carries a copy
of them, so a payment follows the instructions that stood when it was approved. Inside them the payment machine
acts alone and writes down what it did and why. Outside them it stops and asks the right party. With no
instructions on file nothing is waved through and every change is put to a person.

Everything here is arithmetic and comparison. No language model is involved.

  tolerance_percent   how far below the planned local amount the claimant may fall before they are asked again
  small_claim_usd     below this claim amount the holder bears Airwallex's fees; from it upward the claim does
  route_rule          "most_to_claimant": compare the routes Airwallex offers and take the one that delivers most;
                      "fixed": the route that the currency dictates, with no comparison
  deadline_days       days from the approval within which the money must be sent; after that the machine stops
                      and goes back to the holder
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation
from typing import Any

# What Airwallex has charged on every sandbox run so far (docs/AIRWALLEX_FLOW.md). Used to plan; the booked
# figures replace them as soon as Airwallex has booked them.
EXPECTED_INCOMING_FEE_RATE = Decimal("0.003")
EXPECTED_PAYOUT_FEE_USD = Decimal("5.00")

ROUTE_RULES = ("most_to_claimant", "fixed")
DEFAULTS = {"tolerance_percent": "0.5", "small_claim_usd": "250.00", "route_rule": "most_to_claimant",
            "deadline_days": 14}
CENT = Decimal("0.01")


def _decimal(value: Any, name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise ValueError(f"{name} must be a number") from None
    if not number.is_finite():
        raise ValueError(f"{name} must be a number")
    return number


def clean(raw: dict) -> dict:
    """The instructions in their stored form. Raises ValueError, in words for the screen, when a value is missing
    or outside what makes sense."""
    raw = {**DEFAULTS, **(raw or {})}
    tolerance = _decimal(raw["tolerance_percent"], "The tolerance")
    if not Decimal(0) <= tolerance <= Decimal(5):
        raise ValueError("The tolerance must be between 0 and 5 percent")
    small = _decimal(raw["small_claim_usd"], "The small-claim line")
    if not Decimal(0) <= small <= Decimal(10000):
        raise ValueError("The small-claim line must be between 0 and 10,000 US dollars")
    try:
        days = int(raw["deadline_days"])
    except (TypeError, ValueError):
        raise ValueError("The deadline must be a whole number of days") from None
    if not 1 <= days <= 365:
        raise ValueError("The deadline must be between 1 and 365 days")
    if raw["route_rule"] not in ROUTE_RULES:
        raise ValueError("Choose one of the route rules")
    return {"tolerance_percent": str(tolerance.normalize()) if tolerance else "0",
            "small_claim_usd": str(small.quantize(CENT)), "route_rule": raw["route_rule"], "deadline_days": days}


def within_tolerance(planned: Any, now: Any, rules: dict | None) -> tuple[bool, Decimal]:
    """(inside the tolerance, the shortfall in percent of the planned amount). More than planned is always
    inside. With no instructions nothing is inside unless the amount is at least what was planned."""
    planned, now = Decimal(str(planned)), Decimal(str(now))
    if planned <= 0:
        return False, Decimal(0)
    short = ((planned - now) / planned * 100).quantize(CENT, ROUND_HALF_UP)
    if now >= planned:
        return True, min(short, Decimal(0))
    if not rules:
        return False, short
    return short <= Decimal(rules["tolerance_percent"]), short


def fee_plan(claim_usd: Any, rules: dict | None) -> dict:
    """Who bears Airwallex's two fees on this claim, what the holder sends, and the arithmetic in sentences.

    Below the small-claim line the holder sends the claim plus the expected fees, so the whole claim is left to
    convert for the claimant. From the line upward the holder sends the claim and the fees come out of it."""
    claim = Decimal(str(claim_usd)).quantize(CENT)
    rate, payout = EXPECTED_INCOMING_FEE_RATE, EXPECTED_PAYOUT_FEE_USD
    percent = f"{rate * 100:f}".rstrip("0").rstrip(".")
    plain_in = (claim * rate).quantize(CENT, ROUND_HALF_UP)
    plain_fees = plain_in + payout
    share = (plain_fees / claim * 100).quantize(Decimal("0.1"), ROUND_HALF_UP) if claim > 0 else Decimal(0)
    threshold = Decimal(rules["small_claim_usd"]) if rules else None
    if threshold is not None and claim < threshold:
        sends = ((claim + payout) / (1 - rate)).quantize(CENT, ROUND_UP)
        fee_in = (sends * rate).quantize(CENT, ROUND_HALF_UP)
        left = sends - fee_in - payout
        arithmetic = [
            f"The claim is {claim:,.2f} USD, which is below your small-claim line of {threshold:,.2f} USD, so you "
            "bear Airwallex's fees.",
            f"Airwallex is expected to take {percent} percent of what arrives and about {payout:,.2f} USD for the "
            f"payout. Taken out of the claim that would be {plain_fees:,.2f} USD, or {share} percent of it.",
            f"So you send ({claim:,.2f} + {payout:,.2f}) / (1 - {rate}) = {sends:,.2f} USD: {fee_in:,.2f} USD "
            f"incoming fee, {payout:,.2f} USD payout fee, and {left:,.2f} USD left to convert for the claimant.",
        ]
        bearer = "holder"
    else:
        sends, fee_in = claim, plain_in
        left = max(claim - fee_in - payout, Decimal(0))
        if threshold is None:
            first = f"No standing instructions are on file, so Airwallex's fees come out of the claim of {claim:,.2f} USD."
        else:
            first = (f"The claim is {claim:,.2f} USD, which is not below your small-claim line of {threshold:,.2f} "
                     "USD, so Airwallex's fees come out of the claim.")
        arithmetic = [
            first,
            f"Airwallex is expected to take {percent} percent of what arrives ({fee_in:,.2f} USD) and about "
            f"{payout:,.2f} USD for the payout: {plain_fees:,.2f} USD in all, or {share} percent of the claim. "
            f"That leaves {left:,.2f} USD to convert for the claimant.",
        ]
        bearer = "claim"
    return {"bearer": bearer, "threshold": None if threshold is None else str(threshold), "claim": str(claim),
            "holder_sends": str(sends), "holder_adds": str(sends - claim), "expected_incoming_fee": str(fee_in),
            "expected_payout_fee_usd": str(payout), "left_for_claimant_usd": str(left),
            "without_rule": {"fees": str(plain_fees), "share_percent": str(share)}, "arithmetic": arithmetic}


def deadline_at(approved_at: str, rules: dict | None) -> str | None:
    """The moment after which the machine sends nothing more without going back to the holder."""
    if not rules:
        return None
    return (datetime.fromisoformat(approved_at) + timedelta(days=int(rules["deadline_days"]))).isoformat(timespec="seconds")


def in_words(rules: dict | None) -> list[str]:
    """The instructions as sentences, for the screens and the plan."""
    if not rules:
        return ["No standing instructions are on file. Every change of circumstance stops the payment and is put "
                "to a person."]
    route = ("Compare the routes Airwallex offers for the currency, with its own quotes and the fees it has "
             "charged, and take the one that delivers the most to the claimant."
             if rules["route_rule"] == "most_to_claimant" else
             "Use the route the currency dictates, without comparing.")
    days = int(rules["deadline_days"])
    return [
        f"Amount: carry on without asking while the claimant would receive no less than {rules['tolerance_percent']} "
        "percent below the planned amount in their currency. Ask the claimant if it would be worse.",
        f"Fees: below a claim of {Decimal(rules['small_claim_usd']):,.2f} USD the holder bears Airwallex's fees, so "
        "a small claim is not eaten by them. From that amount upward the fees come out of the claim.",
        "Route: " + route,
        f"Deadline: send the money within {days} {'day' if days == 1 else 'days'} of the approval. After that, "
        "stop and come back to the holder.",
        "Never inside these instructions: a different bank account, an amount larger than the one approved, or a "
        "second payment of the same claim. Those always come back to a person.",
    ]
