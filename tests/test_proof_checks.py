"""The checks code makes beside each reading: dates, the name in two places, the issuer, and two separate
readings that must agree. The model is replaced by a table; every decision under test is code."""
import importlib.util
import json
import threading
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from khutlisa import checks, claims as cl, documents, mrz, packet, proof, reading
from khutlisa.server import create_app
from test_claims import AS_PAYER, CLAIMANT, PAYER_KEY, make_register
from test_proof import GOV, HOME, PNG, SEEN, add, by_key, fake_model, open_claim, passport

TODAY = date(2026, 11, 12)
# The specimen lines printed in the passport standard itself (ICAO Doc 9303), for the invented state Utopia.
SPECIMEN = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
LICENCE = {**GOV, "document_type": "driver licence", "names": ["Maria Luz Santos"], "holder_name": "Maria Luz Santos",
           "issue_date": "2022-03-01", "expiry_date": "2030-03-01", "date_of_birth": "1984-02-11",
           "issuing_authority": "California Department of Motor Vehicles", "issuing_country": "USA"}
SEEN.update({
    "licence": LICENCE,
    "backwards": passport("SANTOS", "MARIA LUZ", issued="2032-01-01", expires="2031-05-01"),
    "notaday": {**passport("SANTOS", "MARIA LUZ"), "issue_date": "2021-02-30"},
    "othername": {**passport("SANTOS", "MARIA LUZ"), "holder_name": "MARIA LUZ SANTOS",
                  "machine_readable_lines": mrz.build_td3("REYES", "MARIA LUZ", "PHL", "P1234567", "1984-02-11", "2031-05-01")},
    "canadian": passport("SANTOS", "MARIA LUZ", country="Canada", state="CAN", authority="Passport Canada, Government of Canada"),
    "american": passport("SANTOS", "MARIA LUZ", country="United States of America", state="USA",
                         authority="United States Department of State"),
    "invented": passport("SANTOS", "MARIA LUZ", country="Sampleland", state="XSL", authority="Government of Sampleland"),
    "schoolcard": {**LICENCE, "document_type": "student identity card", "issuing_authority": "Northfield University",
                   "issuing_country": "Philippines"},
    # Two readings of one file that differ: the first sees one expiry date, the second another.
    "tworeadings": [passport("SANTOS", "MARIA LUZ"), passport("SANTOS", "MARIA LUZ", expires="2037-05-01")],
    "twonames": [passport("SANTOS", "MARIA LUZ"), passport("SANTOZ", "MARIA LUZ")],
})


@pytest.fixture
def app(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    return create_app(db_path=make_register(tmp_path), totals_path=tmp_path / "totals.json",
                      web_dist=tmp_path / "no-web", read_documents=True, payer_key=PAYER_KEY)


@pytest.fixture
def api(app):
    with TestClient(app, headers=AS_PAYER) as c:
        yield c


def claim_with(api, app, kind, word):
    claim = open_claim(api)
    add(api, app, claim["id"], kind, word)
    return api.get(f"/api/claims/{claim['id']}").json()


def card_checks(claim, filename):
    card = next(c for c in claim["proof"]["documents"] if c["filename"] == filename)
    return card, {c["key"]: c for c in card["checks"]}


def read(tmp_path, word, kind="id"):
    path = tmp_path / f"{word}.png"
    path.write_bytes(PNG + word.encode())
    return reading.read_twice(path, kind)


def checked(tmp_path, word, kind="id", claimant=CLAIMANT):
    doc = {"id": "a", "kind": kind, "kind_label": documents.KINDS[kind], "filename": f"{word}.png",
           "reading": read(tmp_path, word, kind)}
    return {c["key"]: c for c in checks.document_checks(doc, {"claimant": claimant}, TODAY)}


# ---- 1. dates --------------------------------------------------------------------------------------------------

def test_dates_must_be_real_in_order_and_current(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    good = checked(tmp_path, "passport")["dates"]
    assert good["status"] == "passed" and "2021-05-02" in good["text"] and "2031-05-01" in good["text"]
    backwards = checked(tmp_path, "backwards")["dates"]
    assert backwards["status"] == "failed" and "in the future" in backwards["text"]
    assert "issued on 2032-01-01 and expires on 2031-05-01" in backwards["text"]
    notaday = checked(tmp_path, "notaday")["dates"]
    assert notaday["status"] == "failed" and "2021-02-30, is not a real calendar date" in notaday["text"]
    old = checked(tmp_path, "oldpassport")["dates"]
    assert old["status"] == "failed" and "It expired on 2015-05-01." in old["text"]
    SEEN["nodates"] = {**LICENCE, "issue_date": "", "expiry_date": ""}
    missing = checked(tmp_path, "nodates")["dates"]
    assert missing["status"] == "held" and "expiry date" in missing["text"]
    # A bill is not identification: its date is checked, and it has no expiry to pass.
    bill = checked(tmp_path, "homebill", "proof_of_address")["dates"]
    assert bill["status"] == "passed" and "2026-10-03" in bill["text"]
    SEEN["futurebill"] = {**SEEN["homebill"], "dates": [{"label": "bill date", "value": "2031-10-03"}]}
    assert checked(tmp_path, "futurebill", "proof_of_address")["dates"]["status"] == "failed"


def test_inconsistent_dates_stop_a_passport_from_settling_anything(api, app):
    claim = claim_with(api, app, "id", "backwards")
    item = by_key(claim)["photo_id"]
    assert item["status"] == "partly" and claim["proof"]["ready"] is False
    assert any("issued on 2032-01-01 and expires on 2031-05-01" in p for p in item["supports"][0]["problems"])
    card, _ = card_checks(claim, "backwards.png")
    assert card["standing"] == "refused" and claim["proof"]["record_link"]["status"] == "not shown"


# ---- 2. the name in two places ----------------------------------------------------------------------------------

def test_the_machine_readable_zone_is_parsed_in_code_with_its_check_digits():
    zone = mrz.parse(SPECIMEN, TODAY)
    assert (zone["surname"], zone["given_names"]) == ("ERIKSSON", "ANNA MARIA")
    assert zone["issuing_state"] == "UTO" and zone["birth_date"] == "1974-08-12" and zone["expiry_date"] == "2012-04-15"
    assert zone["check_digits"] == {"document_number": True, "birth_date": True, "expiry_date": True, "composite": True}
    assert "L898902C3" not in json.dumps(zone) and "ZE184226B" not in json.dumps(zone)   # the numbers are not kept
    wrong = mrz.parse([SPECIMEN[0], SPECIMEN[1].replace("1204159", "1304159")], TODAY)
    assert wrong["check_digits"]["expiry_date"] is False and wrong["check_digits"]["birth_date"] is True
    # A reader may miscount the filler characters. The fixed part still parses; the whole-line digit is left out.
    short = mrz.parse(["P<UTOERIKSSON<<ANNA<MARIA<<<<", SPECIMEN[1][:28] + "ZE184226B<<10"], TODAY)
    assert short["surname"] == "ERIKSSON" and short["check_digits"]["expiry_date"] is True
    assert short["check_digits"]["composite"] is None
    assert mrz.parse(["NOT A ZONE"], TODAY) is None and mrz.parse([], TODAY) is None
    made = mrz.build_td3("TOLMEDO PERALMONTE", "MARISOL ELENA", "MEX", "SAMPLE000", "1986-07-23", "2033-05-07")
    assert [len(line) for line in made] == [44, 44] and made[0].startswith("P<MEXTOLMEDO<PERALMONTE<<MARISOL<ELENA<")
    back = mrz.parse(made, TODAY)
    assert all(back["check_digits"].values()) and back["given_names"] == "MARISOL ELENA"


def test_a_passport_name_must_agree_in_the_name_field_and_the_machine_readable_lines(api, app, tmp_path):
    good = card_checks(claim_with(api, app, "id", "passport"), "passport.png")[1]["name_two_places"]
    assert good["status"] == "passed" and "check digits" in good["text"]
    assert "The name field, SANTOS, MARIA LUZ, and the machine-readable lines, MARIA LUZ SANTOS, agree" in good["text"]
    claim = claim_with(api, app, "id", "othername")
    card, found = card_checks(claim, "othername.png")
    assert found["name_two_places"]["status"] == "failed"
    assert "MARIA LUZ SANTOS" in found["name_two_places"]["text"] and "MARIA LUZ REYES" in found["name_two_places"]["text"]
    assert by_key(claim)["photo_id"]["status"] == "partly" and card["standing"] == "refused"
    SEEN["baddigit"] = {**passport("SANTOS", "MARIA LUZ")}
    lines = list(SEEN["baddigit"]["machine_readable_lines"])
    lines[1] = lines[1][:27] + ("1" if lines[1][27] != "1" else "2") + lines[1][28:]
    SEEN["baddigit"]["machine_readable_lines"] = lines
    assert "check digit on the expiry date" in checked(tmp_path, "baddigit")["name_two_places"]["text"]
    SEEN["nozone"] = {**passport("SANTOS", "MARIA LUZ"), "machine_readable_lines": []}
    assert checked(tmp_path, "nozone")["name_two_places"]["status"] == "held"


def test_a_driving_licence_has_no_machine_readable_zone_and_the_result_says_so(api, app):
    claim = claim_with(api, app, "id", "licence")
    card, found = card_checks(claim, "licence.png")
    assert found["name_two_places"]["status"] == "not_applicable"
    assert "no machine-readable lines" in found["name_two_places"]["text"] and "one place" in found["name_two_places"]["text"]
    assert by_key(claim)["photo_id"]["status"] == "satisfied" and card["standing"] == "accepted"
    assert found["issuer"]["status"] == "passed" and "United States" in found["issuer"]["text"]


def test_the_machine_readable_lines_are_never_stored_with_their_numbers(api, app):
    claim = claim_with(api, app, "id", "passport")
    stored = json.dumps(app.state.claims.load(claim["id"]))
    assert "P1234567" not in stored and "P1234567" not in json.dumps(claim)
    zone = claim["documents"][0]["reading"]["mrz"]
    assert zone["surname"] == "SANTOS" and zone["lines"][1].startswith("·········")


# ---- 3. the issuer ----------------------------------------------------------------------------------------------

def test_code_decides_whether_an_issuer_is_a_government_and_which_country_it_is():
    for name in ("Department of Foreign Affairs", "Secretaría de Relaciones Exteriores", "Government of Mexico, Passport Office",
                 "California Department of Motor Vehicles", "Republic of the Philippines", "DFA Manila",
                 "United States Department of State"):
        assert checks.is_government(name) is True, name
    for name in ("Kaiser Foundation Hospitals", "Northfield University", "First Example Bank", "A Gym", "A Club",
                 "Empacadora Valle Sereno", "National Bank of Somewhere"):
        assert checks.is_government(name) is False, name
    assert checks.is_government("Zorblat") is None and checks.is_government("") is None
    assert checks.country_code("Republic of the Philippines") == "PH" and checks.country_code("MEX") == "MX"
    assert checks.country_code("Estados Unidos Mexicanos") == "MX" and checks.country_code("USA") == "US"
    assert checks.country_code("Sampleland") is None and checks.country_code("") is None


def test_identification_from_the_claimants_country_or_the_united_states_passes(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    home = checked(tmp_path, "passport")["issuer"]
    assert home["status"] == "passed" and "Philippines" in home["text"] and "government" in home["text"]
    assert checked(tmp_path, "american")["issuer"]["status"] == "passed"
    school = checked(tmp_path, "schoolcard")["issuer"]
    assert school["status"] == "failed" and "Northfield University, which is not a government authority" in school["text"]


@pytest.mark.parametrize("word, why", [("canadian", "Canada"), ("invented", "Sampleland")])
def test_identification_from_another_or_an_unknown_country_is_held_for_a_person(api, app, word, why):
    claim = claim_with(api, app, "id", word)
    card, found = card_checks(claim, f"{word}.png")
    assert found["issuer"]["status"] == "held" and why in found["issuer"]["text"]
    assert card["standing"] == "held for a person to look at" and card["held"] is True and why in card["held_reasons"][0]
    result = claim["proof"]
    assert result["ready"] is False and result["status"] == "held for a person to look at"
    assert result["held"] == [{"document_id": card["id"], "filename": f"{word}.png",
                               "kind_label": "Photo identification", "reasons": card["held_reasons"]}]
    item = by_key(claim)["photo_id"]
    assert item["status"] == "partly"                    # held, so it settles nothing by itself
    assert any("held for a person to look at" in p for p in item["supports"][0]["problems"])
    assert any(g["key"] == "held" and g["required"] and why in g["text"] for g in result["gaps"])
    if word == "canadian":
        assert "Philippines" in found["issuer"]["text"]   # the country the claimant gave is named beside it


# ---- 4. two separate readings -----------------------------------------------------------------------------------

def test_each_document_is_read_twice_at_the_same_time(tmp_path):
    together = threading.Barrier(2, timeout=5)
    calls = []

    def read_one(path, kind):
        calls.append(kind)
        together.wait()          # a second call that only starts after the first has finished never arrives here
        return documents.clean_reading(SEEN["homebill"])

    path = tmp_path / "bill.png"
    path.write_bytes(PNG)
    out = reading.read_twice(path, "proof_of_address", read_one)
    assert calls == ["proof_of_address"] * 2 and out["status"] == "read"
    assert out["agreement"] == {"status": "agree", "disagreed": []} and len(out["readings"]) == 2
    assert out["readings"][0] == out["readings"][1] and out["readings"][0]["issue_date"] == "2026-10-03"


@pytest.mark.parametrize("word, what", [("tworeadings", "expiry date"), ("twonames", "name")])
def test_readings_that_disagree_hold_the_document_for_a_person(api, app, word, what):
    claim = claim_with(api, app, "id", word)
    card, found = card_checks(claim, f"{word}.png")
    assert found["two_readings"]["status"] == "held" and what in found["two_readings"]["text"]
    assert card["standing"] == "held for a person to look at" and card["read"] == "twice"
    both = claim["documents"][0]["reading"]["readings"]
    assert len(both) == 2 and claim["documents"][0]["reading"]["agreement"]["status"] == "disagree"
    if word == "tworeadings":
        assert {r["expiry_date"] for r in both} == {"2031-05-01", "2037-05-01"}
    result = claim["proof"]
    assert result["ready"] is False and result["status"] == "held for a person to look at"
    assert by_key(claim)["photo_id"]["status"] == "partly" and claim["state"] == "PROOF_NEEDED"
    assert any(what in reason for reason in result["reasons"])
    refused = api.post(f"/api/payer/claims/{claim['id']}/approve")
    assert refused.status_code == 409


def test_one_reading_that_fails_leaves_nothing_to_compare(tmp_path):
    answers = iter([documents.clean_reading(SEEN["homebill"]), {"status": "failed", "problem": "x"}])
    lock = threading.Lock()

    def read_one(path, kind):
        with lock:
            return next(answers)

    path = tmp_path / "bill.png"
    path.write_bytes(PNG)
    out = reading.read_twice(path, "proof_of_address", read_one)
    assert out["status"] == "read" and out["agreement"]["status"] == "one_reading"
    doc = {"id": "a", "kind": "proof_of_address", "kind_label": "Proof of address", "filename": "bill.png", "reading": out}
    found = {c["key"]: c for c in checks.document_checks(doc, {"claimant": CLAIMANT}, TODAY)}
    assert found["two_readings"]["status"] == "held" and "Only one" in found["two_readings"]["text"]
    assert reading.read_twice(tmp_path / "missing.png", "id") == {"status": "not_read"}


def test_a_claim_file_written_before_documents_were_read_twice_still_loads_as_read_once(api, app):
    claim = open_claim(api)
    for kind, word in (("id", "passport"), ("tax_number", "w8ben"), ("proof_of_address", "homebill")):
        add(api, app, claim["id"], kind, word)
    store = app.state.claims
    stored = store.load(claim["id"])
    for doc in stored["documents"]:      # the shape a reading had before: one reading and none of the new fields
        doc["reading"] = documents.clean_reading({k: v for k, v in SEEN[doc["filename"][:-4]].items()
                                                  if k in ("document_type", "names", "addresses", "dates", "issuer",
                                                           "presents_as_government_photo_id", "photo_present")})
        for key in ("holder_name", "issue_date", "expiry_date", "date_of_birth", "issuing_authority",
                    "issuing_country", "mrz"):
            doc["reading"].pop(key, None)
        assert "readings" not in doc["reading"]
    store.save(stored)
    claim = api.get(f"/api/claims/{claim['id']}").json()
    assert claim["proof"]["ready"] is True and claim["proof"]["status"] == "ready"
    card, found = card_checks(claim, "passport.png")
    assert card["read"] == "once" and found["two_readings"]["status"] == "not_checked"
    assert "read once" in found["two_readings"]["text"]
    row = next(r for r in api.get("/api/payer/queue").json()["claims"] if r["id"] == claim["id"])
    assert {d["read"] for d in row["proof_file"]["documents"]} == {"once"}


# ---- 5 and 6. the status and the remaining risk, for the claimant and for the holder -----------------------------

def test_the_proof_says_what_remains_unchecked_and_who_decides(api, app):
    claim = open_claim(api)
    for kind, word in (("id", "passport"), ("tax_number", "w8ben"), ("proof_of_address", "homebill")):
        add(api, app, claim["id"], kind, word)
    claim = api.get(f"/api/claims/{claim['id']}").json()
    result = claim["proof"]
    assert result["remaining_risk"] == "Khutlisa read these documents; it has not verified them with the issuing authority."
    assert result["decided_by"] == "The holder, not Khutlisa, approves."
    assert result["status"] == "ready" and result["held"] == []
    card, found = card_checks(claim, "passport.png")
    assert card["standing"] == "accepted" and card["read"] == "twice" and card["held"] is False
    assert [c["key"] for c in card["checks"]] == ["dates", "name_two_places", "issuer", "two_readings"]
    assert {c["status"] for c in card["checks"]} == {"passed"}
    row = next(r for r in api.get("/api/payer/queue").json()["claims"] if r["id"] == claim["id"])
    file = row["proof_file"]
    assert file["remaining_risk"] == result["remaining_risk"] and file["decided_by"] == result["decided_by"]
    assert file["status"] == "ready" and file["held"] == []
    shown = {d["filename"]: d for d in file["documents"]}
    assert shown["passport.png"]["standing"] == "accepted" and shown["passport.png"]["read"] == "twice"
    assert [c["status"] for c in shown["passport.png"]["checks"]] == ["passed"] * 4
    assert api.get("/api/payer/queue").json()["claims"][0]["proof_file"]["assessed"] is True


def test_held_is_shown_to_the_holder_as_its_own_status_and_not_as_refused(api, app):
    claim = open_claim(api)
    add(api, app, claim["id"], "id", "canadian")
    add(api, app, claim["id"], "id", "schoolcard")
    row = next(r for r in api.get("/api/payer/queue").json()["claims"] if r["id"] == claim["id"])
    file = row["proof_file"]
    assert file["status"] == "held for a person to look at" and file["ready"] is False
    assert [h["filename"] for h in file["held"]] == ["canadian.png"] and "Canada" in file["held"][0]["reasons"][0]
    shown = {d["filename"]: d["standing"] for d in file["documents"]}
    assert shown == {"canadian.png": "held for a person to look at", "schoolcard.png": "refused"}


def test_the_packet_carries_the_same_sentence_about_what_was_not_verified(api, app):
    claim = open_claim(api)
    add(api, app, claim["id"], "id", "passport")
    stored = app.state.claims.load(claim["id"])
    result = api.get(f"/api/claims/{claim['id']}").json()["proof"]
    text = " ".join(packet.build(stored, cl.checklist(stored), compress=False, proof=result).decode("latin-1").split())
    for words in ("it has not verified them with", "The holder, not Khutlisa, approves", "read twice"):
        assert words in text, words


# ---- 7. the sample documents ------------------------------------------------------------------------------------

def test_each_sample_passport_is_of_the_country_its_person_lives_in_with_a_correct_zone():
    path = Path(__file__).resolve().parents[1] / "scripts" / "make_sample_documents.py"
    spec = importlib.util.spec_from_file_location("make_sample_documents", path)
    made = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(made)
    for person, state, code in ((made.MARISOL, "MEX", "MX"), (made.AMIHAN, "PHL", "PH")):
        facts = made.passport_facts(person)
        assert checks.country_code(facts["country"]) == code and person["now"]["country"] == facts["country"]
        assert checks.is_government(facts["authority"]) is True
        zone = mrz.parse(facts["machine_readable_lines"], TODAY)
        assert zone["issuing_state"] == state and all(zone["check_digits"].values())
        assert [len(line) for line in facts["machine_readable_lines"]] == [44, 44]
        assert zone["expiry_date"] == facts["expires"] and zone["birth_date"] == person["born"][0]
        printed = {"holder_name": person["now"]["name"], "mrz": zone}
        assert checks.names_agree(printed["holder_name"], zone) is True
        assert date.fromisoformat(facts["issued"]) < TODAY < date.fromisoformat(facts["expires"])
    source = path.read_text()
    assert "Sampleland" not in source and "invented country" not in source and "SAMPLE" in source


# ---- 8. the tax number ------------------------------------------------------------------------------------------

def test_a_taxpayer_document_from_abroad_counts_only_together_with_the_passport(api, app):
    claim = open_claim(api)
    add(api, app, claim["id"], "tax_number", "w8ben")
    item = by_key(api.get(f"/api/claims/{claim['id']}").json())["tax_number"]
    assert item["status"] == "partly"
    assert any("only together with valid photo identification" in p for p in item["supports"][0]["problems"])
    add(api, app, claim["id"], "id", "passport")
    item = by_key(api.get(f"/api/claims/{claim['id']}").json())["tax_number"]
    assert item["status"] == "satisfied"
    assert any("signed form W-8BEN" in f and "packet" in f for f in item["supports"][0]["facts"])


def test_a_passport_that_prints_surname_and_given_names_apart_is_matched_on_its_whole_name_field(api, app):
    SEEN["splitnames"] = {**passport("SANTOS", "MARIA LUZ"), "names": ["SANTOS", "MARIA LUZ"]}
    claim = claim_with(api, app, "id", "splitnames")
    item = by_key(claim)["photo_id"]
    assert item["status"] == "satisfied", item["supports"][0]["problems"]
    assert "MARIA LUZ SANTOS, matches the name you gave" in " ".join(item["supports"][0]["facts"])
