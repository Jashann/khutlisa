"""The yearly date on which a holder hands unclaimed property to the State, and what the agent does about it.

California's law fixes the schedule (docs/CALIFORNIA_CLAIMS.md, section H3): the Notice Report is filed before
1 November, and the Remit Report and the property follow "no sooner than seven months and no later than seven
months and 15 days after" it (Code of Civil Procedure 1532(a)), in practice between 1 and 15 June, or between
1 and 15 December for life insurance companies. The exact day is in the holder's own Remit Reminder Letter, so
the date is a setting the holder keeps, and it starts at the next 1 June.

The choice is arithmetic on that date. No language model is involved.

  proof ready                                  pay the owner now, before the handover
  proof not ready, time in hand                ask the owner for the missing document
  proof not ready, handover too close          do not wait: the property goes to the State with the Remit Report,
                                               and the owner claims it there
"""
from __future__ import annotations

from datetime import date, datetime, timezone

SCHEDULE = {
    "notice": "The Notice Report is due before 1 November. No money is sent with it.",
    "remit": "The Remit Report and the property are due between 1 and 15 June (1 and 15 December for life "
             "insurance companies).",
    "source": "Code of Civil Procedure 1530(d) and 1532(a); State Controller, how to report",
    "url": "https://www.sco.ca.gov/upd_how_to_report.html",
}
DEFAULT_DOCUMENT_DAYS = 30


def today() -> date:
    return datetime.now(timezone.utc).date()


def default_date(on: date | None = None) -> str:
    """The next 1 June, the first day of the Remit Report window."""
    on = on or today()
    june = date(on.year, 6, 1)
    return (june if on <= june else date(on.year + 1, 6, 1)).isoformat()


def clean(raw: dict | None, on: date | None = None) -> dict:
    """{"handover_date", "document_days"} in stored form. Raises ValueError, in words for the screen."""
    raw = raw or {}
    on = on or today()
    text = str(raw.get("handover_date") or "").strip() or default_date(on)
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise ValueError("The handover date must be a date, written as 2027-06-01") from None
    if not -366 <= (day - on).days <= 800:
        raise ValueError("The handover date must be within about two years of today")
    try:
        days = int(raw.get("document_days") if raw.get("document_days") not in (None, "") else DEFAULT_DOCUMENT_DAYS)
    except (TypeError, ValueError):
        raise ValueError("The days an owner needs to send a document must be a whole number") from None
    if not 1 <= days <= 180:
        raise ValueError("The days an owner needs to send a document must be between 1 and 180")
    return {"handover_date": day.isoformat(), "document_days": days}


def days_left(setting: dict, on: date | None = None) -> int:
    return (date.fromisoformat(setting["handover_date"]) - (on or today())).days


def in_words(day: str) -> str:
    """'1 June 2027' from '2027-06-01'."""
    d = date.fromisoformat(day)
    return f"{d.day} {d:%B %Y}"


def choose(proof_ready: bool, left: int, document_days: int) -> str:
    """"pay", "ask" or "release". The whole decision."""
    if proof_ready:
        return "pay"
    return "ask" if left > document_days else "release"


def card(setting: dict, *, proof_ready: bool, missing: list[str], amount: str, on: date | None = None) -> dict:
    """The deadline choice for one claim, as a decision card of four short lines with the reasons behind it."""
    left = days_left(setting, on)
    need = int(setting["document_days"])
    what = choose(proof_ready, left, need)
    when = in_words(setting["handover_date"])
    first = (missing[0] if missing else "a document").rstrip(".")
    happened = (f"{left} days until the handover to the State on {when}." if left >= 0 else
                f"The handover date, {when}, has passed.")
    allowed = f"An owner needs about {need} days to send a document."
    if what == "pay":
        did, money, tone = "The proof is ready, so it can be paid now.", f"{amount} goes to the owner, not to the State.", "go"
        allowed = "Pay the owner directly once the proof is ready."
    elif what == "ask":
        more = f" and {len(missing) - 1} more" if len(missing) > 1 else ""
        did, tone = f"Time in hand: it asked the owner for {first[0].lower() + first[1:]}{more}.", "ask"
        money = f"{amount} waits for that document."
    else:
        did, tone = "Too close to wait: this property is released to the State process.", "stop"
        money = f"{amount} goes on the Remit Report. The owner claims it from the State."
    why = [
        f"The date is set by the holder: {when}. California's schedule puts the Remit Report and the property "
        "between 1 and 15 June, or 1 and 15 December for life insurance companies (Code of Civil Procedure "
        "1532(a)); the exact day is in the holder's Remit Reminder Letter.",
        f"The rule, in code: proof ready, pay; proof not ready and more than {need} days left, ask the owner for "
        f"what is missing; proof not ready and {need} days or fewer left, pay what is proven and release the "
        "rest to the State with the Remit Report.",
    ]
    if missing and what != "pay":
        why.append("Still missing: " + "; ".join(m.rstrip(".") for m in missing[:4]) + ".")
    return {"kind": "deadline", "choice": what, "tone": tone, "days_left": left, "date": setting["handover_date"],
            "date_words": when, "document_days": need, "title": "The handover date",
            "happened": happened, "allowed": allowed, "did": did, "money": money, "why": why}
