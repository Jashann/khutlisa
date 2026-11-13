"""Queensland's public register as a second source: read from the portal in pages, loaded in the shape the search
expects, checked against what the portal reports, and searched beside California's file with its Australian
dollars kept apart. The portal is a small function here; no network. The records in the fixture are invented."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import queensland as qld
from khutlisa.server import MASK_DOT, create_app
from test_claims import make_register

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "queensland_sample.json").read_text())["records"]


class Portal:
    """Answers the two queries the loader sends, from the fixture."""

    def __init__(self, rows=FIXTURE, fail_after: int | None = None):
        self.rows, self.asked, self.fail_after = list(rows), [], fail_after

    def __call__(self, sql: str) -> dict:
        self.asked.append(sql)
        if self.fail_after is not None and len(self.asked) > self.fail_after:
            raise qld.PortalError("the portal answered HTTP 502")
        if sql.startswith("SELECT COUNT(*)"):
            return {"records": [{"n": len(self.rows), "total": round(sum(r["Amount"] for r in self.rows), 2),
                                 "latest": max(r["DateRec"] for r in self.rows)}]}
        after = int(sql.split('"_id" > ')[1].split(" ")[0])
        limit = int(sql.rsplit("LIMIT ", 1)[1])
        return {"records": [r for r in sorted(self.rows, key=lambda r: r["_id"]) if r["_id"] > after][:limit]}


@pytest.fixture
def loaded(tmp_path):
    path = tmp_path / "queensland.duckdb"
    con = qld.connect(path)
    n = qld.load(con, qld.pages(Portal(), page=2, sleep=lambda s: None))
    figures = qld.loaded_figures(con)
    con.close()
    return path, n, figures


def test_the_register_is_read_in_pages_each_starting_after_the_last_row_seen():
    portal = Portal()
    got = [[r["_id"] for r in page] for page in qld.pages(portal, page=2, sleep=lambda s: None)]
    assert got == [[1, 2], [3, 4], [5]]
    assert ['"_id" > 0' in portal.asked[0], '"_id" > 2' in portal.asked[1], '"_id" > 4' in portal.asked[2]] == [True] * 3
    assert all(qld.RESOURCE in q and 'ORDER BY "_id"' in q for q in portal.asked) and len(portal.asked) == 3
    assert list(qld.pages(Portal(rows=[]), sleep=lambda s: None)) == []


def test_a_row_becomes_a_record_in_australian_dollars_with_a_four_digit_postcode():
    record = qld.as_record(FIXTURE[2])
    assert record[:3] == ("AU-QLD", "900000000003", "SANTOS MARIA LUZ") and record[6] == "0800"       # 800 is 0800
    assert record[8] == "AU" and record[9] == 150.0 and record[10] == "AUD" and record[11] == "EXAMPLE INSURANCE LIMITED"
    assert record[14] == "Unclaimed money" and record[15] == "2019-06-11"
    assert qld.postcode(None) == "" and qld.postcode(4000.0) == "4000" and qld.postcode("ABC") == "ABC"
    assert qld.as_record({"Owner": None, "Amount": "x"})[9] == 0.0


def test_the_load_matches_the_count_and_the_total_the_portal_reports(loaded):
    path, n, figures = loaded
    assert n == 5 and figures == {"records": 5, "amount": 14323.74, "distinct_ids": 5}
    check = qld.verify(figures, qld.portal_figures(Portal()))
    assert check["ok"] and check["records_match"] and check["amount_match"]
    assert not qld.verify(figures, {"records": 6, "amount": 14323.74})["ok"]
    assert not qld.verify(figures, {"records": 5, "amount": 14323.75})["amount_match"]
    con = duckdb.connect(str(path), read_only=True)
    row = con.execute("select owner_norm, phon_first, phon_last, currency, source from records where record_id = '900000000001'").fetchone()
    con.close()
    assert row[0] == "QUILLFEATHER MARIGOLD T" and row[1] and row[2] and row[3:] == ("AUD", "AU-QLD")      # searchable like the rest


def test_loading_again_replaces_the_rows_and_does_not_double_them(tmp_path):
    con = qld.connect(tmp_path / "q.duckdb")
    qld.load(con, qld.pages(Portal(), sleep=lambda s: None))
    qld.load(con, qld.pages(Portal(rows=FIXTURE[:2]), sleep=lambda s: None))
    assert qld.loaded_figures(con)["records"] == 2
    con.close()


def test_a_portal_that_cannot_be_read_says_so_and_the_loader_stops(tmp_path):
    with pytest.raises(qld.PortalError, match="502"):
        list(qld.pages(Portal(fail_after=1), page=2, sleep=lambda s: None))
    assert qld.facts(tmp_path / "missing.duckdb") is None
    assert "Public Trustee of Queensland" in qld.ATTRIBUTION and "Attribution 4.0" in qld.ATTRIBUTION and qld.LICENCE_URL.endswith("/by/4.0/")


def app_with(tmp_path, queensland_path):
    db = make_register(tmp_path)
    return create_app(db_path=db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no", claims_dir=tmp_path / "claims",
                      queensland_path=queensland_path, search_per_minute=0, search_per_hour=0)


def test_one_search_runs_over_both_registers_and_keeps_the_currencies_apart(tmp_path, loaded):
    path, _, _ = loaded
    with TestClient(app_with(tmp_path, path)) as api:
        info = api.get("/api/register").json()
        assert info["queensland"]["owner_records"] == 5 and info["queensland"]["currency"] == "AUD" and info["queensland"]["amount"] == 14323.74
        assert "Public Trustee of Queensland" in info["queensland"]["attribution"] and info["owner_records"] > 0
        got = api.post("/api/search", json={"given_names": ["Maria", "Luz"], "family_names": ["Santos"],
                                            "places": [{"city": "Daly City", "postcode": "94015"}]}).json()
        sources = {m["source"] for m in got["matches"]}
        assert "AU-QLD" in sources and len(sources) > 1                     # California's and Queensland's records together
        assert got["searched"]["queensland_records"] == 5 and got["searched"]["owner_records"] == info["owner_records"]
        mine = next(m for m in got["matches"] if m["source"] == "AU-QLD")
        assert mine["currency"] == "AUD" and mine["amount"] == 150.0 and not mine["owner_is_organisation"]
        assert mine["owner"] == f"S{MASK_DOT * 3} M{MASK_DOT * 3} L{MASK_DOT * 3}" and "SANTOS MARIA" not in json.dumps(mine)    # masked like anyone
        assert mine["holder_name"] == "EXAMPLE INSURANCE LIMITED" and mine["record_id"] != "900000000003"         # an id of our own
        # the US dollar figure never includes Australian dollars; every currency has its own line
        usd = sum(m["amount"] for m in got["matches"] if m["strength"] == "strong" and m["currency"] == "USD")
        assert got["strong_amount"] == round(usd, 2) and got["currency"] == "USD"
        assert all(a["currency"] in ("USD", "AUD") for a in got["strong_amounts"])


def test_a_person_in_queenslands_register_is_never_named_and_an_organisation_is(tmp_path, loaded):
    path, _, _ = loaded
    with TestClient(app_with(tmp_path, path)) as api:
        got = api.get("/api/organisations", params={"q": "northfield"}).json()
        other = got["queensland"]
        assert [r["owner"] for r in other["results"]] == ["NORTHFIELD CITY COUNCIL"] and other["results"][0]["currency"] == "AUD"
        assert other["currency"] == "AUD" and other["owner_records"] == 5 and "Creative Commons" in other["attribution"]
        assert all(r["currency"] == "USD" for r in got["results"])           # California's list holds no Australian dollars
        people = api.get("/api/organisations", params={"q": "quillfeather"}).json()
        assert people["queensland"]["results"] == [] and people["results"] == []
        estate = api.get("/api/organisations", params={"q": "periwinkle"}).json()
        assert estate["queensland"]["results"] == []                         # an estate carries a person's name


def test_a_claim_is_not_opened_on_a_queensland_record(tmp_path, loaded):
    path, _, _ = loaded
    with TestClient(app_with(tmp_path, path)) as api:
        got = api.post("/api/search", json={"given_names": ["Marigold"], "family_names": ["Quillfeather"]}).json()
        record = next(m for m in got["matches"] if m["source"] == "AU-QLD")
        answer = api.post("/api/claims", json={"record_id": record["record_id"], "claimant": {
            "name": "Marigold Quillfeather", "address": "1 Example Road", "country": "AU", "email": "m@example.org", "relationship": "self"}})
        assert answer.status_code == 422 and "Public Trustee of Queensland" in answer.json()["detail"]


def test_without_queenslands_file_the_search_and_its_answers_are_as_before(tmp_path):
    with TestClient(app_with(tmp_path, tmp_path / "not-there.duckdb")) as api:
        assert "queensland" not in api.get("/api/register").json()
        got = api.post("/api/search", json={"given_names": ["Maria"], "family_names": ["Santos"]}).json()
        assert "queensland_records" not in got["searched"] and all(m["source"] != "AU-QLD" for m in got["matches"])
        assert "queensland" not in api.get("/api/organisations", params={"q": "northfield"}).json()
