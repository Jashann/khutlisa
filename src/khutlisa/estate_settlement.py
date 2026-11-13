"""One settlement for an estate: every proven heir is paid in their own country and currency, from one deposit.

The pieces, and the rule each one keeps:

  allocate        divides cents by exact fractions with largest-remainder rounding, so the parts always add up
                  to the whole, to the cent
  targets         applies the holder's fee rule heir by heir
  make_plan       one quote per heir, the route per currency, what each heir should receive; moves no money
  step            the machine: one deposit (a `airwallex.Payout` used only for its deposit step), then one
                  `airwallex.Payout` per heir, started from the heir's part of what arrived. Each heir's payout
                  has its own request ids, saved before any call, so a restart never pays twice, and an error
                  or a refused transfer on one heir's payout never stops or repeats another's
  reconciliation  every ledger row Airwallex booked for the deposit and for each heir, summed by currency

An heir who is not proven is left out of the deposit: that share stays with the holder until a later round.
An heir who has been paid is never in a later round.

Rates: Airwallex quotes some pairs the other way round (GBPUSD: US dollars per pound). Every amount here is
worked out from the quote's own buy and sell amounts, never by multiplying by a rate whose direction is assumed.
"""
from __future__ import annotations

import json
import os
import threading
import time
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

import httpx

from . import airwallex as awx
from . import claims as cl
from . import instructions as ins
from . import payouts

CENT = Decimal("0.01")

# Where this build pays heirs. MXN and PHP are the corridors the single-owner flow already uses; GBP and JPY
# were run on the live sandbox on 13 Nov 2026 (docs/SANDBOX_RUN_LOG_ESTATE.md). `routes` lists the ways the money
# can travel: PHP cannot be bought into a held balance on this account, so it is paid with a quote inside the
# transfer; GBP and JPY are converted first, which fixes the local amount before any transfer is made.
CORRIDORS: dict[str, dict[str, Any]] = {
    "MXN": {"country": "MX", "place": "Mexico", "routes": (awx.CONVERT_THEN_PAY, awx.PAY_WITH_QUOTE)},
    "PHP": {"country": "PH", "place": "the Philippines", "routes": (awx.PAY_WITH_QUOTE,)},
    "GBP": {"country": "GB", "place": "the United Kingdom", "routes": (awx.CONVERT_THEN_PAY,)},
    "JPY": {"country": "JP", "place": "Japan", "routes": (awx.CONVERT_THEN_PAY,)},
}
BY_COUNTRY = {row["country"]: currency for currency, row in CORRIDORS.items()}

ROUNDING_RULE = ("Each share is rounded down to the cent. The cents left over are given out one each, first to the "
                 "heirs whose shares lost the largest part of a cent, and on a tie to the heir who comes first in "
                 "the family. The parts therefore add up to the whole, to the cent.")
FEE_RULE_WORDS = ("The holder's small-claim line is applied to each heir's share, because Airwallex charges its "
                  "payout fee once per transfer. Below the line the holder bears that heir's fees. From the line "
                  "upward the heir's part of the incoming fee and the payout fee of their own transfer come out of "
                  "their share. Nobody pays for another heir's transfer.")

PLANNED, FUNDING, RUNNING, HELD, DONE = "PLANNED", "FUNDING", "RUNNING", "HELD", "DONE"


# ---- cents -----------------------------------------------------------------------------------------------------

def cents(amount: Any) -> int:
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def figure(amount: Any, currency: str) -> str:
    """'64,002 JPY' or '11,223.58 MXN': the amount with the decimals its currency has."""
    value = awx.money(amount, currency)
    return f"{value:,.0f} {currency}" if currency in awx.ZERO_DECIMAL else f"{value:,.2f} {currency}"


def dollars(value: int) -> str:
    return f"{Decimal(value) / 100:.2f}"


def allocate(total: int, weights: list[Fraction]) -> list[int]:
    """`total` (a whole number of cents) divided in proportion to `weights`, by largest remainder. The parts are
    whole cents and add up to exactly `total`. Order breaks ties: an earlier weight gets the spare cent."""
    if total < 0 or any(w < 0 for w in weights):
        raise ValueError("amounts and weights cannot be negative")
    whole = sum(weights, Fraction(0))
    if not weights or whole == 0:
        raise ValueError("there is nothing to divide among")
    exact = [Fraction(total) * w / whole for w in weights]
    parts = [int(e) for e in exact]                     # rounded down
    spare = total - sum(parts)
    by_loss = sorted(range(len(weights)), key=lambda i: (-(exact[i] - parts[i]), i))
    for i in by_loss[:spare]:
        parts[i] += 1
    return parts


def entitlements(amount: Any, heirs: list[dict]) -> dict[str, int]:
    """Each heir's part of the property's amount, in cents, from the exact fractions. Adds up to the amount."""
    parts = allocate(cents(amount), [Fraction(h["share"]) for h in heirs])
    return {h["id"]: part for h, part in zip(heirs, parts)}


def targets(paying: list[dict], rules: dict | None, fee_usd: dict[str, Decimal]) -> dict:
    """What the holder sends for the heirs being paid, and what should arrive for each after Airwallex's incoming
    fee, under the holder's fee rule applied heir by heir. `paying` rows are {"id", "entitlement" (cents)};
    `fee_usd` is each heir's expected payout fee in US dollars.

    Returns {"holder_sends", "expected_incoming_fee", "net", "legs": {id: cents}, "covered": {id: bool},
    "holder_adds"} in cents."""
    rate = ins.EXPECTED_INCOMING_FEE_RATE
    line = cents(rules["small_claim_usd"]) if rules else None
    covered = {h["id"]: line is not None and h["entitlement"] < line for h in paying}
    whole = sum(h["entitlement"] for h in paying)
    if whole <= 0:
        raise ValueError("there is nothing to pay")
    # What should arrive for each heir after the incoming fee. A covered heir: the whole entitlement plus the
    # payout fee, so the fee leaves the entitlement untouched. Any other heir: the entitlement less the incoming
    # fee on it, exactly as a single claim of that size would be treated. The holder then sends the sum of
    # these divided by (1 - the incoming fee rate), rounded up to the cent.
    weights = [Fraction(h["entitlement"] + cents(fee_usd[h["id"]])) if covered[h["id"]] else
               Fraction(h["entitlement"]) * (1 - Fraction(rate)) for h in paying]
    needed = sum(weights, Fraction(0))
    gross = cents((Decimal(needed.numerator) / Decimal(needed.denominator) / 100 / (1 - rate)).quantize(CENT, rounding=ROUND_UP))
    if not any(covered.values()):
        gross = whole               # nobody is covered: the holder sends the entitlements and not a cent more
    fee_in = cents((Decimal(gross) / 100 * rate).quantize(CENT, rounding=ROUND_HALF_UP))
    net = gross - fee_in
    legs = allocate(net, weights)
    return {"holder_sends": gross, "expected_incoming_fee": fee_in, "net": net, "covered": covered,
            "legs": {h["id"]: part for h, part in zip(paying, legs)}, "weights": [str(w) for w in weights],
            "holder_adds": gross - whole}


# ---- quotes, whichever way round the pair is quoted ---------------------------------------------------------------

def bought(quote: dict, sell: Decimal, currency: str) -> Decimal:
    """What `sell` US dollars buy at this quote. Uses the quote's own amounts where it has them; otherwise the
    rate, read in the direction the quote's currency pair gives."""
    have_sell, have_buy = quote.get("sell_amount"), quote.get("buy_amount")
    if have_sell and have_buy and Decimal(str(have_sell)) > 0:
        return awx.money(sell * Decimal(str(have_buy)) / Decimal(str(have_sell)), currency)
    rate = Decimal(str(quote.get("client_rate") or 0))
    if rate <= 0:
        raise ValueError("the quote carries no rate")
    inverse = str(quote.get("currency_pair") or "").endswith("USD")
    return awx.money(sell / rate if inverse else sell * rate, currency)


def per_dollar(quote: dict, currency: str) -> Decimal:
    """Units of `currency` for one US dollar at this quote, for showing and for turning a fee into local money."""
    return bought(quote, Decimal(1000), currency) / Decimal(1000)


def leg_estimate(route: str, usd: Decimal, currency: str, quote: dict, seen: dict) -> dict:
    """What the heir should receive on this route, with the payout fee Airwallex charged on the last payout made
    that way (`seen`, from airwallex.observed_payout_fees) or, where none was made yet, the expected five US
    dollars or its worth. Every figure is an expectation until Airwallex books it."""
    one = per_dollar(quote, currency)
    if route == awx.PAY_WITH_QUOTE:
        got = seen.get("USD")
        fee = awx.money(got["amount"], "USD") if got else ins.EXPECTED_PAYOUT_FEE_USD
        received = awx.money(max(usd - fee, Decimal(0)) * one, currency)
        fee_view = {"amount": str(fee), "currency": "USD", "observed": bool(got)}
        fee_usd = fee
    else:
        local = bought(quote, usd, currency)
        got = seen.get(currency)
        fee = awx.money(got["amount"], currency) if got else awx.money(ins.EXPECTED_PAYOUT_FEE_USD * one, currency)
        received = max(local - fee, Decimal(0))
        fee_view = {"amount": str(fee), "currency": currency, "observed": bool(got)}
        fee_usd = awx.money(fee / one, "USD") if one > 0 else ins.EXPECTED_PAYOUT_FEE_USD
    return {"route": route, "payout_fee": fee_view, "fee_usd": str(fee_usd),
            "received": {"amount": str(awx.money(received, currency)), "currency": currency}}


def choose_leg_route(currency: str, usd: Decimal, quote: dict, seen: dict, rules: dict | None) -> tuple[dict, list[dict]]:
    """(the estimate on the chosen route, every route compared). With the rule "most to the claimant" the route
    that delivers most is taken, and a tie goes to converting first. Otherwise the first route of the corridor."""
    options = [leg_estimate(route, usd, currency, quote, seen) for route in CORRIDORS[currency]["routes"]]
    if rules and rules.get("route_rule") == "most_to_claimant" and len(options) > 1:
        best = max(options, key=lambda o: (Decimal(o["received"]["amount"]), o["route"] == awx.CONVERT_THEN_PAY))
    else:
        best = options[0]
    return best, options


# ---- bank details ---------------------------------------------------------------------------------------------

def beneficiary(currency: str, first_name: str, last_name: str, account_number: str, *, street_address: str,
                city: str, postcode: str = "", state: str = "", swift_code: str = "", sort_code: str = "",
                bank_code: str = "", branch_code: str = "", account_type: str = "") -> dict:
    """The Airwallex beneficiary body for a person's local bank account in one of the corridors. The fields are
    the ones the live schema asked for on 13 Nov 2026. Raises ValueError, in words, for details that cannot be
    right."""
    if currency not in CORRIDORS:
        raise ValueError("this build pays heirs in Mexico, the Philippines, the United Kingdom and Japan")
    if currency in ("MXN", "PHP"):
        return awx.local_beneficiary(currency, first_name, last_name, account_number, swift_code=swift_code or None,
                                     street_address=street_address, city=city, postcode=postcode or None,
                                     state=state or None)
    country = CORRIDORS[currency]["country"]
    bank: dict[str, Any] = {"account_currency": currency, "bank_country_code": country,
                            "account_name": f"{first_name} {last_name}", "account_number": account_number}
    if currency == "GBP":
        sort_code = sort_code.replace("-", "").replace(" ", "")
        if not (account_number.isdigit() and len(account_number) == 8):
            raise ValueError("a United Kingdom account number must be 8 digits")
        if not (sort_code.isdigit() and len(sort_code) == 6):
            raise ValueError("a United Kingdom sort code must be 6 digits")
        bank.update(account_routing_type1="sort_code", account_routing_value1=sort_code,
                    local_clearing_system="FASTER_PAYMENTS")
    if currency == "JPY":
        if not (account_number.isdigit() and len(account_number) == 7):
            raise ValueError("a Japanese account number must be 7 digits")
        if not (bank_code.isdigit() and len(bank_code) == 4 and branch_code.isdigit() and len(branch_code) == 3):
            raise ValueError("a Japanese account needs a 4-digit bank code and a 3-digit branch code")
        if account_type not in ("Checking", "Savings"):
            raise ValueError("say whether the Japanese account is a Checking or a Savings account")
        bank.update(account_routing_type1="bank_code", account_routing_value1=bank_code,
                    account_routing_type2="branch_code", account_routing_value2=branch_code,
                    bank_account_category=account_type)
    if not postcode:
        raise ValueError("the postcode is needed")
    address = {"country_code": country, "street_address": street_address, "city": city, "postcode": postcode}
    return {"beneficiary": {"type": "BANK_ACCOUNT", "entity_type": "PERSONAL", "first_name": first_name,
                            "last_name": last_name, "address": address, "bank_details": bank},
            "transfer_methods": ["LOCAL"]}


# ---- the settlement file ---------------------------------------------------------------------------------------

class Settlement:
    """The rounds of one estate's settlement, saved to a JSON file beside the claim's documents. Each heir's own
    payout is a separate `airwallex.Payout` file in the same folder."""

    def __init__(self, path: Path | str, claim_id: str, rounds: list | None = None):
        self.path, self.claim_id, self.rounds = Path(path), claim_id, rounds or []

    @classmethod
    def open(cls, path: Path | str, claim_id: str) -> "Settlement":
        path = Path(path)
        if path.exists():
            data = json.loads(path.read_text())
            return cls(path, data["claim_id"], data["rounds"])
        return cls(path, claim_id, [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w") as fh:
            json.dump({"claim_id": self.claim_id, "rounds": self.rounds}, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    @property
    def round(self) -> dict | None:
        return self.rounds[-1] if self.rounds else None

    def file(self, name: str) -> Path:
        return self.path.with_name(name)

    def funding(self, rnd: dict) -> awx.Payout | None:
        path = self.file(rnd["funding_file"])
        return awx.Payout.load(path) if path.exists() else None

    def leg(self, rnd: dict, heir_id: str) -> awx.Payout | None:
        meta = rnd["legs"].get(heir_id) or {}
        path = self.file(meta.get("file") or "")
        return awx.Payout.load(path) if meta.get("file") and path.exists() else None

    def legs(self, rnd: dict) -> list[tuple[dict, awx.Payout | None]]:
        order = [leg["heir"] for leg in (rnd.get("plan") or {}).get("legs") or []]      # the family's own order
        ids = [h for h in order if h in rnd["legs"]] + [h for h in rnd["legs"] if h not in order]
        return [(rnd["legs"][heir_id], self.leg(rnd, heir_id)) for heir_id in ids]

    def paid_heirs(self) -> dict[str, dict]:
        """Every heir Airwallex reports as paid, in any round, with what they received."""
        out = {}
        for rnd in self.rounds:
            for meta, leg in self.legs(rnd):
                if leg is not None and leg.state == awx.PAID:
                    out[meta["heir"]] = {"at": leg.paid_at, "amount": leg.target_amount,
                                         "currency": leg.target_currency, "transfer_id": leg.transfer_id,
                                         "round": rnd["n"]}
        return out

    def live_heirs(self) -> set[str]:
        """Heirs who have a payout that is paid, on its way, or holding money. None of them may be in a new round."""
        out = set()
        for rnd in self.rounds:
            if rnd["state"] == PLANNED:
                continue
            out |= set(rnd["legs"])
        return out


def _safe_id(heir_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in heir_id)


# ---- the plan --------------------------------------------------------------------------------------------------

def make_plan(claim: dict, proof: dict, client: awx.AirwallexClient, settlement: Settlement, *,
              rules: dict | None, deadline_at: str | None = None, fail_heir: str | None = None,
              simulator_ready: bool = False) -> dict:
    """The written plan for the next round: who is paid now and who is held, what the holder sends under the fee
    rule, and for each heir the route, the locked rate, the fee and the amount to expect. It takes one quote
    per heir from Airwallex and moves no money. Asking again before agreeing makes a new plan."""
    estate = claim["estate"]
    heirs = estate["heirs"]
    amount = claim["record"]["amount"]
    owed = entitlements(amount, heirs)
    by_proof = {h["id"]: h for h in proof["heirs"]}
    live = settlement.live_heirs()
    stopped = settlement.round if settlement.round and settlement.round["state"] == HELD else None
    if stopped:      # the deposit differed from the plan: plan again for the same heirs, on what arrived
        live -= set(stopped["legs"])
    paying = [h for h in heirs if by_proof[h["id"]]["payable"] and h["id"] not in live and not h.get("paid")]
    if stopped:
        paying = [h for h in paying if h["id"] in stopped["legs"]]
    if not paying:
        raise cl.ClaimError(409, "No heir can be paid in this round: each one is already paid, on the way, or "
                                 "not yet proven.")
    for heir in paying:
        if heir["payee"]["currency"] not in CORRIDORS:
            raise cl.ClaimError(409, f"{heir['name']} cannot be paid yet: this build does not pay in "
                                     f"{heir['payee']['currency']}.")
    seen = {h["id"]: awx.observed_payout_fees(client, h["payee"]["currency"]) for h in paying}
    # A first quote for each heir's entitlement gives the expected payout fee in US dollars, which the fee rule
    # needs. The quote that is locked is taken for the amount that will really be sent.
    fee_usd = {}
    for heir in paying:
        currency = heir["payee"]["currency"]
        first = client.create_quote("USD", currency, sell_amount=Decimal(owed[heir["id"]]) / 100, validity="HR_1")
        best, _ = choose_leg_route(currency, Decimal(owed[heir["id"]]) / 100, first, seen[heir["id"]], rules)
        fee_usd[heir["id"]] = Decimal(best["fee_usd"])
    rows = [{"id": h["id"], "entitlement": owed[h["id"]]} for h in paying]
    sums = targets(rows, rules, fee_usd)
    if stopped:
        arrived = stopped.get("arrived") or {}
        net = cents(arrived.get("net") or 0)
        if net <= 0:
            raise cl.ClaimError(409, "Nothing usable arrived for this estate, so there is nothing to plan on.")
        parts = allocate(net, [Fraction(w) for w in sums["weights"]])
        sums = {**sums, "net": net, "holder_sends": cents(arrived["deposit"]),
                "expected_incoming_fee": cents(arrived.get("incoming_fee") or 0),
                "holder_adds": cents(arrived["deposit"]) - sum(r["entitlement"] for r in rows),
                "legs": {r["id"]: part for r, part in zip(rows, parts)}}
    legs = []
    for heir in paying:
        currency = heir["payee"]["currency"]
        usd = Decimal(sums["legs"][heir["id"]]) / 100
        quote = client.create_quote("USD", currency, sell_amount=usd, validity="HR_1")
        best, compared = choose_leg_route(currency, usd, quote, seen[heir["id"]], rules)
        bank = heir["payee"]["beneficiary"]["beneficiary"]["bank_details"]
        fee = best["payout_fee"]
        legs.append({
            "heir": heir["id"], "name": heir["name"], "relation": heir["relation"], "share": heir["share"],
            "entitlement": dollars(owed[heir["id"]]), "covered": sums["covered"][heir["id"]],
            "leg_usd": dollars(sums["legs"][heir["id"]]), "currency": currency,
            "country": CORRIDORS[currency]["country"], "place": CORRIDORS[currency]["place"],
            "route": best["route"], "route_name": payouts.ROUTE_NAMES[best["route"]],
            "routes_compared": [{"route": o["route"], "route_name": payouts.ROUTE_NAMES[o["route"]],
                                 "would_receive": o["received"], "payout_fee": o["payout_fee"],
                                 "chosen": o["route"] == best["route"]} for o in compared],
            "quote": {"quote_id": quote["quote_id"], "client_rate": quote.get("client_rate"),
                      "mid_rate": quote.get("mid_rate"), "currency_pair": quote.get("currency_pair"),
                      "sell_amount": quote.get("sell_amount"), "buy_amount": quote.get("buy_amount"),
                      "valid_to_at": quote.get("valid_to_at")},
            "per_dollar": str(per_dollar(quote, currency).quantize(Decimal("0.000001"))),
            "payout_fee": {"amount": fee["amount"], "currency": fee["currency"],
                           "basis": "what Airwallex charged on the last payout made this way" if fee["observed"]
                           else "expected: about five US dollars, what Airwallex has charged on local payouts"},
            "expected_local": best["received"],
            "account": {"name": bank.get("account_name"), "number": payouts._mask_account(bank.get("account_number") or ""),
                        "country": bank.get("bank_country_code")},
            "what_if": "transfer_fails" if simulator_ready and fail_heir == heir["id"] else None})
    held = [{"heir": h["id"], "name": h["name"], "relation": h["relation"], "share": h["share"],
             "entitlement": dollars(owed[h["id"]]), "missing": by_proof[h["id"]]["missing"]}
            for h in heirs if h["id"] not in live and not h.get("paid") and h not in paying]
    tolerance = rules["tolerance_percent"] if rules else "0"
    plan = {
        "id": awx.new_request_id(), "made_at": cl.now(), "on_what_arrived": bool(stopped),
        "round": stopped["n"] if stopped else len([r for r in settlement.rounds if r["state"] != PLANNED]) + 1,
        "property_amount": f"{Decimal(str(amount)):.2f}", "currency": "USD",
        "entitlements": {k: dollars(v) for k, v in owed.items()},
        "paying_total": dollars(sum(owed[h["id"]] for h in paying)),
        "holder_sends": dollars(sums["holder_sends"]), "holder_adds": dollars(sums["holder_adds"]),
        "expected_incoming_fee": dollars(sums["expected_incoming_fee"]), "net": dollars(sums["net"]),
        "legs": legs, "held": held,
        "held_total": dollars(sum(owed[h["heir"]] for h in held)),
        "already": [{"heir": h["id"], "name": h["name"]} for h in heirs if h["id"] in live or h.get("paid")],
        "rounding_rule": ROUNDING_RULE, "fee_rule": FEE_RULE_WORDS,
        "small_claim_usd": rules["small_claim_usd"] if rules else None, "tolerance_percent": tolerance,
        "deadline_at": deadline_at, "instructions": rules and {"rules": rules, "in_words": ins.in_words(rules)},
        "if_things_change": [
            "Each heir is paid by a transfer of their own. If one bank refuses or returns a transfer, the other "
            "heirs are still paid. The money that comes back is held for that heir, who corrects the bank "
            "account; the holder approves it, and one replacement is sent.",
            f"If a new rate has to be locked for an heir and they would still receive no less than {tolerance} "
            "percent below the amount in this plan, that heir's payment carries on and the change is noted. If it "
            "would be worse, that heir's payment stops and the family is asked. The other heirs are not held up.",
            "If less arrives from the holder than this plan says, by more than the tolerance, nothing is "
            "converted or sent to anyone until the holder has approved the new amount.",
            "At no point is more sent than arrived for this estate, and no heir is paid twice.",
        ],
    }
    return plan


def plan_cards(plan: dict) -> list[dict]:
    """The plan's decisions as cards of four short lines (the shape of cards.py)."""
    money = lambda v: f"${Decimal(str(v)):,.2f}"
    legs, held = plan["legs"], plan["held"]
    covered = [l for l in legs if l["covered"]]
    out = [{
        "kind": "estate_split", "tone": "go", "title": "The split",
        "happened": f"{money(plan['property_amount'])} for {len(legs) + len(held) + len(plan['already'])} heirs.",
        "allowed": "Shares under the Probate Code, as approved.",
        "did": "Divided by the exact fractions, cents by largest remainder.",
        "money": "; ".join(f"{l['name'].split()[0]} {money(l['entitlement'])}" for l in legs)
                 + ("; " + "; ".join(f"{h['name'].split()[0]} {money(h['entitlement'])} held" for h in held) if held else "") + ".",
        "why": [plan["rounding_rule"]]}]
    if plan.get("small_claim_usd"):
        line = money(plan["small_claim_usd"])
        out.append({
            "kind": "estate_fees", "tone": "go", "title": "The fee rule, heir by heir",
            "happened": f"{len(legs)} transfers, each with its own Airwallex payout fee.",
            "allowed": f"Below {line} per heir, the holder bears that heir's fees.",
            "did": (f"The holder bears the fees of {len(covered)} of {len(legs)} heirs and sends {money(plan['holder_sends'])}."
                    if covered else f"No share is below the line. The holder sends {money(plan['holder_sends'])}."),
            "money": (f"{money(plan['holder_adds'])} added by the holder." if Decimal(plan["holder_adds"]) > 0 else
                      "Fees come out of each heir's own share."),
            "why": [plan["fee_rule"]]})
    if held:
        out.append({
            "kind": "estate_held", "tone": "ask", "title": "A share that waits",
            "happened": f"{len(held)} {'heir is' if len(held) == 1 else 'heirs are'} not proven yet.",
            "allowed": "Pay only heirs whose proof is ready.",
            "did": f"It pays {len(legs)} now and leaves the rest with the holder.",
            "money": f"{money(plan['held_total'])} held for " + ", ".join(h["name"] for h in held) + ".",
            "why": [f"{h['name']}: {' '.join(h['missing'][:3])}" for h in held]})
    return out


# ---- the machine -----------------------------------------------------------------------------------------------

def start_round(settlement: Settlement, claim: dict, plan: dict, *, rules: dict | None, deadline_at: str | None,
                simulator_ready: bool) -> dict:
    """The family agreed to the plan: the round begins with the holder's one deposit. Nothing is created at
    Airwallex here; the request ids are made and saved first."""
    n = plan["round"]
    reference = f"KHUTLISA-{claim['id']}-S{n}"
    payees = {h["id"]: h["payee"] for h in claim["estate"]["heirs"]}
    stopped = settlement.round if settlement.round and settlement.round["state"] == HELD else None
    if stopped and plan.get("on_what_arrived"):
        # The deposit is already in. Everyone has now agreed to the plan made on it, so it can be divided.
        funding = settlement.funding(stopped)
        for who in list((funding.hold or {}).get("needs", [])):
            funding.agreed(who)
        stopped.update(state=FUNDING, plan=plan, confirmed={"plan_id": plan["id"], "at": cl.now()}, rules=rules,
                       deadline_at=deadline_at, held_because=None,
                       legs={leg["heir"]: {"heir": leg["heir"], "name": leg["name"], "currency": leg["currency"],
                                           "file": f"estate_r{n}_{_safe_id(leg['heir'])}.json", "planned": leg,
                                           "beneficiary": payees[leg["heir"]]["beneficiary"]} for leg in plan["legs"]})
        _event(stopped, "The plan made on what arrived was agreed.")
        settlement.save()
        return stopped
    rnd = {"n": n, "state": FUNDING, "plan": plan, "confirmed": {"plan_id": plan["id"], "at": cl.now()},
           "reference": reference, "funding_file": f"estate_r{n}_funding.json", "legs": {}, "events": [],
           "problems": {}, "rules": rules, "deadline_at": deadline_at, "simulator_ready": simulator_ready}
    for leg in plan["legs"]:
        rnd["legs"][leg["heir"]] = {"heir": leg["heir"], "name": leg["name"], "currency": leg["currency"],
                                    "file": f"estate_r{n}_{_safe_id(leg['heir'])}.json", "planned": leg,
                                    "beneficiary": payees[leg["heir"]]["beneficiary"]}
    awx.Payout.open(settlement.file(rnd["funding_file"]), usd_amount=plan["holder_sends"], target_currency="USD",
                    deposit_reference=reference, beneficiary={}, state=awx.DEPOSIT_EXPECTED, instructions=rules)
    settlement.rounds = [r for r in settlement.rounds if r["state"] != PLANNED] + [rnd]
    _event(rnd, f"The plan was agreed. The holder sends {plan['holder_sends']} USD with the reference {reference}.")
    settlement.save()
    return rnd


def _event(rnd: dict, text: str, heir: str | None = None) -> None:
    rnd["events"].append({"at": cl.now(), "text": text, "heir": heir})


def _split(settlement: Settlement, rnd: dict, funding: awx.Payout) -> None:
    """The deposit is in and Airwallex has booked its fee. Divide what is left among this round's heirs in the
    proportions of the plan, and create each heir's payout file. Cents add up to exactly what is held."""
    plan = rnd["plan"]
    net = cents(funding.funds["amount"])
    weights = [Fraction(l["leg_usd"]) for l in plan["legs"]]
    parts = allocate(net, weights)
    rnd["arrived"] = {"deposit": funding.deposit_amount, "incoming_fee": funding.deposit_fee,
                      "net": dollars(net), "deposit_id": funding.deposit_id}
    for leg_plan, part in zip(plan["legs"], parts):
        meta = rnd["legs"][leg_plan["heir"]]
        meta["leg_usd"] = dollars(part)
        quote = leg_plan["quote"]
        fits = cents(leg_plan["leg_usd"]) == part
        awx.Payout.open(
            settlement.file(meta["file"]), usd_amount=dollars(part), target_currency=leg_plan["currency"],
            deposit_reference=f"{rnd['reference']}-{_safe_id(leg_plan['heir'])}"[:60], beneficiary=meta["beneficiary"],
            state=awx.DEPOSIT_CONFIRMED, funds={"amount": dollars(part), "currency": "USD"}, route=leg_plan["route"],
            claim_usd=leg_plan["entitlement"], instructions=rnd.get("rules"), deadline_at=rnd.get("deadline_at"),
            what_if=leg_plan.get("what_if"), spot_checked=True,
            # The plan's quote is used if it was made for exactly this amount; otherwise a new one is taken.
            quote_id=quote["quote_id"] if fits else None, quote_sell=dollars(part) if fits else None,
            quote_valid_to=quote.get("valid_to_at") if fits else None, client_rate=quote.get("client_rate"),
            mid_rate=quote.get("mid_rate"), global_account_id=funding.global_account_id)
    rnd["state"] = RUNNING
    _event(rnd, f"{funding.deposit_amount} USD arrived and Airwallex booked a fee of {funding.deposit_fee} USD. The "
                f"{dollars(net)} USD left was divided among {len(parts)} heirs: "
                + ", ".join(f"{l['name']} {dollars(p)} USD" for l, p in zip(plan["legs"], parts)) + ".")


def _ensure_quote(leg: awx.Payout, meta: dict, client: awx.AirwallexClient, rules: dict | None,
                  clock: Callable[[], float]) -> bool:
    """Before a leg's money is converted or sent it needs a live quote made for its exact amount. When a new one
    has to be taken, the amount it gives is compared with the plan under the holder's tolerance. False when the
    leg was paused because the heir would receive too much less."""
    usd = awx.money(leg.funds["amount"], "USD")
    fits = bool(leg.quote_id) and leg.quote_sell is not None and awx.money(leg.quote_sell, "USD") == usd
    if fits and not awx._quote_expired(leg, clock):
        return True
    currency = leg.target_currency
    quote = client.create_quote("USD", currency, sell_amount=usd, validity="HR_1")
    seen = awx.observed_payout_fees(client, currency)
    now = leg_estimate(leg.route, usd, currency, quote, seen)["received"]["amount"]
    planned = meta["planned"]["expected_local"]["amount"]
    inside, short = ins.within_tolerance(planned, now, rules)
    facts = {"old_rate": meta["planned"]["quote"].get("client_rate"), "new_rate": quote.get("client_rate"),
             "old_local": planned, "new_local": now, "currency": currency, "usd": str(usd),
             "tolerance_percent": rules["tolerance_percent"] if rules else "0", "shortfall_percent": str(short)}
    awx._take_quote(leg, quote, usd)
    if not inside:
        leg.pause(awx.HELD, "amount_changed", ["claimant"], awx.DEPOSIT_CONFIRMED, facts,
                  f"a new quote gives {now} {currency}; {planned} {currency} was planned")
        return False
    leg.decide("requoted", "tolerance",
               f"A new rate was locked for {usd} USD. It gives {figure(now, currency)}, against "
               f"{figure(planned, currency)} in the plan, which is inside the tolerance, so this heir's "
               "payment carried on without asking.", **facts)
    leg.save()
    return True


def _after_refusal(leg: awx.Payout, meta: dict, client: awx.AirwallexClient, rules: dict | None) -> None:
    """A bank refused or returned one heir's transfer. Work out what a replacement would bring, once, and under
    the holder's tolerance decide whether the family has to agree to it again. The corrected account and the
    holder's approval of it are needed in every case."""
    hold = leg.hold or {}
    if hold.get("replacement") or hold.get("kind") not in ("transfer_failed", "transfer_returned"):
        return
    back = (hold.get("facts") or {}).get("came_back") or {}
    currency = back.get("currency") or leg.target_currency
    seen = awx.observed_payout_fees(client, leg.target_currency)
    if currency == leg.target_currency:
        got = seen.get(currency)
        planned_fee = meta["planned"]["payout_fee"]
        fee = (awx.money(got["amount"], currency) if got else
               awx.money(planned_fee["amount"], currency) if planned_fee["currency"] == currency else
               awx.money(ins.EXPECTED_PAYOUT_FEE_USD * Decimal(meta["planned"]["per_dollar"]), currency))
        would = max(awx.money(back.get("amount") or 0, currency) - fee, Decimal(0))
    else:           # it came back in US dollars: a replacement is quoted again when it is made
        would = awx.money(meta["planned"]["expected_local"]["amount"], leg.target_currency)
    agreed = meta.get("received_first") or meta["planned"]["expected_local"]["amount"]
    inside, short = ins.within_tolerance(agreed, would, rules)
    hold["replacement"] = {"would_receive": {"amount": str(would), "currency": leg.target_currency},
                           "agreed": agreed, "shortfall_percent": str(short), "family_asked": not inside,
                           "tolerance_percent": rules["tolerance_percent"] if rules else None}
    if inside and "claimant" in hold.get("needs", []):
        hold["needs"] = [n for n in hold["needs"] if n != "claimant"]
        leg.decide("replacement_within_tolerance", "tolerance",
                   f"The replacement would bring {figure(would, leg.target_currency)}, {short} percent less than the "
                   f"{figure(agreed, leg.target_currency)} in the plan, because Airwallex charges its payout "
                   "fee again. That is inside the tolerance, so the family is not asked to agree again. The new "
                   "bank account still has to come from the heir and be approved by the holder.")
    leg.hold = hold
    leg.save()


LEG_DONE = (awx.PAID,) + awx.STOPPED


def step(settlement: Settlement, client: awx.AirwallexClient, simulator: awx.SandboxSimulator | None = None,
         clock: Callable[[], float] | None = None, max_errors: int = 3) -> bool:
    """One pass over the current round. Returns True when something moved. Each heir's payout is advanced by
    one step, inside its own try: an error on one never reaches another, and after `max_errors` in a row that
    heir's payout is left where it stands and reported, while the others carry on."""
    clock = clock or time.time
    rnd = settlement.round
    if rnd is None or rnd["state"] in (PLANNED, DONE, HELD):
        return False
    moved = False
    if rnd["state"] == FUNDING:
        funding = settlement.funding(rnd)
        before = funding.state
        if funding.state == awx.DEPOSIT_EXPECTED:
            awx.advance(funding, client, simulator, clock)
        if funding.state == awx.DEPOSIT_CONFIRMED:
            _split(settlement, rnd, funding)
            moved = True
        elif funding.state in (awx.HELD, awx.FAILED):
            facts = (funding.hold or {}).get("facts") or {}
            rnd["state"] = HELD
            rnd["held_because"] = (
                f"The holder sent {facts.get('arrived')} USD and {facts.get('approved')} USD was planned. Nothing "
                "has been converted or sent to anyone. The holder has to approve the estate again on what arrived."
                if facts else f"The deposit could not be used: {funding.failure}.")
            rnd["arrived"] = {"deposit": funding.deposit_amount, "incoming_fee": funding.deposit_fee,
                              "net": (funding.funds or {}).get("amount"), "deposit_id": funding.deposit_id}
            _event(rnd, rnd["held_because"])
            moved = True
        else:
            moved = funding.state != before
        settlement.save()
        return moved
    rules = rnd.get("rules")
    for heir_id, meta in rnd["legs"].items():
        leg = settlement.leg(rnd, heir_id)
        if leg is None or leg.state in LEG_DONE:
            if leg is not None and leg.state == awx.FAILED and leg.hold and not leg.hold.get("replacement"):
                try:
                    _after_refusal(leg, meta, client, rules)
                    moved = True
                except (awx.AirwallexError, httpx.HTTPError):
                    pass
            continue
        if rnd["problems"].get(heir_id, {}).get("count", 0) >= max_errors:
            continue
        before = (leg.state, leg.transfer_status, len(leg.history), bool(leg.hold))
        try:
            if leg.state == awx.DEPOSIT_CONFIRMED and not _ensure_quote(leg, meta, client, rules, clock):
                _event(rnd, f"{meta['name']}: the rate changed beyond the tolerance, so this heir's payment waits "
                            "for the family. The other heirs are not held up.", heir_id)
                moved = True
                continue
            awx.advance(leg, client, simulator, clock)
            rnd["problems"].pop(heir_id, None)
        except (awx.AirwallexError, httpx.HTTPError, ValueError) as err:
            seen = rnd["problems"].get(heir_id, {"count": 0})
            rnd["problems"][heir_id] = {"count": seen["count"] + 1, "text": payouts.explain(err), "at": cl.now()}
            if seen["count"] + 1 >= max_errors:
                _event(rnd, f"{meta['name']}: {payouts.explain(err)} This heir's payment is left where it stands. "
                            "The other heirs are not held up.", heir_id)
                moved = True
            continue
        after = (leg.state, leg.transfer_status, len(leg.history), bool(leg.hold))
        if after != before:
            moved = True
            if leg.state == awx.PAID:
                awx.refresh_ledger(leg, client)
                leg.save()
                meta["received_first"] = meta.get("received_first") or leg.target_amount
                _event(rnd, f"{meta['name']} was paid {figure(leg.target_amount, leg.target_currency)} in "
                            f"{CORRIDORS[leg.target_currency]['place']}.", heir_id)
            elif leg.state == awx.FAILED and leg.hold:
                back = (leg.hold.get("facts") or {}).get("came_back") or {}
                _event(rnd, f"{meta['name']}: the bank refused the transfer ({leg.failure or 'no reason given'}). "
                            f"{back.get('amount')} {back.get('currency')} came back and is held for this heir. The "
                            "other heirs are not held up.", heir_id)
                _after_refusal(leg, meta, client, rules)
            elif refused_not_back(leg) and not meta.get("refusal_noted"):
                meta["refusal_noted"] = True
                _event(rnd, f"{meta['name']}: the bank refused the transfer ({leg.failure or 'no reason given'}). "
                            "Airwallex has not booked the money back yet, so nothing more is sent for this heir "
                            "until it has. The other heirs are not held up.", heir_id)
            elif leg.state == awx.HELD and leg.hold:
                _event(rnd, f"{meta['name']}: this heir's payment is waiting "
                            f"({leg.hold['kind'].replace('_', ' ')}). The other heirs are not held up.", heir_id)
    if all((leg is not None and leg.state in LEG_DONE) or rnd["problems"].get(h, {}).get("count", 0) >= max_errors
           for h, (meta, leg) in zip(rnd["legs"], settlement.legs(rnd))):
        if all(leg.state == awx.PAID for _, leg in settlement.legs(rnd) if leg is not None) and not rnd["problems"]:
            if rnd["state"] != DONE:
                rnd["state"] = DONE
                _event(rnd, "Every heir in this round has been paid.")
                moved = True
    settlement.save()
    return moved


def refused_not_back(leg: awx.Payout) -> bool:
    """A transfer the bank refused, for which Airwallex has not yet booked the money back. Until it has, the
    machine only reads and waits: a replacement is never sent on money that has not returned."""
    return leg.state in (awx.TRANSFER_CREATED, awx.SENT, awx.PAID) and leg.transfer_status in awx.TRANSFER_DEAD


def idle(settlement: Settlement) -> bool:
    """True when nothing more can happen without a person: no round, a finished or held round, or every heir's
    payout is paid or waiting for someone."""
    rnd = settlement.round
    if rnd is None or rnd["state"] in (PLANNED, DONE, HELD):
        return True
    if rnd["state"] == FUNDING:
        return False
    return all(leg is not None and leg.state in LEG_DONE and not (leg.state == awx.FAILED and leg.hold
               and not leg.hold.get("replacement")) for _, leg in settlement.legs(rnd))


def run(settlement: Settlement, client: awx.AirwallexClient, simulator: awx.SandboxSimulator | None = None, *,
        pause: float = 1.0, max_idle: int = 120, sleep: Callable[[float], None] = time.sleep,
        on_step: Callable[[Settlement], None] | None = None) -> Settlement:
    """Step until nothing more can happen without a person, or until Airwallex has kept us waiting too long."""
    waited = 0
    while not idle(settlement) and waited < max_idle:
        if step(settlement, client, simulator):
            waited = 0
        else:
            waited += 1
            sleep(pause)
        if on_step:
            on_step(settlement)
    return settlement


# ---- reading it back -------------------------------------------------------------------------------------------

def reconciliation(settlement: Settlement) -> dict:
    """Every row Airwallex booked for this estate: each round's deposit and fee, and each heir's conversion and
    transfers. The settlement balances when every currency adds up to zero. Money that a bank sent back and that
    is held for an heir shows as what is left in that heir's currency, and is named."""
    lines, held, outstanding = [], [], []
    for rnd in settlement.rounds:
        if rnd["state"] == PLANNED:
            continue
        funding = settlement.funding(rnd)
        for row in (funding.ledger if funding else []):
            lines.append({**row, "part": "deposit", "who": "The holder's deposit", "round": rnd["n"]})
        for meta, leg in settlement.legs(rnd):
            if leg is None:
                continue
            for row in leg.ledger:
                lines.append({**row, "who": meta["name"], "round": rnd["n"]})
            if refused_not_back(leg):
                outstanding.append({"heir": meta["heir"], "name": meta["name"], "amount": leg.target_amount,
                                    "currency": leg.target_currency})
            elif leg.state != awx.PAID and leg.funds:
                held.append({"heir": meta["heir"], "name": meta["name"], **leg.funds})
    base = payouts.reconciliation({"ledger": lines, "state": None})
    for line, row in zip(base["lines"], lines):
        line["who"], line["round"] = row["who"], row["round"]
    left = [s for s in base["sums"] if Decimal(s["left"]) != 0]
    if not lines:
        statement = "Airwallex has booked nothing for this estate yet."
    elif outstanding:
        statement = ("A bank refused the transfer to " + ", ".join(o["name"] for o in outstanding) + ", and Airwallex "
                     "has not booked the money back yet: " + ", ".join(figure(o["amount"] or 0, o["currency"])
                                                                       for o in outstanding)
                     + " is outstanding. The other lines add up. Nothing more is sent for that heir until the "
                       "money is back.")
    elif not left:
        statement = ("Every line Airwallex booked for this estate adds up to zero in every currency: what arrived, "
                     "less Airwallex's fees, is exactly what was sent to the heirs.")
    else:
        statement = ("Held at Airwallex for this estate right now: "
                     + ("; ".join(f"{figure(h['amount'], h['currency'])} for {h['name']}" for h in held) if held else
                        ", ".join(figure(s["left"], s["currency"]) for s in left)) + ". Every other line adds up.")
    explained = {}
    for h in held:
        explained[h["currency"]] = explained.get(h["currency"], Decimal(0)) + Decimal(str(h["amount"]))
    unexplained = [s for s in left if explained.get(s["currency"]) != Decimal(s["left"])]
    return {"lines": base["lines"], "sums": base["sums"], "balanced": bool(lines) and not left and not outstanding,
            "held": held, "outstanding": outstanding,
            "accounted_for": bool(lines) and not unexplained and not outstanding, "statement": statement}


JOURNEY = (("funded", "Share set aside"), ("converted", "In their currency"), ("sent", "Sent"), ("paid", "Paid"))


def _leg_view(meta: dict, leg: awx.Payout | None, problem: dict | None) -> dict:
    planned = meta["planned"]
    out = {"heir": meta["heir"], "name": meta["name"], "relation": planned["relation"], "share": planned["share"],
           "currency": meta["currency"], "country": planned["country"], "place": planned["place"],
           "entitlement": planned["entitlement"], "covered": planned["covered"], "account": planned["account"],
           "planned_usd": planned["leg_usd"], "expected_local": planned["expected_local"],
           "route": planned["route"], "route_name": planned["route_name"], "per_dollar": planned["per_dollar"],
           "state": "WAITING", "problem": (problem or {}).get("text"), "what_if": planned.get("what_if")}
    if leg is None:
        return {**out, "journey": [{"key": k, "label": label, "done": False} for k, label in JOURNEY]}
    at = {}
    for event in leg.history:
        at[event["state"]] = event["at"]
    sent = leg.transfer_id is not None and leg.transfer_status in ("SENT", "PAID") or leg.state in (awx.SENT, awx.PAID)
    done = {"funded": True, "converted": leg.state in (awx.CONVERTED, awx.BENEFICIARY_READY, awx.TRANSFER_CREATED,
                                                       awx.SENT, awx.PAID) or bool(leg.attempts),
            "sent": sent, "paid": leg.state == awx.PAID}
    hold = leg.hold
    bank = (leg.beneficiary or {}).get("beneficiary", {}).get("bank_details", {})
    return {**out, "state": leg.state, "refused_not_back": refused_not_back(leg), "leg_usd": leg.usd_amount, "transfer_status": leg.transfer_status,
            "transfer_id": leg.transfer_id, "paid_at": leg.paid_at, "failure": leg.failure,
            "account": {"name": bank.get("account_name"), "number": payouts._mask_account(bank.get("account_number") or ""),
                        "country": bank.get("bank_country_code")},
            "local": leg.target_amount and {"amount": leg.target_amount, "currency": leg.target_currency},
            "received": ({"amount": leg.target_amount, "currency": leg.target_currency}
                         if leg.state == awx.PAID and leg.target_amount else None),
            "payout_fee": leg.transfer_fee and {"amount": leg.transfer_fee["amount"], "currency": leg.transfer_fee["currency"]},
            "funds": leg.funds, "attempts": leg.attempts,
            "hold": hold and {"kind": hold["kind"], "needs": hold.get("needs", []),
                              "needs_words": [payouts.NEEDS_WORDS[n].replace("the claimant", "the heir")
                                              for n in hold.get("needs", [])],
                              "facts": hold.get("facts"), "replacement": hold.get("replacement")},
            "decisions": [d for d in leg.decisions if d.get("by") == "agent"],
            "journey": [{"key": k, "label": label, "done": bool(done[k]),
                         "at": at.get({"converted": awx.CONVERTED, "sent": awx.SENT, "paid": awx.PAID}.get(k, ""))}
                        for k, label in JOURNEY]}


def view(settlement: Settlement | None, *, running: bool = False, problem: str | None = None) -> dict:
    """Everything the estate screen shows about the settlement."""
    if settlement is None or not settlement.rounds:
        return {"started": False, "rounds": [], "plan": None, "running": running, "problem": problem,
                "reconciliation": None, "paid": {}}
    rounds = []
    for rnd in settlement.rounds:
        legs = [_leg_view(meta, leg, rnd["problems"].get(meta["heir"])) for meta, leg in settlement.legs(rnd)]
        rounds.append({"n": rnd["n"], "state": rnd["state"], "plan": rnd["plan"], "cards": plan_cards(rnd["plan"]),
                       "reference": rnd.get("reference"), "arrived": rnd.get("arrived"),
                       "held_because": rnd.get("held_because"), "events": rnd["events"], "legs": legs,
                       "waiting": [l["heir"] for l in legs if l.get("hold")]})
    last = settlement.round
    return {"started": any(r["state"] != PLANNED for r in settlement.rounds), "rounds": rounds,
            "plan": last["plan"] if last["state"] == PLANNED else None,
            "plan_cards": plan_cards(last["plan"]) if last["state"] == PLANNED else [],
            "running": running, "problem": problem, "paid": settlement.paid_heirs(),
            "reconciliation": reconciliation(settlement)}


# ---- running it in the background -------------------------------------------------------------------------------

class EstateRunner:
    """One background thread per estate whose settlement has something to do. `after(claim_id, settlement)` is
    called whenever the machine comes to rest, so the claim can learn what happened."""

    def __init__(self, store: cl.ClaimStore, factory, *, pause: float = 1.0, max_idle: int = 180,
                 after: Callable[[str, Settlement], None] | None = None):
        self.store, self.factory, self.pause, self.max_idle, self.after = store, factory, pause, max_idle, after
        self.problems: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def path(self, claim_id: str) -> Path:
        return self.store.files(claim_id) / "estate_settlement.json"

    def load(self, claim_id: str) -> Settlement | None:
        path = self.path(claim_id)
        return Settlement.open(path, claim_id) if path.exists() else None

    def running(self, claim_id: str) -> bool:
        thread = self._threads.get(claim_id)
        return bool(thread and thread.is_alive())

    def start(self, claim_id: str) -> None:
        with self._lock:
            if self.running(claim_id) or self._stop.is_set():
                return
            self.problems.pop(claim_id, None)
            thread = threading.Thread(target=self._work, args=(claim_id,), name=f"estate-{claim_id}", daemon=True)
            self._threads[claim_id] = thread
            thread.start()

    def join(self, claim_id: str, timeout: float = 20.0) -> None:
        thread = self._threads.get(claim_id)
        if thread is not None:
            thread.join(timeout)

    def stop(self, wait: float = 5.0) -> None:
        self._stop.set()
        for thread in list(self._threads.values()):
            thread.join(wait)

    def resume_all(self) -> list[str]:
        """After a restart: carry on with every settlement that had started and has something left to do."""
        resumed = []
        if not self.store.folder.is_dir():
            return resumed
        for path in sorted(self.store.folder.glob("*/estate_settlement.json")):
            claim_id = path.parent.name
            try:
                settlement = Settlement.open(path, claim_id)
            except (ValueError, KeyError):
                continue
            if not idle(settlement):
                self.start(claim_id)
                resumed.append(claim_id)
        return resumed

    def _work(self, claim_id: str) -> None:
        client = None
        try:
            client, simulator = self.factory()
            waited = 0
            while not self._stop.is_set():
                with self.store.lock:           # people act on the same files (a corrected account, an approval)
                    settlement = Settlement.open(self.path(claim_id), claim_id)
                    if idle(settlement):
                        break
                    moved = step(settlement, client, simulator)
                if moved:
                    waited = 0
                else:
                    waited += 1
                    if waited >= self.max_idle:
                        self.problems[claim_id] = ("The settlement is still waiting on Airwallex. Starting it again "
                                                   "carries on from where it stopped.")
                        break
                    self._stop.wait(self.pause)
        except Exception as err:       # the thread must never die silently
            self.problems[claim_id] = payouts.explain(err)
        finally:
            if client is not None:
                client.close()
            if self.after is not None:
                try:
                    settlement = self.load(claim_id)
                    if settlement is not None:
                        self.after(claim_id, settlement)
                except Exception as err:
                    self.problems.setdefault(claim_id, payouts.explain(err))
