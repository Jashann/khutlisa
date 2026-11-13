"""California's property type codes, grouped into the kinds of money a holder owes.

California's file writes each property's type as a code and a short description ("MS01: WAGES, PAYROLL,
SALARIES"). The lettered codes are the standard codes of the National Association of Unclaimed Property
Administrators as California uses them; the State Controller publishes the list (SOURCE_URL, read on 13 Nov
2026), and every lettered code below was grouped from that list. The file also carries older numeric codes
("81: Non Standard NAUPA Code for - Salaries/wages"). No page of the Controller that was read describes those, so
they are grouped by the description the file itself prints beside the code, and marked unverified.

Grouping is a lookup in code. Nothing is guessed: a code that is in neither list goes to "other".
"""
from __future__ import annotations

SOURCE_URL = "https://www.sco.ca.gov/Files-UPD/upd_naupa_II_codes_dormancy_periods.pdf"
SOURCE_LABEL = "State Controller, Standard NAUPA II Electronic File Format Codes and Dormancy Periods"
SOURCE_LINKED_FROM = "https://sco.ca.gov/upd_rptg2.html"
READ_ON = "13 Nov 2026"

# key, label, lettered codes or families (verified against the Controller's list), old numeric codes (unverified)
GROUPS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("bank_accounts", "Bank accounts and deposits", ("AC", "HS"), ("56", "57", "82", "83")),
    ("securities", "Shares, dividends and brokerage balances", ("SC",),
     ("01", "02", "04", "06", "08", "09", "10", "11", "12", "13", "14", "15", "16", "17", "73")),
    ("bank_cheques", "Cashier's cheques, money orders and other bank cheques",
     ("CK01", "CK02", "CK03", "CK04", "CK05", "CK06", "CK07", "CK08", "CK09", "CK15", "CK16"), ("26", "28", "70", "87")),
    ("wages", "Wages, payroll and commissions", ("MS01", "MS02"), ("59", "81")),
    ("vendor", "Vendor payments and accounts payable", ("MS04", "MS08", "CK13"), ("85",)),
    ("refunds", "Refunds, overpayments and customer credit balances",
     ("MS05", "MS07", "MS09", "MS10", "MS11", "MS12", "CK12", "UT"), ("61", "79")),
    ("insurance", "Insurance benefits and premiums", ("IN", "MS03"), ("55", "62", "63", "68", "69", "74", "90")),
    ("retirement", "Retirement accounts and pensions", ("IR", "MS14", "CK11"), ("71", "78")),
    ("royalties", "Royalties and mineral proceeds", ("MI",), ("75", "80")),
    ("escrow", "Escrow, trust and court funds", ("TR", "CT"), ("60", "64", "67", "77", "84")),
    ("tangible", "Safe deposit boxes and other tangible property", ("SD",), ("41", "42")),
    ("other", "Other and unidentified", ("MS06", "MS13", "MS15", "MS16", "MS17", "MS18", "MS99", "CK10", "CK14",
                                         "CK99", "CS", "ZZ"), ("51", "58", "76")),
)
LABELS = {key: label for key, label, _, _ in GROUPS}
_BY_CODE: dict[str, str] = {}
_BY_FAMILY: dict[str, str] = {}
_NUMERIC: dict[str, str] = {}
for _key, _label, _lettered, _numbers in GROUPS:
    for _code in _lettered:
        (_BY_FAMILY if len(_code) == 2 else _BY_CODE)[_code] = _key
    for _code in _numbers:
        _NUMERIC[_code] = _key


def code_of(property_type: str | None) -> str:
    """'MS01' from 'MS01: WAGES, PAYROLL, SALARIES'; '81' from '81: Non Standard NAUPA Code for - Salaries/wages'."""
    return (property_type or "").split(":", 1)[0].strip().upper()


# Lettered codes in the file that the Controller's list does not carry. They are grouped with their family and
# marked unverified.
NOT_IN_THE_LIST = frozenset({"AC55"})


def group_of(property_type: str | None) -> tuple[str, bool]:
    """(the group's key, whether the code was grouped from the Controller's published list)."""
    code = code_of(property_type)
    if code in _BY_CODE:
        return _BY_CODE[code], True
    if code[:2] in _BY_FAMILY and not code[:2].isdigit():
        return _BY_FAMILY[code[:2]], code not in NOT_IN_THE_LIST
    if code in _NUMERIC:
        return _NUMERIC[code], False
    return "other", False


def breakdown(rows: list[tuple[str, int, float]]) -> list[dict]:
    """(property type as the file writes it, properties, dollars) rows added up by group, largest dollars first.
    Each group says how much of it rests on the old numeric codes."""
    groups: dict[str, dict] = {}
    for written, n, amount in rows:
        key, verified = group_of(written)
        g = groups.setdefault(key, {"key": key, "label": LABELS[key], "properties": 0, "amount": 0.0,
                                    "unverified_properties": 0, "unverified_amount": 0.0, "codes": {}})
        g["properties"] += int(n)
        g["amount"] += float(amount)
        if not verified:
            g["unverified_properties"] += int(n)
            g["unverified_amount"] += float(amount)
        code = code_of(written)
        slot = g["codes"].setdefault(code, {"code": code, "as_written": written, "properties": 0, "amount": 0.0,
                                            "verified": verified})
        slot["properties"] += int(n)
        slot["amount"] += float(amount)
    out = []
    for g in sorted(groups.values(), key=lambda g: (-g["amount"], g["key"])):
        codes = sorted(g["codes"].values(), key=lambda c: (-c["amount"], c["code"]))
        for c in codes:
            c["amount"] = round(c["amount"], 2)
        out.append({**g, "amount": round(g["amount"], 2), "unverified_amount": round(g["unverified_amount"], 2),
                    "codes": codes})
    return out
