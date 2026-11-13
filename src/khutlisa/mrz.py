"""The machine-readable zone of a passport or identity card, parsed in code.

The zone is the block of capital letters, digits and the filler character "<" at the foot of the photo page. Its
layout and its check digits are set by the passport standard (ICAO Doc 9303). The reading model only copies the
lines as printed; everything here is arithmetic. The document number and the personal number are used for their
check digits and then dropped: `parse` never returns them, and `masked` hides them in the lines that are kept.

A reader may miscount the run of fillers at the end of a line. The name and the fixed part of the data line (the
first 28 characters of a passport's second line) do not depend on that count, so they are parsed whatever the
length; the digit that covers the whole line is checked only when the line has its full length, and is None
otherwise.
"""
from __future__ import annotations

import re
from datetime import date

_ALLOWED = re.compile(r"[^A-Z0-9<]")
_WEIGHTS = (7, 3, 1)


def _value(c: str) -> int:
    return int(c) if c.isdigit() else 0 if c == "<" else ord(c) - 55


def check_digit(field: str) -> str:
    """The standard's check digit for a field: values weighted 7, 3, 1 in turn, summed, modulo 10."""
    return str(sum(_value(c) * _WEIGHTS[i % 3] for i, c in enumerate(field)) % 10)


def _digit_ok(field: str, digit: str) -> bool:
    return digit.isdigit() and check_digit(field) == digit


def _date(yymmdd: str, today: date, birth: bool) -> str:
    """'740812' as an ISO date, or "" when it is not a calendar date. A birth year cannot be in the future."""
    if not (len(yymmdd) == 6 and yymmdd.isdigit()):
        return ""
    year = 2000 + int(yymmdd[:2])
    if birth and year > today.year:
        year -= 100
    try:
        return date(year, int(yymmdd[2:4]), int(yymmdd[4:6])).isoformat()
    except ValueError:
        return ""


def _names(field: str) -> tuple[str, str, bool]:
    """(surname, given names, cut short) from a name field: surname, two fillers, given names."""
    cut = bool(field) and not field.endswith("<")       # no filler left at the end: the name did not fit
    parts = [p for p in re.split(r"<{2,}", field.strip("<")) if p]
    surname = parts[0].replace("<", " ").strip() if parts else ""
    given = " ".join(p.replace("<", " ").strip() for p in parts[1:])
    return surname, given, cut


def clean(lines) -> list[str]:
    out = []
    for line in lines if isinstance(lines, list) else []:
        if isinstance(line, str):
            text = _ALLOWED.sub("", line.upper().replace("«", "<<"))
            if text:
                out.append(text)
    return out[:3]


def parse(lines, today: date | None = None) -> dict | None:
    """What the zone says, or None when the lines are not a zone this code can read.

        {"format": "passport, two lines", "surname", "given_names", "name_cut_short",
         "issuing_state", "nationality", "birth_date", "expiry_date",          # ISO dates, "" if not a real date
         "check_digits": {"document_number", "birth_date", "expiry_date", "composite"}}   # True, False or None
    """
    today = today or date.today()
    rows = clean(lines)
    if len(rows) == 2 and len(rows[1]) >= 28 and len(rows[0]) >= 7 and rows[0][0].isalpha():
        top, data = rows
        surname, given, cut = _names(top[5:])
        full = len(data) in (44, 36)
        cover = data[0:10] + data[13:20] + data[21:len(data) - 1]
        out = {"format": "passport, two lines" if top[0] == "P" else "two lines",
               "issuing_state": top[2:5].strip("<"), "nationality": data[10:13].strip("<"),
               "birth_date": _date(data[13:19], today, True), "expiry_date": _date(data[21:27], today, False),
               "check_digits": {"document_number": _digit_ok(data[0:9], data[9]),
                                "birth_date": _digit_ok(data[13:19], data[19]),
                                "expiry_date": _digit_ok(data[21:27], data[27]),
                                "composite": _digit_ok(cover, data[-1]) if full else None}}
        cut = cut and len(top) in (44, 36)
    elif len(rows) == 3 and len(rows[0]) >= 15 and len(rows[1]) >= 18:
        top, data, name = rows
        surname, given, cut = _names(name)
        full = all(len(r) == 30 for r in rows)
        out = {"format": "identity card, three lines",
               "issuing_state": top[2:5].strip("<"), "nationality": data[15:18].strip("<"),
               "birth_date": _date(data[0:6], today, True), "expiry_date": _date(data[8:14], today, False),
               "check_digits": {"document_number": _digit_ok(top[5:14], top[14]),
                                "birth_date": _digit_ok(data[0:6], data[6]),
                                "expiry_date": _digit_ok(data[8:14], data[14]),
                                "composite": _digit_ok(top[5:30] + data[0:7] + data[8:15] + data[18:29], data[29])
                                             if full else None}}
        cut = cut and full
    else:
        return None
    if not surname:
        return None
    return {**out, "surname": surname, "given_names": given, "name_cut_short": cut}


def masked(lines) -> list[str]:
    """The lines with the document number and the personal number hidden, safe to keep and to show."""
    rows = clean(lines)
    dot = "·"
    if len(rows) == 2 and len(rows[1]) >= 28:
        data = rows[1]
        return [rows[0], dot * 9 + data[9:28] + dot * max(len(data) - 30, 0) + data[28:][-2:]]
    if len(rows) == 3 and len(rows[0]) >= 15:
        return [rows[0][:5] + dot * 9 + rows[0][14] + dot * max(len(rows[0]) - 15, 0),
                rows[1][:18] + dot * max(len(rows[1]) - 19, 0) + rows[1][-1:], rows[2]]
    return []


def build_td3(surname: str, given: str, state: str, number: str, birth: str, expiry: str, sex: str = "F") -> list[str]:
    """The two 44-character lines of a passport, with correct check digits. Dates are ISO. Used to draw the
    sample passports and by the tests."""
    def field(text: str, size: int) -> str:
        return _ALLOWED.sub("", text.upper().replace(" ", "<").replace("-", "<"))[:size].ljust(size, "<")

    top = "P<" + field(state, 3) + field(f"{surname.strip()}<<{given.strip()}", 39)
    doc, born, ends = field(number, 9), birth[2:].replace("-", ""), expiry[2:].replace("-", "")
    personal = "<" * 14
    data = (doc + check_digit(doc) + field(state, 3) + born + check_digit(born) + field(sex, 1) + ends
            + check_digit(ends) + personal + check_digit(personal))
    return [top, data + check_digit(data[0:10] + data[13:20] + data[21:43])]
