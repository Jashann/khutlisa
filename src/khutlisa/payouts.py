"""Runs each claim's payout in a background thread, writes the payout plan, words what changed when something
does, and describes it all for the payment screen.

The money movement itself is `airwallex.Payout` and `airwallex.advance`. This module decides when to call them.
The rules that matter: a payout file is created once per claim and never replaced, so a restart of the server
picks the same payout up again with the same request ids, and Airwallex refuses to act twice on one id. Every
amount, limit and choice of route is worked out in code. A language model is asked only to put a change into one
or two plain sentences, and a fixed sentence is used whenever it is not available or says anything the figures do
not support.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Callable

import httpx

from . import airwallex as awx
from . import cards
from . import claims as cl
from . import instructions as ins
from . import llm

# How the money's journey is told on the payment screen, in order.
JOURNEY = (
    ("arrived", "The holder's US dollars arrive in Khutlisa's Airwallex US dollar account, referenced to this "
                "claim"),
    ("fee", "Airwallex books its incoming fee"),
    ("rate_locked", "Exchange rate locked"),
    ("converted", "In your currency"),
    ("sent", "Sent through the local bank network"),
    ("paid", "Paid into your bank account"),
)

# Where each payout currency lands, in words for the claim's history.
PLACES = {"MXN": "Mexico, in Mexican pesos", "PHP": "the Philippines, in Philippine pesos"}
ROUTE_NAMES = {awx.PAY_WITH_QUOTE: "Pay with a locked quote", awx.CONVERT_THEN_PAY: "Convert, then pay",
               awx.PAY_FROM_BALANCE: "Pay from the balance already held"}
WHAT_IF_LABELS = {
    "short_deposit": "The holder sends less than it approved",
    "transfer_fails": "The receiving bank refuses the transfer",
    "transfer_returned": "The receiving bank returns the money after it was paid",
    "rate_lock_expires": "The rate lock runs out before the money is converted",
}
NEEDS_WORDS = {"bank_details": "the claimant corrects the bank details",
               "payer": "the holder approves the new terms", "claimant": "the claimant agrees to the new amount"}

# What the machine may decide by itself, as a heading for each line of its report, and the instruction it rests on.
DECISION_TITLES = {
    "fee_rule": "Applied the fee rule",
    "route_chosen": "Chose the route",
    "better_rate": "Used a better rate than the one locked",
    "kept_lock": "Kept the locked rate",
    "requoted": "Locked a new rate and carried on",
    "short_within_tolerance": "Carried on although slightly less arrived",
    "route_changed": "Changed the route, because the money came back",
    "replacement_within_tolerance": "Did not ask the claimant to agree again",
    "replacement_cleared": "Made sure the first transfer could no longer pay",
}
RULE_NAMES = {"tolerance": "Your amount tolerance", "fees": "Your fee rule", "route": "Your route rule",
              "deadline": "Your deadline", "safety": "A fixed rule, not yours to switch off"}

# Stops that another way of funding adds (metal.py): how each is put into a sentence, and why it withdraws the
# holder's approval. Empty unless such a module fills them in.
EXPLAINERS: dict[str, Callable[[dict, dict | None], str]] = {}
VOID_REASONS: dict[str, str] = {}

NO_CREDENTIALS = ("The Airwallex sandbox keys are not set up on this server, so no payment can run. Add "
                  "AWX_CLIENT_ID and AWX_API_KEY to the environment or to the file .airwallex_sandbox in the home "
                  "folder, then start the server again.")

Factory = Callable[[], tuple[awx.AirwallexClient, awx.SandboxSimulator | None]]


def sandbox_factory() -> tuple[awx.AirwallexClient, awx.SandboxSimulator]:
    """A client for the Airwallex sandbox with the sandbox simulator. Raises CredentialsError without keys."""
    client = awx.AirwallexClient(*awx.load_credentials())
    return client, awx.SandboxSimulator(client)


def explain(err: Exception) -> str:
    """A sentence for the screen. Built only from Airwallex's own error code and message, never from a request."""
    if isinstance(err, awx.CredentialsError):
        return NO_CREDENTIALS
    if isinstance(err, awx.AirwallexError):
        return f"Airwallex refused a step ({err.code or err.status}): {(err.message or 'no reason given')[:300]}"
    if isinstance(err, ValueError):
        return str(err)[:300]
    return f"The payment stopped on an unexpected problem ({type(err).__name__}). Starting it again carries on from the same step."


# ---- the plan --------------------------------------------------------------------------------------------------

def _amount(value, currency: str) -> dict:
    return {"amount": str(awx.money(value, currency)), "currency": currency}


def _figure(a: dict | None) -> str:
    """'7,217.78 PHP' from {"amount", "currency"}."""
    if not a or a.get("amount") in (None, ""):
        return "an unknown amount"
    return f"{Decimal(str(a['amount'])):,.2f} {a['currency']}"


def _live_quote(payout: awx.Payout, sell: Decimal) -> dict | None:
    """The quote the payout already holds, if it was made for this amount and has not run out."""
    if not payout.quote_id or payout.quote_sell is None or awx.money(payout.quote_sell, "USD") != awx.money(sell, "USD"):
        return None
    if awx._quote_expired(payout, time.time):
        return None
    return {"quote_id": payout.quote_id, "client_rate": payout.client_rate, "mid_rate": payout.mid_rate,
            "valid_to_at": payout.quote_valid_to, "valid_from_at": None}


def make_plan(payout: awx.Payout, client: awx.AirwallexClient, *, simulator_ready: bool = False,
              fresh: bool = False) -> dict:
    """The written payout plan: the route and why, each fee, the rate and how long it is locked, the amount the
    person should receive, and what will be done if things change. It takes one quote from Airwallex and moves no
    money. Figures Airwallex has already booked are used as they are; the rest are marked as expected."""
    currency = payout.target_currency
    funds = payout.funds
    arrived = payout.deposit_amount is not None
    rules = payout.instructions
    compared = None
    fee_rule = ins.fee_plan(payout.claim_usd or payout.usd_amount, rules) if rules else None
    comparing = bool(rules) and rules.get("route_rule") == "most_to_claimant"
    seen_fees = awx.observed_payout_fees(client, currency) if comparing else {}
    if funds and funds.get("currency") == currency:        # the money came back in the local currency
        route, why = awx.choose_route(currency, currency)
        held = Decimal(funds["amount"])
        quote = client.create_quote("USD", currency, sell_amount=awx.EXPECTED_PAYOUT_FEE_USD, validity="HR_1")
        outcome = awx.estimate(route, held, currency, quote, seen_fees)
        lines = [{"label": "Held for this claim after the earlier transfer came back", **_amount(held, currency),
                  "basis": "booked by Airwallex"}]
        incoming = None
        to_send = _amount(held, currency)
        rate = None
    else:
        route, why = awx.choose_route(currency)
        gross = Decimal(payout.deposit_amount if arrived else payout.usd_amount)
        fee_in = Decimal(payout.deposit_fee) if arrived else awx.money(gross * awx.EXPECTED_INCOMING_FEE_RATE, "USD")
        net = Decimal(funds["amount"]) if arrived and funds else gross - fee_in
        validity = "MIN_1" if payout.what_if == "rate_lock_expires" and not payout.what_if_done else "HR_1"
        quote = None if fresh else _live_quote(payout, net)
        if quote is None:   # otherwise the lock the machine already took stands, and the plan shows that one
            quote = client.create_quote("USD", currency, sell_amount=net, validity=validity)
            awx._take_quote(payout, quote, awx.money(net, "USD"), validity)
            payout.spot_checked = False
        validity = payout.quote_validity
        started = payout.state not in (awx.PLANNED,) and payout.route in (awx.PAY_WITH_QUOTE, awx.CONVERT_THEN_PAY)
        if comparing and not started:
            compared = awx.compare_routes(currency, net, quote, seen_fees)
            route, why = _route_choice(compared, currency, quote)
        elif started:           # the money is already on its way down one route; a new plan does not switch it
            route = payout.route
            if rules:
                why = (f"{ROUTE_NAMES[route]} was chosen when the first plan was written, and the money is already "
                       "on its way down that route. A plan that is worked out again does not switch it.")
        outcome = awx.estimate(route, net, currency, quote, seen_fees)
        incoming = {**_amount(fee_in, "USD"), "basis": "booked by Airwallex" if arrived else
                    "expected: 0.3 percent, what Airwallex has charged on every deposit so far"}
        sends = ("the claim plus Airwallex's expected fees, under the holder's fee rule"
                 if fee_rule and fee_rule["bearer"] == "holder" else "the amount approved")
        lines = [{"label": "Arrived from the holder" if arrived else "The holder sends",
                  **_amount(gross, "USD"), "basis": "booked by Airwallex" if arrived else sends}]
        to_send = _amount(net, "USD")
        rate = {"pair": f"USD to {currency}", "client_rate": quote.get("client_rate"),
                "quote_id": quote.get("quote_id"), "locked_from": quote.get("valid_from_at"),
                "locked_until": quote.get("valid_to_at"),
                "locked_for": {"MIN_1": "1 minute", "MIN_15": "15 minutes", "HR_1": "1 hour"}.get(validity, validity)}
    payout.route = route
    received = outcome["received"]
    tolerance = rules["tolerance_percent"] if rules else f"{awx.RATE_TOLERANCE * 100:.1f}".rstrip("0").rstrip(".")
    fee = outcome["payout_fee"]
    if rules:
        changes = [
            f"If less arrives than was approved, and it is within {tolerance} percent, the payment carries on and "
            "the shortfall is noted. If it is further off, nothing is converted or sent: the plan is worked out "
            "again, the holder is asked to approve the new amount, and you are asked to agree to it.",
            f"If a new rate has to be locked (the lock ran out, or the amount to convert changed) and you would "
            f"still receive no less than {tolerance} percent below the amount in this plan, the payment carries on "
            "and the change is noted. If it would be worse, the payment stops and you are asked.",
            "If the receiving bank refuses the transfer, or returns it after it was paid, the money that comes "
            "back is held for this claim. You correct the bank details and the holder approves the new account. "
            f"You are asked to agree again only if the replacement would bring more than {tolerance} percent less "
            "than this plan. One replacement transfer is sent. The first transfer and its replacement can never "
            "both pay.",
            "If the holder's deadline passes before the money is sent, the payment stops and goes back to the "
            "holder.",
            "At no point is more sent than arrived for this claim, and no claim is paid twice.",
        ]
    else:
        changes = [
            "If less arrives than was approved, nothing is converted or sent. The plan is worked out again on "
            "what arrived, the holder is asked to approve the new amount, and you are asked to agree to it.",
            f"If the rate lock runs out before the money is converted, a new rate is locked and you are asked to "
            f"agree to the new amount. If a new quote is needed for any other reason and the amount stays within "
            f"{tolerance} percent of the one you agreed to, the payment carries on and the change is noted.",
            "If the receiving bank refuses the transfer, or returns it after it was paid, the money that comes "
            "back is held for this claim. You correct the bank details, the holder approves the new destination, "
            "you agree to the new amount, and one replacement transfer is sent. The first transfer and its "
            "replacement can never both pay.",
            "At no point is more sent than arrived for this claim, and no claim is paid twice.",
        ]
    plan = {
        "id": awx.new_request_id(), "made_at": cl.now(), "replacement": bool(payout.attempts),
        "route": route, "route_name": ROUTE_NAMES[route], "route_reason": why,
        "routes_compared": compared and [{**r, "route_name": ROUTE_NAMES[r["route"]]} for r in compared],
        "lines": lines, "incoming_fee": incoming, "to_send": to_send,
        "payout_fee": {"amount": fee["amount"], "currency": fee["currency"],
                       "basis": ("what Airwallex charged on the last payout made this way" if fee.get("observed") else
                                 "expected: what Airwallex has charged on every local payout so far")
                                + ". It is taken out of the amount sent, never added on top"},
        "rate": rate, "expected_local": received, "tolerance_percent": tolerance,
        "fee_rule": fee_rule, "deadline_at": payout.deadline_at,
        "instructions": rules and {"rules": rules, "in_words": ins.in_words(rules)},
        "what_if": payout.what_if if simulator_ready else None,
        "if_things_change": changes,
    }
    if rules and not payout.attempts and payout.state == awx.PLANNED:
        # What the machine settled by itself while writing the plan. A plan asked for again replaces these lines.
        payout.decisions = [d for d in payout.decisions if d.get("kind") not in ("fee_rule", "route_chosen")]
        payout.decide("fee_rule", "fees", " ".join(fee_rule["arithmetic"]), plan_id=plan["id"],
                      bearer=fee_rule["bearer"], holder_sends=fee_rule["holder_sends"])
        payout.decide("route_chosen", "route", why, plan_id=plan["id"], route=route)
    payout.plan = plan
    return plan


def _route_choice(compared: list[dict], currency: str, quote: dict) -> tuple[str, str]:
    """(the chosen route, why, in sentences built from the comparison's own figures)."""
    chosen = next(r for r in compared if r["chosen"])
    others = [r for r in compared if not r["chosen"]]
    rate = quote.get("client_rate")
    said = (f"{ROUTE_NAMES[chosen['route']]} would deliver {_figure(chosen['would_receive'])} at Airwallex's quote of "
            f"{rate}, after a payout fee of {_figure(chosen['payout_fee'])}.")
    for other in others:
        if not other["available"]:
            said += f" {ROUTE_NAMES[other['route']]} is not open for this currency: {other['why_not']}"
            continue
        more = Decimal(chosen["would_receive"]["amount"]) - Decimal(other["would_receive"]["amount"])
        if more > 0:
            said += (f" {ROUTE_NAMES[other['route']]} would deliver {_figure(other['would_receive'])}, after a payout "
                     f"fee of {_figure(other['payout_fee'])}. The first was chosen: {more:,.2f} {currency} more "
                     "reaches the claimant.")
        else:
            said += (f" {ROUTE_NAMES[other['route']]} would deliver the same amount. The first was chosen because it "
                     "fixes the local amount before any transfer is made.")
    return chosen["route"], said


# ---- wording a change ------------------------------------------------------------------------------------------

def fixed_explanation(kind: str, facts: dict, plan: dict | None) -> str:
    """The sentence used when no model is asked or its answer cannot be trusted. Built from the figures alone.
    Before the new plan has been worked out (`plan` is None) it says what happened and leaves the new amount out."""
    now = _figure(plan.get("expected_local")) if plan else None
    if kind in ("short_deposit", "deposit_differs"):
        less = "less" if kind == "short_deposit" else "more"
        then = f"; on what arrived you would receive about {now}" if now else ""
        return (f"The holder sent {Decimal(facts['arrived']):,.2f} USD, which is "
                f"{Decimal(facts['difference']):,.2f} USD {less} than the {Decimal(facts['approved']):,.2f} USD it "
                f"approved. Nothing has been converted or sent{then}.")
    if kind in ("rate_lock_expired", "amount_changed"):
        why = ("The rate lock ran out before the money could be converted" if kind == "rate_lock_expired" else
               "The amount to convert changed, and the new quote moved more than the agreed tolerance")
        return (f"{why}. The rate was {facts.get('old_rate')} and is now {facts.get('new_rate')}, so you would "
                f"receive {Decimal(facts['new_local']):,.2f} {facts['currency']} instead of "
                f"{Decimal(facts['old_local']):,.2f} {facts['currency']}.")
    if kind in ("transfer_failed", "transfer_returned"):
        what = ("returned the money after the transfer had been paid" if kind == "transfer_returned" else
                "refused the transfer")
        kept = facts.get("fee_kept") or {}
        fee = f" Airwallex kept its payout fee of {_figure(kept)} for that transfer." if kept.get("amount") else ""
        then = f" A replacement to corrected bank details would bring about {now}." if now else ""
        if now and facts.get("claimant_asked") is not None and facts.get("agreed_local"):
            agreed = _figure({"amount": facts["agreed_local"], "currency": plan["expected_local"]["currency"]})
            short, limit = facts.get("shortfall_percent"), facts.get("tolerance_percent")
            then += (f" That is {short} percent less than the {agreed} agreed, which is outside the tolerance of "
                     f"{limit} percent, so the claimant is asked to agree to it." if facts["claimant_asked"] else
                     f" That is {short} percent less than the {agreed} agreed, which is inside the tolerance of "
                     f"{limit} percent, so the claimant is not asked to agree again.")
        return (f"The receiving bank {what} ({facts.get('reason')}). {_figure(facts.get('came_back'))} came back "
                f"and is held for this claim.{fee}{then}")
    if kind == "deadline_passed":
        held = facts.get("funds") or {}
        has = f" {_figure(held)} is held for this claim at Airwallex and stays there." if held.get("amount") else ""
        days = facts.get("days")
        more = f" A new approval gives it {days} more days." if days else ""
        return (f"The holder's deadline for sending this payment passed on {_day(facts.get('deadline'))}, so nothing "
                f"more is sent without the holder.{has}{more}")
    if kind in EXPLAINERS:
        return EXPLAINERS[kind](facts, plan)
    return "Something changed after the plan was agreed, so the payment has stopped until the new terms are agreed."


def _day(stamp: str | None) -> str:
    """'26 Nov 2026' from an ISO time."""
    try:
        when = datetime.fromisoformat(stamp or "")
    except ValueError:
        return "the day it set"
    return f"{when.day} {when:%b %Y}"


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUMBER.findall(text or ""):
        n = m.replace(",", "").rstrip(".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n)
    return out


def word_change(kind: str, facts: dict, plan: dict | None, model: str = "haiku") -> dict:
    """{"text", "worded_by"} for a change. The model only rewords the fixed sentence. Its answer is kept only if
    it is short and every number in it is one of the numbers in the fixed sentence; otherwise the fixed sentence
    stands. No amount, limit or decision comes from the model."""
    fixed = fixed_explanation(kind, facts, plan)
    prompt = ("Rewrite the following notice to a person waiting for a payment, in one or two plain, calm English "
              "sentences. Keep every amount, rate and currency exactly as written. Add no fact, no promise and no "
              "advice. Do not use dashes. Answer with the sentences only.\n\n" + fixed)
    try:
        text = " ".join(llm.ask(prompt, model=model, timeout=45).split())
    except Exception:
        return {"text": fixed, "worded_by": "fixed sentence"}
    allowed = _numbers(fixed)
    if not text or len(text) > 600 or not _numbers(text) <= allowed or not {n for n in allowed if "." in n} <= _numbers(text):
        return {"text": fixed, "worded_by": "fixed sentence"}
    return {"text": text, "worded_by": "language model, checked against the figures"}


class PayoutRunner:
    """One background thread per payout that has something to do."""

    def __init__(self, store: cl.ClaimStore, factory: Factory = sandbox_factory, *, pause: float = 1.0,
                 max_idle: int = 180, max_errors: int = 3, watch_pause: float | None = None,
                 watch_seconds: float | None = None, word: Callable[..., dict] = word_change):
        self.store = store
        self.factory = factory
        self.pause = pause
        self.max_idle = max_idle        # steps without progress before the thread gives up waiting
        self.max_errors = max_errors    # errors in a row before the thread stops and reports
        # After PAID the transfer is read again every `watch_pause` seconds for `watch_seconds`, in case the bank
        # returns it. None for watch_seconds means airwallex.RETURN_WATCH_SECONDS, counted from the payment.
        self.watch_pause = max(pause * 10, 5.0) if watch_pause is None else watch_pause
        self.watch_seconds = watch_seconds
        self.word = word
        # How the holder's money arrives when it is not a bank deposit (metal.MetalFunding), or None.
        self.funding = None
        self.problems: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def credentials_ready(self) -> bool:
        try:
            client, _ = self.factory()
        except awx.CredentialsError:
            return False
        client.close()
        return True

    def simulator_ready(self) -> bool:
        """True when the "what if" cases can be staged, which is only on the sandbox."""
        try:
            client, simulator = self.factory()
        except awx.CredentialsError:
            return False
        client.close()
        return simulator is not None

    def running(self, claim_id: str) -> bool:
        thread = self._threads.get(claim_id)
        return bool(thread and thread.is_alive())

    def start(self, claim_id: str) -> None:
        """Start (or restart) the thread for a payout whose file already exists. Does nothing if one is alive."""
        with self._lock:
            # A thread takes itself out of `_threads` (under this lock) the moment it decides it has nothing
            # left to do, so a start that arrives while it is closing down is not lost.
            if (claim_id in self._threads and self.running(claim_id)) or self._stop.is_set():
                return
            self.problems.pop(claim_id, None)
            thread = threading.Thread(target=self._work, args=(claim_id,), name=f"payout-{claim_id}", daemon=True)
            self._threads[claim_id] = thread
            thread.start()

    def resume_all(self) -> list[str]:
        """After a restart: pick up every payout that had started and not finished, and go back to reading every
        paid one that is still inside its watch time. Never creates one."""
        resumed = []
        if not self.store.folder.is_dir():
            return resumed
        for path in sorted(self.store.folder.glob("*/payout.json")):
            claim_id = path.parent.name
            try:
                self.store.check_id(claim_id)
                payout = awx.Payout.load(path)
            except (cl.ClaimError, ValueError):
                continue
            self.settle(claim_id, payout)
            if payout.state in awx.STOPPED:
                if payout.hold and not payout.hold.get("plan"):
                    self.start(claim_id)     # it stopped just before the server did: finish working out the new plan
                continue
            if payout.state == awx.PAID and not self._watching(payout):
                continue
            self.start(claim_id)
            resumed.append(claim_id)
        return resumed

    def stop(self, wait: float = 5.0) -> None:
        self._stop.set()
        for thread in list(self._threads.values()):
            thread.join(wait)

    def join(self, claim_id: str, timeout: float = 10.0) -> None:
        """Waits until no thread is working on this payout. Used by the tests."""
        ends = time.time() + timeout
        while time.time() < ends:
            thread = self._threads.get(claim_id)
            if thread is None:
                return
            thread.join(0.05)

    def _watching(self, payout: awx.Payout) -> bool:
        if payout.state != awx.PAID or payout.watch_until is None:
            return False
        if self.watch_seconds is not None:
            paid = awx._parse_time(payout.paid_at) or time.time()
            return time.time() < paid + self.watch_seconds
        return time.time() < payout.watch_until

    def settle(self, claim_id: str, payout: awx.Payout) -> None:
        """Carry what happened to the payout over to the claim: paid, held, or sent back by the bank."""
        with self.store.lock:
            try:
                claim = self.store.load(claim_id)
            except cl.ClaimError:
                return
            hold = payout.hold or {}
            if payout.state == awx.PAID and claim["state"] == cl.PAYING:
                self.store._event(claim, cl.PAID, f"Airwallex reports transfer {payout.transfer_id} as paid: "
                                                  f"{payout.target_amount} {payout.target_currency}.")
                self.store.save(claim)
            elif hold.get("needs") and "payer" in hold["needs"] and claim["state"] in (cl.PAYING, cl.PAID):
                text = fixed_explanation(hold["kind"], hold.get("facts") or {}, None)
                claim["history"].append({"state": claim["state"], "at": cl.now(), "note": text})
                reason = {"short_deposit": "less money arrived than was approved",
                          "deposit_differs": "a different amount arrived from the one approved",
                          "transfer_failed": "the bank refused the transfer, so the terms that were approved can "
                                             "no longer be carried out",
                          "transfer_returned": "the bank returned the payment, so the terms that were approved "
                                               "can no longer be carried out",
                          "deadline_passed": "the deadline in the holder's standing instructions passed before "
                                             "the money was sent"}.get(hold["kind"]) or VOID_REASONS.get(hold["kind"], "the terms changed")
                if not self.store.void_approval(claim, reason):
                    self.store._event(claim, cl.PAYMENT_HELD, "The payment is on hold.")
                self.store.save(claim)
            elif hold.get("needs") and claim["state"] == cl.PAYING:
                text = fixed_explanation(hold["kind"], hold.get("facts") or {}, None)
                if not any(e["note"] == text for e in claim["history"]):     # said once
                    claim["history"].append({"state": cl.PAYING, "at": cl.now(), "note": text})
                    self.store.save(claim)
            elif payout.state == awx.FAILED and not hold and claim["state"] == cl.PAYING \
                    and not any(e["note"].startswith("The payment could not go ahead") for e in claim["history"]):
                claim["history"].append({"state": cl.PAYING, "at": cl.now(), "note":
                                         f"The payment could not go ahead: {payout.failure}."})
                self.store.save(claim)

    def prepare_hold(self, payout: awx.Payout, client: awx.AirwallexClient, simulator_ready: bool) -> None:
        """When the machine has just stopped on a change: work the plan out again on the new figures and put the
        change into words. Done once per stop.

        People can act on a stopped payout while this runs (the wording can take some seconds), so nothing here
        writes from memory: each change is made to the file as it is at that moment, under the store's lock."""
        lock = self.store.lock if self.store is not None else threading.RLock()
        with lock:
            fresh = awx.Payout.load(payout.path)
            hold = fresh.hold
            if not hold or hold.get("plan"):
                payout.__dict__.update(fresh.__dict__)
                return
            plan = make_plan(fresh, client, simulator_ready=simulator_ready)
            hold["plan"] = plan
            self._replacement_inside_tolerance(fresh, hold, plan)
            hold["explanation"], hold["worded_by"] = fixed_explanation(hold["kind"], hold.get("facts") or {}, plan), "fixed sentence"
            fresh.save()
            kind, facts, started = hold["kind"], dict(hold.get("facts") or {}), hold.get("at")
        said = self.word(kind, facts, plan)          # may ask a model; never done while holding the lock
        with lock:
            fresh = awx.Payout.load(payout.path)
            if fresh.hold and fresh.hold.get("at") == started and (fresh.hold.get("plan") or {}).get("id") == plan["id"]:
                fresh.hold["explanation"], fresh.hold["worded_by"] = said["text"], said["worded_by"]
            fresh.note(kind, said["text"], worded_by=said["worded_by"], plan_id=plan["id"])
            if started:      # the change is dated when it happened, not when its wording was ready
                fresh.decisions[-1]["at"] = started
            fresh.save()
            payout.__dict__.update(fresh.__dict__)

    @staticmethod
    def _replacement_inside_tolerance(payout: awx.Payout, hold: dict, plan: dict) -> None:
        """After a refused or returned transfer, under standing instructions: if the replacement would bring the
        claimant no less than the tolerance allows, the claimant is not asked to agree again. The corrected bank
        account and the holder's approval of it are needed in every case."""
        rules, facts = payout.instructions, hold.setdefault("facts", {})
        agreed = facts.get("agreed_local")
        if not rules or hold["kind"] not in ("transfer_failed", "transfer_returned") or not agreed:
            return
        if "claimant" not in hold.get("needs", []):
            return
        now = plan["expected_local"]
        inside, short = ins.within_tolerance(agreed, now["amount"], rules)
        facts.update({"replacement_local": now["amount"], "shortfall_percent": str(short),
                      "tolerance_percent": rules["tolerance_percent"], "claimant_asked": not inside})
        if payout.attempts:      # kept with the dead transfer, so the outcome can still be shown once it is paid
            payout.attempts[-1]["outcome"] = {
                "agreed_local": agreed, "replacement_local": now["amount"], "shortfall_percent": str(short),
                "tolerance_percent": rules["tolerance_percent"], "claimant_asked": not inside}
        if not inside:
            return
        hold["needs"] = [n for n in hold["needs"] if n != "claimant"]
        payout.confirmed = {"plan_id": plan["id"], "local_amount": agreed, "currency": now["currency"],
                            "by": "standing instructions", "at": cl.now()}
        payout.decide("replacement_within_tolerance", "tolerance",
                      f"The replacement would bring {_figure(now)}. That is {short} percent less than the "
                      f"{_figure({'amount': agreed, 'currency': now['currency']})} the claimant agreed to, because "
                      f"Airwallex charges its payout fee again. It is inside the tolerance of "
                      f"{rules['tolerance_percent']} percent, so the claimant is not asked to agree again. The new "
                      "bank account still has to come from the claimant and be approved by the holder.",
                      plan_id=plan["id"], shortfall_percent=str(short))

    def _advance_until_stopped(self, claim_id: str, payout: awx.Payout, client, simulator) -> bool:
        """Runs the machine until it is paid and no longer watched, stopped for a person, or told to stop. False
        when it gave up waiting on Airwallex."""
        idle = errors = 0
        while not self._stop.is_set():
            if payout.state in awx.STOPPED:
                break
            if payout.state == awx.PAID:
                self.settle(claim_id, payout)
                if not self._watching(payout):
                    break
                if self._stop.wait(self.watch_pause):
                    break
            before = payout.state
            try:
                awx.advance(payout, client, simulator, funding=self.funding)
                errors = 0
            except (awx.AirwallexError, httpx.HTTPError) as err:
                errors += 1
                if errors >= self.max_errors:
                    raise err
            if payout.state == before and payout.state != awx.PAID:
                idle += 1
                if idle >= self.max_idle:
                    self.problems[claim_id] = ("The payment is still waiting on Airwallex. Starting it again "
                                               "carries on from where it stopped.")
                    return False
                self._stop.wait(self.pause)
            elif payout.state != before:
                idle = 0
        return True

    def _work(self, claim_id: str) -> None:
        client = None
        me = threading.current_thread()
        try:
            client, simulator = self.factory()
            path = self.store.payout_path(claim_id)
            while True:
                payout = awx.Payout.load(path)
                if not self._advance_until_stopped(claim_id, payout, client, simulator):
                    break
                # The claim learns of a stop at once (its approval is withdrawn where the terms no longer hold),
                # so the next person can act. The new plan and the wording of the change follow.
                self.settle(claim_id, payout)
                if payout.hold:
                    self.prepare_hold(payout, client, simulator is not None)
                # While the change was being put into words, the people it waits for may already have agreed.
                # Look at the file again, and bow out only if there is really nothing to do.
                with self._lock:
                    now = awx.Payout.load(path)
                    released = now.state not in awx.STOPPED and not (now.state == awx.PAID and not self._watching(now))
                    if not released or self._stop.is_set():
                        if self._threads.get(claim_id) is me:
                            del self._threads[claim_id]
                        break
        except Exception as err:  # the thread must never die silently: the screen shows what happened
            self.problems[claim_id] = explain(err)
        finally:
            with self._lock:
                if self._threads.get(claim_id) is me:
                    del self._threads[claim_id]
            if client is not None:
                client.close()


def _mask_account(number: str) -> str:
    return "·" * max(len(number) - 4, 0) + number[-4:]


_LONG_DIGITS = re.compile(r"\b\d{8,}\b")


def mask_digits(text: str) -> str:
    """Hides all but the last four digits of anything that looks like an account number."""
    return _LONG_DIGITS.sub(lambda m: "·" * (len(m.group()) - 4) + m.group()[-4:], text or "")


def reconciliation(payout: dict) -> dict:
    """Airwallex's own rows for this claim, line by line, and what they add up to in each currency. A finished
    payout balances when every currency comes to zero: everything that arrived for the claim was either taken as
    a fee by Airwallex or sent to the claimant, and nothing else."""
    lines = [{"id": r.get("id"), "part": r.get("part"), "type": r.get("transaction_type"),
              "description": mask_digits(r.get("description") or ""), "amount": str(r.get("amount")),
              "currency": r.get("currency"), "status": r.get("status"), "at": r.get("created_at")}
             for r in payout.get("ledger") or []]
    sums = []
    for currency in sorted({line["currency"] for line in lines if line["currency"]}):
        rows = [Decimal(line["amount"]) for line in lines if line["currency"] == currency]
        sums.append({"currency": currency, "came_in": str(sum((a for a in rows if a > 0), Decimal(0))),
                     "went_out": str(-sum((a for a in rows if a < 0), Decimal(0))),
                     "left": str(sum(rows, Decimal(0)))})
    left = [s for s in sums if Decimal(s["left"]) != 0]
    paid = payout.get("state") == awx.PAID
    if not lines:
        statement = "Airwallex has booked nothing for this claim yet."
    elif not left:
        statement = ("Every line Airwallex booked for this claim adds up to zero: what arrived, less Airwallex's "
                     "fees, is exactly what was sent.")
    elif paid:
        statement = ("The lines do not add up to zero: " + ", ".join(f"{Decimal(s['left']):,.2f} {s['currency']}"
                     for s in left) + " is unaccounted for. A person needs to look at this.")
    else:
        statement = ("Held for this claim at Airwallex right now: "
                     + ", ".join(f"{Decimal(s['left']):,.2f} {s['currency']}" for s in left) + ".")
    return {"lines": lines, "sums": sums, "balanced": bool(lines) and not left, "statement": statement}


def _bank(beneficiary: dict, currency: str) -> dict:
    bank = beneficiary["beneficiary"]["bank_details"]
    return {"name": bank.get("account_name"), "number": _mask_account(bank.get("account_number") or ""),
            "country": bank.get("bank_country_code"), "currency": currency}


def view(claim: dict, payout: dict | None, *, running: bool, problem: str | None, credentials_ready: bool,
         simulator_ready: bool = False) -> dict:
    """Everything the payment screen shows. Every figure comes from the payout file, which holds what Airwallex
    answered at each step, or from the plan, where each figure says whether it is booked or expected."""
    payee = claim.get("payee")
    approval = claim.get("approval")
    base = {"claim_id": claim["id"], "claim_state": claim["state"], "environment": "Airwallex sandbox",
            "credentials_ready": credentials_ready, "running": running,
            "problem": problem or (None if credentials_ready else NO_CREDENTIALS),
            "record_amount": claim["record"].get("amount"), "record_currency": claim["record"].get("currency", "USD"),
            "approved": bool(approval), "approval": approval and {"at": approval["at"], "amount": approval["terms"]["amount"],
                                                                  "currency": approval["terms"]["currency"]},
            "account": _bank(payee["beneficiary"], payee["currency"]) if payee else None,
            "what_if_options": [{"key": k, "label": WHAT_IF_LABELS[k]} for k in awx.WHAT_IFS] if simulator_ready else []}
    if payout is None:
        return {**base, "started": False, "state": None, "plan": None, "hold": None, "cards": [],
                "journey": [{"key": k, "label": label, "done": False, "at": None} for k, label in JOURNEY]}

    at, first = {}, {}
    for event in payout.get("history", []):
        at[event["state"]] = event["at"]          # the latest time each step was reached
        first.setdefault(event["state"], event["at"])   # and the first: the deposit arrives once
    currency = payout["target_currency"]
    route = payout.get("route")
    sent_by_now = payout.get("transfer_id") is not None
    when = {"arrived": first.get(awx.DEPOSIT_CONFIRMED) or (payout.get("deposit_amount") and first.get(awx.HELD)),
            "fee": first.get(awx.DEPOSIT_CONFIRMED) or (payout.get("deposit_fee") and first.get(awx.HELD)),
            "rate_locked": at.get(awx.CONVERTED),
            "converted": at.get(awx.CONVERTED) if route == awx.CONVERT_THEN_PAY else at.get(awx.TRANSFER_CREATED),
            "sent": at.get(awx.SENT) if sent_by_now else None,
            "paid": at.get(awx.PAID) if payout["state"] == awx.PAID else None}
    if payout.get("attempts") and not sent_by_now:   # a replacement is being arranged: the last steps are open again
        when["converted"] = when["converted"] if route != awx.PAY_WITH_QUOTE else None
    fee = Decimal(payout["deposit_fee"]) if payout.get("deposit_fee") is not None else None
    arrived = Decimal(payout["deposit_amount"]) if payout.get("deposit_amount") is not None else None
    proof = payout.get("proof") or None
    hold = payout.get("hold")
    # While a payment is stopped, the only plan that counts is the one worked out again for the stop. Until it
    # is ready there is no plan to agree to: the earlier one is spent.
    plan = hold.get("plan") if hold else payout.get("plan")
    transfer_fee = payout.get("transfer_fee")
    rules = payout.get("instructions")
    decisions = sorted(payout.get("decisions", []), key=lambda d: d.get("at") or "")
    report = [{"at": d.get("at"), "kind": d["kind"], "title": DECISION_TITLES.get(d["kind"], "Decided alone"),
               "text": d.get("text"), "rule": d.get("rule"), "rule_name": RULE_NAMES.get(d.get("rule") or "", "")}
              for d in decisions if d.get("by") == "agent"]
    confirmed = payout.get("confirmed") or {}
    settled = None
    if payout["state"] == awx.PAID and confirmed.get("local_amount") and payout.get("target_amount"):
        gap = Decimal(payout["target_amount"]) - Decimal(confirmed["local_amount"])
        if gap == 0:
            why = "The amount paid is the amount agreed, to the cent."
        elif payout.get("attempts") and gap < 0:
            fate = "returned" if "returned" in (payout["attempts"][-1].get("fate") or "") else "refused"
            why = (f"{abs(gap):,.2f} {currency} less than the amount agreed, because the first transfer was {fate} "
                   "by the bank and Airwallex charged its payout fee a second time on the replacement."
                   + (" That is inside the holder's tolerance, so the claimant was not asked to agree again."
                      if confirmed.get("by") == "standing instructions" else ""))
        elif gap > 0 and any(d.get("kind") == "better_rate" for d in decisions):
            why = (f"{gap:,.2f} {currency} more than the amount agreed, because a better rate than the one locked "
                   "with the plan was on offer at the moment it was used, and the better one was taken.")
        else:
            why = (f"{abs(gap):,.2f} {currency} {'more' if gap > 0 else 'less'} than the amount agreed. The plan "
                   "gives Airwallex's payout fee and the rate as expected figures; what Airwallex booked is what "
                   "was paid, and every line of it is in Airwallex's records.")
        settled = {"agreed": {"amount": confirmed["local_amount"], "currency": currency},
                   "paid": {"amount": payout["target_amount"], "currency": currency},
                   "difference": {"amount": str(gap), "currency": currency}, "note": why}
    return {
        **base,
        "agent_report": report,
        # Each decision as four short lines; the report above stays as the longer account behind them.
        "cards": cards.payout_cards(payout, plan),
        "instructions": rules and {"rules": rules, "in_words": ins.in_words(rules),
                                   "deadline_at": payout.get("deadline_at")},
        "claim_usd": payout.get("claim_usd"),
        "agreed_and_paid": settled,
        "started": payout["state"] != awx.PLANNED,
        "state": payout["state"],
        "failure": payout.get("failure"),
        "started_at": next((e["at"] for e in claim["history"] if e["state"] == cl.PAYING), None),
        "steps": payout.get("history", []),
        "journey": [{"key": k, "label": label, "done": bool(when[k]), "at": when[k] or None} for k, label in JOURNEY],
        "plan": plan,
        "confirmed": payout.get("confirmed"),
        "route": route, "route_name": ROUTE_NAMES.get(route),
        "what_if": payout.get("what_if"), "what_if_label": WHAT_IF_LABELS.get(payout.get("what_if") or ""),
        "hold": hold and {"kind": hold["kind"], "at": hold.get("at"), "needs": hold.get("needs", []),
                          "needs_words": [NEEDS_WORDS[n] for n in hold.get("needs", [])],
                          "explanation": hold.get("explanation") or fixed_explanation(hold["kind"], hold.get("facts") or {}, plan),
                          "worded_by": hold.get("worded_by") or "fixed sentence", "facts": hold.get("facts"),
                          "ready": bool(hold.get("plan")),   # the new plan and the wording are in place
                          "plan_id": (hold.get("plan") or {}).get("id")},
        "decisions": decisions,
        "attempts": payout.get("attempts", []),
        "funds": payout.get("funds"),
        "deposit": {"amount": str(arrived if arrived is not None else Decimal(payout["usd_amount"])), "currency": "USD",
                    "expected": payout["usd_amount"], "arrived": arrived is not None,
                    "reference": payout["deposit_reference"], "id": payout.get("deposit_id")},
        "incoming_fee": None if fee is None else {"amount": str(fee), "currency": "USD"},
        "after_fee": None if fee is None or arrived is None else {"amount": str(arrived - fee), "currency": "USD"},
        "rate": payout.get("client_rate"),
        "rate_pair": f"USD to {currency}",
        "rate_locked_until": payout.get("quote_valid_to"),
        "local": None if payout.get("target_amount") is None else {"amount": payout["target_amount"],
                                                                   "currency": currency},
        "payout_fee": None if not transfer_fee else {"amount": transfer_fee["amount"], "currency": transfer_fee["currency"],
                                                     "paid_by": transfer_fee.get("paid_by")},
        "left_wallet": None if payout.get("payer_pays") is None else {
            "amount": payout["payer_pays"],
            "currency": "USD" if route == awx.PAY_WITH_QUOTE else currency},
        "received": None if not sent_by_now or payout.get("target_amount") is None else {
            "amount": payout["target_amount"], "currency": currency},
        "transfer_status": payout.get("transfer_status"),
        "transfer_id": payout.get("transfer_id"),
        "paid_at": payout.get("paid_at"),
        "watching_for_return": payout["state"] == awx.PAID and bool(payout.get("watch_until"))
                               and time.time() < payout["watch_until"],
        "account": _bank(payout["beneficiary"], currency),
        "reconciliation": reconciliation(payout),
        "proof": proof,
    }
