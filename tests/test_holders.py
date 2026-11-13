"""The "For holders" figures: which holders (the organisations that reported the property) have the most
properties and dollars for owners abroad. They are computed from California's file by scripts/make_holders.py
and served from a small file. Holder names are organisations; a name that could be a person's is never listed."""
from __future__ import annotations

import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import holders
from khutlisa.registers import DB_PATH
from khutlisa.server import create_app
from test_claims import make_register


def test_holder_names_that_could_be_a_persons_are_kept_out_of_the_lists():
    assert holders.listable("CATHAY BANK") and holders.listable("UNION BANK N.A.")
    assert holders.listable("CHARLES SCHWAB & CO INC")           # read by hand: a well-known broker
    assert not holders.listable("EMMETT A. LARKIN COMPANY, INC.") and not holders.listable("JOHN SMITH DDS")
    assert not holders.listable("") and not holders.listable("ESTATE OF SOMEBODY")


def test_spellings_of_one_company_are_added_together_only_by_the_stated_prefixes():
    assert holders.family("BANK OF AMERICA NT&SA BRANCH:0659-INTL PRIVATE BNKG SVCS") == "Bank of America"
    assert holders.family("Bank of America - Passbook Accounts") == "Bank of America"
    assert holders.family("BANK OF AMERICAN FORK") is None           # another bank: the prefix ends at a word
    assert holders.family("WELLS FARGO BANK NA (APECS 1009)") == "Wells Fargo"
    assert holders.family("STANFORD FEDERAL CREDIT UNION") is None   # not the university


def test_the_figures_are_computed_from_the_register_counting_each_property_once(tmp_path):
    db = make_register(tmp_path)        # the made-up register: one owner abroad (P3, 5,120.00, in the Philippines)
    con = duckdb.connect(str(db))
    con.execute("insert into records select 'TEST', 'P9', 'COHOLDER ANOTHER', 'COHOLDER ANOTHER', '', 'OSAKA', '', "
                "'', 'JP', 300.0, 'USD', 'WELLS FARGO BANK NA', '', '', 'SAVINGS', 'K', 'A'")
    con.execute("insert into records select 'TEST', 'P9', 'COHOLDER SECOND', 'COHOLDER SECOND', '', 'OSAKA', '', "
                "'', 'JP', 300.0, 'USD', 'WELLS FARGO BANK NA', '', '', 'SAVINGS', 'K', 'S'")
    con.execute("insert into records select 'TEST', 'P10', 'COHOLDER THIRD', 'COHOLDER THIRD', '', 'LYON', '', "
                "'', 'FR', 45.5, 'USD', 'WELLS FARGO BANK N.A.', '', '', 'SAVINGS', 'K', 'T'")
    con.execute("insert into records select 'TEST', 'P11', 'COHOLDER FOURTH', 'COHOLDER FOURTH', '', 'LYON', '', "
                "'', 'FR', 400.0, 'USD', 'JOHN SMITH DDS', '', '', 'WAGES', 'K', 'F'")
    made = holders.compute(con)
    con.close()
    assert made["holders_with_an_owner_abroad"] == 3 and made["properties"] == 4 and made["amount"] == 5865.5
    top = made["by_amount"]
    assert [(h["name"], h["properties"], h["amount"]) for h in top] == [
        ("KAISER FOUNDATION HOSPITALS", 1, 5120.0), ("Wells Fargo", 2, 345.5)]     # two owners, one property
    assert top[1]["spellings"] == 2 and made["passed_over_as_possibly_a_person"] == 1   # counted, never named
    assert made["by_properties"][0]["name"] == "Wells Fargo"
    assert made["property_types"][0] == {"type": "WAGES", "properties": 2, "amount": 5520.0}
    assert made["share_of_top_ten"]["amount_percent"] == 93.2


def test_the_api_serves_the_prepared_figures_the_law_in_short_and_says_no_holder_uses_it(tmp_path, monkeypatch):
    path = tmp_path / "holders_abroad.json"
    path.write_text(json.dumps({"properties": 4, "amount": 5475.5, "holders_with_an_owner_abroad": 3,
                                "by_amount": [], "by_properties": [], "property_types": []}))
    monkeypatch.setattr(holders, "FILE", path)
    db = make_register(tmp_path)
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no")) as api:
        got = api.get("/api/holders").json()
    assert got["figures"]["holders_with_an_owner_abroad"] == 3
    assert "No holder uses Khutlisa yet" in got["status"]
    assert all(rule["url"].startswith("https://") and rule["mark"] in ("verified", "our reading")
               for rule in got["law"])
    assert any("1532(b)" in rule["source"] for rule in got["law"]) and any("1560(b)" in rule["source"] for rule in got["law"])
    assert got["proposed_pricing"]["label"].startswith("Proposed")
    monkeypatch.setattr(holders, "FILE", tmp_path / "missing.json")
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no")) as api:
        assert api.get("/api/holders").status_code == 503


@pytest.mark.skipif(not DB_PATH.exists(), reason="needs California's file in data/registers.duckdb")
def test_the_prepared_file_matches_the_database_to_the_cent():
    stored = json.loads(holders.FILE.read_text())
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        now = holders.compute(con)
    finally:
        con.close()
    for key in ("properties", "amount", "holders_with_an_owner_abroad", "by_amount", "by_properties",
                "property_types", "passed_over_as_possibly_a_person", "share_of_top_ten", "kinds_of_money",
                "kinds_of_holder", "wages"):
        assert stored[key] == now[key], key
    assert all(holders.listable(s) for row in stored["by_amount"] + stored["by_properties"]
               for s in row["as_written"])


@pytest.mark.skipif(not DB_PATH.exists(), reason="needs California's file in data/registers.duckdb")
def test_the_kinds_of_money_and_of_holder_add_up_to_the_same_properties_and_dollars():
    stored = json.loads(holders.FILE.read_text())
    money, kinds = stored["kinds_of_money"], stored["kinds_of_holder"]
    assert sum(k["properties"] for k in money) == stored["properties"]
    assert round(sum(k["amount"] for k in money), 2) == stored["amount"]
    assert sum(k["holders"] for k in kinds) == stored["holders_with_an_owner_abroad"]
    assert sum(k["properties"] for k in kinds) == stored["properties"]
    assert all(holders.listable(t["name"]) or holders.family(t["name"]) or t["name"] in dict((f, 1) for f, _ in holders.FAMILIES)
               for k in kinds for t in k["top"])
    assert next(k for k in kinds if k["key"] == "unclassified")["top"] == []
    assert stored["wages"]["holders"] > 0 and stored["wages"]["amount"] == next(k for k in money if k["key"] == "wages")["amount"]


def test_the_api_states_the_buyer_with_sources(tmp_path, monkeypatch):
    path = tmp_path / "holders_abroad.json"
    path.write_text(json.dumps({"properties": 1, "amount": 1.0, "holders_with_an_owner_abroad": 1, "by_amount": [],
                                "by_properties": [], "property_types": []}))
    monkeypatch.setattr(holders, "FILE", path)
    with TestClient(create_app(db_path=make_register(tmp_path), totals_path=tmp_path / "t.json", web_dist=tmp_path / "no")) as api:
        got = api.get("/api/holders").json()
    assert got["buyer"]["who"].startswith("Any holder with a bank account") and len(got["buyer"]["why"]) == 5
    assert "none has been asked" not in json.dumps(got)
