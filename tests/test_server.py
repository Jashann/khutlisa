"""The web API, run against a small made-up register. No real record is used here."""
import json
import re

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa.names import normalise, phonetic
from khutlisa.server import MASK_DOT, MASK_DOTS, create_app, mask_name, shown_as_organisation

# (record_id, owner_name, street, city, region, postcode, country, amount, holder, property_type)
PEOPLE = [
    ("P1", "SANTOS MARIA L", "1482 WINDROSE LANE APT 7", "DALY CITY", "CA", "94015", "US", 1840.55,
     "KAISER FOUNDATION HOSPITALS", "WAGES"),
    ("P2", "SANTOS MARIA QUIXOTIC", "77 HOLLYHOCK TERRACE", "DALY CITY", "CA", "94015", "US", 320.10,
     "PACIFIC GAS AND ELECTRIC", "UTILITY DEPOSIT"),
    ("P3", "MARIA LUZ SANTOS", "9 CALLE ZARAGOZANA", "CEBU", "", "6000", "PH", 5120.00,
     "KAISER FOUNDATION HOSPITALS", "WAGES"),
    ("P4", "VILLANUEVA LUZ", "2210 EUCALYPTUS BOULEVARD", "LOS ANGELES", "CA", "90011", "US", 610.00,
     "WELLS FARGO BANK", "SAVINGS"),
    ("P5", "SANTOS ROBERTO", "5 FERNWHISTLE COURT", "FRESNO", "CA", "93701", "US", 75.25, "ACME PAYROLL INC", "WAGES"),
    ("P6", "CHURCH ROSALIND", "31 MAPLETHORPE ROAD", "DALY CITY", "CA", "94015", "US", 410.00, "ACME PAYROLL INC",
     "WAGES"),
    ("P7", "NGUYEN CO VAN", "600 TAMARISK STREET", "SAN JOSE", "CA", "95112", "US", 990.00, "ACME PAYROLL INC",
     "WAGES"),
]
ORGS = [
    ("O1", "SANTOS TRUCKING INC", "400 HARBOR WAY", "DALY CITY", "CA", "94015", "US", 2500.00, "STATE FUND", "REFUND"),
    ("O2", "NORTHFIELD UNIVERSITY", "1 CAMPUS DRIVE", "PALO ALTO", "CA", "94305", "US", 55690.09,
     "FIRST EXAMPLE BANK", "VENDOR PAYMENT"),
    ("O3", "NORTHFIELD UNIVERSITY BOOKSTORE", "2 CAMPUS DRIVE", "PALO ALTO", "CA", "94305", "US", 120.00,
     "FIRST EXAMPLE BANK", "VENDOR PAYMENT"),
    ("O4", "NORTHFIELD HARDWARE LLC", "88 MAIN STREET", "FRESNO", "CA", "93701", "US", 9000.00, "ACME PAYROLL INC",
     "REFUND"),
]
# A private person whose family name happens to be the search word used for organisations.
PEOPLE.append(("P8", "NORTHFIELD ELEANOR", "12 QUILLWORT CLOSE", "FRESNO", "CA", "93701", "US", 99999.00,
               "ACME PAYROLL INC", "WAGES"))

TOTALS = {
    "source": "Made-up register for tests", "owner_rows": len(PEOPLE) + len(ORGS),
    "all_properties": len(PEOPLE) + len(ORGS), "all_amount": 100000.0,
    "abroad_properties": 12, "abroad_amount": 9000.0,
    "by_country": [
        {"code": "JP", "properties": 4, "amount": 4000.0}, {"code": "PH", "properties": 3, "amount": 2500.0},
        {"code": "PHL", "properties": 1, "amount": 500.0}, {"code": "MEX", "properties": 1, "amount": 900.0},
        {"code": "SZ", "properties": 1, "amount": 600.0}, {"code": "939", "properties": 1, "amount": 300.0},
        {"code": "ZZ", "properties": 1, "amount": 200.0},
    ],
}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    folder = tmp_path_factory.mktemp("register")
    db = folder / "registers.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""create table records (source varchar, record_id varchar, owner_name varchar, owner_norm varchar,
        owner_street varchar, owner_city varchar, owner_region varchar, owner_postcode varchar, owner_country varchar,
        amount double, currency varchar, holder_name varchar, holder_city varchar, holder_region varchar,
        property_type varchar, phon_first varchar, phon_last varchar)""")
    for rid, name, street, city, region, zip_, country, amount, holder, kind in PEOPLE + ORGS:
        norm = normalise(name)
        con.execute("insert into records values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ["TEST", rid, name, norm, street, city, region, zip_, country, amount, "USD", holder, "", "", kind,
                     phonetic(norm.split()[0]), phonetic(norm.split()[-1])])
    con.close()
    totals = folder / "totals.json"
    totals.write_text(json.dumps(TOTALS))
    with TestClient(create_app(db_path=db, totals_path=totals, web_dist=folder / "no-web")) as c:
        yield c


MARIA = {
    "given_names": ["Maria", "Luz"], "family_names": ["Santos", "Villanueva"],
    "places": [{"city": "Daly City", "region": "CA", "postcode": "94015", "street": "1482 Windrose Lane Apt 7"},
               {"city": "Los Angeles", "region": "CA", "postcode": "90011"}],
    "employers": ["Kaiser Foundation Hospitals"], "current_country": "PH",
}


def state_id(client, shown: str) -> str:
    """The register's own number behind an id a reply showed. Only the server can make this step."""
    return client.app.state.record_ids.find(shown)[1]


def ref(client, record_id: str, owner: str | None = None) -> str:
    """Our own id for a row of the made-up register, the way a search reply would show it."""
    cur = client.app.state.store.cursor()
    sql, params = "select source, record_id, owner_name from records where record_id = ?", [record_id]
    if owner:
        sql, params = sql + " and owner_name = ?", params + [owner]
    row = cur.execute(sql, params).fetchone()
    cur.close()
    return client.app.state.record_ids.public({"source": row[0], "record_id": row[1], "owner_name": row[2]})


# Every masked word is one letter and the same number of dots, so nothing about its length shows.
MASKED = re.compile(rf"^\S{MASK_DOT}{{{MASK_DOTS}}}( \S{MASK_DOT}{{{MASK_DOTS}}})*$")


def test_mask_keeps_first_letters_and_nothing_about_length():
    dots = MASK_DOT * MASK_DOTS
    assert mask_name("SANTOS MARIA L") == f"S{dots} M{dots} L{dots}"
    assert mask_name("") == ""


def test_totals_have_names_positions_and_one_other_bucket(client):
    t = client.get("/api/totals").json()
    assert t["abroad_amount"] == 9000.0 and t["abroad_properties"] == 12
    assert t["all_properties"] == len(PEOPLE) + len(ORGS) and t["owner_rows"] == len(PEOPLE) + len(ORGS)
    assert t["origin"]["name"] == "California" and -180 <= t["origin"]["lon"] <= 180
    by_code = {c["code"]: c for c in t["countries"]}
    assert by_code["JP"]["name"] == "Japan" and 30 < by_code["JP"]["lat"] < 40 and 130 < by_code["JP"]["lon"] < 145
    assert by_code["PH"]["properties"] == 4 and by_code["PH"]["amount"] == 3000.0     # PH and PHL are one country
    assert by_code["MX"]["name"] == "Mexico"
    assert [c["amount"] for c in t["countries"]] == sorted((c["amount"] for c in t["countries"]), reverse=True)
    # A code with two meanings, a number and an unknown code all land in the one "other" bucket.
    assert "SZ" not in by_code and "ZZ" not in by_code
    assert t["other"]["properties"] == 3 and t["other"]["amount"] == 1100.0
    assert sum(c["amount"] for c in t["countries"]) + t["other"]["amount"] == t["abroad_amount"]
    # The figures are named for what they count: properties, never "records".
    assert "abroad_records" not in t and "all_records" not in t and "records" not in by_code["JP"]


def test_search_returns_masked_owners_and_no_street(client):
    r = client.post("/api/search", json=MARIA)
    assert r.status_code == 200
    body = r.json()
    assert body["confidence_line"] == 0.6 and 1 <= len(body["matches"]) <= 25
    # The State's own property number never leaves the server: each row carries an id of ours instead.
    assert not {m["record_id"] for m in body["matches"]} & {p[0] for p in PEOPLE + ORGS}
    ids = [state_id(client, m["record_id"]) for m in body["matches"]]
    assert {"P1", "P3", "P4"} <= set(ids)
    assert [m["score"] for m in body["matches"]] == sorted((m["score"] for m in body["matches"]), reverse=True)
    for m in body["matches"]:
        assert set(m) == {"record_id", "source", "owner", "owner_is_organisation", "amount", "currency", "holder_name",
                          "property_type", "owner_city", "owner_region", "owner_country", "score", "strength",
                          "above_line",
                          "reasons", "doubts"} | ({"note"} if m["strength"] == "strong" else set())
        assert 0 <= m["score"] <= 1 and isinstance(m["reasons"], list) and isinstance(m["doubts"], list)
        if not m["owner_is_organisation"]:
            assert MASKED.match(m["owner"]), m["owner"]
    first = next(m for m in body["matches"] if state_id(client, m["record_id"]) == "P1")
    assert first["owner"] == mask_name("SANTOS MARIA L") and first["amount"] == 1840.55
    assert first["holder_name"] == "KAISER FOUNDATION HOSPITALS" and first["above_line"]
    above = [m for m in body["matches"] if m["above_line"]]
    assert body["confident_count"] == len(above)
    assert body["confident_amount"] == round(sum(m["amount"] for m in above), 2)


def _every_reply(client):
    """Replies from every address, built to tempt each code path that touches an owner name or a street."""
    histories = [
        MARIA,
        {"family_names": ["Santos"]},
        {"given_names": "Maria", "family_names": "Santos", "places": [{"postcode": "94015"}]},
        {"given_names": ["Rosalind"], "family_names": ["Church"], "places": [{"city": "Daly City"}]},
        {"given_names": ["Van"], "family_names": ["Nguyen"], "places": [{"city": "San Jose"}],
         "employers": ["Acme Payroll Inc"]},
        {"given_names": ["Eleanor"], "family_names": ["Northfield"],
         "places": [{"city": "Fresno", "street": "12 Quillwort Close"}]},
        {"given_names": ["Roberto"], "family_names": ["Santos", "Trucking"], "current_country": "US"},
    ]
    for h in histories:
        yield client.post("/api/search", json=h)
    for q in ["NORTHFIELD", "SANTOS", "CHURCH", "NGUYEN", "MARIA", "VAN", "northfield university", "CO VAN"]:
        yield client.get("/api/organisations", params={"q": q})
    yield client.get("/api/totals")
    yield client.get("/api/countries")


def test_no_private_name_or_street_can_leave_the_api(client):
    replies = list(_every_reply(client))
    assert all(r.status_code == 200 for r in replies), [r.status_code for r in replies]
    seen_people = set()
    for r in replies:
        text = r.text.upper()
        for rid, name, street, *_ in PEOPLE:
            assert name not in text, f"full name of {rid} left the API"
            assert street not in text, f"street of {rid} left the API"
            for word in street.split():
                if len(word) >= 8:                      # the distinctive street words, such as WINDROSE
                    assert word not in text, f"part of the street of {rid} left the API"
        # Words of a private name the searcher never typed must not appear, even inside a reason or a doubt.
        assert "QUIXOTIC" not in text, "a name word from a private record left the API"
        for rid, name, street, *_ in ORGS:
            assert street not in text, f"street of {rid} left the API"
        if r.request.method == "POST":
            asked = set(normalise(r.request.content.decode()).split())
            for m in r.json()["matches"]:
                rid = state_id(client, m["record_id"])
                seen_people.add(rid)
                assert "street" not in " ".join(m.keys())
                if rid.startswith("P"):
                    assert MASKED.match(m["owner"]) and not m["owner_is_organisation"]
                    name = next(p[1] for p in PEOPLE if p[0] == rid)
                    for word in name.split():
                        if len(word) > 1 and word not in asked:
                            assert not re.search(rf"\b{word}\b", text), \
                                f"{rid}: a name word the searcher never gave left the API"
    # The checks above mean something only if private records were in fact found.
    assert {"P1", "P2", "P3", "P4", "P6", "P7", "P8"} <= seen_people


def test_organisation_owner_is_shown_in_full_in_a_search(client):
    body = client.post("/api/search", json={"given_names": [], "family_names": ["Santos Trucking Inc"],
                                            "places": [{"city": "Daly City", "region": "CA", "street": "400 Harbor Way"}],
                                            "employers": ["State Fund"]}).json()
    org = next(m for m in body["matches"] if state_id(client, m["record_id"]) == "O1")
    assert org["owner"] == "SANTOS TRUCKING INC" and org["owner_is_organisation"]
    assert "HARBOR" not in json.dumps(org).upper()          # an organisation's street is not sent either


def test_name_that_only_looks_like_an_organisation_stays_masked():
    assert shown_as_organisation("NORTHFIELD UNIVERSITY") and shown_as_organisation("BANK OF EXAMPLE")
    assert shown_as_organisation("SANTOS TRUCKING INC") and shown_as_organisation("RIVERBEND MEDICAL GROUP")
    assert not shown_as_organisation("CHURCH ROSALIND") and not shown_as_organisation("NGUYEN CO VAN")
    assert not shown_as_organisation("SANTOS MARIA L") and not shown_as_organisation("")


def test_organisations_endpoint_lists_only_organisations_largest_first(client):
    body = client.get("/api/organisations", params={"q": "northfield"}).json()
    assert [r["owner"] for r in body["results"]] == ["NORTHFIELD UNIVERSITY", "NORTHFIELD HARDWARE LLC",
                                                     "NORTHFIELD UNIVERSITY BOOKSTORE"]
    assert body["results"][0]["amount"] == 55690.09 and all(r["owner_is_organisation"] for r in body["results"])
    assert all("street" not in " ".join(r) for r in body["results"])
    assert len(body["results"]) <= 20
    assert client.get("/api/organisations", params={"q": "zzzzqq"}).json()["results"] == []


def test_bad_input_is_refused_plainly(client):
    assert client.get("/api/organisations", params={"q": "ab"}).status_code == 422
    assert client.get("/api/organisations", params={"q": "a' b"}).status_code == 422
    assert client.get("/api/organisations").status_code == 422
    assert client.post("/api/search", json={"given_names": ["Maria"]}).status_code == 422
    assert client.post("/api/search", json={"given_names": ["Maria"], "family_names": [" ", "x"]}).status_code == 422
    assert client.post("/api/search", json={"family_names": [{"a": 1}]}).status_code == 422
    assert client.post("/api/search", json={"family_names": ["Santos"], "places": "Daly City"}).status_code == 422
    assert client.post("/api/search", json={"family_names": ["S" * 500]}).status_code == 422
    assert client.post("/api/search", content=b"not json", headers={"content-type": "application/json"}).status_code == 422
    assert client.get("/api/nothing-here").status_code == 404
    # A quote mark in a name is data, not a command.
    ok = client.post("/api/search", json={"family_names": ["O'Santos'; drop table records; --"]})
    assert ok.status_code == 200
    assert client.get("/api/organisations", params={"q": "northfield"}).json()["results"]


def test_missing_database_gives_a_clear_answer(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "none.duckdb", totals_path=tmp_path / "none.json",
                               web_dist=tmp_path)) as c:
        assert c.post("/api/search", json={"family_names": ["Santos"]}).status_code == 503
        assert c.get("/api/totals").status_code == 503
