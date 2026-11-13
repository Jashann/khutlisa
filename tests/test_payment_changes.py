"""The payment step when things change: what Airwallex booked is what is shown, fees come out of the claim's own
money, and a short deposit, a refused or returned transfer and a rate lock that runs out each stop the payout
until the right people agree. A fake Airwallex stands behind every test; no network and no model."""
from __future__ import annotations

from decimal import Decimal

import pytest

from khutlisa import airwallex as awx
from khutlisa import llm, payouts
from khutlisa.airwallex import Payout, SandboxSimulator, advance, run
from test_airwallex import FakeAirwallex, make_client


@pytest.fixture
def fake():
    f = FakeAirwallex()
    f.incoming_fee_rate, f.payout_fee_usd = 0.003, 5.0     # what the live sandbox charges
    return f


def planned(tmp_path, fake, currency="PHP", usd="120.00", what_if=None):
    """A payout with a plan the claimant has agreed to, ready to run."""
    client = make_client(fake)
    payout = Payout.open(tmp_path / "payout.json", usd_amount=usd, target_currency=currency, state=awx.PLANNED,
                         deposit_reference="KHUTLISA-test", beneficiary=awx.EXAMPLE_BENEFICIARIES[currency])
    payout.what_if = what_if
    plan = payouts.make_plan(payout, client, simulator_ready=True)
    payout.confirmed = {"plan_id": plan["id"], "local_amount": plan["expected_local"]["amount"]}
    payout._move(awx.DEPOSIT_EXPECTED, "plan agreed")
    return payout, client, SandboxSimulator(client)


def agree(payout, *who):
    for person in who:
        payout.agreed(person)


# ---- what Airwallex booked ---------------------------------------------------------------------------------

def test_the_incoming_fee_is_read_only_once_airwallex_has_booked_it(tmp_path, fake):
    fake.deposit_reads_before_settled = 2      # the deposit first shows as PENDING with no fee, as on the sandbox
    payout, client, sim = planned(tmp_path, fake)
    advance(payout, client, sim)
    assert payout.state == awx.DEPOSIT_EXPECTED and payout.deposit_fee is None   # never 0.00 by reading too soon
    advance(payout, client, sim)
    advance(payout, client, sim)
    assert payout.state == awx.DEPOSIT_CONFIRMED and payout.deposit_fee == "0.36"
    assert payout.funds == {"amount": "119.64", "currency": "USD"}


def test_fees_come_out_of_the_claims_own_money_and_every_line_adds_up_to_zero(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake)
    run(payout, client, sim)
    assert payout.state == awx.PAID
    body = fake.bodies["/api/v1/transfers/create"][0]
    assert body["source_amount"] == "119.64" and body["fee_paid_by"] == "BENEFICIARY"
    transfer = fake.transfers[payout.transfer_id]
    # 120.00 arrived and 0.36 was taken on the way in. Exactly the remaining 119.64 left the wallet, the 5.00
    # payout fee inside it. Before this fix 124.64 left on a 120.00 deposit.
    assert transfer["amount_payer_pays"] == 119.64 and payout.payer_pays == "119.64"
    assert Decimal(payout.payer_pays) <= Decimal(payout.deposit_amount) - Decimal(payout.deposit_fee)
    assert payout.transfer_fee == {"amount": "5.0", "currency": "USD", "paid_by": "BENEFICIARY"}
    assert payout.target_amount == str(awx.money((119.64 - 5) * 58, "PHP"))
    assert fake.balance["USD"] == 0          # the fake wallet started empty: nothing else paid for this claim
    shown = payouts.reconciliation(payout.__dict__)
    assert [(line["type"], line["amount"], line["currency"]) for line in shown["lines"]] == [
        ("DEPOSIT", "120.0", "USD"), ("FEE", "-0.36", "USD"), ("PAYOUT", "-119.64", "USD")]
    assert {(r["id"], str(r["amount"])) for r in fake.ledger} == {(l["id"], l["amount"]) for l in shown["lines"]}
    assert shown["balanced"] and shown["sums"] == [{"currency": "USD", "came_in": "120.0", "went_out": "120.00",
                                                    "left": "0.00"}]
    assert "8487576435" not in str(shown) and "····6435" in str(shown)     # an account number is cut to four digits


def test_a_held_currency_is_converted_first_and_both_currencies_add_up_to_zero(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, "MXN", "1840.55")
    assert payout.plan["route"] == awx.CONVERT_THEN_PAY
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.conversion_id
    sums = {s["currency"]: s["left"] for s in payouts.reconciliation(payout.__dict__)["sums"]}
    assert Decimal(sums["USD"]) == 0 and Decimal(sums["MXN"]) == 0
    assert fake.transfers[payout.transfer_id]["fee_paid_by"] == "BENEFICIARY"
    assert fake.balance["USD"] == 0 and fake.balance["MXN"] == 0


# ---- the plan ----------------------------------------------------------------------------------------------

def test_the_plan_names_the_route_the_fees_the_rate_and_what_happens_if_things_change(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake)
    plan = payout.plan
    assert plan["route"] == awx.PAY_WITH_QUOTE and "converted inside it" in plan["route_reason"]
    assert plan["incoming_fee"]["amount"] == "0.36" and plan["incoming_fee"]["basis"].startswith("expected")
    assert plan["to_send"] == {"amount": "119.64", "currency": "USD"}
    assert plan["payout_fee"]["amount"] == "5.00" and "never added on top" in plan["payout_fee"]["basis"]
    assert plan["rate"]["client_rate"] == 58.0 and plan["rate"]["locked_for"] == "1 hour" and plan["rate"]["locked_until"]
    assert plan["expected_local"] == {"amount": "6649.12", "currency": "PHP"}
    assert len(plan["if_things_change"]) == 4
    assert fake.count("POST", "/api/v1/simulation/deposit/create") == 0 and not fake.transfers   # no money moved
    run(payout, client, sim)
    assert payout.target_amount == plan["expected_local"]["amount"]      # and the plan came true to the cent


def test_the_route_follows_where_the_money_is_and_what_the_currency_allows():
    assert awx.choose_route("PHP")[0] == awx.PAY_WITH_QUOTE
    assert awx.choose_route("MXN")[0] == awx.CONVERT_THEN_PAY
    assert awx.choose_route("PHP", "PHP")[0] == awx.PAY_FROM_BALANCE       # after a refund came back in pesos


# ---- change 1: the deposit arrives short -------------------------------------------------------------------

def test_a_short_deposit_stops_everything_until_the_payer_and_the_claimant_agree(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, what_if="short_deposit")
    run(payout, client, sim)
    assert payout.state == awx.HELD and payout.hold["kind"] == "short_deposit"
    assert payout.hold["needs"] == ["payer", "claimant"]
    assert payout.hold["facts"]["approved"] == "120.00" and payout.hold["facts"]["arrived"] == "102.00"
    assert payout.funds == {"amount": "101.69", "currency": "USD"}            # 102.00 less the 0.31 fee booked
    assert not fake.transfers and fake.count("POST", "/api/v1/fx/quotes/create") == 1   # only the plan's quote
    calls = len(fake.calls)
    run(payout, client, sim)
    assert len(fake.calls) == calls                                           # paused means paused

    runner = payouts.PayoutRunner(None, lambda: (client, sim))
    runner.prepare_hold(payout, client, True)
    assert payout.hold["plan"]["expected_local"]["amount"] == str(awx.money((101.69 - 5) * 58, "PHP"))
    assert "102.00 USD" in payout.hold["explanation"] and "18.00 USD less" in payout.hold["explanation"]
    assert payout.hold["worded_by"] == "fixed sentence"                       # no model in the tests

    assert payout.agreed("payer") is False and payout.state == awx.HELD
    assert payout.agreed("claimant") is True and payout.state == awx.DEPOSIT_CONFIRMED
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.payer_pays == "101.69"
    assert len(fake.transfers) == 1 and fake.count("POST", "/api/v1/simulation/deposit/create") == 1
    assert fake.balance["USD"] == 0


# ---- change 2: the transfer fails, or comes back after it was paid ------------------------------------------

def replacement_beneficiary():
    return awx.local_beneficiary("PHP", "Maria", "Santos", "9876543210", swift_code="BOPIPHMM",
                                 street_address="123 Ayala Avenue", city="Makati", postcode="1226")


@pytest.mark.parametrize("what_if, fate", [("transfer_fails", "refused by the bank before it was paid"),
                                           ("transfer_returned", "returned by the bank after it was paid")])
def test_a_dead_transfer_is_replaced_once_from_what_came_back(tmp_path, fake, what_if, fate):
    payout, client, sim = planned(tmp_path, fake, what_if=what_if)
    run(payout, client, sim)
    if what_if == "transfer_returned":
        assert payout.state == awx.PAID       # it did show as paid
        advance(payout, client, sim)          # and reading it again finds the return
    first = payout.attempts[0]
    assert payout.state == awx.FAILED and payout.hold["kind"] == what_if.replace("fails", "failed")
    assert payout.hold["needs"] == ["bank_details", "payer", "claimant"]
    assert first["fate"] == fate and first["came_back"] == {"amount": "6649.12", "currency": "PHP"}
    assert first["fee_kept"]["amount"] == "5.0"
    assert payout.funds == {"amount": "6649.12", "currency": "PHP"} and payout.route == awx.PAY_FROM_BALANCE
    assert payout.transfer_request_id != first["request_id"] and payout.transfer_id is None
    assert payout.proof is None and payout.paid_at is None                    # nothing still claims it was paid

    runner = payouts.PayoutRunner(None, lambda: (client, sim))
    runner.prepare_hold(payout, client, True)
    plan = payout.hold["plan"]
    assert plan["replacement"] and plan["route"] == awx.PAY_FROM_BALANCE and plan["rate"] is None
    assert plan["expected_local"] == {"amount": "6359.12", "currency": "PHP"}   # the fee is charged again: 290.00
    assert "6,649.12 PHP came back" in payout.hold["explanation"]

    run(payout, client, sim)
    assert len(fake.transfers) == 1                                           # still paused: nothing was resent
    payout.beneficiary = replacement_beneficiary()
    agree(payout, "bank_details", "payer")
    run(payout, client, sim)
    assert len(fake.transfers) == 1
    agree(payout, "claimant")
    assert payout.state == awx.CONVERTED
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.target_amount == "6359.12"
    assert len(fake.transfers) == 2
    ids = [b["request_id"] for b in fake.bodies["/api/v1/transfers/create"]]
    assert len(set(ids)) == 2
    second = fake.bodies["/api/v1/transfers/create"][1]
    assert second["source_currency"] == "PHP" and second["source_amount"] == "6649.12" and "quote_id" not in second
    assert [t["status"] for t in fake.transfers.values()].count("PAID") == 1    # one payment, never two
    sums = {s["currency"]: Decimal(s["left"]) for s in payouts.reconciliation(payout.__dict__)["sums"]}
    assert sums == {"PHP": 0, "USD": 0}
    assert fake.balance["USD"] == 0 and fake.balance["PHP"] == 0


def test_no_replacement_is_sent_while_the_first_transfer_could_still_pay(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, what_if="transfer_fails")
    run(payout, client, sim)
    first = payout.attempts[0]["transfer_id"]
    payout.beneficiary = replacement_beneficiary()
    agree(payout, "bank_details", "payer", "claimant")
    advance(payout, client, sim)                       # the beneficiary is made
    fake.transfers[first]["status"] = "SENT"           # Airwallex now says the first one is alive after all
    with pytest.raises(ValueError, match="no replacement is sent"):
        advance(payout, client, sim)
    assert len(fake.transfers) == 1 and payout.state == awx.BENEFICIARY_READY


def test_a_restart_in_the_middle_of_a_replacement_still_sends_one(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, what_if="transfer_fails")
    run(payout, client, sim)
    payout.beneficiary = replacement_beneficiary()
    agree(payout, "bank_details", "payer", "claimant")
    advance(payout, client, sim)
    advance(payout, client, sim)
    assert payout.state == awx.TRANSFER_CREATED
    revived = Payout.load(payout.path)                 # the process died here
    client2 = make_client(fake)
    run(revived, client2, SandboxSimulator(client2))
    assert revived.state == awx.PAID and len(fake.transfers) == 2
    assert fake.count("POST", "/api/v1/transfers/create") == 2


# ---- change 3: the rate lock runs out, or the quote has to be taken again -----------------------------------

def test_a_rate_lock_that_runs_out_is_put_to_the_claimant_before_anything_is_converted(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, what_if="rate_lock_expires")
    assert payout.plan["rate"]["locked_for"] == "1 minute"
    clock = lambda: fake.now
    advance(payout, client, sim, clock)
    assert payout.state == awx.DEPOSIT_CONFIRMED
    advance(payout, client, sim, clock)
    assert payout.state == awx.DEPOSIT_CONFIRMED and not fake.transfers      # waiting for the lock to run out
    fake.now += 61
    fake.rates["PHP"] = 57.0
    advance(payout, client, sim, clock)
    assert payout.state == awx.HELD and payout.hold["kind"] == "rate_lock_expired"
    assert payout.hold["needs"] == ["claimant"]                               # the approved dollars did not change
    facts = payout.hold["facts"]
    assert (facts["old_rate"], facts["new_rate"]) == (58.0, 57.0)
    assert (facts["old_local"], facts["new_local"]) == ("6649.12", "6534.48")
    runner = payouts.PayoutRunner(None, lambda: (client, sim))
    runner.prepare_hold(payout, client, True)
    assert payout.hold["plan"]["expected_local"]["amount"] == "6534.48"      # the plan shows the lock already taken
    assert "6,534.48 PHP instead of 6,649.12 PHP" in payout.hold["explanation"]
    assert not fake.transfers
    payout.confirmed = {"plan_id": payout.hold["plan"]["id"], "local_amount": "6534.48"}
    agree(payout, "claimant")
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.target_amount == "6534.48" and len(fake.transfers) == 1


def test_a_quote_that_airwallex_reports_as_expired_at_the_last_moment_sends_nothing(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake)
    while payout.state != awx.BENEFICIARY_READY:
        advance(payout, client, sim)
    fake.now += 3700                                   # Airwallex's clock is past the hour; ours has not noticed
    advance(payout, client, sim)
    assert payout.state == awx.DEPOSIT_CONFIRMED and not fake.transfers
    advance(payout, client, sim)
    assert payout.state == awx.HELD and payout.hold["kind"] == "rate_lock_expired" and not fake.transfers


def test_a_new_quote_within_the_tolerance_goes_ahead_and_is_noted_and_beyond_it_stops(tmp_path, fake):
    # The plan expected a 0.3 percent incoming fee. Airwallex books 0.4 percent, so the quote no longer fits.
    payout, client, sim = planned(tmp_path, fake)
    fake.incoming_fee_rate = 0.004
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.deposit_fee == "0.48"
    note = next(d for d in payout.decisions if d["kind"] == "requoted")
    assert "went ahead without asking again" in note["text"] and payout.payer_pays == "119.52"

    other = tmp_path / "second"
    other.mkdir()
    fake2 = FakeAirwallex()
    fake2.incoming_fee_rate, fake2.payout_fee_usd = 0.003, 5.0
    payout, client, sim = planned(other, fake2)
    fake2.incoming_fee_rate, fake2.rates["PHP"] = 0.004, 56.0      # and the rate has dropped by 3.4 percent
    run(payout, client, sim)
    assert payout.state == awx.HELD and payout.hold["kind"] == "amount_changed" and not fake2.transfers


# ---- wording -----------------------------------------------------------------------------------------------

FACTS = {"approved": "120.00", "arrived": "102.00", "difference": "18.00", "incoming_fee": "0.31", "left": "101.69"}
PLAN = {"expected_local": {"amount": "5608.02", "currency": "PHP"}}


def test_the_model_only_rewords_and_any_answer_that_changes_a_figure_is_thrown_away(monkeypatch):
    fixed = payouts.fixed_explanation("short_deposit", FACTS, PLAN)
    assert "102.00 USD" in fixed and "5,608.02 PHP" in fixed
    assert payouts.word_change("short_deposit", FACTS, PLAN) == {"text": fixed, "worded_by": "fixed sentence"}

    good = ("Only 102.00 USD arrived, 18.00 USD less than the 120.00 USD that was approved. Nothing has moved yet, "
            "and on that amount you would get about 5,608.02 PHP.")
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: good)
    assert payouts.word_change("short_deposit", FACTS, PLAN)["text"] == good

    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: good.replace("5,608.02", "6,000.00"))
    assert payouts.word_change("short_deposit", FACTS, PLAN)["text"] == fixed      # an invented amount
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: "A smaller amount arrived. Please agree to it.")
    assert payouts.word_change("short_deposit", FACTS, PLAN)["text"] == fixed      # the figures were dropped


# ---- the same changes through the app: who has to agree, and in what order ----------------------------------

import json
import time

from fastapi.testclient import TestClient

from khutlisa.server import create_app
from test_claims import AS_PAYER, CLAIMANT, PAYER_KEY, PH_BANK, World, give_bank, open_claim


class Live(World):
    """The app over a fake Airwallex that charges what the sandbox charges."""

    watch_seconds = 0.0

    def make_app(self):
        self.fake.incoming_fee_rate, self.fake.payout_fee_usd = 0.003, 5.0
        return create_app(db_path=self.db, totals_path=self.folder / "totals.json", web_dist=self.folder / "no-web",
                          airwallex_factory=self.factory, payout_pause=0.0, payer_key=PAYER_KEY,
                          watch_seconds=self.watch_seconds, watch_pause=0.01)


class Watching(Live):
    watch_seconds = 30.0


@pytest.fixture
def live(tmp_path):
    world = Live(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        yield api


def approved_php(api):
    claim = open_claim(api)
    give_bank(api, claim["id"], PH_BANK)
    assert api.post(f"/api/payer/claims/{claim['id']}/approve").status_code == 200
    return claim["id"]


def start(api, claim_id, what_if=None):
    plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={"what_if": what_if}).json()
    assert plan["plan"]["what_if"] == what_if
    r = api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["plan"]["id"]})
    assert r.status_code == 200, r.text
    api.world.app.state.payouts.join(claim_id)
    return api.get(f"/api/claims/{claim_id}/payout").json()


def claimant_agrees(api, claim_id):
    view = api.get(f"/api/claims/{claim_id}/payout").json()
    return api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": view["plan"]["id"]})


def test_the_what_if_cases_are_offered_only_where_the_sandbox_can_stage_them(live):
    claim_id = approved_php(live)
    view = live.get(f"/api/claims/{claim_id}/payout").json()
    assert [o["key"] for o in view["what_if_options"]] == list(awx.WHAT_IFS)
    assert all(o["label"] for o in view["what_if_options"])
    assert live.post(f"/api/claims/{claim_id}/payout/plan", json={"what_if": "the_moon"}).status_code == 422


def test_a_short_deposit_needs_the_payers_new_approval_and_then_the_claimants_agreement(live):
    claim_id = approved_php(live)
    view = start(live, claim_id, "short_deposit")
    assert view["state"] == "HELD" and view["claim_state"] == "PAYMENT_HELD" and view["approved"] is False
    assert view["hold"]["kind"] == "short_deposit" and view["hold"]["needs"] == ["payer", "claimant"]
    assert "1,564.47 USD" in view["hold"]["explanation"] and "276.08 USD less" in view["hold"]["explanation"]
    assert view["deposit"] == {"amount": "1564.47", "currency": "USD", "expected": "1840.55", "arrived": True,
                               "reference": f"KHUTLISA-{claim_id}", "id": view["deposit"]["id"]}
    assert view["incoming_fee"] == {"amount": "4.69", "currency": "USD"}
    assert view["plan"]["expected_local"]["amount"] == str(awx.money((1564.47 - 4.69 - 5) * 58, "PHP"))
    assert "Held for this claim at Airwallex right now: 1,559.78 USD." == view["reconciliation"]["statement"]
    claim = live.get(f"/api/claims/{claim_id}").json()
    assert "less money arrived than was approved" in claim["approvals_withdrawn"][0]["because"]
    assert not live.world.fake.transfers

    early = claimant_agrees(live, claim_id)
    assert early.status_code == 409 and "holder has to approve the new terms first" in early.json()["detail"]
    row = next(r for r in live.get("/api/payer/queue").json()["claims"] if r["id"] == claim_id)
    assert row["can_decide"] is True and row["can_reject"] is False and row["hold"]["funds"]["amount"] == "1559.78"
    again = live.post(f"/api/payer/claims/{claim_id}/approve").json()
    assert again["state"] == "PAYING" and again["approval"]["amount"] == "1559.78" and again["hold"]["needs"] == ["claimant"]
    assert not live.world.fake.transfers                                    # approved, and still nothing sent

    stale = live.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": "0" * 36})
    assert stale.status_code == 409 and "plan has changed" in stale.json()["detail"]
    assert claimant_agrees(live, claim_id).status_code == 200
    live.world.app.state.payouts.join(claim_id)
    done = live.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and done["claim_state"] == "PAID" and done["hold"] is None
    assert done["left_wallet"] == {"amount": "1559.78", "currency": "USD"}
    assert done["received"]["amount"] == view["plan"]["expected_local"]["amount"]
    assert done["reconciliation"]["balanced"] and len(live.world.fake.transfers) == 1


def test_a_refused_transfer_is_replaced_only_after_new_details_a_new_approval_and_agreement(live):
    claim_id = approved_php(live)
    view = start(live, claim_id, "transfer_fails")
    assert view["state"] == "FAILED" and view["claim_state"] == "PAYMENT_HELD"
    assert view["hold"]["needs"] == ["bank_details", "payer", "claimant"] and view["received"] is None
    assert view["attempts"][0]["fate"] == "refused by the bank before it was paid"
    came_back = view["attempts"][0]["came_back"]
    assert came_back["currency"] == "PHP" and view["funds"] == came_back
    assert view["plan"]["route"] == "pay_from_balance" and view["plan"]["replacement"] is True
    paid = {s["stage"]: s["count"] for s in live.get("/api/payer/results").json()["stages"]}["paid"]
    assert paid == 0

    row = next(r for r in live.get("/api/payer/queue").json()["claims"] if r["id"] == claim_id)
    assert row["can_decide"] is False and row["hold"]["waiting_for_bank_details"] is True
    assert live.post(f"/api/payer/claims/{claim_id}/approve").status_code == 409     # nothing to approve yet
    assert claimant_agrees(live, claim_id).status_code == 409
    wrong_currency = live.put(f"/api/claims/{claim_id}/payee", json={
        "currency": "MXN", "first_name": "Maria", "last_name": "Santos", "account_number": "002010077777777771",
        "street_address": "Avenida Reforma 100", "city": "Ciudad de Mexico", "postcode": "06600", "state": "MX-CMX"})
    assert wrong_currency.status_code == 409 and "already held in PHP" in wrong_currency.json()["detail"]
    give_bank(live, claim_id, {**PH_BANK, "account_number": "9876543210"})
    assert claimant_agrees(live, claim_id).status_code == 409                                   # the payer comes first
    approved = live.post(f"/api/payer/claims/{claim_id}/approve").json()
    assert approved["approval"]["currency"] == "PHP" and approved["approval"]["amount"] == came_back["amount"]
    assert approved["approval"]["replaces_earlier_approval"] is True
    assert approved["payee"]["account_number"].endswith("3210") and len(live.world.fake.transfers) == 1
    assert claimant_agrees(live, claim_id).status_code == 200
    live.world.app.state.payouts.join(claim_id)

    done = live.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and done["claim_state"] == "PAID" and done["account"]["number"].endswith("3210")
    assert done["received"]["amount"] == view["plan"]["expected_local"]["amount"]
    assert done["reconciliation"]["balanced"] and len(done["attempts"]) == 1
    transfers = list(live.world.fake.transfers.values())
    assert [t["status"] for t in transfers].count("PAID") == 1 and len(transfers) == 2
    assert transfers[1]["source_currency"] == "PHP" and transfers[1]["amount_payer_pays"] == float(came_back["amount"])
    notes = " ".join(e["note"] for e in live.get(f"/api/claims/{claim_id}").json()["history"])
    assert "refused the transfer" in notes and "approved the new terms" in notes and "carried on" in notes


def test_a_payment_the_bank_returns_after_it_showed_as_paid_is_shown_as_returned(tmp_path):
    world = Watching(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        claim_id = approved_php(api)
        plan = api.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()["plan"]
        api.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]})
        view = {}
        for _ in range(400):
            view = api.get(f"/api/claims/{claim_id}/payout").json()
            if view["state"] == "PAID":
                break
            time.sleep(0.01)
        assert view["state"] == "PAID" and view["watching_for_return"] is True
        assert api.get(f"/api/claims/{claim_id}").json()["state"] == "PAID"
        world.fake.bank_refuses(view["transfer_id"], "CANCELLED")       # the receiving bank sends the money back
        for _ in range(400):
            view = api.get(f"/api/claims/{claim_id}/payout").json()
            if view["state"] == "FAILED" and view["claim_state"] == "PAYMENT_HELD":
                break
            time.sleep(0.01)
        assert view["state"] == "FAILED" and view["hold"]["kind"] == "transfer_returned"
        assert view["claim_state"] == "PAYMENT_HELD" and view["journey"][-1]["done"] is False
        assert "returned the money after the transfer had been paid" in view["hold"]["explanation"]
        results = api.get("/api/payer/results").json()
        assert {s["stage"]: s["count"] for s in results["stages"]}["paid"] == 0 and results["payment_held"] == 1


def test_after_a_restart_a_paid_transfer_is_read_again_and_a_return_is_found(tmp_path):
    world = Live(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        claim_id = approved_php(api)
        assert start(api, claim_id)["state"] == "PAID"
    paid = json.loads(world.app.state.claims.payout_path(claim_id).read_text())
    world.fake.bank_refuses(paid["transfer_id"], "CANCELLED")           # it happens while the server is down
    world.watch_seconds = 30.0
    restarted = world.make_app()
    with TestClient(restarted, headers=AS_PAYER) as api:
        view = {}
        for _ in range(400):
            view = api.get(f"/api/claims/{claim_id}/payout").json()
            if view["state"] == "FAILED" and view["claim_state"] == "PAYMENT_HELD":
                break
            time.sleep(0.01)
        assert view["state"] == "FAILED" and view["claim_state"] == "PAYMENT_HELD"
    assert len(world.fake.transfers) == 1


def test_a_lock_that_ran_out_needs_only_the_claimant_because_the_approved_dollars_did_not_change(live, monkeypatch):
    claim_id = approved_php(live)
    plan = live.post(f"/api/claims/{claim_id}/payout/plan", json={"what_if": "rate_lock_expires"}).json()["plan"]
    assert plan["rate"]["locked_for"] == "1 minute"
    # Time passes at Airwallex and for us: the one-minute lock is over before the deposit is in.
    monkeypatch.setattr(awx.time, "time", lambda: live.world.fake.now)
    live.world.fake.now += 90
    late = live.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]})
    assert late.status_code == 409 and "no longer locked" in late.json()["detail"]
    plan = live.post(f"/api/claims/{claim_id}/payout/plan", json={"what_if": "rate_lock_expires"}).json()["plan"]
    assert live.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]}).status_code == 200
    live.world.app.state.payouts.join(claim_id)
    waiting = live.get(f"/api/claims/{claim_id}/payout").json()
    assert waiting["state"] == "DEPOSIT_CONFIRMED" and not live.world.fake.transfers    # held back while locked
    live.world.fake.rates["PHP"] = 57.5
    live.world.fake.now += 90
    assert live.post(f"/api/claims/{claim_id}/payout/resume").status_code == 200
    for _ in range(400):
        view = live.get(f"/api/claims/{claim_id}/payout").json()
        if view["state"] == "HELD" and view["hold"]["ready"]:
            break
        assert view["state"] != "HELD" or view["plan"] is None      # the spent plan is never offered again
        time.sleep(0.01)
    assert view["state"] == "HELD" and view["hold"]["kind"] == "rate_lock_expired"
    assert view["hold"]["needs"] == ["claimant"] and view["claim_state"] == "PAYING" and view["approved"] is True
    assert "57.5" in view["hold"]["explanation"] and not live.world.fake.transfers
    assert claimant_agrees(live, claim_id).status_code == 200
    live.world.app.state.payouts.join(claim_id)
    done = live.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and done["rate"] == 57.5
    # What was booked is what is shown. The plan's figure was an expectation and may differ by a rounded centavo.
    assert abs(Decimal(done["received"]["amount"]) - Decimal(view["plan"]["expected_local"]["amount"])) <= Decimal("0.01")


def test_a_stop_that_was_cut_short_by_a_restart_still_gets_its_new_plan(tmp_path):
    world = Live(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        claim_id = approved_php(api)
        assert start(api, claim_id, "short_deposit")["hold"]["ready"] is True
    path = world.app.state.claims.payout_path(claim_id)
    saved = json.loads(path.read_text())
    saved["hold"].pop("plan"), saved["hold"].pop("explanation"), saved["hold"].pop("worded_by")
    path.write_text(json.dumps(saved))                 # as if the server had stopped right after the deposit was read
    restarted = world.make_app()
    with TestClient(restarted, headers=AS_PAYER) as api:
        restarted.state.payouts.join(claim_id)
        view = api.get(f"/api/claims/{claim_id}/payout").json()
        assert view["hold"]["ready"] is True and view["plan"]["expected_local"]["currency"] == "PHP"
    assert not world.fake.transfers and world.fake.count("POST", "/api/v1/simulation/deposit/create") == 1


def test_people_can_act_while_the_change_is_still_being_put_into_words(live):
    """The wording can take seconds. Whatever is agreed in that time must not be lost, and the payment must
    carry on by itself once the last person has agreed."""
    import threading
    waiting, go_on = threading.Event(), threading.Event()

    def slow(kind, facts, plan):
        waiting.set()
        go_on.wait(5)
        return {"text": payouts.fixed_explanation(kind, facts, plan), "worded_by": "fixed sentence"}

    runner = live.world.app.state.payouts
    runner.word = slow
    claim_id = approved_php(live)
    plan = live.post(f"/api/claims/{claim_id}/payout/plan", json={"what_if": "transfer_fails"}).json()["plan"]
    live.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["id"]})
    assert waiting.wait(5)                                   # the transfer was refused; the wording has begun
    give_bank(live, claim_id, {**PH_BANK, "account_number": "9876543210"})
    assert live.post(f"/api/payer/claims/{claim_id}/approve").status_code == 200
    assert claimant_agrees(live, claim_id).status_code == 200
    go_on.set()                                              # only now does the wording come back
    runner.join(claim_id)
    done = live.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and done["hold"] is None and done["claim_state"] == "PAID"
    assert len(live.world.fake.transfers) == 2
    assert [t["status"] for t in live.world.fake.transfers.values()].count("PAID") == 1
    assert any(d["kind"] == "transfer_failed" for d in done["decisions"])      # the change is still on record
