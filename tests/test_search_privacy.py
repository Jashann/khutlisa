"""What the search may tell an anonymous caller, and the rule that calls a match strong.

The search never looks at a street. A street the person gave is compared only inside a claim, once photo
identification in the name on the record has been read. Searches are counted per client address. A masked name
shows first letters and nothing about length. A holder that reports a very large share of the register does not
tie a very common name to a record. Every person, street and holder here is invented.
"""
import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import match, proof, registers
from khutlisa.match import (COMMON_NAME_PLACES, STRENGTH_RULE, STRONG_NOTE, History, Place, compare_streets, find,
                            holder_key, strength_of)
from khutlisa.names import Person
from khutlisa.ratelimit import SlidingWindow
from khutlisa.server import MASK_DOT, MASK_DOTS, create_app, mask_name
from test_claims import AS_PAYER, CLAIMANT, PAYER_KEY, make_register as claims_register
from test_proof import PNG, SEEN, fake_model
from test_server import MARIA, ref

# (record_id, owner_name, street, city, region, postcode, country, amount, holder)
ROWS = [
    ("R1", "ULVERSTANE PERPETUA", "2906 GANNETMOOR CRESCENT", "ELDERWICK", "CA", "95111", "US", 640.00,
     "HARROWGATE CANNERY INC"),
    ("R2", "ULVERSTANE PERPETUA", "51 SNOWBERRY CLOSE", "ELDERWICK", "CA", "95111", "US", 80.00,
     "TIDEWELL WATER DISTRICT"),
    ("R3", "ULVERSTANE WILHELMINA", "7 PLOVERSFIELD ROW", "ELDERWICK", "CA", "95111", "US", 55.00,
     "HARROWGATE CANNERY INC"),
    ("R4", "ULVERSTANE PERPETUA", "18 KITTIWAKE STEPS", "ELDERWICK", "CA", "95111", "US", 410.00,
     "COLOSSUS MERIDIAN BANK NA (BRANCH 0042)"),
]
# One invented name at many places, so that it counts as very common. One of them banks with the very large holder
# in the postcode that will be searched, and one was paid by a small holder there.
PLACES = COMMON_NAME_PLACES + 8
CROWD = [(f"K{i}", "DRAYCOTT LEOPOLD", f"{300 + i} FENWILLOW RD", f"HAMLET{i}", "CA", f"7{i:04d}", "US", 40.0 + i,
          "ORDINARY PAYROLL INC") for i in range(PLACES)]
CROWD += [("K900", "DRAYCOTT LEOPOLD", "12 MALLOWDEN WAY", "HAMLET0", "CA", "70000", "US", 900.0,
           "COLOSSUS MERIDIAN BANK NA"),
          ("K901", "DRAYCOTT LEOPOLD", "12 MALLOWDEN WAY", "HAMLET0", "CA", "70000", "US", 35.0,
           "SALTBUSH NURSERY LLC")]
STREET_WORDS = ["GANNETMOOR", "2906", "SNOWBERRY", "PLOVERSFIELD", "KITTIWAKE", "MALLOWDEN", "FENWILLOW"]


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("privacy") / "registers.duckdb"
    con = registers.connect(path)
    for rid, name, street, city, region, zip_, country, amount, holder in ROWS + CROWD:
        con.execute("insert into records values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ["TEST", rid, name, street, city, region, zip_, country, country, amount, "USD", holder, "", "",
                     "WAGES", None])
    registers.add_search_column(con)
    con.close()
    return path


@pytest.fixture(scope="module")
def con(db_path):
    c = duckdb.connect(str(db_path), read_only=True)
    yield c
    c.close()


@pytest.fixture
def generic(monkeypatch):
    """The invented bank stands for a holder that reports a very large share of the register."""
    monkeypatch.setattr(match, "GENERIC_HOLDER_KEYS", frozenset({"COLOSSUS MERIDIAN"}))


def app_for(db_path, folder, **kw):
    return create_app(db_path=db_path, totals_path=folder / "totals.json", web_dist=folder / "no-web", **kw)


@pytest.fixture
def client(db_path, tmp_path):
    with TestClient(app_for(db_path, tmp_path)) as c:
        yield c


def person(given, family, places=(), holders=(), now=""):
    return History(Person(given=list(given), family=list(family)), list(places), list(holders), now)


def by_id(matches):
    return {m.record["record_id"]: m for m in matches}


PERPETUA = {"given_names": ["Perpetua"], "family_names": ["Ulverstane"], "employers": ["Harrowgate Cannery"]}
RIGHT, WRONG = "2906 Gannetmoor Crescent", "14 Nowhere Lane"


# ---- 1. a street is never used in the search ----------------------------------------------------------------

def reply(client, places, **more):
    r = client.post("/api/search", json={**PERPETUA, "places": places, **more})
    assert r.status_code == 200, r.text
    body = r.json()
    body.pop("elapsed_ms")
    return body


@pytest.mark.parametrize("place", [{"postcode": "95111"}, {"city": "Elderwick", "region": "CA"}, {}])
def test_the_search_reply_is_the_same_whatever_street_is_sent(client, place):
    plain = reply(client, [place] if place else [])
    assert plain["matches"], "the comparison means something only when records are found"
    for street in (RIGHT, RIGHT + " Apt 2", WRONG, "2906", "Gannetmoor", "51 Snowberry Close"):
        assert reply(client, [{**place, "street": street}]) == plain, street
        if place:     # and as a place of its own, with nothing but the street in it
            assert reply(client, [place, {"street": street}]) == plain, street
    text = json.dumps(plain).upper()
    assert "ADDRESS THEY GAVE" not in text and not any(word in text for word in STREET_WORDS)


def test_the_right_street_lifts_nothing_and_orders_nothing(con):
    for places in ([Place(postcode="95111")], [Place(city="Elderwick")], []):
        plain = find(con, person(["Perpetua"], ["Ulverstane"], places), top=500, floor=0.0)
        for street in (RIGHT, WRONG):
            given = [Place(city=p.city, postcode=p.postcode, street=street) for p in places] or [Place(street=street)]
            probed = find(con, person(["Perpetua"], ["Ulverstane"], given), top=500, floor=0.0)
            assert [(m.record["record_id"], m.score, m.strength, m.reasons, m.doubts) for m in probed] == \
                   [(m.record["record_id"], m.score, m.strength, m.reasons, m.doubts) for m in plain]
            assert all("street" not in m.evidence for m in probed)
        assert all(m.strength == "possible" for m in plain)


def test_the_rule_as_stated_has_no_address_tie():
    rule = STRENGTH_RULE.lower()
    assert "house number" not in rule and "an address you gave" not in rule
    assert "never" in rule and "street" in rule            # it says in words that the search does not use one
    assert "house number" not in strength_of.__doc__
    assert strength_of({"family": True, "given_full": 1, "street": True}) == "possible"
    assert strength_of({"family": True, "given_full": 1, "street": True, "postcode": True}) == "possible"


@pytest.mark.parametrize("typed", ["Perpetue", "Perpetu", "Perpetuaa"])
def test_a_near_spelling_of_the_given_name_is_never_strong_in_the_search(con, typed):
    h = person([typed], ["Ulverstane"], [Place(postcode="95111", street=RIGHT)], ["Harrowgate Cannery"])
    found = by_id(find(con, h))
    assert found["R1"].strength == "possible" and any("close" in r for r in found["R1"].reasons)
    assert strength_of({"family": True, "given_close": True, "holder": True, "postcode": True}) == "possible"


def test_a_strong_match_names_the_tie_that_made_it_strong(con):
    before = by_id(find(con, person(["Perpetua"], ["Ulverstane"], [Place(city="Elderwick")], ["Harrowgate Cannery"])))
    after = by_id(find(con, person(["Perpetua"], ["Ulverstane"], [Place(city="Elderwick", postcode="95111")],
                                   ["Harrowgate Cannery"])))
    assert before["R1"].strength == "possible" and after["R1"].strength == "strong"
    gained = [r for r in after["R1"].reasons if r not in before["R1"].reasons]
    assert any("holder they named" in r and "postcode" in r for r in gained), gained
    assert after["R2"].strength == "possible" and not any("holder they named" in r for r in after["R2"].reasons)


# ---- 1b. the street is compared inside a claim, after photo identification ----------------------------------

def test_compare_streets_keeps_a_street_in_the_town_it_was_given_for():
    record = {"owner_street": "2906 GANNETMOOR CRESCENT", "owner_city": "ELDERWICK", "owner_region": "CA",
              "owner_postcode": "95111"}
    assert compare_streets([], record) == "not_given"
    assert compare_streets([{"city": "Elderwick", "street": ""}], record) == "not_given"
    assert compare_streets([{"postcode": "95111", "street": RIGHT}], record) == "matches"
    assert compare_streets([{"street": RIGHT}], record) == "matches"
    assert compare_streets([{"postcode": "95111", "street": WRONG}], record) == "does_not_match"
    assert compare_streets([{"city": "Otherton", "postcode": "90001", "street": RIGHT}], record) == "does_not_match"
    assert compare_streets([{"street": "2906"}], record) == "does_not_match"
    assert compare_streets([{"street": RIGHT}], {**record, "owner_street": ""}) == "no_street_on_record"


@pytest.fixture
def claims(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    db = claims_register(tmp_path)
    app = create_app(db_path=db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no-web",
                     read_documents=True, payer_key=PAYER_KEY)
    with TestClient(app, headers=AS_PAYER) as c:
        yield c


def with_street(street):
    places = [dict(MARIA["places"][0]), dict(MARIA["places"][1])]
    places[0]["street"] = street
    return {**MARIA, "places": places}


def open_claim(api, history, claimant=CLAIMANT):
    r = api.post("/api/claims", json={"record_id": ref(api, "P1"), "claimant": claimant, "history": history})
    assert r.status_code == 201, r.text
    return r.json()


def add(api, claim_id, kind, word):
    r = api.post(f"/api/claims/{claim_id}/documents", data={"kind": kind},
                 files={"file": (f"{word}.png", PNG + word.encode())})
    assert r.status_code == 201, r.text
    api.app.state.reading.join()
    return api.get(f"/api/claims/{claim_id}").json()


def lines(claim):
    return " ".join(claim["match"]["reasons"] + claim["match"]["doubts"])


@pytest.mark.parametrize("street,status,said", [
    ("1482 Windrose Lane Apt 7", "matches", "matches the street on the record"),
    ("77 Larkhill Row", "does_not_match", "does not match the street on the record")])
def test_a_claim_compares_the_street_only_after_photo_identification_has_been_read(claims, street, status, said):
    claim = open_claim(claims, with_street(street))
    waiting = claim["address_check"]
    assert waiting["status"] == "waiting" and "once photo identification" in waiting["text"]
    assert "street" not in lines(claim) and "address they gave" not in lines(claim)
    assert claim["address_given"][0]["street"] == street           # their own typed words, kept with the claim
    # A payslip that shows the name and even the street is not photo identification: still nothing is said.
    claim = add(claims, claim["id"], "payslip", "payslip")
    assert claim["address_check"] == waiting and "street" not in lines(claim)
    claim = add(claims, claim["id"], "id", "passport")
    check = claim["address_check"]
    assert check["status"] == status and said in check["text"]
    assert said in lines(claim)
    assert (said in " ".join(claim["match"]["reasons"])) is (status == "matches")
    if status == "does_not_match":       # nothing from the record's street comes back, whatever the answer
        said_back = json.dumps([claim["address_check"], claim["match"], claim["proof"]["record_link"]]).upper()
        assert "WINDROSE" not in said_back and "1482" not in said_back


def test_the_holder_sees_the_same_street_result_as_the_claimant_and_never_the_street(claims):
    claim = open_claim(claims, with_street("1482 Windrose Lane Apt 7"))
    claim = add(claims, claim["id"], "id", "passport")
    row = next(r for r in claims.get("/api/payer/queue").json()["claims"] if r["id"] == claim["id"])
    assert "matches the street on the record" in " ".join(row["reasons"])
    assert row["match"]["reasons"] == claim["match"]["reasons"]
    assert "WINDROSE" not in json.dumps(row).upper()


def test_identification_in_another_name_does_not_open_the_street_comparison(claims):
    eve = {**CLAIMANT, "name": "Eve Mallory"}
    SEEN["evesown"] = {"presents_as_government_photo_id": True, "photo_present": True, "names": ["Eve Mallory"],
                       "document_type": "passport photo page", "issuer": "Republic of Examplia",
                       "dates": [{"label": "date of expiry", "value": "2031-01-01"}]}
    for street in ("1482 Windrose Lane Apt 7", "77 Larkhill Row"):
        claim = open_claim(claims, with_street(street), claimant=eve)
        claim = add(claims, claim["id"], "id", "evesown")
        assert claim["proof"]["record_link"]["status"] == "not shown"
        assert claim["address_check"]["status"] == "waiting" and "street" not in lines(claim)
    # an expired passport in the right name does not count as identification either
    claim = add(claims, open_claim(claims, with_street("1482 Windrose Lane Apt 7"))["id"], "id", "oldpassport")
    assert claim["address_check"]["status"] == "waiting"


def test_a_claim_with_no_street_given_says_so_and_compares_nothing(claims):
    history = {**MARIA, "places": [{"city": "Daly City", "region": "CA", "postcode": "94015"}]}
    claim = add(claims, open_claim(claims, history)["id"], "id", "passport")
    assert claim["address_check"]["status"] == "not_given" and claim["address_given"] == []
    assert "street" not in lines(claim)


# ---- 2. searches are counted per client address -------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_sliding_window_allows_then_refuses_then_lets_go():
    clock = Clock()
    window = SlidingWindow([(3, 60), (5, 3600)], clock=clock)
    assert [window.take("a") for _ in range(3)] == [0, 0, 0]
    assert window.take("a") == 60 and window.take("b") == 0          # each client has its own count
    clock.now += 59
    assert window.take("a") == 1
    clock.now += 1
    assert window.take("a") == 0 and window.take("a") == 0           # five in the hour now
    clock.now += 120
    wait = window.take("a")
    assert 3300 < wait <= 3600                                       # the hour's count holds after the minute's clears
    clock.now += wait
    assert window.take("a") == 0
    assert len(window.seen) <= 2
    clock.now += 4000
    window.take("c")
    assert set(window.seen) == {"c"}                                 # clients that went quiet are forgotten


def limited(db_path, folder, clock, **kw):
    return app_for(db_path, folder, search_per_minute=3, search_per_hour=6, clock=clock, **kw)


def test_the_search_answers_429_with_a_sentence_and_retry_after(db_path, tmp_path):
    clock = Clock()
    app = limited(db_path, tmp_path, clock)
    body = {"family_names": ["Ulverstane"]}
    with TestClient(app) as c:
        assert [c.post("/api/search", json=body).status_code for _ in range(3)] == [200, 200, 200]
        refused = c.post("/api/search", json=body)
        assert refused.status_code == 429 and refused.headers["Retry-After"] == "60"
        detail = refused.json()["detail"]
        assert isinstance(detail, str) and "searches" in detail and "minute" in detail and detail.endswith(".")
        # a header the caller writes is not trusted to say who they are
        assert c.post("/api/search", json=body, headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429
        assert c.post("/api/search", json={"family_names": []}).status_code == 429     # refused before it is read
        # other routes are not counted
        assert c.get("/api/countries").status_code == 200 and c.get("/api/register").status_code == 200
        clock.now += 61
        assert c.post("/api/search", json=body).status_code == 200
    with TestClient(app, client=("198.51.100.7", 40000)) as other:      # another address has its own count
        assert other.post("/api/search", json=body).status_code == 200


def test_a_forwarding_header_cannot_be_used_to_look_like_many_clients(db_path, tmp_path):
    """The server program may itself rewrite the client address from X-Forwarded-For when the connection comes
    from the same machine. A caller who sends a new address in that header with every request must still be
    stopped, so every request that carries a forwarding header also counts on one shared count."""
    app = limited(db_path, tmp_path, Clock())
    codes = []
    for i in range(5):
        fake = f"203.0.113.{i}"
        with TestClient(app, client=(fake, 40000)) as c:       # what the app sees once the header is believed
            codes.append(c.post("/api/search", json={"family_names": ["Ulverstane"]},
                                headers={"X-Forwarded-For": fake}).status_code)
    assert codes == [200, 200, 200, 429, 429]
    with TestClient(app, client=("198.51.100.20", 40000)) as plain:    # a caller with no such header is not held up
        assert plain.post("/api/search", json={"family_names": ["Ulverstane"]}).status_code == 200


def test_the_hourly_count_holds_after_the_minute_clears(db_path, tmp_path):
    clock = Clock()
    with TestClient(limited(db_path, tmp_path, clock)) as c:
        codes = []
        for _ in range(7):
            codes.append(c.post("/api/search", json={"family_names": ["Ulverstane"]}).status_code)
            clock.now += 30
        assert codes == [200] * 6 + [429]
        refused = c.post("/api/search", json={"family_names": ["Ulverstane"]})
        assert refused.status_code == 429 and "hour" in refused.json()["detail"]
        assert 3000 < int(refused.headers["Retry-After"]) <= 3600


def test_the_organisation_search_is_counted_too(db_path, tmp_path):
    clock = Clock()
    with TestClient(limited(db_path, tmp_path, clock)) as c:
        codes = [c.get("/api/organisations", params={"q": "harrowgate"}).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        assert c.get("/api/organisations/notable").status_code != 429          # the prepared set is not a search
        assert c.post("/api/search", json={"family_names": ["Ulverstane"]}).status_code == 200   # its own count


def test_the_limits_come_from_the_environment_and_the_defaults_leave_the_screens_working(db_path, tmp_path, monkeypatch):
    with TestClient(app_for(db_path, tmp_path, clock=Clock())) as c:
        codes = [c.post("/api/search", json={"family_names": ["Ulverstane"]}).status_code for _ in range(31)]
        assert codes == [200] * 30 + [429]
    monkeypatch.setenv("KHUTLISA_SEARCHES_PER_MINUTE", "2")
    monkeypatch.setenv("KHUTLISA_SEARCHES_PER_HOUR", "50")
    with TestClient(app_for(db_path, tmp_path, clock=Clock())) as c:
        codes = [c.post("/api/search", json={"family_names": ["Ulverstane"]}).status_code for _ in range(3)]
        assert codes == [200, 200, 429]


# ---- 3. a masked name does not show how long a word is ------------------------------------------------------

def test_a_masked_word_is_its_first_letter_and_a_fixed_number_of_dots():
    dots = MASK_DOT * MASK_DOTS
    assert mask_name("SANTOS MARIA L") == f"S{dots} M{dots} L{dots}"
    assert mask_name("NG BARTHOLOMEW") == f"N{dots} B{dots}"
    assert mask_name("AB") == mask_name("ABCDEFGHIJKL") and mask_name("") == ""
    assert len({len(word) for word in mask_name("LI WOLFESCHLEGELSTEIN X JO").split()}) == 1


def test_the_search_sends_names_masked_to_one_width(client):
    body = client.post("/api/search", json={"family_names": ["Ulverstane"], "places": [{"postcode": "95111"}]}).json()
    owners = {m["owner"] for m in body["matches"]}
    dots = MASK_DOT * MASK_DOTS
    assert owners == {f"U{dots} P{dots}", f"U{dots} W{dots}"}


def test_comparing_with_a_masked_name_uses_first_letters_only():
    dots = MASK_DOT * MASK_DOTS
    masked = f"S{dots} M{dots} L{dots}"
    assert proof.compare_with_mask("Maria Luz Santos", masked) == "full"
    assert proof.compare_with_mask("SANTOS, MARIA L", masked) == "full"
    assert proof.compare_with_mask("Maria Santos", masked) == "partial"
    assert proof.compare_with_mask("Roberto Diaz", masked) == "none"
    assert proof.compare_with_mask("Maria Luz Santos", "") == "none"


# ---- 4. a very large holder does not tie a very common name -------------------------------------------------

def test_holder_key_groups_the_ways_one_holder_is_written():
    assert holder_key("COLOSSUS MERIDIAN BANK NA (BRANCH 0042)") == holder_key("Colossus Meridian Bank, N.A.") \
        == holder_key("The Colossus Meridian Financial Inc") == "COLOSSUS MERIDIAN"
    assert holder_key("BANK OF EXAMPLE NA") == "BANK EXAMPLE" and holder_key("") == ""
    assert holder_key("COLOSSUS MERIDIAN BANK") != holder_key("COLOSSUS PAYROLL")


def test_the_generic_holders_are_read_from_a_file_made_from_the_register():
    data = json.loads(match.GENERIC_HOLDERS_PATH.read_text())
    assert data["holders"] and all(h["owner_records"] >= data["at_least"] for h in data["holders"])
    assert match.GENERIC_HOLDER_KEYS == frozenset(h["key"] for h in data["holders"])
    assert "scripts/make_generic_holders.py" in data["made_by"]


def test_a_very_large_holder_does_not_make_a_very_common_name_strong(con, generic):
    h = person(["Leopold"], ["Draycott"], [Place(postcode="70000")], ["Colossus Meridian Bank"])
    found = by_id(find(con, h, top=500))
    bank = found["K900"]
    assert bank.evidence["holder"] and bank.evidence["holder_generic"] and bank.evidence["name_places"] > COMMON_NAME_PLACES
    assert bank.strength == "possible"
    assert any("very large" in d and "common" in d for d in bank.doubts)
    assert not any(m.strength == "strong" for m in found.values())


def test_the_same_holder_still_ties_a_name_that_is_not_common(con, generic):
    h = person(["Perpetua"], ["Ulverstane"], [Place(postcode="95111")], ["Colossus Meridian Bank"])
    found = by_id(find(con, h))
    assert found["R4"].evidence["holder_generic"] and found["R4"].strength == "strong"


def test_a_holder_that_is_not_very_large_still_ties_a_very_common_name(con, generic):
    h = person(["Leopold"], ["Draycott"], [Place(postcode="70000")], ["Saltbush Nursery"])
    found = by_id(find(con, h, top=500))
    assert found["K901"].strength == "strong" and not found["K901"].evidence["holder_generic"]
    assert found["K900"].strength == "possible"


def test_the_rule_states_the_very_large_holder_exception():
    rule = STRENGTH_RULE.lower()
    assert "very common" in rule and "holder" in rule and str(COMMON_NAME_PLACES) in rule
    base = {"family": True, "given_full": 1, "holder": True, "postcode": True}
    assert strength_of(base) == "strong"
    assert strength_of({**base, "holder_generic": True, "name_places": COMMON_NAME_PLACES}) == "strong"
    assert strength_of({**base, "holder_generic": True, "name_places": COMMON_NAME_PLACES + 1}) == "possible"
    # two given names in full with the postcode is a tie of its own and does not lean on the holder
    assert strength_of({**base, "given_full": 2, "holder_generic": True, "name_places": 5000}) == "strong"
    assert strength_of({**base, "given_full": 2, "postcode": False, "holder_generic": True, "name_places": 5000}) == "possible"


# ---- 5. every strong match says that the proof file decides -------------------------------------------------

def test_every_strong_match_carries_the_line_about_the_proof_file(client):
    body = client.post("/api/search", json={**PERPETUA, "places": [{"postcode": "95111"}]}).json()
    assert body["strong_note"] == STRONG_NOTE and "proof file" in STRONG_NOTE and "label" in STRONG_NOTE
    strong = [m for m in body["matches"] if m["strength"] == "strong"]
    assert strong and all(m["note"] == STRONG_NOTE for m in strong)
    assert all("note" not in m for m in body["matches"] if m["strength"] != "strong")


# ---- the same search gives the same reply -------------------------------------------------------------------

def test_rows_with_equal_amounts_are_cut_off_and_ordered_the_same_way_every_time(con):
    """Two replies can be compared only if nothing in them moves by itself. Records with the same points and the
    same amount are ordered by the record, both where candidates are cut off and in the results."""
    sql, _ = match._candidate_sql(person(["Leopold"], ["Draycott"], [Place(postcode="70000")]), 100)
    assert "amount desc, record_id, owner_norm" in sql
    found = find(con, person(["Leopold"], ["Draycott"]), top=500, floor=0.0)
    again = find(con, person(["Leopold"], ["Draycott"]), top=500, floor=0.0)
    assert [m.record["record_id"] for m in found] == [m.record["record_id"] for m in again]
    # the crowd of same-name records all have the same points; among them the larger amount comes first, and two
    # records with the same points and amount would go by record id
    ties = [(-m.score, -m.record["amount"], m.record["record_id"]) for m in found]
    assert ties == sorted(ties) and len(found) == PLACES + 2
