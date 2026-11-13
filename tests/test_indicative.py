"""Money from the start: what an amount would become in the claimant's currency today, at Airwallex's indicative
rate, and the payout plan in summary before the proof is complete. Everything is labelled as indicative or as a
plan. The rate is cached briefly, so a screen full of cards asks Airwallex once."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from khutlisa import indicative as ind
from test_airwallex import FakeAirwallex, make_client
from test_claims import AS_PAYER, PH_BANK, World, give_bank, open_claim


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def fake():
    return FakeAirwallex()


def rates(fake, clock=None):
    return ind.Indicative(lambda: (make_client(fake), None), clock=clock or Clock())


def test_the_corridor_follows_the_country_however_it_is_written():
    assert ind.corridor("MX") == ("MX", "MXN") and ind.corridor("Mexico") == ("MX", "MXN")
    assert ind.corridor("México") == ("MX", "MXN") and ind.corridor("philippines") == ("PH", "PHP")
    assert ind.corridor("Pilipinas") == ("PH", "PHP") and ind.corridor("Japan") is None and ind.corridor("") is None


def test_an_amount_becomes_local_currency_at_the_indicative_rate_after_the_fees_the_plan_expects(fake):
    out = rates(fake).amounts("Mexico", ["2316.40", "95.00"], None)
    assert out["available"] and out["currency"] == "MXN" and out["rate"] == 18.5
    assert "indicative" in out["label"].lower() and "Not locked" in out["label"]
    first, second = out["amounts"]
    # 2,316.40 less 6.95 incoming and 5.00 payout fee is 2,304.45; at 18.5 that is 42,632.33 MXN.
    assert first["would_receive"] == {"amount": "42632.33", "currency": "MXN"}
    assert first["fees"] == {"incoming": "6.95", "payout": "5.00", "currency": "USD", "borne_by": "claim"}
    assert second["would_receive"]["amount"] == "1659.64"        # 95.00 - 0.29 - 5.00 = 89.71; a small claim shrinks
    assert fake.count("POST", "/api/v1/fx/quotes/create") == 0   # nothing is locked by looking


def test_under_the_holders_fee_rule_a_small_amount_is_shown_whole(fake):
    rules = {"tolerance_percent": "0.5", "small_claim_usd": "250.00", "route_rule": "most_to_claimant",
             "deadline_days": 14}
    small = rates(fake).amounts("MX", ["95.00"], rules)["amounts"][0]
    # The holder sends 100.31 (rounded up to the cent), so 95.01 is left to convert: 95.01 x 18.5.
    assert small["fees"]["borne_by"] == "holder" and small["would_receive"]["amount"] == "1757.69"


def test_the_rate_is_asked_for_once_and_kept_for_a_minute(fake):
    clock = Clock()
    source = rates(fake, clock)
    for _ in range(5):
        source.amounts("MX", ["10"], None)
    assert fake.count("GET", "/api/v1/fx/rates/current") == 1
    clock.now += 61
    fake.rates["MXN"] = 19.0
    assert source.amounts("MX", ["10"], None)["rate"] == 19.0
    assert fake.count("GET", "/api/v1/fx/rates/current") == 2


def test_when_airwallex_cannot_be_asked_the_last_rate_is_shown_with_its_age_and_then_nothing(fake):
    clock = Clock()
    source = rates(fake, clock)
    source.amounts("MX", ["10"], None)
    fake.rates_down = True
    clock.now += 120
    late = source.amounts("MX", ["10"], None)
    assert late["available"] and late["rate"] == 18.5 and late["age_seconds"] == 120
    clock.now += 3600
    gone = source.amounts("MX", ["10"], None)
    assert gone["available"] is False and "could not be read" in gone["reason"]


def test_without_keys_or_for_a_country_not_paid_to_yet_it_says_so(fake):
    def no_keys():
        from khutlisa import airwallex as awx
        raise awx.CredentialsError("missing")
    assert "keys" in ind.Indicative(no_keys).amounts("MX", ["10"], None)["reason"]
    out = rates(fake).amounts("Japan", ["10"], None)
    assert out["available"] is False and "Mexico and the Philippines" in out["reason"]


def test_the_api_gives_indicative_amounts_and_a_plan_summary_before_the_proof_is_complete(tmp_path):
    world = World(tmp_path)
    world.fake.incoming_fee_rate, world.fake.payout_fee_usd = 0.003, 5.0
    with TestClient(world.app, headers=AS_PAYER) as api:
        got = api.get("/api/indicative", params={"country": "Philippines", "amount": ["1840.55", "320.10"]}).json()
        assert got["available"] and got["currency"] == "PHP" and len(got["amounts"]) == 2
        assert got["amounts"][0]["would_receive"]["amount"] == "106141.74"      # (1840.55 - 5.52 - 5.00) x 58
        assert api.get("/api/indicative", params={"country": "PH", "amount": ["x"]}).status_code == 422

        claim = open_claim(api)                           # no document yet, no bank account, nothing approved
        plan = api.get(f"/api/claims/{claim['id']}/payout/preview").json()
        assert plan["available"] and plan["is_plan"] is True and "Nothing has moved" in plan["label"]
        assert plan["currency"] == "PHP" and plan["currency_from"] == "the country you gave"
        assert plan["claim"] == {"amount": "1840.55", "currency": "USD"}
        assert plan["would_receive"] == {"amount": "106141.74", "currency": "PHP"}
        assert [s["done"] for s in plan["before_it_can_start"]] == [False, False, False]
        assert api.get(f"/api/claims/{claim['id']}").json()["state"] == "PROOF_NEEDED"   # looking changes nothing
        assert not world.fake.deposits and not world.fake.quotes

        api.put("/api/payer/instructions", json={"small_claim_usd": "2000"})
        give_bank(api, claim["id"], PH_BANK)
        plan = api.get(f"/api/claims/{claim['id']}/payout/preview").json()
        assert plan["currency_from"] == "the bank account you gave" and plan["fee_rule"]["bearer"] == "holder"
        assert plan["holder_sends"] == {"amount": "1851.11", "currency": "USD"}
        assert plan["before_it_can_start"][1]["done"] is True
