"""The whole book: how to pay everything one holder owes to owners abroad.

A book is everything one holder reported in California's public file for owners whose last known address is in
another country: one line per property with the owner's country, the amount and the kind of money. No owner's
name or street is in it. `scripts/make_books.py` writes the books of every holder to data/books.parquet.

`plan` works out, for one book, under the holder's own limits (the small-claim line, the tolerance, the handover
date and the days an owner needs to send a document):

  the route of every claim     local rails where Airwallex returned a schema for the country and currency and the
                               claim is inside what the rail carries; otherwise SWIFT; otherwise no transfer, and
                               the property stays with the State process
  the cost                     Airwallex's incoming fee and payout fee on every claim, who bears them under the
                               fee rule, and which claims are smaller than the fees to send them
  what owners would receive    in their own currency, at rates Airwallex quoted
  the funding                  what the holder funds in US dollars, and for each currency whether to convert each
                               payment as it is approved or once for the batch, from real quotes at several sizes
  the order of work            which corridors can still finish before the handover, most dollars a day first

Every figure is arithmetic in code on the book and on what corridors.py holds from the live sandbox and from
Airwallex's published pages. No language model takes part. The plan is computed from public figures: no holder
has asked for one.
"""
from __future__ import annotations

import statistics
import threading
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import corridors as co
from . import handover as ho
from . import holders
from . import instructions as ins
from . import property_types as pt
from .countries import COUNTRIES

BOOKS_PATH = Path(__file__).resolve().parents[2] / "data" / "books.parquet"
STATEMENT = ("Computed from this holder's figures in California's public file and from Airwallex's sandbox. The "
             "holder did not ask for this plan.")
UNPLACED = "other"
SPREAD_NOISE = Decimal("0.002")     # percentage points: spreads closer than this are the same spread


# ---- the books, read from California's file ---------------------------------------------------------------------

def build(con) -> list[tuple[str, str, float, str]]:
    """(holder as written, owner country, dollars, property type) for every property held for an owner abroad,
    read from the register through `con`. Each property is one row. A property with owners in more than one
    country abroad is planned once, to the country that comes first in the alphabet."""
    from .registers import build_away

    build_away(con)
    rows = con.execute("""
        with props as (select source, record_id, min(shown) country, max(amount) amount
                       from totals_away where kind = 'abroad' group by 1, 2)
        select coalesce(min(r.holder_name), ''), p.country, p.amount, coalesce(min(r.property_type), '')
        from records r join props p on r.source = p.source and r.record_id = p.record_id
        group by p.source, p.record_id, p.country, p.amount""").fetchall()
    con.execute("drop table totals_away")
    return [(h, c, float(a or 0), t) for h, c, a, t in rows]


def write(rows: list[tuple[str, str, float, str]], path: Path | str = BOOKS_PATH) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols = list(zip(*rows)) if rows else [[], [], [], []]
    table = pa.table({"holder": pa.array(cols[0], pa.string()), "country": pa.array(cols[1], pa.string()),
                      "amount": pa.array(cols[2], pa.float64()), "property_type": pa.array(cols[3], pa.string())})
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(path))


class Books:
    """Every holder's book, held in memory. Holders are grouped the way the "For holders" screen groups them
    (holders.key and holders.FAMILIES), and a holder whose name could be a person's is never listed or opened."""

    def __init__(self, rows: list[tuple[str, str, float, str]]):
        self._claims: dict[str, list[tuple[str, int, str]]] = {}
        written: dict[str, dict[str, int]] = {}
        families: dict[str, str | None] = {}
        for holder, country, amount, kind in rows:
            if not holders.key(holder):
                continue
            shown = holders.family(holder)
            k = shown or holders.key(holder)
            families[k] = shown
            self._claims.setdefault(k, []).append((country, int(round(amount * 100)), kind))
            slot = written.setdefault(k, {})
            slot[holder] = slot.get(holder, 0) + 1
        self._index: dict[str, dict] = {}
        for k, claims in self._claims.items():
            names = written[k]
            commonest = sorted(names, key=lambda w: (-names[w], w))[0]
            name = families[k] or commonest
            self._index[k] = {"key": k, "name": name, "properties": len(claims),
                              "amount": round(sum(c[1] for c in claims) / 100, 2),
                              "countries": len({c[0] for c in claims}),
                              "listable": bool(families[k]) or all(holders.listable(w) for w in names),
                              "kind": holders.kind_of(name)}

    @classmethod
    def load(cls, path: Path | str = BOOKS_PATH) -> "Books":
        import pyarrow.parquet as pq

        table = pq.read_table(str(path))
        return cls(list(zip(*(table.column(c).to_pylist() for c in ("holder", "country", "amount", "property_type")))))

    def top(self, limit: int = 12) -> list[dict]:
        rows = [r for r in self._index.values() if r["listable"]]
        return [self._public(r) for r in sorted(rows, key=lambda r: (-r["amount"], r["name"]))[:limit]]

    def find(self, text: str, limit: int = 12) -> list[dict]:
        needle = holders.key(text)
        if len(needle.replace(" ", "")) < 2:
            return []
        rows = [r for r in self._index.values() if r["listable"] and needle in holders.key(r["name"] + " " + r["key"])]
        return [self._public(r) for r in sorted(rows, key=lambda r: (-r["amount"], r["name"]))[:limit]]

    @staticmethod
    def _public(row: dict) -> dict:
        return {"key": row["key"], "name": row["name"], "properties": row["properties"], "amount": row["amount"],
                "countries": row["countries"], "kind": holders.KIND_LABELS[row["kind"]]}

    def get(self, key: str) -> tuple[dict, list[tuple[str, int, str]]] | None:
        """(the holder's line, its claims) for a holder that may be named, or None."""
        row = self._index.get(key) or self._index.get(holders.family(key) or holders.key(key))
        if row is None or not row["listable"]:
            return None
        return self._public(row), self._claims[row["key"]]


_books: dict[str, Any] = {}
_books_lock = threading.Lock()


def books(path: Path | str = BOOKS_PATH) -> Books | None:
    """The books file, read once for each file as it stands on disk. None when it has not been made."""
    path = Path(path)
    if not path.exists():
        return None
    stamp = (str(path), path.stat().st_mtime_ns)
    with _books_lock:
        if _books.get("stamp") != stamp:
            _books.update({"stamp": stamp, "books": Books.load(path)})
        return _books["books"]


# ---- the plan --------------------------------------------------------------------------------------------------

def _usd(cents: int) -> float:
    return round(cents / 100, 2)


def _cents(text: Any) -> int:
    return int((Decimal(str(text)) * 100).to_integral_value())


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}" if abs(cents) < 100_000_00 else f"${cents / 100:,.0f}"


def _decimals(currency: str) -> int:
    return 0 if currency in co.ZERO_DECIMAL else 2


def _minor(usd_cents: int, rate_micro: int, currency: str) -> int:
    """US dollar cents at a rate, as minor units of `currency` (whole units for a currency with no decimals),
    rounded half up."""
    scale = 10 ** _decimals(currency)
    return (usd_cents * rate_micro * scale + 50_000_000) // 100_000_000


def _local(minor: int, currency: str) -> float:
    return minor / (10 ** _decimals(currency))


def _micro(rate: Any) -> int:
    return int((Decimal(str(rate)) * 1_000_000).to_integral_value())


def _country_name(code: str) -> str:
    return (COUNTRIES.get(code) or {}).get("name") or ("Country code that cannot be placed" if code == UNPLACED else code)


def clean_inputs(raw: dict | None, today: date | None = None) -> dict:
    """The four inputs of a plan in stored form. Raises ValueError, in words for the screen."""
    raw = raw or {}
    today = today or ho.today()
    rules = ins.clean({k: raw[k] for k in ("tolerance_percent", "small_claim_usd") if raw.get(k) not in (None, "")})
    setting = ho.clean({k: raw.get(k) for k in ("handover_date", "document_days")}, today)
    return {"tolerance_percent": rules["tolerance_percent"], "small_claim_usd": rules["small_claim_usd"],
            "handover_date": setting["handover_date"], "document_days": setting["document_days"]}


def split(cents: int, fee: int, line: int) -> dict:
    """The fee rule on one claim, in US dollar cents: what the holder sends, what is left after Airwallex's
    incoming fee, and who bears the fees. Airwallex takes 0.3 percent of what arrives and `fee` for the payout.
    Below the small-claim line the holder sends the claim plus both fees, so the whole claim is left for the
    owner. From the line up the holder sends the claim and the fees come out of it. A claim whose fees are at
    least the claim itself is not sent at all."""
    incoming = (cents * 3 + 500) // 1000
    if incoming + fee >= cents:
        return {"too_small": True, "incoming": incoming, "fee": fee, "sends": 0, "net": 0, "bearer": None}
    if cents < line:
        sends = -(-(cents + fee) * 1000 // 997)
        return {"too_small": False, "incoming": (sends * 3 + 500) // 1000, "fee": fee, "sends": sends,
                "net": sends - (sends * 3 + 500) // 1000, "bearer": "holder"}
    return {"too_small": False, "incoming": incoming, "fee": fee, "sends": cents, "net": cents - incoming,
            "bearer": "claim"}


def _route_for(options: list[dict], country: str, cents: int, rate_micro: int | None) -> tuple[dict | None, bool]:
    """(the route for one claim, whether it was moved off local rails by the rail's limit)."""
    if not options:
        return None, False
    first = options[0]
    if first["method"] != co.LOCAL:
        return first, False
    limit = co.LOCAL_LIMITS.get(country)
    if limit:
        if limit["currency"] == "USD":
            over = cents > limit["amount"] * 100
        else:
            over = bool(rate_micro) and _minor(cents, rate_micro, limit["currency"]) > limit["amount"] * 10 ** _decimals(limit["currency"])
        if over:
            return (options[1] if len(options) > 1 else None), True
    return first, False


def plan(holder: dict, claims: list[tuple[str, int, str]], found: dict, raw_inputs: dict | None = None,
         today: date | None = None) -> dict:
    """The plan for one book. `claims` are (owner country, US dollar cents, property type)."""
    today = today or ho.today()
    inputs = clean_inputs(raw_inputs, today)
    line = _cents(inputs["small_claim_usd"])
    tolerance = Decimal(inputs["tolerance_percent"])
    doc_days = int(inputs["document_days"])
    left = (date.fromisoformat(inputs["handover_date"]) - today).days
    rate_in = co.INCOMING_FEE_RATE

    by_country: dict[str, list[tuple[int, str]]] = {}
    for country, cents, kind in claims:
        by_country.setdefault(country, []).append((cents, kind))

    rows: list[dict] = []
    fund: dict[str, dict] = {}          # by currency: the claims that are planned, for the funding decision
    money_kinds: dict[str, list] = {}
    for kind_written in {k for _, _, k in claims}:
        money_kinds[kind_written] = [kind_written, 0, 0.0]
    for _, cents, kind in claims:
        money_kinds[kind][1] += 1
        money_kinds[kind][2] += cents / 100

    for country, items in by_country.items():
        info = co.routes(found, country) if country != UNPLACED else {"options": [], "currency": None, "known": True}
        options = info["options"]
        currency = info.get("currency")
        cur_row = (found.get("currencies") or {}).get(currency or "") or {}
        rate = cur_row.get("rate")
        rate_micro = _micro(rate) if rate else None
        fees = {(o["method"], o["currency"]): co.payout_fee(found, o["method"], o["currency"]) for o in options}
        row: dict[str, Any] = {
            "country": country, "name": _country_name(country), "currency": currency, "owners": len(items),
            "usd": 0, "no_cash": 0, "local": {"owners": 0, "usd": 0}, "swift": {"owners": 0, "usd": 0},
            "unpayable": {"owners": 0, "usd": 0}, "too_small": {"owners": 0, "usd": 0, "would_cost": 0},
            "holder_bears": {"owners": 0, "usd": 0, "adds": 0}, "from_claim": {"owners": 0, "usd": 0, "fees": 0},
            "over_local_limit": {"owners": 0, "usd": 0}, "fees": 0, "planned": {"owners": 0, "usd": 0},
            "refusal": {"inside": 0, "inside_usd": 0, "outside": 0, "outside_usd": 0},
        }
        planned: list[tuple[int, int, int, dict]] = []     # (claim, net to send after the incoming fee, fee, route)
        payable_amounts: list[int] = []
        for cents, _kind in items:
            row["usd"] += cents
            if cents <= 0:
                row["no_cash"] += 1
                continue
            route, moved = _route_for(options, country, cents, rate_micro)
            if route is None:
                row["unpayable"]["owners"] += 1
                row["unpayable"]["usd"] += cents
                continue
            if moved:
                row["over_local_limit"]["owners"] += 1
                row["over_local_limit"]["usd"] += cents
            fee = _cents(fees[(route["method"], route["currency"])]["usd"])
            share = split(cents, fee, line)
            incoming = share["incoming"]
            if share["too_small"]:             # the fees are at least the claim itself: it is not sent
                row["too_small"]["owners"] += 1
                row["too_small"]["usd"] += cents
                row["too_small"]["would_cost"] += incoming + fee
                continue
            side = "local" if route["method"] == co.LOCAL else "swift"
            row[side]["owners"] += 1
            row[side]["usd"] += cents
            payable_amounts.append(cents)
            sends, net = share["sends"], share["net"]
            if share["bearer"] == "holder":    # the holder bears the fees, so the whole claim is left to convert
                row["holder_bears"]["owners"] += 1
                row["holder_bears"]["usd"] += cents
                row["holder_bears"]["adds"] += sends - cents
                row["fees"] += sends - cents
            else:
                row["from_claim"]["owners"] += 1
                row["from_claim"]["usd"] += cents
                row["from_claim"]["fees"] += incoming + fee
                row["fees"] += incoming + fee
            planned.append((cents, sends, net, {**route, "fee": fee}))
            owner_gets = net - fee
            # After a refusal Airwallex charges its payout fee again; that is the whole shortfall of a replacement.
            inside = owner_gets > 0 and Decimal(fee) / Decimal(owner_gets) * 100 <= tolerance
            row["refusal"]["inside" if inside else "outside"] += 1
            row["refusal"]["inside_usd" if inside else "outside_usd"] += cents

        # the route of the corridor, as the screen names it: the one most of its payable claims take
        if row["local"]["owners"] or row["swift"]["owners"]:
            method = co.LOCAL if row["local"]["owners"] >= row["swift"]["owners"] else co.SWIFT
        else:
            method = None
        option = next((o for o in options if o["method"] == method), None) if method else None
        flight = co.flight(country, method) if method else None
        needs = doc_days + co.calendar_days(flight["max"]) if flight else None
        in_time = bool(method) and left >= needs
        fee_info = fees.get((option["method"], option["currency"])) if option else None
        row.update({
            "route": method, "route_words": ("Local rails" if method == co.LOCAL else "SWIFT" if method else co.NOT_PAYABLE),
            "pay_currency": option["currency"] if option else None,
            "scheme": flight["scheme"] if flight else None, "flight": flight, "needs_days": needs, "in_time": in_time,
            "fee": fee_info, "fields_required": len(option.get("required") or []) if option else 0,
            "why_not_local": info.get("local_set_aside") or (
                None if method != co.SWIFT else
                "Airwallex returned no local schema for this country and currency." if not info.get("local_schema")
                else "Airwallex quotes no rate for this currency." if not info.get("quotable") else None),
            "why_unpayable": None if options or not row["unpayable"]["owners"] else (
                "The owner's country code in the file cannot be placed." if country == UNPLACED else
                "Airwallex returned no schema for this country by local rails or by SWIFT."),
            "median_usd": _usd(int(statistics.median(payable_amounts))) if payable_amounts else None,
            "large_usd": _usd(sorted(payable_amounts)[int(len(payable_amounts) * 0.9)]) if payable_amounts else None,
            "rate": rate, "schema_at": info.get("at"),
        })
        row["planned"] = {"owners": len(planned) if in_time else 0, "usd": sum(p[0] for p in planned) if in_time else 0}
        row["too_late"] = {"owners": 0 if in_time else len(planned), "usd": 0 if in_time else sum(p[0] for p in planned)}
        row["sends"] = sum(p[1] for p in planned) if in_time else 0
        # what the owners would receive in the currency paid, at the indicative rate
        gets_usd = sum(p[2] - p[3]["fee"] for p in planned)
        receive = None
        if planned and option:
            if option["currency"] == "USD":
                receive = {"amount": _usd(gets_usd), "currency": "USD"}
            elif rate_micro:
                receive = {"amount": _local(_minor(gets_usd, rate_micro, option["currency"]), option["currency"]),
                           "currency": option["currency"]}
        row["owners_receive"] = receive
        row["owners_receive_usd"] = gets_usd
        if in_time:
            for cents, sends, net, route in planned:
                slot = fund.setdefault(route["currency"], {"currency": route["currency"], "claims": [], "sends": 0})
                slot["claims"].append((net, route["fee"], route["method"]))
                slot["sends"] += sends
        rows.append(row)

    rows.sort(key=lambda r: (-r["usd"], r["country"]))
    funding = _funding(fund, found)
    order = _order(rows, inputs, left, today)
    totals = _totals(rows, funding, left)
    out = {
        "holder": holder, "statement": STATEMENT, "inputs": inputs, "days_left": left,
        "handover_words": ho.in_words(inputs["handover_date"]), "today": today.isoformat(),
        "corridors": [_public_row(r) for r in rows], "totals": totals, "funding": funding, "order": order,
        "kinds_of_money": pt.breakdown([tuple(v) for v in money_kinds.values()]),
        "discovered_at": found.get("fetched_at"), "sandbox": found.get("base_url"),
        "sources": co.SOURCES, "swift_option": {"option": co.SWIFT_OPTION, "why": co.SWIFT_OPTION_WHY},
        "incoming_fee_percent": float(rate_in * 100),
    }
    out["cards"] = cards(out)
    return out


def _public_row(r: dict) -> dict:
    """One corridor with its money in dollars and not cents."""
    def money(part: dict) -> dict:
        return {k: (_usd(v) if k != "owners" else v) for k, v in part.items()}

    out = {k: v for k, v in r.items() if k not in ("local", "swift", "unpayable", "too_small", "holder_bears",
                                                   "from_claim", "over_local_limit", "planned", "too_late", "refusal")}
    out.update({"usd": _usd(r["usd"]), "fees": _usd(r["fees"]), "sends": _usd(r["sends"]),
                "owners_receive_usd": _usd(r["owners_receive_usd"]),
                "local": money(r["local"]), "swift": money(r["swift"]), "unpayable": money(r["unpayable"]),
                "too_small": money(r["too_small"]), "holder_bears": money(r["holder_bears"]),
                "from_claim": money(r["from_claim"]), "over_local_limit": money(r["over_local_limit"]),
                "planned": money(r["planned"]), "too_late": money(r["too_late"]),
                "refusal": {"inside": r["refusal"]["inside"], "outside": r["refusal"]["outside"],
                            "inside_usd": _usd(r["refusal"]["inside_usd"]), "outside_usd": _usd(r["refusal"]["outside_usd"])}})
    payable = r["local"]["owners"] + r["swift"]["owners"]
    out["cost_per_payment"] = _usd(r["fees"] // payable) if payable else None
    out["_cents"] = r
    return out


def _funding(fund: dict[str, dict], found: dict) -> dict:
    """What the holder funds, and for each currency the cheaper way to convert, from real quotes.

    "Each" converts every payment by itself at the quote for its own size. "Batch" converts the sum once at the
    quote for the size of the batch and pays every owner from that balance. Both are worked out with quotes the
    sandbox really gave (corridors.nearest_quote), so a rate that depends on the amount shows up as a saving and
    a rate that does not shows up as none."""
    lines = []
    total_sends = sum(f["sends"] for f in fund.values())
    saving_cents = 0
    conversions_each = conversions_batch = 0
    for currency, slot in sorted(fund.items(), key=lambda kv: -kv[1]["sends"]):
        claims = slot["claims"]
        net_total = sum(c[0] for c in claims)
        line: dict[str, Any] = {"currency": currency, "payments": len(claims), "holder_sends": _usd(slot["sends"]),
                                "to_convert_usd": _usd(net_total)}
        if currency == "USD":
            line.update({"mode": "none", "mode_words": "Paid in US dollars: nothing is converted.", "saving_usd": 0.0,
                         "conversions": 0})
            lines.append(line)
            continue
        hold, how = co.can_hold(found, currency)
        batch_quote = co.nearest_quote(found, currency, net_total / 100)
        if batch_quote is None:
            line.update({"mode": "unknown", "mode_words": "No quote was taken for this currency.", "saving_usd": 0.0,
                         "conversions": len(claims)})
            lines.append(line)
            continue
        mid = Decimal(str(batch_quote["mid_rate"] or batch_quote["client_rate"]))
        sizes = co.spread_by_size(found, currency)
        # The quotes of one ladder are taken a moment apart, so the market can move between them. What a size
        # costs is how far its client rate sits from the mid rate of the same quote. Each payment is priced at
        # the batch quote's mid rate less the spread of the size nearest to it, which leaves only the effect of
        # the amount. Where every size carries the same spread, both ways buy the same and nothing is claimed
        # for the rounding of single conversions.
        spreads = {s_["sell_usd"]: Decimal(str(s_["spread_percent"])) for s_ in sizes}
        by_size = bool(spreads) and max(spreads.values()) - min(spreads.values()) > SPREAD_NOISE
        batch_minor = _minor(net_total, _micro(batch_quote["client_rate"]), currency)
        if by_size:
            each_minor = 0
            for net, _fee, _method in claims:
                q = co.nearest_quote(found, currency, net / 100)
                each_minor += _minor(net, _micro(mid * (1 - spreads[q["sell_usd"]] / 100)), currency)
        else:
            each_minor = batch_minor
        gain_minor = batch_minor - each_minor
        gain_usd = int((Decimal(gain_minor) / (10 ** _decimals(currency)) / mid * 100).to_integral_value())
        line.update({
            "can_hold": hold, "can_hold_basis": how,
            "quote": {"sell_usd": batch_quote["sell_usd"], "client_rate": batch_quote["client_rate"],
                      "mid_rate": batch_quote["mid_rate"], "at": batch_quote.get("at")},
            "each": {"buys": _local(each_minor, currency), "conversions": len(claims)},
            "batch": {"buys": _local(batch_minor, currency), "conversions": 1},
            "sizes": sizes, "rate_depends_on_size": by_size,
            "lock": co.lock_cost(found, currency), "round_trip": co.round_trip(found, currency),
        })
        if not hold:
            line.update({"mode": "each", "saving_usd": 0.0, "conversions": len(claims),
                         "mode_words": ("Each payment converts inside its own transfer: Airwallex does not convert US "
                                        f"dollars into a held balance of {currency} ({how}).") if hold is False else
                                       (f"Each payment converts inside its own transfer: whether {currency} can be held "
                                        "is not known, so nothing is converted ahead.")})
            conversions_each += len(claims)
            conversions_batch += len(claims)
        elif gain_minor >= 0:
            line.update({"mode": "batch", "saving_usd": _usd(gain_usd), "conversions": 1,
                         "mode_words": "Convert once for the batch and pay every owner from that balance."})
            saving_cents += gain_usd
            conversions_each += len(claims)
            conversions_batch += 1
        else:
            line.update({"mode": "each", "saving_usd": _usd(-gain_usd), "conversions": len(claims),
                         "mode_words": "Convert each payment as it is approved: the quotes for single payments were "
                                       "better than the quote for the batch."})
            saving_cents += -gain_usd
            conversions_each += len(claims)
            conversions_batch += len(claims)
        lines.append(line)
    return {"holder_funds_usd": _usd(total_sends), "incoming_fee_usd": _usd((total_sends * 3 + 500) // 1000),
            "currencies": lines, "saving_usd": _usd(saving_cents),
            "conversions_if_each": conversions_each, "conversions_planned": conversions_batch,
            "batch_currencies": sum(1 for x in lines if x["mode"] == "batch"),
            "each_currencies": sum(1 for x in lines if x["mode"] == "each"),
            "rate_depends_on_size": any(x.get("rate_depends_on_size") for x in lines),
            "ahead_of_approvals": "Nothing is converted for an owner before the holder has approved the claim. "
                                  "Money converted for an owner who is then not paid has to be turned back, and "
                                  "the two quotes for that are in each currency's line."}


def _order(rows: list[dict], inputs: dict, left: int, today: date) -> dict:
    """Which corridors to start with: the ones that can still finish before the handover, most dollars a day
    first. A corridor needs the days an owner needs to send a document and then the days its rail takes."""
    end = date.fromisoformat(inputs["handover_date"])
    work, dropped = [], []
    for r in rows:
        payable = r["local"]["usd"] + r["swift"]["usd"]
        if not r["route"] or not payable:
            continue
        line = {"country": r["country"], "name": r["name"], "route": r["route_words"], "scheme": r["scheme"],
                "owners": r["local"]["owners"] + r["swift"]["owners"], "usd": _usd(payable),
                "needs_days": r["needs_days"], "rail_days": f"{r['flight']['min']} to {r['flight']['max']} business days",
                "rail_basis": r["flight"]["basis"],
                "start_by": (end - timedelta(days=r["needs_days"])).isoformat(),
                "start_by_words": ho.in_words((end - timedelta(days=r["needs_days"])).isoformat()),
                "spare_days": left - r["needs_days"], "usd_per_day": _usd(payable // max(r["needs_days"], 1))}
        (work if r["in_time"] else dropped).append(line)
    work.sort(key=lambda x: (-x["usd_per_day"], x["country"]))
    dropped.sort(key=lambda x: (-x["usd"], x["country"]))
    for i, line in enumerate(work, 1):
        line["rank"] = i
    payments = sum(x["owners"] for x in work)
    return {"work": work, "dropped": dropped, "days_left": left, "document_days": int(inputs["document_days"]),
            "payments": payments,
            "machine": {"rate_limit": co.SANDBOX_RATE_LIMIT,
                        "transfer_creation_minutes": round(payments / co.SANDBOX_RATE_LIMIT / 60, 1),
                        "text": f"At the sandbox's limit of {co.SANDBOX_RATE_LIMIT} requests a second on one endpoint, "
                                f"creating {payments:,} transfers takes at least "
                                f"{round(payments / co.SANDBOX_RATE_LIMIT / 60, 1):,} minutes."}}


def _totals(rows: list[dict], funding: dict, left: int) -> dict:
    def add(part: str, field: str) -> int:
        return sum(r[part][field] for r in rows)

    planned_usd, planned_owners = add("planned", "usd"), add("planned", "owners")
    in_time = [r for r in rows if r["in_time"]]
    fees = sum(r["fees"] for r in in_time)
    holder_adds = sum(r["holder_bears"]["adds"] for r in in_time)
    return {
        "owners": sum(r["owners"] for r in rows), "usd": _usd(sum(r["usd"] for r in rows)),
        "countries": len(rows),
        "local": {"owners": add("local", "owners"), "usd": _usd(add("local", "usd")),
                  "countries": sum(1 for r in rows if r["route"] == co.LOCAL)},
        "swift": {"owners": add("swift", "owners"), "usd": _usd(add("swift", "usd")),
                  "countries": sum(1 for r in rows if r["route"] == co.SWIFT)},
        "unpayable": {"owners": add("unpayable", "owners"), "usd": _usd(add("unpayable", "usd")),
                      "countries": sum(1 for r in rows if not r["route"] and r["unpayable"]["owners"])},
        "too_small": {"owners": add("too_small", "owners"), "usd": _usd(add("too_small", "usd")),
                      "would_cost": _usd(add("too_small", "would_cost"))},
        "no_cash": {"owners": sum(r["no_cash"] for r in rows)},
        "over_local_limit": {"owners": add("over_local_limit", "owners"), "usd": _usd(add("over_local_limit", "usd"))},
        "too_late": {"owners": add("too_late", "owners"), "usd": _usd(add("too_late", "usd")),
                     "countries": sum(1 for r in rows if r["too_late"]["owners"])},
        "planned": {"owners": planned_owners, "usd": _usd(planned_usd),
                    "countries": sum(1 for r in rows if r["planned"]["owners"])},
        "holder_bears": {"owners": sum(r["holder_bears"]["owners"] for r in in_time),
                         "usd": _usd(sum(r["holder_bears"]["usd"] for r in in_time)), "adds": _usd(holder_adds)},
        "from_claim": {"owners": sum(r["from_claim"]["owners"] for r in in_time),
                       "fees": _usd(sum(r["from_claim"]["fees"] for r in in_time))},
        "cost": {"usd": _usd(fees), "percent": round(fees / planned_usd * 100, 2) if planned_usd else 0.0,
                 "borne_by_holder": _usd(holder_adds), "out_of_claims": _usd(fees - holder_adds)},
        "holder_funds_usd": funding["holder_funds_usd"],
        "refusal": {"inside": sum(r["refusal"]["inside"] for r in in_time),
                    "outside": sum(r["refusal"]["outside"] for r in in_time),
                    "inside_usd": _usd(sum(r["refusal"]["inside_usd"] for r in in_time)),
                    "outside_usd": _usd(sum(r["refusal"]["outside_usd"] for r in in_time))},
        "estimated_fee_corridors": sum(1 for r in rows if r.get("fee") and r["fee"]["basis"] == "estimate" and r["route"]),
        "observed_fee_corridors": sum(1 for r in rows if r.get("fee") and r["fee"]["basis"] == "observed" and r["route"]),
    }


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count:,} {one if count == 1 else (many or one + 's')}"


def _big(usd: float) -> str:
    return f"${usd:,.0f}" if usd >= 1000 else f"${usd:,.2f}"


def cards(p: dict) -> list[dict]:
    """The plan's decisions, each as a card of four short lines (what happened, what the limits allowed, what the
    agent did, the result in money), with the reasons folded behind "Why"."""
    t, i, f, o = p["totals"], p["inputs"], p["funding"], p["order"]
    line = float(i["small_claim_usd"])
    out = []
    out.append({
        "kind": "book_routes", "tone": "go", "title": "The routes",
        "happened": f"{_n(t['owners'], 'property', 'properties')} in {_n(t['countries'], 'country', 'countries')}, {_big(t['usd'])}.",
        "allowed": "Local rails where Airwallex has them, SWIFT where it does not, no transfer where it has neither.",
        "did": f"{_n(t['local']['countries'], 'country', 'countries')} by local rails, {t['swift']['countries']:,} by SWIFT, "
               f"{t['unpayable']['countries']:,} not payable by transfer.",
        "money": f"{_big(t['local']['usd'])} local, {_big(t['swift']['usd'])} SWIFT, {_big(t['unpayable']['usd'])} stays with the State.",
        "why": [
            "A route exists where the Airwallex sandbox returned a beneficiary schema for the country and currency "
            f"(asked {str(p.get('discovered_at') or '')[:10]}). A claim over what the local rail carries goes by SWIFT: "
            f"{_n(t['over_local_limit']['owners'], 'claim')}, {_big(t['over_local_limit']['usd'])}.",
            f"SWIFT is sent with the payer option. {p['swift_option']['why']}",
            f"The payout fee was seen on the sandbox for {_n(t['observed_fee_corridors'], 'corridor')} and is an "
            f"estimate from Airwallex's published prices for {t['estimated_fee_corridors']:,}.",
        ]})
    out.append({
        "kind": "book_fees", "tone": "go", "title": "The fee rule",
        "happened": f"{_n(t['holder_bears']['owners'], 'claim')} below {_big(line)}; {t['from_claim']['owners']:,} at or above it.",
        "allowed": f"Below {_big(line)} the holder bears the fees. From there up, they come out of the claim.",
        "did": f"The holder adds {_big(t['holder_bears']['adds'])} so the small claims arrive whole.",
        "money": f"Fees {_big(t['cost']['usd'])} in all: {t['cost']['percent']}% of {_big(t['planned']['usd'])} paid.",
        "why": [f"Airwallex takes {p['incoming_fee_percent']:g} percent of the money that arrives and a payout fee for each "
                "transfer. Both are counted for every claim.",
                f"Of the fees, {_big(t['cost']['borne_by_holder'])} is borne by the holder and "
                f"{_big(t['cost']['out_of_claims'])} comes out of the larger claims."]})
    out.append({
        "kind": "book_small", "tone": "stop" if t["too_small"]["owners"] else "go", "title": "Claims smaller than their fees",
        "happened": f"{_n(t['too_small']['owners'], 'claim')}, {_big(t['too_small']['usd'])}, are smaller than the fees to send them.",
        "allowed": "A claim is not sent when the fees are at least the claim itself.",
        "did": "They stay with the State process." if t["too_small"]["owners"] else "Nothing is held back for this.",
        "money": f"Sending them would cost {_big(t['too_small']['would_cost'])} to deliver {_big(t['too_small']['usd'])}.",
        "why": ["This holds whoever bears the fees: below the small-claim line the holder would pay more in fees than "
                "it owes the owner.",
                f"{_n(t['no_cash']['owners'], 'property', 'properties')} carry no cash figure in the file (shares or the "
                "contents of a safe deposit box) and are not part of a payment plan."]})
    batch = [c for c in f["currencies"] if c["mode"] == "batch"]
    each = [c for c in f["currencies"] if c["mode"] == "each"]
    sized = [c for c in f["currencies"] if c.get("sizes")]
    if sized:
        sizes = sized[0]["sizes"]
        measured = (f"Airwallex quoted a different rate by size in {sum(1 for c in sized if c['rate_depends_on_size'])} currencies."
                    if f["rate_depends_on_size"] else
                    f"Airwallex quoted the same rate at {len(sizes)} sizes, {sizes[0]['sell_usd']:,} to {sizes[-1]['sell_usd']:,} USD.")
    else:
        measured = "Nothing has to be converted."
    out.append({
        "kind": "book_funding", "tone": "go", "title": "The funding",
        "happened": measured,
        "allowed": "Convert each payment as it is approved, or once per currency for the batch: take the cheaper.",
        "did": f"Once per currency in {_n(len(batch), 'currency', 'currencies')}; inside each transfer in {len(each):,} that cannot be held ahead.",
        "money": f"The holder funds {_big(f['holder_funds_usd'])}. Saves {_big(f['saving_usd'])} and "
                 f"{max(f['conversions_if_each'] - f['conversions_planned'], 0):,} conversions.",
        "why": [
            "Both ways were worked out with quotes the sandbox really gave: every single payment at the quote for "
            "the size nearest to it, and the whole batch at the quote for the size nearest to the batch.",
            ("The rate did not depend on the amount, so converting once saves nothing on the rate itself. What it "
             "saves is the number of conversions, and every owner in a currency is paid at one rate fixed on one "
             "day." if not f["rate_depends_on_size"] else
             "Where the batch quote was better, the batch is converted once; where single quotes were better, "
             "each payment converts by itself."),
            f["ahead_of_approvals"],
        ]})
    first = ", ".join(x["name"] for x in o["work"][:3]) or "none"
    dropped_usd = t["too_late"]["usd"]
    out.append({
        "kind": "book_order", "tone": "stop" if not o["work"] else ("ask" if o["dropped"] else "go"), "title": "The order of work",
        "happened": (f"{left_words(p['days_left'])} until the handover on {p['handover_words']}."),
        "allowed": f"An owner needs about {o['document_days']} days to send a document; then the rail takes its own days.",
        "did": (f"Start with {first}. {_n(len(o['dropped']), 'corridor')} cannot finish in time." if o["work"] else
                "Too close for any corridor: the whole book stays with the State process."),
        "money": f"{_big(t['planned']['usd'])} can be paid in time; {_big(dropped_usd)} is too close and goes on the Remit Report.",
        "why": ["A corridor is worked only if the days left cover the days an owner needs to send a document and "
                "the longest time its rail takes, as Airwallex's guide for the country gives it. Corridors are "
                "ordered by dollars reachable for each day they need.",
                o["machine"]["text"]]})
    r = t["refusal"]
    out.append({
        "kind": "book_tolerance", "tone": "go", "title": "If a bank refuses a transfer",
        "happened": "A refused transfer costs a second payout fee, which comes out of the replacement.",
        "allowed": f"Up to {Decimal(i['tolerance_percent']).normalize():f}% less than agreed, without asking the owner about the amount again.",
        "did": f"{_n(r['inside'], 'claim')} would be re-sent on that rule; {r['outside']:,} would stop and ask the owner.",
        "money": f"{_big(r['inside_usd'])} inside the tolerance, {_big(r['outside_usd'])} outside it.",
        "why": ["The corrected account always comes from the owner and is always approved by the holder. The "
                "tolerance decides only whether the owner is also asked to agree to the slightly smaller amount.",
                "One replacement is sent, and only once Airwallex reports the first transfer as failed or cancelled."]})
    return out


def left_words(days: int) -> str:
    return f"{days:,} days" if days != 1 else "1 day"


def changes(before: dict, after: dict) -> list[dict]:
    """What a change of the inputs did to the plan, in lines of figures: one line per thing that moved."""
    names = {"small_claim_usd": "the small-claim line", "tolerance_percent": "the tolerance",
             "handover_date": "the handover date", "document_days": "the days an owner needs"}
    moved = [names[k] for k in names if str(before["inputs"][k]) != str(after["inputs"][k])]
    if not moved:
        return []
    b, a = before["totals"], after["totals"]
    out = []

    def line(what: str, was: float, now: float, money: bool = True, unit: str = "") -> None:
        if was != now:
            shown = (lambda v: _big(v)) if money else (lambda v: f"{v:,.0f}{unit}" if float(v).is_integer() else f"{v:,.2f}{unit}")
            out.append({"what": what, "before": shown(was), "after": shown(now), "delta": round(now - was, 2)})

    # what the handover date moves comes first, then what the fee rule moves, then the tolerance
    line("Corridors that can finish in time", b["planned"]["countries"], a["planned"]["countries"], False)
    line("Dollars paid in time", b["planned"]["usd"], a["planned"]["usd"])
    line("Dollars too close to the handover", b["too_late"]["usd"], a["too_late"]["usd"])
    line("Claims on which the holder bears the fees", b["holder_bears"]["owners"], a["holder_bears"]["owners"], False)
    line("What the holder adds for them", b["holder_bears"]["adds"], a["holder_bears"]["adds"])
    line("Fees in all", b["cost"]["usd"], a["cost"]["usd"])
    line("What the holder funds", b["holder_funds_usd"], a["holder_funds_usd"])
    line("Claims re-sent after a refusal without asking about the amount", b["refusal"]["inside"], a["refusal"]["inside"], False)
    line("Claims that would stop and ask the owner", b["refusal"]["outside"], a["refusal"]["outside"], False)
    was = {x["country"] for x in before["order"]["work"]}
    now = {x["country"] for x in after["order"]["work"]}
    gone = [x["name"] for x in before["order"]["work"] if x["country"] not in now]
    back = [x["name"] for x in after["order"]["work"] if x["country"] not in was]
    if gone:
        out.append({"what": "Corridors dropped", "before": "", "after": ", ".join(gone[:8]) + (f" and {len(gone) - 8} more" if len(gone) > 8 else ""),
                    "delta": -len(gone)})
    if back:
        out.append({"what": "Corridors added", "before": "", "after": ", ".join(back[:8]) + (f" and {len(back) - 8} more" if len(back) > 8 else ""),
                    "delta": len(back)})
    return [{"what": "Changed", "before": "", "after": " and ".join(moved), "delta": 0}] + out


def without_cents(p: dict) -> dict:
    """The plan as it leaves the server: the working figures in cents are taken out."""
    return {**p, "corridors": [{k: v for k, v in c.items() if k != "_cents"} for c in p["corridors"]]}
