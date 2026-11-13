"""The proof file's documents: storing what a claimant uploads, and reading it.

`read_document` shows one photo or PDF to a language model and returns only what is visibly printed on it. The
model reads; it decides nothing. Every comparison with the register record is done in code, in proof.py.
Identity numbers are never kept: the model is told to name the kind of number only, and anything that still looks
like a number is masked down to its last two characters before the reading is returned.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import llm, mrz
from .names import tokens

# The kinds a claimant can choose when they upload a document. The claim checklist is driven by these.
KINDS: dict[str, str] = {
    "id": "Photo identification",
    "proof_of_address": "Proof of address",
    "payslip": "Payslip",
    "lease": "Lease",
    "tax_number": "Social Security or taxpayer number document",
    "death_certificate": "Death certificate",
    "birth_certificate": "Birth certificate",
    "name_change": "Marriage certificate or legal name-change document",
    "heirship": "Will, court order or other proof of who inherits",
    "authority": "Proof of authority to sign for an organisation",
    "other": "Other document",
}

# What each kind of document can carry, as evidence. The tie between a claimant and the owner named in the
# register may rest only on the first two: identification a government issued with the holder's photograph, or a
# civil or court record that links two names (a marriage certificate, a legal change of name). The others show
# an address, a number or an employer. A document of the last weight is one anyone could type up, so it settles
# nothing by itself and never ties a person to a record.
GOVERNMENT_PHOTO_ID = "government photo identification"
NAME_LINK = "civil or court record linking two names"
CIVIL_RECORD = "civil or court record"
ISSUED_BY_ORGANISATION = "issued by an organisation"
ANYONE_COULD_MAKE_IT = "anyone could make it"
WEIGHT: dict[str, str] = {
    "id": GOVERNMENT_PHOTO_ID,
    "name_change": NAME_LINK,
    "death_certificate": CIVIL_RECORD,
    "birth_certificate": CIVIL_RECORD,
    "heirship": CIVIL_RECORD,
    "tax_number": ISSUED_BY_ORGANISATION,
    "proof_of_address": ISSUED_BY_ORGANISATION,
    "payslip": ISSUED_BY_ORGANISATION,
    "lease": ISSUED_BY_ORGANISATION,
    "authority": ISSUED_BY_ORGANISATION,
    "other": ANYONE_COULD_MAKE_IT,
}
TIES_A_PERSON_TO_THE_OWNER = frozenset({GOVERNMENT_PHOTO_ID, NAME_LINK})

# The kinds of concern the reader can raise. Every kind stops the document from settling anything, except an
# expiry (the dates are checked in code) and, on the sample register only, the sample mark.
CONCERN_KINDS = ("editing", "sample_mark", "name_mismatch", "illegible", "cropped", "not_what_it_claims", "expired")
_SAMPLE_WORDS = re.compile(r"\b(sample|specimen|void|placeholder|demonstration|not a real)\b", re.I)

MAX_BYTES = 15 * 1024 * 1024

# Accepted uploads, recognised by their first bytes and not by the file name or the browser's stated type.
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
]


def sniff(data: bytes) -> tuple[str, str] | None:
    """(content type, file extension) for an image or PDF we accept, or None for anything else."""
    for magic, content_type, ext in _SIGNATURES:
        if data.startswith(magic):
            return content_type, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"heif"):
        return "image/heic", ".heic"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff", ".tif"
    return None


def safe_label(filename: str) -> str:
    """The uploaded file's own name, cut down to something safe to show and store. Never used as a path."""
    name = re.sub(r"[^\w .()\-]+", "_", Path(filename or "").name).strip(" .")
    return name[:80] or "document"


READ_PROMPT = """You are reading one document that a person uploaded to prove a claim for unclaimed money. \
They say it is: {kind}.

Look at the file and report only what is visibly printed or written on it. Do not guess, do not complete a \
partly hidden word, and do not use outside knowledge about the person or the organisation. When something cannot \
be read, leave it out and say so in "concerns".

Return JSON with exactly these fields:
- document_type: what the document is, in a few plain words (for example "hospital staff identity badge", \
"payslip", "electricity and water bill", "passport photo page")
- names: every personal name printed on it, each exactly as printed (list of strings)
- addresses: every postal address printed on it, as objects with street, city, region (state or province), \
postcode, country (two-letter code if it is clear, else ""), and whose (one of "person", "issuer", "other"). \
Use "" for a part that is not printed.
- dates: every date printed on it, as objects with label (what the date is, in the document's own words, for \
example "pay date", "expires", "bill date") and value (YYYY-MM-DD when the full date is printed, otherwise as \
printed)
- issuer: the organisation that issued the document (employer, hospital, utility, bank, government office), as \
printed, or ""
- holder_name: the name of the person the document was issued to or is about, exactly as printed in its main name \
field (on a passport or identity card, the surname and given names fields together), or ""
- issue_date: the date the document was issued or is dated (date of issue, bill date, statement date, pay date, \
letter date), as YYYY-MM-DD, or "" when no such full date is printed
- expiry_date: the date the document says it expires or stops being valid, as YYYY-MM-DD, or "" when none is printed
- date_of_birth: the holder's date of birth as YYYY-MM-DD, or "" when none is printed
- issuing_authority: the authority or organisation the document names as having issued it, exactly as printed, or ""
- issuing_country: the country the document says issued it, as printed (a name or a code), or "" when no country \
is printed. Do not work it out from an address or from what you know.
- machine_readable_lines: if the document has machine-readable lines (rows of capital letters, digits and the \
filler character < at the foot of a passport or identity card), each line exactly as printed, character for \
character, keeping every <, as a list of strings from top to bottom. Copy them; do not correct them or rebuild \
them from the other fields. This is the one field where a number printed on the document is copied: the program \
checks it and does not keep it. Empty list when there are none.
- identifiers_present: the KINDS of identity or account numbers that appear, for example "passport number", \
"employee number", "account number", "Social Security number". Name the kind only. Never write the number itself, \
in this field or in any other field.
- legible: true if the main text can be read with confidence, false if it is blurred, too dark, cut off or too small
- presents_as_government_photo_id: true only if the document presents itself as identification issued by a \
government body to the holder (a passport, a national identity card, a driver licence, a state identity card). \
Go by what the document says it is. A staff badge, a membership card, a bank card, a letter or a page that \
only carries a name is not one. Doubts about whether it is genuine go in "concerns", not here.
- photo_present: true only if a photograph of the holder is on it (on a document marked SAMPLE or SPECIMEN, a \
drawn placeholder where the photograph goes counts)
- concerns: anything a careful clerk would question, as objects with kind and text. kind is one of: \
"editing" (a concrete sign the document was altered: text in a different font or alignment from its \
surroundings, erased or pasted areas), "sample_mark" (a watermark or line such as SAMPLE, SPECIMEN or VOID), \
"name_mismatch" (names on the document that disagree with each other), "illegible" (a part that could not be \
read), "cropped" (part of the document is cut off or missing), "not_what_it_claims" (it is plainly a different \
kind of document from the one the person says it is: a staff badge or membership card offered as government \
identification, plain typed text offered as an identity card, or an identity document with no photograph. \
Never raise this because a letter, a bill, a statement or a payslip has no photograph), "expired" (an expiry \
date that has passed). text is one plain sentence. If the document is marked as a sample, say so once with \
kind "sample_mark" and do not list separately the things that follow from its being a sample (a placeholder \
photograph, an invented issuer or country, an invented number, a plain layout). Empty list if there is nothing \
to question.
- marked_sample: true if the document is visibly marked SAMPLE, SPECIMEN, VOID or similar
- signs_of_editing: true only if you can see a concrete sign that the document was altered after it was issued
- summary: one or two plain English sentences saying what the document shows. No identity or account numbers."""

# Runs that look like an identity or account number: a Social Security pattern, a long run of digits (with or
# without spaces or dashes between groups), or a long code that is mostly digits.
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b")
_NUMBERISH = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){8,}\d\b|\b\d{7,}\b|\b[A-Z]{1,6}-?\d{4,}[A-Z0-9]*\b", re.I)


def mask_number(value: str) -> str:
    """'P1234567' -> '······67'. All but the last two characters are hidden."""
    return "·" * max(len(value) - 2, 0) + value[-2:]


def mask_numbers(text: str) -> str:
    """Hides anything in a sentence that looks like an identity or account number. Dates are left alone."""
    kept: list[str] = []

    def keep(m: re.Match) -> str:
        kept.append(m.group())
        return f"\x00{len(kept) - 1}\x00"

    text = _DATE.sub(keep, text or "")
    text = _NUMBERISH.sub(lambda m: mask_number(m.group()), text)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)


def _words(value, limit: int = 200) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return " ".join(str(value).split())[:limit]


def _list(value) -> list:
    return value if isinstance(value, list) else [] if value in (None, "") else [value]


def clean_reading(raw: dict) -> dict:
    """The model's answer in a fixed shape, with every number-like run masked. Nothing else is trusted from it."""
    names = [mask_numbers(_words(n, 120)) for n in _list(raw.get("names")) if _words(n)]
    addresses = []
    for a in _list(raw.get("addresses")):
        if isinstance(a, dict):
            address = {k: _words(a.get(k) or "", 120) for k in ("street", "city", "region", "postcode", "country")}
            address["whose"] = _words(a.get("whose") or "", 12).lower()
            if any(address[k] for k in ("street", "city", "postcode")):
                addresses.append(address)
    dates = []
    for d in _list(raw.get("dates")):
        if isinstance(d, dict) and _words(d.get("value")):
            dates.append({"label": _words(d.get("label") or "", 60), "value": _words(d.get("value"), 40)})
        elif _words(d):
            dates.append({"label": "", "value": _words(d, 40)})
    concerns, concern_kinds = [], []
    for c in _list(raw.get("concerns"))[:10]:
        text = mask_numbers(_words(c.get("text") if isinstance(c, dict) else c, 300))
        if not text:
            continue
        kind = _words(c.get("kind") or "", 30).lower() if isinstance(c, dict) else ""
        if kind not in CONCERN_KINDS:   # a bare sentence, or a kind we did not ask for
            kind = "sample_mark" if _SAMPLE_WORDS.search(text) else "other"
        concerns.append(text)
        concern_kinds.append(kind)
    reading = {
        "status": "read",
        "document_type": mask_numbers(_words(raw.get("document_type") or "", 80)),
        "names": names[:10],
        "addresses": addresses[:6],
        "dates": dates[:12],
        "issuer": mask_numbers(_words(raw.get("issuer") or "", 120)),
        "identifiers_present": [mask_numbers(_words(i, 60)) for i in _list(raw.get("identifiers_present"))
                                if _words(i)][:10],
        "legible": raw.get("legible") is not False,
        "concerns": concerns,
        "concern_kinds": concern_kinds,          # one per concern, in the same order
        "presents_as_government_photo_id": raw.get("presents_as_government_photo_id") is True,
        "photo_present": raw.get("photo_present") is True,
        "marked_sample": raw.get("marked_sample") is True,
        "signs_of_editing": raw.get("signs_of_editing") is True,
        "summary": mask_numbers(_words(raw.get("summary") or "", 500)),
        # What the checks in checks.py work from. The model only copied these; code decides what they mean.
        "holder_name": mask_numbers(_words(raw.get("holder_name") or "", 120)),
        "issue_date": _words(raw.get("issue_date") or "", 40),
        "expiry_date": _words(raw.get("expiry_date") or "", 40),
        "date_of_birth": _words(raw.get("date_of_birth") or "", 40),
        "issuing_authority": mask_numbers(_words(raw.get("issuing_authority") or "", 120)),
        "issuing_country": mask_numbers(_words(raw.get("issuing_country") or "", 60)),
        "mrz": _zone(raw.get("machine_readable_lines")),
    }
    if not (reading["names"] or reading["addresses"] or reading["issuer"] or reading["dates"]):
        reading["status"] = "unreadable"
        reading["legible"] = False
    return reading


def _zone(lines) -> dict | None:
    """The machine-readable lines, parsed (mrz.py) and kept without their numbers. None when there are none;
    {"parsed": False} when lines were copied that code cannot read as a zone."""
    rows = mrz.clean(lines)
    if not rows:
        return None
    parsed = mrz.parse(rows)
    if parsed is None:
        return {"parsed": False, "lines": []}
    return {"parsed": True, **parsed, "lines": mrz.masked(rows)}


# ---- two readings of one document ---------------------------------------------------------------------------

# What two separate readings of one document must agree on, with the words used when they do not.
COMPARED = (("holder_name", "name"), ("issue_date", "issue date"), ("expiry_date", "expiry date"),
            ("date_of_birth", "date of birth"), ("mrz_name", "name in the machine-readable lines"),
            ("mrz_expiry_date", "expiry date in the machine-readable lines"))
_LABELLED = {"issue_date": re.compile(r"issu|^dated?$|^signed|(bill|statement|pay|letter)\w* date", re.I),
             "expiry_date": re.compile(r"expir|valid (until|to|thru|through)|good (until|thru)", re.I),
             "date_of_birth": re.compile(r"birth", re.I)}


def date_field(reading: dict, field: str) -> str:
    """The issue date, expiry date or date of birth a reading reports: its own field, or for a reading made
    before those fields existed, the first date in its list whose label says so."""
    if reading.get(field):
        return reading[field]
    return next((d.get("value") or "" for d in reading.get("dates") or []
                 if _LABELLED[field].search(d.get("label") or "")), "")


def compared_fields(reading: dict) -> dict:
    """The part of one reading that is kept beside the document and compared with the other reading."""
    zone = reading.get("mrz") or {}
    return {"status": reading.get("status") or "not_read",
            "holder_name": reading.get("holder_name") or (reading.get("names") or [""])[0],
            "issue_date": date_field(reading, "issue_date"), "expiry_date": date_field(reading, "expiry_date"),
            "date_of_birth": date_field(reading, "date_of_birth"),
            "mrz_name": " ".join(x for x in (zone.get("given_names"), zone.get("surname")) if x),
            "mrz_expiry_date": zone.get("expiry_date") or ""}


def _same(field: str, a: str, b: str) -> bool:
    if "name" in field:      # the same words in any order, with accents and case set aside
        return sorted(tokens(a)) == sorted(tokens(b))
    return a.strip() == b.strip()


def combine_readings(first: dict, second: dict) -> dict:
    """One reading made from two separate readings of the same document.

    The result has the shape `read_document` gives, plus "readings" (the compared fields of both) and
    "agreement": {"status": "agree" | "disagree" | "one_reading", "disagreed": ["expiry date", ...]}. Where the
    two differ, the careful answer is kept: a name counts only if both readings saw it, a sign of editing or a
    sample mark counts if either did, and the document counts as photo identification only if both said so.
    Whether a disagreement holds the document is decided in checks.py, not here."""
    both = [first, second]
    read = [r for r in both if r.get("status") == "read"]
    if not read:
        return first if first.get("status") != "not_read" or second.get("status") == "not_read" else second
    out = dict(read[0])
    out["readings"] = [compared_fields(r) for r in both]
    if len(read) == 1:
        out["agreement"] = {"status": "one_reading", "disagreed": []}
        return out
    a, b = (compared_fields(r) for r in read)
    disagreed = [label for field, label in COMPARED if not _same(field, a[field], b[field])]
    other = read[1]
    seen_by_other = {tuple(sorted(tokens(n))) for n in other.get("names") or []}
    out["names"] = [n for n in out.get("names") or [] if tuple(sorted(tokens(n))) in seen_by_other]
    for key in ("presents_as_government_photo_id", "photo_present", "legible"):
        out[key] = bool(out.get(key)) and bool(other.get(key))
    for key in ("marked_sample", "signs_of_editing"):
        out[key] = bool(out.get(key)) or bool(other.get(key))
    kinds = list(out.get("concern_kinds") or [])
    concerns = list(out.get("concerns") or [])
    for text, kind in zip(other.get("concerns") or [], other.get("concern_kinds") or []):
        if kind not in kinds:        # a kind of doubt only the second reading raised is kept as well
            concerns.append(text)
            kinds.append(kind)
    out["concerns"], out["concern_kinds"] = concerns, kinds
    out["agreement"] = {"status": "disagree" if disagreed else "agree", "disagreed": disagreed}
    return out


def read_document(path: str | Path, kind: str = "other", model: str = "sonnet") -> dict:
    """Reads the image or PDF at `path` with a model and returns what is visible on it.

        {
          "status": "read",                  # "unreadable" when nothing could be made out,
                                             # "failed" when the model could not be reached (with "problem"),
                                             # "not_read" when there is no file to read
          "document_type": "payslip",
          "names": ["..."],                  # exactly as printed
          "addresses": [{"street", "city", "region", "postcode", "country", "whose"}],
          "dates": [{"label": "pay date", "value": "2014-03-28"}],
          "issuer": "...",
          "identifiers_present": ["employee number"],   # kinds only, never the number
          "legible": true,
          "concerns": ["..."],               # what a careful clerk would question, one sentence each; what the
                                             # first design of this function called tamper_flags
          "concern_kinds": ["editing"],      # one of CONCERN_KINDS (or "other") per concern, in the same order
          "presents_as_government_photo_id": true, "photo_present": true,
          "marked_sample": false, "signs_of_editing": false,
          "summary": "...",
          "holder_name": "...", "issue_date": "2023-05-08", "expiry_date": "2033-05-07", "date_of_birth": "...",
          "issuing_authority": "...", "issuing_country": "...",     # as printed; checks.py decides what they mean
          "mrz": {...} or None,              # the machine-readable lines parsed by mrz.py, numbers hidden
        }

    This is one reading. The server reads every document twice (reading.read_twice) and keeps the combined
    result of `combine_readings`, which adds "readings" and "agreement".

    `kind` is the kind the claimant chose (documents.KINDS); the model is told it, and nothing more about the
    claim. It never sees the register record. Callers must treat every key except "status" as optional.
    """
    path = Path(path)
    if not path.is_file():
        return {"status": "not_read"}
    prompt = READ_PROMPT.format(kind=KINDS.get(kind, KINDS["other"]).lower())
    failure: dict = {}
    for _ in range(2):   # a reading that fails for a passing reason is tried once more
        try:
            raw = llm.ask_json(prompt, files=[str(path)], model=model)
        except llm.ModelUnavailable as err:
            failure = {"status": "failed", "problem": str(err) if getattr(err, "for_screen", False) else
                       "The reading model is not available on this machine.",
                       "detail": mask_numbers(str(err))[:200]}
            continue
        except Exception as err:   # the answer was not JSON, or the model program stopped; `detail` is for the log
            failure = {"status": "failed", "problem": "The document could not be read this time.",
                       "detail": mask_numbers(f"{type(err).__name__}: {err}")[:200]}
            continue
        if isinstance(raw, dict):
            return clean_reading(raw)
        failure = {"status": "failed", "problem": "The document could not be read this time."}
    return failure
