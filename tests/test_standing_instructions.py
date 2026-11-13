"""The holder's standing instructions: set once, bound into each approval, and followed by the payment machine.
Inside them the agent acts alone and writes down what it did and why. Outside them it stops and asks the right
party. Every amount, limit and comparison is code; a fake Airwallex stands behind every test."""
from __future__ import annotations

from decimal import Decimal

import pytest

from khutlisa import airwallex as awx
from khutlisa import instructions as ins
from khutlisa import payouts
from khutlisa.airwallex import Payout, SandboxSimulator, advance, run
from test_airwallex import FakeAirwallex, make_client

RULES = ins.clean({"tolerance_percent": "0.5", "small_claim_usd": "250", "route_rule": "most_to_claimant",
                   "deadline_days": 14})


# ---- the rules themselves ------------------------------------------------------------------------------------

def test_instructions_are_cleaned_and_out_of_range_values_are_refused():
    assert RULES == {"tolerance_percent": "0.5", "small_claim_usd": "250.00", "route_rule": "most_to_claimant",
                     "deadline_days": 14}
    for bad in ({"tolerance_percent": "-1"}, {"tolerance_percent": "25"}, {"small_claim_usd": "-5"},
                {"deadline_days": 0}, {"deadline_days": 400}, {"route_rule": "whatever"}, {"tolerance_percent": "x"}):
        with pytest.raises(ValueError):
            ins.clean({**RULES, **bad})


def test_the_tolerance_lets_a_small_shortfall_through_and_any_gain_and_stops_a_larger_shortfall():
    ok, short = ins.within_tolerance("1000.00", "996.00", RULES)       # 0.4 percent less
    assert ok and short == Decimal("0.40")
    ok, short = ins.within_tolerance("1000.00", "994.00", RULES)       # 0.6 percent less
    assert not ok and short == Decimal("0.60")
    assert ins.within_tolerance("1000.00", "1010.00", RULES)[0]        # more for the claimant is never a reason to ask
    assert not ins.within_tolerance("1000.00", "999.99", None)[0]      # no instructions: nothing is waved through


def test_below_the_small_claim_line_the_holder_bears_airwallex_fees_and_the_arithmetic_is_shown():
    small = ins.fee_plan("120.00", RULES)
    # The holder sends enough for 120.00 to be left after the 0.3 percent incoming fee and the 5.00 payout fee:
    # (120.00 + 5.00) / (1 - 0.003) = 125.38.
    assert small["bearer"] == "holder" and small["holder_sends"] == "125.38" and small["holder_adds"] == "5.38"
    assert small["expected_incoming_fee"] == "0.38" and small["expected_payout_fee_usd"] == "5.00"
    assert small["left_for_claimant_usd"] == "120.00"
    assert small["without_rule"] == {"fees": "5.36", "share_percent": "4.5"}
    assert any("125.38" in line for line in small["arithmetic"]) and any("4.5 percent" in line for line in small["arithmetic"])

    large = ins.fee_plan("2316.40", RULES)
    assert large["bearer"] == "claim" and large["holder_sends"] == "2316.40" and large["holder_adds"] == "0.00"
    assert large["left_for_claimant_usd"] == "2304.45"                  # 2316.40 - 6.95 - 5.00
    assert ins.fee_plan("250.00", RULES)["bearer"] == "claim"           # the line itself is not below the line
    none = ins.fee_plan("120.00", None)
    assert none["bearer"] == "claim" and none["holder_sends"] == "120.00"


def test_the_deadline_is_counted_from_the_approval():
    assert ins.deadline_at("2026-11-12T10:00:00+00:00", RULES) == "2026-11-26T10:00:00+00:00"
    assert ins.deadline_at("2026-11-12T10:00:00+00:00", None) is None
    assert "0.5 percent" in " ".join(ins.in_words(RULES)) and "250.00" in " ".join(ins.in_words(RULES))


# ---- the machine follows them --------------------------------------------------------------------------------

@pytest.fixture
def fake():
    f = FakeAirwallex()
    f.incoming_fee_rate, f.payout_fee_usd = 0.003, 5.0     # what the live sandbox charges
    return f


def planned(tmp_path, fake, currency="PHP", usd="120.00", what_if=None, rules=RULES, approved_at=None):
    """A payout approved under the standing instructions, with a plan the claimant has agreed to."""
    client = make_client(fake)
    fees = ins.fee_plan(usd, rules)
    payout = Payout.open(tmp_path / "payout.json", usd_amount=fees["holder_sends"], target_currency=currency,
                         state=awx.PLANNED, deposit_reference="KHUTLISA-test",
                         beneficiary=awx.EXAMPLE_BENEFICIARIES[currency])
    payout.what_if, payout.instructions, payout.claim_usd = what_if, rules, usd
    if approved_at:
        payout.deadline_at = ins.deadline_at(approved_at, rules)
    plan = payouts.make_plan(payout, client, simulator_ready=True)
    payout.confirmed = {"plan_id": plan["id"], "local_amount": plan["expected_local"]["amount"]}
    payout._move(awx.DEPOSIT_EXPECTED, "plan agreed")
    return payout, client, SandboxSimulator(client)


def alone(payout, kind):
    """The note of something the machine decided without asking."""
    return next((d for d in payout.decisions if d["kind"] == kind and d.get("by") == "agent"), None)


def test_a_lock_that_runs_out_is_requoted_and_inside_the_tolerance_the_agent_carries_on_alone(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, usd="2316.40", what_if="rate_lock_expires")
    clock = lambda: fake.now
    advance(payout, client, sim, clock)
    advance(payout, client, sim, clock)
    assert payout.state == awx.DEPOSIT_CONFIRMED                 # waiting for the staged lock to run out
    fake.now += 61
    fake.rates["PHP"] = 57.8                                     # 0.34 percent worse than the 58.0 that was agreed
    while payout.state not in (awx.PAID,) + awx.STOPPED:
        advance(payout, client, sim, clock)
    assert payout.state == awx.PAID and not payout.hold
    note = alone(payout, "requoted")
    assert note["rule"] == "tolerance" and "0.34 percent" in note["text"] and "0.5 percent" in note["text"]
    assert "without asking" in note["text"]
    assert payout.quote_validity == "HR_1"                      # the new lock lasts an hour and is labelled so


def test_outside_the_tolerance_the_agent_stops_and_asks_the_claimant_and_the_new_lock_is_labelled_one_hour(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, usd="2316.40", what_if="rate_lock_expires")
    assert payout.plan["rate"]["locked_for"] == "1 minute"
    clock = lambda: fake.now
    advance(payout, client, sim, clock)
    fake.now += 61
    fake.rates["PHP"] = 57.0                                     # 1.72 percent worse
    advance(payout, client, sim, clock)
    assert payout.state == awx.HELD and payout.hold["kind"] == "rate_lock_expired"
    assert payout.hold["needs"] == ["claimant"] and not fake.transfers
    assert payout.hold["facts"]["shortfall_percent"] == "1.72"
    runner = payouts.PayoutRunner(None, lambda: (client, sim))
    runner.prepare_hold(payout, client, True)
    assert payout.hold["plan"]["rate"]["locked_for"] == "1 hour"   # it used to say 1 minute for a lock of an hour


def test_at_the_moment_of_conversion_the_agent_takes_the_better_of_the_lock_and_a_fresh_quote(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, "MXN", "2316.40")
    fake.rates["MXN"] = 18.6                                     # the market moved in the claimant's favour
    run(payout, client, sim)
    assert payout.state == awx.PAID
    note = alone(payout, "better_rate")
    assert note["rule"] == "route" and "18.5" in note["text"] and "18.6" in note["text"]
    assert Decimal(payout.target_amount) > Decimal(payout.confirmed["local_amount"])
    claim = {"id": "c" * 16, "state": "PAID", "record": {"amount": 2316.40}, "history": [], "payee": None, "approval": None}
    said = payouts.view(claim, payout.__dict__, running=False, problem=None, credentials_ready=True)["agreed_and_paid"]
    assert Decimal(said["difference"]["amount"]) > 0 and "better rate than the one locked" in said["note"]

    other = tmp_path / "second"
    other.mkdir()
    fake2 = FakeAirwallex()
    fake2.incoming_fee_rate, fake2.payout_fee_usd = 0.003, 5.0
    payout, client, sim = planned(other, fake2, "MXN", "2316.40")
    fake2.rates["MXN"] = 18.4                                    # it moved against her: the lock is the floor
    run(payout, client, sim)
    assert payout.state == awx.PAID and alone(payout, "kept_lock") and not alone(payout, "better_rate")
    assert fake2.conversions[0]["client_rate"] == 18.5


def test_a_deposit_a_few_cents_short_is_inside_the_tolerance_and_a_large_shortfall_is_not(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(awx, "SHORT_DEPOSIT_SHARE", Decimal("0.998"))     # the staged deposit is 0.2 percent short
    payout, client, sim = planned(tmp_path, fake, usd="2316.40", what_if="short_deposit")
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.deposit_amount == "2311.77"
    note = alone(payout, "short_within_tolerance")
    assert note["rule"] == "tolerance" and "4.63 USD" in note["text"]
    assert fake.balance["USD"] == 0

    monkeypatch.setattr(awx, "SHORT_DEPOSIT_SHARE", Decimal("0.85"))
    other = tmp_path / "second"
    other.mkdir()
    fake2 = FakeAirwallex()
    fake2.incoming_fee_rate, fake2.payout_fee_usd = 0.003, 5.0
    payout, client, sim = planned(other, fake2, usd="2316.40", what_if="short_deposit")
    run(payout, client, sim)
    assert payout.state == awx.HELD and payout.hold["needs"] == ["payer", "claimant"] and not fake2.transfers


def test_after_the_deadline_nothing_is_sent_and_the_holder_is_asked(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, usd="2316.40", approved_at="2026-11-12T10:00:00+00:00")
    late = awx._parse_time("2026-11-26T10:00:01+00:00")
    advance(payout, client, sim, lambda: late - 60)              # the deposit is read in time
    assert payout.state == awx.DEPOSIT_CONFIRMED
    advance(payout, client, sim, lambda: late)
    assert payout.state == awx.HELD and payout.hold["kind"] == "deadline_passed"
    assert payout.hold["needs"] == ["payer"] and payout.hold["resume"] == awx.DEPOSIT_CONFIRMED
    assert not fake.transfers and not fake.conversions
    text = payouts.fixed_explanation("deadline_passed", payout.hold["facts"], None)
    assert "26 Nov 2026" in text and "holder" in text


def test_a_refused_transfer_on_a_large_claim_is_replaced_without_asking_the_claimant_again(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, usd="2316.40", what_if="transfer_fails")
    agreed = payout.confirmed["local_amount"]
    run(payout, client, sim)
    assert payout.state == awx.FAILED and payout.hold["kind"] == "transfer_failed"
    runner = payouts.PayoutRunner(None, lambda: (client, sim))
    runner.prepare_hold(payout, client, True)
    # 133,658.10 PHP was agreed. The replacement pays the 290.00 PHP payout fee again: 0.22 percent less, inside
    # the 0.5 percent tolerance. The bank account is new, so the claimant must give it and the holder approve it.
    assert payout.hold["needs"] == ["bank_details", "payer"]
    note = alone(payout, "replacement_within_tolerance")
    assert note["rule"] == "tolerance" and "0.22 percent" in note["text"] and "133,368.10 PHP" in note["text"]
    assert alone(payout, "route_changed")["rule"] == "route"
    assert payout.confirmed["local_amount"] == agreed and payout.confirmed["by"] == "standing instructions"
    payout.beneficiary = awx.local_beneficiary("PHP", "Maria", "Santos", "9876543210", swift_code="BOPIPHMM",
                                               street_address="123 Ayala Avenue", city="Makati", postcode="1226")
    payout.agreed("bank_details")
    run(payout, client, sim)
    assert len(fake.transfers) == 1                              # the holder has not approved the new account yet
    payout.agreed("payer")
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.target_amount == "133368.10" and len(fake.transfers) == 2
    assert [t["status"] for t in fake.transfers.values()].count("PAID") == 1
    assert "can no longer pay" in alone(payout, "replacement_cleared")["text"]
    sums = {s["currency"]: Decimal(s["left"]) for s in payouts.reconciliation(payout.__dict__)["sums"]}
    assert sums == {"PHP": 0, "USD": 0}


def test_a_refused_transfer_on_a_small_claim_falls_outside_the_tolerance_so_the_claimant_is_asked(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, usd="400.00", what_if="transfer_fails")
    run(payout, client, sim)
    runner = payouts.PayoutRunner(None, lambda: (client, sim))
    runner.prepare_hold(payout, client, True)
    assert payout.hold["needs"] == ["bank_details", "payer", "claimant"]
    assert payout.hold["facts"]["claimant_asked"] is True and not alone(payout, "replacement_within_tolerance")


# ---- the route and the fee rule in the plan ------------------------------------------------------------------

def test_the_plan_compares_the_routes_with_airwallex_own_quote_and_fees_and_takes_the_one_that_delivers_most(tmp_path, fake):
    fake.mid_rates = {"MXN": 18.7}       # as on the sandbox: the mid rate sits above the rate the client gets
    payout, client, sim = planned(tmp_path, fake, "MXN", "2316.40")
    plan = payout.plan
    routes = {r["route"]: r for r in plan["routes_compared"]}
    # Convert first: 2,309.45 x 18.5 = 42,724.83, less a payout fee of 5.00 x 18.7 = 93.50 MXN: 42,631.33.
    # Pay with the quote: (2,309.45 - 5.00) x 18.5 = 42,632.33. One peso more reaches the claimant.
    assert routes[awx.CONVERT_THEN_PAY]["would_receive"]["amount"] == "42631.33"
    assert routes[awx.PAY_WITH_QUOTE]["would_receive"]["amount"] == "42632.33"
    assert plan["route"] == awx.PAY_WITH_QUOTE and "1.00 MXN more" in plan["route_reason"]
    assert [r["chosen"] for r in plan["routes_compared"]].count(True) == 1
    assert alone(payout, "route_chosen")["rule"] == "route"
    run(payout, client, sim)
    assert payout.state == awx.PAID and not payout.conversion_id
    assert abs(Decimal(payout.target_amount) - Decimal("42632.33")) <= Decimal("0.01")   # the fake rounds in floats


def test_a_tie_between_routes_goes_to_the_one_that_fixes_the_local_amount_first_and_one_route_is_said_plainly(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, "MXN", "2316.40")      # the fake's mid rate equals its client rate
    assert payout.plan["route"] == awx.CONVERT_THEN_PAY and "same amount" in payout.plan["route_reason"]
    other = tmp_path / "second"
    other.mkdir()
    payout, client, sim = planned(other, fake, "PHP", "2316.40")
    assert payout.plan["route"] == awx.PAY_WITH_QUOTE and len(payout.plan["routes_compared"]) == 2
    held = next(r for r in payout.plan["routes_compared"] if r["route"] == awx.CONVERT_THEN_PAY)
    assert held["available"] is False and "does not convert" in held["why_not"]


def test_route_fees_are_the_ones_airwallex_charged_on_the_last_such_transfers(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, "MXN", "1000.00")
    run(payout, client, sim)                                           # one MXN payout from a held balance: 92.50 MXN
    fees = awx.observed_payout_fees(client, "MXN")
    assert fees["MXN"]["amount"] == "92.50" and "USD" not in fees
    other = tmp_path / "second"
    other.mkdir()
    fake.rates["MXN"] = 18.0                                           # today 5.00 USD is worth 90.00 MXN
    payout, client, sim = planned(other, fake, "MXN", "1000.00")
    held = next(r for r in payout.plan["routes_compared"] if r["route"] == awx.CONVERT_THEN_PAY)
    assert held["payout_fee"] == {"amount": "92.50", "currency": "MXN",
                                  "basis": "what Airwallex charged on the last payout made this way"}
    assert payout.plan["route"] == awx.PAY_WITH_QUOTE                 # (997 - 5) x 18 beats 997 x 18 - 92.50


def test_a_small_claim_is_not_eaten_by_fees_because_the_holder_bears_them(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, usd="120.00")
    plan = payout.plan
    assert payout.usd_amount == "125.38" and plan["fee_rule"]["bearer"] == "holder"
    assert plan["lines"][0]["amount"] == "125.38" and plan["fee_rule"]["holder_adds"] == "5.38"
    assert plan["expected_local"] == {"amount": "6960.00", "currency": "PHP"}     # all of 120.00 at 58.0
    assert alone(payout, "fee_rule")["rule"] == "fees"
    run(payout, client, sim)
    assert payout.state == awx.PAID and payout.target_amount == "6960.00" and payout.deposit_amount == "125.38"
    assert payouts.reconciliation(payout.__dict__)["balanced"] and fake.balance["USD"] == 0


def test_the_screen_gets_what_the_agent_decided_alone_and_the_first_time_the_money_arrived(tmp_path, fake):
    payout, client, sim = planned(tmp_path, fake, usd="2316.40", what_if="transfer_fails")
    run(payout, client, sim)
    first_arrival = next(e["at"] for e in payout.history if e["state"] == awx.DEPOSIT_CONFIRMED)
    payout.history.append({"state": awx.DEPOSIT_CONFIRMED, "at": "2099-01-01T00:00:00+00:00", "note": "later"})
    claim = {"id": "c" * 16, "state": "PAYMENT_HELD", "record": {"amount": 2316.40}, "history": [],
             "payee": None, "approval": None}
    shown = payouts.view(claim, payout.__dict__, running=False, problem=None, credentials_ready=True)
    assert next(j for j in shown["journey"] if j["key"] == "arrived")["at"] == first_arrival
    kinds = [d["kind"] for d in shown["agent_report"]]
    assert kinds[:2] == ["fee_rule", "route_chosen"] and "route_changed" in kinds
    assert all(d["title"] and d["text"] and d["rule_name"] for d in shown["agent_report"])
    assert shown["instructions"]["in_words"] == ins.in_words(RULES)
    assert [d["at"] for d in shown["decisions"]] == sorted(d["at"] for d in shown["decisions"])


# ---- through the app: set once by the holder, bound into the approval ------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from test_claims import AS_PAYER, PH_BANK, give_bank, open_claim  # noqa: E402
from test_payment_changes import Live, claimant_agrees, start  # noqa: E402


@pytest.fixture
def live(tmp_path):
    world = Live(tmp_path)
    with TestClient(world.app, headers=AS_PAYER) as api:
        api.world = world
        yield api


def set_rules(api, **changes):
    r = api.put("/api/payer/instructions", json={**RULES, **changes})
    assert r.status_code == 200, r.text
    return r.json()


def approved(api):
    claim = open_claim(api)                       # 1,840.55 USD, paid to the Philippines
    give_bank(api, claim["id"], PH_BANK)
    row = api.post(f"/api/payer/claims/{claim['id']}/approve")
    assert row.status_code == 200, row.text
    return claim["id"], row.json()


def test_the_holder_sets_the_instructions_once_and_only_with_the_key(live):
    before = live.get("/api/payer/instructions").json()
    assert before["set"] is False and before["rules"] is None and before["defaults"] == RULES
    assert "Every change" in before["in_words"][0]
    assert live.put("/api/payer/instructions", json=RULES, headers={"X-Payer-Key": "wrong"}).status_code == 401
    bad = live.put("/api/payer/instructions", json={**RULES, "tolerance_percent": "40"})
    assert bad.status_code == 422 and "between 0 and 5 percent" in bad.json()["detail"]
    after = set_rules(live)
    assert after["set"] is True and after["rules"] == RULES and after["set_at"]
    assert live.get("/api/payer/instructions").json()["rules"] == RULES
    assert live.get("/api/payer/queue").json()["instructions"]["rules"] == RULES


def test_an_approval_carries_the_instructions_that_stood_when_it_was_given(live):
    set_rules(live)
    claim_id, row = approved(live)
    bound = row["approval"]
    assert bound["instructions"]["rules"] == RULES and bound["deadline_at"] and bound["fee_rule"]["bearer"] == "claim"
    set_rules(live, tolerance_percent="2", deadline_days=3)        # the holder changes its mind for later claims
    again = next(r for r in live.get("/api/payer/queue").json()["claims"] if r["id"] == claim_id)
    assert again["state"] == "APPROVED" and again["approval"] == bound       # this approval is as it was given
    plan = live.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()
    assert plan["instructions"]["rules"] == RULES and plan["plan"]["tolerance_percent"] == "0.5"
    assert plan["plan"]["deadline_at"] == bound["deadline_at"]
    assert [d["kind"] for d in plan["agent_report"]] == ["fee_rule", "route_chosen"]


def test_without_instructions_an_approval_binds_none_and_every_change_is_put_to_a_person(live):
    claim_id, row = approved(live)
    assert row["approval"]["instructions"] is None and row["approval"]["deadline_at"] is None
    view = start(live, claim_id, "transfer_fails")
    assert view["hold"]["needs"] == ["bank_details", "payer", "claimant"] and view["agent_report"] == [
        r for r in view["agent_report"] if r["kind"] == "route_changed"]


def test_a_claim_below_the_small_claim_line_is_topped_up_by_the_holder_and_arrives_whole(live):
    set_rules(live, small_claim_usd="2000")
    claim_id, row = approved(live)
    fees = row["approval"]["fee_rule"]
    # (1,840.55 + 5.00) / (1 - 0.003) = 1,851.11: 5.55 incoming fee, 5.00 payout fee, 1,840.56 left to convert.
    assert fees["bearer"] == "holder" and fees["holder_sends"] == "1851.11" and row["approval"]["amount"] == "1840.55"
    done = start(live, claim_id)
    assert done["state"] == "PAID" and done["deposit"]["amount"] == "1851.11" and done["claim_usd"] == "1840.55"
    assert done["incoming_fee"]["amount"] == "5.55"
    assert Decimal(done["received"]["amount"]) >= Decimal("1840.55") * 58     # nothing of the claim went on fees
    assert done["reconciliation"]["balanced"]
    assert done["agreed_and_paid"]["difference"]["amount"] == "0.00"


def test_a_refused_transfer_goes_through_with_a_new_account_and_the_holders_approval_and_no_second_agreement(live):
    set_rules(live)
    claim_id, _ = approved(live)
    view = start(live, claim_id, "transfer_fails")
    assert view["state"] == "FAILED" and view["hold"]["needs"] == ["bank_details", "payer"]
    assert "not asked to agree again" in view["hold"]["explanation"]
    kinds = [d["kind"] for d in view["agent_report"]]
    assert kinds == ["fee_rule", "route_chosen", "kept_lock", "route_changed", "replacement_within_tolerance"]
    give_bank(live, claim_id, {**PH_BANK, "account_number": "9876543210"})
    assert len(live.world.fake.transfers) == 1                       # a new account is never inside the instructions
    row = live.post(f"/api/payer/claims/{claim_id}/approve").json()
    assert row["state"] == "PAYING" and row["approval"]["replaces_earlier_approval"] is True
    live.world.app.state.payouts.join(claim_id)
    done = live.get(f"/api/claims/{claim_id}/payout").json()
    assert done["state"] == "PAID" and done["claim_state"] == "PAID" and done["reconciliation"]["balanced"]
    transfers = list(live.world.fake.transfers.values())
    assert len(transfers) == 2 and [t["status"] for t in transfers].count("PAID") == 1
    assert done["agent_report"][-1]["kind"] == "replacement_cleared"
    assert done["agreed_and_paid"]["difference"]["amount"] == "-290.00"       # the payout fee, charged a second time
    assert "refused" in done["agreed_and_paid"]["note"] and "payout fee a second time" in done["agreed_and_paid"]["note"]
    assert done["confirmed"]["by"] == "standing instructions"


def test_a_plan_left_until_after_the_deadline_cannot_be_started_and_goes_back_to_the_holder(live):
    set_rules(live, deadline_days=1)
    claim_id, _ = approved(live)
    plan = live.post(f"/api/claims/{claim_id}/payout/plan", json={}).json()
    path = live.world.app.state.claims.payout_path(claim_id)
    payout = Payout.load(path)
    payout.deadline_at = "2020-01-01T00:00:00+00:00"
    payout.save()
    late = live.post(f"/api/claims/{claim_id}/payout/confirm", json={"plan_id": plan["plan"]["id"]})
    assert late.status_code == 409 and "deadline" in late.json()["detail"]
    claim = live.get(f"/api/claims/{claim_id}").json()
    assert claim["approval"] is None and "deadline" in claim["approvals_withdrawn"][0]["because"]
    assert not live.world.fake.deposits


def test_a_plan_worked_out_again_keeps_the_route_the_money_is_on_and_says_so(tmp_path, fake):
    fake.mid_rates = {"MXN": 18.7}
    payout, client, sim = planned(tmp_path, fake, "MXN", "2316.40", what_if="rate_lock_expires")
    assert payout.plan["route"] == awx.PAY_WITH_QUOTE
    clock = lambda: fake.now
    advance(payout, client, sim, clock)
    fake.now += 61
    fake.rates["MXN"] = 18.0                                     # 2.7 percent worse: the claimant is asked
    advance(payout, client, sim, clock)
    assert payout.state == awx.HELD
    runner = payouts.PayoutRunner(None, lambda: (client, sim))
    runner.prepare_hold(payout, client, True)
    again = payout.hold["plan"]
    assert again["route"] == awx.PAY_WITH_QUOTE and again["routes_compared"] is None
    assert "already on its way" in again["route_reason"] and "converted first" not in again["route_reason"]
