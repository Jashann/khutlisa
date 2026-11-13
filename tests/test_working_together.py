"""The capabilities working together: estates and Metal, the checks across claims before every approval and every
payment (single claims, estates, batches of claims and claims opened from a notice), a claim from a notice in the
queue, the funnel and the risk view and paid alone or in a batch, the public demonstration over every new route,
and one set of standing instructions behind every decision. A fake Airwallex and a fake chain sit behind every
test; nothing reaches the network or a model."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from khutlisa import airwallex as awx
from khutlisa import batch as bt
from khutlisa import claims as cl
from khutlisa import instructions as ins
from khutlisa import invented_holder as inv
from khutlisa import metal as mt
from khutlisa import public_demo
from khutlisa.server import create_app
from test_airwallex import make_client
from test_batch import FiveCountries
from test_claims import AS_PAYER, CLAIMANT, PAYER_KEY, PH_BANK, give_bank, make_register, open_claim, plan_and_agree
from test_outreach_api import MARISOL
from test_public_demo import SAMPLE, app_for, record
from test_totals import searchable_register

# Two claimants with nothing in common: other names, streets, emails and bank accounts, so the check across claims
# has nothing to link them by. Every account holder's name is part of the claimant's name, as the server asks.
NGUYEN = {"name": "Co Van Nguyen", "address": "41 Kalayaan Street, Quezon City 1100", "country": "PH",
          "email": "covan@nguyen.example", "relationship": "self"}
CHURCH = {"name": "Rosalind Church", "address": "Calle Hidalgo 9, Puebla 72000", "country": "MX",
          "email": "rosalind@church.example", "relationship": "self"}
NGUYEN_BANK = {**PH_BANK, "first_name": "Co Van", "last_name": "Nguyen", "account_number": "5550001112"}
_CLABE = "00232001234567881"
CHURCH_BANK = {"currency": "MXN", "first_name": "Rosalind", "last_name": "Church",
               "account_number": _CLABE + str(awx.clabe_check_digit(_CLABE)), "street_address": "Calle Hidalgo 9",
               "city": "Puebla", "postcode": "72000", "state": "MX-PUE"}
NOTHING = {"given_names": ["Nobody"], "family_names": ["Here"], "places": [], "employers": []}
RULES = {"tolerance_percent": "1.5", "small_claim_usd": "500", "deadline_days": 21}


class Together:
    """One server with every capability on: the made-up register, the demonstration records, the holder's list,
    a fake Airwallex and a fake Metal chain."""

    def __init__(self, folder):
        self.folder = folder
        self.db = make_register(folder)
        self.fake = FiveCountries()
        self.chain = mt.FakeMetal(path=folder / "chain.json")
        self.app = create_app(db_path=self.db, totals_path=folder / "totals.json", web_dist=folder / "no-web",
                              claims_dir=folder / "claims", airwallex_factory=self.factory, payout_pause=0.0,
                              payer_key=PAYER_KEY, watch_seconds=0, demonstration=True, metal=self.chain,
                              metal_scale="100", metal_keys=folder / "keys", outreach_today=lambda: date(2026, 11, 13),
                              public_url="https://khutlisa.example")
        self.claims = self.app.state.claims

    def factory(self):
        client = make_client(self.fake)
        return client, awx.SandboxSimulator(client)


@pytest.fixture
def world(tmp_path):
    w = Together(tmp_path)
    with TestClient(w.app, headers=AS_PAYER) as api:
        w.api = api
        yield w


def risk_of(api, claim_id):
    return next(c for c in api.get("/api/payer/risk").json()["claims"] if c["id"] == claim_id)["status"]


def approved(api, record_id, claimant, bank, **body):
    claim = open_claim(api, record_id, claimant, history=NOTHING)
    give_bank(api, claim["id"], bank)
    r = api.post(f"/api/payer/claims/{claim['id']}/approve", json=body or None)
    assert r.status_code == 200, r.text
    return claim["id"]


def batch_of(api, *ids):
    r = api.post("/api/payer/batches/claims", json={"claim_ids": list(ids)})
    assert r.status_code == 201, r.text
    return r.json()


def notice_claim(world):
    """The invented holder file loaded, its notices prepared and marked sent, and Marisol's answer to hers."""
    api = world.api
    files = {"file": (inv.file_name(), inv.as_csv(inv.rows(3200)), "text/csv")}
    view = api.post("/api/holder/list", files=files).json()
    mapping = {f: g["column"] for f, g in view["list"]["proposal"]["fields"].items()}
    api.put(f"/api/holder/list/{view['list']['id']}/mapping", json={"mapping": mapping})
    api.post("/api/holder/notices/prepare")
    api.post("/api/holder/notices/sent", json={"all_unsent": True})
    row = api.get("/api/holder/notices?q=Tolmedo").json()["rows"][0]
    answer = TestClient(world.app).post(f"/api/notices/{row['code']}/answer", json={"claimant": MARISOL})
    assert answer.status_code == 201, answer.text
    return answer.json()["claim_id"]


def stage(api, key):
    return next(s for s in api.get("/api/holder/outreach").json()["notices"]["funnel"]["stages"] if s["key"] == key)["notices"]


# ---- estates and Metal ---------------------------------------------------------------------------------------------

def test_an_estate_is_never_funded_on_metal_and_every_way_of_asking_says_why(world):
    api = world.api
    claim = open_claim(api, "P1", {**CLAIMANT, "relationship": "heir"}, history=NOTHING)
    assert api.post(f"/api/claims/{claim['id']}/estate").status_code == 200
    for path, body in ((f"/api/payer/estates/{claim['id']}/approve", {"funding": "metal"}),
                       (f"/api/payer/claims/{claim['id']}/approve", {"funding": "metal"})):
        refused = api.post(path, json=body)
        assert refused.status_code == 409 and refused.json()["detail"] == cl.ESTATE_NOT_ON_METAL, path
    with pytest.raises(cl.ClaimError) as err:
        world.app.state.metal.sign_mandate(claim["id"])
    assert err.value.message == cl.ESTATE_NOT_ON_METAL
    assert not world.chain.state.get("mandates") if hasattr(world.chain, "state") else True
    # without asking for Metal the estate route answers by its own rules, and the claim route sends it there
    assert api.post(f"/api/payer/claims/{claim['id']}/approve").json()["detail"].startswith("This is an estate claim")


# ---- the check across claims, before approval and before payment -------------------------------------------------

def test_a_claim_from_a_notice_is_fingerprinted_and_held_with_a_linked_claim_like_any_other(world):
    api = world.api
    from_notice = notice_claim(world)
    stored = world.claims.load(from_notice)
    assert stored["origin"] and set(stored["origin"]) >= {"network", "agent"}
    give_bank(api, from_notice, {"currency": "MXN", "first_name": "Marisol", "last_name": "Tolmedo",
                                 "account_number": CHURCH_BANK["account_number"], "street_address": "Calle Fresno 214",
                                 "city": "Guadalajara", "postcode": "44160", "state": "MX-JAL"})
    other = open_claim(api, "P6", CHURCH, history=NOTHING)          # the same bank account on another claim
    give_bank(api, other["id"], CHURCH_BANK)
    assert risk_of(api, from_notice) == "held" and risk_of(api, other["id"]) == "held"
    refused = api.post(f"/api/payer/claims/{from_notice}/approve")
    assert refused.status_code == 409 and "This claim is held" in refused.json()["detail"]
    # it is in the holder's queue, in the funnel and in the risk view
    queue = {c["id"]: c for c in api.get("/api/payer/queue").json()["claims"]}
    assert queue[from_notice]["from_notice"] is True and queue[from_notice]["risk"]["status"] == "held"
    assert stage(api, "responded") == 1


def test_an_estate_held_with_a_linked_claim_cannot_be_approved_or_settled(world):
    api = world.api
    estate = open_claim(api, "P1", {**CLAIMANT, "relationship": "heir"}, history=NOTHING)
    api.post(f"/api/claims/{estate['id']}/estate")
    other = {**CLAIMANT, "name": "Maria Santos Reyes", "email": "bela@elsewhere.example",
             "address": "9 Narra Road, Davao City 8000"}
    twin = open_claim(api, "P4", other, history=NOTHING)              # another person paid into the same account
    give_bank(api, twin["id"], PH_BANK)
    give_bank(api, estate["id"], PH_BANK)
    assert risk_of(api, estate["id"]) == "held"
    refused = world.claims.approve
    with pytest.raises(cl.ClaimError) as err:
        refused(estate["id"], "for the test")
    assert "This claim is held" in err.value.message
    with pytest.raises(cl.ClaimError):
        world.claims.check_may_pay(world.claims.load(estate["id"]))


def test_a_batch_of_claims_runs_the_same_checks_before_it_is_approved_and_before_any_money_moves(world):
    api = world.api
    a = approved(api, "P7", NGUYEN, NGUYEN_BANK)
    b = approved(api, "P6", CHURCH, CHURCH_BANK)
    assert risk_of(api, a) == risk_of(api, b) == "clear"
    batch = batch_of(api, a, b)
    # a third claim paid into Nguyen's account links his claim after his approval: the batch is refused
    third = open_claim(api, "P5", {**NGUYEN, "name": "Roberto Co Van Nguyen", "email": "r@else.example"}, history=NOTHING)
    give_bank(api, third["id"], {**NGUYEN_BANK, "first_name": "Roberto", "last_name": "Nguyen"})
    assert risk_of(api, a) == "suspended"
    refused = api.post(f"/api/payer/batches/{batch['batch_id']}/approve")
    assert refused.status_code == 409 and "Payment 1" in refused.json()["detail"]
    assert world.claims.load(a)["state"] == cl.APPROVED and not world.fake.deposits
    # the same hold, appearing after the batch was approved but before its deposit, stops it with nothing sent
    runner = world.app.state.batches
    held = runner.load(batch["batch_id"])
    bt.approve(held)
    for item in held.items:
        claim = world.claims.load(item["claim_id"])
        claim["batch"] = {"id": held.batch_id, "n": item["n"]}
        world.claims.save(claim)
    runner.start(held.batch_id)
    runner.join(held.batch_id)
    stopped = runner.load(held.batch_id)
    assert stopped.state == bt.STOPPED and "Payment 1" in stopped.problem and not world.fake.deposits
    assert {world.claims.load(x)["state"] for x in (a, b)} == {cl.APPROVED}       # still approved, out of the batch
    assert all(world.claims.load(x).get("batch") is None for x in (a, b))


def test_metal_does_not_pull_for_a_claim_held_after_its_payment_was_confirmed(world):
    api = world.api
    api.put("/api/payer/instructions", json=RULES)
    claim_id = approved(api, "P7", NGUYEN, NGUYEN_BANK, funding="metal")
    funding = world.app.state.metal
    payout_path = world.claims.payout_path(claim_id)
    plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()
    third = open_claim(api, "P5", {**NGUYEN, "name": "Roberto Co Van Nguyen", "email": "r@else.example"}, history=NOTHING)
    give_bank(api, third["id"], {**NGUYEN_BANK, "first_name": "Roberto", "last_name": "Nguyen"})
    payout = awx.Payout.load(payout_path)
    client, _ = world.factory()
    with pytest.raises(ValueError) as err:
        funding.before_deposit(payout, client)
    assert "Nothing was pulled on Metal" in str(err.value) and plan["plan"]
    assert not (funding.load(claim_id).get("pull") or {}).get("transaction")


# ---- a claim from a notice, paid alone or in a batch ---------------------------------------------------------------

def mexican_account(name_first="Marisol", name_last="Tolmedo"):
    first17 = "00232001234567" + "992"
    return {"currency": "MXN", "first_name": name_first, "last_name": name_last,
            "account_number": first17 + str(awx.clabe_check_digit(first17)), "street_address": "Calle Fresno 214",
            "city": "Guadalajara", "postcode": "44160", "state": "MX-JAL"}


def test_a_claim_from_a_notice_is_paid_like_any_other_and_the_funnel_and_risk_view_follow_it(world):
    api = world.api
    claim_id = notice_claim(world)
    give_bank(api, claim_id, mexican_account())
    assert api.post(f"/api/payer/claims/{claim_id}/approve").status_code == 200
    plan_and_agree(api, claim_id)
    world.app.state.runner.join(claim_id) if hasattr(world.app.state, "runner") else None
    for _ in range(200):
        if world.claims.load(claim_id)["state"] == cl.PAID:
            break
        import time
        time.sleep(0.05)
    assert world.claims.load(claim_id)["state"] == cl.PAID
    assert stage(api, "paid") == 1
    row = next(c for c in api.get("/api/payer/risk").json()["claims"] if c["id"] == claim_id)
    assert row["status"] == "clear" and row["sample"] is True


def test_a_claim_from_a_notice_is_paid_in_a_batch_with_another_approved_claim(world):
    api = world.api
    api.put("/api/payer/instructions", json=RULES)
    from_notice = notice_claim(world)
    give_bank(api, from_notice, mexican_account())
    assert api.post(f"/api/payer/claims/{from_notice}/approve").status_code == 200
    other = approved(api, "P6", CHURCH, CHURCH_BANK)          # 410.00, below the small-claim line of 500
    view = batch_of(api, from_notice, other)
    items = {i["n"]: i for i in view["items"]}
    # the fee rule on each payment is the one a single payment of that claim would use
    for item, claim_id in zip(view["items"], (from_notice, other)):
        claim = world.claims.load(claim_id)
        assert item["holder_sends"] == claim["approval"]["fee_rule"]["holder_sends"]
    assert items[2]["fees_borne_by"] == "holder" and items[1]["fees_borne_by"] == "claim"
    assert view["rules"] == world.claims.load(other)["approval"]["terms"]["instructions"]
    assert api.post(f"/api/payer/batches/{view['batch_id']}/approve").status_code == 200
    queue = {c["id"]: c for c in api.get("/api/payer/queue").json()["claims"]}
    assert queue[from_notice]["batch"] == {"id": view["batch_id"], "n": 1}
    world.app.state.batches.join(view["batch_id"])
    done = api.get(f"/api/payer/batches/{view['batch_id']}").json()
    assert done["state"] == bt.DONE and done["reconciliation"]["balanced"] and len(world.fake.deposits) == 1
    assert {world.claims.load(x)["state"] for x in (from_notice, other)} == {cl.PAID}
    assert stage(api, "paid") == 1
    shown = api.get(f"/api/claims/{from_notice}/payout").json()
    assert shown["in_batch"]["id"] == view["batch_id"]
    # a claim already in a batch cannot be planned alone, and cannot go in a second batch
    assert api.post(f"/api/claims/{from_notice}/payout/plan", json={}).status_code == 409
    assert api.post("/api/payer/batches/claims", json={"claim_ids": [from_notice, other]}).status_code == 409


def test_a_batch_refuses_estates_unapproved_claims_and_claims_funded_on_metal(world):
    api = world.api
    estate = open_claim(api, "P1", {**CLAIMANT, "relationship": "heir"}, history=NOTHING)
    api.post(f"/api/claims/{estate['id']}/estate")
    on_metal = approved(api, "P7", NGUYEN, NGUYEN_BANK, funding="metal")
    plain = open_claim(api, "P6", CHURCH, history=NOTHING)
    refused = api.post("/api/payer/batches/claims", json={"claim_ids": [estate["id"], on_metal, plain["id"]]})
    reasons = refused.json()["detail"]["reasons"]
    assert refused.status_code == 409 and len(reasons) == 3
    assert "estate" in reasons[0] and "Metal" in reasons[1] and "not approved" in reasons[2]


# ---- one set of standing instructions ------------------------------------------------------------------------------

def test_the_standing_instructions_drive_a_single_payment_a_batch_metal_an_estate_and_the_notices(world):
    api = world.api
    assert api.put("/api/payer/instructions", json={**RULES, "handover_date": "2027-03-01"}).status_code == 200
    rules = api.get("/api/payer/instructions").json()["rules"]
    single = approved(api, "P6", CHURCH, CHURCH_BANK)
    on_metal = approved(api, "P7", NGUYEN, NGUYEN_BANK, funding="metal")
    for claim_id in (single, on_metal):
        approval = world.claims.load(claim_id)["approval"]
        assert approval["terms"]["instructions"] == rules
        assert approval["fee_rule"] == ins.fee_plan(world.claims.load(claim_id)["record"]["amount"], rules)
    # the Metal mandate's cap is what the fee rule of those instructions says the holder sends
    wanted = mt.wanted_terms(world.claims.load(on_metal), "0x" + "5e" * 20, Decimal("100"), "2027-03-01")
    assert Decimal(wanted["approved_usd"]) == Decimal(ins.fee_plan("990.00", rules)["holder_sends"])
    view = batch_of(api, single, approved(api, "P4", {"name": "Luz Villanueva", "address": "3 Rizal Road, Cebu", "country": "PH",
                                                      "email": "luz@villanueva.example", "relationship": "self"},
                                          {**PH_BANK, "first_name": "Luz", "last_name": "Villanueva", "account_number": "7778889990"}))
    assert view["rules"] == rules
    # the handover date the holder set is the date the notices and their deadline card count to
    files = {"file": (inv.file_name(), inv.as_csv(inv.rows(400)), "text/csv")}
    listed = api.post("/api/holder/list", files=files).json()
    assert listed["handover"]["handover_date"] == "2027-03-01"


# ---- the public demonstration over every new route -----------------------------------------------------------------

def test_the_public_demonstration_closes_every_new_money_route_to_anything_but_demonstration_claims(tmp_path):
    app = app_for(tmp_path, db=searchable_register(tmp_path / "registers.duckdb"))
    with TestClient(app) as demo:
        store = app.state.claims
        real = store.create({"record_id": "k-real", "source": "US-CA", "owner": "O··· Q···", "owner_is_organisation": False,
                             "amount": 50.0, "currency": "USD", "holder_name": "A BANK", "property_type": "",
                             "owner_city": "", "owner_region": "", "owner_country": "US"},
                            {**MARISOL, "relationship": "self"}, None, {"source": "US-CA", "record_id": "1"})
        rid = real["id"]
        for path in (f"/api/payer/claims/{rid}/metal/mandate", f"/api/payer/claims/{rid}/metal/attempt",
                     f"/api/payer/claims/{rid}/metal/revoke", f"/api/payer/claims/{rid}/metal/verify",
                     f"/api/claims/{rid}/estate/settlement/plan", f"/api/claims/{rid}/estate/settlement/confirm",
                     f"/api/claims/{rid}/estate/settlement/resume", f"/api/claims/{rid}/estate/settlement/heirs/h1/agree",
                     f"/api/payer/estates/{rid}/approve", f"/api/payer/risk/claims/{rid}/release"):
            refused = demo.post(path, headers=AS_PAYER, json={"case": "over_cap", "plan_id": "p" * 10, "reason": "to test"})
            assert refused.status_code == 403 and refused.json()["detail"] == public_demo.ONLY_DEMO_PAYMENTS, path
        shown = demo.post("/api/claims", json={"record_id": record(demo, "DEMO")["record_id"], "claimant": MARISOL}).json()
        batch = demo.post("/api/payer/batches/claims", headers=AS_PAYER, json={"claim_ids": [rid, shown["id"]]})
        assert batch.status_code == 403 and batch.json()["detail"] == public_demo.ONLY_DEMO_PAYMENTS
        # a demonstration claim reaches the routes, which answer by their own rules
        assert demo.post(f"/api/payer/estates/{shown['id']}/approve", headers=AS_PAYER, json={}).status_code != 403
        assert demo.post(f"/api/payer/risk/claims/{shown['id']}/release", headers=AS_PAYER,
                         json={"reason": "to test"}).status_code == 409
        # an estate document is a sample document or nothing
        own = demo.post(f"/api/claims/{shown['id']}/estate/documents", data={"kind": "death_certificate"},
                        files={"file": ("mine.png", b"\x89PNG\r\n\x1a\n" + b"a real document" * 20)})
        assert own.status_code == 403
        sample = demo.post(f"/api/claims/{shown['id']}/estate/documents", data={"kind": "death_certificate"},
                           files={"file": ("sample.png", SAMPLE)})
        assert sample.status_code != 403
        # a holder file of one's own is never taken, whatever the key
        own_list = demo.post("/api/holder/list", headers=AS_PAYER,
                             files={"file": ("mine.csv", b"Name,Amount\nA Person,100\n", "text/csv")})
        assert own_list.status_code == 403
