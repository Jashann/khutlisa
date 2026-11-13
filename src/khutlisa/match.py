"""Finds a person in the registers and says, with the reasons, how well each record fits what they told us.

Two things come back for every record. The match strength number (0 to 1) is a sum of fixed points for named
pieces of evidence, less fixed points for named doubts. It is used to put results in order and is not a measured
chance of anything. The label, "strong" or "possible", is a rule over the same evidence: see `strength_of`.

The search never looks at a street. Anyone can search, so a search that answered differently for the right street
would tell a stranger whether a private person lived there. `compare_streets` and `street_matches` are kept for the
one place a street is compared: inside a claim, once photo identification has been read (claims_api.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .names import (DROPPABLE, NOISE, ORG_WORDS, PARTICLES, Person, droppable_rest, is_organisation, near_spelling,
                    near_spelling_pattern, nickname_forms, normalise, phonetic, tokens)


@dataclass
class Place:
    """Somewhere the person lived or worked."""
    city: str = ""
    region: str = ""
    postcode: str = ""
    country: str = ""
    street: str = ""


@dataclass
class History:
    person: Person
    places: list[Place] = field(default_factory=list)
    employers: list[str] = field(default_factory=list)     # also banks, insurers, landlords, schools
    current_country: str = ""


STRONG = "strong"
POSSIBLE = "possible"
# The one sentence shown on screen. `strength_of` is the rule itself.
MAX_TIE_ADDRESSES = 2
# A name counts as very common when records that carry it in full sit in more than this many different places (a
# place is a city with a postcode). It is the top step of `crowd_cap`.
COMMON_NAME_PLACES = 60
STRENGTH_RULE = ("A match is strong when the family name and a given name match in full and one more thing ties "
                 "the record to you: a holder you named together with the postcode or a second given name, or two "
                 "of your given names in full together with the postcode. A tie stops counting when it points at "
                 f"more than two different addresses. When the name is very common (found in more than "
                 f"{COMMON_NAME_PLACES} different places), a holder that reports a very large share of the "
                 "register does not count as a tie. The search never uses a street: a street you gave is compared "
                 "with the record only inside a claim, after photo identification has been read. Everything else, "
                 "such as a name with only a city or a postcode, is a possible match.")
# The one line every strong match carries, on its card and in the API reply.
STRONG_NOTE = ("This label only sorts the search results. The proof file, not this label, decides whether the "
               "money is paid.")


@dataclass
class Match:
    record: dict
    score: float                 # the match strength number: a sum of fixed points, used for ordering only
    reasons: list[str]
    doubts: list[str]
    strength: str = POSSIBLE     # "strong" or "possible", decided by strength_of
    evidence: dict = field(default_factory=dict)


def strength_of(evidence: dict) -> str:
    """The whole rule for the label. Returns "strong" or "possible", and nothing else.

    A record is "strong" only when BOTH of these hold:

    1. The name matches. The family name matches (exactly, apart from a particle, with a small spelling difference
       or by sound) AND a given name matches in full. A near spelling or a familiar form of a given name (one
       letter different, or BILL for WILLIAM) never counts here, and neither does an initial: such a record is
       found and listed as "possible", and the claim's proof file settles whose it is. (A near spelling used to
       count when a street also matched. The search no longer looks at streets, so nothing stands in for the
       full given name.) For an organisation searched by its own name, the whole organisation name must match.
    2. At least one further tie exists:
       (a) the holder that reported the money is an organisation they named (see `names_holder`), AND the
           record's postcode is one they gave or two given names match in full;
       (b) two given names match in full AND the record's postcode is one they gave.
       Both ties stop counting when the records they tie in one search sit at more than two different addresses
       (`tie_addresses`, counted in `find`), because one person is seldom behind them all.
       Tie (a) also stops counting when BOTH of these hold: the holder is one of the holders that report a very
       large share of the register (`holder_generic`, see `is_generic_holder`), and the name is very common
       (`name_places`, counted in `find`, is more than COMMON_NAME_PLACES). A very large bank and a very common
       name in a big-city postcode meet by chance.

    A street is not evidence here, whatever the evidence says: `find` and `score` never set one, and a `street`
    key passed in by hand is ignored. Everything else is "possible". A name with a city, a name with a postcode,
    and a name with a holder are each "possible" however many points they have: the points order the results and
    never decide the label.
    """
    return STRONG if tie_of(evidence) else POSSIBLE


def tie_of(evidence: dict) -> str:
    """Which tie makes a record strong, as the words of a reason, or "" when none does. `strength_of` is this."""
    family = bool(evidence.get("family"))
    postcode = bool(evidence.get("postcode"))
    full = int(evidence.get("given_full") or 0)
    name = (family and full >= 1) or bool(evidence.get("organisation_named"))
    if evidence.get("organisation") and not evidence.get("organisation_named"):
        name = False
    if not name or int(evidence.get("tie_addresses") or 1) > MAX_TIE_ADDRESSES:
        return ""
    chance = bool(evidence.get("holder_generic")) and int(evidence.get("name_places") or 0) > COMMON_NAME_PLACES
    if evidence.get("holder") and not chance and (postcode or full >= 2):
        return ("the holder they named together with the postcode they gave" if postcode
                else "the holder they named together with two given names in full")
    if full >= 2 and postcode:
        return "two given names in full together with the postcode they gave"
    return ""


def _tie_reason(tie: str) -> str:
    return f"what makes this a strong match: {tie}"


# ---- streets ----

_UNIT_WORDS = {"APT", "APARTMENT", "UNIT", "STE", "SUITE", "BLDG", "BUILDING", "FL", "FLOOR", "RM", "ROOM", "SPC",
               "SPACE", "LOT", "TRLR", "TRAILER", "NO", "NUM", "NUMBER", "DEPT", "PH", "PMB"}
_STREET_FILLER = {"ST", "STREET", "AVE", "AV", "AVENUE", "RD", "ROAD", "BLVD", "BOULEVARD", "DR", "DRIVE", "LN",
                  "LANE", "CT", "COURT", "PL", "PLACE", "WAY", "TER", "TERRACE", "CIR", "CIRCLE", "HWY", "HIGHWAY",
                  "PKWY", "PARKWAY", "SQ", "SQUARE", "TRL", "TRAIL", "ROW", "WALK", "CALLE", "AVENIDA", "CARRERA",
                  "RUE", "N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST",
                  "PO", "POB", "BOX", "POST", "OFFICE", "APARTADO", "POSTAL", "CO", "C", "O"}
_HOUSE_NUMBER = re.compile(r"^\d+[A-Z]?$")


def street_parts(street: str) -> tuple[str, list[str]]:
    """Splits a street line into its house number and its street-name words.

    Unit parts ("APT 5", "UNIT 12B"), suffix words (ST, AVE, RD and the like), compass points and post-box words
    are left out, so '4417 TAMARACK HOLLOW RD APT 5' gives ('4417', ['TAMARACK', 'HOLLOW']) and 'PO BOX 5512'
    gives ('5512', []).
    """
    toks = normalise(street).split()
    kept: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] in _UNIT_WORDS:
            i += 2 if i + 1 < len(toks) and (any(c.isdigit() for c in toks[i + 1]) or len(toks[i + 1]) <= 2) else 1
            continue
        kept.append(toks[i]); i += 1
    number = next((t for t in kept if _HOUSE_NUMBER.match(t)), "")
    words = [t for t in kept if not _HOUSE_NUMBER.match(t) and t not in _STREET_FILLER and len(t) >= 2]
    return number, words


def _same_word(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 5 and Levenshtein.distance(a, b, score_cutoff=1) <= 1)


def street_matches(typed: str, on_record: str, also_typed: tuple[str, ...] = ()) -> bool:
    """The strict street rule. The search does not call it; a claim and the proof file do. True only when ALL of
    these hold:

    - both streets have a house number and the two numbers are the same;
    - the record's street has at least one street-name word, and at least two thirds of those words are in the
      street the person typed (a word of five letters or more may be one letter off);
    - at least half of the street-name words the person typed are in the record's street, so a long list of
      guesses does not pass. Words of the city they typed (`also_typed`) are not counted against them.

    A house number alone, one word of a longer street name, a unit ("APT 5") alone, or a post-box number never
    confirm. The answer is a plain yes or no; nothing from the record's street is ever put into a reason.
    """
    number, words = street_parts(typed)
    r_number, r_words = street_parts(on_record)
    if not number or number != r_number or not words or not r_words:
        return False
    hits = sum(1 for r in r_words if any(_same_word(r, w) for w in words))
    if hits == 0 or hits * 3 < len(r_words) * 2:
        return False
    mine = [w for w in words if w not in also_typed]
    back = sum(1 for w in mine if any(_same_word(r, w) for r in r_words))
    return back * 2 >= len(mine)


def compare_streets(places: list, record: dict) -> str:
    """How the streets a person gave stand against the street on one record. For an opened claim only: the search
    never calls this. `places` are the places they gave, as `Place` objects or plain dicts.

    Returns "not_given" (they gave no street), "no_street_on_record", "matches" or "does_not_match". A street
    counts only in the town it was given for: where they named a city or a postcode with it, one of the two must
    agree with the record. The answer is one word; nothing from the record's street is in it.
    """
    def part(place, key: str) -> str:
        return normalise((place.get(key) if isinstance(place, dict) else getattr(place, key, "")) or "")

    given = [p for p in places if part(p, "street")]
    if not given:
        return "not_given"
    on_record = record.get("owner_street") or ""
    if not street_parts(on_record)[0] and not street_parts(on_record)[1]:
        return "no_street_on_record"
    rc, rr, rz = (normalise(record.get(k) or "") for k in ("owner_city", "owner_region", "owner_postcode"))
    for p in given:
        city, region, zc = part(p, "city"), part(p, "region"), part(p, "postcode")
        zip_hit = bool(zc and rz and rz[:5] == zc[:5])
        city_hit = bool(city and rc and fuzz.ratio(city, rc) >= 90 and (not region or not rr or region == rr))
        if (zip_hit or city_hit or not (zc or city)) and \
                street_matches(part(p, "street"), on_record, tuple(city.split() + region.split() + zc.split())):
            return "matches"
    return "does_not_match"


# ---- holders ----

# Words so many holders share that they name nobody ("BANK", "CREDIT UNION", "PAYROLL SERVICES").
_GENERIC_HOLDER = ORG_WORDS | NOISE | {
    "NA", "FSB", "UNION", "CREDIT", "SAVINGS", "LOAN", "FINANCIAL", "FINANCE", "NATIONAL", "FEDERAL", "FIRST",
    "AMERICAN", "AMERICA", "UNITED", "GENERAL", "INTERNATIONAL", "GLOBAL", "MANAGEMENT", "HOLDINGS", "ENTERPRISES",
    "INDUSTRIES", "SOLUTIONS", "TECHNOLOGIES", "TECHNOLOGY", "ASSOCIATES", "MORTGAGE", "LIFE", "MUTUAL",
    "SECURITIES", "INVESTMENTS", "ENERGY", "ELECTRIC", "GAS", "WATER", "POWER", "COMMUNICATIONS", "WIRELESS",
    "STORES", "STORE", "MARKET", "MARKETS", "RESTAURANT", "RESTAURANTS", "PROPERTIES", "REALTY", "APARTMENTS",
    "PAYROLL", "HOSPITALS", "MEDICAL", "HEALTH", "HEALTHCARE", "CENTER", "CENTRE", "CLINIC", "SYSTEMS", "SYSTEM",
    "CALIFORNIA", "PACIFIC", "WESTERN", "SOUTHERN", "NORTHERN", "EASTERN", "CENTRAL", "USA", "US", "SERVICE",
    "INS", "ASSURANCE", "CASUALTY", "TITLE", "ESCROW", "AGENCY", "STAFFING", "TEMPORARY", "RETAIL", "WHOLESALE"}


def names_holder(typed: str, holder: str) -> bool:
    """True when an organisation the person typed names the record's holder.

    Words that many holders share (BANK, CREDIT, UNION, INC, PAYROLL and so on) are set aside. What is left must
    be at least one word, and at least half of those words must be in the holder's name. If nothing is left
    ("Bank of America", "State Fund"), the typed words must be the holder's whole name or its opening words, and
    be two words or more.
    """
    t, h = normalise(typed).split(), normalise(holder).split()
    if not t or not h:
        return False
    marks = [w for w in t if w not in _GENERIC_HOLDER and len(w) >= 3]
    if marks:
        hits = sum(1 for w in marks if any(_same_word(w, x) for x in h))
        return hits >= 1 and hits * 2 >= len(marks)
    return len(t) >= 2 and h[:len(t)] == t


# The holders that report a very large share of the register, under the key `holder_key` gives each. The file is
# written from the register by scripts/make_generic_holders.py and holds organisation names and counts only.
GENERIC_HOLDERS_PATH = Path(__file__).with_name("generic_holders.json")


_LEGAL_FORM = NOISE | {"INC", "INCORPORATED", "LLC", "LLP", "LP", "CORP", "CORPORATION", "CO", "COMPANY", "LTD",
                       "LIMITED", "NA", "FSB", "DBA", "FKA"}
_N_A = re.compile(r"\bN A\b")


def holder_key(holder: str) -> str:
    """One key for the ways a holder is written ("WELLS FARGO BANK NA", "WELLS FARGO FINANCIAL (APECS 1009)"):
    its first two words, once numbers and words for the legal form (INC, CO, NA, THE, OF and the like) are left
    out. Both of those are "WELLS FARGO". Two words keep the branches and funds of one holder together; they
    also put unrelated holders that open with the same place name ("SAN DIEGO ...") under one key, which only
    ever makes the rule that uses this more careful."""
    words = [w for w in _N_A.sub(" ", normalise(holder)).split() if not w.isdigit() and w not in _LEGAL_FORM]
    return " ".join(words[:2])


def _generic_holder_keys() -> frozenset[str]:
    try:
        return frozenset(h["key"] for h in json.loads(GENERIC_HOLDERS_PATH.read_text())["holders"])
    except (OSError, ValueError, KeyError):
        return frozenset()


GENERIC_HOLDER_KEYS = _generic_holder_keys()


def is_generic_holder(holder: str) -> bool:
    """True for a holder that reports a very large share of the register: at least one owner record in a thousand
    under its key when generic_holders.json was made. Naming such a holder says little about who the owner is."""
    key = holder_key(holder)
    return bool(key) and key in GENERIC_HOLDER_KEYS


# ---- names ----

@dataclass
class _Asked:
    """What the person said, worked out once per search."""
    given: list[str]
    wholes: set[str]
    cores: set[str]
    family_sounds: set[str]
    organisation: bool
    places: list[tuple[str, str, str]]     # city, region, postcode. A street they gave is left out on purpose.
    holders: list[str]
    country: str


def _asked(history: History) -> _Asked:
    cached = history.__dict__.get("_asked_cache")
    key = (tuple(history.person.given), tuple(history.person.family), tuple(history.person.aliases),
           tuple((pl.city, pl.region, pl.postcode, pl.country) for pl in history.places), tuple(history.employers),
           history.current_country)
    if cached and cached[0] == key:
        return cached[1]
    p = history.person
    wholes, cores = p.family_wholes(), p.family_cores()
    places = []
    for pl in history.places:
        # A place that is nothing but a street is no place at all for the search, so a street sent on its own
        # changes nothing, not even the doubt about a record being somewhere they did not mention.
        if normalise(pl.city) or normalise(pl.region) or normalise(pl.postcode) or normalise(pl.country):
            places.append((normalise(pl.city), normalise(pl.region), normalise(pl.postcode)))
    asked = _Asked(given=sorted(p.given_keys()), wholes=wholes, cores=cores,
                   family_sounds={phonetic(k) for k in wholes | cores} - {""},
                   organisation=is_organisation(" ".join(p.family)), places=places,
                   holders=[e for e in history.employers if normalise(e)], country=normalise(history.current_country))
    history.__dict__["_asked_cache"] = (key, asked)
    return asked


def given_kind(typed: str, toks: list[str]) -> str:
    """How one typed given name is found among a record's words: "full", "close", "initial" or "".

    "full" is the same word. "close" is a near spelling (exactly one letter changed, dropped or added, for a typed
    name of four letters or more) or a familiar form from the nickname table, in either direction. "initial" is a
    single letter that starts the typed name.
    """
    if typed in toks:
        return "full"
    forms = nickname_forms(typed)
    if any(t in forms or near_spelling(typed, t) for t in toks if len(t) > 1):
        return "close"
    if any(len(t) == 1 and t == typed[0] for t in toks):
        return "initial"
    return ""


def _record_family_forms(otoks: list[str]) -> tuple[set[str], set[str], set[str]]:
    """The record's words as family names: words standing alone, words that follow a particle ('CRUZ' in
    'DE LA CRUZ'), and joined forms ('DELACRUZ', two neighbouring words as one, all words as one)."""
    plain, after, joined = set(), set(), set()
    run: list[str] = []
    for t in otoks:
        if t in PARTICLES:
            run.append(t)
            if len(t) > 1:
                plain.add(t)
            continue
        if len(t) > 1:
            if run:
                after.add(t)
                joined.update("".join(run[i:]) + t for i in range(len(run)))
            else:
                plain.add(t)
        run = []
    joined.update(a + b for a, b in zip(otoks, otoks[1:]))
    joined.add("".join(otoks))
    return plain, after, joined


def _family_evidence(a: _Asked, otoks: list[str]) -> tuple[float, str]:
    """Points and the reason for the family name, or (0, "") when it does not match."""
    plain, after, joined = _record_family_forms(otoks)
    if a.wholes & (plain | joined):
        return 0.30, "family name matches exactly"
    rests = {droppable_rest(t) for t in plain} - {""}
    if (a.wholes & (after | rests)) or (a.cores & (plain | after)):
        return 0.28, "family name matches apart from a particle (such as DE LA)"
    mine = a.wholes | a.cores
    theirs = plain | after | joined
    if any(len(k) >= 4 and len(t) >= 4 and abs(len(k) - len(t)) <= 2 and fuzz.ratio(k, t, score_cutoff=85) >= 85
           for k in mine for t in theirs):
        return 0.22, "family name matches with a spelling difference"
    if a.family_sounds & {phonetic(t) for t in theirs}:
        return 0.20, "family name is spelled differently but sounds the same"
    return 0.0, ""


def _explained(t: str, a: _Asked) -> bool:
    """True when a word on the record is accounted for by a name the person gave."""
    if t in PARTICLES or phonetic(t) in a.family_sounds or (a.organisation and t in ORG_WORDS):
        return True
    if any(g == t or t in nickname_forms(g) or near_spelling(g, t) for g in a.given):
        return True
    mine = a.wholes | a.cores
    return droppable_rest(t) in mine or any(t == k or (len(t) >= 4 and t in k) or fuzz.ratio(t, k, score_cutoff=85) >= 85
                                            for k in mine)


def score(record: dict, history: History) -> Match:
    """The match strength number for one record, from 0 to 1, with the label.

    The number is a plain sum: fixed points are added for each named piece of evidence (family name, given names,
    postcode or city, a holder they named) and taken away for each named doubt. Every point is listed in
    `reasons` or `doubts`. It orders the results. It was not fitted to labelled data and is not a probability.
    No reason or doubt quotes the record's name or street, and the record's street is not read here at all: the
    result is the same whatever street the person gave.
    """
    a = _asked(history)
    owner = record.get("owner_norm") or normalise(record.get("owner_name", ""))
    otoks = tokens(owner)
    reasons: list[str] = []
    doubts: list[str] = []
    ev = {"family": False, "given_full": 0, "given_close": False, "given_initial": False, "postcode": False,
          "city": False, "holder": False, "holder_generic": False, "organisation": False,
          "organisation_named": False}
    s = 0.0

    points, why = _family_evidence(a, otoks)
    if points:
        s += points; reasons.append(why); ev["family"] = True
    else:
        doubts.append("family name is only a loose match")

    kinds = {g: given_kind(g, otoks) for g in a.given}
    full = sorted(g for g, k in kinds.items() if k == "full")
    close = sorted(g for g, k in kinds.items() if k == "close")
    initials = sorted(g for g, k in kinds.items() if k == "initial")
    ev["given_full"], ev["given_close"], ev["given_initial"] = len(full), bool(close), bool(initials)
    if len(full) >= 2:
        s += 0.30; reasons.append(f"two given names match ({', '.join(full)})")
    elif full:
        s += 0.22; reasons.append(f"given name matches ({', '.join(full)})")
        if initials or close:
            s += 0.04; reasons.append("a second given name matches by initial" if initials
                                      else "a second given name is close to one they gave")
    elif close:
        s += 0.16; reasons.append(f"given name is close to one they gave ({', '.join(close)}): a near spelling or a familiar form")
        doubts.append("the given name on the record is not spelled the way they gave it")
    elif initials:
        s += 0.08; reasons.append("given name matches by initial only"); doubts.append("only an initial for the given name")
    elif a.given:
        doubts.append("the given name on the record is not one they gave")
    else:
        doubts.append("they gave no given name to compare")

    extra = sum(1 for t in otoks if len(t) > 1 and not _explained(t, a))
    if extra:
        s -= 0.06 * min(extra, 3); doubts.append("the record also carries a name they did not give")

    rc, rr, rz, rk = (normalise(record.get(k) or "") for k in ("owner_city", "owner_region", "owner_postcode", "owner_country"))
    city_shown = ""
    for city, region, zc in a.places:
        zip_hit = bool(zc and rz and rz[:5] == zc[:5])
        city_hit = bool(city and rc and fuzz.ratio(city, rc) >= 90 and (not region or not rr or region == rr))
        ev["postcode"] = ev["postcode"] or zip_hit
        if city_hit and not city_shown:
            city_shown = record.get("owner_city") or ""
    ev["city"] = bool(city_shown)
    if ev["postcode"]:
        s += 0.20; reasons.append("the record's postcode is one they lived in")
    elif ev["city"]:
        s += 0.16; reasons.append(f"the record's city is one they lived in ({city_shown})")
    elif a.country and rk and rk == a.country:
        s += 0.12; reasons.append("the record's last address is in the country they live in now")
    elif a.places:
        doubts.append("the record's address is nowhere they mentioned")

    holder = record.get("holder_name") or ""
    if holder and any(names_holder(e, holder) for e in a.holders):
        s += 0.15; reasons.append(f"the money was reported by {holder}, which they named"); ev["holder"] = True
        ev["holder_generic"] = is_generic_holder(holder)

    if is_organisation(record.get("owner_name", "")):
        ev["organisation"] = True
        if a.organisation and not a.given and "".join(otoks) in a.wholes:
            ev["organisation_named"] = True
        elif not a.organisation:
            s -= 0.25; doubts.append("the owner looks like an organisation")
    tie = tie_of(ev)
    if tie:
        reasons.append(_tie_reason(tie))
    return Match(record=record, score=max(0.0, min(1.0, round(s, 3))), reasons=reasons, doubts=doubts,
                 strength=STRONG if tie else POSSIBLE, evidence=ev)


def _settle(m: Match) -> None:
    """Works the label out again after `find` has added what only a whole search knows, and keeps the reason
    that names the tie in step with it."""
    tie = tie_of(m.evidence)
    m.reasons = [r for r in m.reasons if not r.startswith(_tie_reason(""))]
    if tie:
        m.reasons.append(_tie_reason(tie))
    m.strength = STRONG if tie else POSSIBLE


# ---- the search ----

COLUMNS = ["source", "record_id", "owner_name", "owner_norm", "owner_street", "owner_city", "owner_region",
           "owner_postcode", "owner_country", "amount", "currency", "holder_name", "holder_city", "holder_region",
           "property_type"]
MAX_NEEDLES = 5
FLOOR = 0.40        # records with fewer points are not returned, unless they are strong


def _given_patterns(given: list[str]) -> tuple[str, str]:
    """Two regular expressions over owner_norm: one for a full, familiar or near-spelled given name as a whole
    word, one for a bare initial. They are the SQL twin of `given_kind`."""
    words: list[str] = []
    for g in given:
        words.append(g)
        words += sorted(nickname_forms(g))
        words += near_spelling_pattern(g)
    words = list(dict.fromkeys(words))
    initials = "".join(sorted({g[0] for g in given}))
    return f"(^| )({'|'.join(words)})( |$)", f"(^| )[{initials}]( |$)"


def family_filter(history: History) -> tuple[str, list] | None:
    """The family-name half of the candidate query, as SQL over phon_first, phon_last and owner_norm.

    A record passes when the sound key of its first or last word is the sound key of a family name they gave (this
    also covers respellings), or the family name stands as a middle word, or a particle surname written apart
    ('DE LA CRUZ', 'DELA CRUZ') is anywhere in the owner. A bare family name also looks for itself joined to a DE
    particle ('CRUZ' finds 'DELACRUZ').
    """
    p = history.person
    keys = {k for k in p.family_keys() if len(k) >= 2}
    if not keys:
        return None
    single = sorted(k for k in keys if " " not in k)
    typed_bare = {"".join(tokens(f)) for f in p.family if len(tokens(f)) == 1}
    joined = [d + k for k in single if k in typed_bare and len(k) >= 4 and not droppable_rest(k) for d in DROPPABLE]
    phon = sorted({phonetic(k) for k in single + joined} - {""})
    needles = sorted((k for k in keys if " " in k), key=lambda k: (-len(k), k))[:MAX_NEEDLES]
    needles += [f" {k} " for k in sorted(single, key=lambda k: (-len(k), k))[:MAX_NEEDLES]]
    marks = ",".join("?" * len(phon))
    sql = " or ".join(([f"phon_first in ({marks})", f"phon_last in ({marks})"] if phon else [])
                      + ["contains(owner_norm, ?)"] * len(needles))
    return sql, phon + phon + needles


def _candidate_sql(history: History, fetch: int) -> tuple[str, list] | None:
    """The one query that pulls candidates, using only phon_first, phon_last, owner_norm, owner_city and
    owner_postcode.

    Family name: see `family_filter`. Given name, when they gave one: the record must carry it as a whole word in
    full, as a familiar form or as a near spelling; a bare initial is enough only in a city or postcode they named.
    With no given name, the record must be in a city or postcode they named, if they named any.
    """
    family = family_filter(history)
    if family is None:
        return None
    fam_sql, params = family
    given = sorted(g for g in history.person.given_keys() if len(g) >= 2)
    cities = sorted({normalise(pl.city) for pl in history.places if pl.city})
    zips = sorted({normalise(pl.postcode)[:5] for pl in history.places if pl.postcode})
    city_sql = f"upper(owner_city) in ({','.join('?' * len(cities))})" if cities else "false"
    zip_sql = f"substr(owner_postcode, 1, 5) in ({','.join('?' * len(zips))})" if zips else "false"
    if given:
        words, initials = _given_patterns(given)
        near_sql = "regexp_matches(owner_norm, ?)"; params.append(words)
        if cities or zips:
            near_sql += f" or (regexp_matches(owner_norm, ?) and ({city_sql} or {zip_sql}))"
            params += [initials] + cities + zips
    elif cities or zips:
        near_sql = f"{city_sql} or {zip_sql}"; params += cities + zips
    else:
        near_sql = "true"
    # Which records survive the cut-off for a common name: first those in a postcode or city they named, then
    # those that spell the family name and the given name exactly, then the larger amounts.
    exact = sorted(k for k in history.person.family_keys() if " " not in k)
    marks = ",".join("?" * len(exact))
    family_exact = f"(split_part(owner_norm, ' ', 1) in ({marks}) or split_part(owner_norm, ' ', -1) in ({marks}))"
    given_exact = "regexp_matches(owner_norm, ?)" if given else "false"
    order = (f"(case when {zip_sql} then 8 else 0 end + case when {city_sql} then 4 else 0 end"
             f" + case when {family_exact} then 2 else 0 end + case when {given_exact} then 1 else 0 end) desc, amount desc"
             # Then by the record itself, so that the same search always keeps the same rows at the cut-off. Without
             # this, rows with equal amounts come back in whatever order the table scan found them, the counts in
             # the doubts move from one run to the next, and two replies cannot be compared.
             ", record_id, owner_norm, source")
    params += zips + cities + exact + exact + ([f"(^| )({'|'.join(given)})( |$)"] if given else [])
    sql = f"select {', '.join(COLUMNS)} from records where ({fam_sql}) and ({near_sql}) order by {order} limit {fetch}"
    return sql, params


def candidates(con: duckdb.DuckDBPyConnection, history: History, limit: int = 5000) -> list[dict]:
    """Pulls records that carry one of the person's family names (see `_candidate_sql`) and, when they gave a given
    name, that name in full, as a familiar form, as a near spelling or as an initial. At most `limit` records."""
    query = _candidate_sql(history, limit * 4)
    if query is None:
        return []
    given = sorted(g for g in history.person.given_keys() if len(g) >= 2)
    out = []
    for row in con.execute(*query).fetchall():
        r = dict(zip(COLUMNS, row))
        toks = (r["owner_norm"] or "").split()
        if not given or any(given_kind(g, toks) for g in given):
            out.append(r)
        if len(out) >= limit:
            break
    return out


def crowd_cap(crowd: int) -> float:
    """The most points a record may keep when the same name sits at `crowd` different addresses and no postcode
    ties the record to the person."""
    return 1.0 if crowd <= 3 else 0.75 if crowd <= 15 else 0.65 if crowd <= 60 else 0.55


def find(con, history: History, top: int = 25, floor: float = FLOOR) -> list[Match]:
    """Candidates, scored and ordered by the match strength number, highest first. A strong match is kept even
    when its number is under `floor`.

    `con` is one connection or a list of them. With a list (California's owner records and the demonstration
    records), the candidates of every table are scored, capped and ordered together, as one search."""
    cons = list(con) if isinstance(con, (list, tuple)) else [con]
    scored = [score(r, history) for c in cons for r in candidates(c, history)]
    # A common name in a big city is weak evidence. Count how many different addresses carry this name, and hold
    # the number down unless a postcode ties the record to the person.
    def spot(m: Match) -> tuple[str, str]:
        return (m.record.get("owner_city") or "", (m.record.get("owner_postcode") or "")[:5])

    crowd = len({spot(m) for m in scored if m.score >= floor})
    cap = crowd_cap(crowd)
    for m in scored:
        if not m.evidence.get("postcode") and m.score > cap:
            m.score = cap
            m.doubts.append(f"this name appears at {crowd} different addresses in the register, and nothing ties this record to a postcode they gave")
    # How common the name is: the number of different places (city and postcode) where a record carries the family
    # name and a given name in full. It does not depend on `floor`, so a claim and a search count the same. When
    # it is over COMMON_NAME_PLACES, a holder that reports a very large share of the register stops being a tie.
    name_places = len({spot(m) for m in scored if m.evidence.get("family") and m.evidence.get("given_full")})
    for m in scored:
        m.evidence["name_places"] = name_places
        if m.strength == STRONG and not tie_of(m.evidence):
            _settle(m)
            m.doubts.append(f"{m.record.get('holder_name') or 'the holder'} reports a very large share of the "
                            f"register and this name is very common (it is found in {name_places} different "
                            "places), so the holder does not tie this record to them")
    # The ties carry no address (a holder, two given names with the postcode), so they cannot all belong to one
    # person when the records they tie sit at many addresses. See strength_of. The streets are only counted here,
    # the same way for every search; none is compared with anything the person gave.
    loose = [m for m in scored if m.strength == STRONG]
    addresses = {(normalise(m.record.get("owner_street") or ""), (m.record.get("owner_postcode") or "")[:5]) for m in loose}
    if len(addresses) > MAX_TIE_ADDRESSES:
        for m in loose:
            m.evidence["tie_addresses"] = len(addresses)
            _settle(m)
            m.doubts.append(f"records with this name and the same tie sit at {len(addresses)} different addresses, "
                            "so the search cannot say which are theirs, and the proof file of a claim has to")
    scored = [m for m in scored if m.score >= floor or m.strength == STRONG]
    scored.sort(key=lambda m: (-m.score, -(m.record.get("amount") or 0), str(m.record.get("record_id") or ""),
                               m.record.get("owner_norm") or ""))
    return scored[:top]
