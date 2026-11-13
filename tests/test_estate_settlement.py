"""The arithmetic of an estate settlement: cents, the fee rule heir by heir, quotes read the right way round,
and bank details per corridor. Pure code, no app."""
import random
from decimal import Decimal
from fractions import Fraction

import pytest

from khutlisa import airwallex as awx
from khutlisa import estate_settlement as es
from khutlisa import instructions as ins

RULES = ins.clean({})        # tolerance 0.5 percent, small-claim line 250.00, most to the claimant, 14 days


def test_allocate_gives_the_spare_cents_to_the_largest_remainders_and_then_to_the_first():
    assert es.allocate(100, [Fraction(1, 3)] * 3) == [34, 33, 33]
    assert es.allocate(184055, [Fraction(1, 3), Fraction(2, 9), Fraction(2, 9), Fraction(2, 9)]) == [61352, 40901, 40901, 40901]
    assert es.allocate(1, [Fraction(1, 2), Fraction(1, 2)]) == [1, 0]
    assert es.allocate(0, [Fraction(1, 2), Fraction(1, 2)]) == [0, 0]
    with pytest.raises(ValueError):
        es.allocate(100, [])
    with pytest.raises(ValueError):
        es.allocate(-1, [Fraction(1)])


@pytest.mark.parametrize("seed", range(6))
def test_allocated_cents_always_add_up_and_stay_within_a_cent_of_the_exact_share(seed):
    rng = random.Random(seed)
    for _ in range(2000):
        n = rng.randint(1, 9)
        weights = [Fraction(rng.randint(1, 12), rng.randint(1, 12)) for _ in range(n)]
        total = rng.randint(0, 5_000_000)
        parts = es.allocate(total, weights)
        assert sum(parts) == total
        whole = sum(weights)
        for part, w in zip(parts, weights):
            assert abs(part - Fraction(total) * w / whole) < 1
        assert es.allocate(total, weights) == parts                        # the same answer every time
        # equal weights never differ by more than a cent, and the earlier one never gets less
        same = es.allocate(total, [Fraction(1)] * n)
        assert max(same) - min(same) <= 1 and same == sorted(same, reverse=True)


def test_entitlements_add_up_to_the_property_amount():
    heirs = [{"id": "s1", "share": "1/3"}, {"id": "a", "share": "2/9"}, {"id": "b", "share": "2/9"}, {"id": "c", "share": "2/9"}]
    owed = es.entitlements("1840.55", heirs)
    assert owed == {"s1": 61352, "a": 40901, "b": 40901, "c": 40901} and sum(owed.values()) == 184055
    rng = random.Random(3)
    for _ in range(500):
        amount = Decimal(rng.randint(1, 9_999_999)) / 100
        parts = [Fraction(rng.randint(1, 9)) for _ in range(rng.randint(1, 7))]
        heirs = [{"id": str(i), "share": str(p / sum(parts))} for i, p in enumerate(parts)]
        assert sum(es.entitlements(amount, heirs).values()) == es.cents(amount)


def test_fee_rule_for_one_heir_is_the_single_claim_rule():
    """With one heir the settlement sends exactly what instructions.fee_plan sends for a single claim."""
    for amount in ("95.00", "249.99", "250.00", "2316.40"):
        got = es.targets([{"id": "a", "entitlement": es.cents(amount)}], RULES, {"a": Decimal("5.00")})
        single = ins.fee_plan(amount, RULES)
        assert es.dollars(got["holder_sends"]) == single["holder_sends"]
        assert got["covered"]["a"] == (single["bearer"] == "holder")
        assert es.dollars(got["legs"]["a"]) == f"{Decimal(single['left_for_claimant_usd']) + Decimal('5.00'):.2f}"


def test_fee_rule_is_applied_heir_by_heir():
    rows = [{"id": "a", "entitlement": 33334}, {"id": "b", "entitlement": 33333}, {"id": "c", "entitlement": 16667},
            {"id": "d", "entitlement": 16666}]
    got = es.targets(rows, RULES, {k: Decimal("5.00") for k in "abcd"})
    assert got["covered"] == {"a": False, "b": False, "c": True, "d": True}
    # the two small shares arrive whole, with their payout fee on top; the two large ones bear 0.3 percent
    assert got["legs"]["c"] == 16667 + 500 and got["legs"]["d"] == 16666 + 500
    assert got["legs"]["a"] == 33334 - 100 and got["legs"]["b"] in (33333 - 100, 33333 - 99)   # one spare cent
    assert sum(got["legs"].values()) == got["net"] == got["holder_sends"] - got["expected_incoming_fee"]
    assert got["holder_adds"] == got["holder_sends"] - 100000 > 0


def test_without_instructions_the_holder_sends_the_entitlements_and_nothing_more():
    rows = [{"id": "a", "entitlement": 5000}, {"id": "b", "entitlement": 5000}]
    got = es.targets(rows, None, {"a": Decimal("5.00"), "b": Decimal("5.00")})
    assert got["holder_sends"] == 10000 and got["holder_adds"] == 0 and got["covered"] == {"a": False, "b": False}
    assert sum(got["legs"].values()) == got["net"] == 10000 - 30


@pytest.mark.parametrize("seed", range(4))
def test_what_is_planned_always_adds_up_to_what_is_left_after_the_incoming_fee(seed):
    rng = random.Random(seed)
    for _ in range(1500):
        rows = [{"id": str(i), "entitlement": rng.randint(1, 400_000)} for i in range(rng.randint(1, 6))]
        fees = {r["id"]: Decimal(rng.choice(["5.00", "5.06", "10.03"])) for r in rows}
        got = es.targets(rows, RULES if rng.random() < 0.8 else None, fees)
        assert sum(got["legs"].values()) == got["net"]
        assert got["holder_sends"] >= sum(r["entitlement"] for r in rows)
        for r in rows:
            if got["covered"][r["id"]]:          # a covered heir is left the whole entitlement after the payout fee
                assert got["legs"][r["id"]] - es.cents(fees[r["id"]]) >= r["entitlement"] - 1


def test_a_quote_is_read_from_its_own_amounts_whichever_way_the_pair_is_quoted():
    pounds = {"currency_pair": "GBPUSD", "client_rate": 1.331115, "sell_amount": 20.0, "buy_amount": 15.02}
    assert es.bought(pounds, Decimal("20"), "GBP") == Decimal("15.02")
    assert es.bought({"currency_pair": "GBPUSD", "client_rate": 1.25}, Decimal("100"), "GBP") == Decimal("80.00")
    assert es.bought({"currency_pair": "USDJPY", "client_rate": 158.9}, Decimal("20"), "JPY") == Decimal("3178")
    assert es.bought({"client_rate": 18.4}, Decimal("10"), "MXN") == Decimal("184.00")
    with pytest.raises(ValueError):
        es.bought({}, Decimal("10"), "MXN")
    # multiplying dollars by a GBPUSD rate would promise more pounds than dollars; the estimate never does
    got = es.leg_estimate(awx.CONVERT_THEN_PAY, Decimal("400"), "GBP", {"currency_pair": "GBPUSD", "client_rate": 1.33}, {})
    assert Decimal(got["received"]["amount"]) < 400 and got["payout_fee"]["currency"] == "GBP"
    assert Decimal(got["fee_usd"]) == Decimal("5.00")


def test_the_route_that_delivers_most_is_chosen_and_a_tie_goes_to_converting_first():
    quote = {"currency_pair": "USDMXN", "client_rate": 18.0, "mid_rate": 18.0}
    best, compared = es.choose_leg_route("MXN", Decimal("100"), quote, {}, RULES)
    assert best["route"] == awx.CONVERT_THEN_PAY and len(compared) == 2
    cheaper = {"USD": {"amount": "1.00", "currency": "USD"}}
    assert es.choose_leg_route("MXN", Decimal("100"), quote, cheaper, RULES)[0]["route"] == awx.PAY_WITH_QUOTE
    assert es.choose_leg_route("MXN", Decimal("100"), quote, cheaper, {**RULES, "route_rule": "fixed"})[0]["route"] == awx.CONVERT_THEN_PAY
    assert es.choose_leg_route("PHP", Decimal("100"), {"client_rate": 60}, {}, RULES)[0]["route"] == awx.PAY_WITH_QUOTE


def test_bank_details_for_each_corridor():
    base = dict(street_address="1 Example Street", city="Town")
    gb = es.beneficiary("GBP", "Tomas", "Santos", "55779911", sort_code="20-00-00", postcode="LS1 4AP", **base)
    bank = gb["beneficiary"]["bank_details"]
    assert (bank["account_routing_type1"], bank["account_routing_value1"], bank["bank_country_code"]) == ("sort_code", "200000", "GB")
    jp = es.beneficiary("JPY", "Naomi", "Kato", "1234567", bank_code="0005", branch_code="001", account_type="Savings",
                        postcode="530-0001", **base)
    assert jp["beneficiary"]["bank_details"]["bank_account_category"] == "Savings"
    assert es.beneficiary("MXN", "A", "B", "002010077777777771", postcode="06600", state="MX-CMX", **base) == \
        awx.local_beneficiary("MXN", "A", "B", "002010077777777771", postcode="06600", state="MX-CMX", **base)
    for bad in (dict(currency="GBP", account_number="1234", sort_code="200000", postcode="X"),
                dict(currency="GBP", account_number="55779911", sort_code="12", postcode="X"),
                dict(currency="JPY", account_number="1234567", bank_code="5", branch_code="001", account_type="Savings", postcode="X"),
                dict(currency="JPY", account_number="1234567", bank_code="0005", branch_code="001", account_type="Other", postcode="X"),
                dict(currency="GBP", account_number="55779911", sort_code="200000", postcode=""),
                dict(currency="EUR", account_number="55779911")):
        currency = bad.pop("currency")
        with pytest.raises(ValueError):
            es.beneficiary(currency, "A", "B", bad.pop("account_number"), **base, **bad)


def test_amounts_are_worded_with_the_decimals_of_their_currency():
    assert es.figure("64002", "JPY") == "64,002 JPY" and es.figure("11223.5", "MXN") == "11,223.50 MXN"
