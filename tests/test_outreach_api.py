"""The holder's own list through the server: upload, mapping, the queue, notices, the owner's answer, the funnel."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from khutlisa import claims as cl
from khutlisa import invented_holder as inv
from khutlisa import llm
from khutlisa.server import create_app, mask_name
from test_claims import AS_PAYER, PAYER_KEY, PNG

MARISOL = {"name": "Marisol Elena Tolmedo Peralmonte", "address": "Calle Fresno 214, Colonia Americana\nGuadalajara, Jalisco 44160",
           "country": "MX", "email": "marisol.tolmedo@example.com", "relationship": "self"}
REAL_FILE = ("Acct,Customer,Address,City,State,Zip,Country,Kind,Last Activity,Balance,Email,Paperless\n"
             "A-1001,Ines Quillfeather,Calle Vera 9,Morelia,MICH,58000,Mexico,Savings,2023-03-01,412.07,ines@example.org,Y\n"
             "A-1002,Otto Brandbach,Lindstrasse 4,Bremen,,28195,Germany,Savings,2023-02-01,90.00,,\n"
             "A-1003,Pat Welstead,9 Pell Street,Fresno,CA,93701,,Savings,2023-02-01,75.00,,\n"
             "A-1004,Rio Salmeral,,,,,Chile,Savings,2023-02-01,80.00,,\n"
             "A-1005,Sol Perdez,Calle Alba 2,Leon,GTO,37000,Mexico,Savings,2023-02-01,20.00,,\n")


class World:
    """One server with a day that the test can move."""

    def __init__(self, tmp_path, **more):
        self.day = date(2026, 11, 13)
        self.app = create_app(db_path=tmp_path / "no-register.duckdb", totals_path=tmp_path / "t.json", web_dist=tmp_path / "no-web",
                              claims_dir=tmp_path / "claims", demonstration=True, payer_key=PAYER_KEY,
                              outreach_today=lambda: self.day, public_url="https://khutlisa.example", **more)
        self.client = TestClient(self.app, headers=AS_PAYER)
        self.claims = self.app.state.claims

    def load(self, data=None, name=None, rows=3200):
        files = {"file": (name or inv.file_name(), data or inv.as_csv(inv.rows(rows)), "text/csv")}
        view = self.client.post("/api/holder/list", files=files).json()
        mapping = {f: g["column"] for f, g in view["list"]["proposal"]["fields"].items()}
        return self.client.put(f"/api/holder/list/{view['list']['id']}/mapping", json={"mapping": mapping}).json()

    def notice(self, words="Tolmedo"):
        return self.client.get(f"/api/holder/notices?q={words}").json()["rows"][0]

    def view(self):
        return self.client.get("/api/holder/outreach").json()

    def stage(self, key):
        return next(s for s in self.view()["notices"]["funnel"]["stages"] if s["key"] == key)["notices"]


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    with w.client:
        yield w


@pytest.fixture
def ready(world):
    """The invented file loaded, its notices prepared and marked sent."""
    world.load()
    world.client.post("/api/holder/notices/prepare")
    world.client.post("/api/holder/notices/sent", json={"all_unsent": True})
    return world


# ---- the list ------------------------------------------------------------------------------------------------------

def test_the_holders_routes_are_behind_the_holders_key(world):
    bare = TestClient(world.app)
    for method, path in [("get", "/api/holder/outreach"), ("post", "/api/holder/list/invented"), ("post", "/api/holder/notices/prepare"),
                         ("get", "/api/holder/notices"), ("get", "/api/holder/notices/batch.pdf"), ("put", "/api/holder/outreach/settings")]:
        assert getattr(bare, method)(path).status_code == 401, path
        assert getattr(bare, method)(path, headers={"X-Payer-Key": "guess"}).status_code == 401, path
    assert bare.get("/api/holder/list/invented.csv").status_code == 200        # the invented file is for anyone to look at


def test_upload_proposes_the_columns_and_confirming_validates_every_row(world):
    view = world.client.post("/api/holder/list", files={"file": (inv.file_name(), inv.as_csv(inv.rows()), "text/csv")}).json()
    assert view["list"]["state"] == "uploaded" and view["list"]["invented"] is True and view["picture"] is None
    proposal = view["list"]["proposal"]
    assert proposal["by"] == "code" and "No language model" in proposal["model_note"] and proposal["missing"] == []
    mapping = {f: g["column"] for f, g in proposal["fields"].items()}
    assert world.client.put(f"/api/holder/list/{view['list']['id']}/mapping", json={"mapping": {"amount": "Net Amt"}}).status_code == 422
    view = world.client.put(f"/api/holder/list/{view['list']['id']}/mapping", json={"mapping": mapping}).json()
    listed, picture = view["list"], view["picture"]
    assert (listed["rows_read"], listed["valid"], listed["failed"]) == (3217, 3089, 128)
    assert sum(f["rows"] for f in listed["failures"]) >= 128 and listed["failures"][0]["rows"] >= listed["failures"][-1]["rows"]
    assert picture["abroad"] == {"balances": 937, "amount": "322462.32"}
    assert picture["abroad_due_soon"] == {"balances": 310, "amount": "117319.72", "handover": "2027-06-01", "days": 200}
    assert len(view["queue"]) == 50 and view["queue_total"] == 937
    first = view["queue"][0]
    assert first["days_to_state"] == 200 and first["status"] in ("late", "remit") and float(first["amount"]) >= float(view["queue"][1]["amount"])
    failed = world.client.get(f"/api/holder/list/{listed['id']}/failed").json()
    assert failed["total"] == 128 and all(row["reasons"] for row in failed["rows"])
    page = world.client.get(f"/api/holder/list/{listed['id']}/queue?offset=50&country=MX").json()
    assert page["total"] == 119 and all(r["country"] == "MX" for r in page["rows"])


def test_a_confirmed_mapping_is_remembered_for_the_next_export_with_the_same_titles(world, monkeypatch):
    world.load(rows=300)
    monkeypatch.setattr(llm, "ask", lambda *a, **k: pytest.fail("a remembered mapping needs no model"))
    again = world.client.post("/api/holder/list", files={"file": ("next-month.csv", inv.as_csv(inv.rows(200, seed=9)), "text/csv")}).json()
    assert again["list"]["proposal"]["by"] == "remembered" and again["list"]["proposal"]["fields"]["amount"]["source"] == "remembered"


def test_a_file_that_cannot_be_read_is_refused_in_words(world):
    r = world.client.post("/api/holder/list", files={"file": ("x.csv", b"1,2,3\n4,5,6\n", "text/csv")})
    assert r.status_code == 422 and "No row of column titles" in r.json()["detail"]
    assert world.view()["list"] is None


# ---- notices -------------------------------------------------------------------------------------------------------

def test_the_agent_prepares_notices_soonest_handover_first_and_checks_every_one(world):
    before = world.load()
    card = before["notices"]["cards"][0]
    assert card["kind"] == "notify_first" and card["counts"] == {"to_prepare": 527, "under_minimum": 121, "not_yet": 289, "already": 0}
    assert all(len(card[line]) <= 110 for line in ("happened", "allowed", "did", "money"))
    out = world.client.post("/api/holder/notices/prepare").json()
    assert out["prepared"] == {**out["prepared"], "notices": 527, "ready": 527, "held": 0, "amount": "213355.42"}
    assert out["prepared"]["card"]["did"] == "Prepared 527 notices: soonest handover first, then largest amount."
    notices = out["notices"]
    assert (notices["count"], notices["ready"], notices["to_prepare"], notices["unsent"]) == (527, 527, 0, 527)
    assert {l["language"]: l["notices"] for l in notices["languages"]}["Spanish"] == 92 and len(notices["languages"]) == 16
    rows = world.client.get("/api/holder/notices").json()["rows"]
    assert [r["handover"] for r in rows] == sorted(r["handover"] for r in rows)
    assert float(rows[0]["amount"]) >= float(rows[1]["amount"]) >= float(rows[2]["amount"])
    assert all(float(r["amount"]) >= 50 and r["state"] == "ready" and r["stage"] == "prepared" for r in rows)
    # preparing again makes nothing new
    assert world.client.post("/api/holder/notices/prepare").json()["prepared"]["notices"] == 0


def test_one_notice_in_two_languages_with_every_element_and_its_letter(world):
    world.load()
    world.client.post("/api/holder/notices/prepare")
    row = world.notice()
    detail = world.client.get(f"/api/holder/notices/{row['id']}").json()
    assert detail["name"] == "Marisol E Tolmedo" and detail["language"]["code"] == "es" and detail["language"]["translated"]
    assert len(detail["elements"]) == 10 and all(e["present"] for e in detail["elements"])
    english, spanish = detail["views"]["english"], detail["views"]["other"]
    assert english["heading"].startswith("THE STATE OF CALIFORNIA REQUIRES US TO NOTIFY YOU")
    assert [f["value"] for f in english["facts"][1:]] == [f["value"] for f in spanish["facts"][1:]] == ["4471", "USD 1,284.60", "2025-02-14", "2027-06-01"]
    assert detail["link"] == f"https://khutlisa.example/n/{row['code']}" and "Nothing is sent from here" in detail["sends_nothing"]
    assert [(d["channel"], d["counts"]) for d in detail["delivery"]] == [("post", True), ("email", True), ("telephone", False)]
    pdf = world.client.get(f"/api/holder/notices/{row['id']}/letter.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and pdf.headers["cache-control"] == "no-store"
    batch = world.client.get("/api/holder/notices/batch.pdf?limit=25")
    assert batch.status_code == 200 and len(batch.content) > 10 * len(pdf.content)
    assert world.client.get("/api/holder/notices/000000000000").status_code == 404


def test_nothing_is_sent_and_delivery_is_recorded_only_when_the_holder_marks_it(world):
    world.load()
    world.client.post("/api/holder/notices/prepare")
    row = world.notice()
    assert world.stage("sent") == 0 and "Nothing is sent from here" in world.view()["sends_nothing"]
    assert TestClient(world.app).get(f"/api/notices/{row['code']}").status_code == 404        # not sent: the code opens nothing
    assert world.client.post("/api/holder/notices/sent", json={"ids": [row["id"]], "on": "2099-01-01"}).status_code == 422
    one = world.client.post("/api/holder/notices/sent", json={"ids": [row["id"]], "channel": "email", "on": "2026-11-12"}).json()
    assert one["marked"] == 1 and world.stage("sent") == 1
    sent = world.notice()["sent"]
    assert sent == [{**sent[0], "on": "2026-11-12", "channel": "email", "reminder": False, "marked_by": "the holder"}]
    rest = world.client.post("/api/holder/notices/sent", json={"all_unsent": True}).json()
    assert rest["marked"] == 526 and world.stage("sent") == 527 and world.stage("opened") == 0
    assert world.client.post("/api/holder/notices/sent", json={"all_unsent": True}).json()["marked"] == 0     # never twice


# ---- the owner's answer --------------------------------------------------------------------------------------------

def test_the_owner_opens_her_notice_with_the_code_and_sees_it_in_her_language_without_her_name(ready):
    row = ready.notice()
    owner = TestClient(ready.app)                      # no holder's key
    seen = owner.get(f"/api/notices/{row['code'].lower().replace('-', ' ')}")
    assert seen.status_code == 200
    body = seen.json()
    assert body["language"]["code"] == "es" and body["views"]["other"]["heading"].startswith("EL ESTADO DE CALIFORNIA")
    assert body["views"]["english"]["heading"].startswith("THE STATE OF CALIFORNIA")
    assert (body["amount"], body["holder"], body["deadline"], body["days_left"], body["demonstration"]) == (
        "1284.60", "Empacadora Valle Sereno", "2027-06-01", 200, True)
    text = json.dumps(body, ensure_ascii=False)
    assert "Tolmedo" not in text and "Calle Fresno" not in text and "example.com" not in text
    assert ready.stage("opened") == 1
    owner.get(f"/api/notices/{row['code']}")
    assert ready.stage("opened") == 1                  # opened is counted once
    wrong = owner.get("/api/notices/ZZZZ-ZZZZ")
    assert wrong.status_code == 404 and wrong.json()["detail"] == "There is no notice with that code. Check the letter and type it again."


def test_her_answer_opens_a_claim_on_that_exact_record_and_is_recorded_against_the_notice(ready):
    row = ready.notice()
    owner = TestClient(ready.app)
    answer = owner.post(f"/api/notices/{row['code']}/answer", json={"claimant": MARISOL})
    assert answer.status_code == 201 and answer.json()["already"] is False
    claim = owner.get(f"/api/claims/{answer.json()['claim_id']}").json()
    record = claim["record"]
    assert (record["amount"], record["holder_name"], record["source"], record["owner_country"]) == (1284.6, "Empacadora Valle Sereno", "DEMO", "MX")
    assert record["owner"] == mask_name("Marisol E Tolmedo") and claim["sample"] is True and claim["match"]["strength"] == "strong"
    assert "street" not in json.dumps(record).lower() and "Calle Fresno 214" not in json.dumps({k: v for k, v in claim.items() if k != "claimant"})
    assert any("answered Empacadora Valle Sereno's notice" in event["note"] for event in claim["history"])
    assert claim["notice"]["id"] == row["id"] and "property" not in claim
    # the same code again goes to the same claim, and a second claim on the property cannot be made
    again = owner.post(f"/api/notices/{row['code']}/answer", json={"claimant": MARISOL})
    assert again.json() == {"claim_id": claim["id"], "already": True} and len(ready.claims.all()) == 1
    assert owner.get(f"/api/notices/{row['code']}").json()["claim_id"] == claim["id"]
    assert ready.stage("responded") == 1 and ready.notice()["stage"] == "responded"
    # the holder sees the claim in its ordinary queue
    queue = ready.client.get("/api/payer/queue").json()["claims"]
    assert len(queue) == 1 and queue[0]["holder_name"] == "Empacadora Valle Sereno" and queue[0]["sample"] is True


def test_the_claim_is_compared_with_the_holders_own_record_and_the_open_search_never_reads_the_list(ready, tmp_path):
    row = ready.notice()
    claim_id = TestClient(ready.app).post(f"/api/notices/{row['code']}/answer", json={"claimant": MARISOL}).json()["claim_id"]
    stored = ready.claims.load(claim_id)
    assert stored["property"]["record_id"].startswith("HL-") and stored["property"]["source"] == "DEMO"
    with ready.app.state.store.looking_up() as cursors:
        found = [r for cur in cursors for r in cur.execute("select owner_name, owner_street from records where record_id = ?",
                                                           [stored["property"]["record_id"]]).fetchall()]
    assert found == [("Marisol E Tolmedo", "Calle Fresno 214, Colonia Americana")]
    search = ready.client.post("/api/search", json={"given_names": ["Marisol"], "family_names": ["Tolmedo"],
                                                    "employers": ["Empacadora Valle Sereno"]}).json()
    assert search["searched"]["demonstration_records"] == 8 and 1284.6 not in [m["amount"] for m in search["matches"]]


def test_the_funnel_follows_the_claim_to_proven_and_paid_and_the_deadline_card_counts_it(ready):
    row = ready.notice()
    claim_id = TestClient(ready.app).post(f"/api/notices/{row['code']}/answer", json={"claimant": MARISOL}).json()["claim_id"]
    deadline = lambda: next(c for c in ready.view()["notices"]["cards"] if c["kind"] == "deadline_outreach")
    held = deadline()
    assert held["groups"] == {"paid": {"balances": 0, "amount": "0.00"}, "pay": {"balances": 0, "amount": "0.00"},
                              "hold": {"balances": 1, "amount": "1284.60"}, "release": {"balances": 309, "amount": "116035.12"}}
    assert held["did"] == "As things stand: pay 0, hold 1 for proof, release 309 to the State." and held["final"] is False
    for kind in ("id", "tax_number", "proof_of_address"):      # document reading is off here: attached means proven
        ready.client.post(f"/api/claims/{claim_id}/documents", data={"kind": kind}, files={"file": (f"{kind}.png", PNG, "image/png")})
    assert ready.stage("proven") == 1 and ready.stage("paid") == 0 and deadline()["groups"]["pay"]["balances"] == 1
    ready.claims.move(claim_id, cl.BEFORE_DECISION, cl.PAID, "Paid, for the test.", "no")
    funnel = ready.view()["notices"]["funnel"]
    assert [(s["key"], s["notices"]) for s in funnel["stages"]] == [("prepared", 527), ("sent", 527), ("opened", 0), ("responded", 1),
                                                                    ("proven", 1), ("paid", 1)]
    assert funnel["days_left"] == 200 and funnel["date_words"] == "1 June 2027"
    paid = deadline()
    assert paid["groups"]["paid"]["balances"] == 1 and "1 already paid" in paid["did"] and paid["money"].startswith("$1,284.60 to owners")


def test_at_the_handover_date_the_choice_is_final_and_follows_the_holders_instructions(ready):
    row = ready.notice()
    TestClient(ready.app).post(f"/api/notices/{row['code']}/answer", json={"claimant": MARISOL})
    ready.client.put("/api/payer/instructions", json={"handover_date": "2026-12-01"})
    card = next(c for c in ready.view()["notices"]["cards"] if c["kind"] == "deadline_outreach")
    assert card["final"] is True and card["days_left"] == 18 and card["tone"] == "stop"
    assert card["did"] == "At the date: pay 0, hold 1 for proof, release 309 to the State."
    assert ready.view()["notices"]["funnel"]["days_left"] == 18
    assert ready.client.put("/api/holder/outreach/settings", json={"rules": {"hold_answered": False}}).status_code == 200
    card = next(c for c in ready.view()["notices"]["cards"] if c["kind"] == "deadline_outreach")
    assert card["groups"]["hold"]["balances"] == 0 and card["groups"]["release"]["balances"] == 310
    assert card["allowed"] == "Pay what is proven. Release the rest."


def test_a_reminder_falls_due_after_the_days_the_holder_set_and_is_recorded_when_marked(ready):
    reminder = lambda: next(c for c in ready.view()["notices"]["cards"] if c["kind"] == "reminder")
    assert reminder()["did"] == "No reminder is due yet. The first falls due on 13 December 2026." and reminder()["due"] == []
    row = ready.notice()
    TestClient(ready.app).post(f"/api/notices/{row['code']}/answer", json={"claimant": MARISOL})
    ready.day = date(2026, 12, 13)
    card = reminder()
    assert len(card["due"]) == 526 and row["id"] not in card["due"] and card["did"] == "526 reminders due now, soonest handover first."
    assert ready.client.get("/api/holder/notices/batch.pdf?which=reminders&limit=5").status_code == 200
    marked = ready.client.post("/api/holder/notices/sent", json={"all_unsent": True, "reminder": True}).json()
    assert marked["marked"] == 526 and reminder()["due"] == []
    ready.day = date(2027, 2, 1)
    assert reminder()["due"] == [] and "has had its reminders" in reminder()["did"]         # one reminder at most
    assert ready.client.put("/api/holder/outreach/settings", json={"rules": {"reminders_most": 2}}).status_code == 200
    assert len(reminder()["due"]) == 526


def test_the_outreach_limits_are_checked(world):
    for rules, words in [({"notice_minimum_usd": "75"}, "cannot be higher"), ({"reminder_after_days": 2}, "7 to 180 days"),
                         ({"reminders_most": 9}, "between 0 and 3"), ({"notice_minimum_usd": "lots"}, "must be a number")]:
        r = world.client.put("/api/holder/outreach/settings", json={"rules": rules})
        assert r.status_code == 422 and words in r.json()["detail"], rules
    saved = world.client.put("/api/holder/outreach/settings", json={"rules": {"notice_minimum_usd": "25"}}).json()
    assert saved["settings"]["rules"]["notice_minimum_usd"] == "25.00" and saved["settings"]["rules_set"] is True
    world.load()
    assert world.view()["notices"]["cards"][0]["counts"]["to_prepare"] > 527      # a lower line notifies more owners


def test_notices_prepared_before_the_handover_date_changed_are_made_again(world):
    world.load()
    world.client.post("/api/holder/notices/prepare")
    row = world.notice()
    world.client.post("/api/holder/notices/sent", json={"ids": [row["id"]]})
    world.client.put("/api/payer/instructions", json={"handover_date": "2027-06-10"})
    view = world.view()
    assert view["notices"]["stale"] > 200 and view["notices"]["to_prepare"] == 0
    out = world.client.post("/api/holder/notices/prepare").json()
    assert out["notices"]["stale"] == 0 and out["prepared"]["notices"] > 200
    after = world.notice()
    assert after["id"] == row["id"] and after["handover"] == "2027-06-01"       # a notice already sent stands as it was sent
    rows = world.client.get("/api/holder/notices").json()["rows"]
    assert [r["handover"] for r in rows[:3]] == ["2027-06-01", "2027-06-10", "2027-06-10"] and rows[0]["id"] == row["id"]


def test_reading_and_answering_notices_is_counted_per_client(tmp_path):
    now = [0.0]
    w = World(tmp_path, clock=lambda: now[0])
    with w.client:
        codes = [TestClient(w.app).get("/api/notices/AAAA-AAAA").status_code for _ in range(31)]
        assert codes[:30] == [404] * 30 and codes[30] == 429
        now[0] += 61
        assert TestClient(w.app).get("/api/notices/AAAA-AAAA").status_code == 404


# ---- a real holder's file ------------------------------------------------------------------------------------------

def test_a_real_holders_list_needs_the_holders_details_and_its_records_are_not_demonstration_records(world):
    view = world.load(REAL_FILE.encode(), "dormant-accounts.csv")
    assert view["list"]["invented"] is False and view["holder"] is None and (view["list"]["valid"], view["list"]["failed"]) == (5, 0)
    assert view["picture"]["abroad"]["balances"] == 4 and view["picture"]["by_kind"][0]["kind"] == "bank_account"
    refused = world.client.post("/api/holder/notices/prepare")
    assert refused.status_code == 409 and "holder's name and contact details first" in refused.json()["detail"]
    assert world.client.put("/api/holder/outreach/settings", json={"holder": {"name": "Brisa Clara Credit Union"}}).status_code == 422
    world.client.put("/api/holder/outreach/settings", json={"holder": {"name": "Brisa Clara Credit Union", "street": "1 Tide Court",
                                                                       "city": "Watsonville", "region": "CA", "postcode": "95076",
                                                                       "country": "US", "phone": "+1 831 555 0100"}})
    out = world.client.post("/api/holder/notices/prepare").json()
    rows = {r["name"]: r for r in out["notices"]["rows"]}
    assert set(rows) == {"Ines Quillfeather", "Otto Brandbach", "Rio Salmeral"}       # 20 dollars is under the line
    assert rows["Ines Quillfeather"]["state"] == "ready" and rows["Otto Brandbach"]["language"]["code"] == "de"
    assert rows["Rio Salmeral"]["state"] == "held" and "cannot be delivered" in rows["Rio Salmeral"]["problems"][0]
    assert out["notices"]["held"] == 1 and out["notices"]["funnel"]["stages"][0]["notices"] == 2
    assert world.client.get(f"/api/holder/notices/{rows['Rio Salmeral']['id']}/letter.pdf").status_code == 409
    world.client.post("/api/holder/notices/sent", json={"all_unsent": True})
    code = rows["Ines Quillfeather"]["code"]
    owner = TestClient(world.app)
    assert owner.get(f"/api/notices/{code}").json()["demonstration"] is False
    assert owner.get(f"/api/notices/{rows['Rio Salmeral']['code']}").status_code == 404      # held back: never sent, never opened
    claim_id = owner.post(f"/api/notices/{code}/answer", json={"claimant": {**MARISOL, "name": "Ines Quillfeather"}}).json()["claim_id"]
    claim = owner.get(f"/api/claims/{claim_id}").json()
    assert claim["record"]["source"] == "HOLDER" and claim["sample"] is False and claim["record"]["owner"] == "I··· Q···"
    assert claim["record"]["holder_name"] == "Brisa Clara Credit Union"
