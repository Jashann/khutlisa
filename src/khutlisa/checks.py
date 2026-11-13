"""Checks that code makes on every document, beside what the model read.

The model reports what is printed. These functions decide what it means:

1. dates: the issue and expiry dates are real calendar dates, in order, the issue date is not in the future, and
   identification has not expired today;
2. name_two_places: on a passport-type document the name in the name field and the name in the machine-readable
   lines agree, and the check digits in those lines are right (mrz.py). A document with no such lines, a
   driving licence say, cannot have this check, and the result says so;
3. issuer: identification was issued by a government authority, of the country the claimant gave or of the
   United States, where the property was reported;
4. two_readings: two separate readings of the document agree on the name and the dates.

A check ends as "passed", "failed", "held", "not_applicable" or "not_checked". A failed check is a concern: the
document settles nothing. "held" means held for a person to look at: code could not settle the point either way
(another country's passport, two readings that differ), so the document settles nothing by itself and the proof
is not ready until a person has looked. "not_checked" is only for a reading stored before these checks existed.

None of this shows that a document is genuine. Nobody here asks the issuing authority.
"""
from __future__ import annotations

import re
from datetime import date

from . import documents as docs
from .countries import ALPHA3, COUNTRIES
from .names import normalise, tokens

PASSED, FAILED, HELD, NOT_APPLICABLE, NOT_CHECKED = "passed", "failed", "held", "not_applicable", "not_checked"
HELD_WORDS = "held for a person to look at"
REMAINING_RISK = "Khutlisa read these documents; it has not verified them with the issuing authority."
DECIDED_BY = "The holder, not Khutlisa, approves."
TITLES = {"dates": "Dates", "name_two_places": "Name in two places", "issuer": "Issuer", "two_readings": "Two readings"}
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _check(key: str, status: str, text: str, blocks: bool | None = None) -> dict:
    """`blocks` says whether a failed check is reported among the document's faults. An expiry is not: proof.py
    already words it for the photo identification requirement."""
    return {"key": key, "title": TITLES[key], "status": status, "text": text,
            "blocks": status == FAILED if blocks is None else blocks}


def _twice(reading: dict) -> bool:
    """False for a reading stored before documents were read twice: it has one reading and none of the fields
    the newer checks need, so what it lacks is reported as not checked instead of being held against it."""
    return "readings" in reading


# ---- 1. dates ------------------------------------------------------------------------------------------------

def _calendar(value: str) -> tuple[date | None, bool]:
    """(the date, whether it is written as a full date). '2023-02-30' is written as one and is not a date."""
    m = _ISO.fullmatch((value or "").strip())
    if not m:
        return None, False
    try:
        return date(int(m[1]), int(m[2]), int(m[3])), True
    except ValueError:
        return None, True


def check_dates(reading: dict, kind: str, today: date) -> dict:
    is_id = kind == "id"
    raw = {f: docs.date_field(reading, f) for f in ("issue_date", "expiry_date", "date_of_birth")}
    words = {"issue_date": "issue date", "expiry_date": "expiry date", "date_of_birth": "date of birth"}
    parsed, wrong = {}, []
    for field, value in raw.items():
        parsed[field], written = _calendar(value)
        if written and parsed[field] is None:
            wrong.append(f"The {words[field]} on it, {value}, is not a real calendar date.")
    issued, expires, born = parsed["issue_date"], parsed["expiry_date"], parsed["date_of_birth"]
    if issued and issued > today:
        wrong.append(f"The issue date on it, {raw['issue_date']}, is in the future.")
    if issued and expires and issued >= expires:
        wrong.append(f"It says it was issued on {raw['issue_date']} and expires on {raw['expiry_date']}, which "
                     "cannot both be right.")
    if born and issued and born >= issued:
        wrong.append(f"It says it was issued on {raw['issue_date']}, which is not after the date of birth on it.")
    if wrong:
        return _check("dates", FAILED, " ".join(wrong))
    if is_id and expires and expires < today:
        return _check("dates", FAILED, f"It expired on {raw['expiry_date']}.", blocks=False)
    if is_id:
        missing = [words[f] for f in ("issue_date", "expiry_date") if parsed[f] is None]
        if missing and not _twice(reading):
            return _check("dates", NOT_CHECKED, f"No {' or '.join(missing)} was kept when it was read, so its "
                                                "dates were not checked in full.")
        if missing:
            return _check("dates", HELD, f"No {' or '.join(missing)} could be read on it, so its dates could not "
                                         "be checked.")
        return _check("dates", PASSED, f"Issued {raw['issue_date']}, expires {raw['expiry_date']}. The dates are "
                                       "in order and it is current today.")
    if issued and expires:
        return _check("dates", PASSED, f"Issued {raw['issue_date']}, expires {raw['expiry_date']}. The dates are "
                                       "in order.")
    if issued:
        return _check("dates", PASSED, f"Dated {raw['issue_date']}, a real date that is not in the future.")
    return _check("dates", NOT_APPLICABLE, "No issue or expiry date was read on it, so there was none to check.")


# ---- 2. the name in two places -------------------------------------------------------------------------------

def names_agree(printed: str, zone: dict) -> bool:
    """Does the name field say the same as the machine-readable lines? Accents, case, order and hyphens are set
    aside (the lines can only hold A to Z). When the name was cut short to fit the line, each word in the lines
    must begin a word in the name field."""
    have = tokens(printed)
    want = tokens(f"{zone.get('given_names') or ''} {zone.get('surname') or ''}")
    if not have or not want:
        return False
    if zone.get("name_cut_short"):
        return all(any(h.startswith(w) for h in have) for w in want)
    return sorted(have) == sorted(want) or "".join(sorted(have)) == "".join(sorted(want))


def check_name_two_places(reading: dict, today: date) -> dict:
    key = "name_two_places"
    zone = reading.get("mrz")
    is_passport = "passport" in (reading.get("document_type") or "").lower()
    if not zone:
        if not _twice(reading) and is_passport:
            return _check(key, NOT_CHECKED, "It was read before the machine-readable lines were checked, so its "
                                            "name was checked in one place only.")
        if is_passport:
            return _check(key, HELD, "It is a passport, but no machine-readable lines were read on it, so the "
                                     "name could be checked in one place only.")
        return _check(key, NOT_APPLICABLE, "This kind of document has no machine-readable lines, so this check "
                                           "does not apply and the name is checked in one place only.")
    if not zone.get("parsed"):
        return _check(key, HELD, "The machine-readable lines could not be read well enough to check the name "
                                 "against them.")
    in_lines = " ".join(x for x in (zone.get("given_names"), zone.get("surname")) if x)
    printed = [reading["holder_name"]] if reading.get("holder_name") else list(reading.get("names") or [])
    if not printed:
        return _check(key, HELD, "No name field could be read on it to compare with the machine-readable lines.")
    wrong = []
    if not any(names_agree(p, zone) for p in printed):
        wrong.append(f"The name field says {printed[0]} and the machine-readable lines say {in_lines}. They do "
                     "not agree.")
    digits = zone.get("check_digits") or {}
    labels = {"birth_date": "date of birth", "expiry_date": "expiry date", "document_number": "document number",
              "composite": "whole line"}
    wrong += [f"The check digit on the {labels[k]} in the machine-readable lines is wrong." for k in labels
              if digits.get(k) is False]
    for field, label in (("expiry_date", "expiry date"), ("date_of_birth", "date of birth")):
        on_page, in_zone = docs.date_field(reading, field), zone.get("birth_date" if field == "date_of_birth" else field)
        if _calendar(on_page)[0] and in_zone and on_page != in_zone:
            wrong.append(f"The {label} printed on it, {on_page}, is not the one in the machine-readable lines, {in_zone}.")
    if wrong:
        return _check(key, FAILED, " ".join(wrong))
    return _check(key, PASSED, f"The name field, {printed[0]}, and the machine-readable lines, {in_lines}, agree. "
                               "The check digits on the date of birth and the expiry date are correct.")


# ---- 3. the issuer -------------------------------------------------------------------------------------------

# Words that mark an employer, a school, a bank or a club. One of them settles it, whatever else the name says.
_NOT_GOVERNMENT = {
    "HOSPITAL", "HOSPITALS", "CLINIC", "COMPANY", "CO", "INC", "CORP", "CORPORATION", "LLC", "LTD", "LIMITED",
    "UNIVERSITY", "UNIVERSIDAD", "COLLEGE", "SCHOOL", "ACADEMY", "BANK", "BANCO", "CLUB", "GYM", "ASSOCIATION",
    "UNION", "EMPLOYER", "STAFF", "EMPLOYEE", "FOUNDATION", "CHURCH", "STORE", "SHOP", "HOTEL", "AIRLINE",
    "AIRLINES", "PACKING", "EMPACADORA", "MEMBERSHIP", "SOCIETY", "LIBRARY", "INSURANCE",
}
# Words and phrases a government authority that issues identification is named with.
_GOVERNMENT = (
    "GOVERNMENT", "GOBIERNO", "REPUBLIC", "REPUBLICA", "REPUBLIKA", "REPUBLIQUE", "KINGDOM", "COMMONWEALTH",
    "FEDERAL", "FEDERATION", "MINISTRY", "MINISTERIO", "SECRETARIA", "DEPARTMENT OF STATE", "FOREIGN AFFAIRS",
    "RELACIONES EXTERIORES", "MOTOR VEHICLES", "PASSPORT OFFICE", "PASSPORT AUTHORITY", "PASSPORT AGENCY",
    "IMMIGRATION", "HOME OFFICE", "HOME AFFAIRS", "INTERIOR", "CIVIL REGISTRY", "REGISTRO CIVIL", "STATE OF",
    "PROVINCE OF", "NATIONAL POLICE", "LAND TRANSPORTATION OFFICE", "INSTITUTO NACIONAL ELECTORAL",
    "DRIVER LICENSING", "DRIVER SERVICES", "PUBLIC SAFETY", "MUNICIPALITY", "CITY OF", "COUNTY OF",
    "UNITED STATES", "DFA", "SRE", "DMV", "LTO", "INE", "DVLA", "USCIS",
)
_COUNTRY_NAMES = sorted(((normalise(c["name"]), code) for code, c in COUNTRIES.items()), key=lambda x: -len(x[0]))
_OTHER_NAMES = {
    "USA": "US", "UNITED STATES OF AMERICA": "US", "ESTADOS UNIDOS MEXICANOS": "MX", "UNITED MEXICAN STATES": "MX",
    "PILIPINAS": "PH", "UK": "GB", "GREAT BRITAIN": "GB", "UNITED KINGDOM": "GB", "DEUTSCHLAND": "DE",
    "ESPANA": "ES", "BRASIL": "BR", "RUSSIAN FEDERATION": "RU", "KOREA": "KR", "VIET NAM": "VN",
}
_US_STATES = (
    "ALABAMA", "ALASKA", "ARIZONA", "ARKANSAS", "CALIFORNIA", "COLORADO", "CONNECTICUT", "DELAWARE", "FLORIDA",
    "HAWAII", "IDAHO", "ILLINOIS", "INDIANA", "IOWA", "KANSAS", "KENTUCKY", "LOUISIANA", "MAINE", "MARYLAND",
    "MASSACHUSETTS", "MICHIGAN", "MINNESOTA", "MISSISSIPPI", "MISSOURI", "MONTANA", "NEBRASKA", "NEVADA",
    "NEW HAMPSHIRE", "NEW JERSEY", "NEW MEXICO", "NEW YORK", "NORTH CAROLINA", "NORTH DAKOTA", "OHIO", "OKLAHOMA",
    "OREGON", "PENNSYLVANIA", "RHODE ISLAND", "SOUTH CAROLINA", "SOUTH DAKOTA", "TENNESSEE", "TEXAS", "UTAH",
    "VERMONT", "VIRGINIA", "WASHINGTON", "WEST VIRGINIA", "WISCONSIN", "WYOMING", "DISTRICT OF COLUMBIA",
)


def _has(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def country_code(printed: str, states: bool = False) -> str | None:
    """The country a printed name or code means, as an ISO two-letter code, or None when it is not a country in
    our table. `states` also reads the name of a state of the United States as the United States."""
    text = normalise(printed)
    if not text:
        return None
    if text in _OTHER_NAMES:
        return _OTHER_NAMES[text]
    if len(text) == 3 and text in ALPHA3:
        return ALPHA3[text]
    if len(text) == 2:
        return text if text in COUNTRIES else None
    for name, code in list(_OTHER_NAMES.items()) + _COUNTRY_NAMES:
        if len(name) > 3 and _has(text, name):
            # "New Mexico" is a state of the United States, not Mexico
            if states and any(_has(text, s) and name in s and name != s for s in _US_STATES):
                continue
            return code
    if states and any(_has(text, s) for s in _US_STATES):
        return "US"
    return None


def is_government(authority: str) -> bool | None:
    """True for a government authority, False for an employer, school, bank or club, None when the name does not
    say. Decided from the words of the name alone."""
    text = normalise(authority)
    if not text:
        return None
    if any(word in _NOT_GOVERNMENT for word in text.split()):
        return False
    if any(_has(text, phrase) for phrase in _GOVERNMENT) or text in _OTHER_NAMES \
            or any(text == name for name, _ in _COUNTRY_NAMES):      # or the bare name of a country
        return True
    return None


def _country_name(code: str) -> str:
    name = COUNTRIES.get(code, {}).get("name") or code
    return f"the {name}" if name in ("United States", "Philippines", "Netherlands", "United Kingdom",
                                     "United Arab Emirates", "Bahamas", "Dominican Republic") else name


def check_issuer(reading: dict, claim: dict) -> dict:
    key = "issuer"
    authority = reading.get("issuing_authority") or reading.get("issuer") or ""
    government = is_government(authority)
    if government is False:
        return _check(key, FAILED, f"It was issued by {authority}, which is not a government authority.")
    if not authority:
        if not _twice(reading):
            return _check(key, NOT_CHECKED, "No issuing authority was kept when it was read.")
        return _check(key, HELD, "No issuing authority could be read on it.")
    if government is None:
        return _check(key, HELD, f"Khutlisa could not tell from its name whether {authority} is a government "
                                 "authority.")
    printed = reading.get("issuing_country") or ""
    code = country_code(printed) if printed else country_code(authority, states=True)
    zone = reading.get("mrz") or {}
    in_zone = country_code(zone.get("issuing_state") or "") if zone.get("parsed") else None
    if code and in_zone and code != in_zone:
        return _check(key, FAILED, f"It names {_country_name(code)} as the issuing country, and its "
                                   f"machine-readable lines name {_country_name(in_zone)}.")
    code = code or in_zone
    stated = (claim.get("claimant") or {}).get("country") or ""
    if code is None:
        if not printed and not _twice(reading):
            return _check(key, NOT_CHECKED, f"It was issued by {authority}, a government authority. No issuing "
                                            "country was kept when it was read.")
        return _check(key, HELD, f"The issuing country on it, {printed}, is not a country Khutlisa knows." if printed
                      else f"It was issued by {authority}, and no issuing country could be read on it.")
    if code == stated.upper():
        return _check(key, PASSED, f"Issued by {authority}, a government authority of {_country_name(code)}, the "
                                   "country the claimant gave.")
    if code == "US":
        return _check(key, PASSED, f"Issued by {authority}, a government authority of the United States, where "
                                   "the property was reported.")
    return _check(key, HELD, f"It was issued by {authority}, a government authority of {_country_name(code)}, and "
                             f"the claimant gave {_country_name(stated.upper()) if stated else 'no country'} as "
                             "their country. That does not refuse it, but a person has to look at why.")


# ---- 4. two readings -----------------------------------------------------------------------------------------

def check_two_readings(reading: dict) -> dict:
    key = "two_readings"
    agreement = reading.get("agreement") or {}
    if not _twice(reading):
        return _check(key, NOT_CHECKED, "It was read once, before every document was read twice, so there is no "
                                        "second reading to compare.")
    if agreement.get("status") == "agree":
        return _check(key, PASSED, "Two separate readings agree on the name and the dates.")
    if agreement.get("status") == "disagree":
        what = agreement.get("disagreed") or ["name or the dates"]
        listed = what[0] if len(what) == 1 else ", ".join(what[:-1]) + " and the " + what[-1]
        return _check(key, HELD, f"Two separate readings disagree on the {listed}.")
    return _check(key, HELD, "Only one of the two readings could be made, so there was nothing to compare it with.")


def read_how_often(reading: dict) -> str | None:
    """"twice" or "once" for a document that was read, None for one that was not."""
    if reading.get("status") != "read":
        return None
    return "twice" if _twice(reading) else "once"


def document_checks(doc: dict, claim: dict, today: date | None = None) -> list[dict]:
    """Every check that applies to one read document, in a fixed order. [] for a document that was not read."""
    reading = doc.get("reading") or {}
    if reading.get("status") != "read":
        return []
    today = today or date.today()
    kind = doc.get("kind") or "other"
    out = [check_dates(reading, kind, today)]
    if kind == "id":      # the last two questions are asked of identification only
        out += [check_name_two_places(reading, today), check_issuer(reading, claim)]
    return out + [check_two_readings(reading)]
