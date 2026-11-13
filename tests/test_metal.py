"""Funding a claim on Metal: the holder's mandate mirrors its approval, the agent pulls under it, and the chain
refuses whatever is outside it. A FakeMetal that enforces the same limits stands in for the chain and a fake
Airwallex for the bank. No test reaches the testnet: conftest hides the keys on the machine."""
from __future__ import annotations

import json
import subprocess
import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from khutlisa import airwallex as awx
from khutlisa import instructions as ins
from khutlisa import metal as mt
from khutlisa import payouts
from khutlisa.server import create_app
from test_claims import AS_PAYER, PAYER_KEY, PH_BANK, give_bank, open_claim
from test_payment_changes import Live, claimant_agrees, start

RULES = ins.clean({"tolerance_percent": "0.5", "small_claim_usd": "250", "route_rule": "most_to_claimant",
                   "deadline_days": 14})
SCALE = Decimal(100)


# ---- the scale and the terms ---------------------------------------------------------------------------------

def test_the_scale_is_explicit_and_amounts_round_up_to_the_cent_a_mandate_counts_in():
    assert mt.to_usdz("1840.55", SCALE) == Decimal("18.41")       # 18.4055 rounded up to the *USDZ cent
    assert mt.to_usd("18.41", SCALE) == Decimal("1841.00")
    assert mt.to_usdz("95.00", Decimal(1)) == Decimal("95.00")     # one for one: exact to the cent
    assert mt.to_usdz("1800.00", SCALE) == Decimal("18.00")
    words = mt.scale_words(SCALE)
    assert "1 *USDZ on Metal testnet stands for 100 US dollars" in words and "No real money moves" in words
    assert "1.00 US dollars" in words                              # what one cent on chain stands for
    assert "stands for 1 US dollar" in mt.scale_words(Decimal(1))
    assert mt.scale_from({}) == SCALE and mt.scale_from({"KHUTLISA_METAL_SCALE": "1"}) == 1
    for bad in ("0", "x", "-3"):
        with pytest.raises(mt.MetalUnavailable):
            mt.scale_from({"KHUTLISA_METAL_SCALE": bad})


def a_claim(amount="1840.55", rules=RULES, at="2026-11-13T10:00:00+00:00"):
    terms = {"instructions": rules, "amount": amount, "currency": "USD"}
    return {"id": "ab" * 8, "record": {"amount": float(amount), "currency": "USD"},
            "approval": {"at": at, "terms": terms, "terms_hash": "f" * 64, "deadline_at": ins.deadline_at(at, rules),
                         "fee_rule": ins.fee_plan(amount, rules) if rules else None}}


def test_the_mandate_an_approval_asks_for_mirrors_it_term_by_term():
    wanted = mt.wanted_terms(a_claim(), "0xSETTLE", SCALE, "2027-06-01")
    assert wanted["payee"] == "0xSETTLE" and wanted["max_occurrences"] == 1
    assert wanted["cap_usdz"] == wanted["budget_usdz"] == "18.41" and wanted["approved_usd"] == "1840.55"
    # 14 days after the approval, which comes before the handover date, so that is the expiry, to the second.
    assert wanted["expiry"] == mt._unix("2026-11-27T10:00:00+00:00") and "standing instructions" in wanted["expiry_from"]
    assert wanted["reference"] == "ab" * 8 and wanted["description"] == f"Khutlisa claim {'ab' * 8} approval {'f' * 16}"


def test_the_expiry_is_the_handover_date_when_it_comes_first_or_when_no_deadline_is_set():
    soon = mt.wanted_terms(a_claim(), "0xS", SCALE, "2026-11-20")
    assert soon["expiry"] == mt._unix("2026-11-20T00:00:00+00:00") and "handover" in soon["expiry_from"]
    none = mt.wanted_terms(a_claim(rules=None), "0xS", SCALE, "2027-06-01")
    assert none["expiry"] == mt._unix("2027-06-01T00:00:00+00:00") and none["cap_usdz"] == "18.41"
    with pytest.raises(mt.MetalError):
        mt.wanted_terms(a_claim(rules=None), "0xS", SCALE, None)       # a mandate without an expiry is never signed


def test_under_the_fee_rule_the_cap_is_what_the_holder_sends_not_the_bare_claim():
    wanted = mt.wanted_terms(a_claim("120.00"), "0xS", Decimal(1), "2027-06-01")
    assert wanted["approved_usd"] == "125.38" and wanted["cap_usdz"] == "125.38"     # (120 + 5) / (1 - 0.003)


# ---- the fake chain enforces what a Metal account enforces ---------------------------------------------------

def bound(chain, cap="18.41", expires_in=3600, **more):
    issued = chain.create_credential("/keys/x", cap=cap, budget=cap, expires_in=expires_in, description="d", **more)
    chain.bind(issued["credential"])
    return issued["credential"]


def test_the_chain_refuses_a_pull_over_the_cap_to_another_payee_after_expiry_and_after_revocation():
    clock = [1_800_000_000.0]
    chain = mt.FakeMetal(clock=lambda: clock[0])
    credential = bound(chain)
    to = chain.config.settlement
    assert chain.pull(credential, to, "18.42", "a")["reason"] == "mandate_cap_exceeded"
    assert chain.pull(credential, "0x" + "bb" * 20, "18.41", "b")["reason"] == "mandate_payee_not_listed"
    assert chain.balance(chain.config.holder_account) == "100"        # nothing moved
    recorded = chain.pull(credential, to, "18.42", "c", record_refusal=True)
    assert recorded["outcome"] == "refused" and recorded["recorded"] and recorded["transaction"].startswith("0x")
    clock[0] += 3601
    assert chain.pull(credential, to, "18.41", "d")["reason"] == "mandate_expired"
    fresh = bound(chain)
    chain.revoke(fresh)
    assert chain.pull(fresh, to, "18.41", "e")["reason"] == "mandate_revoked"
    unbound = chain.create_credential("/keys/y", cap="1", budget="1", expires_in=60, description="d")["credential"]
    assert chain.pull(unbound, to, "1", "f")["reason"] == "mandate_not_bound"


def test_one_mandate_pays_once_a_repeat_of_the_same_payment_sends_nothing_and_a_new_one_is_refused():
    chain = mt.FakeMetal()
    credential = bound(chain)
    to = chain.config.settlement
    paid = chain.pull(credential, to, "18.41", "claim-1")
    again = chain.pull(credential, to, "18.41", "claim-1")
    assert paid["outcome"] == again["outcome"] == "paid" and again["already_paid"]
    assert again["transaction"] == paid["transaction"] and chain.balance(to) == "18.41"
    second = chain.pull(credential, to, "18.41", "claim-1-again")
    assert second["outcome"] == "refused" and second["reason"] == "mandate_budget_spent"
    assert chain.balance(to) == "18.41" and chain.status(credential)["payments"] == 1
    seen = chain.settlement(paid["transaction"])
    assert seen["status"] == "success" and seen["transfers"] == [
        {"amount_usdz": "18.41", "from": chain.config.holder_account, "to": to}]
    assert chain.verify(credential, paid["transaction"])["verified"]
    short = mt.FakeMetal(balance="5")
    assert short.pull(bound(short), short.config.settlement, "18.41", "x")["reason"] == "transfer_would_fail"


# ---- the command line: what it prints is read correctly, and nothing secret leaves ---------------------------

PAID = """transaction 0x3594083219b8eae492f3835861f50345fadc47b55920d82ba5d7e62981698f60
outcome paid
spent 0.05 *USDZ of 0.05 *USDZ
payer 0xA1a662b1Ac52a33A181A83762623B64463645d42
payee 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec
amount 0.05 *USDZ
explorer https://testnet.metalntwx.com/tx/0x3594083219b8eae492f3835861f50345fadc47b55920d82ba5d7e62981698f60
gas 780316
"""
NOT_SENT = """outcome refused, not sent
reason mandate_cap_exceeded (the amount is above the mandate's per-payment cap)
recorded no
"""
RECORDED = """transaction 0x81f7403a6096a4cc948231f6ca454a4851bf6e8ae97ae023aaa79408d9547683
outcome refused
reason mandate_payee_not_listed (the payee is not one the mandate allows)
payer 0xA1a662b1Ac52a33A181A83762623B64463645d42
payee 0x2e472dFc2a8237ef5f985Af38391DCC97F21f634
amount 0.05 *USDZ
gas 793803
"""
STATUS = """mandate 0xde12201e20a03ff52726083bd745597d9cceecd7d383b4eba41839a8f36d5454
description Khutlisa probe
principal 0xA1a662b1Ac52a33A181A83762623B64463645d42
mandate-key 0x019ff52c (P-256)
token 0x000000000000000000000000000000000000B5d5
per-payment-cap 0.05 *USDZ
budget 0.05 *USDZ until expiry
starts 1794528000 (2026-11-13T00:00:00.000Z)
expiry 1794555507 (2026-11-13T07:38:27.000Z)
max-occurrences 1
payee 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec Khutlisa settlement
account-type MetalAccount
bound yes
revoked no
spent 0.05 *USDZ of 0.05 *USDZ
payments 1
"""
SETTLED = """transaction 0x3594083219b8eae492f3835861f50345fadc47b55920d82ba5d7e62981698f60
status success
block 27058625
submitter 0xa1ea44afe3948831194c90438f23827c8b458f88
gas 780316 at 1 per gas, paid in *USDZ
transfer 0.05 *USDZ from 0xA1a662b1Ac52a33A181A83762623B64463645d42 to 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec
"""
VERIFIED = """mandate 0xde12201e20a03ff52726083bd745597d9cceecd7d383b4eba41839a8f36d5454
step 1 pass: The mandate is bound on the principal's account
  0xde12201e bound in block 27058206
step 2 pass: The credential in hand hashes to the bound hash(C)
  the credential hashes to the bound hash(C)
step 3 pass: The credential's signatures
  the issuer's signature verifies
step 4 pass: Each payment and refusal is the mandate key's per-payment mandate
  1 payment(s) and 1 refusal(s)
refusal (mandate_cap_exceeded) 0x81f7403a6096a4cc948231f6ca454a4851bf6e8ae97ae023aaa79408d9547683 block 27058470: 0.06 *USDZ to 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec, nonce 0xde
payment 0x3594083219b8eae492f3835861f50345fadc47b55920d82ba5d7e62981698f60 block 27058625: 0.05 *USDZ to 0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec, nonce 0xde
verified yes
"""
SECRET_RPC = "https://rpc-testnet.metalntwx.com/v1/SECRETENDPOINTID123"


def cli(tmp_path, answers):
    """A MetalCli whose command line is a table of canned answers: [(exit code, stdout, stderr), ...]."""
    home = tmp_path / "metal"
    (home / "holder").mkdir(parents=True)
    (home / "agent").mkdir()
    (home / "holder" / "owner-key.json").write_text('{"address": "0xowner", "privateKey": "0xNEVERSHOWN"}')
    (home / "agent" / "key.json").write_text('{"address": "0xagent", "privateKey": "0xNEVERSHOWN"}')
    (home / "config.json").write_text(json.dumps({"holder_account": "0xA1a662b1Ac52a33A181A83762623B64463645d42",
                                                  "settlement": "0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec",
                                                  "agent": "0x2e472dFc2a8237ef5f985Af38391DCC97F21f634"}))
    sent = []

    def run(command, **kwargs):
        sent.append((command, kwargs))
        code, out, err = answers.pop(0)
        return subprocess.CompletedProcess(command, code, out, err)

    config = mt.MetalConfig.load({"METAL_RPC_URL": SECRET_RPC, "KHUTLISA_METAL_CLI": "metal-agent"}, home)
    return mt.MetalCli(config, run=run), sent


def test_the_command_lines_answers_are_read_as_paid_refused_and_recorded(tmp_path):
    chain, sent = cli(tmp_path, [(0, PAID, ""), (1, NOT_SENT, ""), (1, RECORDED, ""),
                                 (0, "already paid, nothing sent\n" + PAID, "")])
    paid = chain.pull("/c/mandate.json", "0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec", "0.05", "claim-1")
    assert paid["outcome"] == "paid" and paid["transaction"].endswith("698f60") and paid["reason"] is None
    assert paid["amount_usdz"] == "0.05" and not paid["already_paid"]
    command, kwargs = sent[0]
    assert command[:3] == ["metal-agent", "mandate", "pull"] and command[-2:] == ["--network", "testnet"]
    assert "--payment-id" in command and "claim-1" in command
    # The endpoint goes to the command line in its environment and its HOME is always the same folder, which is
    # where the command line remembers what it has sent.
    assert kwargs["env"]["METAL_RPC_URL"] == SECRET_RPC and kwargs["env"]["HOME"].endswith("metal/home")
    refused = chain.pull("/c/mandate.json", "0x9D", "0.06", "x")
    assert refused == {**refused, "outcome": "refused", "reason": "mandate_cap_exceeded", "recorded": False,
                       "transaction": None}
    recorded = chain.pull("/c/mandate.json", "0x2e", "0.05", "y", record_refusal=True)
    assert recorded["outcome"] == "refused" and recorded["reason"] == "mandate_payee_not_listed"
    assert recorded["recorded"] and recorded["transaction"].endswith("547683")
    assert "--record-refusal" in sent[2][0] and "--key" in sent[2][0]
    assert chain.pull("/c/mandate.json", "0x9D", "0.05", "claim-1")["already_paid"]


def test_status_settlement_and_verification_are_read_from_what_the_chain_answers(tmp_path):
    chain, _ = cli(tmp_path, [(0, STATUS, ""), (0, SETTLED, ""), (0, VERIFIED, "")])
    status = chain.status("/c/mandate.json")
    assert status["bound"] and not status["revoked"] and status["cap_usdz"] == status["budget_usdz"] == "0.05"
    assert status["expiry"] == 1794555507 and status["max_occurrences"] == 1 and status["payments"] == 1
    assert status["payees"] == ["0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec"] and status["spent_usdz"] == "0.05"
    seen = chain.settlement("0x35")
    assert seen["status"] == "success" and seen["block"] == "27058625" and seen["transfers"] == [
        {"amount_usdz": "0.05", "from": "0xA1a662b1Ac52a33A181A83762623B64463645d42",
         "to": "0x9D72faE225eA16FBC5289Eb8662EcA47310866Ec"}]
    check = chain.verify("/c/mandate.json")
    assert check["verified"] and [s["result"] for s in check["steps"]] == ["pass"] * 4
    assert check["steps"][0]["detail"].startswith("0xde12201e bound")
    assert [(l["kind"], l["reason"], l["amount_usdz"]) for l in check["lines"]] == [
        ("refusal", "mandate_cap_exceeded", "0.06"), ("payment", None, "0.05")]


def test_an_error_never_carries_the_endpoint_or_a_key_and_a_missing_setup_names_what_is_missing(tmp_path):
    chain, _ = cli(tmp_path, [(1, "", f"error: could not reach {SECRET_RPC}: connection refused")])
    with pytest.raises(mt.MetalError) as err:
        chain.bind("/c/mandate.json")
    assert "SECRETENDPOINTID123" not in str(err.value) and "<endpoint id>" in str(err.value)
    assert "SECRET" not in repr(chain) and "NEVERSHOWN" not in repr(chain.config.holder_key)
    chain, _ = cli(tmp_path / "again", [(1, "", "error: something unexpected")])
    with pytest.raises(mt.MetalError):        # no outcome and no reason: nothing is assumed
        chain.pull("/c/mandate.json", "0x9D", "0.05", "z")
    with pytest.raises(mt.MetalUnavailable) as missing:
        mt.MetalConfig.load({}, tmp_path / "nothing-here")
    assert "config.json is missing" in str(missing.value) and "metal_setup.py" in str(missing.value)


# ---- the application: a claim funded by a pull under a mandate ------------------------------------------------

class OnMetal(Live):
    """The app over a fake Airwallex and a fake chain whose state is kept in a file, so an app can be stopped and
    another started over the same chain."""

    def make_app(self):
        self.fake.incoming_fee_rate, self.fake.payout_fee_usd = 0.003, 5.0
        self.chain = mt.FakeMetal(path=self.folder / "chain.json", clock=lambda: getattr(self, "now", None) or time.time())
        return create_app(db_path=self.db, totals_path=self.folder / "totals.json", web_dist=self.folder / "no-web",
                          airwallex_factory=self.factory, payout_pause=0.0, payer_key=PAYER_KEY,
                          watch_seconds=self.watch_seconds, watch_pause=0.01, metal=self.chain, metal_scale="100",
                          metal_keys=self.folder / "keys")


@pytest.fixture
def metal(tmp_path):
    world = OnMetal(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        yield api


def approve_on_metal(api, rules=RULES):
    if rules:
        assert api.put("/api/payer/instructions", json=rules).status_code == 200
    claim = open_claim(api)                       # 1,840.55 USD, paid to the Philippines
    give_bank(api, claim["id"], PH_BANK)
    row = api.post(f"/api/payer/claims/{claim['id']}/approve", json={"funding": "metal"})
    assert row.status_code == 200, row.text
    return claim["id"], row.json()


def panel(api, claim_id, payer=True):
    r = api.get(f"/api/payer/claims/{claim_id}/metal" if payer else f"/api/claims/{claim_id}/metal")
    assert r.status_code == 200, r.text
    return r.json()


def test_approving_on_metal_signs_a_mandate_whose_terms_are_the_approvals(metal):
    claim_id, row = approve_on_metal(metal)
    seen = panel(metal, claim_id)
    chain = metal.world.chain
    assert seen["available"] and seen["funding"] == "metal" and seen["network"] == "Metal testnet"
    assert seen["scale"]["usd_per_usdz"] == "100" and "stands for 100 US dollars" in seen["scale"]["words"]
    mandate = seen["mandate"]
    assert mandate["status"] == "bound" and mandate["for_current_approval"] and mandate["all_same"]
    assert mandate["bind_transaction"].startswith("0x") and mandate["bind_explorer"].endswith(mandate["bind_transaction"])
    terms = {t["term"]: t for t in mandate["terms"]}
    assert all(t["same"] and t["source"] == "read from the chain" for t in terms.values())
    assert terms["Who may be paid"]["mandate"] == chain.config.settlement
    assert "1,840.55 USD" in terms["Most per payment"]["approval"]
    assert terms["Most per payment"]["mandate"] == "18.41 *USDZ, which stands for 1,841.00 USD"
    assert terms["Number of payments"]["mandate"] == "1"
    # The expiry on chain is the approval's deadline, to the second.
    held = chain.status(next(iter(chain.state["mandates"])))
    assert held["expiry"] == mt._unix(row["approval"]["deadline_at"]) and held["payees"] == [chain.config.settlement]
    assert terms["Until"]["approval"].startswith(mt._when(held["expiry"])) and terms["Until"]["mandate"].endswith(" UTC")
    assert mt._when(mt._unix("2026-11-27T06:52:55+00:00")) == "27 Nov 2026, 06:52:55 UTC"
    assert claim_id in terms["Reference"]["mandate"] and row["approval"]["terms_hash"][:16] in terms["Reference"]["mandate"]
    assert mandate["chain"] == {**mandate["chain"], "bound": True, "revoked": False, "spent_usdz": "0", "payments": 0}
    assert seen["pull"] is None and seen["can"]["revoke"] and not seen["can"]["sign"]
    assert [a["key"] for a in seen["can"]["attempts"]] == ["over_cap", "wrong_payee"]
    history = metal.get(f"/api/claims/{claim_id}").json()["history"]
    assert any("signed a Metal mandate" in e["note"] and "stands for 100 US dollars" in e["note"] for e in history)
    # The claimant sees the same mandate and may do nothing to it; nothing shown is a key or a file.
    theirs = panel(metal, claim_id, payer=False)
    assert theirs["can"] is None and theirs["mandate"]["mandate_id"] == mandate["mandate_id"]
    assert "credential" not in json.dumps(theirs) and "keys" not in json.dumps(theirs["mandate"])


def test_the_pull_funds_the_claim_and_the_deposits_reference_is_the_metal_transaction(metal):
    claim_id, _ = approve_on_metal(metal)
    done = start(metal, claim_id)
    chain, bank = metal.world.chain, metal.world.fake
    seen = panel(metal, claim_id)
    pull = seen["pull"]
    assert done["state"] == "PAID" and done["reconciliation"]["balanced"]
    assert pull["outcome"] == "paid" and pull["checked"] and pull["amount_usdz"] == "18.41"
    assert pull["approved_usd"] == "1840.55" and pull["stands_for_usd"] == "1841.00"
    assert pull["explorer"] == f"https://testnet.metalntwx.com/tx/{pull['transaction']}"
    # Read from the chain: one transfer of exactly the amount, from the holder's account to the settlement address.
    assert pull["settlement"]["status"] == "success" and pull["settlement"]["transfers"] == [
        {"amount_usdz": "18.41", "from": chain.config.holder_account, "to": chain.config.settlement}]
    assert pull["verification"]["verified"] and seen["mandate"]["status"] == "spent"
    assert seen["mandate"]["chain"]["spent_usdz"] == "18.41" and seen["mandate"]["chain"]["payments"] == 1
    # The bridge: one simulated deposit, for the approved dollars, whose reference is the transaction hash.
    assert [d["reference"] for d in bank.deposits] == [pull["transaction"]] and bank.deposits[0]["amount"] == 1840.55
    assert done["deposit"]["reference"] == pull["transaction"] and done["deposit"]["amount"] == "1840.55"
    assert bank.count("POST", "/api/v1/simulation/deposit/create") == 1 and chain.count("pull") == 1
    note = next(r for r in done["agent_report"] if r["kind"] == "funded_on_metal")
    assert note["title"] == "Pulled the holder's funds under the Metal mandate" and pull["transaction"] in note["text"]
    assert "18.41 *USDZ" in note["text"] and "1,840.55 US dollars" in note["text"] and "mandate" in note["rule_name"]
    assert json.loads((metal.world.folder / "claims" / "metal_funded.json").read_text()) == {pull["transaction"]: claim_id}
    assert [a["key"] for a in seen["can"]["attempts"]] == ["over_cap", "wrong_payee", "second_pull"]


def test_a_claim_funded_by_a_bank_deposit_goes_on_as_before_and_never_touches_the_chain(metal):
    assert metal.put("/api/payer/instructions", json=RULES).status_code == 200
    claim = open_claim(metal)
    give_bank(metal, claim["id"], PH_BANK)
    assert metal.post(f"/api/payer/claims/{claim['id']}/approve").status_code == 200       # no choice: a bank deposit
    done = start(metal, claim["id"])
    assert done["state"] == "PAID" and done["deposit"]["reference"] == f"KHUTLISA-{claim['id']}"
    assert metal.world.chain.calls == [] and panel(metal, claim["id"])["funding"] == "bank"
    assert panel(metal, claim["id"])["mandate"] is None
    refused = metal.post(f"/api/payer/claims/{claim['id']}/metal/mandate")
    assert refused.status_code == 409 and "bank deposit" in refused.json()["detail"]


def test_a_restart_between_the_pull_and_the_deposit_neither_pulls_nor_credits_twice(tmp_path):
    world = OnMetal(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        claim_id, _ = approve_on_metal(api)
        # The server stops right after the pull settled, before anything is credited at Airwallex.
        funding = world.app.state.metal
        real = funding.before_deposit

        def stops_here(payout, client, clock=None):
            real(payout, client, clock)
            raise RuntimeError("the server stopped here")

        funding.before_deposit = stops_here
        plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
        assert api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]}).status_code == 200
        world.app.state.payouts.join(claim_id)
        stopped = api.get(f"/api/claims/{claim_id}/payout").json()
        tx = panel(api, claim_id)["pull"]["transaction"]
        assert stopped["state"] == "DEPOSIT_EXPECTED" and stopped["deposit"]["reference"] == tx and not world.fake.deposits
    again = OnMetal(tmp_path)                       # a new process over the same files and the same chain
    again.fake = world.fake
    again.app = again.make_app()
    with TestClient(again.app, headers=AS_PAYER) as api:
        again.app.state.payouts.join(claim_id)      # the payout was picked up when the app started
        done = api.get(f"/api/claims/{claim_id}/payout").json()
        assert done["state"] == "PAID" and done["deposit"]["reference"] == tx
        assert [d["reference"] for d in again.fake.deposits] == [tx]
        status = again.chain.status(next(iter(again.chain.state["mandates"])))
        assert status["payments"] == 1 and status["spent_usdz"] == "18.41" and again.chain.count("pull") == 0


def test_a_pull_whose_answer_was_lost_is_asked_for_again_under_the_same_id_and_pays_once(metal):
    claim_id, _ = approve_on_metal(metal)
    chain = metal.world.chain
    chain.fail["settlement"] = mt.MetalError("the endpoint did not answer")     # paid on chain, then we lose touch
    plan = metal.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
    assert metal.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]}).status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    stuck = metal.get(f"/api/claims/{claim_id}/payout").json()
    assert stuck["state"] == "DEPOSIT_EXPECTED" and "did not answer" in stuck["problem"] and not metal.world.fake.deposits
    assert metal.post(f"/api/claims/{claim_id}/payout/resume").status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    done = metal.get(f"/api/claims/{claim_id}/payout").json()
    pulls = [c for c in chain.calls if c[0] == "pull"]
    assert done["state"] == "PAID" and len(pulls) == 2 and {c[4] for c in pulls} == {claim_id}
    assert chain.status(pulls[0][1])["payments"] == 1 and chain.balance(chain.config.settlement) == "18.41"
    assert len(metal.world.fake.deposits) == 1


def test_one_transaction_hash_can_fund_one_claim_once(metal):
    claim_id, _ = approve_on_metal(metal)
    start(metal, claim_id)
    funding = metal.world.app.state.metal
    tx = panel(metal, claim_id)["pull"]["transaction"]
    funding.claim_hash(tx, claim_id)                           # the same claim again: nothing changes
    with pytest.raises(mt.MetalError) as err:
        funding.claim_hash(tx.upper().replace("0X", "0x"), "cd" * 8)     # another claim, the same hash
    assert "already funded another claim" in str(err.value)
    # And at Airwallex: the machine looks the hash up among the deposits before it credits anything.
    payout = awx.Payout.load(metal.world.folder / "claims" / claim_id / "payout.json")
    payout.state, payout.deposit_id = awx.DEPOSIT_EXPECTED, None
    client, sim = metal.world.factory()
    awx.advance(payout, client, sim, funding=funding)
    assert payout.deposit_id == metal.world.fake.deposits[0]["id"] and len(metal.world.fake.deposits) == 1
    assert metal.world.chain.count("pull") == 1


def test_a_pull_that_settled_as_something_else_is_not_credited(metal):
    claim_id, _ = approve_on_metal(metal)
    chain = metal.world.chain
    real = chain.settlement

    def other(tx):
        seen = real(tx)
        return {**seen, "transfers": [{**seen["transfers"][0], "amount_usdz": "1.00"}]}

    chain.settlement = other
    held = start(metal, claim_id)
    assert held["state"] == "HELD" and held["hold"]["kind"] == "metal_settlement_differs"
    assert "is not the payment the approval covers" in held["hold"]["explanation"] and not metal.world.fake.deposits
    assert panel(metal, claim_id)["pull"]["checked"] is None


# ---- refusals by the chain ------------------------------------------------------------------------------------

def test_a_mandate_revoked_before_the_payment_starts_sends_the_claim_back_to_the_holder(metal):
    claim_id, _ = approve_on_metal(metal)
    after = metal.post(f"/api/payer/claims/{claim_id}/metal/revoke")
    assert after.status_code == 200, after.text
    seen = after.json()
    assert seen["mandate"]["status"] == "revoked" and seen["mandate"]["revoke_transaction"].startswith("0x")
    assert seen["mandate"]["chain"]["revoked"] is True
    row = next(r for r in metal.get("/api/payer/queue").json()["claims"] if r["id"] == claim_id)
    assert row["state"] != "APPROVED" and row["approval"] is None and row["can_decide"]
    assert row["approvals_withdrawn"][0]["because"] == "the holder revoked the Metal mandate before any money was pulled"
    plan = metal.post(f"/api/claims/{claim_id}/payout/plan", json={})
    assert plan.status_code == 409 and metal.world.chain.count("pull") == 0
    # A new approval signs a new mandate; the revoked one stays on the record.
    again = metal.post(f"/api/payer/claims/{claim_id}/approve", json={"funding": "metal"})
    assert again.status_code == 200, again.text
    seen = panel(metal, claim_id)
    assert seen["mandate"]["seq"] == 2 and seen["mandate"]["status"] == "bound"
    assert [m["status"] for m in seen["earlier_mandates"]] == ["revoked"]
    assert start(metal, claim_id)["state"] == "PAID"


def test_a_mandate_revoked_on_chain_while_the_payment_starts_is_refused_by_metal_and_the_claim_returns(metal):
    claim_id, _ = approve_on_metal(metal)
    chain = metal.world.chain
    chain.revoke(next(iter(chain.state["mandates"])))          # the holder revokes from its own wallet
    held = start(metal, claim_id)
    assert held["state"] == "HELD" and held["hold"]["kind"] == "mandate_revoked" and held["hold"]["needs"] == ["payer"]
    assert "revoked the Metal mandate before any money was pulled" in held["hold"]["explanation"]
    assert "mandate_revoked" in held["hold"]["explanation"] and held["claim_state"] == "PAYMENT_HELD"
    assert not metal.world.fake.deposits and chain.balance(chain.config.settlement) == "0"
    seen = panel(metal, claim_id)
    refusal = seen["refusals"][0]
    assert refusal["reason"] == "mandate_revoked" and refusal["recorded_on_chain"] and refusal["transaction"]
    assert refusal["explorer"].endswith(refusal["transaction"]) and not refusal["staged"]
    row = next(r for r in metal.get("/api/payer/queue").json()["claims"] if r["id"] == claim_id)
    assert row["can_decide"] and "revoked the Metal mandate" in row["approvals_withdrawn"][0]["because"]
    # The holder approves again: a new mandate is signed with the approval and the payment carries on.
    assert metal.post(f"/api/payer/claims/{claim_id}/approve").status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    done = metal.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and panel(metal, claim_id)["mandate"]["seq"] == 2
    assert chain.balance(chain.config.settlement) == "18.41" and len(metal.world.fake.deposits) == 1


def test_a_pull_above_the_cap_is_refused_by_the_chain_even_if_our_own_code_asked_for_it(metal):
    claim_id, _ = approve_on_metal(metal)
    plan = metal.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
    path = metal.world.folder / "claims" / claim_id / "payout.json"
    payout = awx.Payout.load(path)
    payout.usd_amount = "2500.00"                 # as if a fault in our code asked for more than was approved
    payout.save()
    assert metal.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]}).status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    held = metal.get(f"/api/claims/{claim_id}/payout").json()
    assert held["state"] == "HELD" and held["hold"]["kind"] == "metal_refused"
    assert "mandate_cap_exceeded" in held["hold"]["explanation"] and "25.00 *USDZ" in held["hold"]["explanation"]
    chain = metal.world.chain
    assert chain.balance(chain.config.holder_account) == "100" and not metal.world.fake.deposits


def test_an_expired_mandate_stops_the_payment_and_returns_the_claim(metal):
    claim_id, row = approve_on_metal(metal)
    chain = metal.world.chain
    plan = metal.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
    chain.fail["pull"] = mt.MetalUnavailable("the command line is not installed")
    assert metal.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]}).status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    assert "not installed" in metal.get(f"/api/claims/{claim_id}/payout").json()["problem"]
    metal.world.now = mt._unix(row["approval"]["deadline_at"]) + 1          # the chain's clock passes the expiry
    assert metal.post(f"/api/claims/{claim_id}/payout/resume").status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    held = metal.get(f"/api/claims/{claim_id}/payout").json()
    assert held["state"] == "HELD" and held["hold"]["kind"] == "metal_refused"
    assert "mandate_expired" in held["hold"]["explanation"] and not metal.world.fake.deposits
    assert chain.balance(chain.config.holder_account) == "100"


def test_the_agent_can_be_told_to_overstep_and_metal_refuses_each_time(metal):
    claim_id, _ = approve_on_metal(metal)
    chain = metal.world.chain
    early = metal.post(f"/api/payer/claims/{claim_id}/metal/attempt", json={"case": "second_pull"})
    assert early.status_code == 409 and "only after the claim has been funded" in early.json()["detail"]
    over = metal.post(f"/api/payer/claims/{claim_id}/metal/attempt", json={"case": "over_cap"}).json()["refusal"]
    wrong = metal.post(f"/api/payer/claims/{claim_id}/metal/attempt", json={"case": "wrong_payee"}).json()["refusal"]
    assert over["reason"] == "mandate_cap_exceeded" and over["amount_usdz"] == "18.42" and over["staged"]
    assert wrong["reason"] == "mandate_payee_not_listed" and wrong["payee"] == chain.config.agent_address
    assert over["recorded_on_chain"] and over["explorer"].endswith(over["transaction"])
    assert chain.balance(chain.config.holder_account) == "100" and chain.balance(chain.config.agent_address) == "0"
    assert start(metal, claim_id)["state"] == "PAID"            # the real pull is untouched by the refused ones
    second = metal.post(f"/api/payer/claims/{claim_id}/metal/attempt", json={"case": "second_pull"})
    assert second.status_code == 200, second.text
    assert second.json()["refusal"]["reason"] == "mandate_budget_spent"
    assert chain.balance(chain.config.settlement) == "18.41" and len(metal.world.fake.deposits) == 1
    seen = panel(metal, claim_id)
    assert [r["reason"] for r in seen["refusals"]] == ["mandate_cap_exceeded", "mandate_payee_not_listed",
                                                       "mandate_budget_spent"]
    checked = metal.post(f"/api/payer/claims/{claim_id}/metal/verify").json()["mandate"]["verification"]
    assert checked["verified"] and [l["kind"] for l in checked["lines"]] == ["refusal", "refusal", "payment", "refusal"]
    assert metal.post(f"/api/payer/claims/{claim_id}/metal/attempt", json={"case": "anything"}).status_code == 422


# ---- tied to the agent's decisions ----------------------------------------------------------------------------

def test_a_refused_bank_transfer_is_replaced_from_what_came_back_and_the_mandate_is_never_pulled_again(metal):
    claim_id, _ = approve_on_metal(metal)
    chain = metal.world.chain
    view = start(metal, claim_id, "transfer_fails")
    for _ in range(400):
        view = metal.get(f"/api/claims/{claim_id}/payout").json()
        if view["state"] == "FAILED" and view["hold"]["ready"]:
            break
        time.sleep(0.01)
    assert view["state"] == "FAILED" and view["hold"]["kind"] == "transfer_failed"
    tx = panel(metal, claim_id)["pull"]["transaction"]
    assert chain.count("pull") == 1 and len(metal.world.fake.deposits) == 1
    # The replacement needs a corrected account and the holder's approval of it. No new mandate is signed for it
    # and nothing more is pulled: the replacement is paid from what Airwallex booked back for this claim.
    give_bank(metal, claim_id, {**PH_BANK, "account_number": "9876543210"})
    assert metal.post(f"/api/payer/claims/{claim_id}/approve").status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    done = metal.get(f"/api/claims/{claim_id}/payout").json()
    if done["state"] != "PAID":                   # outside the tolerance the claimant agrees to the new amount
        assert claimant_agrees(metal, claim_id).status_code == 200
        metal.world.app.state.payouts.join(claim_id)
        done = metal.get(f"/api/claims/{claim_id}/payout").json()
    seen = panel(metal, claim_id)
    assert done["state"] == "PAID" and len(done["attempts"]) == 1 and done["deposit"]["reference"] == tx
    assert chain.count("pull") == 1 and chain.count("bind") == 1 and len(seen["earlier_mandates"]) == 0
    assert len(metal.world.fake.deposits) == 1 and chain.balance(chain.config.settlement) == "18.41"
    # And if the agent tried: the chain refuses a second pull under the same mandate.
    second = metal.post(f"/api/payer/claims/{claim_id}/metal/attempt", json={"case": "second_pull"}).json()["refusal"]
    assert second["reason"] == "mandate_budget_spent" and chain.balance(chain.config.settlement) == "18.41"
    assert not seen["can"]["sign"]
    refused = metal.post(f"/api/payer/claims/{claim_id}/metal/mandate")
    assert refused.status_code == 409 and "already been funded" in refused.json()["detail"]


def held_before_the_pull(api, monkeypatch, new_rate, rules=RULES):
    """A claim whose plan was agreed, and whose pull could not be made until the rate lock had run out."""
    claim_id, _ = approve_on_metal(api, rules)
    world = api.world
    monkeypatch.setattr(awx.time, "time", lambda: world.fake.now)
    plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
    world.chain.fail["pull"] = mt.MetalUnavailable("the command line is not installed")
    assert api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]}).status_code == 200
    world.app.state.payouts.join(claim_id)
    world.fake.now += 3700                        # the one-hour lock is over
    world.fake.rates["PHP"] = new_rate
    assert api.post(f"/api/claims/{claim_id}/payout/resume").status_code == 200
    world.app.state.payouts.join(claim_id)
    return claim_id, plan


def test_outside_the_tolerance_the_agent_does_not_pull_at_all_and_asks_the_owner(metal, monkeypatch):
    claim_id, plan = held_before_the_pull(metal, monkeypatch, 57.0)       # 1.72 percent worse than 58.0
    chain = metal.world.chain
    for _ in range(400):
        view = metal.get(f"/api/claims/{claim_id}/payout").json()
        if view["state"] == "HELD" and view["hold"]["ready"]:
            break
        time.sleep(0.01)
    assert view["state"] == "HELD" and view["hold"]["kind"] == "rate_lock_expired" and view["hold"]["needs"] == ["claimant"]
    # Nothing left the holder's account: the only pull on record is the one that never reached the chain.
    assert chain.balance(chain.config.holder_account) == "100" and chain.status(next(iter(chain.state["mandates"])))["payments"] == 0
    assert not metal.world.fake.deposits and view["claim_state"] == "PAYING" and view["approved"]
    note = next(r for r in view["agent_report"] if r["kind"] == "metal_no_pull")
    assert "nothing was pulled from the holder's Metal account" in note["text"] and "0.5 percent" in note["text"]
    assert any("did not pull" in e["text"] for e in panel(metal, claim_id)["events"])
    # The owner agrees to the new amount, and only then is the holder's money pulled.
    assert view["plan"]["id"] != plan["id"] and claimant_agrees(metal, claim_id).status_code == 200
    metal.world.app.state.payouts.join(claim_id)
    done = metal.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and done["rate"] == 57.0 and chain.balance(chain.config.settlement) == "18.41"


def test_inside_the_tolerance_the_agent_locks_a_new_rate_pulls_and_says_so(metal, monkeypatch):
    claim_id, _ = held_before_the_pull(metal, monkeypatch, 57.8)          # 0.34 percent worse
    done = metal.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and done["rate"] == 57.8
    note = next(r for r in done["agent_report"] if r["kind"] == "metal_requoted")
    assert "inside the tolerance of 0.5 percent" in note["text"] and "so the pull went ahead" in note["text"]


def test_without_standing_instructions_a_lock_that_ran_out_before_the_pull_is_always_put_to_the_owner(metal, monkeypatch):
    claim_id, _ = held_before_the_pull(metal, monkeypatch, 57.99, rules=None)
    view = metal.get(f"/api/claims/{claim_id}/payout").json()
    assert view["state"] == "HELD" and view["hold"]["kind"] == "rate_lock_expired"
    assert metal.world.chain.balance(metal.world.chain.config.holder_account) == "100"


# ---- when Metal is not there, or does not answer ---------------------------------------------------------------

def test_without_metal_set_up_the_choice_is_refused_and_the_claim_is_not_approved(live):
    status = live.get("/api/metal").json()
    assert status == {**status, "available": False, "label": "not yet run on testnet"}
    assert "config.json is missing" in status["problem"]
    claim = open_claim(live)
    give_bank(live, claim["id"], PH_BANK)
    refused = live.post(f"/api/payer/claims/{claim['id']}/approve", json={"funding": "metal"})
    assert refused.status_code == 503 and "Metal is not set up" in refused.json()["detail"]
    assert live.get(f"/api/claims/{claim['id']}").json()["approval"] is None
    assert live.get(f"/api/claims/{claim['id']}/metal").json()["available"] is False
    assert live.post(f"/api/payer/claims/{claim['id']}/metal/revoke").status_code == 503
    assert live.post(f"/api/payer/claims/{claim['id']}/approve").status_code == 200      # a bank deposit still works


@pytest.fixture
def live(tmp_path):
    world = Live(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        yield api


def test_a_mandate_that_could_not_be_signed_leaves_the_approval_and_can_be_signed_again(metal):
    assert metal.put("/api/payer/instructions", json=RULES).status_code == 200
    claim = open_claim(metal)
    give_bank(metal, claim["id"], PH_BANK)
    metal.world.chain.fail["bind"] = mt.MetalError("the endpoint did not answer")
    failed = metal.post(f"/api/payer/claims/{claim['id']}/approve", json={"funding": "metal"})
    assert failed.status_code == 502 and "could not be signed on Metal" in failed.json()["detail"]
    seen = panel(metal, claim["id"])
    assert seen["funding"] == "metal" and seen["mandate"]["status"] == "issued" and seen["can"]["sign"]
    # Nothing can be pulled under a mandate the chain does not hold.
    plan = metal.post(f"/api/claims/{claim['id']}/payout/plan", json={}).json()["plan"]
    assert metal.post(f"/api/claims/{claim['id']}/payout/confirm", json={"plan_id": plan["id"]}).status_code == 200
    metal.world.app.state.payouts.join(claim["id"])
    waiting = metal.get(f"/api/claims/{claim['id']}/payout").json()
    assert waiting["state"] == "DEPOSIT_EXPECTED" and "has not signed a Metal mandate" in waiting["problem"]
    signed = metal.post(f"/api/payer/claims/{claim['id']}/metal/mandate")
    assert signed.status_code == 200 and signed.json()["mandate"]["status"] == "bound"
    metal.world.app.state.payouts.join(claim["id"])
    assert metal.get(f"/api/claims/{claim['id']}/payout").json()["state"] == "PAID"


def test_the_holders_metal_routes_need_the_holders_key_and_the_account_must_hold_enough(metal):
    claim_id, _ = approve_on_metal(metal)
    for path in ("metal/revoke", "metal/mandate", "metal/verify"):
        assert metal.post(f"/api/payer/claims/{claim_id}/{path}", headers={"X-Payer-Key": "wrong"}).status_code == 401
    assert metal.get(f"/api/payer/claims/{claim_id}/metal", headers={"X-Payer-Key": "wrong"}).status_code == 401
    assert metal.post(f"/api/payer/claims/{claim_id}/metal/attempt", json={"case": "over_cap"},
                      headers={"X-Payer-Key": "wrong"}).status_code == 401
    public = metal.get("/api/metal").json()
    assert public["available"] and public["scale"]["usd_per_usdz"] == "100" and len(public["enforced"]["by_chain"]) == 5
    # A second, larger claim than the account holds cannot be given a mandate.
    chain = metal.world.chain
    chain.state["balances"][chain.config.holder_account] = "5"
    assert metal.post(f"/api/payer/claims/{claim_id}/metal/revoke").status_code == 200
    short = metal.post(f"/api/payer/claims/{claim_id}/approve", json={"funding": "metal"})
    assert short.status_code == 409 and "holds 5.00 *USDZ" in short.json()["detail"] and "18.41" in short.json()["detail"]


def test_the_stops_metal_adds_are_put_into_fixed_sentences_and_withdraw_the_approval_with_a_reason():
    said = payouts.fixed_explanation("mandate_revoked", {"reason": "mandate_revoked", "amount_usdz": "18.41"}, None)
    assert "revoked the Metal mandate" in said and "nothing moved" in said
    said = payouts.fixed_explanation("metal_refused", {"reason": "mandate_expired", "amount_usdz": "18.41"}, None)
    assert "mandate_expired (the mandate has expired)" in said and "18.41 *USDZ" in said
    assert "revoked the Metal mandate" in payouts.VOID_REASONS["mandate_revoked"]
    assert set(mt.ATTEMPTS) == {"over_cap", "wrong_payee", "second_pull"}
    assert all(reason in mt.REFUSALS for reason in ("mandate_cap_exceeded", "mandate_payee_not_listed",
                                                    "mandate_expired", "mandate_revoked", "mandate_budget_spent"))
