"""A wrong person must not be able to prove a claim, get it approved or get it paid.

The claimant here is a stranger to the record, or the right person with the wrong papers. The model is replaced
by a table of what it "sees"; every decision under test is code. A fake Airwallex stands behind the payouts."""
import json

import pytest
from fastapi.testclient import TestClient

from khutlisa import documents, llm, proof
from khutlisa.server import create_app, mask_name, shown_as_organisation
from test_claims import AS_PAYER, CLAIMANT, MX_BANK, PAYER_KEY, PH_BANK, World, give_bank, make_register, plan_and_agree
from test_proof import GOV, HOME, PNG, SEEN, fake_model, passport
from test_server import MARIA, ref
from test_walkthrough_fixes import sample_register

EVE = {"name": "Eve Mallory", "address": "14 Mango Avenue, Lahug, Cebu City 6000", "country": "PH",
       "email": "eve@example.org", "relationship": "self"}
# What the stand-in model reports for each made-up file. `typed*` are sheets anyone could prepare in an editor.
SEEN.update({
    "typedid": {"document_type": "identity card", "names": ["Eve Mallory"], "issuer": "Republic of Examplia",
                "presents_as_government_photo_id": True, "photo_present": False,
                "concerns": [{"kind": "not_what_it_claims",
                              "text": "Plain black text on a white background with no photograph."}]},
    "evepassport": {**passport("MALLORY", "EVE"), "names": ["Eve Mallory"]},
    "evetax": {"document_type": "tax letter", "names": ["Eve Mallory"], "issuer": "Tax Office"},
    "evebill": {"document_type": "bank statement", "names": ["Eve Mallory"], "addresses": [HOME], "issuer": "A Bank"},
    "gymcard": {"document_type": "gym membership card", "names": ["Maria L Santos"], "issuer": "A Gym"},
    "namecard": {"document_type": "membership card", "names": ["Maria Luz Santos"], "issuer": "A Club"},
    "marriage": {"document_type": "marriage certificate", "names": ["Maria Luz Santos", "Maria Luz Reyes"],
                 "issuer": "Civil Registry of Cebu City", "dates": [{"label": "date of marriage", "value": "2019-02-02"}]},
    "reyespassport": passport("REYES", "MARIA LUZ"),
    "reyestax": {"document_type": "IRS form W-8BEN", "names": ["Maria Luz Reyes"], "issuer": "Internal Revenue Service"},
    "reyesbill": {"document_type": "electricity bill", "names": ["Maria Luz Reyes"], "addresses": [HOME],
                  "issuer": "Visayan Electric"},
    "samplepassport": {**passport("DALISAY", "AMIHAN", authority="Government of the Philippines, Passport Office"),
                       "document_type": "sample passport-style identity document",
                       "names": ["Amihan Dalisay"], "marked_sample": True,
                       "concerns": [{"kind": "sample_mark", "text": "It is marked SAMPLE across the page."}]},
    "sampletax": {"document_type": "tax number letter", "names": ["Amihan Dalisay"], "marked_sample": True,
                  "issuer": "Sample Tax Office", "concerns": ["A SAMPLE watermark crosses the page."]},
    "samplebill": {"document_type": "bank statement", "names": ["Amihan Dalisay"], "addresses": [HOME],
                   "marked_sample": True, "issuer": "Visayas Sample Bank"},
    "sampleedited": {"document_type": "bank statement", "names": ["Amihan Dalisay"], "addresses": [HOME],
                     "marked_sample": True, "issuer": "Visayas Sample Bank",
                     "concerns": [{"kind": "sample_mark", "text": "Marked SAMPLE."},
                                  {"kind": "editing", "text": "The name is in a different font from the rest."}]},
})


@pytest.fixture
def app(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    world = World(tmp_path)
    world.app = create_app(db_path=world.db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no-web",
                           airwallex_factory=world.factory, payout_pause=0.0, read_documents=True,
                           payer_key=PAYER_KEY, watch_seconds=0)
    world.app.state.world = world
    return world.app


@pytest.fixture
def api(app):
    with TestClient(app, headers=AS_PAYER) as c:
        yield c


def open_claim(api, record_id="P1", claimant=CLAIMANT):
    r = api.post("/api/claims", json={"record_id": ref(api, record_id), "claimant": claimant, "history": MARIA})
    assert r.status_code == 201, r.text
    return r.json()


def add(api, claim_id, kind, word):
    r = api.post(f"/api/claims/{claim_id}/documents", data={"kind": kind},
                 files={"file": (f"{word}.png", PNG + word.encode())})
    assert r.status_code == 201, r.text
    api.app.state.reading.join()
    return api.get(f"/api/claims/{claim_id}").json()


def good_proof(api, claim_id):
    for kind, word in (("id", "passport"), ("tax_number", "w8ben"), ("proof_of_address", "homebill")):
        claim = add(api, claim_id, kind, word)
    assert claim["proof"]["ready"], claim["proof"]["reasons"]
    return claim


def approve(api, claim_id):
    return api.post(f"/api/payer/claims/{claim_id}/approve")


# ---- the tie to the record rests on government photo identification -----------------------------------------

def test_document_kinds_are_ranked_by_what_they_can_prove():
    assert documents.WEIGHT["id"] == documents.GOVERNMENT_PHOTO_ID and documents.WEIGHT["name_change"] == documents.NAME_LINK
    assert documents.WEIGHT["other"] == documents.ANYONE_COULD_MAKE_IT
    assert set(documents.WEIGHT) == set(documents.KINDS)
    assert documents.TIES_A_PERSON_TO_THE_OWNER == {documents.GOVERNMENT_PHOTO_ID, documents.NAME_LINK}


def test_typed_sheets_and_a_card_with_the_owners_name_do_not_prove_a_stranger(api):
    """Three sheets typed up in the stranger's own name and a card bearing the owner's name once gave "ready"."""
    claim = open_claim(api, claimant=EVE)
    for kind, word in (("id", "typedid"), ("tax_number", "evetax"), ("proof_of_address", "evebill"), ("other", "gymcard")):
        claim = add(api, claim["id"], kind, word)
    result = claim["proof"]
    assert result["ready"] is False and claim["state"] == "PROOF_NEEDED"
    photo = next(r for r in result["requirements"] if r["key"] == "photo_id")
    assert photo["status"] == "partly"
    problems = " ".join(photo["supports"][0]["problems"])
    assert "No photograph of the holder" in problems and "The reader questioned it" in problems
    assert result["record_link"]["status"] == "not shown"
    assert "anyone could prepare one" in result["record_link"]["text"]
    give_bank(api, claim["id"], {**MX_BANK, "first_name": "Eve", "last_name": "Mallory"})
    refused = approve(api, claim["id"])
    assert refused.status_code == 409 and "proof is not ready" in refused.json()["detail"]["message"]


def test_a_real_passport_in_the_strangers_own_name_does_not_tie_her_to_the_record_either(api):
    claim = open_claim(api, claimant=EVE)
    for kind, word in (("id", "evepassport"), ("tax_number", "evetax"), ("proof_of_address", "evebill"),
                       ("other", "namecard"), ("payslip", "payslip")):
        claim = add(api, claim["id"], kind, word)
    result = claim["proof"]
    assert result["satisfied"] == 3            # her own three papers are in order
    assert result["ready"] is False            # and still nothing ties her to the owner
    assert [g["key"] for g in result["gaps"] if g["required"]] == ["record_name"]
    assert "namecard.png" in result["record_link"]["text"] and "payslip.png" in result["record_link"]["text"]
    assert approve(api, claim["id"]).status_code == 409


def test_a_marriage_certificate_links_a_new_name_to_the_name_on_the_record(api):
    reyes = {**CLAIMANT, "name": "Maria Luz Reyes"}
    claim = open_claim(api, claimant=reyes)
    for kind, word in (("id", "reyespassport"), ("tax_number", "reyestax"), ("proof_of_address", "reyesbill")):
        claim = add(api, claim["id"], kind, word)
    assert claim["proof"]["ready"] is False and claim["proof"]["record_link"]["status"] == "not shown"
    assert "marriage certificate" in next(g for g in claim["proof"]["gaps"] if g["key"] == "record_name")["how"]
    claim = add(api, claim["id"], "other", "marriage")          # offered as "other", it links nothing
    assert claim["proof"]["ready"] is False
    claim = add(api, claim["id"], "name_change", "marriage")
    link = claim["proof"]["record_link"]
    assert claim["proof"]["ready"] is True and link["status"] == "matched"
    assert link["rests_on"] == documents.NAME_LINK and "shows both names" in link["text"]


def test_the_owners_own_passport_ties_them_directly(api):
    claim = good_proof(api, open_claim(api)["id"])
    assert claim["proof"]["record_link"]["rests_on"] == documents.GOVERNMENT_PHOTO_ID
    assert "government photo identification" in claim["proof"]["reasons"][0]


# ---- concerns block ----------------------------------------------------------------------------------------

def test_a_document_that_looks_altered_holds_the_whole_file_back_until_it_is_removed(api):
    claim = good_proof(api, open_claim(api)["id"])
    claim = add(api, claim["id"], "proof_of_address", "edited")
    assert claim["proof"]["ready"] is False
    gap = next(g for g in claim["proof"]["gaps"] if g["key"] == "concern")
    assert "edited.png" in gap["text"] and "Remove it" in gap["how"]
    doc = next(d for d in claim["documents"] if d["filename"] == "edited.png")
    removed = api.delete(f"/api/claims/{claim['id']}/documents/{doc['id']}")
    assert removed.status_code == 200 and removed.json()["proof"]["ready"] is True
    assert api.delete(f"/api/claims/{claim['id']}/documents/{doc['id']}").status_code == 404


def test_a_sample_mark_blocks_a_real_claim(api):
    claim = open_claim(api)
    claim = add(api, claim["id"], "id", "passport")
    claim = add(api, claim["id"], "tax_number", "w8ben")
    SEEN["samplehome"] = {**SEEN["homebill"], "marked_sample": True}
    claim = add(api, claim["id"], "proof_of_address", "samplehome")
    address = next(r for r in claim["proof"]["requirements"] if r["key"] == "current_address")
    assert address["status"] == "partly"
    assert "It is marked as a sample, so it cannot support a real claim." in address["supports"][0]["problems"]
    assert claim["proof"]["ready"] is False
    assert any(g["key"] == "concern" and "marked as a sample" in g["text"] for g in claim["proof"]["gaps"])


def test_on_the_sample_register_the_sample_mark_alone_is_let_through_and_nothing_else_is(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    amihan = {**CLAIMANT, "name": "Amihan Dalisay"}
    with TestClient(create_app(db_path=sample_register(tmp_path), totals_path=tmp_path / "t.json",
                               web_dist=tmp_path / "no-web", read_documents=True, payer_key=PAYER_KEY),
                    headers=AS_PAYER) as c:
        claim = c.post("/api/claims", json={"record_id": ref(c, "SAMPLE-0001"), "claimant": amihan}).json()
        for kind, word in (("id", "samplepassport"), ("tax_number", "sampletax"), ("proof_of_address", "samplebill")):
            claim = add(c, claim["id"], kind, word)
        assert claim["proof"]["ready"] is True and claim["proof"]["samples"] == 3
        assert "demonstration and not proof of a real claim" in claim["proof"]["summary"]
        claim = add(c, claim["id"], "proof_of_address", "sampleedited")
        assert claim["proof"]["ready"] is False
        assert any("different font" in g["text"] for g in claim["proof"]["gaps"] if g["key"] == "concern")


def test_the_reading_keeps_the_kind_of_each_concern(tmp_path, monkeypatch):
    path = tmp_path / "scan.png"
    path.write_bytes(PNG)
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: json.dumps(
        {"names": ["A B"], "concerns": [{"kind": "editing", "text": "Pasted area."}, "SPECIMEN across the page.",
                                        {"kind": "made_up", "text": "Something else."}],
         "presents_as_government_photo_id": True, "photo_present": "yes"}))
    reading = documents.read_document(path, "id")
    assert reading["concerns"] == ["Pasted area.", "SPECIMEN across the page.", "Something else."]
    assert reading["concern_kinds"] == ["editing", "sample_mark", "other"]
    assert reading["presents_as_government_photo_id"] is True and reading["photo_present"] is False   # only a plain true counts
    assert "presents_as_government_photo_id" in documents.READ_PROMPT and "not_what_it_claims" in documents.READ_PROMPT


# ---- the account must be the claimant's own -----------------------------------------------------------------

def test_the_bank_account_must_be_in_the_claimants_name(api):
    claim = open_claim(api)
    put = lambda **change: api.put(f"/api/claims/{claim['id']}/payee", json={**MX_BANK, **change})
    wrong = put(first_name="Eve", last_name="Mallory")
    assert wrong.status_code == 422
    assert "in the name Eve Mallory" in wrong.json()["detail"] and "Maria Luz Santos" in wrong.json()["detail"]
    assert put(first_name="Roberto").status_code == 422          # a relative with the same family name
    assert put(first_name="Mario").status_code == 422            # one letter away is another person
    assert api.get(f"/api/claims/{claim['id']}").json()["payee"] is None
    assert put().status_code == 200                               # Maria Santos
    assert put(first_name="Maria Luz").status_code == 200
    assert put(first_name="Maria L").status_code == 200


# ---- one live claim per property ----------------------------------------------------------------------------

def test_a_second_claim_on_a_property_waits_and_a_paid_property_is_never_paid_again(api):
    first = open_claim(api)
    second = open_claim(api, claimant={**CLAIMANT, "email": "second@example.org"})
    assert first["line"] == {"others": 0, "ahead": 0, "paid_elsewhere": False, "held_elsewhere": False}
    assert second["line"]["ahead"] == 1 and "waits behind" in second["history"][-2]["note"]
    for claim in (first, second):
        good_proof(api, claim["id"])
        give_bank(api, claim["id"])
    rows = {r["id"]: r for r in api.get("/api/payer/queue").json()["claims"]}
    assert rows[first["id"]]["line"]["others"] == 1 and rows[second["id"]]["line"]["ahead"] == 1

    jumped = approve(api, second["id"])
    assert jumped.status_code == 409 and "earlier claim on this property is still open" in jumped.json()["detail"]
    assert approve(api, first["id"]).status_code == 200
    held = approve(api, second["id"])
    assert held.status_code == 409 and "Only one claim on a property can be live" in held.json()["detail"]

    plan_and_agree(api, first["id"])
    api.app.state.payouts.join(first["id"])
    assert api.get(f"/api/claims/{first['id']}").json()["state"] == "PAID"
    paid = approve(api, second["id"])
    assert paid.status_code == 409 and "already been paid" in paid.json()["detail"]
    third = open_claim(api, claimant={**CLAIMANT, "email": "third@example.org"})
    assert third["line"]["paid_elsewhere"] is True
    assert len(api.app.state.world.fake.transfers) == 1


def test_when_the_first_claim_is_rejected_the_next_one_can_be_decided(api):
    first, second = open_claim(api), open_claim(api, claimant={**CLAIMANT, "email": "second@example.org"})
    good_proof(api, second["id"])
    give_bank(api, second["id"])
    assert approve(api, second["id"]).status_code == 409
    assert api.post(f"/api/payer/claims/{first['id']}/reject", json={"reason": "No documents."}).status_code == 200
    assert approve(api, second["id"]).status_code == 200


# ---- an approval covers exact terms -------------------------------------------------------------------------

def approved(api):
    claim = open_claim(api)
    good_proof(api, claim["id"])
    give_bank(api, claim["id"])
    assert approve(api, claim["id"]).status_code == 200
    return claim["id"]


def test_an_approval_needs_the_bank_account_and_records_exactly_what_it_covers(api):
    claim = open_claim(api)
    good_proof(api, claim["id"])
    early = approve(api, claim["id"])
    assert early.status_code == 409 and "bank account" in early.json()["detail"]
    give_bank(api, claim["id"])
    row = approve(api, claim["id"]).json()
    assert row["approval"]["amount"] == "1840.55" and row["approval"]["currency"] == "USD"
    assert row["approval"]["claimant_name"] == "Maria Luz Santos" and row["approval"]["documents"] == 3
    assert row["payee"]["account_number"].endswith("7771") and "002010077777777771" not in json.dumps(row)
    stored = api.app.state.claims.load(claim["id"])
    terms = stored["approval"]["terms"]
    assert terms["payee_hash"] == stored["payee"]["hash"] and len(terms["payee_hash"]) == 64
    assert terms["documents"] == {d["id"]: d["sha256"] for d in stored["documents"]}
    assert all(len(h) == 64 for h in terms["documents"].values()) and len(stored["approval"]["terms_hash"]) == 64
    assert "paid_by" not in terms and terms["payee_currency"] == "MXN"
    assert "1840.55 USD to the bank account on file" in stored["history"][-1]["note"]


@pytest.mark.parametrize("change, because", [
    ("add", "a document was added"), ("remove", "a document the approval relied on was removed"),
    ("payee", "the bank account to be paid was changed")])
def test_any_change_after_approval_withdraws_it_and_nothing_can_be_paid_until_a_new_one(api, change, because):
    claim_id = approved(api)
    if change == "add":
        add(api, claim_id, "payslip", "payslip")
    elif change == "remove":
        doc = api.get(f"/api/claims/{claim_id}").json()["documents"][0]
        assert api.delete(f"/api/claims/{claim_id}/documents/{doc['id']}").status_code == 200
    else:
        give_bank(api, claim_id, PH_BANK)
    claim = api.get(f"/api/claims/{claim_id}").json()
    assert claim["approval"] is None and claim["state"] != "APPROVED"
    assert because in claim["approvals_withdrawn"][0]["because"]
    assert "approval no longer holds" in claim["history"][-1]["note"] or "approval no longer holds" in claim["history"][-2]["note"]
    assert api.post(f"/api/claims/{claim_id}/payout/plan", json={}).status_code == 409
    row = next(r for r in api.get("/api/payer/queue").json()["claims"] if r["id"] == claim_id)
    assert row["can_decide"] is True and row["approval"] is None
    if change == "remove":          # the proof is no longer complete, so it cannot simply be approved again
        assert approve(api, claim_id).status_code == 409
    else:
        assert approve(api, claim_id).status_code == 200
        assert api.post(f"/api/claims/{claim_id}/payout/plan", json={}).status_code == 200


def test_a_plan_made_for_one_account_cannot_be_agreed_after_the_account_changes(api):
    claim_id = approved(api)
    plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
    give_bank(api, claim_id, PH_BANK)
    stale = api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]})
    assert stale.status_code == 409
    assert not api.app.state.world.fake.deposits and api.get(f"/api/claims/{claim_id}").json()["state"] != "PAYING"


def test_a_tampered_claim_file_is_caught_when_the_payment_is_about_to_start(api):
    claim_id = approved(api)
    plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
    store = api.app.state.claims
    claim = store.load(claim_id)
    claim["record"]["amount"] = 9999.0          # someone edits the amount behind the approval's back
    store.save(claim)
    r = api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]})
    assert r.status_code == 409 and "9999.00 USD, and 1840.55 USD was approved" in r.json()["detail"]
    assert store.load(claim_id)["approval"] is None and not api.app.state.world.fake.deposits


# ---- the payer's routes need a key --------------------------------------------------------------------------

def test_the_payer_routes_need_the_key_and_the_claim_routes_do_not(app):
    with TestClient(app) as anyone:
        claim = anyone.post("/api/claims", json={"record_id": ref(anyone, "P1"), "claimant": CLAIMANT}).json()
        assert anyone.get(f"/api/claims/{claim['id']}").status_code == 200          # whoever holds the number
        for method, path, body in (("get", "/api/payer/queue", None), ("get", "/api/payer/results", None),
                                   ("post", f"/api/payer/claims/{claim['id']}/approve", None),
                                   ("post", f"/api/payer/claims/{claim['id']}/reject", {"reason": "No."})):
            call = getattr(anyone, method)
            no_key = call(path, json=body) if body else call(path)
            assert no_key.status_code == 401 and "holder's key" in no_key.json()["detail"]
            wrong = call(path, json=body, headers={"X-Payer-Key": "guess"}) if body else call(path, headers={"X-Payer-Key": "guess"})
            assert wrong.status_code == 401
        assert anyone.get(f"/api/claims/{claim['id']}").json()["state"] == "PROOF_NEEDED"   # nothing was decided
        assert anyone.get("/api/payer/queue", headers=AS_PAYER).status_code == 200


def test_with_no_key_set_the_payer_routes_stay_locked(tmp_path, monkeypatch):
    monkeypatch.delenv("KHUTLISA_PAYER_KEY", raising=False)
    db = make_register(tmp_path)
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "t.json", web_dist=tmp_path / "no-web")) as c:
        r = c.get("/api/payer/queue", headers={"X-Payer-Key": ""})
        assert r.status_code == 401 and "KHUTLISA_PAYER_KEY" in r.json()["detail"]


# ---- privacy -----------------------------------------------------------------------------------------------

def test_an_address_is_confirmed_only_by_the_house_number_with_most_of_the_street_name():
    record = "1482 WINDROSE LANE APT 7"
    for piece in ("1482", "WINDROSE", "APT 7", "LANE", "1482 LANE", "1483 WINDROSE LANE", "WINDROSE LANE"):
        assert proof.street_agrees(piece, record) is False, piece
    assert proof.street_agrees("1482 Windrose Lane", record) and proof.street_agrees("1482 Windrose Ln Apt 7", record)
    assert proof.street_agrees("1482 Windrose", record)
    long = "77 OLD HOLLYHOCK HILL TERRACE"
    assert proof.street_agrees("77 Hollyhock Hill", long) and not proof.street_agrees("77 Hollyhock", long)
    part = {"street": "1482", "city": "Daly City", "region": "CA", "postcode": "94015"}
    full_record = {"owner_street": record, "owner_city": "DALY CITY", "owner_region": "CA", "owner_postcode": "94015"}
    assert "street" not in proof.address_against_record(part, full_record)


def test_the_registers_own_property_number_never_reaches_a_browser(api):
    claim = good_proof(api, open_claim(api)["id"])
    give_bank(api, claim["id"])
    approve(api, claim["id"])
    plan_and_agree(api, claim["id"])
    api.app.state.payouts.join(claim["id"])
    replies = [api.get(f"/api/claims/{claim['id']}"), api.get("/api/payer/queue"), api.post("/api/search", json=MARIA),
               api.get(f"/api/claims/{claim['id']}/payout"), api.get("/api/organisations", params={"q": "northfield"})]
    for r in replies:
        assert r.status_code == 200
        found = json.loads(r.text)
        flat = json.dumps(found)
        for number in ("P1", "P2", "P3", "P4", "O1", "O2"):
            assert f'"{number}"' not in flat, f"{number} left the API in {r.request.url.path}"
    assert claim["record"]["record_id"].startswith("k") and "property" not in claim
    # The claim file on the server does keep it, which is how one property is tied to one live claim.
    assert api.app.state.claims.load(claim["id"])["property"] == {"source": "TEST", "record_id": "P1"}


def test_the_packet_gives_the_property_number_only_once_the_proof_is_ready(api, monkeypatch):
    from khutlisa import claims as cl, packet
    given = []
    real = packet.build
    monkeypatch.setattr(packet, "build", lambda *a, **kw: given.append(kw.get("property_number")) or real(*a, **kw))
    claim = open_claim(api)
    assert api.get(f"/api/claims/{claim['id']}/packet.pdf").status_code == 200 and given == [None]
    good_proof(api, claim["id"])
    assert api.get(f"/api/claims/{claim['id']}/packet.pdf").status_code == 200 and given == [None, "P1"]
    stored = api.app.state.claims.load(claim["id"])
    without = real(stored, cl.checklist(stored), compress=False).decode("latin-1")
    assert "Given once the proof file is ready" in without and "(P1)" not in without
    assert "(P1)" in real(stored, cl.checklist(stored), compress=False, property_number="P1").decode("latin-1")


def test_an_owner_that_carries_a_persons_name_is_masked_like_a_person():
    for name in ("JOHN SMITH MD INC", "JOHN A SMITH DDS INC", "ESTATE OF MARY JONES", "ESTATE OF MARY JONES INC",
                 "THE GARCIA FAMILY TRUST", "SMITH FAMILY TRUST LLC", "ROBERT LEE IRA", "FBO MARIA SANTOS CO",
                 "JOHN SMITH INC", "MARIA SANTOS LLC", "JOHN SMITH GROUP", "J SMITH CORP", "LAW OFFICES OF PEDRO REYES INC"):
        assert not shown_as_organisation(name), name
    for name in ("NORTHFIELD UNIVERSITY", "SANTOS TRUCKING INC", "BANK OF EXAMPLE", "RIVERBEND MEDICAL GROUP",
                 "ACME PAYROLL INC", "WELLS FARGO BANK", "KAISER FOUNDATION HOSPITALS", "CITY OF FRESNO", "ACME INC"):
        assert shown_as_organisation(name), name
    assert mask_name("JOHN SMITH MD INC") == "J··· S··· M··· I···"
