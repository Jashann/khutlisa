"""What an amount in US dollars would become in the claimant's currency today.

The rate is Airwallex's own indicative client rate (GET /api/v1/fx/rates/current on the sandbox). Asking for it
locks nothing and moves nothing. It is kept for a minute, so a screen full of match cards asks Airwallex once,
and the client's own pacing keeps every call under the sandbox's rate limit. Every figure made from it is
labelled as indicative; the payout plan, written after the holder's approval, is where a rate is locked.
"""
from __future__ import annotations

import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import httpx

from . import airwallex as awx
from . import instructions as ins
from .countries import COUNTRIES
from .names import normalise

TTL = 60.0             # seconds a rate is reused before Airwallex is asked again
STALE_AFTER = 900.0    # an older rate is shown, with its age, for this long when Airwallex cannot be asked
LABEL = "Indicative: Airwallex's sandbox rate a moment ago. Not locked, and not a promise."
NOT_PAID_YET = "This build pays to bank accounts in Mexico and the Philippines only."
_OTHER_NAMES = {"MEXICO": "MX", "MEJICO": "MX", "PHILIPPINES": "PH", "PILIPINAS": "PH", "FILIPINAS": "PH",
                "THE PHILIPPINES": "PH"}


def corridor(country: str | None) -> tuple[str, str] | None:
    """(country code, currency) for a country written as a code or a name, if this build pays there."""
    text = normalise(country or "")
    if not text:
        return None
    code = text if text in COUNTRIES else _OTHER_NAMES.get(text)
    if code is None:
        code = next((c for c, row in COUNTRIES.items() if normalise(row["name"]) == text), None)
    for currency, row in awx.CORRIDORS.items():
        if row["country"] == code:
            return code, currency
    return None


class Indicative:
    """One shared source of indicative rates. `factory` returns (Airwallex client, simulator) as elsewhere."""

    def __init__(self, factory: Callable[[], tuple], ttl: float = TTL, clock: Callable[[], float] = time.time):
        self.factory = factory
        self.ttl = ttl
        self.clock = clock
        self._rates: dict[str, dict] = {}
        self._lock = threading.Lock()

    def rate(self, currency: str) -> dict:
        """{"rate", "at", "age_seconds"} for US dollars into `currency`, or {"reason"} when none can be given."""
        with self._lock:      # one caller asks Airwallex; the others wait and use its answer
            held = self._rates.get(currency)
            now = self.clock()
            if held and now - held["at"] < self.ttl:
                return {**held, "age_seconds": int(now - held["at"])}
            try:
                client, _ = self.factory()
            except awx.CredentialsError:
                return {"reason": "The Airwallex sandbox keys are not set up on this server, so no rate can be shown."}
            try:
                answer = client.indicative_rate("USD", currency)
                held = {"rate": float(answer["rate"]), "at": now, "stated_at": answer.get("created_at")}
                self._rates[currency] = held
                return {**held, "age_seconds": 0}
            except (awx.AirwallexError, httpx.HTTPError, KeyError, TypeError, ValueError):
                if held and now - held["at"] < STALE_AFTER:
                    return {**held, "age_seconds": int(now - held["at"])}
                return {"reason": "Airwallex's rate could not be read just now."}
            finally:
                client.close()

    def amounts(self, country: str | None, amounts: list[Any], rules: dict | None) -> dict:
        """What each US dollar amount would become for someone paid in `country`, after the fees the payout plan
        expects and under the holder's fee rule if one is set."""
        where = corridor(country)
        if where is None:
            return {"available": False, "reason": NOT_PAID_YET, "amounts": []}
        code, currency = where
        got = self.rate(currency)
        if "rate" not in got:
            return {"available": False, "reason": got["reason"], "currency": currency, "amounts": []}
        rate = Decimal(str(got["rate"]))
        rows = []
        for amount in amounts:
            fees = ins.fee_plan(amount, rules)
            left = Decimal(fees["left_for_claimant_usd"])
            rows.append({
                "usd": fees["claim"],
                "holder_sends": {"amount": fees["holder_sends"], "currency": "USD"},
                "fees": {"incoming": fees["expected_incoming_fee"], "payout": fees["expected_payout_fee_usd"],
                         "currency": "USD", "borne_by": fees["bearer"]},
                "would_receive": {"amount": str(awx.money(left * rate, currency)), "currency": currency},
            })
        return {"available": True, "country": code, "currency": currency, "pair": f"USD to {currency}",
                "rate": got["rate"], "age_seconds": got["age_seconds"], "label": LABEL,
                "fees_note": "After the fees the payout plan expects: Airwallex's incoming fee of 0.3 percent and "
                             "its payout fee of about 5.00 USD.",
                "amounts": rows}


def clean_amounts(values: list[str], limit: int = 30) -> list[str]:
    """Up to `limit` positive amounts as decimal strings. Raises ValueError for anything else."""
    out = []
    for value in values[:limit]:
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise ValueError("each amount must be a number") from None
        if not number.is_finite() or number <= 0 or number > Decimal("100000000"):
            raise ValueError("each amount must be a positive number")
        out.append(str(number.quantize(Decimal("0.01"))))
    return out
