"""The holder's own list: what each column of an uploaded file means, and which rows can be used.

Two steps, kept apart on purpose.

1. Proposing the mapping. `propose` reads the column titles and a sample of rows and says which column is the
   owner's name, the parts of the last known address, the country, the amount, the currency, the date of last
   activity, the reference and the property type. A language model may be asked for this (through khutlisa.llm);
   it sees the titles and at most 20 sample rows in which every name, address, contact detail and reference has
   been replaced by its shape. Without a model, or when its answer does not fit the file, the proposal comes
   from the titles and the shapes of the values, in code. The holder confirms or corrects the proposal.

2. Validating the rows. `validate` reads every row with the confirmed mapping, in code, and returns the
   balances that can be used and the rows that cannot, each with the reason in words. No model is involved.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from . import llm
from .countries import ALPHA3 as _ALPHA3, COUNTRIES, US_TERRITORIES
from .names import normalise

SAMPLE_ROWS = 20          # the most rows of a file that are ever shown to the model, masked

FIELDS: dict[str, str] = {
    "owner_name": "the owner's full name in one column",
    "first_name": "the owner's given name, when the name is split over columns",
    "middle_name": "the owner's middle name or initial",
    "last_name": "the owner's family name, when the name is split over columns",
    "address_1": "the first line of the last known address (street and number)",
    "address_2": "a second address line (apartment, district)",
    "city": "the city or town of the last known address",
    "region": "the state or province of the last known address",
    "postcode": "the postal or ZIP code",
    "country": "the country of the last known address",
    "amount": "the amount owed to the owner",
    "currency": "the currency of the amount",
    "last_activity": "the date of last activity: for wages the date they became payable, for an account the "
                     "last time the owner did something with it",
    "reference": "the account, employee, cheque or other reference number the holder uses for this balance",
    "property_type": "what kind of property the balance is (wages, a savings account, an uncashed cheque)",
    "email": "the owner's email address",
    "phone": "the owner's telephone number",
    "e_consent": "whether the owner agreed to receive notices electronically",
}
LABELS = {"owner_name": "Owner's name", "first_name": "Given name", "middle_name": "Middle name",
          "last_name": "Family name", "address_1": "Address", "address_2": "Address, second line", "city": "City",
          "region": "State or province", "postcode": "Postal code", "country": "Country", "amount": "Amount",
          "currency": "Currency", "last_activity": "Date of last activity", "reference": "Reference",
          "property_type": "Property type", "email": "Email", "phone": "Telephone",
          "e_consent": "Agreed to electronic notices"}
PRIVATE_FIELDS = {"owner_name", "first_name", "middle_name", "last_name", "address_1", "address_2", "city",
                  "postcode", "email", "phone", "reference"}

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "owner_name": ("owner name", "owner", "name", "full name", "employee name", "ee name", "payee", "payee name",
                   "account holder", "customer name", "customer", "member name", "beneficiary", "worker name",
                   "name last first", "employee"),
    "first_name": ("first name", "fname", "given name", "first", "forename"),
    "middle_name": ("middle name", "middle", "mi", "middle initial"),
    "last_name": ("last name", "lname", "surname", "family name", "last"),
    "address_1": ("address", "address 1", "addr 1", "addr1", "address1", "street", "street address",
                  "address line 1", "mailing address", "last known address", "last known addr 1", "addr",
                  "home address"),
    "address_2": ("address 2", "addr 2", "addr2", "address2", "address line 2", "apt", "suite", "unit"),
    "city": ("city", "town", "locality", "city town"),
    "region": ("state", "province", "region", "st", "state province", "st prov", "prov", "state prov"),
    "postcode": ("zip", "zip code", "zipcode", "postal code", "postcode", "post code", "zip postal", "postal"),
    "country": ("country", "ctry", "country code", "nation", "cntry", "country of residence"),
    "amount": ("amount", "balance", "amt", "net pay", "net amount", "net amt", "check amount", "chk amt",
               "amount due", "unclaimed amount", "outstanding", "outstanding amount", "value", "bal", "amount owed",
               "open amount"),
    "currency": ("currency", "ccy", "curr", "cur", "currency code"),
    "last_activity": ("last activity", "last activity date", "date of last activity", "last activity dt",
                      "check date", "chk date", "pay date", "payable date", "date payable", "issue date",
                      "last transaction", "last transaction date", "last contact", "dormant since",
                      "last owner activity"),
    "reference": ("employee id", "emp id", "ee id", "account", "account number", "acct", "acct no", "acct number",
                  "reference", "ref", "ref no", "payee id", "customer id", "member id", "id", "account no",
                  "check number", "check no", "chk no"),
    "property_type": ("property type", "prop type", "type", "pay type", "description", "category", "naupa",
                      "naupa code", "item type", "property", "kind"),
    "email": ("email", "e mail", "email address", "e mail address"),
    "phone": ("phone", "telephone", "mobile", "cell", "tel", "phone number", "telephone number"),
    "e_consent": ("e consent", "econsent", "electronic consent", "paperless", "paperless consent", "email consent",
                  "e delivery", "electronic delivery", "e notice consent"),
}
# Words in a title that say a date or an id is about something else than the balance.
_NOT_ACTIVITY = {"hire", "hired", "birth", "dob", "term", "termination", "start", "rehire", "report", "run", "created"}
_ABBREVIATIONS = {"dt": "date", "chk": "check", "ck": "check", "cheque": "check", "num": "number", "nbr": "number",
                  "no": "no", "nm": "name", "addr": "addr", "amt": "amt", "ee": "ee", "emp": "emp"}

CURRENCIES = frozenset("USD CAD MXN EUR GBP JPY CNY HKD AUD NZD SGD PHP INR KRW CHF BRL TWD".split())
_SYMBOLS = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}

US_STATES = frozenset("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM
NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split())

_COUNTRY_NAMES: dict[str, str] = {}
for _code, _c in COUNTRIES.items():
    _COUNTRY_NAMES[normalise(_c["name"])] = _code
_COUNTRY_NAMES.update({normalise(k): v for k, v in {
    "USA": "US", "U.S.A.": "US", "U.S.": "US", "United States": "US", "United States of America": "US",
    "America": "US", "UK": "GB", "U.K.": "GB", "Great Britain": "GB", "England": "GB", "Scotland": "GB",
    "Wales": "GB", "Britain": "GB", "Korea": "KR", "Republic of Korea": "KR", "South Korea": "KR",
    "Pilipinas": "PH", "The Philippines": "PH", "Viet Nam": "VN", "Russian Federation": "RU", "Mexico": "MX",
    "Méjico": "MX", "Estados Unidos Mexicanos": "MX", "Deutschland": "DE", "Brasil": "BR", "España": "ES",
    "Italia": "IT", "Nippon": "JP", "PRC": "CN", "Peoples Republic of China": "CN", "Mainland China": "CN",
    "Hong Kong SAR": "HK", "Republic of China": "TW", "Holland": "NL", "The Netherlands": "NL", "UAE": "AE",
    "Czech Republic": "CZ", "Republic of Ireland": "IE", "Eire": "IE",
}.items()})


def _tokens(title: str) -> list[str]:
    words = re.sub(r"[^a-z0-9]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", title).lower()).split()
    return [_ABBREVIATIONS.get(w, w) for w in words]


def signature(header: list[str]) -> str:
    """One short text for a set of column titles, so a mapping confirmed once is offered again for the same
    export. Order, case and punctuation of the titles do not matter."""
    return hashlib.sha256("|".join(sorted(" ".join(_tokens(h)) for h in header)).encode()).hexdigest()[:20]


# ---- reading single values -------------------------------------------------------------------------------------------

def country_of(text: str) -> str | None:
    """ISO two-letter code for a country written as a code or a name, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    upper = raw.upper().replace(".", "")
    if len(upper) == 2 and upper in COUNTRIES:
        return upper
    if len(upper) == 3 and upper in _ALPHA3:
        return _ALPHA3[upper]
    return _COUNTRY_NAMES.get(normalise(raw))


_MONEY_JUNK = re.compile(r"(?i)\b(usd|us|dollars?)\b|[$\s]")


def money_of(text: str) -> Decimal:
    """The amount in a cell. Accepts "$1,284.60", "1284.6", "1.284,60", "1 284,60" and "(45.00)" (negative).
    Raises ValueError for anything that is not one number."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty")
    negative = raw.startswith("(") and raw.endswith(")") or raw.startswith("-") or raw.endswith("-")
    body = _MONEY_JUNK.sub("", raw.strip("()-+"))
    if not re.fullmatch(r"[\d.,']+", body) or not re.search(r"\d", body):
        raise ValueError("not a number")
    body = body.replace("'", "")
    if "," in body and "." in body:
        decimal = "," if body.rfind(",") > body.rfind(".") else "."
        other = "." if decimal == "," else ","
        body = body.replace(other, "").replace(decimal, ".")
    elif "," in body:
        head, _, tail = body.rpartition(",")
        body = head.replace(",", "") + "." + tail if len(tail) in (1, 2) else body.replace(",", "")
    elif body.count(".") > 1:
        body = body.replace(".", "")
    try:
        value = Decimal(body)
    except InvalidOperation:
        raise ValueError("not a number") from None
    return -value if negative else value


def currency_in(text: str) -> str | None:
    """A currency named inside an amount cell ("€ 12,00", "CAD 15.00"), or None."""
    raw = (text or "").upper()
    for code in CURRENCIES:
        if re.search(rf"\b{code}\b", raw):
            return code
    for symbol, code in _SYMBOLS.items():
        if symbol in raw:
            return code
    return None


_MONTHS = {m: i for i, names in enumerate([
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")], start=1) for m in names}
_SLASHED = re.compile(r"(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})")


def _year(text: str) -> int:
    year = int(text)
    return year if len(text) == 4 else 2000 + year if year < 70 else 1900 + year


def date_order(values: list[str]) -> str:
    """How a column writes dates with two numbers before the year: "MDY", "DMY", or "mixed" when both kinds
    are certain to be there. A column in which no date settles it reads as month first, as a United States
    export would write it."""
    month_first = day_first = False
    for v in values:
        m = _SLASHED.fullmatch((v or "").strip().split(" ")[0])
        if not m or len(m.group(1)) == 4:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            day_first = True
        elif b > 12 >= a:
            month_first = True
    return "mixed" if month_first and day_first else "DMY" if day_first else "MDY"


class _Reason(ValueError):
    """A reason of our own wording, as against the date library's."""


def date_of(text: str, order: str = "MDY") -> date:
    """The date in a cell. Raises ValueError with a reason in words."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("it is empty")
    raw = re.sub(r"[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\s*([AaPp][Mm])?(Z|[+-]\d{2}:?\d{2})?$", "", raw).strip()
    try:
        if re.fullmatch(r"\d{8}", raw):
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
        if re.fullmatch(r"\d{5}", raw) and 20000 <= int(raw) <= 80000:      # an Excel day count
            return (datetime(1899, 12, 30) + timedelta(days=int(raw))).date()
        m = _SLASHED.fullmatch(raw)
        if m:
            a, b, c = m.groups()
            if len(a) == 4:
                return date(int(a), int(b), int(c))
            x, y = int(a), int(b)
            if x > 12 and y > 12:
                raise _Reason("neither of its first two numbers can be a month")
            if order == "mixed" and x <= 12 and y <= 12 and x != y:
                raise _Reason("it could be day first or month first, and this column has both kinds")
            day_first = x > 12 or (order == "DMY" and y <= 12)
            return date(_year(c), y if day_first else x, x if day_first else y)
        m = re.fullmatch(r"(\d{1,2})[\s\-/.]*([A-Za-z]{3,9})\.?,?[\s\-/.]*(\d{2,4})", raw)
        if m and m.group(2).lower() in _MONTHS:
            return date(_year(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
        m = re.fullmatch(r"([A-Za-z]{3,9})\.?[\s\-/.]*(\d{1,2})(?:st|nd|rd|th)?,?[\s\-/.]*(\d{2,4})", raw)
        if m and m.group(1).lower() in _MONTHS:
            return date(_year(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    except _Reason:
        raise
    except ValueError:
        raise ValueError("there is no such day") from None
    raise ValueError("it is not written as a date")


def consent_of(text: str) -> bool | None:
    word = (text or "").strip().lower()
    if word in ("y", "yes", "true", "1", "x", "consented", "opted in", "opt-in", "agreed"):
        return True
    if word in ("n", "no", "false", "0", "declined", "opted out", "opt-out"):
        return False
    return None


# What kind of property a holder's own words describe, as one of the classes in dormancy.PERIODS.
_NAUPA = {"MS01": "wages", "MS02": "wages", "AC01": "bank_account", "AC02": "bank_account", "AC03": "bank_account",
          "CK01": "cheque", "CK07": "money_order", "CK08": "travelers_cheque", "CK13": "cheque", "MS16": "cheque"}
_CLASS_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("travelers_cheque", ("traveler", "traveller")),
    ("money_order", ("money order",)),
    ("wages", ("wage", "salary", "salaries", "payroll", "paycheck", "paycheque", "pay check", "final pay",
               "commission")),
    ("ordered_refund", ("ordered refund", "court ordered", "court-ordered")),
    ("bank_account", ("checking", "savings", "demand deposit", "time deposit", "certificate of deposit")),
    ("securities", ("dividend", "stock", "shares", "bond")),
    ("life_insurance", ("life insurance", "annuity", "death benefit")),
    ("cheque", ("cashier", "uncashed check", "uncashed cheque", "vendor check", "vendor cheque", "written instrument")),
)


def property_class(text: str) -> tuple[str, bool]:
    """(the dormancy class, whether the holder's words settled it). Words that settle nothing give "other",
    which carries California's general three years."""
    raw = (text or "").strip()
    code = raw[:4].upper()
    if code in _NAUPA:
        return _NAUPA[code], True
    low = raw.lower()
    for name, words in _CLASS_WORDS:
        if any(w in low for w in words):
            return name, True
    return "other", False


# ---- the shape of a column ---------------------------------------------------------------------------------------

def _share(values: list[str], test) -> float:
    filled = [v for v in values if v]
    if not filled:
        return 0.0
    return sum(1 for v in filled if test(v)) / len(filled)


def _try(fn, *args) -> bool:
    try:
        fn(*args)
        return True
    except ValueError:
        return False


_SHAPES = {
    "amount": lambda v: _try(money_of, v) and bool(re.search(r"[.,]\d{1,2}\)?$|[$€£]", v)),
    "last_activity": lambda v: _try(date_of, v, "MDY") or _try(date_of, v, "DMY"),
    "email": lambda v: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v)),
    "country": lambda v: country_of(v) is not None and not v.isdigit(),
    "currency": lambda v: v.upper() in CURRENCIES,
    "phone": lambda v: bool(re.fullmatch(r"[+()\d][\d\s().\-+x]{6,}", v)) and sum(c.isdigit() for c in v) >= 7,
    "postcode": lambda v: bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 \-]{2,9}", v)) and any(c.isdigit() for c in v),
    "e_consent": lambda v: consent_of(v) is not None,
}
_SHAPE_ALONE = ("amount", "last_activity", "email", "country", "currency")   # shapes that can name a column alone


def _header_score(field: str, title: str) -> float:
    tokens = _tokens(title)
    if not tokens:
        return 0.0
    joined = " ".join(tokens)
    best = 0.0
    for synonym in _SYNONYMS[field]:
        words = synonym.split()
        if joined == synonym:
            best = max(best, 1.0)
        elif all(w in tokens for w in words):
            best = max(best, 0.55 + 0.35 * len(words) / len(tokens))
    if field == "last_activity":
        if _NOT_ACTIVITY & set(tokens):
            best *= 0.2
        elif best == 0 and "date" in tokens:
            best = 0.4
    if field == "reference" and {"check", "invoice", "batch"} & set(tokens):
        best *= 0.6          # a cheque number names the payment; an employee or account number names the balance
    return best


def propose_from_code(header: list[str], rows: list[list[str]]) -> dict[str, dict]:
    """{field: {"column", "source", "score"}} from the titles and the shapes of the values. `source` is "title"
    or "values". Each column is used for one field at most."""
    sample = rows[:400]
    columns = {title: [r[i] for r in sample] for i, title in enumerate(header)}
    scored: list[tuple[float, str, str, str]] = []
    for field in FIELDS:
        for title, values in columns.items():
            by_title = _header_score(field, title)
            shape = _share(values, _SHAPES[field]) if field in _SHAPES else None
            score, source = by_title, "title"
            if shape is not None:
                if by_title and shape < 0.3 and any(values):
                    score = by_title * 0.3            # the title fits and the values do not
                elif by_title:
                    score = by_title + 0.2 * shape
                elif field in _SHAPE_ALONE and shape >= 0.9:
                    score, source = 0.5 * shape, "values"
            if score >= 0.45:
                scored.append((score, field, title, source))
    out: dict[str, dict] = {}
    used: set[str] = set()
    for score, field, title, source in sorted(scored, key=lambda s: (-s[0], header.index(s[2]))):
        if field in out or title in used:
            continue
        out[field] = {"column": title, "source": source, "score": round(min(score, 1.0), 2)}
        used.add(title)
    if "owner_name" in out and "first_name" in out and "last_name" in out:
        del out["owner_name"]                  # the name is split over columns: the split columns are the name
    return out


# ---- the masked sample and the model ---------------------------------------------------------------------------------

def mask_shape(value: str) -> str:
    """A value with every letter and digit replaced, so only its shape is left: "Calle Fresno 214" becomes
    "Xxxxx Xxxxx 999". Words are cut to five characters, so not even their length is exact."""
    out = []
    for word in value.split(" "):
        shaped = "".join("9" if c.isdigit() else ("X" if c.isupper() else "x") if c.isalpha() else c for c in word)
        out.append(shaped[:5])
    return " ".join(out)[:40]


def _safe_to_show(value: str, column_values: list[str], total_rows: int) -> bool:
    """True for a value that says nothing about a person: a number, a date, a country, a currency, a yes or
    no, or one of a handful of labels that the whole column repeats (a pay type, a status)."""
    if not value:
        return True
    if _try(money_of, value) and not re.fullmatch(r"\d{5,}", value):
        return True
    if _try(date_of, value, "MDY") or _try(date_of, value, "DMY"):
        return True
    if country_of(value) or value.upper() in CURRENCIES or consent_of(value) is not None:
        return True
    distinct = {v.lower() for v in column_values if v}
    return (total_rows >= 30 and len(distinct) <= 12 and not any(c.isdigit() for c in value)
            and len(value.split()) <= 5 and "@" not in value)


def masked_sample(header: list[str], rows: list[list[str]], guess: dict[str, dict] | None = None) -> list[list[str]]:
    """At most SAMPLE_ROWS rows for the model, spread over the file. Every cell of a column that code takes for
    a name, an address part, a contact detail or a reference is replaced by its shape, and so is every other
    cell that is not plainly a number, a date, a country, a currency or a repeated label."""
    guess = guess if guess is not None else propose_from_code(header, rows)
    private = {g["column"] for f, g in guess.items() if f in PRIVATE_FIELDS}
    step = max(1, len(rows) // SAMPLE_ROWS)
    picked = rows[::step][:SAMPLE_ROWS]
    columns = [[r[i] for r in rows[:2000]] for i in range(len(header))]
    out = []
    for row in picked:
        out.append([mask_shape(v) if header[i] in private or not _safe_to_show(v, columns[i], len(rows)) else v
                    for i, v in enumerate(row)])
    return out


PROMPT = """A company has exported a list of dormant balances it owes to people (former employees or customers) \
from its payroll or banking system. Say which column holds which piece of information.

The column titles, in order:
{header}

Sample rows (at most 20). Names, addresses, contact details and reference numbers have been replaced by their \
shape (X for a capital letter, x for a small letter, 9 for a digit), so you cannot and need not read them:
{rows}

The pieces of information we need:
{fields}

Return JSON of this shape:
{{"mapping": {{"<field>": "<the exact column title, or null when no column holds it>", ...}},
 "date_order": "MDY, DMY or YMD: how the date of last activity is written, or null if you cannot tell",
 "notes": "one short sentence about anything unusual, or an empty string"}}

Rules: use each column for one field at most. Use the exact titles given. If the name is split over a given-name \
and a family-name column, fill first_name and last_name and leave owner_name null. The date of last activity is \
the date the money became payable or the owner last did something, not a hire, birth, termination or report date. \
The reference names the balance or the person (an account or employee number), not a batch."""


def propose_from_model(header: list[str], rows: list[list[str]], guess: dict[str, dict], model: str = "haiku") -> dict:
    """The model's proposal, cut down to what fits the file: {"mapping": {field: column}, "date_order", "notes"}.
    Raises llm.ModelUnavailable or ValueError; the caller then keeps the proposal made in code."""
    import json

    sample = masked_sample(header, rows, guess)
    prompt = PROMPT.format(header=json.dumps(header, ensure_ascii=False),
                           rows="\n".join(json.dumps(r, ensure_ascii=False) for r in sample),
                           fields="\n".join(f"- {name}: {text}" for name, text in FIELDS.items()))
    answer = llm.ask_json(prompt, model=model, timeout=90)
    if not isinstance(answer, dict) or not isinstance(answer.get("mapping"), dict):
        raise ValueError("the model did not return a mapping")
    mapping: dict[str, str] = {}
    for field, title in answer["mapping"].items():
        if field in FIELDS and isinstance(title, str) and title in header and title not in mapping.values():
            mapping[field] = title
    order = answer.get("date_order") if answer.get("date_order") in ("MDY", "DMY", "YMD") else None
    return {"mapping": mapping, "date_order": order, "notes": str(answer.get("notes") or "")[:300],
            "sample_rows_sent": len(sample)}


def propose(header: list[str], rows: list[list[str]], remembered: dict | None = None, use_model: bool = True,
            model: str = "haiku") -> dict:
    """The proposal the holder is shown: for each field the column, where the proposal came from ("remembered",
    "model", "title" or "values") and, for the whole proposal, `by`: "remembered", "model" or "code"."""
    guess = propose_from_code(header, rows)
    out = {"by": "code", "fields": {}, "notes": "", "model_note": "", "sample_rows_sent": 0}
    if remembered and all(c in header for c in remembered.get("mapping", {}).values()):
        out["by"] = "remembered"
        out["fields"] = {f: {"column": c, "source": "remembered"} for f, c in remembered["mapping"].items()}
        out["defaults"] = remembered.get("defaults") or {}
        return _finish(out, header, rows)
    fields = {f: {"column": g["column"], "source": g["source"]} for f, g in guess.items()}
    if use_model:
        try:
            said = propose_from_model(header, rows, guess, model=model)
        except llm.ModelUnavailable as err:
            out["model_note"] = (str(err) if getattr(err, "for_screen", False) else
                                 "No language model is available on this server, so the columns were read in code "
                                 "from their titles and values.")
        except Exception:
            out["model_note"] = ("The language model's answer did not fit this file, so the columns were read in "
                                 "code from their titles and values.")
        else:
            out["by"], out["notes"], out["sample_rows_sent"] = "model", said["notes"], said["sample_rows_sent"]
            taken = set(said["mapping"].values())
            merged = {f: {"column": c, "source": "model"} for f, c in said["mapping"].items()}
            for f, g in fields.items():      # what the model left out, code may still fill from a free column
                if f not in merged and g["column"] not in taken:
                    merged[f] = g
                    taken.add(g["column"])
            if "first_name" in merged and "last_name" in merged:
                merged.pop("owner_name", None)
            fields = merged
    out["fields"] = fields
    return _finish(out, header, rows)


def _finish(out: dict, header: list[str], rows: list[list[str]]) -> dict:
    mapping = {f: g["column"] for f, g in out["fields"].items()}
    out["missing"] = missing_fields(mapping)
    out.setdefault("defaults", {})
    used = set(mapping.values())
    out["unused_columns"] = [h for h in header if h not in used]
    return out


def missing_fields(mapping: dict[str, str]) -> list[str]:
    """What a mapping still needs before rows can be read, in words."""
    need = []
    if not mapping.get("owner_name") and not (mapping.get("first_name") and mapping.get("last_name")):
        need.append("the owner's name")
    if not mapping.get("amount"):
        need.append("the amount")
    if not mapping.get("last_activity"):
        need.append("the date of last activity")
    return need


def clean_mapping(raw: dict, header: list[str]) -> dict[str, str]:
    """A mapping the holder sent back, checked against the file. Raises ValueError in words for the screen."""
    mapping: dict[str, str] = {}
    for field, title in (raw or {}).items():
        if title in (None, ""):
            continue
        if field not in FIELDS:
            raise ValueError(f"There is no field called {field}")
        if title not in header:
            raise ValueError(f"The file has no column called {title}")
        if title in mapping.values():
            raise ValueError(f"The column {title} is used for two fields. Each column can hold one")
        mapping[field] = title
    need = missing_fields(mapping)
    if need:
        raise ValueError("Choose the column for " + ", ".join(need))
    return mapping


# ---- every row, in code ------------------------------------------------------------------------------------------------

LIMIT_USD = Decimal("10000000")
EARLIEST = date(1970, 1, 1)


def _name(cells: dict[str, str]) -> str:
    if cells.get("owner_name"):
        return cells["owner_name"]
    return " ".join(x for x in (cells.get("first_name"), cells.get("middle_name"), cells.get("last_name")) if x)


def tidy_name(name: str) -> str:
    """"Tolmedo, Marisol E." as "Marisol E. Tolmedo": a payroll export writes the family name first."""
    if name.count(",") == 1:
        family, given = (part.strip() for part in name.split(","))
        if family and given:
            return f"{given} {family}"
    return name.strip()


def validate(header: list[str], rows: list[list[str]], row_numbers: list[int], mapping: dict[str, str],
             defaults: dict | None = None, today: date | None = None) -> dict:
    """Every row read with the confirmed mapping. Returns {"balances", "failed", "notes", "date_order"}.

    A balance is a dict of cleaned values; `row` is the row's number in the holder's file. A failed row keeps
    its number and its reasons. `defaults` may carry "property_class" (the kind of property every row is, when
    the file has no column for it) and "country" (the country of every row with none written)."""
    defaults = defaults or {}
    today = today or datetime.now().date()
    at = {field: header.index(title) for field, title in mapping.items()}
    order = date_order([r[at["last_activity"]] for r in rows]) if "last_activity" in at else "MDY"
    notes: list[str] = []
    if order == "mixed":
        notes.append("The date column writes some dates day first and some month first. A date that could be "
                     "read both ways is not used.")
    elif order == "DMY":
        notes.append("Dates were read day first, because some of them cannot be read any other way.")
    if "currency" not in at:
        notes.append("The file has no currency column, so amounts were read as US dollars unless the amount "
                     "itself names another currency.")
    if "property_type" not in at:
        kind = defaults.get("property_class") or "other"
        notes.append(f"The file has no column for the kind of property, so every balance was read as "
                     f"{'wages' if kind == 'wages' else kind.replace('_', ' ')}.")
    balances: list[dict] = []
    failed: list[dict] = []
    seen: dict[tuple, int] = {}
    unsettled_kinds = 0
    for cells_raw, number in zip(rows, row_numbers):
        cells = {field: cells_raw[i].strip() for field, i in at.items()}
        reasons: list[str] = []
        name = tidy_name(_name(cells))
        if len(normalise(name).replace(" ", "")) < 2:
            reasons.append("There is no owner name.")
        # the amount and its currency
        amount = None
        try:
            amount = money_of(cells.get("amount", ""))
        except ValueError:
            shown = cells.get("amount", "")
            reasons.append("There is no amount." if not shown else f'The amount "{shown[:30]}" is not a number.')
        currency = (cells.get("currency") or "").upper() or currency_in(cells.get("amount", "")) or "USD"
        if currency not in CURRENCIES:
            reasons.append(f'The currency "{currency[:10]}" is not one this build knows.')
        elif currency != "USD":
            reasons.append(f"The amount is in {currency}. This build handles balances held in US dollars only.")
        if amount is not None:
            if amount <= 0:
                reasons.append(f"The amount is {'zero' if amount == 0 else 'negative'}, so nothing is owed on this row.")
            elif amount > LIMIT_USD:
                reasons.append("The amount is more than 10 million, which looks like a mistake in the file.")
        # the date of last activity
        when = None
        try:
            when = date_of(cells.get("last_activity", ""), order)
            if when > today:
                reasons.append(f"The date of last activity, {when.isoformat()}, is in the future.")
            elif when < EARLIEST:
                reasons.append(f"The date of last activity, {when.isoformat()}, is before 1970.")
        except ValueError as err:
            shown = cells.get("last_activity", "")
            reasons.append("There is no date of last activity." if not shown else
                           f'The date "{shown[:30]}" cannot be used: {err}.')
        # the country
        region = (cells.get("region") or "").upper().replace(".", "")
        written = cells.get("country") or ""
        country = country_of(written) if written else None
        if written and country is None:
            reasons.append(f'The country "{written[:30]}" is not one that can be recognised.')
        elif not written:
            if region in US_STATES or region in US_TERRITORIES:
                country = "US"
            elif defaults.get("country") and country_of(defaults["country"]):
                country = country_of(defaults["country"])
            else:
                reasons.append("There is no country, and the state or province is not one of the United States.")
        elif country != "US" and written.upper() == region and region in US_STATES:
            reasons.append(f'The country and the state both read "{region}", so the row may be in the United '
                           "States or abroad. A person has to look at it.")
        kind_words = cells.get("property_type", "")
        kind, settled = property_class(kind_words) if "property_type" in at else (defaults.get("property_class") or "other", True)
        if "property_type" in at and not settled and defaults.get("property_class") and not kind_words:
            kind, settled = defaults["property_class"], True
        reference = cells.get("reference", "")
        key = (normalise(name), reference, str(amount), str(when)) if not reasons else None
        if key is not None and key in seen:
            reasons.append(f"This row repeats row {seen[key]}: the same owner, reference, amount and date.")
        if reasons:
            failed.append({"row": number, "reasons": reasons, "reference": reference[-4:] if reference else ""})
            continue
        seen[key] = number
        if not settled:
            unsettled_kinds += 1
        street = ", ".join(x for x in (cells.get("address_1"), cells.get("address_2")) if x)
        balances.append({
            "row": number, "name": name, "street": street, "city": cells.get("city", ""),
            "region": cells.get("region", ""), "postcode": cells.get("postcode", ""), "country": country,
            "amount": f"{amount.quantize(Decimal('0.01')):.2f}", "currency": "USD",
            "last_activity": when.isoformat(), "reference": reference,
            "property_words": kind_words, "property_class": kind, "class_settled": settled,
            "email": cells.get("email", "") if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", cells.get("email", "")) else "",
            "phone": cells.get("phone", ""), "e_consent": consent_of(cells.get("e_consent", "")),
            "abroad": country != "US" and country not in US_TERRITORIES,
        })
    if unsettled_kinds:
        notes.append(f"{unsettled_kinds:,} {'balance has' if unsettled_kinds == 1 else 'balances have'} a kind of "
                     "property that is not one of the named kinds. They are read as other property, which "
                     "California treats as unclaimed after three years.")
    return {"balances": balances, "failed": failed, "notes": notes, "date_order": order}


def failure_summary(failed: list[dict]) -> list[dict]:
    """The reasons rows failed, counted, with the commonest first. A reason's own figures are left out of the
    count's wording, so "The amount "TBD" is not a number" and its like count as one kind."""
    kinds: dict[str, dict] = {}
    for row in failed:
        for reason in row["reasons"]:
            kind = re.sub(r' "[^"]*"', "", reason)
            kind = re.sub(r", \d{4}-\d{2}-\d{2},", "", kind)
            kind = re.sub(r"row \d+", "an earlier row", kind)
            kind = re.sub(r"in [A-Z]{3}\.", "in another currency.", kind)
            kind = re.sub(r"cannot be used: .*", "cannot be used.", kind)
            slot = kinds.setdefault(kind, {"reason": kind, "rows": 0, "first_rows": []})
            slot["rows"] += 1
            if len(slot["first_rows"]) < 5:
                slot["first_rows"].append(row["row"])
    return sorted(kinds.values(), key=lambda k: -k["rows"])
