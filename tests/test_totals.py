"""Totals count each property once however many owners it has. Everything here runs on a tiny made-up register."""
import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import registers
from khutlisa.countries import COUNTRIES, US_TERRITORIES, resolve
from khutlisa.registers import COUNTRY_FIX, country_of


def test_two_letter_codes_settled_by_their_cities():
    assert country_of("CH") == "CN" and country_of("CHE") == "CH"      # CH in the file is China, CHE is Switzerland
    assert country_of("SZ") == "CH" and country_of("AS") == "AU" and country_of("IS") == "IL"
    assert country_of("RP") == "PH" and country_of("VI") == "VG" and country_of("MP") == "MU"
    assert country_of("CA") == "CA" and country_of("") == ""


def test_codes_whose_cities_disagree_stay_uncertain():
    for raw in ("AU", "BD", "ES", "ZA", "NT", "ZZ"):
        assert country_of(raw) == f"?{raw}"
        assert resolve(country_of(raw), frozenset(COUNTRY_FIX.values())) is None


def test_us_territories_are_named_apart_and_us_spellings_are_home():
    assert country_of("PRI") == "PR" and country_of("GUM") == "GU" and country_of("VIR") == "VI"
    assert country_of("ASM") == "AS" and country_of("MNP") == "MP" and country_of("GQ") == "GU"
    assert {"PR", "GU", "VI", "AS", "MP", "UM"} == set(US_TERRITORIES)
    assert country_of("U.S") == "US" and country_of("USA") == "US"


def test_every_settled_code_has_a_name_and_a_map_position():
    assert set(COUNTRY_FIX.values()) <= set(COUNTRIES)


# (source, record_id, owner_country, amount): one row per owner, the full balance repeated on every owner row.
OWNER_ROWS = [
    ("US-CA", "A1", "US", 100.0),
    ("US-CA", "A2", "US", 1000.0), ("US-CA", "A2", "MX", 1000.0),          # joint: one owner at home, one abroad
    ("US-CA", "A3", "JP", 500.0), ("US-CA", "A3", "MX", 500.0),            # joint: owners in two foreign countries
    ("US-CA", "A4", "PH", 200.0), ("US-CA", "A4", "PHL", 200.0),           # two spellings of one country
    ("US-CA", "A5", "PR", 50.0), ("US-CA", "A5", "US", 50.0),              # a United States territory
    ("US-CA", "A6", "", 30.0),                                             # no country code at all
    ("US-CA", "A7", "?AU", 70.0), ("US-CA", "A7", "YUG", 70.0),            # two codes that cannot be placed
    ("OTHER", "A2", "MX", 5.0),                                            # the same id in another register
    ("US-CA", "A9", "JP", 300.0), ("US-CA", "A9", "JP", 300.0), ("US-CA", "A9", "JP", 300.0),
]


def tiny_register(path=":memory:"):
    con = duckdb.connect(str(path))
    con.execute("create table records (source varchar, record_id varchar, owner_country varchar, amount double)")
    con.executemany("insert into records values (?, ?, ?, ?)", OWNER_ROWS)
    return con


@pytest.fixture()
def figures():
    con = tiny_register()
    yield registers.totals(con)
    con.close()


def test_a_joint_property_is_counted_once(figures):
    assert figures["owner_rows"] == 16
    assert figures["all_properties"] == 9 and figures["all_amount"] == 2255.0
    # Summing owner rows would give 11 records worth 3,490 here.
    assert figures["abroad_properties"] == 6 and figures["abroad_amount"] == 2075.0


def test_each_country_counts_a_property_once_and_the_overlap_is_stated(figures):
    by_code = {c["code"]: c for c in figures["by_country"]}
    assert by_code["MX"] == {"code": "MX", "properties": 3, "amount": 1505.0}
    assert by_code["JP"] == {"code": "JP", "properties": 2, "amount": 800.0}
    assert by_code["PH"] == {"code": "PH", "properties": 1, "amount": 200.0}       # PH and PHL are one line
    assert set(by_code) == {"MX", "JP", "PH"}
    assert [c["amount"] for c in figures["by_country"]] == [1505.0, 800.0, 200.0]
    assert figures["other"] == {"properties": 1, "amount": 70.0, "codes": 2}
    # A3 is listed under Japan and under Mexico, and once in the headline.
    assert figures["multi_country_properties"] == 1 and figures["multi_country_amount"] == 500.0
    lines = sum(c["amount"] for c in figures["by_country"]) + figures["other"]["amount"]
    assert lines == figures["listed_amount"] == 2575.0
    assert lines - figures["multi_country_extra_amount"] == figures["abroad_amount"]
    assert "counted once" in figures["rule"] and "listed under each" in figures["rule"]


def test_territories_and_blank_codes_are_not_abroad(figures):
    assert figures["us_territories"] == {"properties": 1, "amount": 50.0,
                                         "by_territory": [{"code": "PR", "properties": 1, "amount": 50.0}]}
    assert figures["no_country_properties"] == 1 and figures["no_country_amount"] == 30.0
    assert all(c["code"] not in US_TERRITORIES and c["code"] != "US" for c in figures["by_country"])


def test_the_printed_summary_states_the_rule(figures):
    text = registers.describe_totals(figures)
    assert "9 properties worth $2,255" in text and "16 owner records" in text
    assert "6 properties worth $2,075" in text and figures["rule"] in text
    assert "1 property worth $500" in text or "1 properties worth $500" in text


def test_the_totals_can_be_made_on_a_read_only_database(tmp_path):
    tiny_register(tmp_path / "r.duckdb").close()
    con = duckdb.connect(str(tmp_path / "r.duckdb"), read_only=True)
    assert registers.totals(con)["abroad_properties"] == 6
    assert registers.totals(con)["abroad_properties"] == 6          # and twice on one connection
    con.close()


# ---- the API ---------------------------------------------------------------------------------------------------

def searchable_register(path, source="TEST"):
    from khutlisa.names import normalise, phonetic
    con = duckdb.connect(str(path))
    con.execute("""create table records (source varchar, record_id varchar, owner_name varchar, owner_norm varchar,
        owner_street varchar, owner_city varchar, owner_region varchar, owner_postcode varchar, owner_country varchar,
        amount double, currency varchar, holder_name varchar, holder_city varchar, holder_region varchar,
        property_type varchar, phon_first varchar, phon_last varchar)""")
    for rid, name, country in (("J1", "QUILLFEATHER ODALYS", "US"), ("J1", "QUILLFEATHER BRISEIDA", "MX")):
        norm = normalise(name)
        con.execute("insert into records values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [source, rid, name, norm, "9 TESSELWOOD ROW", "FRESNO", "CA", "93701", country, 640.0, "USD",
                     "ACME PAYROLL INC", "", "", "WAGES", phonetic(norm.split()[0]), phonetic(norm.split()[-1])])
    con.close()
    return path


def test_the_api_gives_properties_by_country_with_the_rule(tmp_path):
    from khutlisa.server import build_totals, create_app
    db = searchable_register(tmp_path / "registers.duckdb")
    con = duckdb.connect(str(db), read_only=True)
    made = registers.totals(con)
    con.close()
    shown = build_totals(made)
    assert shown["abroad_properties"] == 1 and shown["abroad_amount"] == 640.0 and shown["owner_rows"] == 2
    assert shown["countries"][0]["name"] == "Mexico" and shown["countries"][0]["properties"] == 1
    assert shown["other"]["properties"] == 0 and shown["rule"] == made["rule"]
    assert "records" not in shown["countries"][0] and "abroad_records" not in shown
    (tmp_path / "t.json").write_text(json.dumps(made))
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "t.json", web_dist=tmp_path / "no-web")) as c:
        body = c.get("/api/totals").json()
        assert body["abroad_properties"] == 1 and body["multi_country_properties"] == 0 and not body.get("sample")
        # One property with two owners: the search runs over two owner records.
        assert c.get("/api/register").json() == {"owner_records": 2, "records": 2, "sample": False}


def test_without_a_totals_file_the_opening_gets_the_labelled_sample_totals_beside_the_database(tmp_path):
    from khutlisa.server import create_app
    folder = tmp_path / "samples"
    folder.mkdir()
    db = searchable_register(folder / "registers.duckdb", source="SAMPLE")
    con = duckdb.connect(str(db), read_only=True)
    sample = {**registers.totals(con), "source": "Sample register of invented records", "sample": True}
    con.close()
    (folder / "totals.json").write_text(json.dumps(sample))
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "missing.json", web_dist=tmp_path / "no-web")) as c:
        r = c.get("/api/totals")
        assert r.status_code == 200
        assert r.json()["sample"] is True and r.json()["source"].startswith("Sample register")
        assert r.json()["all_properties"] == 1
    # A totals file that exists always wins over the one beside the database.
    (tmp_path / "real.json").write_text(json.dumps({**sample, "sample": False, "source": "Made-up real totals"}))
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "real.json", web_dist=tmp_path / "no-web")) as c:
        assert c.get("/api/totals").json()["source"] == "Made-up real totals"
    # With neither file the answer is still a plain 503.
    (folder / "totals.json").unlink()
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "missing.json", web_dist=tmp_path / "no-web")) as c:
        assert c.get("/api/totals").status_code == 503


def test_a_three_letter_code_is_shown_under_its_country_and_the_lines_still_add_up():
    """BMU is Bermuda with no doubt, although the two letters BM mean something else in the older code list."""
    from khutlisa.server import build_totals
    con = tiny_register()
    con.execute("insert into records values ('US-CA', 'B1', 'BMU', 40.0), ('US-CA', 'B1', '?BD', 40.0)")
    made = registers.totals(con)
    con.close()
    shown = build_totals(made)
    by_code = {c["code"]: c for c in shown["countries"]}
    assert by_code["BM"]["name"] == "Bermuda" and by_code["BM"]["properties"] == 1
    assert shown["other"]["properties"] == made["other"]["properties"] == 2 and shown["other"]["codes"] == 3
    assert round(sum(c["amount"] for c in shown["countries"]) + shown["other"]["amount"], 2) == made["listed_amount"]
    assert sum(c["properties"] for c in shown["countries"]) + shown["other"]["properties"] >= made["abroad_properties"]
