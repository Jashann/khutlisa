"""Country codes that the owner cities contradict, and the table of properties away from home that the totals and
the holder figures both read. Everything here runs on a tiny made-up register."""
import duckdb
import pytest

from khutlisa import registers
from khutlisa.countries import CITY_DECIDED, COUNTRIES, RAW_DECIDED, resolve
from khutlisa.registers import COUNTRY_FIX, country_of

SETTLED = frozenset(COUNTRY_FIX.values())


def test_prk_rows_are_south_korea_because_their_cities_are():
    assert resolve("PRK", SETTLED) == "KR" and country_of("PRK") == "KR"


@pytest.mark.parametrize("raw", ["939", "277", "950", "934", "387", "SLI"])
def test_a_californian_postcode_or_county_written_as_a_country_is_home(raw):
    assert resolve(raw, SETTLED) == "US" and country_of(raw) == "US"


@pytest.mark.parametrize("raw, iso", [("TAI", "TW"), ("JAP", "JP"), ("KUW", "KW"), ("SPA", "ES"), ("UAE", "AE"),
                                      ("CDN", "CA"), ("GIN", "PG"), ("COG", "CD")])
def test_a_code_is_placed_where_its_cities_are(raw, iso):
    assert resolve(raw, SETTLED) == iso and country_of(raw) == iso


@pytest.mark.parametrize("raw", ["YUG", "SKV", "SWZ", "GMB", "GEO", "BIH", "SRB", "RWA", "ATG", "TCD", "MDG", "MLI",
                                 "CAF", "NER", "STP", "FRO", "COM", "DJI", "SPM"])
def test_a_code_whose_cities_lie_in_several_countries_cannot_be_placed(raw):
    assert resolve(raw, SETTLED) is None
    assert country_of(raw) == raw                 # the loader keeps the raw code, so nothing is lost


def test_codes_that_were_right_are_left_alone():
    assert resolve("KOR", SETTLED) == "KR" and resolve("BMU", SETTLED) == "BM" and resolve("MEX", SETTLED) == "MX"
    assert resolve("CHE", SETTLED) == "CH" and resolve("XXX", SETTLED) is None


def test_every_decided_code_and_city_points_at_a_known_country():
    assert {iso for iso in RAW_DECIDED.values() if iso} <= set(COUNTRIES)
    for code, city, postcode, iso in CITY_DECIDED:
        assert code in COUNTRIES and iso in COUNTRIES and code != iso and city == city.upper()


# (record_id, owner_country as stored, owner_city, owner_postcode, amount)
ROWS = [
    ("P1", "PRK", "INCHEON", "", 10.0),                      # coded North Korea, the city is South Korean
    ("P2", "939", "SALINAS", "93901", 20.0),                 # a Californian postcode written as a country
    ("P3", "YUG", "BEOGRAD", "", 30.0),                      # no single country today
    ("P4", "CA", "TIJUANA BC", "", 40.0),                    # Baja California read as British Columbia
    ("P5", "CA", "ONTARIO", "91761", 50.0),                  # Ontario in California
    ("P6", "CA", "ONTARIO", "", 60.0),                       # no postcode: stays in Canada
    ("P7", "CA", "Toronto", "M5V 2T6", 70.0),
    ("P8", "PR", "AGOURA HILLS", "91301", 80.0),             # coded Puerto Rico, the city is in California
    ("P9", "PR", "SAN JUAN", "00901", 90.0),
    ("P10", "BMU", "BERMUDA DUNES", "92203", 100.0),         # coded Bermuda, the city is in California
    ("P11", "BMU", "HAMILTON", "", 110.0),
    ("P12", "DE", "SAN GERMAN", "", 120.0),                  # coded Germany, the city is in Puerto Rico
    ("P13", "IE", "BELFAST", "BT9", 130.0),                  # coded Ireland, the city is in the United Kingdom
    ("P14", "US", "FRESNO", "93701", 140.0),
    ("P15", "", "", "", 150.0),
    ("P16", "CA", "TIJUANA BC", "", 160.0), ("P16", "MX", "TIJUANA", "", 160.0),    # two owners, one country
]


def city_register():
    con = duckdb.connect(":memory:")
    con.execute("create table records (source varchar, record_id varchar, owner_country varchar, owner_city varchar,"
                " owner_postcode varchar, amount double)")
    con.executemany("insert into records values ('US-CA', ?, ?, ?, ?, ?)", ROWS)
    return con


def test_build_away_leaves_one_row_for_each_property_and_line():
    con = city_register()
    registers.build_away(con)
    columns = [c[0] for c in con.execute("describe totals_away").fetchall()]
    assert columns == ["source", "record_id", "kind", "shown", "amount"]
    rows = {(rid, kind, shown): amount for _, rid, kind, shown, amount in
            con.execute("select * from totals_away").fetchall()}
    assert rows == {
        ("P1", "abroad", "KR"): 10.0, ("P3", "abroad", "other"): 30.0, ("P4", "abroad", "MX"): 40.0,
        ("P6", "abroad", "CA"): 60.0, ("P7", "abroad", "CA"): 70.0, ("P9", "territory", "PR"): 90.0,
        ("P11", "abroad", "BM"): 110.0, ("P12", "territory", "PR"): 120.0, ("P13", "abroad", "GB"): 130.0,
        ("P15", "blank", ""): 150.0, ("P16", "abroad", "MX"): 160.0,
    }
    con.close()


def test_the_totals_use_the_same_table_and_drop_it():
    con = city_register()
    made = registers.totals(con)
    by_code = {c["code"]: c for c in made["by_country"]}
    assert "KP" not in by_code and by_code["KR"] == {"code": "KR", "properties": 1, "amount": 10.0}
    assert by_code["MX"] == {"code": "MX", "properties": 2, "amount": 200.0}
    assert by_code["CA"]["properties"] == 2 and by_code["GB"]["properties"] == 1 and by_code["BM"]["amount"] == 110.0
    assert made["abroad_properties"] == 8 and made["abroad_amount"] == 610.0
    assert made["multi_country_properties"] == 0
    assert made["other"] == {"properties": 1, "amount": 30.0, "codes": 1}
    assert made["us_territories"]["properties"] == 2 and made["us_territories"]["amount"] == 210.0
    assert made["no_country_properties"] == 1
    assert con.execute("select count(*) from duckdb_tables() where table_name like 'totals_%'").fetchone()[0] == 0
    con.close()


def test_build_away_works_on_a_register_with_no_city_column():
    con = duckdb.connect(":memory:")
    con.execute("create table records (source varchar, record_id varchar, owner_country varchar, amount double)")
    con.execute("insert into records values ('US-CA', 'A', 'PRK', 5.0), ('US-CA', 'B', 'US', 6.0)")
    registers.build_away(con)
    assert con.execute("select kind, shown, amount from totals_away").fetchall() == [("abroad", "KR", 5.0)]
    con.close()
