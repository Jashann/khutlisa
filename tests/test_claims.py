"""Claims, the packet, the payout and the payer's view, against a made-up register and a fake Airwallex.

Nothing here touches the network or the real register.
"""
import json

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import airwallex as awx
from khutlisa import california, claims as cl, documents, packet
from khutlisa.names import normalise, phonetic
from khutlisa.server import MASK_DOT, MASK_DOTS, create_app, mask_name
from test_airwallex import FakeAirwallex, make_client
from test_server import MARIA, ORGS, PEOPLE, TOTALS, ref

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64
CLAIMANT = {"name": "Maria Luz Santos", "address": "14 Mango Avenue, Lahug, Cebu City 6000", "country": "PH",
            "email": "maria@example.org", "relationship": "self"}
MX_BANK = {"currency": "MXN", "first_name": "Maria", "last_name": "Santos", "account_number": "002010077777777771",
           "street_address": "Avenida Reforma 100", "city": "Ciudad de Mexico", "postcode": "06600",
           "state": "MX-CMX"}
# Words that exist only in the made-up register's private names and streets. None may ever leave the server.
PH_BANK = {"currency": "PHP", "first_name": "Maria", "last_name": "Santos", "account_number": "1234567890",
           "swift_code": "BOPIPHMM", "street_address": "123 Ayala Avenue", "city": "Makati", "postcode": "1226"}
PAYER_KEY = "test-payer-key"
AS_PAYER = {"X-Payer-Key": PAYER_KEY}
PRIVATE = ["QUIXOTIC", "WINDROSE", "HOLLYHOCK", "ZARAGOZANA", "ROSALIND", "MAPLETHORPE", "ELEANOR", "QUILLWORT"]


def make_register(folder):
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
    (folder / "totals.json").write_text(json.dumps(TOTALS))
    return db


class World:
    """One app over a temporary folder, with a fake Airwallex behind it."""

    def __init__(self, folder, with_keys=True):
        self.folder = folder
        self.db = folder / "registers.duckdb"
        if not self.db.exists():
            make_register(folder)
        self.fake = FakeAirwallex()
        self.with_keys = with_keys
        self.app = self.make_app()

    def factory(self):
        if not self.with_keys:
            raise awx.CredentialsError("missing AWX_CLIENT_ID, AWX_API_KEY")
        client = make_client(self.fake)
        return client, awx.SandboxSimulator(client)

    def make_app(self):
        return create_app(db_path=self.db, totals_path=self.folder / "totals.json", web_dist=self.folder / "no-web",
                          airwallex_factory=self.factory, payout_pause=0.0, payer_key=PAYER_KEY, watch_seconds=0)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture
def api(world):
    # The payer's key rides along on every request of these tests; the claim routes ignore it.
    with TestClient(world.app, headers=AS_PAYER) as c:
        yield c


def open_claim(api, record_id="P1", claimant=CLAIMANT, history=MARIA, **extra):
    """Opens a claim on a row of the made-up register. The API takes our own id for the row, never the
    register's number, so the number used here is turned into that id first."""
    r = api.post("/api/claims", json={"record_id": ref(api, record_id), "claimant": claimant, "history": history,
                                      **extra})
    assert r.status_code == 201, r.text
    return r.json()


def give_bank(api, claim_id, bank=MX_BANK):
    r = api.put(f"/api/claims/{claim_id}/payee", json=bank)
    assert r.status_code == 200, r.text
    return r.json()


def plan_and_agree(api, claim_id, what_if=None):
    """The claimant asks for the payout plan and agrees to it, which starts the payment."""
    plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={"what_if": what_if})
    assert plan.status_code == 200, plan.text
    r = api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan.json()["plan"]["id"]})
    assert r.status_code == 200, r.text
    return r.json()


def add(api, claim_id, kind, data=PNG, name="scan.png"):
    return api.post(f"/api/claims/{claim_id}/documents", data={"kind": kind}, files={"file": (name, data)})


def complete_proof(api, claim):
    for item in claim["checklist"]["items"]:
        if item["required"]:
            r = add(api, claim["id"], item["kinds"][0])
            assert r.status_code == 201, r.text
    return api.get(f"/api/claims/{claim['id']}").json()


# ---- claims ------------------------------------------------------------------------------------------------

def test_a_new_claim_starts_found_then_proof_needed_and_is_stored_as_a_file(api, world):
    claim = open_claim(api)
    assert claim["state"] == "PROOF_NEEDED"
    assert [e["state"] for e in claim["history"]] == ["FOUND", "PROOF_NEEDED"]
    assert all(e["at"] and e["note"] for e in claim["history"])
    assert claim["record"]["amount"] == 1840.55 and claim["claimant"] == CLAIMANT
    assert (world.folder / "claims" / f"{claim['id']}.json").is_file()
    assert api.get(f"/api/claims/{claim['id']}").json()["id"] == claim["id"]


def test_a_claim_never_holds_the_private_owners_name_or_street(api, world):
    # P2's owner has a name the claimant never gave (QUIXOTIC) and a street they never gave.
    claim = open_claim(api, "P2")
    assert claim["record"]["owner"] == mask_name("SANTOS MARIA QUIXOTIC")
    assert "owner_street" not in claim["record"] and "owner_name" not in claim["record"]
    on_disk = (world.folder / "claims" / f"{claim['id']}.json").read_text()
    # The claim keeps the street the claimant typed with their history (WINDROSE, in their own words) so that
    # it can be compared later. Nothing from the record itself may be there.
    typed = json.dumps(MARIA).upper()
    assert claim["address_given"] == [{"street": "1482 Windrose Lane Apt 7", "city": "Daly City", "region": "CA",
                                       "postcode": "94015"}]
    for text in (json.dumps(claim), on_disk, api.get(f"/api/claims/{claim['id']}").text):
        for word in PRIVATE:
            assert word in typed or word not in text.upper()
    assert claim["match"]["score"] > 0 and claim["match"]["reasons"]


def test_an_organisation_owner_is_named_and_gets_the_business_checklist(api):
    claim = open_claim(api, "O2", history=None)
    assert claim["record"]["owner"] == "NORTHFIELD UNIVERSITY" and claim["match"] is None
    keys = [i["key"] for i in claim["checklist"]["items"]]
    assert "authority" in keys and claim["checklist"]["notary"]["required"] is True


def test_owner_shown_picks_the_right_owner_when_a_record_number_is_shared(tmp_path):
    db = make_register(tmp_path)
    con = duckdb.connect(str(db))
    con.execute("insert into records select source, 'P1', 'VILLANUEVA LUZ', 'VILLANUEVA LUZ', owner_street, owner_city,"
                " owner_region, owner_postcode, owner_country, 9999.0, currency, holder_name, '', '', property_type,"
                " phon_first, phon_last from records where record_id = 'P4'")
    con.close()
    with TestClient(World(tmp_path).app) as api:
        # Each owner's row has its own id of ours, so the claim lands on the right owner without the browser
        # ever holding the register's number or the full name.
        mine, theirs = ref(api, "P1", "SANTOS MARIA L"), ref(api, "P1", "VILLANUEVA LUZ")
        assert mine != theirs and "P1" not in (mine, theirs)
        claim = api.post("/api/claims", json={"record_id": mine, "claimant": CLAIMANT}).json()
        assert claim["record"]["amount"] == 1840.55 and claim["record"]["owner"] == mask_name("SANTOS MARIA L")
        other = api.post("/api/claims", json={"record_id": theirs, "claimant": CLAIMANT}).json()
        assert other["record"]["amount"] == 9999.0 and other["record"]["owner"] == mask_name("VILLANUEVA LUZ")


def test_bad_claims_are_refused(api):
    assert api.post("/api/claims", json={"record_id": "NOPE", "claimant": CLAIMANT}).status_code == 404
    # The register's own number is not an address into the API.
    assert api.post("/api/claims", json={"record_id": "P1", "claimant": CLAIMANT}).status_code == 404
    for change in ({"email": "not an email"}, {"country": "XX"}, {"relationship": "friend"}, {"name": ""}):
        r = api.post("/api/claims", json={"record_id": "P1", "claimant": {**CLAIMANT, **change}})
        assert r.status_code == 422
    for bad in ("../../etc/passwd", "zzzz", "0" * 15, "..%2F..%2Fx"):
        assert api.get(f"/api/claims/{bad}").status_code == 404


def test_documents_fill_the_checklist_and_move_the_claim_on(api, world):
    claim = open_claim(api)
    need = claim["checklist"]
    assert need["attached"] == 0 and need["required"] == 3 and not need["complete"]
    assert {i["status"] for i in need["items"]} == {"still needed"}

    claim = add(api, claim["id"], "id", PNG, "../../passport page.png").json()
    doc = claim["documents"][0]
    assert doc["kind"] == "id" and doc["reading"] == {"status": "not_read"} and "stored_as" not in doc
    assert "/" not in doc["filename"] and claim["state"] == "PROOF_NEEDED"
    stored = list((world.folder / "claims" / claim["id"]).iterdir())
    assert len(stored) == 1 and stored[0].suffix == ".png" and stored[0].read_bytes() == PNG
    by_key = {i["key"]: i for i in claim["checklist"]["items"]}
    assert by_key["photo_id"]["status"] == "attached" and by_key["current_address"]["status"] == "still needed"
    assert "Proof of your current mailing address" in claim["checklist"]["missing"]

    add(api, claim["id"], "tax_number", PDF, "w8ben.pdf")
    claim = add(api, claim["id"], "proof_of_address").json()
    assert claim["checklist"]["complete"] and claim["state"] == "PROOF_READY"
    # A lease or payslip ties the claimant to the old address. It is asked for but does not block the packet.
    claim = add(api, claim["id"], "lease").json()
    assert {i["key"]: i for i in claim["checklist"]["items"]}["reported_address"]["status"] == "attached"


def test_uploads_that_are_not_photos_or_pdfs_are_refused(api):
    claim = open_claim(api)
    assert add(api, claim["id"], "id", b"<html>hello</html>", "page.png").status_code == 415
    assert add(api, claim["id"], "id", b"", "empty.png").status_code == 422
    assert add(api, claim["id"], "selfie").status_code == 422
    assert add(api, "0123456789abcdef", "id").status_code == 404
    assert api.get(f"/api/claims/{claim['id']}").json()["documents"] == []


def test_read_document_is_a_marked_placeholder(tmp_path):
    assert documents.read_document(tmp_path / "anything.png") == {"status": "not_read"}
    assert "status" in documents.read_document.__doc__ and "tamper_flags" in documents.read_document.__doc__


def test_the_claimant_marks_the_claim_as_sent_only_after_the_packet(api):
    claim = open_claim(api)
    assert api.post(f"/api/claims/{claim['id']}/filed").status_code == 409
    complete_proof(api, claim)
    assert api.get(f"/api/claims/{claim['id']}/packet.pdf").status_code == 200
    assert api.get(f"/api/claims/{claim['id']}").json()["state"] == "PACKET_READY"
    filed = api.post(f"/api/claims/{claim['id']}/filed").json()
    assert filed["state"] == "FILED"
    assert [e["state"] for e in filed["history"] if e["state"] != "PROOF_NEEDED"][-3:] == [
        "PROOF_READY", "PACKET_READY", "FILED"]


# ---- California's rules and the packet -----------------------------------------------------------------------

def test_notary_rule_follows_the_thousand_dollar_line_and_the_property_type():
    assert california.notary_rule(999.99, "MS01: WAGES, PAYROLL, SALARIES")["required"] is False
    assert california.notary_rule(1000.00, "MS01: WAGES, PAYROLL, SALARIES")["required"] is True
    assert california.notary_rule(5.00, "SD01: SAFE DEPOSIT BOX CONTENTS")["required"] is True
    assert california.notary_rule(5.00, "SC08: SHARES OF STOCK (RTRNED BY PO)")["required"] is True
    assert california.notary_rule(5.00, "SC01: DIVIDENDS")["required"] is False


def test_an_heir_is_asked_for_the_death_certificate_and_proof_of_inheritance(api):
    claim = open_claim(api, claimant={**CLAIMANT, "relationship": "heir"})
    keys = [i["key"] for i in claim["checklist"]["items"] if i["required"]]
    assert keys == ["photo_id", "tax_number", "current_address", "death_certificate", "heirship"]
    abroad = " ".join(s["detail"] for s in claim["checklist"]["signing"])
    assert "outside the United States" in abroad and "Each heir signs" in abroad
    assert all(s["url"].startswith("https://") for s in claim["checklist"]["sources"])


def test_the_packet_is_a_pdf_marked_as_not_filed(api):
    claim = open_claim(api, "P2")
    r = api.get(f"/api/claims/{claim['id']}/packet.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and len(r.content) > 5000
    assert "attachment" in r.headers["content-disposition"]
    # Downloading an incomplete packet is allowed and does not pretend the proof is ready.
    assert api.get(f"/api/claims/{claim['id']}").json()["state"] == "PROOF_NEEDED"


def test_the_packet_text_carries_the_claimants_details_but_never_the_private_owner(api, world):
    claim = open_claim(api, "P2")
    add(api, claim["id"], "id", PNG, "passport.png")
    stored = world.app.state.claims.load(claim["id"])
    text = packet.build(stored, cl.checklist(stored), compress=False).decode("latin-1")
    assert packet.BANNER == "Prepared by Khutlisa for the claimant to review and sign; not filed"
    assert packet.BANNER.upper() in text
    for expected in ("Maria Luz Santos", "maria@example.org", "Philippines", "PACIFIC GAS AND ELECTRIC", "US$320.10",
                     "Still needed", "Attached", "passport.png", "P.O. Box 942850", "Khutlisa never signs"):
        assert expected in text, expected
    for word in PRIVATE:
        assert word not in text.upper()
    # the masked name: a first letter and the same few middle dots for every word, whatever its length
    assert "Q" + "\\267" * MASK_DOTS in text and "Q" + "\\267" * (MASK_DOTS + 1) not in text


# ---- the payer's view ------------------------------------------------------------------------------------------

def test_the_payer_queue_masks_the_owner_and_shows_proof_reasons_and_doubts(api):
    person = open_claim(api, "P2")
    org = open_claim(api, "O2", history=None)
    add(api, person["id"], "id")
    r = api.get("/api/payer/queue")
    assert r.status_code == 200
    for word in PRIVATE:
        assert word not in r.text.upper()
    rows = {row["id"]: row for row in r.json()["claims"]}
    row = rows[person["id"]]
    assert row["owner"] == mask_name("SANTOS MARIA QUIXOTIC") and row["owner_is_organisation"] is False
    assert row["state"] == "PROOF_NEEDED" and row["amount"] == 320.10
    assert row["proof"] == {"required": 3, "attached": 1, "complete": False, "documents": 1,
                            "missing": row["proof"]["missing"]} and len(row["proof"]["missing"]) == 2
    assert row["reasons"] and row["doubts"] and row["match"]["score"] > 0
    assert any("name they did not give" in d for d in row["doubts"])
    assert row["claimant"] == {"name": "Maria Luz Santos", "country": "PH", "relationship": "self"}
    assert rows[org["id"]]["owner"] == "NORTHFIELD UNIVERSITY" and rows[org["id"]]["reasons"] == []


def test_approve_and_reject_move_the_claim_and_leave_a_dated_event(api):
    first, second = open_claim(api), open_claim(api, "P4")
    give_bank(api, first["id"])
    approved = api.post(f"/api/payer/claims/{first['id']}/approve").json()
    assert approved["state"] == "APPROVED" and approved["can_decide"] is False
    events = api.get(f"/api/claims/{first['id']}").json()["history"]
    assert events[-1]["state"] == "APPROVED" and "approved" in events[-1]["note"] and events[-1]["at"]

    assert api.post(f"/api/payer/claims/{second['id']}/reject", json={"reason": ""}).status_code == 422
    rejected = api.post(f"/api/payer/claims/{second['id']}/reject",
                        json={"reason": "The address on the bill does not match."}).json()
    assert rejected["state"] == "REJECTED" and rejected["rejection_reason"] == "The address on the bill does not match."
    claim = api.get(f"/api/claims/{second['id']}").json()
    assert claim["history"][-1]["state"] == "REJECTED" and "does not match" in claim["history"][-1]["note"]

    # A decision is made once.
    assert api.post(f"/api/payer/claims/{first['id']}/reject", json={"reason": "Changed my mind."}).status_code == 409
    assert api.post(f"/api/payer/claims/{second['id']}/approve").status_code == 409
    assert api.post("/api/payer/claims/0123456789abcdef/approve").status_code == 404


def test_results_count_each_stage_and_give_the_median_time_between_them():
    def claim(amount, *events):
        return {"state": events[-1][0], "record": {"amount": amount},
                "history": [{"state": s, "at": f"2026-11-11T10:{m:02d}:00+00:00", "note": ""} for s, m in events]}
    out = cl.results([
        claim(100.0, ("FOUND", 0), ("PROOF_NEEDED", 0), ("PROOF_READY", 10), ("PACKET_READY", 11), ("FILED", 30),
              ("APPROVED", 40), ("PAYING", 41), ("PAID", 42)),
        claim(50.0, ("FOUND", 0), ("PROOF_NEEDED", 0), ("PROOF_READY", 20)),
        claim(25.0, ("FOUND", 0), ("PROOF_NEEDED", 0), ("REJECTED", 5)),
    ])
    assert {s["stage"]: (s["count"], s["amount"]) for s in out["stages"]} == {
        "found": (3, 175.0), "proven": (2, 150.0), "filed": (1, 100.0), "approved": (1, 100.0), "paid": (1, 100.0)}
    medians = {(m["from"], m["to"]): (m["median_seconds"], m["claims"]) for m in out["medians"]}
    assert medians == {("found", "proven"): (900.0, 2), ("proven", "filed"): (1200.0, 1),
                       ("filed", "approved"): (600.0, 1), ("approved", "paid"): (120.0, 1)}
    assert out["rejected"] == 1 and out["claims"] == 3
    assert cl.results([])["medians"][0]["median_seconds"] is None


def test_the_results_endpoint_follows_the_claims(api):
    claim = open_claim(api)
    give_bank(api, claim["id"])
    api.post(f"/api/payer/claims/{claim['id']}/approve")
    stages = {s["stage"]: s for s in api.get("/api/payer/results").json()["stages"]}
    assert stages["found"]["count"] == 1 and stages["approved"] == {"stage": "approved", "count": 1, "amount": 1840.55}
    assert stages["paid"]["count"] == 0


# ---- payout --------------------------------------------------------------------------------------------------

def approved_claim(api, record_id="P1", bank=MX_BANK):
    """A claim with the bank account on file and the payer's approval of exactly that."""
    claim = open_claim(api, record_id)
    give_bank(api, claim["id"], bank)
    r = api.post(f"/api/payer/claims/{claim['id']}/approve")
    assert r.status_code == 200, r.text
    return claim["id"]


def test_the_bank_account_is_checked_when_it_is_given_and_nothing_moves_before_approval(api, world):
    claim = open_claim(api)
    view = api.get(f"/api/claims/{claim['id']}/payout").json()
    assert view["started"] is False and view["state"] is None and view["environment"] == "Airwallex sandbox"
    assert [s["done"] for s in view["journey"]] == [False] * 6
    put = lambda **change: api.put(f"/api/claims/{claim['id']}/payee", json={**MX_BANK, **change})
    bad = put(account_number="002010077777777772")
    assert bad.status_code == 422 and "CLABE" in bad.json()["detail"]
    assert put(currency="EUR").status_code == 422
    no_swift = put(currency="PHP", account_number="1234567890")
    assert no_swift.status_code == 422 and "swift" in no_swift.json()["detail"].lower()
    assert api.get(f"/api/claims/{claim['id']}").json()["payee"] is None

    shown = give_bank(api, claim["id"])["payee"]
    assert shown["account_name"] == "Maria Santos" and shown["account_number"] == MASK_DOT * 14 + "7771"
    assert "Airwallex" in shown["checked_by"] and "002010077777777771" not in json.dumps(shown)
    # Bank details alone start nothing: no plan and no payment before the payer has approved.
    assert api.post(f"/api/claims/{claim['id']}/payout/plan", json={}).status_code == 409
    assert api.post(f"/api/claims/{claim['id']}/payout/confirm", json={"plan_id": "0" * 36}).status_code == 409
    assert not world.app.state.claims.payout_path(claim["id"]).exists()
    assert world.fake.count("POST", "/api/v1/simulation/deposit/create") == 0


def test_a_payout_runs_to_paid_and_reports_every_figure(api, world):
    claim_id = approved_claim(api)
    plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()
    assert plan["state"] == "PLANNED" and plan["started"] is False and plan["claim_state"] == "APPROVED"
    assert plan["plan"]["route"] == "convert_then_pay" and plan["plan"]["expected_local"]["currency"] == "MXN"
    assert world.fake.count("POST", "/api/v1/simulation/deposit/create") == 0      # a plan moves no money
    r = api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["plan"]["id"]})
    assert r.status_code == 200 and r.json()["started"] is True
    world.app.state.payouts.join(claim_id)

    view = api.get(f"/api/claims/{claim_id}/payout").json()
    assert view["state"] == "PAID" and view["claim_state"] == "PAID" and view["running"] is False
    assert view["problem"] is None and view["environment"] == "Airwallex sandbox"
    assert [s["key"] for s in view["journey"]] == ["arrived", "fee", "rate_locked", "converted", "sent", "paid"]
    assert "Khutlisa's Airwallex US dollar account" in view["journey"][0]["label"]
    assert "in your name" not in json.dumps(view)
    assert all(s["done"] and s["at"] for s in view["journey"])
    assert [s["state"] for s in view["steps"]] == ["DEPOSIT_EXPECTED", "DEPOSIT_CONFIRMED", "CONVERTED",
                                                   "BENEFICIARY_READY", "TRANSFER_CREATED", "SENT", "PAID"]
    assert view["deposit"]["amount"] == "1840.55" and view["deposit"]["reference"] == f"KHUTLISA-{claim_id}"
    assert view["incoming_fee"] == {"amount": "0.00", "currency": "USD"}
    assert view["after_fee"] == {"amount": "1840.55", "currency": "USD"}
    assert view["rate"] == 18.5 and view["local"] == {"amount": "34050.17", "currency": "MXN"}
    assert view["received"] == {"amount": "34050.17", "currency": "MXN"}
    assert view["payout_fee"] == {"amount": "0.0", "currency": "MXN", "paid_by": "BENEFICIARY"}
    assert view["left_wallet"] == {"amount": "34050.17", "currency": "MXN"}     # pesos are labelled as pesos
    assert view["transfer_status"] == "PAID" and view["transfer_id"] == view["proof"]["transfer"]["id"]
    assert view["proof"]["financial_transactions"][0]["source_id"] == view["transfer_id"]
    assert view["reconciliation"]["balanced"] is True and len(view["reconciliation"]["lines"]) == 4
    assert view["account"] == {"name": "Maria Santos", "number": MASK_DOT * 14 + "7771", "country": "MX",
                               "currency": "MXN"}
    assert "002010077777777771" not in json.dumps({k: v for k, v in view.items() if k != "proof"})

    claim = api.get(f"/api/claims/{claim_id}").json()
    assert [e["state"] for e in claim["history"]][-3:] == ["APPROVED", "PAYING", "PAID"]
    assert view["transfer_id"] in claim["history"][-1]["note"]
    paid = {s["stage"]: s["count"] for s in api.get("/api/payer/results").json()["stages"]}["paid"]
    assert paid == 1


def test_asking_twice_never_makes_a_second_payout(api, world):
    claim_id = approved_claim(api)
    started = plan_and_agree(api, claim_id)
    world.app.state.payouts.join(claim_id)
    first = json.loads(world.app.state.claims.payout_path(claim_id).read_text())
    # Asking for a plan again, agreeing again, or trying to point it at another account changes nothing.
    again = api.post(f"/api/claims/{claim_id}/payout/plan", json={})
    assert again.status_code == 200 and again.json()["state"] == "PAID" and again.json()["local"]["currency"] == "MXN"
    assert api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": started["plan"]["id"]}).json()["state"] == "PAID"
    assert api.put(f"/api/claims/{claim_id}/payee", json=PH_BANK).status_code == 409
    world.app.state.payouts.join(claim_id)
    second = json.loads(world.app.state.claims.payout_path(claim_id).read_text())
    assert second["payout_id"] == first["payout_id"] and second["transfer_id"] == first["transfer_id"]
    assert world.fake.count("POST", "/api/v1/transfers/create") == 1
    assert world.fake.count("POST", "/api/v1/simulation/deposit/create") == 1
    assert len(world.fake.transfers) == 1


def test_a_philippine_payout_converts_inside_the_transfer(api, world):
    claim = open_claim(api, "P4", claimant={**CLAIMANT, "name": "Luz Villanueva"})
    body = {**PH_BANK, "first_name": "Luz", "last_name": "Villanueva", "swift_code": "bopiphmm", "state": ""}
    give_bank(api, claim["id"], body)
    assert api.post(f"/api/payer/claims/{claim['id']}/approve").status_code == 200
    claim_id = claim["id"]
    plan_and_agree(api, claim_id)
    world.app.state.payouts.join(claim_id)
    view = api.get(f"/api/claims/{claim_id}/payout").json()
    assert view["state"] == "PAID" and view["local"] == {"amount": "35380.00", "currency": "PHP"}
    assert view["route"] == "pay_with_quote" and view["left_wallet"] == {"amount": "610.0", "currency": "USD"}
    at = {s["state"]: s["at"] for s in view["steps"]}
    journey = {s["key"]: s["at"] for s in view["journey"]}
    assert journey["rate_locked"] == at["CONVERTED"] and journey["converted"] == at["TRANSFER_CREATED"]
    assert world.fake.count("POST", "/api/v1/fx/conversions/create") == 0


def test_a_restart_resumes_the_same_payout_and_pays_once(world):
    with TestClient(world.app, headers=AS_PAYER) as api:
        claim_id = approved_claim(api)
    store = world.app.state.claims
    # The state a crash would leave: the claim is PAYING and the payout file is part of the way through.
    store.move(claim_id, (cl.APPROVED,), cl.PAYING, "Payout started.", "not approved")
    payout = awx.Payout.open(store.payout_path(claim_id), usd_amount="1840.55", target_currency="MXN",
                             deposit_reference=f"KHUTLISA-{claim_id}", beneficiary=awx.EXAMPLE_BENEFICIARIES["MXN"])
    client = make_client(world.fake)
    simulator = awx.SandboxSimulator(client)
    while payout.state != awx.TRANSFER_CREATED:
        awx.advance(payout, client, simulator)
    assert world.fake.count("POST", "/api/v1/transfers/create") == 1

    restarted = world.make_app()
    with TestClient(restarted) as api:
        restarted.state.payouts.join(claim_id)
        view = api.get(f"/api/claims/{claim_id}/payout").json()
        assert view["state"] == "PAID" and view["claim_state"] == "PAID"
        assert view["transfer_id"] == payout.transfer_id
    assert json.loads(store.payout_path(claim_id).read_text())["payout_id"] == payout.payout_id
    assert world.fake.count("POST", "/api/v1/transfers/create") == 1
    assert world.fake.count("POST", "/api/v1/simulation/deposit/create") == 1
    assert world.fake.count("POST", "/api/v1/fx/conversions/create") == 1


def test_a_failed_transfer_is_reported_and_not_retried(api, world):
    world.fake.sent_becomes = "FAILED"
    claim_id = approved_claim(api)
    plan_and_agree(api, claim_id)
    world.app.state.payouts.join(claim_id)
    view = api.get(f"/api/claims/{claim_id}/payout").json()
    assert view["state"] == "FAILED" and "Invalid account" in view["failure"]
    # The claim does not sit in "paying" for ever: it is on hold, and the screen says what is needed next.
    assert view["claim_state"] == "PAYMENT_HELD" and view["hold"]["kind"] == "transfer_failed"
    assert view["hold"]["needs"] == ["bank_details", "payer", "claimant"] and view["attempts"][0]["status"] == "FAILED"
    assert [s["done"] for s in view["journey"]] == [True, True, True, True, False, False]
    assert world.fake.count("POST", "/api/v1/transfers/create") == 1


def test_missing_keys_give_a_clear_message_and_start_nothing(tmp_path):
    world = World(tmp_path, with_keys=False)
    with TestClient(world.app, headers=AS_PAYER) as api:
        claim_id = approved_claim(api)      # the bank details are checked by our own rules when Airwallex is out of reach
        assert "Khutlisa's own checks" in api.get(f"/api/claims/{claim_id}").json()["payee"]["checked_by"]
        view = api.get(f"/api/claims/{claim_id}/payout").json()
        assert view["credentials_ready"] is False and "AWX_CLIENT_ID" in view["problem"]
        r = api.post(f"/api/claims/{claim_id}/payout/plan", json={})
        assert r.status_code == 503 and "sandbox keys are not set up" in r.json()["detail"]
        assert not world.app.state.claims.payout_path(claim_id).exists()
        assert api.get(f"/api/claims/{claim_id}").json()["state"] == "APPROVED"
    assert world.fake.calls == []


def test_airwallex_refusing_the_bank_details_is_passed_on_in_words(api, world):
    claim = open_claim(api)
    world.fake.fail_once["/api/v1/beneficiaries/validate"] = 400
    r = api.put(f"/api/claims/{claim['id']}/payee", json=MX_BANK)
    assert r.status_code == 422 and "Airwallex did not accept the bank details" in r.json()["detail"]
    assert api.get(f"/api/claims/{claim['id']}").json()["payee"] is None
