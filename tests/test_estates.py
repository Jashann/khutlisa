"""An owner who has died, end to end: the intake, the proof for each heir, the approval bound to the shares, and
the one settlement that pays every heir in their own currency. The model is a table and Airwallex is a fake;
every decision under test is code."""
import json
from collections import Counter
from decimal import Decimal

import pytest

from khutlisa import airwallex as awx
from khutlisa import claims as cl
from khutlisa import estate_settlement as es
from khutlisa import estates
from estate_helpers import (ANA, BANKS, CHILD_A, CHILD_T, DOCS, ELENA, FAMILY, GRAND, NAOMI, OWNER, PEDRO, SEEN, SPOUSE,
                            TOMAS, EstateWorld, add_doc, approve, civil, ok, open_estate, prove, settle)
from test_claims import PRIVATE
from test_proof import PNG, passport
from test_server import MARIA, ref

RULES = {"tolerance_percent": "0.5", "small_claim_usd": "250.00", "route_rule": "most_to_claimant", "deadline_days": 14}


@pytest.fixture
def world(tmp_path, monkeypatch):
    return EstateWorld(tmp_path, monkeypatch)


@pytest.fixture
def api(world):
    with world.client() as c:
        yield c


def by_id(view):
    return {h["id"]: h for h in view["heirs"]}


def legs(view, n=-1):
    return {l["heir"]: l for l in view["settlement"]["rounds"][n]["legs"]}


def transfers_to(world):
    """How many transfers were made to each account name. Nobody may be paid twice."""
    names = {b["id"]: b["beneficiary"]["bank_details"]["account_name"] for b in world.fake.beneficiaries}
    return Counter(names[t["beneficiary_id"]] for t in world.fake.transfers.values())


# ---- the intake and the shares ----------------------------------------------------------------------------------

def test_the_claimants_words_become_the_family_and_the_shares(api, world):
    view = open_estate(api)
    assert view["succession"]["computed"] and view["question"] is None
    assert {h["name"]: h["share"] for h in view["heirs"]} == {PEDRO: "1/3", ANA: "2/9", TOMAS: "2/9", NAOMI: "2/9"}
    assert [h["entitlement"] for h in view["heirs"]] == ["613.52", "409.01", "409.01", "409.01"]   # adds up to 1,840.55
    assert sum(Decimal(h["entitlement"]) for h in view["heirs"]) == Decimal(view["amount"])
    tree = {n["id"]: n for n in view["tree"]}
    assert tree["c3"]["alive"] is False and "share" not in tree["c3"] and tree["c3.1"]["parent"] == "c3"
    assert tree["c2"]["indicative_local"]["currency"] == "GBP"
    assert Decimal(tree["c2"]["indicative_local"]["amount"]) < Decimal(tree["c2"]["amount_usd"])    # pounds, not dollars x 1.33
    steps = {s["n"]: s for s in view["succession"]["steps"]}
    assert [steps[n]["section"] for n in tree["s1"]["steps"]] == ["6401(c)(3)(A)"]
    assert all(s["url"].startswith("https://leginfo.legislature.ca.gov/") for s in steps.values())
    assert "who that person's family is" in world.model["calls"][0]          # the model saw the words, once
    assert view["intake"]["language"] == "Spanish"


def test_a_follow_up_question_is_asked_for_what_the_rule_needs(tmp_path, monkeypatch):
    partial = {**FAMILY, "children": [FAMILY["children"][0], {"name": ELENA, "alive": False}],
               "follow_up_key": "children_of", "follow_up": "¿Elena dejó hijos?", "follow_up_english": "Did Elena leave children?"}
    world = EstateWorld(tmp_path, monkeypatch, family=partial)
    with world.client() as api:
        view = open_estate(api)
        assert not view["succession"]["computed"] and view["heirs"] == []
        q = view["question"]
        assert (q["key"], q["about"], q["question"], q["in_their_language"]) == ("children_of", "c2", "¿Elena dejó hijos?", True)
        assert "Did Elena Santos leave children" in q["english"].replace("has died. ", "")
        # the model asked about something else: the question the rule needs is shown, in English
        world.model["family"] = {**partial, "follow_up_key": "property", "follow_up": "¿Era dinero del matrimonio?"}
        view = ok(api.post(f"/api/claims/{view['claim_id']}/estate/intake", json={"text": "No lo se."}))
        assert view["question"]["key"] == "children_of" and view["question"]["in_their_language"] is False
        # the answer completes the family
        world.model["family"] = FAMILY
        view = ok(api.post(f"/api/claims/{view['claim_id']}/estate/intake",
                           json={"text": "Si, una hija, Naomi.", "earlier": "Mi esposa murio.", "question": q["question"]}))
        assert view["succession"]["computed"] and len(view["heirs"]) == 4
        assert "They answered: Si, una hija, Naomi." in world.model["calls"][-1]


def test_the_family_can_be_corrected_by_hand_and_a_refusal_is_shown_with_its_section(api):
    view = open_estate(api)
    family = {**view["family"], "unusual": ["stepchild_or_foster"]}
    view = ok(api.put(f"/api/claims/{view['claim_id']}/estate/family", json={"family": family}))
    assert not view["succession"]["computed"] and view["succession"]["refusal"]["section"] == "6454"
    assert view["heirs"] == []
    assert approve(api, view["claim_id"]).status_code == 409


def test_only_a_claim_by_an_heir_on_a_person_can_become_an_estate(api):
    own = ok(api.post("/api/claims", json={"record_id": ref(api, "P1"), "history": MARIA, "claimant": {
        "name": "Maria Luz Santos", "address": "14 Mango Avenue", "country": "PH", "email": "m@example.org",
        "relationship": "self"}}), 201)
    assert api.post(f"/api/claims/{own['id']}/estate").status_code == 409
    assert api.get(f"/api/claims/{own['id']}/estate").status_code == 404
    assert own["is_estate"] is False


# ---- the proof for each heir ------------------------------------------------------------------------------------

def test_each_heir_is_tied_to_the_owner_link_by_link(api):
    view = open_estate(api)
    cid = view["claim_id"]
    naomi = by_id(view)[GRAND]
    assert [l["label"] for l in naomi["links"]] == ["Elena Santos was a child of the owner", "Elena Santos has died",
                                                    "Child of Elena Santos"]
    assert all(l["status"] == "missing" for l in naomi["links"]) and not naomi["proven"]
    assert view["estate_proof"]["ready"] is False and view["payable"] == []
    for kind, word in DOCS["estate"] + DOCS[GRAND][:2]:
        add_doc(api, cid, kind, word)
    naomi = by_id(ok(api.get(f"/api/claims/{cid}/estate")))[GRAND]
    assert [l["status"] for l in naomi["links"]] == ["proven", "proven", "missing"]
    assert "A birth certificate of Naomi Santos Kato that names Elena Santos as a parent." in naomi["missing"]
    view = prove(api, cid)
    assert view["proof_ready"] and sorted(view["payable"]) == sorted([SPOUSE, CHILD_A, CHILD_T, GRAND])
    assert by_id(view)[SPOUSE]["links"][0]["facts"] == [f"The marriage certificate names {PEDRO} and {OWNER} as the two people married."]
    assert view["remaining_risk"].startswith("Khutlisa read these documents")
    assert by_id(view)[SPOUSE]["payee"]["account_number"].endswith("7771") and "0020100" not in json.dumps(view)


def test_a_certificate_that_names_someone_else_as_the_parent_proves_nothing(tmp_path, monkeypatch):
    seen = {**SEEN, "birth_ana": civil("birth certificate", [(ANA, "subject"), ("Rosa Santos", "mother"), (OWNER, "official")])}
    world = EstateWorld(tmp_path, monkeypatch, seen=seen)
    with world.client() as api:
        view = prove(api, open_estate(api)["claim_id"])
        ana = by_id(view)[CHILD_A]
        assert ana["links"][0]["status"] == "missing" and not ana["proven"] and CHILD_A in view["held"]
        assert sorted(view["payable"]) == sorted([SPOUSE, CHILD_T, GRAND])


def test_two_readings_that_disagree_on_the_people_hold_the_document(tmp_path, monkeypatch):
    other = civil("birth certificate", [(TOMAS, "subject"), ("Rosa Santos", "mother"), (PEDRO, "father")])
    world = EstateWorld(tmp_path, monkeypatch, seen={**SEEN, "birth_tomas": [SEEN["birth_tomas"], other]})
    with world.client() as api:
        view = prove(api, open_estate(api)["claim_id"])
        tomas = by_id(view)[CHILD_T]
        assert not tomas["proven"] and tomas["links"][0]["status"] in ("held", "missing")
        doc = next(d for d in view["documents"] if d["filename"] == "birth_tomas.png")
        assert {"name": OWNER, "role": "mother"} not in doc["people"]        # a person counts only if both readings saw them


def test_identification_must_be_the_heirs_own_government_photo_id(tmp_path, monkeypatch):
    seen = {**SEEN, "id_ana": {"document_type": "staff badge", "names": [ANA], "holder_name": ANA, "issuer": "A Hospital"},
            "id_tomas": passport("SANTOS", "TOMAS", country="United Kingdom", state="GBR", authority="HM Passport Office",
                                 issued="2010-01-01", expires="2020-01-01")}
    world = EstateWorld(tmp_path, monkeypatch, seen=seen)
    with world.client() as api:
        view = prove(api, open_estate(api)["claim_id"])
        heirs = by_id(view)
        assert not heirs[CHILD_A]["proven"] and heirs[CHILD_A]["identity"]["status"] == "not proven"
        assert not heirs[CHILD_T]["proven"] and any("expired" in p.lower() for p in heirs[CHILD_T]["identity"]["problems"])
        assert heirs[SPOUSE]["proven"] and heirs[GRAND]["proven"]


def test_the_death_certificate_must_be_the_owners_and_forty_days_old(tmp_path, monkeypatch):
    recent = civil("death certificate", [(OWNER, "subject")], date_of_death="2026-11-01", issue_date="2026-11-05")
    world = EstateWorld(tmp_path, monkeypatch, family={**FAMILY, "decedent": {**FAMILY["decedent"], "died_on": "2026-11-01"}},
                        seen={**SEEN, "death_owner": recent, "death_other": civil("death certificate", [("Rosa Santos", "subject")],
                                                                                    date_of_death="2020-01-01")})
    with world.client() as api:
        view = open_estate(api)
        cid = view["claim_id"]
        view = add_doc(api, cid, "death_certificate", "death_other")
        items = {i["key"]: i for i in view["estate_proof"]["items"]}
        assert items["death"]["status"] == "missing" and items["forty_days"]["status"] == "missing"
        view = add_doc(api, cid, "death_certificate", "death_owner")
        items = {i["key"]: i for i in view["estate_proof"]["items"]}
        if (estates.date.today() - estates.date(2026, 11, 1)).days < 40:
            assert items["death"]["status"] == "proven" and items["forty_days"]["status"] == "not proven"
            assert "The declaration needs 40." in items["forty_days"]["problems"][0]
            assert approve(api, cid).status_code == 409


def test_the_person_who_died_must_be_the_owner_on_the_record(tmp_path, monkeypatch):
    world = EstateWorld(tmp_path, monkeypatch, family={**FAMILY, "decedent": {**FAMILY["decedent"], "name": "Rosa Delgado"}})
    with world.client() as api:
        view = open_estate(api)
        owner = view["estate_proof"]["items"][0]
        assert owner["key"] == "owner" and owner["status"] == "not proven"
        assert not any(word in json.dumps(view) for word in PRIVATE)          # nothing of the private record leaks


def test_the_declaration_is_needed_without_a_court_order(api):
    view = open_estate(api)
    cid = view["claim_id"]
    view = prove(api, cid)
    ok(api.put(f"/api/claims/{cid}/estate/heirs/{CHILD_A}", json={"declared": False}))
    view = ok(api.get(f"/api/claims/{cid}/estate"))
    ana = by_id(view)[CHILD_A]
    assert not ana["proven"] and "The heir's statement of the declaration's points." in ana["missing"]
    assert "13101" in view["declaration"]["note"]


def test_a_court_order_names_the_shares_and_the_document_must_show_them(tmp_path, monkeypatch):
    family = {"decedent": FAMILY["decedent"], "disposition": "court_order", "language": "English", "english": "",
              "named_shares": [{"name": ANA, "share": "3/4", "relation": "daughter", "country": "PH"},
                               {"name": TOMAS, "share": "1/4", "relation": "son", "country": "GB"}]}
    order = civil("final decree of distribution", [(ANA, "heir"), (TOMAS, "heir"), ("Judge Lee", "official")],
                  shares=[{"name": ANA, "share": "75%"}, {"name": TOMAS, "share": "25%"}])
    wrong = civil("final decree of distribution", [(ANA, "heir"), (TOMAS, "heir")],
                  shares=[{"name": ANA, "share": "1/2"}, {"name": TOMAS, "share": "1/2"}])
    world = EstateWorld(tmp_path, monkeypatch, family=family, seen={**SEEN, "order": order, "wrongorder": wrong})
    with world.client() as api:
        view = open_estate(api)
        cid = view["claim_id"]
        assert {h["name"]: h["share"] for h in view["heirs"]} == {ANA: "3/4", TOMAS: "1/4"}
        assert view["succession"]["steps"][0]["section"] == "6400"
        add_doc(api, cid, "death_certificate", "death_owner")
        view = add_doc(api, cid, "heirship", "wrongorder")
        assert {i["key"]: i["status"] for i in view["estate_proof"]["items"]}["basis"] == "missing"
        view = add_doc(api, cid, "heirship", "order")
        items = {i["key"]: i["status"] for i in view["estate_proof"]["items"]}
        assert items["basis"] == "proven" and "forty_days" not in items
        assert by_id(view)["n1"]["links"][0]["status"] == "proven" and by_id(view)["n1"]["declaration"]["needed"] is False


def test_bank_account_must_be_in_the_heirs_own_name(api):
    cid = open_estate(api)["claim_id"]
    r = api.put(f"/api/claims/{cid}/estate/heirs/{CHILD_A}/payee", json=BANKS[SPOUSE])
    assert r.status_code == 422 and "own name" in r.json()["detail"]
    r = api.put(f"/api/claims/{cid}/estate/heirs/{CHILD_T}/payee", json={**BANKS[CHILD_T], "sort_code": "12"})
    assert r.status_code == 422 and "sort code" in r.json()["detail"]
    assert api.put(f"/api/claims/{cid}/estate/heirs/nobody/payee", json=BANKS[SPOUSE]).status_code == 404


# ---- the approval is bound to the shares -------------------------------------------------------------------------

def approved(api):
    cid = open_estate(api)["claim_id"]
    prove(api, cid)
    return ok(approve(api, cid))


def test_the_approval_covers_the_shares_and_any_change_withdraws_it(api):
    view = approved(api)
    cid = view["claim_id"]
    assert view["state"] == cl.APPROVED
    assert view["approval"]["shares"] == {SPOUSE: "1/3", CHILD_A: "2/9", CHILD_T: "2/9", GRAND: "2/9"}
    assert all(view["approval"]["proven"].values())
    # the family changes: one child fewer, so every share changes
    family = {**view["family"], "children": view["family"]["children"][:2]}
    view = ok(api.put(f"/api/claims/{cid}/estate/family", json={"family": family}))
    assert view["approval"] is None and view["state"] != cl.APPROVED
    assert "the family or the shares were changed" in view["approvals_withdrawn"][-1]["because"]
    assert api.post(f"/api/claims/{cid}/estate/settlement/plan").status_code == 409


def test_a_new_document_or_a_new_bank_account_withdraws_the_approval(api):
    view = approved(api)
    cid = view["claim_id"]
    view = add_doc(api, cid, "birth_certificate", "birth_ana")
    assert view["approval"] is None and "a document was added" in view["approvals_withdrawn"][-1]["because"]
    ok(approve(api, cid))
    other = {**BANKS[CHILD_A], "account_number": "9876543210"}
    view = ok(api.put(f"/api/claims/{cid}/estate/heirs/{CHILD_A}/payee", json=other))
    assert view["approval"] is None and "bank account" in view["approvals_withdrawn"][-1]["because"]
    ok(approve(api, cid))
    doc = next(d for d in view["documents"] if d["filename"] == "id_tomas.png")
    ok(api.delete(f"/api/claims/{cid}/documents/{doc['id']}"))
    view = ok(api.get(f"/api/claims/{cid}/estate"))
    assert view["approval"] is None and not by_id(view)[CHILD_T]["proven"]


def test_an_estate_is_approved_and_paid_only_through_its_own_routes(api):
    cid = open_estate(api)["claim_id"]
    prove(api, cid)
    r = api.post(f"/api/payer/claims/{cid}/approve")
    assert r.status_code == 409 and "estate view" in r.json()["detail"]
    ok(approve(api, cid))
    r = api.post(f"/api/claims/{cid}/payout/plan")
    assert r.status_code == 409 and "one settlement" in r.json()["detail"]
    assert api.get("/api/payer/estates", headers={"X-Payer-Key": "wrong"}).status_code == 401
    rows = ok(api.get("/api/payer/estates"))["estates"]
    assert len(rows) == 1 and rows[0]["payable"] == 4 and rows[0]["owner"] == "S··· M··· L···"
    queue = ok(api.get("/api/payer/queue"))["claims"]
    assert queue[0]["is_estate"] is True


def test_an_owner_who_lived_elsewhere_needs_a_recorded_reason(tmp_path, monkeypatch):
    abroad = {**FAMILY, "decedent": {**FAMILY["decedent"], "domicile_country": "MX", "domicile_state": ""}}
    world = EstateWorld(tmp_path, monkeypatch, family=abroad)
    with world.client() as api:
        view = open_estate(api)
        cid = view["claim_id"]
        assert view["succession"]["computed"] and view["succession"]["needs_person"]
        assert "has not decided which law applies" in view["other_law"]["flag"]["text"]
        prove(api, cid)
        r = approve(api, cid)
        assert r.status_code == 409 and "other law may apply" in r.json()["detail"]
        assert approve(api, cid, other_law_reason="short").status_code == 409
        view = ok(approve(api, cid, other_law_reason="Our counsel advised that California law governs wages earned here."))
        assert view["state"] == cl.APPROVED and "counsel advised" in view["other_law"]["acknowledged"]["reason"]


def test_a_check_added_by_another_module_stops_approval_and_payment(api, world):
    """rings.py adds its checks to these lists; an estate obeys them like any claim."""
    cid = open_estate(api)["claim_id"]
    prove(api, cid)

    def held(claim):
        raise cl.ClaimError(409, "This claim is held: it is linked to other claims.")

    world.app.state.claims.approval_checks.append(held)
    assert "linked to other claims" in approve(api, cid).json()["detail"]
    world.app.state.claims.approval_checks.clear()
    ok(approve(api, cid))
    world.app.state.claims.payment_checks.append(held)
    r = api.post(f"/api/claims/{cid}/estate/settlement/plan")
    assert r.status_code == 409 and "linked to other claims" in r.json()["detail"]
    assert world.fake.transfers == {} and world.fake.deposits == []


# ---- the settlement -----------------------------------------------------------------------------------------------

def test_every_heir_is_paid_in_their_own_currency_in_one_settlement(api, world):
    ok(api.put("/api/payer/instructions", json=RULES))
    view = approved(api)
    cid = view["claim_id"]
    planned = ok(api.post(f"/api/claims/{cid}/estate/settlement/plan"))
    plan = planned["settlement"]["plan"]
    assert world.fake.deposits == [] and world.fake.transfers == {}            # a plan moves nothing
    assert {l["currency"] for l in plan["legs"]} == {"MXN", "PHP", "GBP", "JPY"}
    assert sum(Decimal(v) for v in plan["entitlements"].values()) == Decimal("1840.55")
    assert sum(Decimal(l["leg_usd"]) for l in plan["legs"]) == Decimal(plan["net"])
    assert Decimal(plan["holder_sends"]) - Decimal(plan["expected_incoming_fee"]) == Decimal(plan["net"])
    assert not any(l["covered"] for l in plan["legs"]) and plan["holder_sends"] == "1840.55"   # every share is above 250
    pounds = next(l for l in plan["legs"] if l["currency"] == "GBP")
    assert Decimal(pounds["expected_local"]["amount"]) < Decimal(pounds["leg_usd"])
    assert [c["kind"] for c in planned["settlement"]["plan_cards"]] == ["estate_split", "estate_fees"]
    r = api.post(f"/api/claims/{cid}/estate/settlement/confirm", json={"plan_id": "not-the-plan"})
    assert r.status_code == 409

    view = settle(api, cid)
    assert view["state"] == cl.PAID
    done = legs(view)
    assert {l["state"] for l in done.values()} == {awx.PAID} and len(done) == 4
    assert all(l["received"]["currency"] == l["currency"] for l in done.values())
    assert len(world.fake.deposits) == 1 and world.fake.deposits[0]["amount"] == 1840.55
    assert world.fake.deposits[0]["reference"] == f"KHUTLISA-{cid}-S1"
    assert transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 1, NAOMI: 1}
    # what was sent adds up to exactly what Airwallex held after its fee, and every currency comes to zero
    assert sum(Decimal(l["leg_usd"]) for l in done.values()) == Decimal("1840.55") - Decimal("5.52")
    rec = view["settlement"]["reconciliation"]
    assert rec["balanced"] and {s["currency"] for s in rec["sums"]} == {"USD", "MXN", "GBP", "JPY"}
    assert all(Decimal(s["left"]) == 0 for s in rec["sums"])
    assert "adds up to zero in every currency" in rec["statement"]
    assert all(h["paid"] for h in view["heirs"]) and "Every heir of this estate has been paid" in view["history"][-1]["note"]
    assert round(sum(world.fake.balance.values()), 2) == 0
    assert "0020100777" not in json.dumps(view) and "55779911" not in json.dumps(view)
    # asking again changes nothing: no second deposit, no second transfer
    assert api.post(f"/api/claims/{cid}/estate/settlement/plan").status_code == 409
    ok(api.post(f"/api/claims/{cid}/estate/settlement/resume"))
    api.app.state.estates.join(cid)
    assert len(world.fake.deposits) == 1 and len(world.fake.transfers) == 4


def test_the_holder_bears_the_fees_of_a_small_share(tmp_path, monkeypatch):
    world = EstateWorld(tmp_path, monkeypatch)
    with world.client() as api:
        ok(api.put("/api/payer/instructions", json={**RULES, "small_claim_usd": "500.00"}))
        cid = open_estate(api)["claim_id"]
        prove(api, cid)
        ok(approve(api, cid))
        plan = ok(api.post(f"/api/claims/{cid}/estate/settlement/plan"))["settlement"]["plan"]
        covered = {l["heir"]: l["covered"] for l in plan["legs"]}
        assert covered == {SPOUSE: False, CHILD_A: True, CHILD_T: True, GRAND: True}       # 409.01 is below 500, 613.52 is not
        assert Decimal(plan["holder_sends"]) > Decimal("1840.55") and Decimal(plan["holder_adds"]) > 15
        ana = next(l for l in plan["legs"] if l["heir"] == CHILD_A)
        assert Decimal(ana["leg_usd"]) >= Decimal("409.01") + Decimal("5.00")              # the whole share, plus the payout fee
        view = settle(api, cid)
        assert view["state"] == cl.PAID and view["settlement"]["reconciliation"]["balanced"]
        assert world.fake.deposits[0]["amount"] == float(plan["holder_sends"])


def test_an_unproven_heir_is_held_and_paid_in_a_second_round(api, world):
    cid = open_estate(api)["claim_id"]
    view = prove(api, cid, who=(SPOUSE, CHILD_A, CHILD_T))
    assert view["held"] == [GRAND]
    view = ok(approve(api, cid))
    assert "is held until proven" in view["history"][-1]["note"]
    planned = ok(api.post(f"/api/claims/{cid}/estate/settlement/plan"))["settlement"]
    plan = planned["plan"]
    assert [h["heir"] for h in plan["held"]] == [GRAND] and plan["held_total"] == "409.01"
    assert plan["holder_sends"] == "1431.54" and plan["paying_total"] == "1431.54"        # the held share is not sent
    assert planned["plan_cards"][-1]["kind"] == "estate_held" and NAOMI in planned["plan_cards"][-1]["money"]
    view = settle(api, cid)
    assert view["state"] == cl.PAYMENT_HELD and view["approval"] is None
    assert f"the share of {NAOMI} is held until that heir is proven" in view["approvals_withdrawn"][-1]["because"]
    assert transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 1}
    assert view["settlement"]["reconciliation"]["balanced"]                                # nothing idle at Airwallex
    assert by_id(view)[GRAND]["paid"] is None and by_id(view)[SPOUSE]["paid"]["currency"] == "MXN"
    # nothing more can be planned until the heir is proven and the holder approves again
    assert api.post(f"/api/claims/{cid}/estate/settlement/plan").status_code == 409
    assert approve(api, cid).status_code == 409
    # the family can no longer be redrawn: shares have been paid
    r = api.put(f"/api/claims/{cid}/estate/family", json={"family": {**view["family"], "children": []}})
    assert r.status_code == 409 and "already been paid" in r.json()["detail"]

    view = prove(api, cid, who=(GRAND,))
    assert view["payable"] == [GRAND]
    view = ok(approve(api, cid))
    assert view["state"] == cl.PAYING
    view = settle(api, cid)
    assert view["state"] == cl.PAID and len(view["settlement"]["rounds"]) == 2
    assert list(legs(view)) == [GRAND] and world.fake.deposits[1]["amount"] == 409.01
    assert transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 1, NAOMI: 1}                   # nobody twice
    assert view["settlement"]["reconciliation"]["balanced"]


def test_one_refused_transfer_never_blocks_or_double_pays_the_others(api, world):
    ok(api.put("/api/payer/instructions", json=RULES))
    cid = approved(api)["claim_id"]
    view = settle(api, cid, fail_heir=CHILD_T)
    done = legs(view)
    assert {h: l["state"] for h, l in done.items()} == {SPOUSE: awx.PAID, CHILD_A: awx.PAID, GRAND: awx.PAID,
                                                         CHILD_T: awx.FAILED}
    tomas = done[CHILD_T]
    # Airwallex keeps its payout fee and charges it again: on a share of about 400 dollars that is more than
    # half a percent, so under the holder's tolerance the family is asked to agree to the replacement.
    assert tomas["hold"]["needs"] == ["bank_details", "payer", "claimant"]
    assert tomas["hold"]["replacement"]["family_asked"] is True and tomas["funds"]["currency"] == "GBP"
    assert view["state"] == cl.PAYMENT_HELD
    assert f"the bank refused the transfer to {TOMAS}" in view["approvals_withdrawn"][-1]["because"]
    rec = view["settlement"]["reconciliation"]
    assert not rec["balanced"] and rec["accounted_for"]                # all that is left is Tomas's pounds, and it says so
    assert [(s["currency"], Decimal(s["left"])) for s in rec["sums"] if Decimal(s["left"]) != 0] == \
        [("GBP", Decimal(tomas["funds"]["amount"]))]
    assert f"for {TOMAS}" in rec["statement"]
    assert any("The other heirs are not held up." in e["text"] for e in view["settlement"]["rounds"][-1]["events"])
    assert transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 1, NAOMI: 1}

    # the holder cannot approve before the heir has corrected the account
    r = approve(api, cid)
    assert r.status_code == 409 and "not yet corrected the bank account" in r.json()["detail"]
    # the corrected account must take the currency the money is already in
    assert api.put(f"/api/claims/{cid}/estate/heirs/{CHILD_T}/payee",
                   json={**BANKS[CHILD_A], "first_name": "Tomas"}).status_code == 409
    assert api.post(f"/api/claims/{cid}/estate/settlement/heirs/{CHILD_T}/agree").status_code == 409
    ok(api.put(f"/api/claims/{cid}/estate/heirs/{CHILD_T}/payee", json={**BANKS[CHILD_T], "account_number": "31926819"}))
    view = ok(approve(api, cid))
    api.app.state.estates.join(cid)
    assert len(world.fake.transfers) == 4                              # still waiting for the family: nothing was sent
    ok(api.post(f"/api/claims/{cid}/estate/settlement/heirs/{CHILD_T}/agree"))
    api.app.state.estates.join(cid)
    view = ok(api.get(f"/api/claims/{cid}/estate"))
    assert view["state"] == cl.PAID and legs(view)[CHILD_T]["state"] == awx.PAID
    assert legs(view)[CHILD_T]["account"]["number"].endswith("6819") and len(legs(view)[CHILD_T]["attempts"]) == 1
    assert transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 2, NAOMI: 1}                    # one replacement, nobody else touched
    dead = [t for t in world.fake.transfers.values() if t["status"] in ("FAILED", "CANCELLED")]
    assert len(dead) == 1 and len([t for t in world.fake.transfers.values() if t["status"] == "PAID"]) == 4
    assert view["settlement"]["reconciliation"]["balanced"]
    assert len(world.fake.deposits) == 1


def test_a_replacement_inside_the_tolerance_does_not_ask_the_family_again(api, world):
    """The same refusal on a larger estate (row P3, 5,120.00 US dollars): the second payout fee is under half a
    percent of the share, so the corrected account and the holder's approval are all that is needed."""
    ok(api.put("/api/payer/instructions", json=RULES))
    cid = open_estate(api, record="P3")["claim_id"]
    prove(api, cid)
    ok(approve(api, cid))
    view = settle(api, cid, fail_heir=SPOUSE)
    pedro = legs(view)[SPOUSE]
    assert pedro["hold"]["needs"] == ["bank_details", "payer"] and pedro["hold"]["replacement"]["family_asked"] is False
    assert any(d["kind"] == "replacement_within_tolerance" for d in pedro["decisions"])
    ok(api.put(f"/api/claims/{cid}/estate/heirs/{SPOUSE}/payee", json={**BANKS[SPOUSE], "account_number": "002010077777777823"}))
    ok(approve(api, cid))
    api.app.state.estates.join(cid)
    view = ok(api.get(f"/api/claims/{cid}/estate"))
    assert view["state"] == cl.PAID and transfers_to(world)[PEDRO] == 2
    assert view["settlement"]["reconciliation"]["balanced"]


def test_an_error_on_one_heirs_payout_does_not_stop_the_others(api, world):
    cid = approved(api)["claim_id"]
    world.fake.refuse_beneficiary_named = "Ana Santos"
    api.app.state.estates.max_idle = 3
    view = settle(api, cid)
    done = legs(view)
    assert {h: l["state"] for h, l in done.items() if h != CHILD_A} == {SPOUSE: awx.PAID, CHILD_T: awx.PAID, GRAND: awx.PAID}
    assert done[CHILD_A]["state"] != awx.PAID and "Airwallex refused a step" in done[CHILD_A]["problem"]
    assert view["state"] == cl.PAYING and transfers_to(world) == {PEDRO: 1, TOMAS: 1, NAOMI: 1}
    world.fake.refuse_beneficiary_named = None
    ok(api.post(f"/api/claims/{cid}/estate/settlement/resume"))
    api.app.state.estates.join(cid)
    view = ok(api.get(f"/api/claims/{cid}/estate"))
    assert view["state"] == cl.PAID and transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 1, NAOMI: 1}
    assert view["settlement"]["reconciliation"]["balanced"]


def test_a_restart_in_the_middle_pays_nobody_twice(tmp_path, monkeypatch):
    world = EstateWorld(tmp_path, monkeypatch)
    with world.client() as api:
        cid = approved(api)["claim_id"]
        plan = ok(api.post(f"/api/claims/{cid}/estate/settlement/plan"))["settlement"]["plan"]
        runner = api.app.state.estates
        monkeypatch.setattr(runner, "start", lambda claim_id: None)           # the server "stops" before doing anything
        ok(api.post(f"/api/claims/{cid}/estate/settlement/confirm", json={"plan_id": plan["id"]}))
        path = runner.path(cid)
    # step by step, loading the files afresh each time, as a restarted server would
    client, simulator = world.factory()
    for _ in range(60):
        settlement = es.Settlement.open(path, cid)
        if es.idle(settlement):
            break
        es.step(settlement, client, simulator)
        es.step(es.Settlement.open(path, cid), client, simulator)             # and a second server doing the same
    settlement = es.Settlement.open(path, cid)
    assert settlement.round["state"] == es.DONE and len(settlement.paid_heirs()) == 4
    assert len(world.fake.deposits) == 1 and len(world.fake.transfers) == 4 and len(world.fake.conversions) == 3
    assert transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 1, NAOMI: 1}
    world.app = world.make_app()                                             # a new server picks the claim up
    with world.client() as api:
        api.app.state.estates.join(cid)
        ok(api.post(f"/api/claims/{cid}/estate/settlement/resume"))
        view = ok(api.get(f"/api/claims/{cid}/estate"))
        assert len(view["settlement"]["paid"]) == 4 and len(world.fake.transfers) == 4


def test_a_rate_that_moves_beyond_the_tolerance_stops_that_heir_only(tmp_path, monkeypatch):
    world = EstateWorld(tmp_path, monkeypatch)
    with world.client() as api:
        ok(api.put("/api/payer/instructions", json=RULES))
        cid = approved(api)["claim_id"]
        plan = ok(api.post(f"/api/claims/{cid}/estate/settlement/plan"))["settlement"]["plan"]
        world.fake.incoming_fee_rate = 0.0031          # a slightly different fee: every leg needs a new quote
        world.fake.rates["JPY"] = 150.0                # and the yen has fallen by more than half a percent
        ok(api.post(f"/api/claims/{cid}/estate/settlement/confirm", json={"plan_id": plan["id"]}))
        api.app.state.estates.join(cid)
        view = ok(api.get(f"/api/claims/{cid}/estate"))
        done = legs(view)
        assert done[GRAND]["state"] == awx.HELD and done[GRAND]["hold"]["needs"] == ["claimant"]
        assert {done[h]["state"] for h in (SPOUSE, CHILD_A, CHILD_T)} == {awx.PAID}
        assert any(d["kind"] == "requoted" for d in done[SPOUSE]["decisions"])     # inside the tolerance: carried on, noted
        assert view["state"] == cl.PAYING
        ok(api.post(f"/api/claims/{cid}/estate/settlement/heirs/{GRAND}/agree"))
        api.app.state.estates.join(cid)
        view = ok(api.get(f"/api/claims/{cid}/estate"))
        assert view["state"] == cl.PAID and view["settlement"]["reconciliation"]["balanced"]


def test_a_deposit_that_differs_stops_everything_until_approved_again(tmp_path, monkeypatch):
    world = EstateWorld(tmp_path, monkeypatch)
    with world.client() as api:
        cid = approved(api)["claim_id"]
        plan = ok(api.post(f"/api/claims/{cid}/estate/settlement/plan"))["settlement"]["plan"]
        real = world.fake.route

        def short(method, path, body, params):       # the holder sends 85 percent of what was planned
            if path == "/api/v1/simulation/deposit/create":
                body = {**body, "amount": round(body["amount"] * 0.85, 2)}
            return real(method, path, body, params)

        monkeypatch.setattr(world.fake, "route", short)
        ok(api.post(f"/api/claims/{cid}/estate/settlement/confirm", json={"plan_id": plan["id"]}))
        api.app.state.estates.join(cid)
        view = ok(api.get(f"/api/claims/{cid}/estate"))
        rnd = view["settlement"]["rounds"][-1]
        assert rnd["state"] == es.HELD and "Nothing has been converted or sent to anyone" in rnd["held_because"]
        assert world.fake.transfers == {} and world.fake.conversions == [] and view["state"] == cl.PAYMENT_HELD
        ok(approve(api, cid))
        view = ok(api.post(f"/api/claims/{cid}/estate/settlement/plan"))
        again = view["settlement"]["rounds"][-1]
        assert again["state"] == es.HELD
        settlement = api.app.state.estates.load(cid)
        replan = settlement.round["replan"]
        assert replan["on_what_arrived"] and Decimal(replan["net"]) == Decimal(rnd["arrived"]["net"])
        ok(api.post(f"/api/claims/{cid}/estate/settlement/confirm", json={"plan_id": replan["id"]}))
        api.app.state.estates.join(cid)
        view = ok(api.get(f"/api/claims/{cid}/estate"))
        assert view["state"] == cl.PAID and len(world.fake.deposits) == 1 and len(world.fake.transfers) == 4
        assert view["settlement"]["reconciliation"]["balanced"]
        assert sum(Decimal(l["leg_usd"]) for l in legs(view).values()) == Decimal(rnd["arrived"]["net"])


def test_the_estate_view_never_shows_a_stored_file_or_the_private_record(api):
    cid = open_estate(api)["claim_id"]
    view = prove(api, cid)
    text = json.dumps(view)
    assert "stored_as" not in text and "sha256" not in text and not any(word in text for word in PRIVATE)
    claim = ok(api.get(f"/api/claims/{cid}"))
    assert "estate" not in claim and claim["is_estate"] is True


def test_a_refusal_whose_money_has_not_come_back_is_waited_for_and_said_plainly(tmp_path, monkeypatch):
    """Seen on the live sandbox with pounds: the transfer reads FAILED and no refund row is booked. Nothing is
    sent again on money that has not returned, the other heirs are paid, and the books say what is outstanding."""
    world = EstateWorld(tmp_path, monkeypatch)
    with world.client() as api:
        cid = approved(api)["claim_id"]
        monkeypatch.setattr(world.fake, "bank_refuses", lambda transfer_id, status="FAILED": world.fake.transfers[transfer_id].update(
            status=status, failure_type="INCORRECT_ROUTING", failure_reason="90101: Invalid account name/number"))
        api.app.state.estates.max_idle = 3
        view = settle(api, cid, fail_heir=CHILD_T)
        done = legs(view)
        assert done[CHILD_T]["refused_not_back"] is True and done[CHILD_T]["state"] != awx.PAID and done[CHILD_T]["hold"] is None
        assert {done[h]["state"] for h in (SPOUSE, CHILD_A, GRAND)} == {awx.PAID}
        rec = view["settlement"]["reconciliation"]
        assert not rec["balanced"] and not rec["accounted_for"] and rec["outstanding"][0]["name"] == TOMAS
        assert "has not booked the money back yet" in rec["statement"]
        assert any("Airwallex has not booked the money back yet" in e["text"] for e in view["settlement"]["rounds"][-1]["events"])
        assert transfers_to(world) == {PEDRO: 1, ANA: 1, TOMAS: 1, NAOMI: 1} and view["state"] == cl.PAYING
        # no corrected account can be given, and nothing can be approved, while the money is still out
        assert api.put(f"/api/claims/{cid}/estate/heirs/{CHILD_T}/payee", json=BANKS[CHILD_T]).status_code == 409
