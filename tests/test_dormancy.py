"""California's dormancy periods and reporting calendar, applied to balances. All arithmetic."""
from datetime import date

import pytest

from khutlisa import dormancy as d

TODAY = date(2026, 11, 13)


def balance(last_activity, kind="wages", amount="100.00", abroad=True, country="MX", row=2):
    return {"row": row, "last_activity": last_activity, "property_class": kind, "amount": amount, "abroad": abroad,
            "country": country if abroad else "US"}


def test_the_periods_are_the_ones_read_on_the_controllers_table():
    years = {kind: period["years"] for kind, period in d.PERIODS.items()}
    assert years == {"wages": 1, "bank_account": 3, "cheque": 3, "money_order": 7, "travelers_cheque": 15,
                     "ordered_refund": 1, "securities": 3, "life_insurance": 3, "other": 3}
    assert all(period["mark"] == "verified" and "Code of Civil Procedure" in period["section"] for period in d.PERIODS.values())
    assert d.NOTICE_MINIMUM_USD == 50 and d.SOURCE["url"].startswith("https://www.sco.ca.gov/")


@pytest.mark.parametrize("last, kind, dormant, year", [
    ("2025-02-14", "wages", "2026-02-14", 2026),       # dormant before 30 June 2026: on the 2026 Notice Report
    ("2025-06-30", "wages", "2026-06-30", 2026),       # on the very day
    ("2025-07-01", "wages", "2026-07-01", 2027),       # a day late for 30 June: the next year's report
    ("2023-02-01", "other", "2026-02-01", 2026),
    ("2024-01-01", "bank_account", "2027-01-01", 2027),
    ("2024-02-29", "wages", "2025-02-28", 2025),       # a leap day
    ("2020-03-01", "money_order", "2027-03-01", 2027),
])
def test_the_cycle_of_one_balance(last, kind, dormant, year):
    c = d.cycle(date.fromisoformat(last), kind)
    assert c["dormant_on"].isoformat() == dormant and c["report_year"] == year
    assert c["notice_report"] == date(year, 11, 1) and c["remit_from"] == date(year + 1, 6, 1)
    # the owner's notice: 6 to 12 months before the Notice Report is due
    assert c["window_opens"] == date(year - 1, 11, 1) and c["window_closes"] == date(year, 4, 30)


def test_where_balances_stand_in_november_after_a_notice_report():
    place = lambda last, kind="wages": d.place(balance(last, kind), TODAY)
    remit = place("2025-02-14")
    assert (remit["status"], remit["handover"], remit["days_to_state"], remit["window"]) == ("remit", "2027-06-01", 200, "closed")
    notice = place("2025-09-01")
    assert (notice["status"], notice["notice_report"], notice["handover"], notice["window"]) == ("notice", "2027-11-01", "2028-06-01", "open")
    assert place("2026-08-01")["status"] == "later" and place("2026-08-01")["window"] == "not_open"
    late = place("2024-03-01")
    assert late["status"] == "late" and late["report_year"] == 2025 and late["handover"] == "2027-06-01"   # goes with the next handover
    assert place("2023-02-01", "other")["status"] == "remit" and place("2024-01-01", "other")["status"] == "notice"


def test_where_balances_stand_in_the_summer_before_the_notice_report():
    summer = date(2026, 8, 1)
    due = d.place(balance("2025-02-14"), summer)
    assert due["status"] == "notice" and due["notice_report"] == "2026-11-01" and due["handover"] == "2027-06-01"
    assert due["window"] == "closed"                      # the window closed on 30 April
    assert d.place(balance("2024-03-01"), summer)["status"] == "late"
    assert d.place(balance("2025-09-01"), summer)["status"] == "later"


def test_in_the_spring_the_remit_and_the_open_window_are_both_ahead():
    spring = date(2027, 3, 1)
    assert d.place(balance("2025-02-14"), spring)["status"] == "remit" and d.place(balance("2025-02-14"), spring)["days_to_state"] == 92
    coming = d.place(balance("2025-09-01"), spring)
    assert coming["status"] == "notice" and coming["window"] == "open"
    assert d.remit_year(date(2027, 6, 15)) == 2027 and d.remit_year(date(2027, 6, 16)) == 2028
    assert d.next_notice_report(date(2026, 10, 31)) == date(2026, 11, 1) and d.next_notice_report(date(2026, 11, 1)) == date(2027, 11, 1)


def test_the_holders_own_handover_date_replaces_the_first_of_june_for_the_next_handover_only():
    own = date(2026, 12, 3)
    assert d.place(balance("2025-02-14"), TODAY, own)["handover"] == "2026-12-03"
    assert d.place(balance("2025-02-14"), TODAY, own)["days_to_state"] == 20
    assert d.place(balance("2024-03-01"), TODAY, own)["handover"] == "2026-12-03"        # a late balance goes with it
    assert d.place(balance("2025-09-01"), TODAY, own)["handover"] == "2028-06-01"        # a later cycle keeps its June
    # A date that belongs to a later year's handover is not applied to this one.
    assert d.place(balance("2025-02-14"), TODAY, date(2028, 6, 1))["handover"] == "2027-06-01"


def test_a_notice_is_required_from_fifty_dollars():
    assert d.place(balance("2025-02-14", amount="50.00"), TODAY)["notice_required"] is True
    assert d.place(balance("2025-02-14", amount="49.99"), TODAY)["notice_required"] is False


def test_the_picture_adds_up_and_the_queue_is_soonest_first_then_largest():
    balances = [balance("2025-02-14", amount="100.00", row=2), balance("2025-03-01", amount="900.00", row=3, country="JP"),
                balance("2025-09-01", amount="5000.00", row=4), balance("2025-02-14", amount="40.00", row=5),
                balance("2025-02-14", amount="70.00", abroad=False, row=6), balance("2026-08-01", amount="10.00", row=7),
                balance("2024-03-01", amount="300.00", row=8, country="JP")]
    p = d.picture(balances, TODAY, date(2027, 6, 1))
    assert p["all"] == {"balances": 7, "amount": "6420.00"} and p["abroad"] == {"balances": 6, "amount": "6350.00"}
    assert p["home"] == {"balances": 1, "amount": "70.00"}
    assert p["abroad_due_soon"] == {"balances": 4, "amount": "1340.00", "handover": "2027-06-01", "days": 200}
    assert p["abroad_under_minimum"] == {"balances": 2, "amount": "50.00"}
    assert p["abroad_window_open"] == {"balances": 1, "amount": "5000.00"}
    assert [b["row"] for b in p["queue"]] == [3, 8, 2, 5, 4, 7]      # the handover date, then the amount
    assert sum(s["balances"] for s in p["by_status"]) == 7
    assert [(c["code"], c["balances"], c["amount"]) for c in p["by_country"]] == [("MX", 4, "5150.00"), ("JP", 2, "1200.00")]
    assert [(g["handover"], g["balances"], g["abroad"]["balances"]) for g in p["by_due_date"]] == [
        ("2027-06-01", 5, 4), ("2028-06-01", 1, 1), ("2029-06-01", 1, 1)]
    assert p["calendar"]["next_notice_report"] == "2027-11-01" and p["calendar"]["notice_window"] == ["2026-11-01", "2027-04-30"]
    assert p["calendar"]["next_handover"] == "2027-06-01" and "30 June" in p["calendar"]["assumption"]
