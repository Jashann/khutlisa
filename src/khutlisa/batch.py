"""A batch: several approved payments funded together and paid through the same payout machine.

A single claim has its own deposit and its own conversion (airwallex.Payout). A batch has one deposit for all of
its payments and, where the plan chose it, one conversion per currency; each payment is then an ordinary Payout
that starts with its share of that money and is carried by `airwallex.advance` from there: beneficiary, transfer,
SENT, PAID, and the same path as ever when the receiving bank refuses it.

The guarantees are the ones a single payout has:

  never pays twice     the deposit is found by its reference before one is made; a conversion and a transfer are
                       each looked up by a request id that was stored before the call, and a duplicate reply
                       adopts the object already made
  restart-safe         the batch file is written whole and swapped into place after every step, and each
                       payment is its own payout file; `advance` can be called again at any point
  bound to approval    the holder approves the batch on exact terms (every owner, amount and bank account, the
                       limits, and how each currency is funded). Money is committed only while those terms are
                       unchanged, and a payment whose bank account changes waits for the holder again
  reconciles           Airwallex's own ledger rows for the deposit, every conversion and every transfer are read
                       again and must add up to zero in every currency once everything is paid

The owners in a batch run on the sandbox are demonstration owners: invented people with example bank details
built from Airwallex's live schema for their country. They are never people from the register.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import httpx

from . import airwallex as awx
from . import book as bk
from . import cards
from . import corridors as co
from . import instructions as ins
from . import demo
from .countries import COUNTRIES

PLANNED = "PLANNED"                    # written, waits for the holder's approval
APPROVED = "APPROVED"                  # approved on exact terms; nothing has moved
DEPOSIT_EXPECTED = "DEPOSIT_EXPECTED"  # waits for the holder's US dollars
FUNDED = "FUNDED"                      # the deposit is booked and every payment has its share
PAYING = "PAYING"                      # conversions are made; payments are on their way
DONE = "DONE"                          # every payment is paid and the ledger has been read to zero
STOPPED = "STOPPED"                    # the approved terms no longer hold, or the money does not fit: a person must look
STATES = (PLANNED, APPROVED, DEPOSIT_EXPECTED, FUNDED, PAYING, DONE, STOPPED)

STATE_WORDS = {PLANNED: "Planned. Waits for the holder's approval", APPROVED: "Approved. Nothing has moved yet",
               DEPOSIT_EXPECTED: "Waiting for the holder's US dollars", FUNDED: "Funded. Converting",
               PAYING: "Paying", DONE: "Every payment is paid", STOPPED: "Stopped for a person to look"}
ITEM_WORDS = {awx.DEPOSIT_CONFIRMED: "Locking the rate", awx.CONVERTED: "Funded", awx.BENEFICIARY_READY: "Bank account accepted",
              awx.TRANSFER_CREATED: "Transfer created", awx.SENT: "Sent", awx.PAID: "Paid",
              awx.HELD: "Stopped: a person must agree", awx.FAILED: "Refused by the bank"}
REMAINDER_LIMIT = 100                  # cents: a pool further than this from the plan is not shared out by itself


def _clabe(first17: str) -> str:
    return first17 + str(awx.clabe_check_digit(first17))


# Demonstration owners: invented people, one for each country a batch can be run to on the sandbox. `bank` is the
# first account and `corrected` the one given after a refusal, so the two can be told apart by their last four
# digits. The values are example bank identifiers that the sandbox's validation accepts for the country.
EXAMPLE_OWNERS: dict[str, dict] = {
    "MX": {"first": "Ximena", "last": "Olvareda", "address": {"street_address": "Calle Morelos 118", "city": "Guadalajara",
                                                             "postcode": "44100", "state": "MX-JAL"},
           "bank": {"account_number": _clabe("00232001234567771")}, "corrected": {"account_number": _clabe("00232001234567823")}},
    "PH": {"first": "Dalisay", "last": "Marquendo", "address": {"street_address": "14 Mango Avenue", "city": "Cebu City",
                                                               "postcode": "6000"},
           "bank": {"account_number": "1002003004", "swift_code": "BOPIPHMM"},
           "corrected": {"account_number": "1002003091", "swift_code": "BOPIPHMM"}},
    "JP": {"first": "Kaede", "last": "Hoshimori", "address": {"street_address": "3-1-1 Shinjuku", "city": "Tokyo",
                                                             "postcode": "160-0022"},
           "bank": {"account_routing_type1": "bank_code", "account_routing_value1": "0001",
                    "account_routing_type2": "branch_code", "account_routing_value2": "001",
                    "bank_account_category": "Savings", "account_number": "1234567"},
           "corrected": {"account_number": "1234512"}},
    "GB": {"first": "Rowan", "last": "Ashcombe", "address": {"street_address": "12 Canal Street", "city": "Manchester",
                                                            "postcode": "M1 1AE"},
           "bank": {"account_routing_type1": "sort_code", "account_routing_value1": "200415", "account_number": "38290008"},
           "corrected": {"account_number": "38290024"}},
    "DE": {"first": "Jonas", "last": "Feldbrunner", "address": {"street_address": "Domstrasse 12", "city": "Koeln",
                                                               "postcode": "50667"},
           "bank": {"iban": "DE89370400440532013000"}, "corrected": {"iban": "DE75512108001245126199"}},
    "CA": {"first": "Odile", "last": "Marchetier", "address": {"street_address": "210 Portage Avenue", "city": "Winnipeg",
                                                              "postcode": "R3C 1A5", "state": "CA-MB"},
           "bank": {"account_routing_type1": "institution_number", "account_routing_value1": "003",
                    "account_routing_type2": "transit_number", "account_routing_value2": "00102",
                    "account_number": "1234567"},
           "corrected": {"account_number": "1234544"}},
    "IN": {"first": "Kavya", "last": "Indurkar", "address": {"street_address": "14 MG Road", "city": "Pune",
                                                            "postcode": "411001", "state": "IN-MH"},
           "bank": {"account_routing_type1": "bank_code", "account_routing_value1": "HDFC0000001",
                    "account_number": "50100123456789"},
           "corrected": {"account_number": "50100123456716"}},
    "AU": {"first": "Tamsin", "last": "Wirralee", "address": {"street_address": "88 Queen Street", "city": "Brisbane",
                                                             "postcode": "4000", "state": "AU-QLD"},
           "bank": {"account_routing_type1": "bsb", "account_routing_value1": "062000", "account_number": "12345678"},
           "corrected": {"account_number": "12345633"}},
    "TW": {"first": "Meilin", "last": "Zhaoqing", "address": {"street_address": "7 Zhongshan Road", "city": "Taipei",
                                                             "postcode": "100"},
           "bank": {"swift_code": "BKTWTWTP", "account_number": "0123456789012"},
           "corrected": {"account_number": "0123456789055"}},
}


def example_beneficiary(country: str, currency: str, method: str, corrected: bool = False) -> dict:
    """The request body for one demonstration owner's bank account, for Airwallex's validate and create calls."""
    owner = EXAMPLE_OWNERS[country]
    bank = {**owner["bank"], **(owner["corrected"] if corrected else {})}
    return {"beneficiary": {"type": "BANK_ACCOUNT", "entity_type": "PERSONAL", "first_name": owner["first"],
                            "last_name": owner["last"], "address": {"country_code": country, **owner["address"]},
                            "bank_details": {"account_currency": currency, "bank_country_code": country,
                                             "account_name": f"{owner['first']} {owner['last']}", **bank}},
            "transfer_methods": [method]}


def account_tail(beneficiary: dict) -> str:
    bank = (beneficiary.get("beneficiary") or {}).get("bank_details") or {}
    return str(bank.get("account_number") or bank.get("iban") or "")[-4:]


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _now() -> str:
    return awx._now()


@dataclass
class Batch:
    """One batch. Saved to `path` after every step."""
    path: str
    batch_id: str
    holder: dict                       # {"key", "name"}: whose book the batch was planned from
    rules: dict                        # the holder's standing instructions as they stood
    items: list                        # one dict per payment; see `new_batch`
    funding: dict                      # by currency: {"mode": "batch" | "each" | "none", ...}
    plan: dict                         # the planned figures the batch is compared with at the end
    state: str = PLANNED
    created_at: str = field(default_factory=_now)
    approval: dict | None = None       # {"at", "digest"}: the exact terms the holder approved
    deposit_reference: str = ""
    global_account_request_id: str = field(default_factory=awx.new_request_id)
    global_account_id: str | None = None
    deposit_id: str | None = None
    deposit_amount: str | None = None
    deposit_fee: str | None = None
    pool: str | None = None            # what Airwallex's rows say the batch holds in US dollars after its fee
    conversions: dict = field(default_factory=dict)   # by currency: request id, quote, conversion id, amounts
    ledger: list = field(default_factory=list)        # Airwallex's rows for the deposit and the conversions
    decisions: list = field(default_factory=list)
    history: list = field(default_factory=list)
    problem: str | None = None
    finished_at: str | None = None
    api_calls: int = 0                 # calls made to Airwallex while this batch ran, for the time it takes
    checked_at: str | None = None      # when every paid transfer was last read again

    def save(self) -> None:
        target = Path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(asdict(self), fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Batch":
        data = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        batch = cls(**{k: v for k, v in data.items() if k in known})
        batch.path = str(path)
        if batch.state not in STATES:
            raise ValueError(f"unknown batch state {batch.state!r} in {path}")
        return batch

    def _move(self, state: str, note: str = "") -> None:
        self.state = state
        self.history.append({"state": state, "at": _now(), "note": note})
        self.save()

    def decide(self, kind: str, rule: str, text: str, **facts: Any) -> None:
        self.decisions.append({"at": _now(), "kind": kind, "text": text, "by": "agent", "rule": rule, **facts})

    def folder(self) -> Path:
        return Path(self.path).parent

    def item_path(self, n: int) -> Path:
        return self.folder() / f"item-{n:02d}.json"

    def payout(self, n: int) -> awx.Payout | None:
        path = self.item_path(n)
        return awx.Payout.load(path) if path.exists() else None


# ---- the terms an approval covers ------------------------------------------------------------------------------

def item_terms(item: dict) -> dict:
    """What the holder approves for one payment: the person, the amount, the rail and the bank account. A payment
    for a claim in the holder's queue also carries that claim and the approval it was given."""
    terms = {"n": item["n"], "name": item["owner"]["name"], "country": item["country"], "currency": item["currency"],
             "method": item["method"], "claim_usd": item["claim_usd"], "holder_sends": item["holder_sends"],
             "account": digest(item["beneficiary"])}
    if item.get("claim_id"):
        terms["claim"] = {"id": item["claim_id"], "approval": item.get("claim_approval")}
    return terms


def batch_terms(batch: Batch) -> dict:
    return {"holder": batch.holder.get("key"), "rules": batch.rules,
            "funding": {c: f["mode"] for c, f in sorted(batch.funding.items())},
            "items": [item["first_terms"] for item in batch.items]}


def approve(batch: Batch) -> Batch:
    """The holder approves the batch as it stands. Each payment is approved with it."""
    if batch.state != PLANNED:
        raise ValueError("This batch has already been approved.")
    for item in batch.items:
        item["first_terms"] = item_terms(item)
        item["approved_digest"] = digest(item["first_terms"])
    batch.approval = {"at": _now(), "digest": digest(batch_terms(batch)), "by": "holder",
                      "deadline_at": ins.deadline_at(_now(), batch.rules)}
    batch._move(APPROVED, f"approved on exact terms: {len(batch.items)} payments, "
                          f"{sum(Decimal(i['holder_sends']) for i in batch.items):,.2f} USD to fund")
    return batch


def approval_holds(batch: Batch) -> tuple[bool, str]:
    """(whether the batch is still what the holder approved, the reason if not)."""
    if not batch.approval:
        return False, "The holder has not approved this batch."
    if digest(batch_terms(batch)) != batch.approval["digest"]:
        return False, "The batch is no longer what the holder approved: an amount, an owner, the limits or the way a currency is funded has changed."
    return True, ""


def item_approved(item: dict) -> bool:
    """True while this payment's person, amount and bank account are the ones the holder last approved."""
    return bool(item.get("approved_digest")) and digest(item_terms(item)) == item["approved_digest"]


# ---- making a batch from a plan --------------------------------------------------------------------------------

def choose_slice(plan: dict, limit: int = 9, want: tuple[str, ...] = ("MX", "PH", "JP", "GB", "DE", "CA", "IN", "AU", "TW")) -> list[dict]:
    """The corridors of a plan that a demonstration batch runs to: those the plan works in time and for which a
    demonstration owner exists, largest first. Each demonstration owner is owed the median payable claim of her
    corridor in the book; the owner in the largest corridor is owed the claim at the ninetieth percentile, so the
    batch holds one larger payment."""
    rows = [c for c in plan["corridors"] if c["country"] in want and c["country"] in EXAMPLE_OWNERS
            and c["in_time"] and c["route"] and c["median_usd"]]
    rows.sort(key=lambda c: -c["planned"]["usd"])
    out = []
    for i, c in enumerate(rows[:limit]):
        amount = c["large_usd"] if i == 0 and c.get("large_usd") else c["median_usd"]
        out.append({"country": c["country"], "name": c["name"], "currency": c["pay_currency"], "method": c["route"],
                    "claim_usd": f"{amount:.2f}", "fee": c["fee"], "scheme": c["scheme"],
                    "amount_is": "the claim at the ninetieth percentile of this corridor" if i == 0 and c.get("large_usd")
                                 else "the median claim of this corridor"})
    return out


def new_batch(folder: Path | str, holder: dict, chosen: list[dict], plan: dict, rules: dict,
              refuse: tuple[int, ...] = ()) -> Batch:
    """Write a batch for `chosen` (from `choose_slice`), with the fee rule and the funding choice of `plan`.
    `refuse` names the payments (by number) on which the sandbox is asked to stage a bank refusal. Moves no money."""
    batch_id = uuid.uuid4().hex[:12]
    line = bk._cents(rules["small_claim_usd"])
    modes = {c["currency"]: c for c in plan["funding"]["currencies"]}
    items, funding = [], {}
    for n, row in enumerate(chosen, 1):
        cents = bk._cents(row["claim_usd"])
        fee = bk._cents(row["fee"]["usd"])
        share = bk.split(cents, fee, line)
        if share["too_small"]:
            continue
        owner = EXAMPLE_OWNERS[row["country"]]
        currency, method = row["currency"], row["method"]
        mode = "none" if currency == "USD" else (modes.get(currency) or {}).get("mode") or "each"
        funding.setdefault(currency, {"mode": mode, "why": (modes.get(currency) or {}).get("mode_words") or "",
                                      "request_id": awx.new_request_id()})
        beneficiary = example_beneficiary(row["country"], currency, method)
        items.append({
            "n": n, "owner": {"name": f"{owner['first']} {owner['last']}", "city": owner["address"]["city"],
                              "country": row["country"], "country_name": row["name"], "demonstration": True},
            "country": row["country"], "currency": currency, "method": method, "scheme": row.get("scheme"),
            "claim_usd": row["claim_usd"], "amount_is": row.get("amount_is"),
            "holder_sends": f"{share['sends'] / 100:.2f}", "net_usd": f"{share['net'] / 100:.2f}",
            "fees_borne_by": share["bearer"],
            "planned": {"incoming_fee_usd": f"{share['incoming'] / 100:.2f}", "payout_fee_usd": f"{fee / 100:.2f}",
                        "payout_fee_basis": row["fee"]["basis"], "owner_gets_usd": f"{(share['net'] - fee) / 100:.2f}"},
            "beneficiary": beneficiary, "account_last4": account_tail(beneficiary),
            "what_if": "transfer_fails" if n in refuse else None,
        })
    planned_fees = sum(bk._cents(i["planned"]["incoming_fee_usd"]) + bk._cents(i["planned"]["payout_fee_usd"]) for i in items)
    batch = Batch(path=str(Path(folder) / batch_id / "batch.json"), batch_id=batch_id,
                  holder={"key": holder.get("key"), "name": holder.get("name")}, rules=dict(rules), items=items,
                  funding=funding, deposit_reference=f"KHUTLISA-BATCH-{batch_id}",
                  plan={"inputs": plan.get("inputs"), "holder_funds_usd": f"{sum(bk._cents(i['holder_sends']) for i in items) / 100:.2f}",
                        "fees_usd": f"{planned_fees / 100:.2f}", "payments": len(items),
                        "claims_usd": f"{sum(bk._cents(i['claim_usd']) for i in items) / 100:.2f}",
                        "statement": "A slice of the plan, run for demonstration owners on the Airwallex sandbox. The "
                                     "owners are invented and their bank details are examples; no real owner is paid."})
    for item in batch.items:
        item["first_terms"] = item_terms(item)
    batch.history.append({"state": PLANNED, "at": _now(), "note": "batch written; nothing has moved"})
    batch.save()
    return batch


def new_claims_batch(folder: Path | str, claims: list[dict], rules: dict | None) -> Batch:
    """A batch of claims from the holder's own queue, each already approved on its exact terms: the claimant's
    bank account, the amount on the record, and the standing instructions bound to its approval (`rules`, the
    same for every claim). Each payment's fee rule is the one a single payment of that claim would use
    (instructions.fee_plan), so the claimant receives what she would have received alone; only the deposit is
    shared. Each currency is converted inside its own transfer. Moves no money."""
    batch_id = uuid.uuid4().hex[:12]
    items, funding = [], {}
    for n, claim in enumerate(claims, 1):
        payee = claim["payee"]
        currency = payee["currency"]
        bank = payee["beneficiary"]["beneficiary"]["bank_details"]
        country = bank.get("bank_country_code") or ""
        claim_usd = str(awx.money(claim["record"]["amount"], "USD"))
        fee = ins.fee_plan(claim_usd, rules)
        sends = Decimal(fee["holder_sends"])
        incoming = (sends * ins.EXPECTED_INCOMING_FEE_RATE).quantize(Decimal("0.01"))
        payout_fee = ins.EXPECTED_PAYOUT_FEE_USD
        mode = "none" if currency == "USD" else "each"
        funding.setdefault(currency, {"mode": mode, "why": "Nothing is converted." if mode == "none" else
                                      "Converted inside each transfer, at a rate locked for that payment.",
                                      "request_id": awx.new_request_id()})
        method = (payee["beneficiary"].get("transfer_methods") or [co.LOCAL])[0]
        items.append({
            "n": n, "claim_id": claim["id"], "claim_approval": (claim.get("approval") or {}).get("terms_hash"),
            "owner": {"name": claim["claimant"]["name"], "city": "", "country": country,
                      "country_name": (COUNTRIES.get(country) or {}).get("name", country), "demonstration": demo.is_demonstration((claim.get("record") or {}).get("source"))},
            "country": country, "currency": currency, "method": method, "scheme": None,
            "claim_usd": claim_usd, "amount_is": "the amount on the record the holder approved",
            "holder_sends": f"{sends:.2f}", "net_usd": f"{sends - incoming:.2f}", "fees_borne_by": fee["bearer"],
            "planned": {"incoming_fee_usd": f"{incoming:.2f}", "payout_fee_usd": f"{payout_fee:.2f}",
                        "payout_fee_basis": "the payout fee the standing instructions expect",
                        "owner_gets_usd": f"{max(sends - incoming - payout_fee, Decimal(0)):.2f}"},
            "beneficiary": payee["beneficiary"], "account_last4": account_tail(payee["beneficiary"]),
            "what_if": None,
        })
    planned_fees = sum(bk._cents(i["planned"]["incoming_fee_usd"]) + bk._cents(i["planned"]["payout_fee_usd"]) for i in items)
    batch = Batch(path=str(Path(folder) / batch_id / "batch.json"), batch_id=batch_id,
                  holder={"key": "", "name": "the holder's approved claims"}, rules=dict(rules or {}), items=items,
                  funding=funding, deposit_reference=f"KHUTLISA-BATCH-{batch_id}",
                  plan={"inputs": None, "source": "queue",
                        "holder_funds_usd": f"{sum(bk._cents(i['holder_sends']) for i in items) / 100:.2f}",
                        "fees_usd": f"{planned_fees / 100:.2f}", "payments": len(items),
                        "claims_usd": f"{sum(bk._cents(i['claim_usd']) for i in items) / 100:.2f}",
                        "statement": "Claims from the holder's own queue, each approved on its own terms, paid "
                                     "together from one deposit on the Airwallex sandbox."})
    for item in batch.items:
        item["first_terms"] = item_terms(item)
    batch.history.append({"state": PLANNED, "at": _now(), "note": f"batch written from {len(items)} approved claims; "
                                                                 "nothing has moved"})
    batch.save()
    return batch


def claim_ids(batch: Batch) -> list[str]:
    """The claims in the holder's queue that this batch pays, if it was made from the queue."""
    return [i["claim_id"] for i in batch.items if i.get("claim_id")]


# ---- the machine -----------------------------------------------------------------------------------------------

def _rows(client: awx.AirwallexClient, source_id: str, part: str) -> list[dict]:
    return [{**row, "source_id": row.get("source_id") or source_id, "part": part} for row in client.ledger(source_id)]


def refresh_ledger(batch: Batch, client: awx.AirwallexClient) -> list[dict]:
    """Read again every row Airwallex has booked for the batch's deposit and conversions."""
    rows: list[dict] = []
    seen: set[str] = set()
    parts = [("deposit", batch.deposit_id)] + [(f"conversion to {c}", f.get("conversion_id")) for c, f in batch.conversions.items()]
    for part, source_id in parts:
        if not source_id:
            continue
        for row in _rows(client, source_id, part):
            key = row.get("id") or json.dumps(row, sort_keys=True)
            if key not in seen:
                seen.add(key)
                rows.append(row)
    rows.sort(key=lambda r: r.get("created_at") or "")
    batch.ledger = rows
    return rows


def _share_out(total: int, weights: list[int]) -> list[int]:
    """`total` split by `weights`, in whole units, so that the parts add up to `total` exactly. What rounding
    leaves over goes to the largest part."""
    whole = sum(weights)
    if whole <= 0:
        return [0 for _ in weights]
    parts = [total * w // whole for w in weights]
    parts[max(range(len(weights)), key=lambda i: weights[i])] += total - sum(parts)
    return parts


def _stop(batch: Batch, reason: str) -> Batch:
    batch.problem = reason
    batch._move(STOPPED, reason)
    return batch


def _minor_units(amount: Any, currency: str) -> int:
    return int((Decimal(str(amount)) * 10 ** bk._decimals(currency)).to_integral_value())


def _from_minor(units: int, currency: str) -> str:
    return str(awx.money(Decimal(units) / 10 ** bk._decimals(currency), currency))


def _open_item(batch: Batch, item: dict, client: awx.AirwallexClient) -> awx.Payout:
    """The payout file of one payment, made once with its share of the batch's money. A payment whose currency
    was converted for the batch starts holding that currency; one whose currency cannot be held starts holding US
    dollars with a rate locked for it; one paid in US dollars starts holding US dollars."""
    path = batch.item_path(item["n"])
    if path.exists():
        return awx.Payout.load(path)
    currency, mode = item["currency"], batch.funding[item["currency"]]["mode"]
    conv = batch.conversions.get(currency) or {}
    if item["method"] == co.LOCAL:     # what Airwallex charged on the last local payouts in this currency, if any
        fees = awx.observed_payout_fees(client, currency)
    elif mode == "batch":              # SWIFT from a held balance: the planned fee, at the mid rate
        fees = {currency: {"amount": str(Decimal(item["planned"]["payout_fee_usd"]) * Decimal(str(conv.get("mid_rate") or 1)))}}
    else:                              # SWIFT funded from US dollars: the fee of the payer option, as planned
        fees = {"USD": {"amount": item["planned"]["payout_fee_usd"]}}
    new: dict[str, Any] = {
        "usd_amount": item["holder_sends"], "target_currency": currency, "beneficiary": item["beneficiary"],
        "deposit_reference": f"KHUTLISA-{batch.batch_id}-{item['n']:02d}", "instructions": batch.rules,
        "claim_usd": item["claim_usd"], "transfer_method": item["method"],
        "swift_charge_option": co.SWIFT_OPTION if item["method"] == co.SWIFT else None,
        "what_if": item.get("what_if"), "global_account_id": batch.global_account_id,
        "deadline_at": (batch.approval or {}).get("deadline_at")}
    if mode == "batch" or currency == "USD":
        held = item["allocation_local"] if mode == "batch" else item["allocation_usd"]
        quote = {"client_rate": conv.get("client_rate") or 1, "mid_rate": conv.get("mid_rate") or conv.get("client_rate") or 1}
        new.update({"state": awx.CONVERTED, "route": awx.PAY_FROM_BALANCE, "funds": {"amount": held, "currency": currency},
                    "allocation": {"amount": held, "currency": currency, "batch": batch.batch_id},
                    "client_rate": conv.get("client_rate"), "mid_rate": conv.get("mid_rate")})
        expected = awx.estimate(awx.PAY_FROM_BALANCE, held, currency, quote, fees)["received"]["amount"]
        payout = awx.Payout(path=str(path), **new)
    else:
        usd = awx.money(item["allocation_usd"], "USD")
        new.update({"state": awx.DEPOSIT_CONFIRMED, "route": awx.PAY_WITH_QUOTE, "funds": {"amount": str(usd), "currency": "USD"},
                    "allocation": {"amount": str(usd), "currency": "USD", "batch": batch.batch_id}})
        payout = awx.Payout(path=str(path), **new)
        quote = client.create_quote("USD", currency, sell_amount=usd, validity="HR_1")
        awx._take_quote(payout, quote, usd)
        pair = str(quote.get("currency_pair") or "").upper()
        if pair == f"{currency}USD":   # quoted the other way round: keep the rate as units of the currency per dollar
            payout.client_rate = co.per_usd(quote.get("client_rate"), pair, currency)
            payout.mid_rate = co.per_usd(quote.get("mid_rate"), pair, currency)
            payout.spot_checked = True      # the machine compares raw rates, which would read this pair backwards
            quote = {**quote, "client_rate": payout.client_rate, "mid_rate": payout.mid_rate}
        expected = awx.estimate(awx.PAY_WITH_QUOTE, usd, currency, quote, fees)["received"]["amount"]
    payout.confirmed = {"plan_id": batch.batch_id, "local_amount": expected, "currency": currency,
                        "by": "the holder's approval of the batch", "at": _now()}
    payout.target_amount = expected
    payout.history.append({"state": payout.state, "at": _now(), "note": f"funded from batch {batch.batch_id}"})
    payout.save()
    item["expected_local"] = {"amount": expected, "currency": currency}
    return payout


def _prepare_item_hold(payout: awx.Payout) -> None:
    """After a refusal: work out what the replacement would bring and let the tolerance decide whether the owner
    is also asked to agree to the amount. Done once for each stop."""
    from .payouts import PayoutRunner

    hold = payout.hold
    if not hold or hold.get("plan") or hold.get("kind") not in ("transfer_failed", "transfer_returned"):
        return
    funds = payout.funds or {}
    kept = (payout.attempts[-1].get("fee_kept") or {}) if payout.attempts else {}
    fees = {kept["currency"]: {"amount": kept["amount"]}} if kept.get("currency") == funds.get("currency") else {}
    quote = {"client_rate": payout.client_rate or 1, "mid_rate": payout.mid_rate or payout.client_rate or 1}
    expected = awx.estimate(awx.PAY_FROM_BALANCE, funds.get("amount") or 0, payout.target_currency, quote, fees)["received"]
    plan = {"id": awx.new_request_id(), "expected_local": expected, "route": payout.route}
    hold["plan"] = plan
    PayoutRunner._replacement_inside_tolerance(payout, hold, plan)
    payout.save()


def advance(batch: Batch, client: awx.AirwallexClient, simulator: awx.SandboxSimulator | None = None,
            clock: Callable[[], float] | None = None) -> Batch:
    """Do the next step for this batch and save it. Safe to call again at any point, also after a restart: every
    step first looks for what it already did."""
    clock = clock or time.time
    if batch.state in (PLANNED, DONE, STOPPED):
        return batch
    if batch.state == APPROVED:
        holds, why = approval_holds(batch)
        if not holds:
            return _stop(batch, why)
        batch._move(DEPOSIT_EXPECTED, "started; waiting for the holder's US dollars")

    elif batch.state == DEPOSIT_EXPECTED:
        holds, why = approval_holds(batch)
        if not holds:
            return _stop(batch, why)
        if not batch.global_account_id:
            batch.global_account_id = client.find_or_create_usd_global_account(batch.global_account_request_id)["id"]
            batch.save()
        gross = sum(bk._cents(i["holder_sends"]) for i in batch.items)
        deposit = client.find_deposit(batch.deposit_reference, batch.global_account_id)
        if deposit is None and simulator is not None:
            simulator.deposit(batch.global_account_id, Decimal(gross) / 100, batch.deposit_reference)
            deposit = client.find_deposit(batch.deposit_reference, batch.global_account_id)
        if deposit is None:
            return batch
        batch.deposit_id = deposit.get("id")
        if deposit.get("status") in ("REJECTED", "REVERSED"):
            return _stop(batch, f"The deposit was {deposit.get('status')} at Airwallex.")
        if deposit.get("status") != "SETTLED":
            batch.save()
            return batch
        rows = refresh_ledger(batch, client)
        mine = [r for r in rows if r.get("source_id") == batch.deposit_id]
        if not any(r.get("transaction_type") == "DEPOSIT" for r in mine):
            batch.save()        # the fee is booked with the deposit's own row, a moment after it first shows up
            return batch
        fee = -sum((awx._dec(r.get("amount")) for r in mine if r.get("transaction_type") == "FEE"), Decimal(0))
        pool = awx.claim_balance(rows, "USD")
        batch.deposit_amount = str(awx.money(deposit.get("amount") or 0, "USD"))
        batch.deposit_fee = str(awx.money(fee, "USD"))
        batch.pool = str(awx.money(pool, "USD"))
        if bk._cents(batch.deposit_amount) != gross:
            return _stop(batch, f"{batch.deposit_amount} USD arrived and {gross / 100:,.2f} USD was approved. Nothing "
                                "was converted or sent.")
        # Every payment gets the dollars the plan gave it. Airwallex takes its fee once on the whole deposit and the
        # plan worked it out payment by payment, so a few cents can be left over or short: they go to the largest.
        planned = [bk._cents(i["net_usd"]) for i in batch.items]
        over = bk._cents(batch.pool) - sum(planned)
        if abs(over) > REMAINDER_LIMIT:
            return _stop(batch, f"After Airwallex's fee the batch holds {batch.pool} USD and the plan needs "
                                f"{sum(planned) / 100:,.2f} USD. Nothing was converted or sent.")
        largest = max(range(len(planned)), key=lambda i: planned[i])
        for i, item in enumerate(batch.items):
            item["allocation_usd"] = f"{(planned[i] + (over if i == largest else 0)) / 100:.2f}"
        if over:
            batch.decide("remainder", "safety",
                         f"Airwallex booked its fee on the whole deposit as {batch.deposit_fee} USD. Payment by payment "
                         f"the plan expected {abs(over) / 100:.2f} USD {'less' if over > 0 else 'more'}. The difference "
                         f"went to payment {batch.items[largest]['n']}, the largest, so every dollar the batch holds is "
                         "given to a payment and none is left over.", cents=over)
        batch._move(FUNDED, f"deposit {batch.deposit_id} SETTLED; Airwallex's fee {batch.deposit_fee} USD; "
                            f"{batch.pool} USD shared out")

    elif batch.state == FUNDED:
        holds, why = approval_holds(batch)
        if not holds:
            return _stop(batch, why)
        for currency, how in batch.funding.items():
            if how["mode"] != "batch" or currency in batch.conversions:
                continue
            mine = [i for i in batch.items if i["currency"] == currency]
            sell = sum(bk._cents(i["allocation_usd"]) for i in mine)
            done = client.find_conversion(how["request_id"])        # ask first: a restart must not convert twice
            quote = None
            if done is None:
                quote = client.create_quote("USD", currency, sell_amount=Decimal(sell) / 100, validity="MIN_1")
                try:
                    done = client.create_conversion(how["request_id"], "USD", currency, sell_amount=Decimal(sell) / 100,
                                                    quote_id=quote["quote_id"])
                except awx.AirwallexError as err:
                    if not err.is_duplicate_request:
                        raise
                    done = client.find_conversion(how["request_id"])
                    if done is None:
                        raise
            bought = awx.money(done["buy_amount"], currency)
            parts = _share_out(_minor_units(bought, currency), [bk._cents(i["allocation_usd"]) for i in mine])
            for item, part in zip(mine, parts):
                item["allocation_local"] = _from_minor(part, currency)
            # The rate as units of the currency for one US dollar, whichever way round Airwallex quotes the pair.
            rate = float((Decimal(bought) / (Decimal(sell) / 100)).quantize(Decimal("0.00000001"))) if sell else None
            mid = co.per_usd((quote or {}).get("mid_rate"), (quote or {}).get("currency_pair"), currency) or rate
            batch.conversions[currency] = {
                "request_id": how["request_id"], "conversion_id": done.get("conversion_id") or done.get("id"),
                "sell_usd": f"{sell / 100:.2f}", "buy": str(bought), "client_rate": rate, "mid_rate": mid,
                "quoted_rate": done.get("client_rate"), "status": done.get("status"), "payments": len(mine), "at": _now()}
            batch.decide("converted_once", "route",
                         f"{sell / 100:,.2f} USD was converted once into {bought:,.2f} {currency}, at {rate} {currency} for "
                         f"one US dollar, for {len(mine)} payment{'s' if len(mine) != 1 else ''}, and shared out in "
                         "proportion to each payment's dollars.", currency=currency)
            batch.save()        # one conversion a step, saved before the next
            return batch
        refresh_ledger(batch, client)
        for item in batch.items:
            _open_item(batch, item, client)
            batch.save()
        batch._move(PAYING, f"{len(batch.conversions)} conversion{'s' if len(batch.conversions) != 1 else ''} booked; "
                            f"{len(batch.items)} payments opened")

    elif batch.state == PAYING:
        waiting = False
        for item in batch.items:
            payout = batch.payout(item["n"])
            if payout is None:
                payout = _open_item(batch, item, client)
            if payout.state == awx.PAID:
                continue
            waiting = True
            if payout.hold and payout.hold.get("needs"):
                _prepare_item_hold(payout)
                continue
            if payout.state in awx.STOPPED:
                continue
            if not item_approved(item):       # the terms changed after the approval: nothing is sent on them
                continue
            awx.advance(payout, client, simulator, clock)
            if payout.hold:
                _prepare_item_hold(payout)
        if not waiting:
            refresh_ledger(batch, client)
            done = reconcile(batch)
            batch.finished_at = _now()
            batch.checked_at = _now()
            batch._move(DONE, "every payment is paid; Airwallex's rows add up to zero in every currency"
                        if done["balanced"] else "every payment is paid; the ledger does not add up to zero yet")
        else:
            batch.save()
    return batch


def run(batch: Batch, client: awx.AirwallexClient, simulator: awx.SandboxSimulator | None = None,
        max_steps: int = 400) -> Batch:
    """Advance until the batch is done, stopped, or waiting for a person. Used by the tests and the run script."""
    for _ in range(max_steps):
        before = json.dumps(asdict(batch), sort_keys=True) + "".join(
            (p.state + str(len(p.history))) for p in (batch.payout(i["n"]) for i in batch.items) if p)
        advance(batch, client, simulator)
        after = json.dumps(asdict(batch), sort_keys=True) + "".join(
            (p.state + str(len(p.history))) for p in (batch.payout(i["n"]) for i in batch.items) if p)
        if batch.state in (DONE, STOPPED, PLANNED) or before == after:
            break
    return batch


# ---- what people do on a payment that stopped ------------------------------------------------------------------

def _item(batch: Batch, n: int) -> dict:
    for item in batch.items:
        if item["n"] == n:
            return item
    raise ValueError("There is no such payment in this batch.")


def give_corrected_account(batch: Batch, n: int, beneficiary: dict | None = None) -> awx.Payout:
    """The owner gives a bank account again after a refusal. For a demonstration owner the second example account
    is used. The payment then waits for the holder, because a different account is never inside the limits."""
    item = _item(batch, n)
    payout = batch.payout(n)
    if payout is None or not payout.hold or "bank_details" not in payout.hold.get("needs", []):
        raise ValueError("This payment is not waiting for a bank account.")
    new = beneficiary or example_beneficiary(item["country"], item["currency"], item["method"], corrected=True)
    if digest(new) == digest(item["beneficiary"]):
        raise ValueError("That is the account the bank has just refused.")
    item["beneficiary"] = new
    item["account_last4"] = account_tail(new)
    item["refused_last4"] = (payout.attempts[-1].get("account_last4") if payout.attempts else None)
    payout.beneficiary = new
    payout.agreed("bank_details")
    batch.history.append({"state": batch.state, "at": _now(), "note": f"payment {n}: the owner gave another bank account; "
                                                                     "it waits for the holder's approval"})
    batch.save()
    return payout


def approve_item(batch: Batch, n: int) -> awx.Payout:
    """The holder approves a payment's corrected bank account."""
    item = _item(batch, n)
    payout = batch.payout(n)
    if payout is None or not payout.hold or "payer" not in payout.hold.get("needs", []):
        raise ValueError("This payment is not waiting for the holder.")
    if "bank_details" in payout.hold.get("needs", []):
        raise ValueError("The owner has not given another bank account yet.")
    item["approved_digest"] = digest(item_terms(item))
    payout.agreed("payer")
    batch.history.append({"state": batch.state, "at": _now(), "note": f"payment {n}: the holder approved the corrected "
                                                                     f"account ending {item['account_last4']}"})
    batch.save()
    return payout


def owner_agrees(batch: Batch, n: int) -> awx.Payout:
    """The owner agrees to the smaller amount of a replacement that is outside the tolerance."""
    payout = batch.payout(n)
    if payout is None or not payout.hold or "claimant" not in payout.hold.get("needs", []):
        raise ValueError("This payment is not waiting for the owner to agree to an amount.")
    if payout.hold["needs"] != ["claimant"]:
        raise ValueError("The corrected account and the holder's approval come first.")
    plan = payout.hold.get("plan") or {}
    payout.confirmed = {"plan_id": plan.get("id"), "local_amount": (plan.get("expected_local") or {}).get("amount"),
                        "currency": payout.target_currency, "by": "the owner", "at": _now()}
    payout.agreed("claimant")
    batch.history.append({"state": batch.state, "at": _now(), "note": f"payment {n}: the owner agreed to the new amount"})
    batch.save()
    return payout


# ---- the whole batch against Airwallex's ledger ----------------------------------------------------------------

def all_rows(batch: Batch) -> list[dict]:
    rows = list(batch.ledger)
    seen = {r.get("id") for r in rows}
    for item in batch.items:
        payout = batch.payout(item["n"])
        for row in (payout.ledger if payout else []):
            if row.get("id") not in seen:
                seen.add(row.get("id"))
                rows.append({**row, "part": f"payment {item['n']}"})
    rows.sort(key=lambda r: r.get("created_at") or "")
    return rows


def reconcile(batch: Batch) -> dict:
    """Every row Airwallex booked for the batch, added up by currency. The batch balances when every payment is
    paid and every currency adds up to zero: all the money that came in went to a fee Airwallex booked or to an
    owner."""
    rows = all_rows(batch)
    sums: dict[str, dict] = {}
    for row in rows:
        amount = awx._dec(row.get("amount"))
        slot = sums.setdefault(row.get("currency"), {"in": Decimal(0), "out": Decimal(0)})
        slot["in" if amount > 0 else "out"] += amount
    lines = [{"currency": cur, "came_in": str(awx.money(s["in"], cur)), "went_out": str(awx.money(-s["out"], cur)),
              "left": str(awx.money(s["in"] + s["out"], cur))} for cur, s in sorted(sums.items())]
    payouts = [batch.payout(i["n"]) for i in batch.items]
    all_paid = bool(payouts) and all(p is not None and p.state == awx.PAID for p in payouts)
    return {"rows": len(rows), "sums": lines, "all_paid": all_paid,
            "balanced": all_paid and all(Decimal(l["left"]) == 0 for l in lines)}


def costs(batch: Batch) -> dict:
    """The planned cost beside what Airwallex booked. Fees charged in another currency are also given in US
    dollars at the mid rate of the payment's own quote, and listed in their own currency."""
    planned_in = sum(bk._cents(i["planned"]["incoming_fee_usd"]) for i in batch.items)
    planned_out = sum(bk._cents(i["planned"]["payout_fee_usd"]) for i in batch.items)
    booked: dict[str, Decimal] = {}
    usd = Decimal(0)
    transfers = 0
    for item in batch.items:
        payout = batch.payout(item["n"])
        if payout is None:
            continue
        fees = [a.get("fee_kept") for a in payout.attempts if a.get("fee_kept")] + ([payout.transfer_fee] if payout.transfer_fee else [])
        for fee in fees:
            transfers += 1
            amount, currency = awx._dec(fee.get("amount")), fee.get("currency")
            booked[currency] = booked.get(currency, Decimal(0)) + amount
            mid = Decimal(str(payout.mid_rate or payout.client_rate or 1)) if currency != "USD" else Decimal(1)
            usd += amount / mid if mid else Decimal(0)
    actual_in = awx._dec(batch.deposit_fee)
    planned = planned_in + planned_out
    actual = awx.money(actual_in + usd, "USD")
    return {"planned": {"incoming_usd": f"{planned_in / 100:.2f}", "payout_usd": f"{planned_out / 100:.2f}",
                        "usd": f"{planned / 100:.2f}", "transfers": len(batch.items)},
            "actual": {"incoming_usd": str(awx.money(actual_in, "USD")), "payout_usd": str(awx.money(usd, "USD")),
                       "usd": str(actual), "transfers": transfers,
                       "payout_fees": [{"currency": c, "amount": str(awx.money(a, c))} for c, a in sorted(booked.items())]},
            "difference_usd": str(awx.money(actual - Decimal(planned) / 100, "USD")),
            "note": "A refused transfer keeps its payout fee and the replacement is charged again, so a batch with a "
                    "refusal costs one more payout fee than planned for each."}


def view(batch: Batch, running: bool = False, problem: str | None = None) -> dict:
    """The batch as the "Batch" screen shows it. Bank account numbers are cut to their last four digits."""
    rows = []
    for item in batch.items:
        payout = batch.payout(item["n"])
        p = asdict(payout) if payout else None
        hold = (payout.hold or {}) if payout else {}
        needs = list(hold.get("needs") or [])
        state = payout.state if payout else None
        words = ITEM_WORDS.get(state, "Waiting for the batch to be funded") if payout else (
            "Approved" if batch.state != PLANNED else "Planned")
        if needs:
            words = ("Refused by the bank: waiting for the owner's corrected account" if "bank_details" in needs else
                     "Waiting for the holder to approve the corrected account" if "payer" in needs else
                     "Outside the tolerance: waiting for the owner to agree to the amount")
        elif payout and payout.attempts and state != awx.PAID:
            words = "Replacement on its way"
        attempts = []
        for a in (payout.attempts if payout else []):
            attempts.append({"transfer_id": a.get("transfer_id"), "status": a.get("status"), "reason": a.get("reason"),
                             "fate": a.get("fate"), "account_last4": a.get("account_last4"), "came_back": a.get("came_back"),
                             "fee_kept": a.get("fee_kept"), "outcome": a.get("outcome"), "at": a.get("at")})
        rows.append({
            "n": item["n"], "claim_id": item.get("claim_id"), "owner": item["owner"], "country": item["country"], "currency": item["currency"],
            "method": item["method"], "scheme": item.get("scheme"), "claim_usd": item["claim_usd"],
            "amount_is": item.get("amount_is"), "holder_sends": item["holder_sends"],
            "fees_borne_by": item["fees_borne_by"], "planned": item["planned"], "funded_by": batch.funding[item["currency"]]["mode"],
            "allocation_usd": item.get("allocation_usd"), "allocation_local": item.get("allocation_local"),
            "expected_local": item.get("expected_local") or ((payout.confirmed or {}) if payout else {}).get("local_amount") and
                              {"amount": payout.confirmed["local_amount"], "currency": item["currency"]},
            "account_last4": item["account_last4"], "refused_last4": item.get("refused_last4"),
            "staged": item.get("what_if"), "state": state, "state_words": words, "needs": needs,
            "transfer_id": payout.transfer_id if payout else None,
            "paid": {"amount": payout.target_amount, "currency": item["currency"]} if payout and state == awx.PAID else None,
            "fee": payout.transfer_fee if payout else None, "attempts": attempts,
            "cards": [cards.refusal_card(a, p) for a in (p["attempts"] if p else [])],
            "approved": item_approved(item) if batch.approval else False,
            "decisions": [d for d in (payout.decisions if payout else []) if d.get("by") == "agent"],
        })
    paid = sum(1 for r in rows if r["state"] == awx.PAID)
    waiting = [r["n"] for r in rows if r["needs"]]
    return {
        "batch_id": batch.batch_id, "holder": batch.holder, "state": batch.state, "state_words": STATE_WORDS[batch.state],
        "created_at": batch.created_at, "finished_at": batch.finished_at, "checked_at": batch.checked_at,
        "statement": batch.plan.get("statement"), "plan": batch.plan, "rules": batch.rules,
        "approval": {"at": batch.approval["at"], "holds": approval_holds(batch)[0]} if batch.approval else None,
        "deposit": {"reference": batch.deposit_reference, "id": batch.deposit_id, "amount": batch.deposit_amount,
                    "fee": batch.deposit_fee, "pool": batch.pool},
        "funding": [{"currency": c, "mode": f["mode"], "why": f.get("why"), **{k: v for k, v in (batch.conversions.get(c) or {}).items()
                                                                              if k != "request_id"}} for c, f in batch.funding.items()],
        "items": rows, "paid": paid, "payments": len(rows), "waiting_for_people": waiting,
        "running": running, "problem": problem or batch.problem,
        "reconciliation": {**reconcile(batch), "lines": [
            {"id": r.get("id"), "type": r.get("transaction_type"), "amount": str(r.get("amount")), "currency": r.get("currency"),
             "part": r.get("part"), "status": r.get("status"), "at": r.get("created_at")} for r in all_rows(batch)]},
        "costs": costs(batch), "decisions": batch.decisions, "history": batch.history, "api_calls": batch.api_calls,
    }


# ---- running batches in the background -------------------------------------------------------------------------

class BatchRunner:
    """One background thread for each batch that has something to do."""

    def __init__(self, folder: Path | str, factory, *, pause: float = 1.0, max_idle: int = 240, max_errors: int = 3):
        self.folder = Path(folder)
        self.factory = factory
        self.pause = pause
        self.max_idle = max_idle
        self.max_errors = max_errors
        self.problems: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self.lock = threading.RLock()       # held while a person's action or a step changes a batch
        self._stop = threading.Event()
        # `checks` are called with a batch before each step that comes before money leaves the holder; one that
        # returns a sentence stops the batch with it. `after` are called with the batch after every step. The
        # holder's routes (book_api.py) use them for batches made of claims in the queue.
        self.checks: list = []
        self.after: list = []

    def path(self, batch_id: str) -> Path:
        if not batch_id.isalnum() or len(batch_id) > 32:
            raise ValueError("There is no such batch.")
        return self.folder / batch_id / "batch.json"

    def load(self, batch_id: str) -> Batch:
        path = self.path(batch_id)
        if not path.exists():
            raise ValueError("There is no such batch.")
        return Batch.load(path)

    def all(self) -> list[Batch]:
        if not self.folder.is_dir():
            return []
        out = []
        for path in sorted(self.folder.glob("*/batch.json")):
            try:
                out.append(Batch.load(path))
            except (ValueError, OSError):
                continue
        return sorted(out, key=lambda b: b.created_at, reverse=True)

    def running(self, batch_id: str) -> bool:
        thread = self._threads.get(batch_id)
        return bool(thread and thread.is_alive())

    def start(self, batch_id: str) -> None:
        with self._lock:
            if self.running(batch_id) or self._stop.is_set():
                return
            self.problems.pop(batch_id, None)
            thread = threading.Thread(target=self._work, args=(batch_id,), name=f"batch-{batch_id}", daemon=True)
            self._threads[batch_id] = thread
            thread.start()

    def resume_all(self) -> list[str]:
        """After a restart: pick up every batch that was approved and is not finished. Never makes one."""
        resumed = []
        for batch in self.all():
            if batch.state in (APPROVED, DEPOSIT_EXPECTED, FUNDED, PAYING):
                self.start(batch.batch_id)
                resumed.append(batch.batch_id)
        return resumed

    def stop(self, wait: float = 5.0) -> None:
        self._stop.set()
        for thread in list(self._threads.values()):
            thread.join(wait)

    def join(self, batch_id: str, timeout: float = 20.0) -> None:
        ends = time.time() + timeout
        while time.time() < ends:
            thread = self._threads.get(batch_id)
            if thread is None or not thread.is_alive():
                return
            thread.join(0.05)

    @staticmethod
    def _mark(batch: Batch) -> str:
        parts = [batch.state, str(len(batch.history)), str(len(batch.conversions))]
        for item in batch.items:
            payout = batch.payout(item["n"])
            parts.append(f"{payout.state}:{len(payout.history)}:{len((payout.hold or {}).get('needs') or [])}" if payout else "-")
        return "|".join(parts)

    def _work(self, batch_id: str) -> None:
        client = None
        try:
            client, simulator = self.factory()
            idle = errors = 0
            while not self._stop.is_set():
                with self.lock:
                    batch = self.load(batch_id)
                    if batch.state in (PLANNED, DONE, STOPPED):
                        break
                    before = self._mark(batch)
                    if batch.state in (APPROVED, DEPOSIT_EXPECTED, FUNDED):
                        reason = next((r for r in (check(batch) for check in self.checks) if r), None)
                        if reason:
                            _stop(batch, reason)
                            for hook in self.after:
                                hook(batch)
                            break
                    calls = getattr(client, "calls", 0)
                    try:
                        advance(batch, client, simulator)
                        errors = 0
                    except (awx.AirwallexError, httpx.HTTPError) as err:
                        errors += 1
                        if errors >= self.max_errors:
                            raise err
                    batch = self.load(batch_id)
                    for hook in self.after:
                        hook(batch)
                    batch.api_calls += getattr(client, "calls", 0) - calls
                    batch.save()
                    after = self._mark(batch)
                    people = batch.state == PAYING and all(
                        (p is None) or p.state == awx.PAID or (p.hold and p.hold.get("needs") and p.hold.get("plan"))
                        or (p.state in awx.STOPPED and not p.hold)
                        for p in (batch.payout(i["n"]) for i in batch.items)) and after == before
                if people:
                    break            # every payment left is waiting for a person: a person's action starts it again
                if after == before:
                    idle += 1
                    if idle >= self.max_idle:
                        self.problems[batch_id] = ("The batch is still waiting on Airwallex. Starting it again carries "
                                                   "on from where it stopped.")
                        break
                    self._stop.wait(self.pause)
                else:
                    idle = 0
        except Exception as err:   # the thread must never die silently: the screen shows what happened
            from .payouts import explain

            self.problems[batch_id] = explain(err)
        finally:
            if client is not None:
                client.close()
