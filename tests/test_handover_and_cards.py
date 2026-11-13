"""The handover date and the deadline choice (handover.py), and the decision cards (cards.py). Arithmetic and
fixed sentences only: no model, no network."""
from datetime import date

import pytest

from khutlisa import cards, handover
from khutlisa import instructions as ins

RULES = ins.clean({"tolerance_percent": "0.5", "small_claim_usd": "250", "route_rule": "most_to_claimant",
                   "deadline_days": 14})
ON = date(2026, 11, 13)


def test_the_handover_date_starts_at_the_next_first_of_june_and_is_checked():
    assert handover.default_date(ON) == "2027-06-01" and handover.default_date(date(2027, 6, 1)) == "2027-06-01"
    assert handover.default_date(date(2027, 6, 2)) == "2028-06-01"
    setting = handover.clean({}, ON)
    assert setting == {"handover_date": "2027-06-01", "document_days": 30} and handover.days_left(setting, ON) == 200
    assert handover.clean({"handover_date": "2026-12-01", "document_days": "21"}, ON)["document_days"] == 21
    for bad in ({"handover_date": "soon"}, {"handover_date": "2031-01-01"}, {"document_days": 0}, {"document_days": "x"}):
        with pytest.raises(ValueError):
            handover.clean(bad, ON)


def test_the_choice_depends_on_the_days_left_and_on_nothing_else():
    assert handover.choose(True, 3, 30) == "pay" and handover.choose(True, 300, 30) == "pay"
    assert handover.choose(False, 31, 30) == "ask"          # time in hand: ask the owner for what is missing
    assert handover.choose(False, 30, 30) == "release"      # too close: release it to the State process
    assert handover.choose(False, -2, 30) == "release"


def test_the_deadline_card_says_which_it_chose_and_why_in_four_short_lines():
    far = handover.card(handover.clean({}, ON), proof_ready=False, missing=["photo identification", "tax number"],
                        amount="$1,840.55", on=ON)
    assert far["choice"] == "ask" and far["days_left"] == 200 and "200 days" in far["happened"]
    assert "asked the owner for photo identification and 1 more" in far["did"] and "$1,840.55" in far["money"]
    near = handover.card(handover.clean({"handover_date": "2026-12-01"}, ON), proof_ready=False,
                         missing=["photo identification"], amount="$1,840.55", on=ON)
    assert near["choice"] == "release" and near["tone"] == "stop" and "released to the State process" in near["did"]
    assert "Remit Report" in near["money"] and any("1532(a)" in line for line in near["why"])
    ready = handover.card(handover.clean({"handover_date": "2026-12-01"}, ON), proof_ready=True, missing=[],
                          amount="$120.00", on=ON)
    assert ready["choice"] == "pay" and "paid now" in ready["did"]
    for made in (far, near, ready):
        assert all(made[k] and len(made[k]) <= 110 for k in ("happened", "allowed", "did", "money"))


def test_the_fee_card_follows_the_fee_rule_on_both_sides_of_the_line():
    small = cards.fee_card(ins.fee_plan("120.00", RULES))
    assert "4.5%" in small["happened"] and "$125.38" in small["did"] and "whole $120.00" in small["money"]
    large = cards.fee_card(ins.fee_plan("2316.40", RULES))
    assert "$2,316.40" in large["did"] and "$2,304.45" in large["money"] and "From $250.00 up" in large["allowed"]
    assert cards.fee_card(ins.fee_plan("120.00", None)) is None and large["why"] == ins.fee_plan("2316.40", RULES)["arithmetic"]


def test_the_route_card_gives_the_difference_in_money_or_says_one_route_is_open():
    two = {"route_reason": "why", "routes_compared": [
        {"route": "convert_then_pay", "available": True, "chosen": False, "would_receive": {"amount": "42344.88", "currency": "MXN"}},
        {"route": "pay_with_quote", "available": True, "chosen": True, "would_receive": {"amount": "42345.99", "currency": "MXN"}}]}
    card = cards.route_card(two)
    assert "Two routes to MXN" in card["happened"] and "pay with a locked quote" in card["did"]
    # 1.11 MXN on 42,345.99 MXN is not worth a figure: the difference is named only when it is material
    assert "1.11 MXN more" not in card["money"] and "about the same" in card["money"] and "42,345.99 MXN" in card["money"]
    two["routes_compared"][0]["would_receive"]["amount"] = "42200.00"
    assert "145.99 MXN more than the other route" in cards.route_card(two)["money"]
    one = {"route_reason": "why", "routes_compared": [
        {"route": "convert_then_pay", "available": False, "chosen": False, "would_receive": None},
        {"route": "pay_with_quote", "available": True, "chosen": True, "would_receive": {"amount": "7554.31", "currency": "PHP"}}]}
    assert "One route is open for PHP" in cards.route_card(one)["happened"] and cards.route_card({}) is None


def _attempt(short: str, asked: bool) -> dict:
    return {"account_last4": "7771", "fate": "refused by the bank before it was paid", "reason": "INCORRECT_ROUTING",
            "came_back": {"amount": "42363.13", "currency": "MXN"}, "fee_kept": {"amount": "5.00", "currency": "USD"},
            "outcome": {"agreed_local": "42345.99", "replacement_local": "42270.14", "shortfall_percent": short,
                        "tolerance_percent": "0.5", "claimant_asked": asked}}


def test_the_same_refusal_carries_on_inside_the_limit_and_stops_and_asks_outside_it():
    payout = {"instructions": RULES, "state": "FAILED", "target_currency": "MXN", "hold": {"needs": ["bank_details", "payer"]}}
    inside = cards.refusal_card(_attempt("0.18", False), payout)
    assert inside["tone"] == "go" and inside["asked"] is False
    # what was skipped is one confirmation of the amount; the account was still asked for and the holder approves it
    assert "did not ask the owner to confirm the amount" in inside["did"] and "carried on without asking" not in inside["did"]
    assert "Still asked: the corrected account and the holder's approval" in inside["did"] and len(inside["did"]) <= 140
    assert "confirm the amount" in inside["allowed"]
    assert "account ending 7771" in inside["happened"] and "42,270.14 MXN in place of 42,345.99 MXN" in inside["money"]
    outside = cards.refusal_card(_attempt("5.29", True), {**payout, "hold": {"needs": ["claimant"]}})
    assert outside["tone"] == "stop" and outside["asked"] is True and "stopped and asked" in outside["did"]
    assert "waiting for the owner's answer" in outside["money"] and inside["allowed"] == outside["allowed"]
    paid = cards.refusal_card(_attempt("0.18", False), {**payout, "state": "PAID", "target_amount": "42270.12", "hold": None})
    assert "Paid 42,270.12 MXN" in paid["money"]
    undecided = cards.refusal_card({k: v for k, v in _attempt("0", False).items() if k != "outcome"}, payout)
    assert undecided["asked"] is None and undecided["tone"] == "ask"


def test_the_cards_of_a_payout_come_in_the_order_things_happened():
    plan = {"fee_rule": ins.fee_plan("2316.40", RULES), "route_reason": "why", "routes_compared": [
        {"route": "pay_with_quote", "available": True, "chosen": True, "would_receive": {"amount": "42345.99", "currency": "MXN"}},
        {"route": "convert_then_pay", "available": True, "chosen": False, "would_receive": {"amount": "42344.88", "currency": "MXN"}}]}
    payout = {"plan": plan, "instructions": RULES, "state": "FAILED", "hold": {"needs": ["bank_details", "payer"]},
              "attempts": [_attempt("0.18", False)], "decisions": []}
    assert [c["kind"] for c in cards.payout_cards(payout)] == ["fee_rule", "route_chosen", "refusal"]
    assert cards.payout_cards(None) == []
