"""The strong / possible rule, the strict street rule and the harder ways a name is typed.

Every person, street and holder here is invented. Nothing touches the real register or the network.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import registers
from khutlisa.match import STRENGTH_RULE, History, Place, find, score, street_matches, strength_of
from khutlisa.names import Person, normalise
from khutlisa.server import _safe_lines, create_app

ROOT = Path(__file__).resolve().parents[1]

# (record_id, owner_name, street, city, region, postcode, country, amount, holder)
ROWS = [
    ("A1", "QUENTRELL MARISOL", "4417 TAMARACK HOLLOW RD APT 5", "RIVERTON", "CA", "95999", "US", 812.40,
     "BLUEFERN CREDIT UNION"),
    ("A2", "QUENTRELL MARISOL", "88 OSPREY LANDING WAY", "RIVERTON", "CA", "95999", "US", 64.00, "ACME PAYROLL INC"),
    ("A3", "OKONKWELL MARGARET ANNE", "12 FERNGULLY CT", "RIVERTON", "CA", "95999", "US", 300.00, "ACME PAYROLL INC"),
    ("A4", "DE LA VEYRA ROSENDO T", "9 SALTMARSH AVE", "HARBORVIEW", "CA", "95888", "US", 150.00, "ACME PAYROLL INC"),
    ("A5", "DELAVEYRA IGNACIO", "31 COPPERLEAF DR", "HARBORVIEW", "CA", "95888", "US", 75.00, "ACME PAYROLL INC"),
    ("A6", "DELA VEYRA CONSUELO", "7 LARKSPUR PL", "HARBORVIEW", "CA", "95888", "US", 90.00, "ACME PAYROLL INC"),
    ("A7", "MC TAVISHAM WILLIAM", "640 BRAMBLEWOOD ST", "HARBORVIEW", "CA", "95888", "US", 410.00,
     "ACME PAYROLL INC"),
    ("A8", "PELLIGRAVE JUANA", "5 THISTLEDOWN RD", "RIVERTON", "CA", "95999", "US", 220.00, "BLUEFERN CREDIT UNION"),
    ("A9", "ZORNWALD FRANCISCO JAVIER", "2 MILLRACE LN", "RIVERTON", "CA", "95999", "US", 510.00,
     "ACME PAYROLL INC"),
    ("B1", "HALVERSTROM M", "77 CINDERPATH ROAD", "RIVERTON", "CA", "95999", "US", 45.00, "ACME PAYROLL INC"),
    ("B2", "YSMAELA TEODORO KRISTOFF", "PO BOX 5512", "RIVERTON", "CA", "95999", "US", 130.00, "ACME PAYROLL INC"),
    ("B3", "ROSENDO MARIA DE LA VEYRA", "14 PIPERS GLEN", "HARBORVIEW", "CA", "95888", "US", 33.00,
     "ACME PAYROLL INC"),
]
# The same name and holder at four different addresses in one postcode, and another name at two.
SAME_TIE = [(f"D{i}", "KESTERLING OSWALD", f"{20 + i} {w} ST", "MILLBROOK", "CA", "95777", "US", 10.0 + i,
             "BLUEFERN CREDIT UNION") for i, w in enumerate(["ALDERGATE", "BIRCHMERE", "CEDARHOLT", "DUNSTABLE"])]
SAME_TIE += [(f"E{i}", "MARLOWICK DELPHINE", f"{30 + i} {w} ST", "MILLBROOK", "CA", "95777", "US", 20.0 + i,
              "BLUEFERN CREDIT UNION") for i, w in enumerate(["ELMHURST", "FOXGLOVE"])]
# The sound of a family name shared by 300 richer strangers, to crowd a rare exact name out of a cut-off.
SOUNDALIKE = [(f"F{i}", "WENVICK ALBERTA", f"{i} OAK ST", f"VILLE{i}", "CA", f"8{i:04d}", "US", 5000.0 + i,
               "ACME PAYROLL INC") for i in range(300)]
SOUNDALIKE.append(("G1", "VENWYCK ALBERTA", "1 PINE ST", "LASTTOWN", "CA", "80999", "US", 1.0, "ACME PAYROLL INC"))
# One common invented name at many different addresses, to stand for a crowd of same-name strangers.
CROWD = [(f"C{i}", "BRANLOW TERESA", f"{100 + i} ELM ST", f"TOWN{i}", "CA", f"9{i:04d}", "US", 50.0 + i,
          "ACME PAYROLL INC") for i in range(70)]
PRIVATE_WORDS = ["TAMARACK", "HOLLOW", "4417", "OSPREY", "FERNGULLY", "SALTMARSH", "COPPERLEAF", "LARKSPUR",
                 "BRAMBLEWOOD", "THISTLEDOWN", "MILLRACE", "CINDERPATH", "5512", "PIPERS", "KRISTOFF", "ANNE"]


def make_register(path):
    con = registers.connect(path)
    for rid, name, street, city, region, zip_, country, amount, holder in ROWS + CROWD + SAME_TIE + SOUNDALIKE:
        con.execute("insert into records values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ["TEST", rid, name, street, city, region, zip_, country, country, amount, "USD", holder, "", "",
                     "WAGES", None])
    registers.add_search_column(con)
    return con


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("strength") / "registers.duckdb"
    make_register(path).close()
    return path


@pytest.fixture(scope="module")
def con(db_path):
    c = duckdb.connect(str(db_path), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def client(db_path, tmp_path_factory):
    folder = tmp_path_factory.mktemp("strength-web")
    totals = folder / "totals.json"
    totals.write_text(json.dumps({"source": "invented", "all_records": 1, "all_amount": 1.0, "abroad_records": 0,
                                  "abroad_amount": 0.0, "by_country": []}))
    with TestClient(create_app(db_path=db_path, totals_path=totals, web_dist=folder / "no-web")) as c:
        yield c


def person(given, family, places=(), holders=(), now=""):
    return History(Person(given=list(given), family=list(family)), list(places), list(holders), now)


def by_id(matches):
    return {m.record["record_id"]: m for m in matches}


RIVERTON = Place(city="Riverton", region="CA", postcode="95999")
HARBORVIEW = Place(city="Harborview", region="CA", postcode="95888")


# ---- the strength rule ----

def test_name_and_postcode_alone_is_possible_never_strong(con):
    found = by_id(find(con, person(["Marisol"], ["Quentrell"], [Place(postcode="95999")])))
    assert {"A1", "A2"} <= set(found)
    assert found["A1"].score >= 0.6                      # the points are high, and still it is not strong
    assert all(m.strength == "possible" for m in found.values())


def test_name_and_city_alone_is_possible_never_strong(con):
    found = by_id(find(con, person(["Marisol"], ["Quentrell"], [Place(city="Riverton", region="CA")])))
    assert {"A1", "A2"} <= set(found)
    assert all(m.strength == "possible" for m in found.values())


def test_strength_has_exactly_two_values(con):
    seen = {m.strength for m in find(con, person(["Marisol"], ["Quentrell"], [RIVERTON], ["Bluefern Credit Union"]),
                                     top=500, floor=0.0)}
    assert seen == {"strong", "possible"}


def test_two_given_names_in_full_with_the_postcode_is_strong(con):
    found = by_id(find(con, person(["Margaret", "Anne"], ["Okonkwell"], [Place(postcode="95999")])))
    assert found["A3"].strength == "strong"
    city_only = by_id(find(con, person(["Margaret", "Anne"], ["Okonkwell"], [Place(city="Riverton")])))
    assert city_only["A3"].strength == "possible"
    one_name = by_id(find(con, person(["Margaret"], ["Okonkwell"], [Place(postcode="95999")])))
    assert one_name["A3"].strength == "possible"


def test_a_named_holder_makes_the_name_match_strong(con):
    found = by_id(find(con, person(["Marisol"], ["Quentrell"], [RIVERTON], ["Bluefern Credit Union"])))
    assert found["A1"].strength == "strong" and found["A2"].strength == "possible"
    assert any("BLUEFERN CREDIT UNION" in r for r in found["A1"].reasons)


def test_a_named_holder_alone_or_with_only_a_city_is_not_enough(con):
    h = person(["Marisol"], ["Quentrell"], [], ["Bluefern Credit Union"])
    assert by_id(find(con, h))["A1"].strength == "possible"
    h = person(["Marisol"], ["Quentrell"], [Place(city="Riverton", region="CA")], ["Bluefern Credit Union"])
    assert by_id(find(con, h))["A1"].strength == "possible"
    assert any("BLUEFERN" in r for r in by_id(find(con, h))["A1"].reasons)        # the points still say so


def test_a_named_holder_with_two_given_names_in_full_is_strong(con):
    h = person(["Francisco", "Javier"], ["Zornwald"], [], ["Acme Payroll"])
    assert by_id(find(con, h))["A9"].strength == "strong"
    h = person(["Francisco"], ["Zornwald"], [], ["Acme Payroll"])
    assert by_id(find(con, h))["A9"].strength == "possible"


def test_ties_without_an_address_stop_counting_when_they_point_at_many_addresses(con):
    millbrook = Place(postcode="95777")
    two = find(con, person(["Delphine"], ["Marlowick"], [millbrook], ["Bluefern Credit Union"]))
    assert len(two) == 2 and all(m.strength == "strong" for m in two)               # two addresses: still strong
    four = find(con, person(["Oswald"], ["Kesterling"], [millbrook], ["Bluefern Credit Union"]))
    assert len(four) == 4 and all(m.strength == "possible" for m in four)           # four addresses: none is strong
    assert all(any("4 different addresses" in d for d in m.doubts) for m in four)
    assert all(any("proof file" in d for d in m.doubts) for m in four)
    # A street does not settle which one in the search: the search does not use streets. A claim's proof does.
    one = by_id(find(con, person(["Oswald"], ["Kesterling"], [Place(postcode="95777", street="22 Cedarholt St")],
                                 ["Bluefern Credit Union"])))
    assert len(one) == 4 and all(m.strength == "possible" for m in one.values())


def test_a_rare_exact_name_is_not_crowded_out_by_richer_soundalikes(con):
    from khutlisa.match import candidates
    h = person(["Alberta"], ["Venwyck"])
    assert "G1" in {r["record_id"] for r in candidates(con, h, limit=50)}
    assert find(con, h, top=1)[0].record["record_id"] == "G1"


def test_a_word_every_holder_shares_does_not_name_a_holder(con):
    for vague in (["Union"], ["Credit Union"], ["Inc"], ["Payroll Inc"], ["Bank"]):
        found = by_id(find(con, person(["Marisol"], ["Quentrell"], [RIVERTON], vague)))
        assert found["A1"].strength == "possible" and found["A2"].strength == "possible", vague


def test_an_initial_is_not_a_given_name_for_strong(con):
    h = person(["Mirabel"], ["Halverstrom"], [Place(postcode="95999", street="77 Cinderpath Road")])
    found = by_id(find(con, h, floor=0.0))
    assert found["B1"].strength == "possible"


def test_strength_rule_is_stated_once_and_matches_the_function():
    assert "strong" in STRENGTH_RULE.lower() and "postcode" in STRENGTH_RULE.lower()
    doc = strength_of.__doc__
    for phrase in ("two given names", "holder", "possible", "street"):
        assert phrase in doc, phrase
    assert "house number" not in doc and "house number" not in STRENGTH_RULE


# ---- the street rule: kept for claims and the proof file, never used by the search ----

def street_search(con, street):
    place = Place(city="Riverton", region="CA", postcode="95999", street=street)
    return by_id(find(con, person(["Marisol"], ["Quentrell"], [place])))


def test_house_number_and_street_name_agree_under_the_strict_rule_that_a_claim_uses():
    record = "4417 TAMARACK HOLLOW RD APT 5"
    for typed in ("4417 Tamarack Hollow Rd", "4417 Tamarack Hollow Road, Apt 5", "4417 tamarack hollow"):
        assert street_matches(typed, record), typed
    for typed in ("4417", "Tamarack Hollow Rd", "4418 Tamarack Hollow Rd", "4417 Osprey Landing Way", "Apt 5"):
        assert not street_matches(typed, record), typed


@pytest.mark.parametrize("probe", ["4417 Tamarack Hollow Rd", "4417 Tamarack Hollow Road, Apt 5",
                                   "4417", "Tamarack", "Hollow", "Apt 5", "APT 5 RD", "5", "Rd", "4417 Rd",
                                   "4417 Apt 5", "Tamarack Hollow Rd", "4418 Tamarack Hollow Rd",
                                   "4417 Tamarack Street", "4417 Osprey Landing Way", "88 Tamarack Hollow Rd"])
def test_an_address_right_wrong_or_partial_confirms_nothing_and_changes_nothing(con, probe):
    plain = street_search(con, "")
    probed = street_search(con, probe)
    assert set(probed) == set(plain)
    for rid in plain:
        assert probed[rid].strength == "possible"
        assert probed[rid].reasons == plain[rid].reasons and probed[rid].doubts == plain[rid].doubts
        assert probed[rid].score == plain[rid].score


def test_a_post_box_number_never_confirms(con):
    h = person(["Teodoro"], ["Ysmaela"], [Place(postcode="95999", street="PO Box 5512")])
    assert by_id(find(con, h))["B2"].strength == "possible"


def test_a_street_in_another_town_does_not_confirm(con):
    h = person(["Marisol"], ["Quentrell"], [Place(city="Fresno", postcode="93701", street="4417 Tamarack Hollow Rd")])
    found = by_id(find(con, h, floor=0.0))
    assert found["A1"].strength == "possible" and not any("address they gave" in r for r in found["A1"].reasons)


def test_no_reason_or_doubt_carries_text_from_the_register(con):
    histories = [
        person(["Marisol"], ["Quentrell"], [Place(postcode="95999", street="4417 Tamarack Hollow Rd")]),
        person(["Marisol"], ["Quentrell"], [Place(postcode="95999", street="1 Wrong Street")]),
        person(["Margaret"], ["Okonkwell"], [RIVERTON]),
        person(["Teodoro"], ["Ysmaela"], [RIVERTON]),
        person(["Rosendo"], ["De la Veyra"], [HARBORVIEW]),
    ]
    for h in histories:
        typed = set(normalise(" ".join(pl.street for pl in h.places)).split())
        for m in find(con, h, top=500, floor=0.0):
            text = " ".join(m.reasons + m.doubts).upper()
            for word in PRIVATE_WORDS:
                assert word in typed or word not in text, (word, text)
            street = m.record["owner_street"]
            assert street not in text
            safe = _safe_lines(m.reasons + m.doubts, m.record, set(), False)
            assert all(word in typed or word not in " ".join(safe).upper() for word in PRIVATE_WORDS)


# ---- recall: the harder ways a name is typed ----

@pytest.mark.parametrize("typed", ["Marisal", "Marisl", "Marisoll", "Narisol"])
def test_one_letter_typo_in_the_given_name_is_found_as_a_close_match(con, typed):
    with_place = by_id(find(con, person([typed], ["Quentrell"], [RIVERTON])))
    assert "A1" in with_place and with_place["A1"].strength == "possible"
    assert any("close" in r for r in with_place["A1"].reasons)
    assert "A1" in by_id(find(con, person([typed], ["Quentrell"])))        # and with no place at all


def test_a_near_spelling_is_weaker_than_the_full_name_and_never_strong_on_its_own(con):
    full = score(dict(by_id(find(con, person(["Juana"], ["Pelligrave"], [RIVERTON])))["A8"].record),
                 person(["Juana"], ["Pelligrave"], [RIVERTON]))
    h = person(["Juan"], ["Pelligrave"], [RIVERTON], ["Bluefern Credit Union"])
    near = by_id(find(con, h))["A8"]
    assert near.strength == "possible"                  # JUAN is not JUANA: a holder and a postcode do not settle it
    assert near.score < full.score + 0.15 and not any("given name matches (" in r for r in near.reasons)
    assert full.strength == "possible"


@pytest.mark.parametrize("typed,rid,family,place", [
    ("Bill", "A7", "Mc Tavisham", HARBORVIEW), ("Peggy", "A3", "Okonkwell", RIVERTON),
    ("Paco", "A9", "Zornwald", RIVERTON), ("Chito", "A9", "Zornwald", RIVERTON)])
def test_a_nickname_finds_the_formal_name(con, typed, rid, family, place):
    assert rid in by_id(find(con, person([typed], [family], [place])))
    assert rid in by_id(find(con, person([typed], [family])))


def test_a_formal_name_finds_the_nickname_on_the_record():
    rec = {"owner_name": "ZORNWALD PEPE", "owner_norm": "ZORNWALD PEPE", "owner_city": "RIVERTON",
           "owner_postcode": "95999", "owner_street": "", "holder_name": ""}
    m = score(rec, person(["Jose"], ["Zornwald"], [RIVERTON]))
    assert any("close" in r for r in m.reasons) and m.score >= 0.45


@pytest.mark.parametrize("family", ["De la Veyra", "Dela Veyra", "Delaveyra", "DELA VEYRA", "Veyra"])
def test_a_particle_surname_is_found_joined_split_or_bare(con, family):
    for given, rid in (("Rosendo", "A4"), ("Ignacio", "A5"), ("Consuelo", "A6")):
        found = by_id(find(con, person([given], [family], [HARBORVIEW])))
        assert rid in found, (family, rid)
        found = by_id(find(con, person([given], [family])))
        assert rid in found, (family, rid, "name only")


def test_a_mc_surname_is_found_joined_or_split(con):
    for family in ("McTavisham", "Mc Tavisham", "MCTAVISHAM"):
        assert "A7" in by_id(find(con, person(["William"], [family], [HARBORVIEW]))), family


def test_given_and_family_in_the_wrong_boxes_are_still_found(con):
    assert "A1" in by_id(find(con, person(["Quentrell"], ["Marisol"], [RIVERTON])))
    assert "A3" in by_id(find(con, person(["Okonkwell"], ["Margaret"], [RIVERTON])))      # MARGARET is a middle word
    assert "A9" in by_id(find(con, person(["Zornwald"], ["Javier"])))
    assert "B3" in by_id(find(con, person(["Veyra"], ["Rosendo"], [HARBORVIEW])))


def test_a_different_given_name_is_not_returned(con):
    found = by_id(find(con, person(["Hiroshi"], ["Quentrell"], [RIVERTON])))
    assert "A1" not in found and "A2" not in found


def test_a_common_name_is_still_held_down_by_the_crowd(con):
    found = find(con, person(["Teresa"], ["Branlow"], now="US"), top=500)       # same country: 0.64 before the cap
    assert len(found) == 70 and len({m.record["record_id"] for m in found}) == 70
    assert all(m.score <= 0.55 and m.strength == "possible" for m in found)
    assert all(any("different addresses" in d for d in m.doubts) for m in found)


# ---- the API ----

def test_the_api_counts_strong_matches_by_the_rule_not_by_the_points(client):
    body = client.post("/api/search", json={"given_names": ["Marisol"], "family_names": ["Quentrell"],
                                            "places": [{"postcode": "95999"}]}).json()
    assert len(body["matches"]) == 2 and all(m["score"] >= 0.6 for m in body["matches"])
    assert body["confident_count"] == 0 and body["confident_amount"] == 0
    assert body["strong_count"] == 0 and body["strong_amount"] == 0 and body["possible_count"] == 2
    assert all(m["strength"] == "possible" and m["above_line"] is False for m in body["matches"])
    assert body["strength_rule"] == STRENGTH_RULE

    # The right street is not a tie in the search: the reply is still two possible matches.
    body = client.post("/api/search", json={"given_names": ["Marisol"], "family_names": ["Quentrell"],
                                            "places": [{"postcode": "95999", "street": "4417 Tamarack Hollow Rd"}]}).json()
    assert body["strong_count"] == 0 and body["possible_count"] == 2
    # The holder they named, together with the postcode, is.
    body = client.post("/api/search", json={"given_names": ["Marisol"], "family_names": ["Quentrell"],
                                            "places": [{"postcode": "95999", "street": "4417 Tamarack Hollow Rd"}],
                                            "employers": ["Bluefern Credit Union"]}).json()
    strong = [m for m in body["matches"] if m["strength"] == "strong"]
    assert [m["amount"] for m in strong] == [812.40] and strong[0]["above_line"] is True      # record A1
    assert body["confident_count"] == body["strong_count"] == 1
    assert body["confident_amount"] == body["strong_amount"] == 812.40
    assert not any("address" in r for r in strong[0]["reasons"])
    assert any("holder they named together with the postcode" in r for r in strong[0]["reasons"])
    text = json.dumps(body).upper()
    assert "TAMARACK" not in text and "4417" not in text and "OSPREY" not in text


def test_the_api_address_check_is_not_an_oracle(client):
    def reply(street):
        place = {"postcode": "95999"} | ({"street": street} if street else {})
        body = client.post("/api/search", json={"given_names": ["Marisol"], "family_names": ["Quentrell"],
                                                "places": [place]}).json()
        body.pop("elapsed_ms")
        return body
    plain = reply("")
    for probe in ("4417", "Tamarack", "Apt 5", "4417 Apt 5", "Hollow Rd", "4417 Osprey", "4417 Tamarack Hollow Rd"):
        assert reply(probe) == plain, probe


def test_a_strong_match_is_always_among_the_matches_shown(client):
    # 70 same-name records, one of them tied by its postcode and holder: it must be listed however the others
    # are ordered.
    body = client.post("/api/search", json={"given_names": ["Teresa"], "family_names": ["Branlow"],
                                            "places": [{"postcode": "90069"}], "employers": ["Acme Payroll"]}).json()
    assert body["strong_count"] == 1 and len(body["matches"]) == 25
    assert [m["amount"] for m in body["matches"] if m["strength"] == "strong"] == [119.0]     # record C69
    assert [m["score"] for m in body["matches"]] == sorted((m["score"] for m in body["matches"]), reverse=True)


# ---- the measurement script ----

def test_measurement_script_runs_on_an_invented_register_and_prints_no_name(db_path):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "measure_matcher.py"), "8", "--db", str(db_path),
                          "--any-country", "--min-amount", "0"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    text = out.stdout.upper()
    assert "PEOPLE TESTED" in text and "STRONG" in text and "NOWHERE" not in text
    for rid, name, street, *_ in ROWS:
        for word in name.split() + street.split():
            if len(word) >= 6 and word not in {"ROSENDO", "FRANCISCO", "MARGARET", "WILLIAM", "TEODORO", "IGNACIO",
                                                "CONSUELO", "JAVIER", "MARISOL"}:
                assert not re.search(rf"\b{word}\b", text), word
