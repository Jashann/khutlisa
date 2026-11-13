"""Rings through the real API: the fingerprint kept at creation, holds that block approval and payment, an approval
suspended when a later claim completes a ring, the record when money had already left, release with a reason and
a new hold only on a new signal, masking, and the holder's key. Built the way tests/test_claims.py builds its app."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from khutlisa import rings
from khutlisa.server import create_app
from test_claims import AS_PAYER, CLAIMANT, MX_BANK, PH_BANK, World, give_bank, open_claim, plan_and_agree

# Three invented claimants whose names all contain the account holder's name, which the server asks of an account.
ANA = CLAIMANT                                                                        # Maria Luz Santos
BELA = {**CLAIMANT, "name": "Maria Santos Reyes", "email": "bela@elsewhere.example",
        "address": "9 Narra Road, Davao City 8000"}
CORA = {**CLAIMANT, "name": "Maria Consuelo Santos", "email": "cora@third.example",
        "address": "300 Acacia Street, Iloilo City 5000"}


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture
def api(world):
    with TestClient(world.app, headers=AS_PAYER) as c:
        yield c


def risk(api):
    r = api.get("/api/payer/risk")
    assert r.status_code == 200, r.text
    return r.json()


def status(api, claim_id):
    return next(c for c in risk(api)["claims"] if c["id"] == claim_id)["status"]


def on_disk(world, claim_id):
    return json.loads((world.folder / "claims" / f"{claim_id}.json").read_text())


def ring_of_two(api):
    """Two claimants on two properties, paid into one bank account."""
    a, b = open_claim(api, "P1", ANA), open_claim(api, "P4", BELA)
    give_bank(api, a["id"])
    give_bank(api, b["id"])
    return a["id"], b["id"]


# ---- the key ---------------------------------------------------------------------------------------------------

def test_nothing_in_the_risk_api_answers_without_the_holders_key(world):
    with TestClient(world.app) as anyone:
        claim = open_claim(anyone)
        assert anyone.get("/api/payer/risk").status_code == 401
        assert anyone.get("/api/payer/risk", headers={"X-Payer-Key": "wrong"}).status_code == 401
        release = f"/api/payer/risk/claims/{claim['id']}/release"
        assert anyone.post(release, json={"reason": "Looks fine to me."}).status_code == 401
        assert anyone.post(release, json={"reason": "Looks fine."}, headers={"X-Payer-Key": "wrong"}).status_code == 401
        assert anyone.get("/api/payer/risk", headers=AS_PAYER).status_code == 200
    locked = create_app(db_path=world.db, totals_path=world.folder / "totals.json", web_dist=world.folder / "no-web",
                        claims_dir=world.folder / "locked-claims", airwallex_factory=world.factory, payer_key="",
                        watch_seconds=0)
    with TestClient(locked) as c:                           # no key set on the server: locked for everyone
        assert c.get("/api/payer/risk", headers=AS_PAYER).status_code == 401


# ---- the fingerprint -------------------------------------------------------------------------------------------

def test_a_new_claim_keeps_a_keyed_hash_of_where_it_came_from_and_never_the_address(world):
    with TestClient(world.app, client=("203.0.113.77", 51000), headers={"User-Agent": "Sample Browser 1.0"}) as first:
        a = open_claim(first, "P1", ANA)
        b = open_claim(first, "P4", BELA)
    with TestClient(world.app, client=("198.51.100.5", 51000), headers={"User-Agent": "Sample Browser 1.0"}) as second:
        c = open_claim(second, "P5", CORA)
        assert "origin" not in c and "risk" not in c                          # the claimant never sees either
        assert "origin" not in second.get(f"/api/claims/{c['id']}").json()
    origins = [on_disk(world, x["id"])["origin"] for x in (a, b, c)]
    assert all(re.fullmatch(r"[0-9a-f]{16}", o["network"]) and re.fullmatch(r"[0-9a-f]{16}", o["agent"]) for o in origins)
    assert origins[0]["network"] == origins[1]["network"] != origins[2]["network"]
    assert origins[0]["agent"] == origins[2]["agent"]                         # the same browser line
    everything = "".join(p.read_text() for p in (world.folder / "claims").glob("*.json"))
    assert "203.0.113.77" not in everything and "198.51.100.5" not in everything and "Sample Browser" not in everything
    # the hash is keyed with a salt kept beside the claims, so it cannot be matched to an address without it
    salt = (world.folder / "claims" / "origin_salt.txt").read_text()
    assert len(salt) == 32 and rings.Rings(world.app.state.claims).fingerprint("203.0.113.77", "x")["network"] == origins[0]["network"]
    with TestClient(world.app, headers={"X-Forwarded-For": "203.0.113.77"}) as proxied:
        d = open_claim(proxied, "P6", {**CORA, "name": "Rosa Lind"})
    assert on_disk(world, d["id"])["origin"]["network"] == ""                 # behind a proxy no address is kept
    # the claims so far share a device or a network at most, which holds nothing
    with TestClient(world.app, headers=AS_PAYER) as holder:
        view = risk(holder)
    assert view["counts"]["held"] == 0 and all(not g["flagged"] for g in view["groups"])


# ---- holds -----------------------------------------------------------------------------------------------------

def test_a_claim_in_a_flagged_group_cannot_be_approved_and_says_why(api, world):
    a, b = ring_of_two(api)
    view = risk(api)
    assert view["counts"] == {**view["counts"], "claims": 2, "groups_flagged": 1, "held": 2, "suspended": 0,
                              "held_usd": round(1840.55 + 610.00, 2)}
    (group,) = view["groups"]
    assert group["flagged"] and group["points"] >= 60 and {n["status"] for n in group["nodes"]} == {"held"}
    assert group["points"] == sum(row["points"] for row in group["table"])
    card = group["card"]
    assert set(card) >= {"kind", "tone", "title", "happened", "allowed", "did", "money", "why"}
    assert card["kind"] == "ring_hold" and card["tone"] == "stop" and "not yours to switch off" in card["allowed"]
    assert card["did"] == "Held 2 claims before any money moved." and card["money"] == "$2,450.55 held."
    for claim_id in (a, b):
        r = api.post(f"/api/payer/claims/{claim_id}/approve")
        assert r.status_code == 409 and "This claim is held" in r.json()["detail"]
        assert "the same bank account" in r.json()["detail"] and "release" in r.json()["detail"]
        stored = on_disk(world, claim_id)
        assert stored["state"] == "PROOF_NEEDED" and stored["approval"] is None
        assert stored["risk"]["status"] == "held" and stored["risk"]["since"]
        notes = [e["note"] for e in stored["history"] if "Held by the fixed safety rule" in e["note"]]
        assert len(notes) == 1                                                # written once, however often it is looked at
    # the holder's queue row carries the state too
    rows = {row["id"]: row for row in api.get("/api/payer/queue").json()["claims"]}
    assert rows[a]["risk"]["status"] == "held"


def test_an_approval_given_before_the_ring_showed_is_suspended_and_no_payment_starts(api, world):
    a = open_claim(api, "P1", ANA)["id"]
    give_bank(api, a)
    assert api.post(f"/api/payer/claims/{a}/approve").json()["state"] == "APPROVED"      # alone, nothing is wrong
    assert status(api, a) == "clear"
    b = open_claim(api, "P4", BELA)["id"]
    give_bank(api, b)                                                                     # the same account: a ring
    assert status(api, a) == "suspended" and status(api, b) == "held"
    for _ in range(2):
        plan = api.post(f"/api/claims/{a}/payout/plan", json={})
        assert plan.status_code == 409 and plan.json()["detail"] == rings.HELD_FOR_CLAIMANT
    assert "account" not in rings.HELD_FOR_CLAIMANT and "linked" not in rings.HELD_FOR_CLAIMANT      # nothing about others
    stored = on_disk(world, a)
    assert stored["state"] == "APPROVED" and stored["approval"] is not None      # suspended, not withdrawn
    suspended = [e for e in stored["history"] if "approval is suspended" in e["note"]]
    assert len(suspended) == 1 and suspended[0]["at"] and stored["risk"]["events"][-1]["kind"] == "suspended"
    assert world.fake.count("POST", "/api/v1/simulation/deposit/create") == 0    # no money moved
    card = risk(api)["groups"][0]["card"]
    assert card["did"] == "Held 1 claim and suspended 1 approval before any money moved."
    # released by a person, the approval stands again and the payment can be planned
    assert api.post(f"/api/payer/risk/claims/{a}/release", json={"reason": "Her own account, checked by phone."}).status_code == 200
    assert api.post(f"/api/claims/{a}/payout/plan", json={}).status_code == 200


def test_money_that_had_already_left_is_recorded_and_the_rest_of_the_group_is_held(api, world):
    a = open_claim(api, "P1", ANA)["id"]
    give_bank(api, a)
    api.post(f"/api/payer/claims/{a}/approve")
    plan_and_agree(api, a)
    world.app.state.payouts.join(a)
    assert api.get(f"/api/claims/{a}").json()["state"] == "PAID"
    b = open_claim(api, "P4", BELA)["id"]
    give_bank(api, b)
    view = risk(api)
    assert status(api, a) == "paid_before" and status(api, b) == "held"
    assert view["counts"]["paid_before"] == 1 and view["counts"]["paid_before_usd"] == 1840.55
    assert view["counts"]["held"] == 1 and view["counts"]["held_usd"] == 610.00
    event = on_disk(world, a)["risk"]["events"][-1]
    assert event["kind"] == "paid_before" and event["amount"] == "1840.55" and event["currency"] == "USD" and event["at"]
    assert "$1,840.55 had already left" in event["note"] and "Nothing is called back" in event["note"]
    assert on_disk(world, a)["state"] == "PAID"                                # nothing is undone
    card = view["groups"][0]["card"]
    assert card["money"] == "$610.00 held. $1,840.55 had already left on 1 claim."
    assert api.post(f"/api/payer/claims/{b}/approve").status_code == 409


# ---- release ---------------------------------------------------------------------------------------------------

def test_a_release_needs_a_reason_and_is_recorded_and_only_a_new_signal_holds_the_claim_again(api, world):
    a, b = ring_of_two(api)
    risk(api)
    path = f"/api/payer/risk/claims/{a}/release"
    assert api.post(path, json={"reason": "ok"}).status_code == 422
    assert api.post(path, json={"reason": "x" * 501}).status_code == 422
    assert api.post(path, json={}).status_code == 422
    assert api.post("/api/payer/risk/claims/0123456789abcdef/release", json={"reason": "No such claim."}).status_code == 404
    released = api.post(path, json={"reason": "  Spoke to her. The account is her own.  "})
    assert released.status_code == 200
    view = released.json()
    row = next(c for c in view["claims"] if c["id"] == a)
    assert row["status"] == "released" and row["release"]["reason"] == "Spoke to her. The account is her own." and row["release"]["at"]
    assert view["counts"]["released"] == 1 and view["counts"]["held"] == 1
    assert {n["id"]: n["status"] for n in view["groups"][0]["nodes"]} == {a: "released", b: "held"}     # still in its group
    stored = on_disk(world, a)
    assert stored["risk"]["release"]["reason"] == "Spoke to her. The account is her own."
    assert "released this claim" in stored["history"][-1]["note"] and "Spoke to her" in stored["history"][-1]["note"]
    assert api.post(path, json={"reason": "Released twice."}).status_code == 409        # nothing left to release
    # looking again changes nothing: the links are the ones that were there at the release
    for _ in range(2):
        assert status(api, a) == "released" and status(api, b) == "held"
    assert api.post(f"/api/payer/claims/{a}/approve").json()["state"] == "APPROVED"
    assert api.post(f"/api/payer/claims/{b}/approve").status_code == 409
    assert status(api, a) == "released"                                          # and stays released once approved
    # a third claim on the same account is a new link: the released claim's approval is suspended
    c = open_claim(api, "P5", CORA)["id"]
    give_bank(api, c)
    assert status(api, a) == "suspended" and status(api, c) == "held"
    stored = on_disk(world, a)
    assert stored["risk"]["release"] and len(stored["risk"]["releases"]) == 1    # the earlier release stays on file
    assert api.post(f"/api/claims/{a}/payout/plan", json={}).status_code == 409
    # released again, with the new link among those seen
    assert api.post(path, json={"reason": "Checked again after the third claim."}).status_code == 200
    assert status(api, a) == "released" and len(on_disk(world, a)["risk"]["releases"]) == 2


def test_a_hold_ends_when_the_link_is_gone(api, world):
    a, b = ring_of_two(api)
    assert status(api, a) == "held"
    give_bank(api, b, PH_BANK | {"first_name": "Maria", "last_name": "Santos"})      # b moves to its own account
    assert status(api, a) == "clear" and status(api, b) == "clear"
    assert "the hold has ended" in on_disk(world, a)["history"][-1]["note"]
    assert risk(api)["counts"]["held"] == 0
    assert api.post(f"/api/payer/claims/{a}/approve").json()["state"] == "APPROVED"


def test_an_honest_person_with_two_properties_and_one_account_is_never_held(api):
    a, b = open_claim(api, "P1", ANA)["id"], open_claim(api, "P4", ANA)["id"]
    give_bank(api, a)
    give_bank(api, b)
    view = risk(api)
    assert view["groups"] == [] and view["counts"]["held"] == 0
    assert all(c["status"] == "clear" for c in view["claims"])
    assert api.post(f"/api/payer/claims/{a}/approve").json()["state"] == "APPROVED"
    assert api.post(f"/api/payer/claims/{b}/approve").json()["state"] == "APPROVED"


# ---- what the view shows ---------------------------------------------------------------------------------------

def test_the_view_masks_every_shared_element_and_carries_no_private_detail(world):
    with TestClient(world.app, client=("203.0.113.77", 51000), headers={**AS_PAYER, "User-Agent": "Sample Browser 1.0"}) as api:
        a, b = ring_of_two(api)
        c = open_claim(api, "P5", {**CORA, "email": "Bela@Elsewhere.example"})["id"]       # b's mailbox again
        view = risk(api)
        text = json.dumps(view, ensure_ascii=False)
        stored = [on_disk(world, i) for i in (a, b, c)]
    account = MX_BANK["account_number"]
    assert account not in text and account[-4:] in text and "account ending 7771" in text
    assert "b···@elsewhere.example" in text and "bela@elsewhere.example" not in text.lower().replace("b···@elsewhere.example", "")
    assert "maria@example.org" not in text
    for claim in stored:
        assert claim["claimant"]["address"] not in text                           # nobody's typed address
        assert claim["claimant"]["name"] not in text                              # names are a first name and initials
        assert claim["origin"]["network"] not in text and claim["origin"]["agent"] not in text
    assert "203.0.113.77" not in text and "Sample Browser" not in text and "origin" not in text
    assert not re.search(r"\d{8,}", re.sub(r"g?[0-9a-f]{10,16}", "", text))                 # no long number of any kind
    assert {row["claimant"] for row in view["claims"]} == {"Maria L. S.", "Maria S. R.", "Maria C. S."}
    keys = {"id", "state", "created_at", "claimant", "country", "amount", "currency", "holder_name", "owner", "status",
            "group", "group_flagged", "since", "release", "events", "sample", "from_notice", "is_estate"}
    assert all(set(row) == keys for row in view["claims"])
    group = view["groups"][0]
    assert {s["kind"] for s in group["shared"]} >= {"account", "email", "device"}
    assert all(set(e) == {"a", "b", "linked", "points", "signals"} for e in group["edges"])
    assert all("key" not in s for e in group["edges"] for s in e["signals"])
    assert view["rule"]["flag_at"] == 60 and view["rule"]["link_at"] == 30 and len(view["rule"]["points"]) == 14
    assert view["measurement"] is None and view["demonstration"] is False


def test_the_measurement_beside_the_claims_is_shown_when_it_is_there(api, world):
    open_claim(api)
    (world.folder / "claims" / "ring_measurement.json").write_text(json.dumps(
        {"seed": 7, "ring_claims": 13, "ring_claims_caught": 11, "ring_claims_paid_before": 1, "honest_claims": 60,
         "honest_claims_held": 0, "rings": 3, "rings_flagged": 3, "measured_at": "2026-11-13T00:00:00+00:00",
         "per_ring": {"anything": "else"}}))
    shown = risk(api)["measurement"]
    assert shown["ring_claims_caught"] == 11 and shown["honest_claims"] == 60 and "per_ring" not in shown
    (world.folder / "claims" / "ring_measurement.json").write_text("not json")
    assert risk(api)["measurement"] is None


def test_the_analysis_is_made_again_only_when_a_claim_changes(api, world, monkeypatch):
    ring_of_two(api)
    calls = []
    real = rings.analyse
    monkeypatch.setattr(rings, "analyse", lambda *a, **k: calls.append(1) or real(*a, **k))
    risk(api)                                   # the first look after the claims changed
    made = len(calls)
    for _ in range(3):
        risk(api)
    assert len(calls) == made <= 2              # writing the risk state does not count as a change
    open_claim(api, "P5", CORA)
    risk(api)
    assert len(calls) == made + 1


def test_the_card_for_a_group_below_the_line_and_the_card_for_a_release():
    rows = {"a": {"status": "clear", "amount": 100, "currency": "USD"}, "b": {"status": "clear", "amount": 50.5, "currency": "USD"}}
    group = {"members": ["a", "b"], "points": 30, "flagged": False,
             "table": [{"kind": "email", "points": 30, "words": rings.POINTS["email"][1], "elements": ["a···@post.example"]}]}
    card = rings.group_card(group, rows)
    assert card["kind"] == "ring_linked" and card["tone"] == "go" and card["did"].startswith("Held nothing")
    assert card["money"] == "$150.50 across the group, none of it held." and card["why"][-1].startswith("The points add up to 30")
    release = rings.release_card({"amount": 610, "currency": "USD"}, {"at": "2026-11-13T00:00:00+00:00", "reason": "Her own account."})
    assert release["allowed"].startswith("A release is always a person's decision") and release["money"] == "$610.00 can move again."
    assert release["why"] == ["Reason on file: Her own account."]
