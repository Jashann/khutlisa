"""Who inherits, and how much: California's rules for an owner who has died, as exact fractions.

`compute(family)` takes a family described as data and returns each heir's share as a fraction, with the section
of the California Probate Code behind every step. It refuses, with the reason, whenever the facts are outside
what was read at the source and written down in docs/HEIRS.md. Nothing here guesses, and no language model is
involved: the model only turns a person's words into the family structure (estates.py), and this module decides.

What is computed (each section was read on leginfo.legislature.ca.gov on 13 Nov 2026):

  6400        the part of an estate not disposed of by will passes under these rules
  100, 101    one half of community (or quasi-community) property already belongs to the surviving spouse
  6401        the surviving spouse's share of community, quasi-community and separate property
  6402(a)-(c) the rest: to issue, then to parents, then to the issue of parents
  240         how issue of unequal degree divide (equal shares at the nearest generation with a living member)
  6403        an heir must survive the owner by 120 hours
  6406        relatives of the half blood take the same share
  6414        nothing here applies to a death before 1 January 1985
  37, 72, 78  a registered domestic partner is a spouse; a former spouse is not a surviving spouse

What is refused: takers under 6402(d) to (g) (grandparents, the issue of a predeceased spouse, next of kin), the
predeceased-spouse rule of 6402.5, advancements (6409), debts (6410), adoption out of the family (6451),
stepchildren and foster children (6454), a person related through two lines (6413), a parent barred by 6452, a
person barred by 250, and a will or court order whose shares do not add up to the whole.

Where the owner did not live in California when they died, the California default is still computed, and the
result carries a flag: other law may govern, and a person has to decide. This module does not resolve that.
"""
from __future__ import annotations

import re
from datetime import date
from fractions import Fraction
from typing import Any

LEGINFO = "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode={code}&sectionNum={number}."
FIRST_DAY = date(1985, 1, 1)     # Probate Code 6414(a)

DISPOSITIONS = ("intestate", "will", "court_order")
PROPERTY = ("separate", "community", "quasi_community")

# Facts a claimant can report that take the estate outside what this module computes. Each names its section.
OUTSIDE = {
    "adopted_out": ("6451", "A child of the owner was adopted by someone else, or the owner was adopted. Whether "
                            "the first parent and child relationship still counts depends on section 6451."),
    "stepchild_or_foster": ("6454", "A stepchild or foster child claims as a child. Section 6454 allows it only on "
                                    "clear and convincing evidence that an adoption was prevented by a legal barrier."),
    "advancement": ("6409", "The owner gave an heir property during life as an advance on the inheritance. Section "
                            "6409 then changes that heir's share."),
    "debt_to_owner": ("6410", "An heir owed the owner money. Section 6410 charges the debt against that heir's "
                              "share."),
    "two_lines": ("6413", "An heir is related to the owner in two ways. Section 6413 gives one share, the larger."),
    "parent_barred": ("6452", "A parent may be barred from inheriting from the child under section 6452."),
    "heir_barred": ("250", "An heir may be barred under section 250."),
}


def url(section: str) -> str:
    """The Legislature's page for a section such as "6401(c)(2)(A)" or "CIV 946"."""
    code, _, rest = section.partition(" ") if section[:1].isalpha() else ("PROB", "", section)
    number = re.match(r"[\d.]+", rest)
    return LEGINFO.format(code=code, number=number.group(0).rstrip(".") if number else rest)


class Refused(Exception):
    """The facts are outside what was verified. `reason` is a sentence; `section` names the rule in the way."""

    def __init__(self, reason: str, section: str | None = None, question: str | None = None):
        super().__init__(reason)
        self.reason, self.section, self.question = reason, section, question


# ---- the family, as data ---------------------------------------------------------------------------------------

def _text(value: Any, limit: int = 120) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int)) else ""


def _country(value: Any) -> str:
    code = _text(value, 2).upper()
    return code if len(code) == 2 and code.isalpha() else ""


def _tri(value: Any) -> bool | None:
    """True, False or None (not known) from what a form or a model sent."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in ("true", "yes", "y", "alive", "living"):
            return True
        if word in ("false", "no", "n", "dead", "deceased", "died"):
            return False
    return None


def _person(raw: Any, prefix: str, index: int, depth: int = 0) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = _text(raw.get("name"))
    pid = _text(raw.get("id"), 24) or f"{prefix}{index}"
    alive = _tri(raw.get("alive"))
    children = []
    if depth < 4:
        for i, child in enumerate(raw.get("children") or [] if isinstance(raw.get("children"), list) else [], 1):
            got = _person(child, f"{pid}.", i, depth + 1)
            if got:
                children.append(got)
    known = _tri(raw.get("children_known"))
    return {"id": re.sub(r"[^A-Za-z0-9.]", "", pid) or f"{prefix}{index}", "name": name, "alive": alive,
            "country": _country(raw.get("country")),     # where they live now; no rule depends on it
            "children": children,
            # Whether we were told about this person's own children. Only asked of a person who has died.
            "children_known": bool(children) or bool(known)}


def clean_family(raw: dict | None) -> dict:
    """The family in its stored form. Unknown things stay unknown (None); nothing is assumed."""
    raw = raw if isinstance(raw, dict) else {}
    owner = raw.get("decedent") if isinstance(raw.get("decedent"), dict) else {}
    died = _text(owner.get("died_on"), 10)
    try:
        date.fromisoformat(died)
    except ValueError:
        died = ""
    country = _text(owner.get("domicile_country"), 2).upper()
    state = _text(owner.get("domicile_state"), 3).upper()
    disposition = raw.get("disposition") if raw.get("disposition") in DISPOSITIONS else None
    kind = raw.get("property") if raw.get("property") in PROPERTY else None
    has_spouse = _tri(raw.get("has_spouse"))
    spouse = _person(raw.get("spouse"), "s", 1) if has_spouse is not False else None
    if spouse:
        spouse = {"id": "s1", "name": spouse["name"], "alive": spouse["alive"], "country": spouse["country"]}
        has_spouse = True if has_spouse is None else has_spouse
    elif has_spouse:            # married at death, and nothing more is known yet
        spouse = {"id": "s1", "name": "", "alive": None, "country": ""}

    def people(key: str, prefix: str, nested: bool) -> list[dict]:
        rows = raw.get(key) if isinstance(raw.get(key), list) else []
        out = [p for i, r in enumerate(rows, 1) if (p := _person(r, prefix, i, 0 if nested else 4))]
        return out[:20]

    children, parents, siblings = people("children", "c", True), people("parents", "p", False)[:2], people("siblings", "b", True)
    named = []
    for i, row in enumerate(raw.get("named_shares") if isinstance(raw.get("named_shares"), list) else [], 1):
        if isinstance(row, dict) and _text(row.get("name")):
            named.append({"id": re.sub(r"[^A-Za-z0-9.]", "", _text(row.get("id"), 24)) or f"n{i}",
                          "name": _text(row.get("name")), "share": _text(row.get("share"), 20),
                          "country": _country(row.get("country")),
                          "relation": _text(row.get("relation"), 40)})
    unusual = [k for k in (raw.get("unusual") if isinstance(raw.get("unusual"), list) else []) if k in OUTSIDE]
    family = {
        "decedent": {"name": _text(owner.get("name")), "died_on": died, "domicile_country": country,
                     "domicile_state": state if country == "US" else ""},
        "disposition": disposition, "named_shares": named[:20], "property": kind,
        "has_spouse": has_spouse, "spouse": spouse,
        "children": children, "children_known": bool(children) or bool(_tri(raw.get("children_known"))),
        "parents": parents, "parents_known": bool(parents) or bool(_tri(raw.get("parents_known"))),
        "siblings": siblings, "siblings_known": bool(siblings) or bool(_tri(raw.get("siblings_known"))),
        "predeceased_spouse_recent": _tri(raw.get("predeceased_spouse_recent")),
        "unusual": sorted(set(unusual)),
    }
    seen: set[str] = set()
    for person in everyone(family):      # ids must be unique, whatever was sent
        while person["id"] in seen:
            person["id"] += "x"
        seen.add(person["id"])
    return family


def everyone(family: dict) -> list[dict]:
    """Every person in the family, at any depth, the spouse first."""
    out: list[dict] = []

    def walk(person: dict) -> None:
        out.append(person)
        for child in person.get("children") or []:
            walk(child)

    if family.get("spouse"):
        out.append(family["spouse"])
    for key in ("children", "parents", "siblings"):
        for person in family.get(key) or []:
            walk(person)
    return out + list(family.get("named_shares") or [])


def _living(person: dict) -> bool:
    return person.get("alive") is True


def _living_issue(person: dict) -> bool:
    return any(_living(c) or _living_issue(c) for c in person.get("children") or [])


def _counts(person: dict) -> bool:
    """A person who takes a share or passes one down: alive, or dead with living issue."""
    return _living(person) or _living_issue(person)


# ---- what the rule still needs to know --------------------------------------------------------------------------

def questions(family: dict) -> list[dict]:
    """The facts still missing, in the order they should be asked, each with a fixed English question. Empty
    when `compute` has everything the rule needs. "Alive" always means: survived the owner by at least 120 hours
    (section 6403)."""
    asks: list[dict] = []

    def ask(key: str, question: str, about: str | None = None) -> None:
        asks.append({"key": key, "question": question, "about": about})

    owner = family["decedent"]
    who = owner["name"] or "the person who died"
    if family["disposition"] is None:
        ask("disposition", f"Did {who} leave a will, or has a court made an order saying who receives what?")
    if not owner["died_on"]:
        ask("died_on", f"On what date did {who} die?")
    if not owner["domicile_country"] or (owner["domicile_country"] == "US" and not owner["domicile_state"]):
        ask("domicile", f"Where was {who} living at the time of death: which country, and which state if it was the "
                        "United States?")
    if family["disposition"] in ("will", "court_order"):
        if not family["named_shares"] or any(not n["share"] for n in family["named_shares"]):
            ask("named_shares", "Who does the will or the court order name, and what share does each person receive?")
        return asks
    if family["has_spouse"] is None:
        ask("has_spouse", f"Was {who} married, or in a registered domestic partnership, at the time of death?")
    elif family["has_spouse"] and family["spouse"] and family["spouse"]["alive"] is None:
        ask("spouse_alive", f"Did the husband, wife or partner outlive {who} by at least five days?", "s1")
    if not family["children_known"]:
        ask("children", f"How many children did {who} have, counting any who have died? What are their names?")

    def about_issue(person: dict, label: str) -> None:
        name = person["name"] or label
        if person["alive"] is None:
            ask("alive", f"Is {name} alive, and did they outlive {who} by at least five days?", person["id"])
        elif person["alive"] is False:
            if not person["children_known"]:
                ask("children_of", f"{name} has died. Did {name} leave children? What are their names?", person["id"])
            for i, child in enumerate(person["children"], 1):
                about_issue(child, f"child {i} of {name}")

    for i, child in enumerate(family["children"], 1):
        about_issue(child, f"child {i}")
    issue = any(_counts(c) for c in family["children"])
    settled = family["children_known"] and not any(q["key"] in ("alive", "children_of") for q in asks)
    if settled and not issue:       # no issue: parents come next, then brothers and sisters and their children
        if not family["parents_known"]:
            ask("parents", f"Is either of {who}'s parents alive?")
        for parent in family["parents"]:
            if parent["alive"] is None:
                ask("alive", f"Is {parent['name'] or 'this parent'} alive, and did they outlive {who} by at least "
                             "five days?", parent["id"])
        parents_settled = family["parents_known"] and all(p["alive"] is not None for p in family["parents"])
        if parents_settled and not any(_living(p) for p in family["parents"]):
            if not family["siblings_known"]:
                ask("siblings", f"Did {who} have brothers or sisters, counting half brothers and half sisters and "
                                "any who have died? What are their names?")
            for i, sibling in enumerate(family["siblings"], 1):
                about_issue(sibling, f"brother or sister {i}")
            siblings_settled = family["siblings_known"] and not any(
                q["key"] in ("alive", "children_of") for q in asks)
            spouse_takes = family["has_spouse"] and family["spouse"] and _living(family["spouse"])
            if siblings_settled and not any(_counts(s) for s in family["siblings"]) and not spouse_takes \
                    and family["predeceased_spouse_recent"] is None:
                ask("predeceased_spouse_recent", f"Did {who} have a husband, wife or partner who died in the five "
                                                 "years before them?")
    if family["has_spouse"] and family["spouse"] and _living(family["spouse"]) and family["property"] is None \
            and not asks and _property_matters(family):
        ask("property", f"Was this money earned or saved during the marriage, or was it {who}'s own from before "
                        "the marriage or from a gift or an inheritance?")
    return asks


def _property_matters(family: dict) -> bool:
    """Whether the spouse's share differs between community and separate property for this family."""
    try:
        return _spouse_fraction({**family, "property": "separate"})[0] != 1
    except Refused:
        return True


# ---- the rules ---------------------------------------------------------------------------------------------------

class _Result:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.shares: dict[str, Fraction] = {}
        self.people: dict[str, dict] = {}

    def step(self, section: str, text: str, gives: dict[str, Fraction] | None = None) -> int:
        self.steps.append({"n": len(self.steps) + 1, "section": section, "url": url(section), "text": text,
                           "gives": {k: str(v) for k, v in (gives or {}).items()}})
        return len(self.steps)

    def give(self, person: dict, relation: str, share: Fraction, step: int, line: list[str] | None = None) -> None:
        self.shares[person["id"]] = self.shares.get(person["id"], Fraction(0)) + share
        held = self.people.setdefault(person["id"], {"id": person["id"], "name": person.get("name") or "",
                                                     "relation": relation, "line": line or [], "steps": []})
        held["steps"].append(step)


def _say(share: Fraction) -> str:
    words = {Fraction(1): "the whole", Fraction(1, 2): "one half", Fraction(1, 3): "one third",
             Fraction(2, 3): "two thirds", Fraction(1, 4): "one quarter"}
    return words.get(share, f"{share.numerator}/{share.denominator}")


def _spouse_fraction(family: dict) -> tuple[Fraction, str, str]:
    """(the surviving spouse's fraction of separate property, the paragraph of 6401(c), why)."""
    children = [c for c in family["children"] if _counts(c)]
    living = [c for c in children if _living(c)]
    through = [c for c in children if not _living(c)]         # deceased children who left living issue
    if not children:
        parents = any(_living(p) for p in family["parents"])
        their_issue = any(_counts(s) for s in family["siblings"])
        if not parents and not their_issue:
            return Fraction(1), "6401(c)(1)", ("the owner left no surviving issue, parent, brother, sister, or "
                                               "issue of a deceased brother or sister")
        return Fraction(1, 2), "6401(c)(2)(B)", "the owner left no issue, but left a parent or the issue of a parent"
    if len(children) == 1:
        why = "the owner left only one child" if living else "the owner left the issue of one deceased child"
        return Fraction(1, 2), "6401(c)(2)(A)", why
    if len(living) >= 2:
        return Fraction(1, 3), "6401(c)(3)(A)", "the owner left more than one child"
    if len(living) == 1:
        return Fraction(1, 3), "6401(c)(3)(B)", "the owner left one child and the issue of one or more deceased children"
    return Fraction(1, 3), "6401(c)(3)(C)", "the owner left the issue of two or more deceased children"


def _by_240(result: _Result, roots: list[dict], whole: Fraction, relation, section: str, line: list[str]) -> None:
    """Divide `whole` among the issue below `roots` in the manner of section 240: equal shares at the nearest
    generation that has a living member, one for each living member and one for each deceased member who left
    living issue; a deceased member's share is divided among their issue in the same manner."""
    generation, depth, parents_of = [r for r in roots], 1, {r["id"]: line for r in roots}
    while generation and not any(_living(p) for p in generation):
        nxt = []
        for person in generation:
            for child in person.get("children") or []:
                parents_of[child["id"]] = parents_of[person["id"]] + [person["id"]]
                nxt.append(child)
        generation, depth = nxt, depth + 1
    stocks = [p for p in generation if _counts(p)]
    if not stocks:
        return
    each = whole / len(stocks)
    living = [p for p in stocks if _living(p)]
    through = [p for p in stocks if not _living(p)]
    if not through and depth == 1:
        text = (f"{len(living)} of the same degree take equally: {_say(each)} of the estate each."
                if len(living) > 1 else f"The only one in that degree takes {_say(each)} of the estate.")
        n = result.step(section, text, {p["id"]: each for p in living})
    else:
        text = (f"The nearest generation with a living member has {len(living)} living and {len(through)} who died "
                f"leaving living issue, so the part is divided into {len(stocks)} equal shares of {_say(each)} of the "
                "estate. Each living member takes one share. The share of each member who died is divided among "
                "their own issue in the same way.")
        n = result.step("240", text, {p["id"]: each for p in living})
    for person in living:
        result.give(person, relation(depth), each, n, parents_of[person["id"]])
    for person in through:
        _by_240(result, person["children"], each, lambda d, base=depth: relation(base + d), "240",
                parents_of[person["id"]] + [person["id"]])


def _issue_relation(depth: int) -> str:
    return {1: "child", 2: "grandchild", 3: "great-grandchild"}.get(depth, "issue")


def _collateral_relation(depth: int) -> str:
    return {1: "brother or sister", 2: "niece or nephew"}.get(depth, "issue of a brother or sister")


def _fraction(text: str) -> Fraction:
    text = text.strip().replace(" ", "")
    if text.endswith("%"):
        return Fraction(text[:-1]) / 100
    return Fraction(text)


def _named(family: dict, result: _Result) -> None:
    kind = "will" if family["disposition"] == "will" else "court order"
    rows = family["named_shares"]
    if not rows:
        raise Refused(f"The {kind} has to say who receives what. No shares were given.", "6400")
    total = Fraction(0)
    gives: dict[str, Fraction] = {}
    for row in rows:
        try:
            share = _fraction(row["share"])
        except (ValueError, ZeroDivisionError):
            raise Refused(f"The share given for {row['name']} ({row['share'] or 'nothing'}) is not a fraction or a "
                          "percentage.", "6400") from None
        if share <= 0:
            raise Refused(f"The share given for {row['name']} is not more than nothing.", "6400")
        gives[row["id"]] = share
        total += share
    if total != 1:
        raise Refused(f"The shares named in the {kind} add up to {total}, not to the whole. Section 6400 sends any "
                      "part a will does not dispose of to the heirs under the rules for an estate without a will, "
                      "and working out that mixture is left to a person.", "6400")
    n = result.step("6400", f"The owner's property is disposed of by a {kind}, so the shares are the ones it names. "
                            "The rules for an estate without a will apply only to a part that is not disposed of. "
                            "Khutlisa does not interpret the document: the shares are as the family stated them, and "
                            "the holder reads the document itself.", gives)
    for row in rows:
        result.give(row, f"named in the {kind}", gives[row["id"]], n)


def compute(family: dict, today: date | None = None) -> dict:
    """Each heir's share as an exact fraction, with the statute step behind it.

    Returns {"computed": True, "basis", "heirs": [{"id", "name", "relation", "share": "1/3", "line", "steps"}],
    "steps": [{"n", "section", "url", "text", "gives"}], "flags": [...], "needs_person": bool}, or
    {"computed": False, "refusal": {"reason", "section", "url"}, "questions": [...]} when the facts are missing
    or outside what was verified. The shares of a computed result always add up to exactly 1."""
    family = clean_family(family)
    result = _Result()
    try:
        flags = _compute(family, result, today or date.today())
    except Refused as no:
        return {"computed": False, "questions": questions(family),
                "refusal": {"reason": no.reason, "section": no.section, "url": url(no.section) if no.section else None}}
    total = sum(result.shares.values(), Fraction(0))
    if total != 1 or any(s <= 0 for s in result.shares.values()):     # never hand out a result that does not add up
        return {"computed": False, "questions": [],
                "refusal": {"reason": f"The shares came to {total}, not to the whole. This is a fault in Khutlisa, "
                                      "and a person has to work this estate out.", "section": None, "url": None}}
    heirs = [{**result.people[pid], "share": str(share)} for pid, share in result.shares.items()]
    return {"computed": True, "basis": family["disposition"], "law": "California Probate Code",
            "heirs": heirs, "steps": result.steps, "flags": flags, "needs_person": bool(flags), "questions": []}


def _compute(family: dict, result: _Result, today: date) -> list[dict]:
    owner = family["decedent"]
    asks = questions(family)
    if asks:
        raise Refused("The rule needs a fact that has not been given yet: " + asks[0]["question"], None,
                      asks[0]["question"])
    died = date.fromisoformat(owner["died_on"])
    if died > today:
        raise Refused("The date of death is in the future.", None)
    if died < FIRST_DAY:
        raise Refused("The owner died before 1 January 1985. Section 6414 leaves such an estate to the law as it "
                      "stood before that date, which Khutlisa does not compute.", "6414(a)")
    for key in family["unusual"]:
        section, text = OUTSIDE[key]
        raise Refused(text + " Khutlisa does not compute this. A person has to.", section)
    flags = []
    if owner["domicile_country"] != "US" or owner["domicile_state"] != "CA":
        place = owner["domicile_state"] if owner["domicile_country"] == "US" else owner["domicile_country"]
        flags.append({"key": "other_law", "section": "CIV 946", "url": url("CIV 946"),
                      "text": f"The owner was not living in California at the time of death (domicile: {place}). "
                              "California's Civil Code 946 lets personal property follow the law of its owner's "
                              "home, and Probate Code 13006(b) itself allows that the law of another state or "
                              "nation may govern who succeeds. The shares shown are California's default. Khutlisa "
                              "has not decided which law applies. A person has to, before anything is paid."})
    if family["disposition"] in ("will", "court_order"):
        _named(family, result)
        return flags

    spouse = family["spouse"] if family["has_spouse"] and family["spouse"] and _living(family["spouse"]) else None
    if family["has_spouse"] and family["spouse"] and not spouse:
        result.step("6403(a)", "The husband, wife or partner did not survive the owner by 120 hours, so is treated "
                               "as having died first and takes nothing.")
    kind = family["property"]
    rest = Fraction(1)
    if spouse:
        if kind is None:
            kind = "separate"       # questions() asks only when it matters, so here both give the same answer
        if kind == "quasi_community" and not (owner["domicile_country"] == "US" and owner["domicile_state"] == "CA"):
            raise Refused("Section 101 gives the surviving spouse half of quasi-community property only where the "
                          "owner was living in California at death. This owner was not.", "101(a)")
        if kind in ("community", "quasi_community"):
            own, intestate = ("100(a)", "6401(a)") if kind == "community" else ("101(a)", "6401(b)")
            words = "community" if kind == "community" else "quasi-community"
            a = result.step(own, f"The money is {words} property. One half of it already belongs to the surviving "
                                 "spouse.", {spouse["id"]: Fraction(1, 2)})
            b = result.step(intestate, "The other half belonged to the owner. With no will, that half also passes "
                                       "to the surviving spouse.", {spouse["id"]: Fraction(1, 2)})
            result.give(spouse, "spouse", Fraction(1, 2), a)
            result.give(spouse, "spouse", Fraction(1, 2), b)
            return flags
        share, paragraph, why = _spouse_fraction(family)
        n = result.step(paragraph, f"The money is the owner's separate property. The surviving spouse takes "
                                   f"{_say(share)}, because {why}.", {spouse["id"]: share})
        result.give(spouse, "spouse", share, n)
        rest -= share
        if rest == 0:
            return flags
    lead = ("the part that does not pass to the surviving spouse" if spouse else
            "the whole estate, as there is no surviving spouse")
    if any(_counts(c) for c in family["children"]):
        result.step("6402(a)", f"{lead[0].upper() + lead[1:]} ({_say(rest)}) passes to the owner's issue.")
        _by_240(result, family["children"], rest, _issue_relation, "6402(a)", [])
        return flags
    parents = [p for p in family["parents"] if _living(p)]
    if parents:
        each = rest / len(parents)
        n = result.step("6402(b)", f"There is no surviving issue, so {lead} ({_say(rest)}) passes to the owner's "
                                   f"{'parents equally' if len(parents) > 1 else 'surviving parent'}.",
                        {p["id"]: each for p in parents})
        for parent in parents:
            result.give(parent, "parent", each, n)
        return flags
    if any(_counts(s) for s in family["siblings"]):
        result.step("6402(c)", f"There is no surviving issue or parent, so {lead} ({_say(rest)}) passes to the issue "
                               "of the owner's parents: brothers and sisters, and the children of any who have "
                               "died. Section 6406 gives a half brother or half sister the same share.")
        _by_240(result, family["siblings"], rest, _collateral_relation, "6402(c)", [])
        return flags
    if family["predeceased_spouse_recent"]:
        raise Refused("The owner left no spouse, issue, parent, brother or sister, and had a husband, wife or "
                      "partner who died within the five years before. Section 6402.5 may then send part of the "
                      "estate to that person's family. Khutlisa does not compute this.", "6402.5(b)")
    raise Refused("The owner left no surviving spouse, issue, parent, or issue of a parent. The next takers under "
                  "section 6402(d) to (g) are grandparents and their issue, the issue of a spouse who died first, "
                  "and the next of kin; if there is nobody, section 6404 sends the estate to the State. Khutlisa "
                  "does not compute these. A person has to.", "6402(d)")
