"""California's dormancy periods and reporting calendar, applied to a holder's own list. All of it is arithmetic.

Sources, read on 13 Nov 2026 (docs/CALIFORNIA_CLAIMS.md, sections H2, H3 and H11):

- The periods by kind of property: the State Controller's dormancy table
  (https://www.sco.ca.gov/Files-UPD/outreach_rptg_hol_dormancy.pdf, rev. 07/2023), and the Code of Civil
  Procedure as the Controller prints it (February 2026): wages one year (1513(a)(7)), most other property three
  years (1520(a)).
- The calendar: property that has been dormant for its period as of 30 June goes on the Notice Report, which
  is due before 1 November of that year (1530(d)). The Remit Report and the property follow between 1 and
  15 June of the next year (1532(a)). The holder keeps the exact day (handover.py).
- The owner's notice: sent 6 to 12 months before the Notice Report is due (1520(b); the Controller's due
  diligence guide says "6-12 months prior to the Notice Report due date"), so between 1 November and 30 April.
- The notice is required for property of 50 US dollars or more (1520(b)).

One simplification is made and said on screen: every holder is treated as reporting "as of June 30". The law
also allows the holder's own fiscal year end (1530(d)), and life insurance companies have other dates.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

_DORM = "https://www.sco.ca.gov/Files-UPD/outreach_rptg_hol_dormancy.pdf"

# class: years, the words for the screen, the section, and whether the period was read at the source.
PERIODS: dict[str, dict] = {
    "wages": {"years": 1, "label": "Wages or salaries", "section": "Code of Civil Procedure 1513(a)(7)",
              "mark": "verified"},
    "bank_account": {"years": 3, "label": "Checking, savings and matured time deposits",
                     "section": "Code of Civil Procedure 1513(a)(1) and (2)", "mark": "verified"},
    "cheque": {"years": 3, "label": "Cashier's cheques and other written instruments",
               "section": "Code of Civil Procedure 1513(a)(4)", "mark": "verified"},
    "money_order": {"years": 7, "label": "Money orders", "section": "Code of Civil Procedure 1513(a)(5)",
                    "mark": "verified"},
    "travelers_cheque": {"years": 15, "label": "Traveler's cheques", "section": "Code of Civil Procedure 1513(a)(3)",
                         "mark": "verified"},
    "ordered_refund": {"years": 1, "label": "Refunds ordered by a court or agency",
                       "section": "Code of Civil Procedure 1519.5", "mark": "verified"},
    "securities": {"years": 3, "label": "Dividends, stocks and bonds", "section": "Code of Civil Procedure 1516",
                   "mark": "verified"},
    "life_insurance": {"years": 3, "label": "Life insurance funds", "section": "Code of Civil Procedure 1515",
                       "mark": "verified"},
    "other": {"years": 3, "label": "Other property", "section": "Code of Civil Procedure 1520(a)",
              "mark": "verified"},
}
SOURCE = {"label": "State Controller, dormancy periods (rev. 07/2023)", "url": _DORM}
NOTICE_MINIMUM_USD = Decimal("50.00")
AS_OF = (6, 30)                 # "as of June 30"
NOTICE_REPORT = (11, 1)         # the Notice Report is due before this day
REMIT_FIRST_DAY = (6, 1)        # the Remit Report window opens on this day of the next year

ASSUMPTION = ("Every balance is counted as of 30 June, the date the law gives when a holder does not use its own "
              "fiscal year end. Life insurance companies report on other dates and are not handled here.")


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:                     # 29 February
        return day.replace(year=day.year + years, day=28)


def cycle(last_activity: date, kind: str) -> dict:
    """The dates that follow from one balance's date of last activity and kind, whatever today is.

    dormant_on      the day the period has run
    report_year     the year of the first 30 June on or after that day; the Notice Report of that year lists it
    notice_report   the day before which that Notice Report is due
    remit_from      the first day of the Remit Report window that follows
    window_opens, window_closes   the 6 to 12 months before the Notice Report in which the owner's notice is due
    """
    period = PERIODS.get(kind) or PERIODS["other"]
    dormant = _add_years(last_activity, period["years"])
    year = dormant.year if dormant <= date(dormant.year, *AS_OF) else dormant.year + 1
    return {"years": period["years"], "dormant_on": dormant, "report_year": year,
            "as_of": date(year, *AS_OF), "notice_report": date(year, *NOTICE_REPORT),
            "remit_from": date(year + 1, *REMIT_FIRST_DAY),
            "window_opens": date(year - 1, *NOTICE_REPORT), "window_closes": date(year, 4, 30)}


def next_notice_report(today: date) -> date:
    due = date(today.year, *NOTICE_REPORT)
    return due if today < due else date(today.year + 1, *NOTICE_REPORT)


def remit_year(today: date) -> int:
    """The year of the Remit Report window that comes next (it closes on 15 June)."""
    return today.year if today <= date(today.year, 6, 15) else today.year + 1


def place(balance: dict, today: date, handover_date: date | None = None) -> dict:
    """Where one balance stands today. `handover_date` is the holder's own date for the handover that comes
    next; it replaces 1 June for the balances that go to the State on that handover.

    status   "late"      the handover it belonged to has passed
             "remit"     it was due on the last Notice Report and goes to the State with the next Remit Report
             "notice"    it is due on the next Notice Report; the owner's notice window is this winter and spring
             "later"     it reaches its dormancy period after that
    """
    c = cycle(date.fromisoformat(balance["last_activity"]), balance["property_class"])
    feeding = remit_year(today) - 1                    # the report year whose property goes with the next remit
    handover = c["remit_from"]
    next_remit = date(feeding + 1, *REMIT_FIRST_DAY)
    if handover_date is not None and (handover_date - next_remit).days <= 30:
        next_remit = handover_date                     # the holder's own day for the handover that comes next
    if c["report_year"] < feeding:
        status, handover = "late", next_remit          # a late balance goes with the next handover there is
    elif today >= c["notice_report"]:
        status, handover = "remit", next_remit
    elif c["notice_report"] == next_notice_report(today):
        status = "notice"
        if c["report_year"] == feeding:
            handover = next_remit
    else:
        status = "later"
    if today < c["window_opens"]:
        window = "not_open"
    elif today <= c["window_closes"]:
        window = "open"
    else:
        window = "closed"
    amount = Decimal(balance["amount"])
    return {"status": status, "dormant_on": c["dormant_on"].isoformat(), "years": c["years"],
            "report_year": c["report_year"], "notice_report": c["notice_report"].isoformat(),
            "handover": handover.isoformat(), "days_to_state": (handover - today).days,
            "window": window, "window_opens": c["window_opens"].isoformat(),
            "window_closes": c["window_closes"].isoformat(),
            "notice_required": amount >= NOTICE_MINIMUM_USD}


def _sum(rows: list[dict]) -> str:
    return f"{sum((Decimal(r['amount']) for r in rows), Decimal(0)):.2f}"


def _group(rows: list[dict]) -> dict:
    return {"balances": len(rows), "amount": _sum(rows)}


STATUS_WORDS = {
    "late": "Overdue from an earlier year, due with the next Remit Report",
    "remit": "Due to the State with the next Remit Report",
    "notice": "Due on the next Notice Report",
    "later": "Reaching their dormancy period later",
}


def picture(balances: list[dict], today: date, handover_date: date | None = None) -> dict:
    """The holder's dormancy picture: every valid balance placed on California's calendar, with the totals the
    screen shows. Each balance in the returned `queue` carries its `place`; the queue is the balances owed to
    owners abroad, soonest handover first and the largest amount first within a date."""
    from .countries import COUNTRIES

    placed = [{**b, "place": place(b, today, handover_date)} for b in balances]
    abroad = [b for b in placed if b["abroad"]]
    by_status = {s: [b for b in placed if b["place"]["status"] == s] for s in STATUS_WORDS}
    countries: dict[str, list[dict]] = {}
    for b in abroad:
        countries.setdefault(b["country"], []).append(b)
    dates: dict[str, list[dict]] = {}
    for b in placed:
        dates.setdefault(b["place"]["handover"], []).append(b)
    kinds: dict[str, list[dict]] = {}
    for b in placed:
        kinds.setdefault(b["property_class"], []).append(b)
    queue = sorted(abroad, key=lambda b: (b["place"]["handover"], -Decimal(b["amount"]), b["row"]))
    soon = [b for b in abroad if b["place"]["status"] in ("late", "remit")]
    coming = next_notice_report(today)
    return {
        "today": today.isoformat(),
        "all": _group(placed), "abroad": _group(abroad),
        "home": _group([b for b in placed if not b["abroad"]]),
        "abroad_due_soon": {**_group(soon), "handover": min((b["place"]["handover"] for b in soon), default=None),
                            "days": min((b["place"]["days_to_state"] for b in soon), default=None)},
        "abroad_under_minimum": _group([b for b in abroad if not b["place"]["notice_required"]]),
        "abroad_window_open": _group([b for b in abroad if b["place"]["status"] == "notice"
                                      and b["place"]["window"] == "open"]),
        "by_status": [{"status": s, "words": STATUS_WORDS[s], **_group(rows),
                       "abroad": _group([b for b in rows if b["abroad"]])} for s, rows in by_status.items()],
        "by_country": sorted(({"code": code, "name": COUNTRIES.get(code, {}).get("name", code), **_group(rows),
                               "due_soon": _group([b for b in rows if b["place"]["status"] in ("late", "remit")])}
                              for code, rows in countries.items()), key=lambda c: -Decimal(c["amount"])),
        "by_due_date": [{"handover": day, "days": (date.fromisoformat(day) - today).days, **_group(rows),
                         "abroad": _group([b for b in rows if b["abroad"]])}
                        for day, rows in sorted(dates.items())],
        "by_kind": sorted(({"kind": k, "label": PERIODS[k]["label"], "years": PERIODS[k]["years"], **_group(rows)}
                           for k, rows in kinds.items()), key=lambda k: -Decimal(k["amount"])),
        "calendar": {"next_notice_report": coming.isoformat(),
                     "notice_window": [date(coming.year - 1, *NOTICE_REPORT).isoformat(),
                                       date(coming.year, 4, 30).isoformat()],
                     "next_handover": min((b["place"]["handover"] for b in placed
                                           if b["place"]["status"] in ("late", "remit")),
                                          default=date(remit_year(today), *REMIT_FIRST_DAY).isoformat()),
                     "assumption": ASSUMPTION},
        "queue": queue,
    }
