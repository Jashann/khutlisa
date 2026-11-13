"""Document reading and the proof file. The model is replaced by a function that answers from a table; the
comparisons under test are the code in proof.py."""
import json
import threading
from datetime import date

import pytest
from fastapi.testclient import TestClient

from khutlisa import claims as cl, documents, llm, mrz, packet, proof
from khutlisa.server import create_app, mask_name
from test_claims import AS_PAYER, CLAIMANT, MX_BANK, PAYER_KEY, PRIVATE, give_bank, make_register
from test_server import MARIA, ref

PNG = b"\x89PNG\r\n\x1a\n"
HOME = {"street": "14 Mango Avenue", "city": "Cebu City", "region": "", "postcode": "6000", "country": "PH",
        "whose": "person"}
WINDROSE = {"street": "1482 Windrose Lane Apt 7", "city": "Daly City", "region": "CA", "postcode": "94015",
            "country": "US", "whose": "person"}
# What the stand-in model "sees" on each made-up document, by a word stored in the file.
GOV = {"presents_as_government_photo_id": True, "photo_present": True}


def passport(surname, given, country="Philippines", state="PHL", issued="2021-05-02", expires="2031-05-01",
             born="1984-02-11", authority="Department of Foreign Affairs"):
    """What the stand-in model reports for a passport that passes every check: the name field, the dates, the
    issuer, and the machine-readable lines copied as printed (with a passport number, which must never be kept)."""
    return {**GOV, "document_type": "passport photo page", "names": [f"{surname}, {given}"],
            "holder_name": f"{given} {surname}", "issue_date": issued, "expiry_date": expires, "date_of_birth": born,
            "issuer": authority, "issuing_authority": authority, "issuing_country": country,
            "machine_readable_lines": mrz.build_td3(surname, given, state, "P1234567", born, expires)}


SEEN = {
    "passport": {**passport("SANTOS", "MARIA LUZ"), "holder_name": "SANTOS, MARIA LUZ", "addresses": [],
                 "dates": [{"label": "date of expiry", "value": "2031-05-01"}],
                 "identifiers_present": ["passport number P1234567"], "legible": True, "concerns": [],
                 "summary": "Passport P1234567 of Maria Luz Santos, tax number 123-45-6789."},
    "oldpassport": {**passport("SANTOS", "MARIA LUZ", issued="2005-05-02", expires="2015-05-01"),
                    "names": ["Maria Luz Santos"], "dates": [{"label": "date of expiry", "value": "2015-05-01"}]},
    "w8ben": {"document_type": "IRS form W-8BEN", "names": ["Maria Luz Santos"], "issuer": "Internal Revenue Service",
              "dates": [{"label": "signed", "value": "2026-11-01"}]},
    "homebill": {"document_type": "electricity bill", "names": ["Maria Luz Santos"], "addresses": [HOME],
                 "issuer": "Visayan Electric", "dates": [{"label": "bill date", "value": "2026-10-03"}]},
    "payslip": {"document_type": "payslip", "names": ["Maria L. Santos"], "addresses": [WINDROSE],
                "issuer": "Kaiser Foundation Hospitals", "dates": [{"label": "pay date", "value": "2014-03-28"}],
                "identifiers_present": ["employee number"]},
    "dalybill": {"document_type": "gas bill", "names": ["Maria Santos"],
                 "addresses": [{"street": "5 Other Road", "city": "Daly City", "region": "CA", "postcode": "94015"}],
                 "issuer": "Pacific Gas and Electric", "concerns": ["The corner of the page is cut off."]},
    "badge": {"document_type": "staff badge", "names": ["Maria Luz Santos"], "issuer": "Kaiser Foundation Hospitals",
              "dates": [{"label": "expires", "value": "2019-06-14"}], "marked_sample": True},
    "stranger": {**passport("DIAZ", "ROBERTO"), "names": ["Roberto Diaz"], "holder_name": "Roberto Diaz"},
    "edited": {"document_type": "electricity bill", "names": ["Maria Luz Santos"], "addresses": [HOME],
               "signs_of_editing": True, "concerns": ["The name is in a different font from the rest of the page."]},
    "blur": {"document_type": "", "names": [], "legible": False, "concerns": ["Nothing on the page can be read."]},
}


def fake_model(monkeypatch):
    prompts, lock = [], threading.Lock()

    def ask(prompt, files=None, **kw):
        with lock:      # a document is read by two calls at once
            prompts.append((prompt, files))
            nth = sum(1 for _, f in prompts if f == files) - 1
        word = open(files[0], "rb").read()[len(PNG):].decode()
        seen = SEEN[word]
        if isinstance(seen, list):      # two readings of one file that differ: each call gets the next answer
            seen = seen[nth % len(seen)]
        return json.dumps(seen)

    monkeypatch.setattr(llm, "ask", ask)
    return prompts


@pytest.fixture
def app(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    db = make_register(tmp_path)
    return create_app(db_path=db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no-web",
                      read_documents=True, payer_key=PAYER_KEY)


@pytest.fixture
def api(app):
    with TestClient(app, headers=AS_PAYER) as c:
        yield c


def open_claim(api, record_id="P1", claimant=CLAIMANT):
    r = api.post("/api/claims", json={"record_id": ref(api, record_id), "claimant": claimant, "history": MARIA})
    assert r.status_code == 201, r.text
    return r.json()


def add(api, app, claim_id, kind, word):
    r = api.post(f"/api/claims/{claim_id}/documents", data={"kind": kind}, files={"file": (f"{word}.png", PNG + word.encode())})
    assert r.status_code == 201, r.text
    app.state.reading.join()
    return r.json()


def by_key(claim):
    return {r["key"]: r for r in claim["proof"]["requirements"]}


# ---- reading ---------------------------------------------------------------------------------------------------

def test_reading_asks_for_only_what_is_visible_and_never_keeps_an_identity_number(tmp_path, monkeypatch):
    prompts = fake_model(monkeypatch)
    path = tmp_path / "p.png"
    path.write_bytes(PNG + b"passport")
    out = documents.read_document(path, "id")
    prompt, files = prompts[0]
    assert files == [str(path)] and "only what is visibly printed" in prompt and "Never write the number" in prompt
    assert "photo identification" in prompt and "cannot be read" in prompt
    assert out["status"] == "read" and out["names"] == ["SANTOS, MARIA LUZ"] and out["legible"] is True
    text = json.dumps(out, ensure_ascii=False)
    assert "P1234567" not in text and "123-45-6789" not in text and "1234" not in text
    assert out["identifiers_present"] == ["passport number ······67"] and "·········89" in out["summary"]
    assert out["dates"] == [{"label": "date of expiry", "value": "2031-05-01"}]     # a date is not a number to hide


def test_reading_reports_what_went_wrong(tmp_path, monkeypatch):
    path = tmp_path / "p.png"
    path.write_bytes(PNG + b"blur")
    assert documents.read_document(path, "id")["status"] == "failed"         # no model in the tests
    assert documents.read_document(tmp_path / "missing.png", "id") == {"status": "not_read"}
    fake_model(monkeypatch)
    out = documents.read_document(path, "id")
    assert out["status"] == "unreadable" and out["legible"] is False and out["concerns"]
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: "[1, 2]")
    assert documents.read_document(path, "id")["status"] == "failed"


# ---- comparisons -----------------------------------------------------------------------------------------------

def test_names_are_compared_in_any_order_with_initials_and_spelling_differences():
    assert proof.compare_names("Maria Luz Santos", "SANTOS MARIA L") == "full"
    assert proof.compare_names("SANTOS, MARIA L.", "Maria Luz Santos") == "full"
    # A near spelling is not the same name when identity is being proven: these are different people.
    assert proof.compare_names("Maria Luz Santoz", "SANTOS MARIA L") == "partial"
    for near, name in (("JUANA", "JUAN"), ("PAULA", "PAUL"), ("DANIELA", "DANIEL"), ("ROBERTA", "ROBERT"),
                       ("MARTIN", "MARTINA")):
        assert proof.compare_names(f"{near} REYES", f"REYES {name}") == "partial"
    # A surname written joined or split is still the same surname.
    assert proof.compare_names("Maria Delacruz", "DELA CRUZ MARIA") == "full"
    assert proof.compare_names("Maria Dela Cruz", "DELACRUZ MARIA") == "full"
    assert proof.compare_names("María Lúz Santos-Villanueva", "SANTOS MARIA") == "full"
    assert proof.compare_names("Maria Santos", "SANTOS MARIA QUIXOTIC") == "partial"
    assert proof.compare_names("Luz Villanueva", "SANTOS MARIA L") == "none"
    assert proof.compare_names("Roberto Diaz", "SANTOS MARIA L") == "none"
    assert proof.compare_names("", "SANTOS MARIA L") == "none"
    assert proof.compare_with_mask("Maria Luz Santos", mask_name("SANTOS MARIA L")) == "full"
    assert proof.compare_with_mask("Maria Santos", mask_name("SANTOS MARIA QUIXOTIC")) == "partial"
    assert proof.compare_with_mask("Roberto Diaz", mask_name("SANTOS MARIA L")) == "none"


def test_addresses_are_compared_with_the_typed_address_and_with_the_record():
    assert proof.address_against_typed(HOME, CLAIMANT["address"]) is True
    assert proof.address_against_typed(WINDROSE, CLAIMANT["address"]) is False
    assert proof.address_against_typed({"street": "99 Banana Road", "city": "Cebu City"}, CLAIMANT["address"]) is False
    record = {"owner_street": "1482 WINDROSE LANE APT 7", "owner_city": "DALY CITY", "owner_region": "CA",
              "owner_postcode": "94015-1203"}
    assert proof.address_against_record(WINDROSE, record) == {"street", "postcode", "city"}
    assert proof.address_against_record({"street": "5 Other Road", "city": "Daly City", "postcode": "94014"}, record) == {"city"}
    assert proof.address_against_record(HOME, record) == set()
    assert proof.expired_dates({"dates": [{"label": "Expires", "value": "2019-06-14"},
                                          {"label": "Issued", "value": "2009-06-15"}]}, date(2026, 11, 11)) == ["2019-06-14"]


# ---- the proof file --------------------------------------------------------------------------------------------

def test_a_new_claim_is_not_ready_and_names_each_gap_with_how_to_close_it(api):
    claim = open_claim(api)
    result = claim["proof"]
    assert result["assessed"] and result["readiness"] == "not ready" and result["ready"] is False
    assert {r["status"] for r in result["requirements"]} == {"missing"}
    gaps = {g["key"]: g for g in result["gaps"]}
    assert gaps["reported_address"]["text"] == "No document shows the Daly City address the money was reported under."
    assert gaps["reported_address"]["how"] == "A bank statement, utility bill or lease from that address would close it."
    assert gaps["reported_address"]["required"] is False and gaps["photo_id"]["required"] is True
    assert "passport" in gaps["photo_id"]["how"] and "W-8BEN" in gaps["tax_number"]["how"]
    assert "record_name" in gaps and result["reasons"] == [g["text"] for g in result["gaps"] if g["required"]]
    assert all(i["proof"] == "missing" for i in claim["checklist"]["items"])


def test_an_upload_answers_at_once_and_the_reading_arrives_in_the_background(api, app, monkeypatch):
    claim = open_claim(api)
    r = api.post(f"/api/claims/{claim['id']}/documents", data={"kind": "id"},
                 files={"file": ("passport.png", PNG + b"passport")})
    assert r.json()["documents"][0]["reading"] == {"status": "reading"}
    app.state.reading.join()
    claim = api.get(f"/api/claims/{claim['id']}").json()
    doc = claim["documents"][0]
    assert doc["reading"]["status"] == "read" and doc["reading"]["names"] == ["SANTOS, MARIA LUZ"] and doc["read_at"]
    assert "P1234567" not in json.dumps(claim) and "stored_as" not in doc
    assert any("was read" in e["note"] for e in claim["history"])
    item = by_key(claim)["photo_id"]
    assert item["status"] == "satisfied"
    facts = " ".join(item["supports"][0]["facts"])
    assert "SANTOS, MARIA LUZ" in facts and "the name you gave, Maria Luz Santos" in facts
    assert mask_name("SANTOS MARIA L") in facts and claim["proof"]["record_link"]["status"] == "matched"
    card = claim["proof"]["documents"][0]
    assert card["supports"][0]["key"] == "photo_id" and card["supports"][0]["settles"] is True


def test_documents_that_do_not_tie_are_partly_and_say_why(api, app):
    claim = open_claim(api)
    add(api, app, claim["id"], "id", "stranger")
    add(api, app, claim["id"], "proof_of_address", "payslip")      # shows the old address, not the current one
    add(api, app, claim["id"], "tax_number", "blur")
    claim = api.get(f"/api/claims/{claim['id']}").json()
    items = by_key(claim)
    assert items["photo_id"]["status"] == "partly"
    assert "Roberto Diaz, does not match the name you gave" in items["photo_id"]["supports"][0]["problems"][0]
    assert items["current_address"]["status"] == "partly"
    assert any("is not the current address you gave" in p for p in items["current_address"]["supports"][0]["problems"])
    assert items["tax_number"]["status"] == "partly"
    assert "Nothing could be read" in items["tax_number"]["supports"][0]["problems"][0]
    # The payslip was added as something else, yet it shows the reported address, so it supports that item.
    assert items["reported_address"]["status"] == "satisfied"
    facts = " ".join(items["reported_address"]["supports"][0]["facts"])
    assert "matches the street and city the money was reported under" in facts
    assert "issued by Kaiser Foundation Hospitals, the holder that reported the money" in facts
    assert "It is dated 2014-03-28 (pay date)." in facts
    gap = next(g for g in claim["proof"]["gaps"] if g["key"] == "current_address")
    assert gap["text"].startswith("The proof of address you added (payslip.png) does not settle")
    assert claim["proof"]["ready"] is False and claim["state"] == "PROOF_NEEDED"


def test_an_expired_identity_document_and_an_edited_bill_do_not_settle_anything(api, app):
    claim = open_claim(api)
    add(api, app, claim["id"], "id", "oldpassport")
    add(api, app, claim["id"], "proof_of_address", "edited")
    claim = api.get(f"/api/claims/{claim['id']}").json()
    items = by_key(claim)
    assert items["photo_id"]["status"] == "partly" and items["current_address"]["status"] == "partly"
    assert any("expired on 2015-05-01" in p for p in items["photo_id"]["supports"][0]["problems"])
    assert "It shows signs of having been edited." in items["current_address"]["supports"][0]["problems"]
    cards = {c["filename"]: c for c in claim["proof"]["documents"]}
    assert cards["edited.png"]["concerns"] == ["The name is in a different font from the rest of the page."]
    assert cards["oldpassport.png"]["concerns"] == ["It expired on 2015-05-01."]


def test_a_complete_proof_is_ready_moves_the_claim_on_and_can_be_approved(api, app):
    claim = open_claim(api)
    refused = api.post(f"/api/payer/claims/{claim['id']}/approve")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "proof is not ready" in detail["message"] and "No photo identification has been added." in detail["reasons"]
    add(api, app, claim["id"], "id", "passport")
    add(api, app, claim["id"], "tax_number", "w8ben")
    assert api.get(f"/api/claims/{claim['id']}").json()["state"] == "PROOF_NEEDED"
    assert api.post(f"/api/payer/claims/{claim['id']}/approve").status_code == 409
    add(api, app, claim["id"], "proof_of_address", "homebill")
    give_bank(api, claim["id"])
    claim = api.get(f"/api/claims/{claim['id']}").json()
    result = claim["proof"]
    assert result["ready"] and result["readiness"] == "ready" and result["satisfied"] == 3 and claim["state"] == "PROOF_READY"
    assert [g["key"] for g in result["gaps"]] == ["reported_address"]        # asked for, not blocking
    assert "current address you gave" in " ".join(by_key(claim)["current_address"]["supports"][0]["facts"])
    row = next(r for r in api.get("/api/payer/queue").json()["claims"] if r["id"] == claim["id"])
    assert row["proof_file"]["ready"] is True and len(row["proof_file"]["requirements"]) == 4
    assert row["proof_file"]["requirements"][0]["facts"]
    approved = api.post(f"/api/payer/claims/{claim['id']}/approve")
    assert approved.status_code == 200 and approved.json()["state"] == "APPROVED"
    assert "proof was ready" in api.get(f"/api/claims/{claim['id']}").json()["history"][-1]["note"]
    # Rejecting never needs a ready proof.
    other = open_claim(api, "P4")
    assert api.post(f"/api/payer/claims/{other['id']}/reject", json={"reason": "No documents."}).status_code == 200


def test_the_private_owner_name_and_street_are_compared_but_never_shown(api, app, tmp_path):
    # P2's owner carries a name the claimant never gave (QUIXOTIC) and lives on a street they never gave.
    claim = open_claim(api, "P2")
    add(api, app, claim["id"], "proof_of_address", "dalybill")
    add(api, app, claim["id"], "other", "badge")
    view = api.get(f"/api/claims/{claim['id']}")
    queue = api.get("/api/payer/queue")
    stored = app.state.claims.load(claim["id"])
    full = {"owner_name": "SANTOS MARIA QUIXOTIC", "owner_street": "77 HOLLYHOCK TERRACE", "owner_city": "DALY CITY",
            "owner_region": "CA", "owner_postcode": "94015"}
    result = proof.build_proof(stored, stored["documents"], full)
    pdf = packet.build(stored, cl.checklist(stored), compress=False, proof=result).decode("latin-1")
    on_disk = (tmp_path / "claims" / f"{claim['id']}.json").read_text()
    # The claimant's own typed street (WINDROSE, part of the history they gave) is kept with the claim and
    # shown back to them. It is not this record's street, and nothing from the record may appear anywhere.
    typed = json.dumps(MARIA).upper()
    for text in (view.text, on_disk):
        for word in PRIVATE:
            assert word in typed or word not in text.upper()
    for text in (queue.text, json.dumps(result), pdf):
        for word in PRIVATE:
            assert word not in text.upper()
    result = view.json()["proof"]
    assert result["compared_with"] == "the full register record"
    reported = by_key(view.json())["reported_address"]
    assert reported["status"] == "partly"
    bill = next(s for s in reported["supports"] if s["filename"] == "dalybill.png")
    assert any("only partly matches the owner's name on the record" in p and "does not show" in p for p in bill["problems"])
    assert any("matches the city and postcode" in f and "94015" in f for f in bill["facts"])
    # Neither document is government photo identification, so neither can tie a person to the record.
    assert result["record_link"]["status"] == "not shown" and mask_name("SANTOS MARIA QUIXOTIC") in result["record_link"]["text"]
    assert result["samples"] == 1 and "marked as a sample" in result["summary"]
    row = next(r for r in queue.json()["claims"] if r["id"] == claim["id"])
    assert row["proof_file"]["ready"] is False and row["proof_file"]["reasons"]
    assert {"filename": "dalybill.png", "concerns": ["The corner of the page is cut off."]} in row["proof_file"]["concerns"]


def test_without_the_register_record_the_name_is_checked_against_the_mask():
    claim = {"record": {"owner": mask_name("SANTOS MARIA L"), "owner_is_organisation": False, "amount": 50.0,
                        "owner_city": "DALY CITY", "owner_region": "CA", "holder_name": "KAISER FOUNDATION HOSPITALS",
                        "property_type": "WAGES"},
             "claimant": CLAIMANT,
             "documents": [{"id": "a", "kind": "payslip", "kind_label": "Payslip", "filename": "slip.png",
                            "reading": documents.clean_reading(SEEN["payslip"])},
                           {"id": "b", "kind": "id", "kind_label": "Photo identification", "filename": "new.png",
                            "reading": {"status": "reading"}}]}
    result = proof.build_proof(claim)
    items = {r["key"]: r for r in result["requirements"]}
    assert result["compared_with"] == "the public form of the record" and result["reading"] == 1
    assert items["reported_address"]["status"] == "satisfied"
    fact = items["reported_address"]["supports"][0]["facts"][0]
    assert "by first letters" in fact and "lengths" not in fact
    assert items["photo_id"]["status"] == "partly" and "still being read" in items["photo_id"]["supports"][0]["problems"][0]
    assert "1 document is still being read" in result["summary"]


def test_an_heir_needs_the_owner_on_the_death_certificate(api, app, monkeypatch):
    SEEN["death"] = {"document_type": "death certificate", "names": ["Maria L Santos"], "issuer": "City of Daly City"}
    SEEN["wrongdeath"] = {"document_type": "death certificate", "names": ["Roberto Diaz"]}
    heir = {**CLAIMANT, "name": "Luz Villanueva", "relationship": "heir"}
    claim = open_claim(api, claimant=heir)
    add(api, app, claim["id"], "death_certificate", "wrongdeath")
    assert by_key(api.get(f"/api/claims/{claim['id']}").json())["death_certificate"]["status"] == "partly"
    add(api, app, claim["id"], "death_certificate", "death")
    claim = api.get(f"/api/claims/{claim['id']}").json()
    assert by_key(claim)["death_certificate"]["status"] == "satisfied" and claim["proof"]["record_link"] is None


# ---- the packet ------------------------------------------------------------------------------------------------

def test_the_packet_uses_the_proof_result(api, app):
    claim = open_claim(api)
    add(api, app, claim["id"], "id", "passport")
    add(api, app, claim["id"], "other", "payslip")
    stored = app.state.claims.load(claim["id"])
    result = api.get(f"/api/claims/{claim['id']}").json()["proof"]
    text = packet.build(stored, cl.checklist(stored), compress=False, proof=result).decode("latin-1")
    for expected in ("Proof file", "Proven", "Still needed", "passport.png", "What is still missing",
                     "payslip.png", "2014-03-28", "1 of 3 required items proven; not ready",
                     "genuine", packet.BANNER.upper()):
        assert expected in text, expected
    r = api.get(f"/api/claims/{claim['id']}/packet.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")


def test_names_outside_western_european_letters_are_set_in_an_embedded_font():
    def claim(name):
        return {"id": "0123456789abcdef", "record": {"owner": "NORTHFIELD UNIVERSITY", "owner_is_organisation": True,
                                                     "amount": 10.0, "holder_name": "FIRST EXAMPLE BANK"},
                "claimant": {**CLAIMANT, "name": name}, "documents": []}
    assert packet._text("María Núñez-O'Brien") == "María Núñez-O'Brien"           # Helvetica can draw these
    for name in ("Nguyễn Thị Hồng", "Łukasz Żółć", "Марія Шевченко", "Ελένη Παπαδοπούλου"):
        marked = packet._text(name)
        assert "KhutlisaSans" in marked and "?" not in marked
        made = claim(name)
        pdf = packet.build(made, cl.checklist(made), compress=False)
        assert b"NotoSans" in pdf and b"FontFile2" in pdf
    assert "?" in packet._text("\U0001F600 Maria") or "KhutlisaWide" in packet._text("\U0001F600 Maria")
    assert (packet.FONT_DIR / "OFL.txt").is_file()
