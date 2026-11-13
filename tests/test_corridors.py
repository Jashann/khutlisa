"""Corridors: what the live sandbox is asked, what is kept, and what a plan reads from it. A small stand-in
answers in place of Airwallex; no network."""
from __future__ import annotations

from decimal import Decimal

import pytest

from khutlisa import airwallex as awx
from khutlisa import corridors as co


class Sandbox:
    """Answers the five calls discovery makes, and counts them."""

    LOCAL = {("MX", "MXN"), ("GB", "GBP"), ("PH", "PHP"), ("CN", "CNY")}
    SWIFT = {("MX", "MXN"), ("GB", "GBP"), ("PH", "PHP"), ("CN", "CNY"), ("TW", "USD"), ("MX", "USD"), ("GB", "USD"),
             ("PH", "USD"), ("CN", "USD")}
    RATES = {"MXN": ("USDMXN", 18.40, 18.60), "GBP": ("GBPUSD", 1.33, 1.3234), "PHP": ("USDPHP", 63.0, 63.7),
             "CNY": ("USDCNY", 6.63, 6.67)}
    HOLD = {"MXN", "GBP", "CNY"}

    def __init__(self):
        self.calls: list[str] = []
        self.spread_by_size: dict[int, float] = {}

    def beneficiary_schema(self, country, currency, method="LOCAL", entity="PERSONAL"):
        self.calls.append(f"schema {country} {currency} {method}")
        if (country, currency) not in (self.LOCAL if method == "LOCAL" else self.SWIFT):
            raise awx.AirwallexError(400, "SCHEMA_DEFINITION_NOT_FOUND", "Provided parameters do not match any schema definition.")
        fields = [{"path": "beneficiary.bank_details.account_number", "required": True},
                  {"path": "beneficiary.first_name", "required": True},
                  {"path": "beneficiary.date_of_birth", "required": False}]
        if method == "LOCAL" and country == "GB":
            fields.append({"path": "beneficiary.bank_details.local_clearing_system", "required": False,
                           "rule": {"pattern": "FASTER_PAYMENTS|CHAPS"}})
        return {"fields": fields}

    def indicative_rate(self, sell, buy):
        self.calls.append(f"rate {buy}")
        if buy not in self.RATES:
            raise awx.AirwallexError(400, "invalid_parameter", "unsupported_currency")
        pair, client, _ = self.RATES[buy]
        return {"rate": client, "currency_pair": pair}

    def create_quote(self, sell, buy, *, sell_amount=None, buy_amount=None, validity="HR_1"):
        self.calls.append(f"quote {sell}>{buy} {sell_amount} {validity}")
        if sell != "USD":      # back into US dollars: a little less than was sold
            pair, client, mid = self.RATES[sell]
            per = 1 / client if pair.startswith(sell) else client
            return {"buy_amount": round(float(sell_amount) / per * 0.98, 2), "client_rate": client, "mid_rate": mid,
                    "currency_pair": pair}
        if buy not in self.RATES:
            raise awx.AirwallexError(400, "invalid_parameter", "unsupported_currency")
        pair, client, mid = self.RATES[buy]
        worse = {"MIN_1": 0.0, "MIN_15": 0.0008, "HR_1": 0.0012}[validity] + self.spread_by_size.get(int(sell_amount), 0.0)
        client = client * (1 + worse) if pair.startswith(buy) else client * (1 - worse)
        return {"quote_id": "q", "client_rate": client, "mid_rate": mid, "awx_rate": mid, "currency_pair": pair}

    def balances(self):
        return [{"currency": c} for c in ("USD", "MXN", "GBP", "PHP", "CNY")]

    def create_conversion(self, request_id, sell, buy, *, sell_amount=None, quote_id=None):
        self.calls.append(f"convert {buy}")
        if buy not in self.HOLD:
            raise awx.AirwallexError(400, "unable_to_resolve_valid_value_date", f"Restricted capabilities: sell USD, buy {buy} is not supported")
        return {"status": "SETTLED", "buy_amount": 1}

    def _pages(self, path, params=None, max_pages=20):
        self.calls.append("transfers")
        return [
            {"transfer_method": "LOCAL", "transfer_currency": "MXN", "fee_amount": 5, "fee_currency": "USD", "created_at": "t3"},
            {"transfer_method": "LOCAL", "transfer_currency": "MXN", "fee_amount": 93.02, "fee_currency": "MXN", "created_at": "t2"},
            {"transfer_method": "SWIFT", "swift_charge_option": "PAYER", "transfer_currency": "USD", "fee_amount": 25, "fee_currency": "USD"},
            {"transfer_method": "SWIFT", "swift_charge_option": "SHARED", "transfer_currency": "USD", "fee_amount": 15, "fee_currency": "USD"},
            {"transfer_method": "LOCAL", "transfer_currency": "PHP", "fee_amount": None},
        ]


COUNTRIES = ["MX", "GB", "PH", "CN", "TW", "VE"]


@pytest.fixture(scope="module")
def found():
    return co.discover(Sandbox(), COUNTRIES, try_conversions=True)


def test_every_country_has_a_currency_and_the_euro_countries_share_one():
    assert co.currency_of("mx") == "MXN" and co.currency_of("DE") == co.currency_of("FR") == "EUR"
    assert co.currency_of("EC") == "USD" and co.currency_of("ZZ") is None
    assert co.calendar_days(1) == 2 and co.calendar_days(3) == 5 and co.calendar_days(0) == 0


def test_a_pair_quoted_the_other_way_round_is_turned_into_units_for_one_dollar():
    assert co.per_usd(18.4, "USDMXN", "MXN") == 18.4
    assert co.per_usd(1.33, "GBPUSD", "GBP") == pytest.approx(1 / 1.33, abs=1e-8)
    assert co.per_usd(None, "GBPUSD", "GBP") is None and co.per_usd(159.2, None, "JPY") == 159.2


def test_discovery_asks_for_each_rail_and_keeps_what_airwallex_answered(found):
    mx, tw, ve = (found["corridors"][c] for c in ("MX", "TW", "VE"))
    assert mx["local"]["available"] and mx["swift"]["available"] and mx["swift_usd"]["available"] and mx["at"]
    assert "bank_details.account_number" in mx["local"]["required"] and "date_of_birth" not in mx["local"]["required"]
    assert found["corridors"]["GB"]["local"]["clearing"] == ["FASTER_PAYMENTS", "CHAPS"]
    assert tw["local"] == {"available": False, "answer": "SCHEMA_DEFINITION_NOT_FOUND", "at": tw["at"]}
    assert tw["swift_usd"]["available"] and not ve["swift_usd"]["available"]
    gbp = found["currencies"]["GBP"]          # turned over: about 0.75 pounds for a dollar, and below the mid rate
    assert gbp["quotable"] and 0.74 < gbp["rate"] < 0.76 and gbp["quoted_pair"] == "GBPUSD"
    assert [q["sell_usd"] for q in gbp["ladder"]] == list(co.LADDER) and all(q["client_rate"] < q["mid_rate"] for q in gbp["ladder"])
    assert [q["validity"] for q in gbp["locks"]] == list(co.VALIDITIES)
    assert "TWD" not in found["currencies"]   # no schema in its own currency, so its rate is never asked
    assert found["conversions"]["MXN"]["held"] and not found["conversions"]["PHP"]["held"]
    assert "not supported" in found["conversions"]["PHP"]["answer"] and found["fetched_at"]


def test_what_is_already_known_is_not_asked_again():
    sandbox = Sandbox()
    first = co.discover(sandbox, ["MX", "TW"])
    asked = len(sandbox.calls)
    assert sum(1 for c in sandbox.calls if c.startswith("schema")) == 6 and "rate MXN" in sandbox.calls
    again = co.discover(sandbox, ["MX", "TW"], known=first)
    new = sandbox.calls[asked:]
    assert not any(c.startswith(("schema", "rate", "quote")) for c in new) and again["corridors"] == first["corridors"]
    more = co.discover(sandbox, ["MX", "TW", "GB"], known=first)
    assert sum(1 for c in sandbox.calls[asked + len(new):] if c.startswith("schema")) == 3 and "GBP" in more["currencies"]
    stale = co.discover(sandbox, ["MX"], known=first, max_age_hours=0)       # too old: asked again
    assert stale["corridors"]["MX"]["local"]["available"]


def test_a_network_failure_is_kept_as_not_known_and_is_asked_again():
    class Down(Sandbox):
        def beneficiary_schema(self, *a, **k):
            raise OSError("no route")
    first = co.discover(Down(), ["MX"])
    assert first["corridors"]["MX"]["local"]["available"] is None
    assert co.discover(Sandbox(), ["MX"], known=first)["corridors"]["MX"]["local"]["available"] is True


def test_the_cache_is_written_and_read_back(tmp_path, found):
    path = tmp_path / "corridors.json"
    co.save(found, path)
    assert co.load(path) == found and co.load(tmp_path / "missing.json") is None
    (tmp_path / "broken.json").write_text("{")
    assert co.load(tmp_path / "broken.json") is None


def test_a_fee_is_what_was_seen_or_an_estimate_that_says_so(found):
    mxn = co.payout_fee(found, "LOCAL", "MXN")
    assert mxn["basis"] == "observed" and mxn["usd"] == "5.00" and mxn["documented_usd"] == "1" and mxn["seen"] == 2
    gbp = co.payout_fee(found, "LOCAL", "GBP")          # never paid from this account: the published price, marked
    assert gbp["basis"] == "estimate" and gbp["usd"] == "1.00" and "An estimate" in gbp["text"] and gbp["seen"] == 0
    assert co.payout_fee(found, "LOCAL", "XYZ")["usd"] == "5.00"              # "all other currencies"
    assert co.payout_fee(found, "LOCAL", "JPY")["usd"] == "7.00"
    swift = co.payout_fee(found, "SWIFT", "USD")        # the payer option, as charged on the sandbox
    assert swift == {**swift, "usd": "25.00", "basis": "observed"}
    assert co.payout_fee({}, "SWIFT", "USD")["basis"] == "estimate" and co.payout_fee({}, "SWIFT", "USD")["usd"] == "25"
    only_local = {"observed_fees": {"LOCAL:MXN": {"seen": 1, "by_fee_currency": {"MXN": {"amount": "93.00"}}}},
                  "currencies": found["currencies"]}
    assert co.payout_fee(only_local, "LOCAL", "MXN")["usd"] == "5.00" and "93.00 MXN" in co.payout_fee(only_local, "LOCAL", "MXN")["text"]
    assert co.documented_local_fee("CNY", Decimal("2000")) == Decimal("2.00")


def test_whether_a_currency_can_be_held_is_what_the_sandbox_did_before_what_the_table_says(found):
    assert co.can_hold(found, "MXN") == (True, "converted on the sandbox")
    assert co.can_hold(found, "PHP") == (False, "the sandbox refused the conversion")
    assert co.can_hold({}, "PHP")[0] is False and co.can_hold({}, "EUR")[0] is True and "not tried" in co.can_hold({}, "EUR")[1]
    assert co.can_hold({}, "XOF") == (None, "not known") and co.can_hold({}, "USD")[0] is True
    assert co.can_hold({"conversions": {"EUR": {"held": False}}}, "EUR")[0] is False


def test_the_routes_of_a_country_come_in_the_order_the_plan_prefers(found):
    mx = co.routes(found, "MX")
    assert [(o["method"], o["currency"]) for o in mx["options"]] == [("LOCAL", "MXN"), ("SWIFT", "MXN"), ("SWIFT", "USD")]
    tw = co.routes(found, "TW")
    assert [(o["method"], o["currency"]) for o in tw["options"]] == [("SWIFT", "USD")] and tw["local_schema"] is False
    cn = co.routes(found, "CN")       # a local schema exists, but the guide keeps it for e-commerce sellers
    assert cn["options"][0]["method"] == "SWIFT" and "e-commerce" in cn["local_set_aside"]
    assert co.routes(found, "VE")["options"] == [] and co.routes(found, "BR") == {"country": "BR", "currency": "BRL", "known": False, "options": []}


def test_rail_times_come_from_the_guides_and_say_when_they_are_an_estimate():
    assert co.flight("MX", "LOCAL") == {"min": 0, "max": 1, "scheme": "SPEI", "basis": "documented"}
    assert co.flight("AE", "LOCAL")["max"] == 3 and co.flight("FR", "LOCAL")["scheme"].startswith("SEPA")
    assert co.flight("MX", "SWIFT")["max"] == 3 and co.flight("BW", "LOCAL")["basis"] == "estimate"


def test_quotes_at_several_sizes_show_whether_the_rate_depends_on_the_amount(found):
    sizes = co.spread_by_size(found, "MXN")
    assert len(sizes) == 6 and len({s["spread_percent"] for s in sizes}) == 1 and sizes[0]["spread_percent"] == pytest.approx(1.0753, abs=1e-3)
    assert co.nearest_quote(found, "MXN", 40)["sell_usd"] == 100 and co.nearest_quote(found, "MXN", 31)["sell_usd"] == 10
    assert co.nearest_quote(found, "MXN", 5_000_000)["sell_usd"] == 1_000_000 and co.nearest_quote(found, "TWD", 100) is None
    lock = co.lock_cost(found, "MXN")
    assert lock["percent"] == pytest.approx(0.12, abs=0.001) and lock["min_1"] > lock["hr_1"]
    assert co.lock_cost(found, "GBP")["percent"] == pytest.approx(0.12, abs=0.001)     # also for a pair quoted the other way
    back = co.round_trip(found, "MXN")
    assert back["sold_usd"] == 1000 and back["percent"] == pytest.approx(2.0, abs=0.01) and co.round_trip(found, "TWD") is None


def test_fees_seen_on_transfers_are_kept_by_rail_and_currency():
    seen = co.observed_fees(Sandbox()._pages(""))
    assert set(seen) == {"LOCAL:MXN", "SWIFT:PAYER", "SWIFT:SHARED"}
    assert seen["LOCAL:MXN"]["by_fee_currency"]["USD"]["amount"] == "5" and seen["LOCAL:MXN"]["seen"] == 2
    assert seen["SWIFT:SHARED"]["by_fee_currency"]["USD"]["amount"] == "15"
