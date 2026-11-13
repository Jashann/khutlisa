"""Why a holder pays, from the data: the kinds of money and the kinds of holder, organisations only."""
from __future__ import annotations

from khutlisa import holders
from khutlisa import property_types as pt


def test_lettered_codes_follow_the_controllers_list_and_numeric_ones_are_marked_unverified():
    assert pt.code_of("MS01: WAGES, PAYROLL, SALARIES") == "MS01" and pt.code_of(None) == ""
    assert pt.group_of("MS01: WAGES, PAYROLL, SALARIES") == ("wages", True)
    assert pt.group_of("81: Non Standard NAUPA Code for - Salaries/wages") == ("wages", False)
    assert pt.group_of("CK13: VENDOR CHECKS") == ("vendor", True) and pt.group_of("MS11: REFUNDS DUE") == ("refunds", True)
    assert pt.group_of("AC01: CHECKING ACCOUNTS") == ("bank_accounts", True) and pt.group_of("SC20: CREDIT BALANCES") == ("securities", True)
    assert pt.group_of("IN01: INDIVIDUAL POLICY BENEFIT/CLM") == ("insurance", True) and pt.group_of("CK01: CASHIER'S CHECKS") == ("bank_cheques", True)
    assert pt.group_of("AC55: Formerly AC51-53 accounts") == ("bank_accounts", False)      # not on the published list
    assert pt.group_of("99: something new") == ("other", False) and pt.group_of("") == ("other", False)
    assert pt.SOURCE_URL.startswith("https://www.sco.ca.gov/")
    codes = [c for _, _, lettered, numbers in pt.GROUPS for c in lettered + numbers]
    assert len(codes) == len(set(codes))            # no code sits in two groups


def test_the_breakdown_adds_up_and_says_how_much_rests_on_unverified_codes():
    rows = [("MS01: WAGES, PAYROLL, SALARIES", 3, 900.0), ("81: Non Standard NAUPA Code for - Salaries/wages", 1, 100.0),
            ("AC01: CHECKING ACCOUNTS", 2, 5000.0), ("SD01: SAFE DEPOSIT BOX CONTENTS", 4, 0.0)]
    got = pt.breakdown(rows)
    assert [g["key"] for g in got] == ["bank_accounts", "wages", "tangible"]
    wages = got[1]
    assert wages["properties"] == 4 and wages["amount"] == 1000.0 and wages["unverified_properties"] == 1 and wages["unverified_amount"] == 100.0
    assert [c["code"] for c in wages["codes"]] == ["MS01", "81"] and wages["codes"][1]["verified"] is False
    assert sum(g["properties"] for g in got) == 10 and sum(g["amount"] for g in got) == 6000.0


def test_a_holders_kind_is_told_only_where_its_name_says_so():
    assert holders.kind_of("CATHAY BANK") == "bank" and holders.kind_of("STANFORD FEDERAL CREDIT UNION") == "bank"
    assert holders.kind_of("BANK OF AMERICA NT&SA BRANCH:0260") == "bank" and holders.kind_of("CHARLES SCHWAB & CO INC") == "broker"
    assert holders.kind_of("STATE COMP INSURANCE FUND") == "insurer" and holders.kind_of("CAST & CREW PAYROLL LLC") == "payroll"
    assert holders.kind_of("KIVA USER FUNDS LLC") == "platform" and holders.kind_of("UPWORK GLOBAL INC") == "platform"
    assert holders.kind_of("UNIVERSITY OF SOUTHERN CALIFORNIA") == "education_health"
    assert holders.kind_of("PACIFIC GAS & ELECTRIC CO") == "utility"
    assert holders.kind_of("APPLE INC") == "unclassified" and holders.kind_of("POWER INTEGRATIONS INC") == "unclassified"
    assert holders.kind_of("") == "unclassified"


def test_the_figures_name_organisations_only():
    rows = [("ACME PAYROLL INC", "MS01: WAGES, PAYROLL, SALARIES", 5, 2500.0),
            ("ACME PAYROLL INC", "CK13: VENDOR CHECKS", 1, 80.0),
            ("FIRST EXAMPLE BANK", "AC01: CHECKING ACCOUNTS", 10, 90000.0),
            ("JOHN SMITH DDS", "MS01: WAGES, PAYROLL, SALARIES", 1, 400.0),
            ("NORTHFIELD HARDWARE LLC", "MS11: REFUNDS DUE", 2, 60.0)]
    got = holders.why_holders_pay(rows, may_name=holders.listable)
    kinds = {k["key"]: k for k in got["kinds_of_holder"]}
    assert kinds["bank"]["holders"] == 1 and kinds["bank"]["amount"] == 90000.0 and kinds["bank"]["top"][0]["name"] == "FIRST EXAMPLE BANK"
    assert kinds["payroll"]["properties"] == 6 and got["kinds_of_holder"][-1]["key"] == "unclassified"
    assert kinds["unclassified"]["holders"] == 2 and kinds["unclassified"]["top"] == []      # never listed, never guessed
    wages = got["wages"]              # employers by what they reported: the practice is counted and not named
    assert wages["holders"] == 2 and wages["properties"] == 6 and wages["amount"] == 2900.0
    assert [t["name"] for t in wages["top"]] == ["ACME PAYROLL INC"]
    assert "JOHN SMITH" not in str(got)
    assert sum(g["amount"] for g in got["kinds_of_money"]) == 93040.0 and got["kinds_source"]["url"] == pt.SOURCE_URL


def test_the_buyer_is_stated_with_a_source_for_every_line_and_no_invented_figure():
    buyer = holders.BUYER
    assert "bank transfer" in buyer["who"] or "pay by transfer" in buyer["who"]
    assert len(buyer["why"]) >= 4 and all(w["url"].startswith("https://www.sco.ca.gov/") and w["source"] for w in buyer["why"])
    assert any("two dollars" in w["text"] for w in buyer["why"]) and any("12 percent" in w["text"] for w in buyer["why"])
    assert "no figure" in buyer["not_stated"] and "already been handed over" in buyer["already_with_the_state"]
    assert "none has been asked" not in holders.STATUS and "No holder uses Khutlisa yet" in holders.STATUS
