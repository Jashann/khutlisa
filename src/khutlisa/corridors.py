"""Corridors: for each country an owner may live in, how money can reach a bank account there through Airwallex.

Three kinds of fact are kept apart, and every figure says which kind it is:

  discovered   read from the live Airwallex sandbox by `discover` and kept in airwallex_corridors.json with the
               time it was fetched: whether a beneficiary schema exists for the country and currency by local
               rails and by SWIFT, which fields it requires, the indicative rate, real quotes at several sizes
               and lock lengths, whether the currency can be converted into a held balance, and the fees
               Airwallex really charged on transfers this account has made.
  documented   copied from Airwallex's public pages (the fee schedule, the country payout guides, the currency
               table), each with the address it was read at and the date. A documented fee for a corridor that
               has never been paid from this account is an estimate, and the plan says so.
  assumed      nothing. Where neither exists the plan says the figure is not known.

Everything here is lookups and arithmetic. No language model is involved.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

FILE = Path(__file__).with_name("airwallex_corridors.json")

LOCAL, SWIFT = "LOCAL", "SWIFT"
LADDER = (10, 100, 1_000, 10_000, 100_000, 1_000_000)     # US dollar sizes at which a real quote is taken
VALIDITIES = ("MIN_1", "MIN_15", "HR_1")                  # lock lengths compared at one size
VALIDITY_SIZE = 1_000
EUROZONE = ("AD AT BE CY DE EE ES FI FR GR HR IE IT LT LU LV MC ME MT NL PT SI SK SM XK GF GP MQ RE YT PM BL MF "
            "AX VA").split()

# The currency of each country, ISO 4217. A country missing here has no corridor in its own currency and is
# planned in US dollars by SWIFT if Airwallex offers that.
CURRENCY_OF: dict[str, str] = {c: "EUR" for c in EUROZONE}
CURRENCY_OF.update({
    "AE": "AED", "AF": "AFN", "AG": "XCD", "AI": "XCD", "AL": "ALL", "AM": "AMD", "AO": "AOA", "AR": "ARS",
    "AU": "AUD", "AW": "AWG", "AZ": "AZN", "BA": "BAM", "BB": "BBD", "BD": "BDT", "BF": "XOF", "BG": "BGN",
    "BH": "BHD", "BI": "BIF", "BJ": "XOF", "BM": "BMD", "BN": "BND", "BO": "BOB", "BR": "BRL", "BS": "BSD",
    "BT": "BTN", "BW": "BWP", "BY": "BYN", "BZ": "BZD", "CA": "CAD", "CD": "CDF", "CF": "XAF", "CG": "XAF",
    "CH": "CHF", "CI": "XOF", "CK": "NZD", "CL": "CLP", "CM": "XAF", "CN": "CNY", "CO": "COP", "CR": "CRC",
    "CU": "CUP", "CV": "CVE", "CW": "ANG", "CX": "AUD", "CZ": "CZK", "DJ": "DJF", "DK": "DKK", "DM": "XCD",
    "DO": "DOP", "DZ": "DZD", "EC": "USD", "EG": "EGP", "ER": "ERN", "ET": "ETB", "FJ": "FJD", "FK": "FKP",
    "FM": "USD", "FO": "DKK", "GA": "XAF", "GB": "GBP", "GD": "XCD", "GE": "GEL", "GG": "GBP", "GH": "GHS",
    "GI": "GIP", "GL": "DKK", "GM": "GMD", "GN": "GNF", "GQ": "XAF", "GT": "GTQ", "GW": "XOF", "GY": "GYD",
    "HK": "HKD", "HN": "HNL", "HT": "HTG", "HU": "HUF", "ID": "IDR", "IL": "ILS", "IM": "GBP", "IN": "INR",
    "IO": "USD", "IQ": "IQD", "IR": "IRR", "IS": "ISK", "JE": "GBP", "JM": "JMD", "JO": "JOD", "JP": "JPY",
    "KE": "KES", "KG": "KGS", "KH": "KHR", "KI": "AUD", "KM": "KMF", "KN": "XCD", "KP": "KPW", "KR": "KRW",
    "KW": "KWD", "KY": "KYD", "KZ": "KZT", "LA": "LAK", "LB": "LBP", "LC": "XCD", "LI": "CHF", "LK": "LKR",
    "LR": "LRD", "LS": "LSL", "LY": "LYD", "MA": "MAD", "MD": "MDL", "MG": "MGA", "MH": "USD", "MK": "MKD",
    "ML": "XOF", "MM": "MMK", "MN": "MNT", "MO": "MOP", "MR": "MRU", "MS": "XCD", "MU": "MUR", "MV": "MVR",
    "MW": "MWK", "MX": "MXN", "MY": "MYR", "MZ": "MZN", "NA": "NAD", "NC": "XPF", "NE": "XOF", "NG": "NGN",
    "NI": "NIO", "NO": "NOK", "NP": "NPR", "NR": "AUD", "NU": "NZD", "NZ": "NZD", "OM": "OMR", "PA": "USD",
    "PE": "PEN", "PF": "XPF", "PG": "PGK", "PH": "PHP", "PK": "PKR", "PL": "PLN", "PS": "ILS", "PW": "USD",
    "PY": "PYG", "QA": "QAR", "RO": "RON", "RS": "RSD", "RU": "RUB", "RW": "RWF", "SA": "SAR", "SB": "SBD",
    "SC": "SCR", "SD": "SDG", "SE": "SEK", "SG": "SGD", "SH": "SHP", "SL": "SLE", "SN": "XOF", "SO": "SOS",
    "SR": "SRD", "SS": "SSP", "ST": "STN", "SV": "USD", "SX": "ANG", "SY": "SYP", "SZ": "SZL", "TC": "USD",
    "TD": "XAF", "TG": "XOF", "TH": "THB", "TJ": "TJS", "TK": "NZD", "TL": "USD", "TM": "TMT", "TN": "TND",
    "TO": "TOP", "TR": "TRY", "TT": "TTD", "TV": "AUD", "TW": "TWD", "TZ": "TZS", "UA": "UAH", "UG": "UGX",
    "UY": "UYU", "UZ": "UZS", "VC": "XCD", "VE": "VES", "VG": "USD", "VN": "VND", "VU": "VUV", "WF": "XPF",
    "WS": "WST", "YE": "YER", "ZA": "ZAR", "ZM": "ZMW", "ZW": "ZWL",
})

# Currencies with no minor unit (ISO 4217). Amounts in them are whole numbers.
ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}

_AWX_DOCS = "https://www.airwallex.com/docs"
DOCUMENTED_ON = "13 Nov 2026"
SOURCES = {
    "fee_schedule": {"label": "Airwallex fee schedule for US customers (last updated 5 Nov 2026)",
                     "url": "https://www.airwallex.com/en-us/terms/fee-schedule"},
    "payout_guides": {"label": "Airwallex payout guides, one per country (payment scheme and flight time)",
                      "url": _AWX_DOCS + "/payouts/payout-network/bank-accounts"},
    "currencies": {"label": "Airwallex supported regions and currencies (hold in wallet, or convert and pay only)",
                   "url": _AWX_DOCS + "/transactional-fx/supported-regions-and-currencies"},
    "rate_limits": {"label": "Airwallex API rate limits", "url": _AWX_DOCS + "/developer-tools/api/rate-limits"},
    "schemas": {"label": "Airwallex beneficiary schemas",
                "url": _AWX_DOCS + "/payouts/beneficiaries/using-api-and-form-schemas"},
}

# Airwallex's published price of one transfer, in US dollars, by the currency paid out (the fee schedule; "take
# effect on 12 October 2026"; "do not apply to Grow and Accelerate customers"). The sandbox has charged 5.00 on
# every local payout this account has made, so a documented figure is not what was seen: where a corridor has
# been paid, what was seen is used, and where it has not, the documented figure is an estimate.
_DOC_LOCAL = {1: "AUD BRL EUR GBP HKD IDR MXN MYR NOK NZD PHP PLN SGD",
              2: "AED ARS CHF CLP COP CZK DKK INR KES LKR NGN NPR PKR SEK THB VND", 3: "HUF ILS RON", 7: "JPY",
              0: "CAD USD"}
DOCUMENTED_LOCAL_FEE_USD: dict[str, Decimal] = {cur: Decimal(usd) for usd, curs in _DOC_LOCAL.items()
                                                for cur in curs.split()}
DOCUMENTED_OTHER_LOCAL_FEE_USD = Decimal(5)          # "$5 per transfer for transfers in all other currencies"
DOCUMENTED_CNY_RATE = Decimal("0.001")               # "0.10% for transfers in CNY"
DOCUMENTED_SWIFT_FEE_USD = {"SHARED": Decimal(15), "PAYER": Decimal(25)}   # SHA and OUR
SWIFT_OPTION = "PAYER"
SWIFT_OPTION_WHY = ("With the shared option (SHA) the owner receives the amount less whatever the banks on the way "
                    "take, which nobody can state beforehand. With the payer option (OUR) the fee is higher and "
                    "the amount that arrives is the amount stated. The plan always uses the payer option, so an "
                    "owner is never told an amount that the agent cannot keep.")
INCOMING_FEE_RATE = Decimal("0.003")                  # seen on every deposit on the sandbox (docs/AIRWALLEX_FLOW.md)

# Flight time in business days, from each country's payout guide: (scheme, fewest days, most days).
DOCUMENTED_FLIGHT: dict[str, tuple[str, int, int]] = {
    "MX": ("SPEI", 0, 1), "PH": ("InstaPay or PESONet", 0, 1), "JP": ("Zengin", 0, 1),
    "GB": ("Faster Payments", 0, 1), "DE": ("SEPA Instant or SEPA", 0, 2), "CA": ("EFT", 0, 1),
    "IN": ("NEFT, IMPS or RTGS", 0, 2), "AU": ("BECS", 0, 2), "HK": ("FPS", 0, 1), "SG": ("FAST", 0, 1),
    "KR": ("HOFINET", 0, 1), "BR": ("TED or PIX", 0, 1), "CH": ("SIC", 0, 1), "IL": ("Masav", 1, 2),
    "TH": ("PromptPay", 0, 1), "NZ": ("Direct Credit", 0, 1), "ID": ("SKN or BI-FAST", 0, 2),
    "MY": ("DuitNow", 0, 2), "AE": ("UAEFTS", 2, 3), "CN": ("UnionPay or NUCC", 0, 1),
}
DOCUMENTED_FLIGHT.update({c: ("SEPA Instant or SEPA", 0, 2) for c in EUROZONE if c not in ("DE",)})
SWIFT_FLIGHT = (0, 3)                                 # every guide read gives 0 to 3 business days for SWIFT

# What the guides say a local payout cannot do. A claim over the limit is planned by SWIFT.
LOCAL_LIMITS: dict[str, dict] = {
    "JP": {"amount": 1_000_000, "currency": "JPY", "text": "Zengin: at most 1,000,000 JPY for one payout"},
    "GB": {"amount": 1_000_000, "currency": "GBP", "text": "Faster Payments: at most 1,000,000 GBP"},
    "TH": {"amount": 500_000, "currency": "THB", "text": "PromptPay: at most 500,000 THB"},
    "SG": {"amount": 200_000, "currency": "SGD", "text": "FAST: at most 200,000 SGD"},
    "HK": {"amount": 10_000_000, "currency": "HKD", "text": "FPS: at most 10,000,000 HKD"},
    "MX": {"amount": 25_000, "currency": "USD", "text": "a monthly limit of 25,000 USD for each beneficiary"},
    "BR": {"amount": 10_000, "currency": "USD", "text": "a monthly limit of 10,000 USD for each beneficiary"},
    "IL": {"amount": 25_000, "currency": "USD", "text": "at most 25,000 USD to an individual"},
}
# Local rails the guide keeps for another purpose. China's local payout is described for e-commerce sellers and
# needs "declarant information and relevant order information", so it is not planned for returning money owed.
LOCAL_NOT_FOR_THIS = {"CN": "The guide describes local CNY payouts for e-commerce sellers only, and they must "
                            "be supported by declarant and order information."}

# Whether Airwallex converts US dollars into a balance that is held (so one conversion can fund many payouts), as
# its currency table says. What the sandbox did when a conversion was tried is kept in the cache and wins.
DOCUMENTED_HOLD = frozenset("AUD CNY USD HKD EUR GBP CAD SGD CHF NZD JPY THB KRW MXN BRL ILS".split())
DOCUMENTED_NO_HOLD = frozenset("PHP INR IDR SAR".split())

SANDBOX_RATE_LIMIT = 10      # requests a second on one endpoint ("Sandbox: 20 / 10 / 10": global, endpoint, at once)
NOT_PAYABLE = "Not payable by transfer: stays with the State process"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def currency_of(country: str) -> str | None:
    return CURRENCY_OF.get((country or "").upper())


def calendar_days(business_days: int) -> int:
    """Business days as calendar days, counting a weekend for every five."""
    return int(math.ceil(business_days * 7 / 5))


def documented_local_fee(currency: str, usd: Decimal | None = None) -> Decimal:
    """Airwallex's published price for one local payout in this currency, in US dollars."""
    if currency == "CNY" and usd is not None:
        return (usd * DOCUMENTED_CNY_RATE).quantize(Decimal("0.01"))
    return DOCUMENTED_LOCAL_FEE_USD.get(currency, DOCUMENTED_OTHER_LOCAL_FEE_USD)


# ---- discovery on the live sandbox -----------------------------------------------------------------------------

def _schema_summary(answer: dict, at: str) -> dict:
    fields = answer.get("fields") or []
    required, clearing = [], []
    for f in fields:
        path = (f.get("path") or f.get("key") or "").replace("beneficiary.", "")
        if path.endswith("local_clearing_system"):
            clearing = [x for x in ((f.get("rule") or {}).get("pattern") or "").split("|") if x]
        if f.get("required"):
            required.append(path)
    return {"available": True, "fields": len(fields), "required": required, "clearing": clearing, "at": at}


def _ask_schema(client, country: str, currency: str, method: str, at: str) -> dict:
    from . import airwallex as awx

    try:
        return _schema_summary(client.beneficiary_schema(country, currency, method), at)
    except awx.AirwallexError as err:
        if err.code == "SCHEMA_DEFINITION_NOT_FOUND" or err.status in (400, 404):
            return {"available": False, "answer": err.code or f"HTTP {err.status}", "at": at}
        return {"available": None, "answer": err.code or f"HTTP {err.status}", "at": at}
    except Exception as err:      # a network failure: not known, to be asked again
        return {"available": None, "answer": type(err).__name__, "at": at}


def per_usd(rate: Any, pair: str | None, currency: str) -> float | None:
    """A rate as units of `currency` for one US dollar. Airwallex quotes some pairs the other way round (GBPUSD,
    EURUSD, AUDUSD: US dollars for one unit), and says so in `currency_pair`; those are turned over here, so
    every rate in the cache multiplies US dollars into the currency."""
    if rate in (None, "", 0):
        return None
    value = Decimal(str(rate))
    if pair and pair.upper() == f"{currency}USD":
        value = Decimal(1) / value
    return float(value.quantize(Decimal("0.00000001")) if value < 1000 else value.quantize(Decimal("0.0001")))


def _quote_row(quote: dict, sell: int, validity: str, at: str, currency: str | None = None) -> dict:
    currency = currency or quote.get("buy_currency") or ""
    pair = quote.get("currency_pair")
    return {"sell_usd": sell, "validity": validity, "client_rate": per_usd(quote.get("client_rate"), pair, currency),
            "mid_rate": per_usd(quote.get("mid_rate"), pair, currency),
            "awx_rate": per_usd(quote.get("awx_rate"), pair, currency),
            "quoted": {"pair": pair, "client_rate": quote.get("client_rate"), "mid_rate": quote.get("mid_rate")}, "at": at}


def discover_currency(client, currency: str, *, sizes=LADDER, validities=VALIDITIES, clock=now_iso) -> dict:
    """Airwallex's indicative rate for US dollars into `currency`, a real quote at each size, a real quote at each
    lock length, and a quote back into US dollars (what turning unspent money back would cost)."""
    from . import airwallex as awx

    out: dict[str, Any] = {"currency": currency, "at": clock()}
    if currency == "USD":
        return {**out, "quotable": True, "rate": 1.0, "ladder": [], "locks": [], "back": None}
    try:
        answer = client.indicative_rate("USD", currency)
        out["rate"] = per_usd(answer["rate"], answer.get("currency_pair"), currency)
        out["quoted_pair"] = answer.get("currency_pair")
    except (awx.AirwallexError, KeyError, TypeError, ValueError) as err:
        out["rate"] = None
        out["rate_answer"] = getattr(err, "message", None) or getattr(err, "code", None) or type(err).__name__
    ladder, locks = [], []
    for sell in sizes:
        try:
            ladder.append(_quote_row(client.create_quote("USD", currency, sell_amount=sell, validity="MIN_1"), sell,
                                     "MIN_1", clock(), currency))
        except awx.AirwallexError as err:
            out["quote_answer"] = err.message or err.code
            break
    if ladder:
        for validity in validities:
            try:
                locks.append(_quote_row(client.create_quote("USD", currency, sell_amount=VALIDITY_SIZE,
                                                            validity=validity), VALIDITY_SIZE, validity, clock(), currency))
            except awx.AirwallexError:
                continue
        try:
            bought = Decimal(str(ladder[2]["client_rate"])) * VALIDITY_SIZE if len(ladder) > 2 else None
            if bought:
                back = client.create_quote(currency, "USD", sell_amount=float(bought), validity="MIN_1")
                out["back"] = {"sell_local": float(bought), "buy_usd": back.get("buy_amount"),
                               "quoted": {"pair": back.get("currency_pair"), "client_rate": back.get("client_rate"),
                                          "mid_rate": back.get("mid_rate")}, "at": clock()}
        except awx.AirwallexError:
            out["back"] = None
    out.update({"quotable": bool(ladder), "ladder": ladder, "locks": locks})
    out.setdefault("back", None)
    return out


def observed_fees(transfers: list[dict]) -> dict:
    """What Airwallex charged on transfers this account has made, by rail and currency paid out:
    {"LOCAL:MXN": {"amount", "currency", "usd", "seen", "last"}, "SWIFT:PAYER": {...}}. A local payout funded from
    a held balance is charged in that currency; `usd` is then left out unless the fee was charged in US dollars."""
    seen: dict[str, dict] = {}
    for t in transfers:
        if t.get("fee_amount") is None:
            continue
        method = t.get("transfer_method") or LOCAL
        key = f"SWIFT:{t.get('swift_charge_option') or 'SHARED'}" if method == SWIFT else f"LOCAL:{t.get('transfer_currency')}"
        fee_currency = t.get("fee_currency") or t.get("source_currency")
        slot = seen.setdefault(key, {"seen": 0, "by_fee_currency": {}})
        slot["seen"] += 1
        held = slot["by_fee_currency"].setdefault(fee_currency, {"amount": str(t["fee_amount"]), "last": t.get("created_at"),
                                                                 "seen": 0})
        held["seen"] += 1
    return seen


def discover(client, countries: list[str], *, known: dict | None = None, try_conversions: bool = False,
             progress: Callable[[str], None] | None = None, clock=now_iso, max_age_hours: float | None = None) -> dict:
    """Ask the live sandbox about every country in `countries` and every currency they use. `known` is an earlier
    result: what it already holds is kept and not asked again (unless older than `max_age_hours`), so discovery
    runs once and is reused. The client paces its own calls under the sandbox's limit of ten a second for one
    endpoint, and a 429 is retried."""
    from . import airwallex as awx

    known = known or {}
    out = {"base_url": awx.SANDBOX_BASE_URL, "started_at": clock(), "corridors": dict(known.get("corridors") or {}),
           "currencies": dict(known.get("currencies") or {}), "conversions": dict(known.get("conversions") or {}),
           "observed_fees": dict(known.get("observed_fees") or {}), "wallet_currencies": known.get("wallet_currencies") or []}

    def fresh(row: dict | None) -> bool:
        if not row or not row.get("at"):
            return False
        if max_age_hours is None:
            return True
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row["at"])
        except ValueError:
            return False
        return age.total_seconds() < max_age_hours * 3600

    def say(text: str) -> None:
        if progress:
            progress(text)

    for country in countries:
        country = country.upper()
        held = out["corridors"].get(country)
        if fresh(held) and all((held.get(k) or {}).get("available") is not None for k in ("local", "swift", "swift_usd")):
            continue
        currency = currency_of(country)
        at = clock()
        row: dict[str, Any] = {"country": country, "currency": currency, "at": at}
        none = {"available": False, "answer": "no currency of its own is known for this country", "at": at}
        row["local"] = _ask_schema(client, country, currency, LOCAL, at) if currency else none
        if currency == "USD":
            row["swift"] = _ask_schema(client, country, "USD", SWIFT, at)
            row["swift_usd"] = row["swift"]
        else:
            row["swift"] = _ask_schema(client, country, currency, SWIFT, at) if currency else none
            row["swift_usd"] = _ask_schema(client, country, "USD", SWIFT, at)
        out["corridors"][country] = row
        say(f"{country} {currency or '-'}: local {row['local']['available']}, SWIFT {row['swift']['available']}, "
            f"SWIFT in USD {row['swift_usd']['available']}")
    wanted = sorted({r["currency"] for r in out["corridors"].values()
                     if r.get("currency") and ((r["local"].get("available")) or (r["swift"].get("available")))})
    for currency in wanted:
        if fresh(out["currencies"].get(currency)):
            continue
        out["currencies"][currency] = discover_currency(client, currency, clock=clock)
        say(f"{currency}: rate {out['currencies'][currency].get('rate')}, "
            f"{len(out['currencies'][currency].get('ladder') or [])} quotes")
    try:
        out["wallet_currencies"] = sorted({b.get("currency") for b in client.balances() if b.get("currency")})
    except Exception:
        pass
    if try_conversions:      # one US dollar into each wallet currency: the only way to learn what can be held
        for currency in out["wallet_currencies"]:
            if currency == "USD" or currency in out["conversions"] or not (out["currencies"].get(currency) or {}).get("quotable"):
                continue
            try:
                done = client.create_conversion(awx.new_request_id(), "USD", currency, sell_amount=1)
                out["conversions"][currency] = {"held": True, "status": done.get("status"), "at": clock()}
            except awx.AirwallexError as err:
                out["conversions"][currency] = {"held": False, "answer": (err.message or err.code or "")[:160], "at": clock()}
            say(f"{currency}: converting into a held balance {'works' if out['conversions'][currency]['held'] else 'is refused'}")
    try:
        transfers = client._pages("/api/v1/transfers", {"page_size": 200}, max_pages=3)
        out["observed_fees"] = {**out["observed_fees"], **observed_fees(transfers)}
        out["observed_fees_at"] = clock()
    except Exception:
        pass
    out["fetched_at"] = clock()
    return out


def save(found: dict, path: Path | str = FILE) -> None:
    Path(path).write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")


def load(path: Path | str = FILE) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except ValueError:
        return None


# ---- what a plan reads from the cache --------------------------------------------------------------------------

def can_hold(found: dict, currency: str) -> tuple[bool | None, str]:
    """(whether US dollars can be converted into a held balance of `currency`, how that is known)."""
    if currency == "USD":
        return True, "the money is already in US dollars"
    seen = (found.get("conversions") or {}).get(currency)
    if seen is not None:
        return bool(seen.get("held")), ("converted on the sandbox" if seen.get("held") else
                                        "the sandbox refused the conversion")
    if currency in DOCUMENTED_NO_HOLD:
        return False, "Airwallex's currency table: convert and pay only"
    if currency in DOCUMENTED_HOLD:
        return True, "Airwallex's currency table: can be held (not tried on the sandbox)"
    return None, "not known"


def payout_fee(found: dict, method: str, currency: str) -> dict:
    """The fee the plan expects for one payout, in US dollars, with where the figure comes from. `basis` is
    "observed" (Airwallex charged it on a transfer this account made), or "estimate" (the published price for a
    corridor that has never been paid from this account)."""
    seen = found.get("observed_fees") or {}
    if method == SWIFT:
        row = seen.get(f"SWIFT:{SWIFT_OPTION}")
        doc = DOCUMENTED_SWIFT_FEE_USD[SWIFT_OPTION]
        usd = (row or {}).get("by_fee_currency", {}).get("USD")
        if usd:
            return {"usd": str(Decimal(usd["amount"]).quantize(Decimal("0.01"))), "basis": "observed",
                    "documented_usd": str(doc), "seen": row["seen"],
                    "text": f"Airwallex charged this on {row['seen']} SWIFT transfer{'s' if row['seen'] != 1 else ''} "
                            "made from this sandbox account with the payer option."}
        return {"usd": str(doc), "basis": "estimate", "documented_usd": str(doc), "seen": 0,
                "text": "An estimate: Airwallex's published price for a SWIFT transfer with the payer option. "
                        "None has been made from this account."}
    row = seen.get(f"LOCAL:{currency}")
    doc = documented_local_fee(currency)
    if row:
        by = row["by_fee_currency"]
        if "USD" in by:
            usd = Decimal(by["USD"]["amount"])
            note = ""
        else:        # charged in the local currency, from a held balance: its worth in US dollars at the mid rate
            cur, held = next(iter(by.items()))
            mid = _mid(found, cur)
            usd = (Decimal(held["amount"]) / mid) if mid else doc
            note = f" ({Decimal(held['amount']):,.2f} {cur} at the mid rate)"
        return {"usd": str(usd.quantize(Decimal("0.01"))), "basis": "observed", "documented_usd": str(doc),
                "seen": row["seen"],
                "text": f"Airwallex charged this on {row['seen']} local payout{'s' if row['seen'] != 1 else ''} in "
                        f"{currency} made from this sandbox account{note}. Its published price is {doc:,.2f} USD."}
    return {"usd": str(doc.quantize(Decimal("0.01"))), "basis": "estimate", "documented_usd": str(doc), "seen": 0,
            "text": f"An estimate: Airwallex's published price for a local payout in {currency}. No payout in "
                    f"{currency} has been made from this account, and on the sandbox the fee charged has differed "
                    "from the published price."}


def _mid(found: dict, currency: str) -> Decimal | None:
    row = (found.get("currencies") or {}).get(currency) or {}
    for q in row.get("ladder") or []:
        if q.get("mid_rate"):
            return Decimal(str(q["mid_rate"]))
    return Decimal(str(row["rate"])) if row.get("rate") else None


def nearest_quote(found: dict, currency: str, usd: float) -> dict | None:
    """The real quote taken at the size nearest to `usd` (nearest by ratio)."""
    ladder = [q for q in ((found.get("currencies") or {}).get(currency) or {}).get("ladder") or [] if q.get("client_rate")]
    if not ladder:
        return None
    usd = max(float(usd), 0.01)
    return min(ladder, key=lambda q: abs(math.log(q["sell_usd"] / usd)))


def flight(country: str, method: str) -> dict:
    """How long the rail takes, in business days, and whether that was read in the country's guide."""
    if method == SWIFT:
        return {"min": SWIFT_FLIGHT[0], "max": SWIFT_FLIGHT[1], "scheme": "SWIFT", "basis": "documented"}
    if country in DOCUMENTED_FLIGHT:
        scheme, low, high = DOCUMENTED_FLIGHT[country]
        return {"min": low, "max": high, "scheme": scheme, "basis": "documented"}
    return {"min": SWIFT_FLIGHT[0], "max": SWIFT_FLIGHT[1], "scheme": "local rails", "basis": "estimate",
            "text": "The guide for this country was not read, so the SWIFT figure is used as the estimate."}


def routes(found: dict, country: str) -> dict:
    """The ways money can reach `country`, in the order the plan prefers them: local rails in the local currency,
    SWIFT in the local currency, SWIFT in US dollars. Each says whether Airwallex returned a schema for it."""
    row = (found.get("corridors") or {}).get(country)
    currency = currency_of(country)
    if row is None:
        return {"country": country, "currency": currency, "known": False, "options": []}
    quotable = currency == "USD" or bool(((found.get("currencies") or {}).get(currency) or {}).get("quotable"))
    options = []
    local = row.get("local") or {}
    if local.get("available") and quotable and country not in LOCAL_NOT_FOR_THIS:
        options.append({"method": LOCAL, "currency": currency, "required": local.get("required") or [],
                        "clearing": local.get("clearing") or []})
    swift = row.get("swift") or {}
    if swift.get("available") and quotable and currency:
        options.append({"method": SWIFT, "currency": currency, "required": swift.get("required") or []})
    swift_usd = row.get("swift_usd") or {}
    if swift_usd.get("available") and currency != "USD":
        options.append({"method": SWIFT, "currency": "USD", "required": swift_usd.get("required") or []})
    return {"country": country, "currency": currency, "known": True, "options": options,
            "local_schema": local.get("available"), "local_set_aside": LOCAL_NOT_FOR_THIS.get(country),
            "quotable": quotable, "at": row.get("at")}


def spread_by_size(found: dict, currency: str) -> list[dict]:
    """How far the client rate sits from the mid rate at each size a real quote was taken at, in percent."""
    out = []
    for q in ((found.get("currencies") or {}).get(currency) or {}).get("ladder") or []:
        if not q.get("client_rate") or not q.get("mid_rate"):
            continue
        client, mid = Decimal(str(q["client_rate"])), Decimal(str(q["mid_rate"]))
        out.append({"sell_usd": q["sell_usd"], "client_rate": q["client_rate"], "mid_rate": q["mid_rate"],
                    "spread_percent": float(((mid - client) / mid * 100).quantize(Decimal("0.0001"))), "at": q.get("at")})
    return out


def lock_cost(found: dict, currency: str) -> dict | None:
    """What a one-hour lock costs against a one-minute quote at the same size, in percent, as quoted."""
    locks = {q["validity"]: q for q in ((found.get("currencies") or {}).get(currency) or {}).get("locks") or []
             if q.get("client_rate")}
    if "MIN_1" not in locks or "HR_1" not in locks:
        return None
    short, hour = Decimal(str(locks["MIN_1"]["client_rate"])), Decimal(str(locks["HR_1"]["client_rate"]))
    return {"min_1": locks["MIN_1"]["client_rate"], "hr_1": locks["HR_1"]["client_rate"],
            "min_15": (locks.get("MIN_15") or {}).get("client_rate"),
            "percent": float(((short - hour) / short * 100).quantize(Decimal("0.0001"))), "at": locks["HR_1"].get("at")}


def round_trip(found: dict, currency: str) -> dict | None:
    """What it costs to buy the currency and turn it straight back into US dollars, in percent, from two real
    quotes: the price of converting money for an owner who is then not paid."""
    row = (found.get("currencies") or {}).get(currency) or {}
    back = row.get("back")
    if not back or not back.get("buy_usd"):
        return None
    lost = (Decimal(VALIDITY_SIZE) - Decimal(str(back["buy_usd"]))) / Decimal(VALIDITY_SIZE) * 100
    return {"sold_usd": VALIDITY_SIZE, "back_usd": back["buy_usd"], "percent": float(lost.quantize(Decimal("0.01"))),
            "at": back.get("at")}
