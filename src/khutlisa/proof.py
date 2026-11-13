"""The proof file: does what was read from the claimant's documents tie them to the register record?

`build_proof` takes a claim, its documents (each with the reading documents.read_document made) and decides, for
every requirement in the claim's California checklist, whether it is satisfied, partly met or missing, which
document supports it, and which visible fact makes the tie. Every comparison here is plain code (the name helpers
in names.py and rapidfuzz). No model is asked anything.

Privacy: `record` may be the full register record, with the private owner's name, street and postcode. They are
used for comparing and never copied into the result. The result says whether they matched and shows the owner only
in the masked form the claim already holds. Words that appear in the result come from the claimant's own documents
and typed details, or from the public form of the record.
"""
from __future__ import annotations

import re
from datetime import date

from rapidfuzz import fuzz

from . import checks
from . import documents as docs
from .demo import SOURCE as DEMO_SOURCE, is_demonstration
from .match import street_matches
from .names import normalise, tokens

SATISFIED, PARTLY, MISSING = "satisfied", "partly", "missing"
_EXPIRY = re.compile(r"expir|valid (until|to|thru|through)|good (until|thru)", re.I)
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


# ---- comparisons ---------------------------------------------------------------------------------------------

def _same_word(a: str, b: str) -> bool:
    """Two name words are the same only when they are spelled the same once accents and case are set aside.
    A near spelling is not enough here: JUAN and JUANA, PAUL and PAULA, MARTIN and MARTINA are different
    people, often in the same family, and proof of identity must tell them apart."""
    return a == b


def _joined(words: list[str]) -> set[str]:
    """Each word, plus every pair of neighbours written as one ("DELA CRUZ" and "DELACRUZ" are one surname)."""
    return set(words) | {x + y for x, y in zip(words, words[1:])}


def compare_names(printed: str, wanted: str) -> str:
    """How well a name printed on a document covers a wanted name: "full", "partial" or "none".

    Order does not matter ("SANTOS MARIA L" and "Maria Luz Santos" are the same person) and a single letter is an
    initial. Words must otherwise be spelled the same; a surname written joined or split counts as the same."""
    want, have = tokens(wanted), tokens(printed)
    if not want or not have:
        return "none"
    words = [w for w in want if len(w) > 1]
    have_words = _joined([h for h in have if len(h) > 1])
    want_joined = _joined(words)
    have_letters = {h[0] for h in have}
    by_word = [w for w in words if w in have_words
               or any(j in have_words for j in want_joined if len(j) > len(w) and (j.startswith(w) or j.endswith(w)))]
    by_initial = [w for w in words if w not in by_word and w[0] in {h for h in have if len(h) == 1}]
    initials_ok = all(w in have_letters for w in want if len(w) == 1)
    if not words:
        return "full" if initials_ok else "none"
    if len(by_word) + len(by_initial) == len(words) and by_word and (len(by_word) >= 2 or len(words) == 1):
        return "full"
    return "partial" if by_word else "none"


def compare_with_mask(printed: str, masked: str) -> str:
    """The same question when only the masked owner ("S··· M··· L···") is known: does the printed name have a
    word of its own that starts with the first letter of each masked word? The mask carries first letters and
    nothing else (no lengths), so this is a weak check, used only when the full record is not at hand."""
    letters = [w[0].upper() for w in (masked or "").split() if w]
    have = [h[0] for h in tokens(printed)]
    if not letters or not have:
        return "none"
    hits = 0
    for first in letters:
        if first in have:
            have.remove(first)     # each printed word answers for one masked word only
            hits += 1
    return "full" if hits == len(letters) else "partial" if hits else "none"


def compare_organisation(texts: list[str], organisation: str) -> bool:
    want = normalise(organisation)
    for text in texts:
        have = normalise(text)
        if want and have and (fuzz.token_set_ratio(want, have) >= 88 or (len(want) >= 5 and want in have)
                              or (len(have) >= 5 and have in want)):
            return True
    return False


def _best(levels: list[tuple[str, str]]) -> tuple[str, str]:
    """The strongest (level, printed name) of several."""
    order = {"full": 2, "partial": 1, "none": 0}
    return max(levels, key=lambda x: order[x[0]], default=("none", ""))


def _address_line(a: dict) -> str:
    tail = " ".join(x for x in (a.get("region"), a.get("postcode")) if x)
    return ", ".join(x for x in (a.get("street"), a.get("city"), tail) if x)


def address_against_typed(address: dict, typed: str) -> bool:
    """Does an address printed on a document agree with the address the claimant typed as free text?"""
    want = normalise(typed)
    if not want:
        return False
    city, postcode, street = (normalise(address.get(k) or "") for k in ("city", "postcode", "street"))
    place = bool(postcode and postcode in want.split()) or bool(city and city in want)
    if not place:
        return False
    return not street or fuzz.token_set_ratio(street, want) >= 80 or fuzz.partial_ratio(street, want) >= 85


def address_against_record(address: dict, record: dict) -> set[str]:
    """Which parts of the record's reported address a printed address matches: "street", "postcode", "city"."""
    hit: set[str] = set()
    city, postcode, street, region = (normalise(address.get(k) or "") for k in ("city", "postcode", "street", "region"))
    r_city, r_post, r_street, r_region = (normalise(record.get(k) or "") for k in
                                          ("owner_city", "owner_postcode", "owner_street", "owner_region"))
    if city and r_city and fuzz.ratio(city, r_city) >= 90 and (not region or not r_region or region == r_region):
        hit.add("city")
    if postcode and r_post and postcode.replace(" ", "")[:5] == r_post.replace(" ", "")[:5]:
        hit.add("postcode")
    if street_agrees(street, r_street):
        hit.add("street")
    return hit


def street_agrees(given: str, on_record: str) -> bool:
    """The strict street rule (match.street_matches; the search itself never compares a street): the house number
    must be the same and at least two thirds of the words in the record's street name must be there. A lone
    number, a lone word or a unit never agrees, so the answer cannot be used to find an address out one piece at
    a time."""
    return street_matches(given, on_record)


def expired_dates(reading: dict, today: date) -> list[str]:
    out = []
    for d in reading.get("dates") or []:
        m = _ISO.search(d.get("value") or "")
        if m and _EXPIRY.search(d.get("label") or ""):
            try:
                if date(int(m[1]), int(m[2]), int(m[3])) < today:
                    out.append(d["value"])
            except ValueError:
                continue
    m = _ISO.fullmatch(reading.get("expiry_date") or "")     # the expiry date as its own field, when there is one
    if m and m[0] not in out:
        try:
            if date(int(m[1]), int(m[2]), int(m[3])) < today:
                out.append(m[0])
        except ValueError:
            pass
    return out


# ---- what each document shows --------------------------------------------------------------------------------

class _Seen:
    """Everything the comparisons found on one read document."""

    def __init__(self, doc: dict, claim: dict, record: dict | None, today: date, payer: bool = False):
        reading = doc.get("reading") or {}
        self.doc = doc
        self.payer = payer   # word everything for the office that decides, not for the claimant
        self.status = reading.get("status") or "not_read"
        self.read = self.status == "read"
        self.reading = reading
        claimant, public = claim["claimant"], claim["record"]
        names = list(reading.get("names") or [])
        # The main name field as a whole comes first: a passport prints the surname and the given names apart,
        # and neither half alone is the person's name.
        if reading.get("holder_name") and reading["holder_name"] not in names:
            names.insert(0, reading["holder_name"])
        self.names = names
        self.claim = claim
        self.private = record
        # On the sample register every document is a marked sample by design, so the mark alone is let through
        # there. Anywhere else a sample mark means the document proves nothing.
        self.sample_mode = is_demonstration(public.get("source"))
        self.weight = docs.WEIGHT.get(doc.get("kind") or "other", docs.ANYONE_COULD_MAKE_IT)
        self.organisation = bool(public.get("owner_is_organisation"))
        self.claimant_level, self.claimant_name = _best([(compare_names(n, claimant["name"]), n) for n in names])
        if self.organisation:
            texts = names + [reading.get("issuer") or "", reading.get("summary") or ""]
            self.owner_level = "full" if compare_organisation(texts, public.get("owner") or "") else "none"
            self.owner_name = public.get("owner") or ""
        elif record and record.get("owner_name"):
            self.owner_level, self.owner_name = _best([(compare_names(n, record["owner_name"]), n) for n in names])
        else:
            self.owner_level, self.owner_name = _best([(compare_with_mask(n, public.get("owner") or ""), n)
                                                       for n in names])
        self.private_record = bool(record)
        against = record or public
        self.current_address = next((a for a in reading.get("addresses") or []
                                     if a.get("whose") != "issuer" and address_against_typed(a, claimant["address"])),
                                    None)
        self.record_address, self.record_parts = None, set()
        for a in reading.get("addresses") or []:
            parts = address_against_record(a, against) if a.get("whose") != "issuer" else set()
            if len(parts) > len(self.record_parts):
                self.record_address, self.record_parts = a, parts
        self.holder = compare_organisation([reading.get("issuer") or ""], public.get("holder_name") or "") \
            if reading.get("issuer") and public.get("holder_name") else False
        self.expired = expired_dates(reading, today)
        # The checks code makes beside the reading (checks.py): dates, the name in two places, the issuer, and
        # whether two separate readings agree. A check that code cannot settle holds the document for a person.
        self.checks = checks.document_checks(doc, claim, today)
        self.held_reasons = [c["text"] for c in self.checks if c["status"] == checks.HELD]
        self.label = f"{doc.get('kind_label', 'Document').lower()} ({doc.get('filename', 'file')})"

    def faults(self) -> list[str]:
        """Reasons this document cannot be relied on, whatever it is offered for."""
        if self.status in ("reading", "not_read"):
            return ["It is still being read."]
        if self.status == "failed":
            return [(self.reading.get("problem") or "It could not be read.")
                    + ("" if self.payer else " Add it again to try once more.")]
        if self.status != "read":
            return ["Nothing could be read from it. A sharper, complete photo or scan is needed."]
        out = []
        if not self.reading.get("legible", True):
            out.append("The main text could not be read with confidence. A sharper photo or scan is needed.")
        if self.reading.get("signs_of_editing"):
            out.append("It shows signs of having been edited.")
        if self.reading.get("marked_sample") and not self.sample_mode:
            out.append("It is marked as a sample, so it cannot support a real claim.")
        out += [f"The reader questioned it: {text}" for text, kind in self.concerns() if self.blocks(kind)]
        out += [c["text"] for c in self.checks if c["blocks"]]
        out += [f"It is {checks.HELD_WORDS}. {text}" for text in self.held_reasons]
        return out

    def standing(self, supports: list[dict]) -> str:
        """Where the document stands, in words: held is its own answer, different from refused."""
        if self.status in ("reading", "not_read"):
            return "being read"
        if not self.read:
            return "not read"
        if self.held_reasons:
            return checks.HELD_WORDS
        if self.faults() or (supports and not any(e["settles"] for e in supports)):
            return "refused"
        return "accepted" if supports else "read"

    def concerns(self) -> list[tuple[str, str]]:
        """(sentence, kind) for everything the reader questioned. A reading stored before kinds were kept gets
        its kinds worked out from the words."""
        texts = list(self.reading.get("concerns") or [])
        kinds = list(self.reading.get("concern_kinds") or [])
        kinds += [("sample_mark" if docs._SAMPLE_WORDS.search(t) else "other") for t in texts[len(kinds):]]
        return list(zip(texts, kinds))

    def blocks(self, kind: str) -> bool:
        """Whether a concern of this kind stops the document from being relied on. An expiry is worked out from the
        dates in code. A sample mark is let through on the sample register only (and reported above elsewhere)."""
        if kind == "expired":
            return False
        if kind == "sample_mark":
            return False        # in real mode the `marked_sample` fault above already blocks; never say it twice
        return True

    def taints(self) -> list[str]:
        """Concerns that hold the whole file back until the document is removed: signs that it was altered,
        names that disagree, and a sample offered as proof of a real claim."""
        if not self.read:
            return []
        out = []
        if self.reading.get("signs_of_editing"):
            out.append("it shows signs of having been edited")
        out += [text[:1].lower() + text[1:].rstrip(".") for text, kind in self.concerns()
                if kind in ("editing", "name_mismatch")]
        if (self.reading.get("marked_sample") or any(k == "sample_mark" for _, k in self.concerns())) \
                and not self.sample_mode:
            out.append("it is marked as a sample")
        return out

    def is_government_photo_id(self) -> list[str]:
        """Why this document is not government photo identification, or [] when it is."""
        out = []
        if self.doc.get("kind") != "id":
            return ["It was not added as photo identification."]
        if not self.reading.get("presents_as_government_photo_id"):
            out.append("It does not present itself as identification issued by a government (a passport, a "
                       "national identity card or a driver licence).")
        if not self.reading.get("photo_present"):
            out.append("No photograph of the holder could be seen on it.")
        return out

    def dated(self) -> str | None:
        dates = [d for d in self.reading.get("dates") or [] if not _EXPIRY.search(d.get("label") or "")]
        if not dates:
            return None
        d = next((x for x in dates if re.search(r"(pay|bill|statement|issue)\w* date|^date|dated", x.get("label") or "", re.I)),
                 dates[0])
        return f"It is dated {d['value']}" + (f" ({d['label'].lower()})." if d.get("label") else ".")


def _owner_shown(claim: dict) -> str:
    return claim["record"].get("owner") or ""


def _name_fact(seen: _Seen, claim: dict, whose: str) -> tuple[list[str], list[str]]:
    """(facts, problems) for the name on a document against the claimant ("claimant") or the owner ("owner")."""
    if whose == "claimant":
        level, printed, wanted = seen.claimant_level, seen.claimant_name, claim["claimant"]["name"]
        target = f"the claimant's name, {wanted}" if seen.payer else f"the name you gave, {wanted}"
    else:
        level, printed = seen.owner_level, seen.owner_name
        shown = _owner_shown(claim)
        if seen.organisation:
            if level == "full":
                return [f"It names {shown}, the organisation that owns the money."], []
            return [], [f"It does not name {shown}, the organisation that owns the money."]
        target = f"the owner's name on the record, shown here as {shown}"
        if not seen.private_record:
            target = f"the masked owner's name on the record, {shown}, by first letters"
    if level == "full":
        return [f"The name on it, {printed}, matches {target}."], []
    if level == "partial":
        extra = " The record also carries a name the document does not show." if whose == "owner" else ""
        return [], [f"The name on it, {printed}, only partly matches {target}.{extra}"]
    if not seen.names:
        return [], ["No name could be read on it."]
    return [], [f"The name on it, {seen.names[0]}, does not match {target}."]


# ---- the requirements ----------------------------------------------------------------------------------------

def _gap_words(key: str, claim: dict, abroad: bool, payer: bool = False) -> tuple[str, str]:
    """(what is missing, how to close it) for a requirement with no usable document. The second part is advice
    to the claimant and is not shown to a payer."""
    your = "the claimant's" if payer else "your"
    record = claim["record"]
    city = (record.get("owner_city") or "").title()
    where = f"the {city} address" if city else "the address"
    heir = claim["claimant"]["relationship"] == "heir"
    return {
        "photo_id": ("No photo identification has been added.",
                     "A colour copy of the first and last page of your valid passport would close it." if abroad else
                     "A copy of your current driver licence, state identity card or passport would close it."),
        "tax_number": ("No document shows a Social Security or taxpayer number.",
                       "A Social Security card or an ITIN letter would close it. If you have no United States tax "
                       "number, a completed and signed IRS form W-8BEN closes it instead."
                       if not record.get("owner_is_organisation") or heir else
                       "An IRS letter confirming the employer identification number, or a form 1098 or 1099, "
                       "would close it."),
        "current_address": (f"No document shows {your} current address.",
                            "A recent utility bill, bank statement or payslip that shows your name and the "
                            "address you gave would close it."),
        "reported_address": (f"No document shows {where} the money was reported under.",
                             "A bank statement, utility bill or lease from that address would close it."),
        "death_certificate": ("No death certificate for the owner has been added.",
                              "All pages of the certified final death certificate would close it."),
        "heirship": ("No document shows that the claimant inherits from the owner." if payer else
                     "No document shows that you inherit from the owner.",
                     "A court's final decree of distribution, letters testamentary, or the signed will with "
                     "California's declaration under Probate Code section 13101 would close it."),
        "authority": ("No document shows that the signer may sign for the organisation.",
                      "A corporate resolution, the latest Statement of Information, or a letter of authorisation "
                      "from an officer would close it."),
    }.get(key, ("This document has not been added.", "Adding it would close this."))


def _weigh(key: str, seen: _Seen, claim: dict) -> tuple[bool, list[str], list[str]]:
    """Whether one document settles one requirement: (settles it, visible facts, problems)."""
    facts: list[str] = []
    problems = seen.faults()
    if not seen.read:
        return False, facts, problems
    gave = "the claimant's current address" if seen.payer else "the current address you gave"
    heir = claim["claimant"]["relationship"] == "heir"
    business = seen.organisation and not heir

    def name(whose: str, needed: bool = True) -> bool:
        f, p = _name_fact(seen, claim, whose)
        facts.extend(f)
        if needed:
            problems.extend(p)
        return bool(f)

    if key == "photo_id":
        name("claimant")
        problems.extend(seen.is_government_photo_id())
        problems.extend(f"It expired on {when}. California asks for current identification." for when in seen.expired)
        if not heir and not business:
            name("owner", needed=False)
    elif key == "tax_number":
        name("owner" if business else "claimant")
    elif key == "current_address":
        name("owner" if business else "claimant")
        if seen.current_address:
            facts.append(f"The address on it, {_address_line(seen.current_address)}, is {gave}.")
        else:
            shown = next((_address_line(a) for a in seen.reading.get("addresses") or [] if a.get("whose") != "issuer"), "")
            problems.append(f"The address on it, {shown}, is not {gave}." if shown else
                            "No address could be read on it.")
    elif key == "reported_address":
        name("owner")
        record = claim["record"]
        place = ", ".join(x for x in ((record.get("owner_city") or "").title(), record.get("owner_region")) if x)
        parts = seen.record_parts
        if parts:
            printed = _address_line(seen.record_address)
            if "street" in parts:
                facts.append(f"The address on it, {printed}, matches the street and city the money was reported under.")
            elif "postcode" in parts:
                facts.append(f"The address on it, {printed}, matches the city and postcode the money was reported "
                             f"under ({place} {seen.record_address.get('postcode', '')[:5]}).")
            elif seen.private_record:
                problems.append(f"The address on it, {printed}, is in {place}, the record's city, but its street "
                                "and postcode are not the ones on the record.")
            else:
                facts.append(f"The address on it, {printed}, is in {place}, the city the money was reported under.")
        else:
            problems.append(f"It does not show the {place or 'reported'} address the money was reported under.")
        if seen.holder:
            facts.append(f"It was issued by {seen.reading['issuer']}, the holder that reported the money.")
        when = seen.dated()
        if when:
            facts.append(when)
    elif key == "death_certificate":
        name("owner")
    elif key == "heirship":
        name("claimant")
        name("owner", needed=False)
    elif key == "authority":
        name("owner")
        name("claimant", needed=False)
    return not problems, facts, problems


def build_proof(claim: dict, documents: list[dict] | None = None, record: dict | None = None,
                today: date | None = None, payer: bool = False) -> dict:
    """The proof result for one claim. `documents` defaults to the claim's own. `record` is the full register
    record when the caller has it; without it the name is compared with the masked owner and only the city of the
    address can be compared. `payer` words every sentence for the office that decides the claim ("the claimant's
    name") instead of for the claimant ("the name you gave")."""
    from .claims import checklist   # claims.py does not import this module, so there is no circle

    documents = claim.get("documents", []) if documents is None else documents
    today = today or date.today()
    need = checklist(claim)
    claimant = claim["claimant"]
    abroad = (claimant.get("country") or "").upper() not in ("", "US")
    seen = [_Seen(d, claim, record, today, payer) for d in documents]
    per_doc: dict[str, list[dict]] = {d["id"]: [] for d in documents}
    requirements, gaps = [], []
    business = bool(claim["record"].get("owner_is_organisation")) and claimant["relationship"] != "heir"
    photo_id_settled = False     # the photo identification comes first in every checklist

    for item in need["items"]:
        key = item["key"]
        # The link to the reported address can come from any document that shows it, whatever it was added as.
        offered = seen if key == "reported_address" else [s for s in seen if s.doc["kind"] in item["kinds"]]
        supports = []
        for s in offered:
            settles, facts, problems = _weigh(key, s, claim)
            if key == "tax_number" and settles and abroad and not business:
                # California asks a foreign citizen with no United States tax number for a signed form W-8BEN
                # together with the passport copy, so a taxpayer document from abroad never stands alone.
                if photo_id_settled:
                    facts.append("It counts together with the photo identification. If this is not a Social "
                                 "Security card or an ITIN letter, California asks for a signed form W-8BEN with "
                                 "the passport copy, and the signed form goes in the packet.")
                else:
                    settles = False
                    problems.append(" ".join(facts) + " Even so, a taxpayer document from outside the United "
                                    "States counts only together with valid photo identification, and none has "
                                    "been accepted so far.")
            if key == "reported_address" and s.doc["kind"] not in item["kinds"] and not (s.record_parts or s.holder):
                continue   # a document added for something else that says nothing about this address or holder
            entry = {"document_id": s.doc["id"], "filename": s.doc["filename"], "kind_label": s.doc["kind_label"],
                     "settles": settles, "facts": facts, "problems": problems}
            supports.append(entry)
            per_doc[s.doc["id"]].append({"key": key, "title": item["title"], "settles": settles, "facts": facts,
                                         "problems": problems})
        status = SATISFIED if any(e["settles"] for e in supports) else PARTLY if supports else MISSING
        if key == "photo_id":
            photo_id_settled = status == SATISFIED
        title = item.get("payer_title", item["title"]) if payer else item["title"]
        requirements.append({"key": key, "title": title, "required": item["required"], "status": status,
                             "supports": supports})
        if status != SATISFIED:
            what, how = _gap_words(key, claim, abroad, payer)
            if status == PARTLY:
                best = max(supports, key=lambda e: len(e["facts"]) - len(e["problems"]))
                what = (f"The {best['kind_label'].lower()} {'the claimant' if payer else 'you'} added "
                        f"({best['filename']}) does not settle \"{title}\". " + " ".join(best["problems"]))
            gaps.append({"key": key, "title": item["title"], "required": item["required"], "text": what, "how": how})

    # The tie to the record itself. For a person claiming their own money it may rest only on government photo
    # identification that carries the name on the record, or on a civil or court record that links that name to
    # the name on the claimant's photo identification (a marriage certificate, a legal change of name). A
    # payslip, a letter, a card with a name on it or any other sheet cannot make it: anyone could prepare one.
    # (An heir's death certificate and an organisation's proof of authority tie those claims.)
    link = None
    person_owner = claimant["relationship"] == "self" and not claim["record"].get("owner_is_organisation")
    if person_owner:
        shown = _owner_shown(claim)
        whose = "the claimant's" if payer else "your"
        usable = [s for s in seen if s.read and not s.faults()]
        ids = [s for s in usable if not s.is_government_photo_id() and not s.expired and s.claimant_level == "full"]
        direct = [s for s in ids if s.owner_level == "full"]
        bridges = []
        if ids and not direct:
            # the document must carry both names: the one on the record and the one on the identification
            bridges = [s for s in usable if s.weight == docs.NAME_LINK and s.owner_level == "full"
                       and s.claimant_level == "full"]
        if direct:
            link = {"status": "matched", "document_ids": [s.doc["id"] for s in direct], "rests_on": docs.GOVERNMENT_PHOTO_ID,
                    "text": f"The name on the record, shown here as {shown}, is on "
                            f"{whose} government photo identification "
                            f"({', '.join(s.doc['filename'] for s in direct)})."}
        elif bridges:
            link = {"status": "matched", "document_ids": [s.doc["id"] for s in bridges + ids], "rests_on": docs.NAME_LINK,
                    "text": f"The name on the record, shown here as {shown}, is linked to "
                            f"{whose} present name by "
                            f"{bridges[0].doc['kind_label'].lower()} ({bridges[0].doc['filename']}), which shows both "
                            f"names, and the photo identification ({ids[0].doc['filename']}) is in the present name."}
        else:
            elsewhere = [s for s in usable if s.owner_level == "full" and s not in ids]
            text = (f"No government photo identification read so far carries the name on the record, shown here as "
                    f"{shown}.")
            if elsewhere:
                text += (f" The name is on {', '.join(s.doc['filename'] for s in elsewhere)}, but a document of "
                         "that kind cannot tie a person to a record, because anyone could prepare one.")
            link = {"status": "not shown", "document_ids": [], "rests_on": None, "text": text}
            gaps.append({"key": "record_name", "title": "The name on the record", "required": True,
                         "text": text,
                         "how": "Photo identification issued by a government, in the name on the record, would "
                                "close it. If you used another name then, add a marriage certificate or a "
                                "court's change-of-name order that shows both names, with photo identification "
                                "in your present name."})

    # A document that looks altered, or a sample offered as real proof, holds the whole file back until it is
    # taken out. Showing the concern and carrying on would let one bad document hide behind good ones.
    for s in seen:
        for why in s.taints():
            gaps.append({"key": "concern", "title": "A document that cannot be relied on", "required": True,
                         "text": f"The {s.doc.get('kind_label', 'document').lower()} ({s.doc['filename']}) cannot be "
                                 f"relied on: {why}.",
                         "how": "Remove it from the proof file, or replace it with a clean original."})

    # A document held for a person to look at is neither accepted nor refused. It settles nothing by itself and
    # the file is not ready while it is in it, so that the open question cannot hide behind other documents.
    held = [{"document_id": s.doc["id"], "filename": s.doc["filename"], "kind_label": s.doc.get("kind_label", "Document"),
             "reasons": s.held_reasons} for s in seen if s.held_reasons]
    for h in held:
        gaps.append({"key": "held", "title": "A document held for a person to look at", "required": True,
                     "text": f"The {h['kind_label'].lower()} ({h['filename']}) is {checks.HELD_WORDS}. "
                             + " ".join(h["reasons"]),
                     "how": "It stays held until a person has looked at it. Removing it and adding a document "
                            "that passes the checks also closes this."})

    blocking = [g for g in gaps if g["required"]]
    waiting = [s for s in seen if s.status in ("reading", "not_read")]
    ready = not blocking
    required = [r for r in requirements if r["required"]]
    done = [r for r in required if r["status"] == SATISFIED]
    if ready:
        reasons = [f"All {len(required)} required documents have been read, and each one ties to the claimant"
                   + (". The tie to the record rests on " + ("government photo identification."
                      if link["rests_on"] == docs.GOVERNMENT_PHOTO_ID else
                      "a civil or court record that links the two names, with photo identification.")
                      if person_owner else ".")]
    else:
        reasons = [g["text"] for g in blocking]
    samples = [s for s in seen if s.reading.get("marked_sample")]
    summary = f"{len(done)} of {len(required)} required items are proven by a document that was read."
    if waiting:
        summary += f" {len(waiting)} {'document is' if len(waiting) == 1 else 'documents are'} still being read."
    if held:
        summary += f" {len(held)} {'document is' if len(held) == 1 else 'documents are'} {checks.HELD_WORDS}."
    # On a demonstration record the screen says once, in its top bar, that the person and the documents are a
    # demonstration. Anywhere else a sample among the documents is said here.
    if samples and claim["record"].get("source") != DEMO_SOURCE:
        summary += (f" {len(samples)} {'document is' if len(samples) == 1 else 'documents are'} marked as "
                    "a sample, so this is a demonstration and not proof of a real claim.")

    cards = []
    for s in seen:
        concerns = [text for text, kind in s.concerns() if not (s.sample_mode and kind == "sample_mark")]
        concerns += [f"It expired on {when}." for when in s.expired if not any(when in c for c in concerns)]
        cards.append({"id": s.doc["id"], "filename": s.doc["filename"], "kind_label": s.doc["kind_label"],
                      "weight": s.weight, "status": s.status, "supports": per_doc[s.doc["id"]], "concerns": concerns,
                      "holds_the_file_back": bool(s.taints()),
                      "marked_sample": bool(s.reading.get("marked_sample")),
                      "standing": s.standing(per_doc[s.doc["id"]]), "read": checks.read_how_often(s.reading),
                      "checks": [{k: c[k] for k in ("key", "title", "status", "text")} for c in s.checks],
                      "held": bool(s.held_reasons), "held_reasons": s.held_reasons})
    return {"assessed": True, "ready": ready, "readiness": "ready" if ready else "not ready",
            # the same verdict with held told apart from not ready
            "status": "ready" if ready else checks.HELD_WORDS if held else "not ready", "held": held,
            "remaining_risk": checks.REMAINING_RISK, "decided_by": checks.DECIDED_BY, "reasons": reasons,
            "summary": summary, "required": len(required), "satisfied": len(done), "reading": len(waiting),
            "requirements": requirements, "record_link": link, "gaps": gaps, "documents": cards,
            "samples": len(samples),
            "compared_with": "the full register record" if record else "the public form of the record"}
