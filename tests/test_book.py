"""The whole book: one holder's properties abroad, planned. Every figure is arithmetic on the book and on what
corridors.py holds, so the tests give both and read the plan."""
from __future__ import annotations

import copy
import json
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import book as bk
from khutlisa import corridors as co
from khutlisa.server import create_app
from test_claims import make_register
from test_corridors import Sandbox

TODAY = date(2026, 11, 13)
HOLDER = {"key": "ACME PAYROLL INC", "name": "ACME PAYROLL INC"}
WAGES = "MS01: WAGES, PAYROLL, SALARIES"

# (owner country, US dollar cents, property type)
CLAIMS = (
    [("MX", 120_00, WAGES)] * 3 + [("MX", 2_316_40, WAGES), ("MX", 40_000_00, WAGES), ("MX", 3_00, WAGES)]   # one over SPEI's limit, one tiny
    + [("GB", 800_00, WAGES), ("GB", 90_00, WAGES)]
    + [("PH", 500_00, WAGES)] * 2
    + [("TW", 1_000_00, WAGES), ("TW", 20_00, WAGES)]     # SWIFT in US dollars; 20.00 is smaller than a 25.00 fee
    + [("CN", 5_000_00, WAGES)]                           # local rails set aside: SWIFT in CNY
    + [("VE", 700_00, WAGES)]                             # no schema at all
    + [("other", 50_00, WAGES)]                           # a country code that cannot be placed
    + [("GB", 0, "SD01: SAFE DEPOSIT BOX CONTENTS")]      # no cash
)


@pytest.fixture(scope="module")
def found():
    return co.discover(Sandbox(), ["MX", "GB", "PH", "CN", "TW", "VE"], try_conversions=True)


def plan(found, **inputs):
    return bk.plan(HOLDER, CLAIMS, found, {"handover_date": "2027-06-01", **inputs}, today=TODAY)


def row(p, country):
    return next(c for c in p["corridors"] if c["country"] == country)


def test_the_fee_rule_on_one_claim_is_exact_arithmetic():
    below = bk.split(120_00, 5_00, 250_00)          # the holder sends (120.00 + 5.00) / (1 - 0.003) = 125.38
    assert below == {"too_small": False, "incoming": 38, "fee": 5_00, "sends": 125_38, "net": 125_00, "bearer": "holder"}
    above = bk.split(2_316_40, 5_00, 250_00)        # the claim bears 0.3 percent and the payout fee
    assert above["bearer"] == "claim" and above["sends"] == 2_316_40 and above["incoming"] == 6_95 and above["net"] == 2_309_45
    assert bk.split(3_00, 5_00, 250_00)["too_small"] and bk.split(5_02, 5_00, 250_00)["too_small"]
    assert not bk.split(5_03, 5_00, 250_00)["too_small"]     # 5.03 less 0.02 less 5.00 leaves a cent
    assert bk.split(250_00, 5_00, 250_00)["bearer"] == "claim"      # the line itself is not below the line


def test_every_claim_gets_a_route_local_where_it_exists_then_swift_then_none(found):
    p = plan(found)
    mx, tw, cn, ve, other = (row(p, c) for c in ("MX", "TW", "CN", "VE", "other"))
    assert mx["route"] == "LOCAL" and mx["scheme"] == "SPEI" and mx["pay_currency"] == "MXN" and mx["fee"]["basis"] == "observed"
    assert mx["local"] == {"owners": 4, "usd": 2676.40} and mx["swift"] == {"owners": 1, "usd": 40000.0}     # over 25,000 USD
    assert mx["over_local_limit"] == {"owners": 1, "usd": 40000.0} and mx["too_small"]["owners"] == 1
    assert tw["route"] == "SWIFT" and tw["pay_currency"] == "USD" and tw["fee"]["usd"] == "25.00" and "no local schema" in tw["why_not_local"]
    assert tw["too_small"] == {"owners": 1, "usd": 20.0, "would_cost": 25.06}
    assert cn["route"] == "SWIFT" and cn["pay_currency"] == "CNY" and "e-commerce" in cn["why_not_local"]
    assert ve["route"] is None and ve["route_words"] == co.NOT_PAYABLE and ve["unpayable"] == {"owners": 1, "usd": 700.0}
    assert "no schema" in ve["why_unpayable"] and "cannot be placed" in other["why_unpayable"]
    assert row(p, "GB")["no_cash"] == 1 and row(p, "GB")["fee"]["basis"] == "estimate" and row(p, "GB")["fee"]["usd"] == "1.00"
    t = p["totals"]
    assert t["owners"] == len(CLAIMS) and t["usd"] == round(sum(c[1] for c in CLAIMS) / 100, 2)
    assert t["local"]["usd"] + t["swift"]["usd"] + t["unpayable"]["usd"] + t["too_small"]["usd"] == t["usd"]
    assert t["local"]["countries"] == 3 and t["swift"]["countries"] == 2 and t["unpayable"]["countries"] == 2
    assert t["no_cash"]["owners"] == 1 and t["observed_fee_corridors"] == 3 and t["estimated_fee_corridors"] == 2
    assert p["statement"] == bk.STATEMENT and "did not ask" in p["statement"] and "public file" in p["statement"]


def test_costs_and_what_owners_receive_follow_the_fee_rule(found):
    p = plan(found)
    gb = row(p, "GB")
    # 800.00 bears its own fees (2.40 and 1.00); below the line of 250.00 the holder adds them to 90.00
    assert gb["from_claim"] == {"owners": 1, "usd": 800.0, "fees": 3.40} and gb["holder_bears"] == {"owners": 1, "usd": 90.0, "adds": 1.28}
    assert gb["fees"] == 4.68 and gb["sends"] == 891.28 and gb["cost_per_payment"] == 2.34
    # 796.60 from the larger claim; the small one arrives whole (the holder's sum is rounded up, which leaves a cent over)
    assert gb["owners_receive"]["currency"] == "GBP" and gb["owners_receive_usd"] == 886.61
    assert gb["owners_receive"]["amount"] == pytest.approx(886.61 / 1.33, abs=0.01)
    t = p["totals"]
    assert t["cost"]["usd"] == round(sum(c["fees"] for c in p["corridors"]), 2)
    assert t["cost"]["borne_by_holder"] + t["cost"]["out_of_claims"] == pytest.approx(t["cost"]["usd"])
    assert t["holder_funds_usd"] == round(t["planned"]["usd"] + t["holder_bears"]["adds"], 2)
    assert t["cost"]["percent"] == round(t["cost"]["usd"] / t["planned"]["usd"] * 100, 2)


def test_raising_the_small_claim_line_moves_claims_to_the_holder_and_changes_the_total(found):
    low, high = plan(found), plan(found, small_claim_usd="1000")
    assert low["totals"]["holder_bears"]["owners"] == 4 and high["totals"]["holder_bears"]["owners"] == 7
    assert high["totals"]["holder_funds_usd"] > low["totals"]["holder_funds_usd"]
    assert high["totals"]["cost"]["borne_by_holder"] > low["totals"]["cost"]["borne_by_holder"]
    lines = {c["what"]: c for c in bk.changes(low, high)}
    assert lines["Changed"]["after"] == "the small-claim line"
    assert lines["Claims on which the holder bears the fees"] == {**lines["Claims on which the holder bears the fees"], "before": "4", "after": "7", "delta": 3}
    assert "What the holder funds" in lines and bk.changes(low, low) == []
    zero = plan(found, small_claim_usd="0")
    assert zero["totals"]["holder_bears"]["owners"] == 0 and zero["totals"]["too_small"] == low["totals"]["too_small"]


def test_moving_the_handover_date_closer_drops_the_slow_corridors(found):
    far = plan(found)
    assert far["days_left"] == 200 and far["totals"]["too_late"]["owners"] == 0
    assert [x["country"] for x in far["order"]["work"]][0] == "MX"              # most dollars a day first
    assert {x["country"]: x["needs_days"] for x in far["order"]["work"]} == {"MX": 32, "GB": 32, "PH": 32, "TW": 35, "CN": 35}
    assert far["order"]["work"][0]["usd_per_day"] == 1333.63 and far["order"]["work"][0]["start_by_words"] == "30 April 2027"   # 42,676.40 over 32 days
    near = plan(found, handover_date="2026-12-17")          # 34 days: local rails still fit, SWIFT does not
    assert near["days_left"] == 34 and [x["country"] for x in near["order"]["dropped"]] == ["CN", "TW"]
    assert near["totals"]["too_late"] == {"owners": 2, "usd": 6000.0, "countries": 2}
    assert near["totals"]["planned"]["usd"] == far["totals"]["planned"]["usd"] - 6000.0
    assert row(near, "TW")["in_time"] is False and row(near, "TW")["planned"]["owners"] == 0
    assert "USD" not in [c["currency"] for c in near["funding"]["currencies"]]
    lines = {c["what"]: c for c in bk.changes(far, near)}
    assert lines["Corridors dropped"]["after"] == "China, Taiwan" and lines["Dollars too close to the handover"]["after"] == "$6,000"
    gone = plan(found, handover_date="2026-12-10")          # 27 days: fewer than an owner needs to send a document
    assert gone["order"]["work"] == [] and gone["totals"]["planned"]["owners"] == 0
    card = next(c for c in gone["cards"] if c["kind"] == "book_order")
    assert card["tone"] == "stop" and "whole book stays with the State process" in card["did"]
    longer = plan(found, handover_date="2026-12-17", document_days=20)      # owners answer faster: SWIFT fits again
    assert longer["totals"]["too_late"]["owners"] == 0


def test_the_tolerance_decides_which_refused_transfers_would_be_resent_without_asking_about_the_amount(found):
    tight, wide = plan(found), plan(found, tolerance_percent="5")
    # a second 5.00 fee on about 2,309 is 0.22 percent; on 120.00 it is 4.2 percent; 25.00 on about 972 is 2.6 percent
    assert tight["totals"]["refusal"]["inside"] == 5 and tight["totals"]["refusal"]["outside"] == 6
    assert wide["totals"]["refusal"]["inside"] == 11 and wide["totals"]["refusal"]["outside"] == 0
    none = plan(found, tolerance_percent="0")
    assert none["totals"]["refusal"]["inside"] == 0
    lines = {c["what"]: c for c in bk.changes(tight, wide)}
    assert lines["Claims that would stop and ask the owner"]["delta"] == -6
    card = next(c for c in wide["cards"] if c["kind"] == "book_tolerance")
    assert "5%" in card["allowed"] and "about the amount" in card["allowed"] and "always approved by the holder" in card["why"][0]


def test_funding_takes_the_cheaper_way_from_real_quotes_and_claims_no_saving_where_there_is_none(found):
    f = plan(found)["funding"]
    by = {c["currency"]: c for c in f["currencies"]}
    assert by["MXN"]["mode"] == "batch" and by["MXN"]["saving_usd"] == 0.0 and by["MXN"]["rate_depends_on_size"] is False
    assert by["MXN"]["each"]["conversions"] == 5 and by["MXN"]["batch"]["conversions"] == 1 and by["MXN"]["each"]["buys"] == by["MXN"]["batch"]["buys"]
    assert by["MXN"]["lock"]["percent"] == pytest.approx(0.12, abs=0.001) and by["MXN"]["round_trip"]["percent"] == pytest.approx(2.0, abs=0.01)
    assert by["PHP"]["mode"] == "each" and "does not convert" in by["PHP"]["mode_words"] and by["PHP"]["can_hold"] is False
    assert by["USD"]["mode"] == "none" and by["USD"]["conversions"] == 0
    assert f["saving_usd"] == 0.0 and f["rate_depends_on_size"] is False
    assert f["conversions_if_each"] == 5 + 2 + 2 + 1 and f["conversions_planned"] == 1 + 1 + 2 + 1
    assert f["holder_funds_usd"] == plan(found)["totals"]["holder_funds_usd"]
    card = next(c for c in plan(found)["cards"] if c["kind"] == "book_funding")
    assert "same rate at 6 sizes" in card["happened"] and "Saves $0.00" in card["money"] and "saves nothing on the rate" in card["why"][1]


def test_a_rate_that_is_better_for_larger_amounts_shows_up_as_a_saving():
    sandbox = Sandbox()
    sandbox.spread_by_size = {10: 0.004, 100: 0.004, 1_000: 0.002}       # small amounts are quoted worse
    tiered = co.discover(sandbox, ["MX", "GB", "PH", "CN", "TW", "VE"], try_conversions=True)
    f = plan(tiered)["funding"]
    mxn = next(c for c in f["currencies"] if c["currency"] == "MXN")
    assert mxn["rate_depends_on_size"] and mxn["mode"] == "batch" and mxn["batch"]["buys"] > mxn["each"]["buys"]
    assert mxn["saving_usd"] > 1 and f["saving_usd"] >= mxn["saving_usd"] and f["rate_depends_on_size"]
    worse = Sandbox()
    worse.spread_by_size = {100_000: 0.01, 1_000_000: 0.01}             # and the other way round: single payments win
    f = plan(co.discover(worse, ["MX", "GB", "PH", "CN", "TW", "VE"], try_conversions=True))["funding"]
    assert next(c for c in f["currencies"] if c["currency"] == "MXN")["mode"] == "each"


def test_every_decision_is_a_card_of_four_lines_with_real_numbers(found):
    cards = plan(found)["cards"]
    assert [c["kind"] for c in cards] == ["book_routes", "book_fees", "book_small", "book_funding", "book_order", "book_tolerance"]
    for card in cards:
        assert all(card[k] and isinstance(card[k], str) for k in ("happened", "allowed", "did", "money", "title"))
        assert card["tone"] in ("go", "ask", "stop") and card["why"] and "\u2014" not in json.dumps(card, ensure_ascii=False)
    routes, small = cards[0], cards[2]
    assert "3 countries by local rails, 2 by SWIFT, 2 not payable by transfer" in routes["did"]
    assert "2 claims, $23.00" in small["happened"] and "stay with the State process" in small["did"]
    assert "1 property" in small["why"][1]


def test_inputs_are_checked_and_said_in_words(found):
    assert bk.clean_inputs({}, TODAY) == {"tolerance_percent": "0.5", "small_claim_usd": "250.00", "handover_date": "2027-06-01", "document_days": 30}
    with pytest.raises(ValueError, match="tolerance"):
        bk.clean_inputs({"tolerance_percent": "50"}, TODAY)
    with pytest.raises(ValueError, match="handover date"):
        bk.clean_inputs({"handover_date": "soon"}, TODAY)
    public = bk.without_cents(plan(found))
    assert "_cents" not in json.dumps(public)


# ---- the books, read from the register ------------------------------------------------------------------------

def test_the_books_are_read_from_the_register_one_line_for_each_property_and_no_owner_in_them(tmp_path):
    db = make_register(tmp_path)        # the made-up register: one owner abroad (P3, 5,120.00, in the Philippines)
    con = duckdb.connect(str(db))
    for rid, city, country, amount, holder in [("P9", "OSAKA", "JP", 300.0, "WELLS FARGO BANK NA"), ("P9", "LYON", "FR", 300.0, "WELLS FARGO BANK NA"),
                                               ("P10", "LYON", "FR", 45.5, "WELLS FARGO BANK N.A."), ("P11", "LYON", "FR", 400.0, "JOHN SMITH DDS")]:
        con.execute("insert into records select 'TEST', ?, 'COHOLDER SOMEONE', 'COHOLDER SOMEONE', '', ?, '', '', ?, ?, 'USD', ?, '', '', 'SAVINGS', 'K', 'S'",
                    [rid, city, country, amount, holder])
    rows = bk.build(con)
    con.close()
    assert sorted(rows) == [("JOHN SMITH DDS", "FR", 400.0, "SAVINGS"), ("KAISER FOUNDATION HOSPITALS", "PH", 5120.0, "WAGES"),
                            ("WELLS FARGO BANK N.A.", "FR", 45.5, "SAVINGS"), ("WELLS FARGO BANK NA", "FR", 300.0, "SAVINGS")]   # P9 once, under FR
    assert "SOMEONE" not in str(rows)
    path = tmp_path / "books.parquet"
    bk.write(rows, path)
    books = bk.Books.load(path)
    assert [h["name"] for h in books.top()] == ["KAISER FOUNDATION HOSPITALS", "Wells Fargo"]      # the practice is never listed
    line, claims = books.get("Wells Fargo")
    assert line["properties"] == 2 and line["amount"] == 345.5 and line["countries"] == 1 and line["kind"] == "Banks and credit unions"
    assert sorted(claims) == [("FR", 4550, "SAVINGS"), ("FR", 30000, "SAVINGS")]
    assert books.get("WELLS FARGO BANK NA")[0]["name"] == "Wells Fargo" and books.get("JOHN SMITH DDS") is None and books.get("NOBODY") is None
    assert [h["name"] for h in books.find("wells")] == ["Wells Fargo"] and books.find("smith") == [] and books.find("w") == []
    assert bk.books(path).top() == books.top() and bk.books(tmp_path / "missing.parquet") is None


# ---- the routes ------------------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, found):
    books = tmp_path / "books.parquet"
    bk.write([(HOLDER["name"], c, cents / 100, t) for c, cents, t in CLAIMS] + [("JOHN SMITH DDS", "MX", 900.0, WAGES)], books)
    corridors = tmp_path / "corridors.json"
    co.save(found, corridors)
    db = make_register(tmp_path)
    app = create_app(db_path=db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no", claims_dir=tmp_path / "claims",
                     books_path=books, corridors_path=corridors, payer_key="k")
    with TestClient(app) as client:
        yield client


def test_the_api_lists_holders_that_may_be_named_and_plans_a_book(api):
    listed = api.get("/api/book/holders").json()
    assert [h["name"] for h in listed["top"]] == ["ACME PAYROLL INC"] and listed["corridors_ready"] and listed["matches"] == []
    assert api.get("/api/book/holders", params={"q": "acme"}).json()["matches"][0]["key"] == "ACME PAYROLL INC"
    assert api.get("/api/book/holders", params={"q": "smith"}).json()["matches"] == []
    got = api.get("/api/book", params={"holder": "ACME PAYROLL INC"})
    assert got.status_code == 200
    p = got.json()
    assert p["holder"]["name"] == "ACME PAYROLL INC" and p["changes"] == [] and p["baseline"]["inputs"] == p["inputs"]
    assert p["totals"]["owners"] == len(CLAIMS) and len(p["cards"]) == 6 and "_cents" not in got.text
    assert {s["country"] for s in p["slice"]} <= {"MX", "GB", "PH", "TW"}
    moved = api.get("/api/book", params={"holder": "ACME PAYROLL INC", "small_claim_usd": "1000"}).json()
    assert moved["changes"][0]["after"] == "the small-claim line" and moved["baseline"]["inputs"]["small_claim_usd"] == "250.00"
    assert moved["totals"]["holder_bears"]["owners"] > p["totals"]["holder_bears"]["owners"]
    assert api.get("/api/book", params={"holder": "JOHN SMITH DDS"}).status_code == 404        # counted, never opened
    assert api.get("/api/book", params={"holder": "ACME PAYROLL INC", "tolerance_percent": "50"}).status_code == 422
    assert "tolerance" in api.get("/api/book", params={"holder": "ACME PAYROLL INC", "tolerance_percent": "50"}).json()["detail"]


def test_the_plan_starts_from_the_limits_the_holder_has_saved(api):
    saved = api.put("/api/payer/instructions", headers={"X-Payer-Key": "k"},
                    json={"tolerance_percent": "1", "small_claim_usd": "500", "route_rule": "most_to_claimant", "deadline_days": 14,
                          "handover_date": "2027-06-10", "document_days": 25})
    assert saved.status_code == 200
    p = api.get("/api/book", params={"holder": "ACME PAYROLL INC"}).json()
    assert p["inputs"] == {"tolerance_percent": "1", "small_claim_usd": "500.00", "handover_date": "2027-06-10", "document_days": 25}


def test_without_the_prepared_files_the_routes_say_what_to_run(tmp_path, found):
    db = make_register(tmp_path)
    app = create_app(db_path=db, totals_path=tmp_path / "t.json", web_dist=tmp_path / "no", claims_dir=tmp_path / "claims",
                     books_path=tmp_path / "none.parquet", corridors_path=tmp_path / "none.json")
    with TestClient(app) as client:
        assert client.get("/api/book/holders").status_code == 503 and "make_books.py" in client.get("/api/book/holders").json()["detail"]
        bk.write([(HOLDER["name"], "MX", 10.0, WAGES)], tmp_path / "none.parquet")
        answer = client.get("/api/book", params={"holder": "ACME PAYROLL INC"})
        assert answer.status_code == 503 and "discover_corridors.py" in answer.json()["detail"]
