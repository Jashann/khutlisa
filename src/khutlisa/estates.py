"""An owner who has died: the family, each heir's share, and what ties each heir to the owner.

An estate is a claim with relationship "heir" plus `claim["estate"]`:

    {"family": {...},            the family as data (succession.clean_family)
     "succession": {...},        succession.compute(family): the shares and the statute steps, or the refusal
     "heirs": [{"id", "name", "relation", "share": "1/3", "line", "country", "email", "payee", "declared",
                "proven", "paid"}],
     "details": {heir id: {...}}, what each heir gave, kept even while the shares cannot be computed
     "words", "language", "english", "follow_up": the intake, as the claimant gave it
     "other_law": the holder's recorded reason when California's default is used for an owner who lived elsewhere
    }

Three kinds of work are kept apart. A language model turns the claimant's words into the family structure and
reads the documents; it decides nothing. `succession.py` computes the shares. This module compares the names on
the documents with the family in code, and says for each heir what ties them to the owner and what is missing.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from fractions import Fraction
from pathlib import Path
from typing import Callable

from . import checks, documents, intake, llm, proof, reading, succession
from . import claims as cl
from .countries import COUNTRIES
from .demo import is_demonstration
from .names import tokens

DAYS_AFTER_DEATH = 40          # Probate Code 13100 and 13101(a)(3)
DECLARATION = [                # the points of Probate Code 13101(a) that each heir states
    "At least 40 days have passed since the death.",
    "No proceeding is being or has been conducted in California to administer the estate.",
    "The heirs named here are the successors to this property, and nobody else has a better right to it.",
    "The value of everything the owner left in California is within the limit of Probate Code 13100.",
]
SIMULATED_DECLARATION = ("Recorded here as a statement. In real use each heir signs the declaration of Probate Code "
                         "13101 under penalty of perjury.")

# ---- the intake: the claimant's words become the family structure ----------------------------------------------

FAMILY_PROMPT = """A person is telling us, in their own words and possibly not in English, that someone has died \
and who that person's family is. The person who died is owed unclaimed money in California. We need the family as \
data, so that a program (not you) can work out who inherits.

Their words (a speech-to-text transcript, so expect errors):
<<<
{transcript}
>>>

Return JSON with these fields. Use only what they said. Use null (or an empty list with the matching *_known \
field false) for anything they did not say. Never guess a death, a marriage, a child or a date.
- language: the language they spoke
- english: a faithful English translation of what they said
- decedent: object with name (the person who died, in full as said), died_on (YYYY-MM-DD only if the full date was \
said, else ""), domicile_country (ISO two-letter code of the country they were living in when they died, else ""), \
domicile_state (two-letter state code if that country is the United States, else "")
- disposition: "will" if they said there is a will, "court_order" if a court has ordered who receives what, \
"intestate" if they said there is no will, null if they did not say
- named_shares: only for a will or court order: list of objects with name, share (a fraction like "1/2" or a \
percentage, as said), relation, country
- property: "community" if they said the money was earned or saved during the marriage, "separate" if they said it \
was the dead person's own from before the marriage or from a gift or inheritance, null if they did not say
- has_spouse: true if the dead person was married or in a registered partnership at the time of death, false if \
they said there was no spouse then (never married, divorced, or the spouse died earlier), null if not said
- spouse: object with name, alive (true or false or null), country (ISO two-letter code of where they live now, \
or "")
- children: every child of the dead person that was mentioned, including any who have died, each an object with \
name, alive (true, false or null), country, children (that child's own children, in the same shape; list them \
only for a child who has died), children_known (true if they said whether this child had children)
- children_known: true if they said how many children the dead person had (including "none")
- parents: the dead person's parents if mentioned, each with name, alive, country
- parents_known: true if they said whether the parents are alive
- siblings: the dead person's brothers and sisters if mentioned, in the same shape as children
- siblings_known: true if they said whether there were brothers or sisters
- predeceased_spouse_recent: true if a husband, wife or partner of the dead person died in the five years before \
them, false if they said not, null if not said
- unusual: a list with any of these that they clearly described: "adopted_out" (a child was adopted by someone \
else, or the dead person was adopted), "stepchild_or_foster" (a stepchild or foster child is claiming), \
"advancement" (the dead person gave an heir money in advance of the inheritance), "debt_to_owner" (an heir owed \
the dead person money)
- follow_up_key: we will ask them for the first fact still missing, in this order: "disposition" (was there a \
will or a court order), "died_on" (the full date of death), "domicile" (where the dead person lived at death), \
"has_spouse" (married or partnered at death), "spouse_alive", "children" (how many children, and their names), \
"alive" (whether a named relative is alive), "children_of" (whether a child who died left children), "parents", \
"siblings", "property". Give the key of the first one that is missing, or "" if none is.
- follow_up: that one question, in their language, naming the relative it is about where there is one. "" if none.
- follow_up_english: the same question in English"""

SAMPLE_WORDS_ES = (
    "Mi esposo, Rafael Ibarra Montoya, murió el 14 de marzo de 2024 en Guadalajara, donde vivíamos desde que "
    "volvimos de California. No dejó testamento. Yo soy su esposa, Lucía Montoya de Ibarra, y vivo en Guadalajara. "
    "Tuvimos tres hijos: Carmela, que vive en Cebú, en Filipinas; Tomás, que vive en Leeds, en Inglaterra; y "
    "Esteban, que murió en 2019 y dejó una hija, Naomi, que vive en Osaka, en Japón. El dinero era el salario de "
    "Rafael de antes de casarnos."
)


def understand_family(words: str, earlier: str = "", question: str = "", model: str = "sonnet") -> dict:
    """The claimant's words as a family structure, with the model's own wording of one follow-up question. The
    question that is really asked is chosen in code (`next_question`); the model's wording is used only when it
    is asking for the same fact."""
    transcript = intake.join_answer(earlier, question, words)[-intake.MAX_WORDS:]
    data = llm.ask_json(FAMILY_PROMPT.format(transcript=transcript.strip()), model=model)
    if not isinstance(data, dict):
        raise ValueError("the model did not return a family")
    return {"transcript": words.strip(), "full_transcript": transcript,
            "language": intake._text(data.get("language") or "", 60),
            "english": intake._text(data.get("english") or "", intake.MAX_WORDS),
            "family": succession.clean_family(data),
            "asked": {"key": intake._text(data.get("follow_up_key") or "", 40),
                      "question": intake._text(data.get("follow_up") or "", 400),
                      "english": intake._text(data.get("follow_up_english") or "", 400)}}


def next_question(family: dict, asked: dict | None = None) -> dict | None:
    """The one question to put next: the first fact the rule still needs (succession.questions). It is shown in
    the claimant's language when the model worded a question for that same fact, and in English otherwise."""
    needs = succession.questions(family)
    if not needs:
        return None
    first = needs[0]
    theirs = (asked or {}).get("question") if (asked or {}).get("key") == first["key"] else ""
    return {"key": first["key"], "about": first.get("about"), "english": first["question"],
            "question": theirs or first["question"], "in_their_language": bool(theirs),
            "remaining": len(needs)}


# ---- reading a civil record: the people on it and their parts ----------------------------------------------------

ROLES = ("subject", "mother", "father", "parent", "spouse", "heir", "official", "other")
PARENT_ROLES = ("mother", "father", "parent")
ESTATE_KINDS = ("death_certificate", "birth_certificate", "name_change", "heirship", "id")

PEOPLE_FIELDS = """
- people: every person the document names, with the part they play in it, as objects with name (exactly as \
printed) and role. role is one of: "subject" (the person a certificate is about: the child on a birth certificate, \
the person who died on a death certificate, the holder of an identity document), "mother", "father", "parent", \
"spouse" (each of the two people married on a marriage certificate; the husband or wife named on a death \
certificate), "heir" (a person a will or a court order gives a share to), "official" (a registrar, judge, notary, \
witness or informant), "other". Go by the labels printed beside each name. Empty list if there are none.
- date_of_death: on a death certificate, the date of death as YYYY-MM-DD, or "" when it is not printed in full
- shares: on a will or a court order, each share it gives, as objects with name (exactly as printed) and share \
(as printed, for example "1/2" or "50%"). Empty list otherwise."""


def _people(raw) -> list[dict]:
    out = []
    for row in raw if isinstance(raw, list) else []:
        if isinstance(row, dict) and documents._words(row.get("name")):
            role = documents._words(row.get("role") or "", 12).lower()
            out.append({"name": documents.mask_numbers(documents._words(row.get("name"), 120)),
                        "role": role if role in ROLES else "other"})
    return out[:16]


def read_civil_record(path: str | Path, kind: str = "other", model: str = "sonnet") -> dict:
    """One reading of an estate document: everything `documents.read_document` returns, plus "people" (each name
    with its part in the document), "date_of_death" and "shares". The model copies; code decides."""
    path = Path(path)
    if not path.is_file():
        return {"status": "not_read"}
    prompt = documents.READ_PROMPT.format(kind=documents.KINDS.get(kind, documents.KINDS["other"]).lower()) + PEOPLE_FIELDS
    failure: dict = {}
    for _ in range(2):
        try:
            raw = llm.ask_json(prompt, files=[str(path)], model=model)
        except llm.ModelUnavailable as err:
            failure = {"status": "failed", "problem": "The reading model is not available on this machine.",
                       "detail": documents.mask_numbers(str(err))[:200]}
            continue
        except Exception as err:
            failure = {"status": "failed", "problem": "The document could not be read this time.",
                       "detail": documents.mask_numbers(f"{type(err).__name__}: {err}")[:200]}
            continue
        if isinstance(raw, dict):
            out = documents.clean_reading(raw)
            out["people"] = _people(raw.get("people"))
            out["date_of_death"] = documents._words(raw.get("date_of_death") or "", 40)
            out["shares"] = [{"name": documents._words(s.get("name"), 120), "share": documents._words(s.get("share"), 20)}
                             for s in (raw.get("shares") if isinstance(raw.get("shares"), list) else [])
                             if isinstance(s, dict) and documents._words(s.get("name"))][:20]
            return out
        failure = {"status": "failed", "problem": "The document could not be read this time."}
    return failure


def _key(name: str) -> tuple:
    return tuple(sorted(tokens(name)))


def read_civil_record_twice(path, kind: str, read: Callable[..., dict] | None = None) -> dict:
    """Two separate readings, made side by side, combined by `documents.combine_readings` (which compares the
    name and the dates). The parts added here are compared as well: a person and their role count only if both
    readings saw them, and "extra_agreement" says which of people, date of death and shares the two disagree
    on. A disagreement holds the document for a person to look at."""
    one = read or read_civil_record

    def attempt(_) -> dict:
        try:
            return one(path, kind)
        except Exception:
            return {"status": "failed", "problem": "The document could not be read this time."}

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="estate-reading") as pool:
        first, second = pool.map(attempt, range(2))
    out = documents.combine_readings(first, second)
    both = [r for r in (first, second) if r.get("status") == "read"]
    if out.get("status") != "read" or len(both) < 2:
        return out
    seen = [{(_key(p["name"]), p["role"]) for p in r.get("people") or []} for r in both]
    disagreed = []
    if seen[0] != seen[1]:
        disagreed.append("people named and their parts")
    if (both[0].get("date_of_death") or "") != (both[1].get("date_of_death") or ""):
        disagreed.append("date of death")
    as_set = lambda r: {(_key(s["name"]), s["share"].replace(" ", "")) for s in r.get("shares") or []}
    if as_set(both[0]) != as_set(both[1]):
        disagreed.append("shares")
    out["people"] = [p for p in both[0].get("people") or [] if (_key(p["name"]), p["role"]) in seen[1]]
    out["date_of_death"] = both[0].get("date_of_death") if "date of death" not in disagreed else ""
    out["shares"] = both[0].get("shares") if "shares" not in disagreed else []
    out["extra_agreement"] = {"status": "disagree" if disagreed else "agree", "disagreed": disagreed}
    return out


class EstateReadingRunner(reading.ReadingRunner):
    """Reads an estate's documents in the background, twice each, with the reader above."""

    def _work(self, claim_id: str, doc_id: str) -> None:
        with self._gate:
            try:
                claim = self.store.load(claim_id)
                doc = next(d for d in claim["documents"] if d["id"] == doc_id)
                path = self.store.files(claim_id) / doc["stored_as"]
                got = read_civil_record_twice(path, doc["kind"], self.read)
            except Exception:
                got = {"status": "failed", "problem": "The document could not be read this time."}
            try:
                self.store.set_reading(claim_id, doc_id, got, None)
            except cl.ClaimError:
                pass


# ---- the estate on the claim -----------------------------------------------------------------------------------

def _rebuild(claim: dict, today: date | None = None) -> None:
    """Work the shares out again from the family and lay each heir's own details over the result."""
    estate = claim["estate"]
    result = succession.compute(estate["family"], today)
    estate["succession"] = result
    details = estate.setdefault("details", {})
    family_people = {p["id"]: p for p in succession.everyone(estate["family"])}
    heirs = []
    for heir in result.get("heirs") or []:
        mine = details.setdefault(heir["id"], {})
        heirs.append({"id": heir["id"], "name": heir["name"], "relation": heir["relation"], "share": heir["share"],
                      "line": heir.get("line") or [], "steps": heir.get("steps") or [],
                      "country": mine.get("country") or family_people.get(heir["id"], {}).get("country") or "",
                      "email": mine.get("email") or "", "payee": mine.get("payee"),
                      "declared": mine.get("declared"), "proven": bool(mine.get("proven")),
                      "paid": mine.get("paid")})
    estate["heirs"] = heirs


def _changed(store: cl.ClaimStore, claim: dict, before: dict | None, note: str, reason: str) -> None:
    """Called under the lock after a change: note it, and withdraw an approval that no longer covers the estate."""
    claim["history"].append({"state": claim["state"], "at": cl.now(), "note": note})
    if before is not None and before != cl.estate_terms(claim):
        store.void_approval(claim, reason)


def open_estate(store: cl.ClaimStore, claim_id: str) -> dict:
    """Turns a claim by an heir into an estate claim. Nothing is known about the family yet."""
    with store.lock:
        claim = store.load(claim_id)
        if claim.get("estate"):
            return claim
        if claim["claimant"].get("relationship") != "heir":
            raise cl.ClaimError(409, "Only a claim made as an heir can be an estate claim.")
        if claim["record"].get("owner_is_organisation"):
            raise cl.ClaimError(409, "The owner on this record is an organisation, which has no heirs.")
        if claim["state"] not in cl.BEFORE_DECISION:
            raise cl.ClaimError(409, "This claim has already been decided.")
        claim["estate"] = {"family": succession.clean_family({}), "details": {}, "heirs": [], "words": "",
                           "language": "", "english": "", "asked": None, "other_law": None}
        _rebuild(claim)
        claim["history"].append({"state": claim["state"], "at": cl.now(), "note":
                                 "The claimant said the owner has died. The claim is now an estate claim."})
        store.save(claim)
        return claim


def _open_for_changes(claim: dict) -> None:
    if not claim.get("estate"):
        raise cl.ClaimError(404, "This claim is not an estate claim.")
    if claim["state"] in (cl.PAYING, cl.PAID, cl.REJECTED):
        raise cl.ClaimError(409, "The estate cannot be changed while a payment is under way or after the claim "
                                 "is closed.")


def _paid_ids(claim: dict) -> set[str]:
    return {k for k, v in (claim["estate"].get("details") or {}).items() if v.get("paid")}


def set_family(store: cl.ClaimStore, claim_id: str, family: dict, said: dict | None = None,
               today: date | None = None) -> dict:
    """Stores the family (as the model understood it, or as the claimant corrected it) and works the shares out
    again. `said` carries the intake's words. A change to the family withdraws an approval. Once an heir has
    been paid the family is fixed: a change then would change shares that have already been paid."""
    with store.lock:
        claim = store.load(claim_id)
        _open_for_changes(claim)
        estate = claim["estate"]
        cleaned = succession.clean_family(family)
        if _paid_ids(claim) and cl.digest(cleaned) != cl.digest(estate["family"]):
            raise cl.ClaimError(409, "An heir of this estate has already been paid, so the family can no longer "
                                     "be changed here. A person has to look at it.")
        before = cl.estate_terms(claim)
        estate["family"] = cleaned
        if said:
            estate.update({k: said[k] for k in ("words", "language", "english", "asked") if k in said})
        _rebuild(claim, today)
        _changed(store, claim, before, "The family of the owner was described or corrected, and the shares were "
                                       "worked out again.", "the family or the shares were changed")
        store.save(claim)
        return claim


def set_heir(store: cl.ClaimStore, claim_id: str, heir_id: str, *, country: str | None = None,
             email: str | None = None, payee: dict | None = None, declared: bool | None = None) -> dict:
    """What one heir gives: where they live, how to reach them, the bank account in their own name, and their
    statement of the declaration's points. A new bank account withdraws an approval."""
    with store.lock:
        claim = store.load(claim_id)
        _open_for_changes(claim)
        estate = claim["estate"]
        heir = next((h for h in estate["heirs"] if h["id"] == heir_id), None)
        if heir is None:
            raise cl.ClaimError(404, "There is no such heir on this estate.")
        if (estate["details"].get(heir_id) or {}).get("paid") and payee is not None:
            raise cl.ClaimError(409, "This heir has already been paid.")
        before = cl.estate_terms(claim)
        mine = estate["details"].setdefault(heir_id, {})
        if country is not None:
            mine["country"] = country
        if email is not None:
            mine["email"] = email
        if payee is not None:
            mine["payee"] = {**payee, "hash": cl.digest({"currency": payee["currency"],
                                                         "beneficiary": payee["beneficiary"]}), "set_at": cl.now()}
        if declared is not None:
            mine["declared"] = {"at": cl.now(), "points": DECLARATION} if declared else None
        _rebuild(claim)
        what = ("gave the bank account to be paid into" if payee is not None else
                "stated the points of the declaration" if declared else "gave their details")
        _changed(store, claim, before, f"{heir['name'] or 'An heir'} {what}.", "an heir's bank account was changed")
        store.save(claim)
        return claim


# ---- the proof: what ties each heir to the owner ----------------------------------------------------------------

def _full(printed: str, wanted: str) -> bool:
    return bool(printed and wanted) and proof.compare_names(printed, wanted) == "full"


class _Doc:
    """One read document of the estate, with the faults that stop it from being relied on."""

    def __init__(self, doc: dict, claim: dict, today: date, country: str = ""):
        pseudo = {"claimant": {"name": claim["claimant"]["name"], "address": "", "country": country},
                  "record": claim["record"]}
        self.seen = proof._Seen(doc, pseudo, None, today)
        self.doc, self.reading = doc, doc.get("reading") or {}
        self.kind = doc.get("kind")
        self.label = f"{doc.get('kind_label', 'Document').lower()} ({doc.get('filename', 'file')})"
        extra = self.reading.get("extra_agreement") or {}
        self.faults = self.seen.faults()
        if self.seen.read and extra.get("status") == "disagree":
            self.faults.append(f"It is {checks.HELD_WORDS}. Two separate readings disagree on the "
                               + " and the ".join(extra.get("disagreed") or ["people named"]) + ".")
        if self.seen.read and self.kind != "id" and "people" not in self.reading:
            self.faults.append("It was read without the parts each person plays in it. Add it again on the "
                               "estate view.")
        self.usable = self.seen.read and not self.faults

    def who(self, *roles: str) -> list[str]:
        return [p["name"] for p in self.reading.get("people") or [] if p["role"] in roles]

    def subject(self) -> list[str]:
        names = self.who("subject")
        return names or ([self.reading["holder_name"]] if self.reading.get("holder_name") else [])


def _link(label: str, section: str, found: list[tuple["_Doc", list[str]]], tried: list["_Doc"], missing: str) -> dict:
    """One link of the chain between an heir and the owner: proven by a usable document, or what stands in the way."""
    good = [(d, facts) for d, facts in found if d.usable]
    if good:
        doc, facts = good[0]
        return {"label": label, "basis": section, "status": "proven", "files": [doc.doc["filename"]], "facts": facts,
                "problems": []}
    if found:       # a document shows the link but cannot be relied on
        doc = found[0][0]
        return {"label": label, "basis": section, "status": "held" if doc.seen.held_reasons else "not proven",
                "files": [doc.doc["filename"]], "facts": [], "problems": doc.faults[:3]}
    waiting = [d for d in tried if d.seen.status in ("reading", "not_read")]
    if waiting:
        return {"label": label, "basis": section, "status": "being read", "files": [d.doc["filename"] for d in waiting],
                "facts": [], "problems": []}
    return {"label": label, "basis": section, "status": "missing", "files": [], "facts": [], "problems": [missing]}


def _birth(docs_: list[_Doc], child: str, parent: str, label: str) -> dict:
    births = [d for d in docs_ if d.kind == "birth_certificate"]
    found = []
    for d in births:
        parents = [p for p in d.who(*PARENT_ROLES) if _full(p, parent)]
        if any(_full(s, child) for s in d.subject()) and parents:
            found.append((d, [f"The birth certificate of {child} names {parents[0]} as a parent."]))
    return _link(label, "birth certificate", found, births,
                 f"A birth certificate of {child or 'this person'} that names {parent or 'the parent'} as a parent.")


def _death(docs_: list[_Doc], person: str, label: str) -> tuple[dict, str]:
    deaths = [d for d in docs_ if d.kind == "death_certificate"]
    found = [(d, [f"The death certificate is in the name {next(s for s in d.subject() if _full(s, person))}."
                  + (f" It gives {d.reading['date_of_death']} as the date of death." if d.reading.get("date_of_death") else "")])
             for d in deaths if any(_full(s, person) for s in d.subject())]
    link = _link(label, "death certificate", found, deaths, f"The death certificate of {person or 'this person'}.")
    when = next((d.reading.get("date_of_death") or "" for d, _ in found if d.usable), "")
    return link, when


def _shared_parent(docs_: list[_Doc], one: str, other: str, label: str) -> dict:
    births = [d for d in docs_ if d.kind == "birth_certificate"]
    mine = [d for d in births if any(_full(s, one) for s in d.subject())]
    theirs = [d for d in births if any(_full(s, other) for s in d.subject())]
    found = []
    for a in mine:
        for b in theirs:
            shared = [p for p in a.who(*PARENT_ROLES) if any(_full(q, p) or _full(p, q) for q in b.who(*PARENT_ROLES))]
            if shared and a is not b:
                doc = a if not a.usable else b      # the pair is only as good as its weaker document
                found.append((doc, [f"The birth certificates of {one} and {other} both name {shared[0]} as a parent."]))
    return _link(label, "birth certificates", found, births,
                 f"The birth certificates of {one or 'this heir'} and of {other or 'the owner'}, naming the same parent.")


def _chain(heir: dict, family: dict, docs_: list[_Doc]) -> list[dict]:
    """The links that tie one heir to the owner, in order from the owner outwards."""
    owner = family["decedent"]["name"]
    people = {p["id"]: p for p in succession.everyone(family)}
    name = heir["name"]
    relation = heir["relation"]
    line = [people[i]["name"] for i in heir.get("line") or [] if i in people]
    if relation == "spouse":
        marriages = [d for d in docs_ if d.kind == "name_change"]
        found = [(d, [f"The marriage certificate names {name} and {owner} as the two people married."])
                 for d in marriages
                 if any(_full(s, name) for s in d.who("spouse")) and any(_full(s, owner) for s in d.who("spouse"))]
        return [_link("Married to the owner", "marriage certificate", found, marriages,
                      f"A marriage certificate that names {name or 'the heir'} and {owner or 'the owner'}.")]
    if relation == "parent":
        return [_birth(docs_, owner, name, "Parent of the owner")]
    collateral = relation in ("brother or sister", "niece or nephew", "issue of a brother or sister")
    if relation.startswith("named in"):
        orders = [d for d in docs_ if d.kind == "heirship"]
        found = [(d, [f"The document names {name}."]) for d in orders
                 if any(_full(n, name) for n in d.who("heir") + [s["name"] for s in d.reading.get("shares") or []])]
        return [_link("Named in the will or the court order", "will or court order", found, orders,
                      f"The will or the court order, naming {name or 'the heir'}.")]
    links = []
    path = line + [name]                       # from the owner's child (or sibling) down to the heir
    if collateral:
        links.append(_shared_parent(docs_, path[0], owner,
                                    "Brother or sister of the owner" if len(path) == 1 else
                                    f"{path[0]} was a brother or sister of the owner"))
    else:
        links.append(_birth(docs_, path[0], owner, "Child of the owner" if len(path) == 1 else
                            f"{path[0]} was a child of the owner"))
    for above, below in zip(path, path[1:]):
        links.append(_death(docs_, above, f"{above} has died")[0])
        links.append(_birth(docs_, below, above, f"Child of {above}"))
    return links


REMAINING_RISK = ("Khutlisa read these documents and compared the names on them. It has not verified any of them "
                  "with the registry or authority that issued it.")


def build_proof(claim: dict, record: dict | None = None, today: date | None = None) -> dict:
    """For the estate and for each heir: what is proven, by which document, and what is missing.

    {"estate": {"items": [...], "ready": bool}, "heirs": [{"id", "name", "relation", "share", "identity", "links",
    "declaration", "account", "proven", "payable", "missing"}], "ready": every heir proven, "payable": [...ids],
    "held": [...ids]}. `record` is the full register record, used only to compare the owner's name."""
    today = today or date.today()
    estate = claim["estate"]
    family, result = estate["family"], estate.get("succession") or {}
    owner = family["decedent"]["name"]
    sample = is_demonstration(claim["record"].get("source"))
    docs_ = [_Doc(d, claim, today) for d in claim.get("documents") or []]
    items = []

    # The owner on the record is the person who died.
    on_record = (record or {}).get("owner_name") or ""
    if not owner:
        name_ok, name_text = False, "The name of the person who died has not been given."
    elif on_record:
        name_ok = proof.compare_names(owner, on_record) == "full" or proof.compare_names(on_record, owner) == "full"
        name_text = ("The name given for the person who died matches the owner on the record." if name_ok else
                     "The name given for the person who died does not match the owner on the record.")
    else:
        name_ok = proof.compare_with_mask(owner, claim["record"].get("owner") or "") == "full"
        name_text = ("The name given for the person who died fits the owner shown on the record." if name_ok else
                     "The name given for the person who died does not fit the owner shown on the record.")
    items.append({"key": "owner", "label": "The person who died is the owner on the record",
                  "status": "proven" if name_ok else "not proven", "files": [], "facts": [name_text] if name_ok else [],
                  "problems": [] if name_ok else [name_text]})

    death, when = _death(docs_, owner, "The owner's death certificate")
    if death["status"] == "proven" and family["decedent"]["died_on"] and when and when != family["decedent"]["died_on"]:
        death = {**death, "status": "not proven", "facts": [],
                 "problems": [f"The certificate gives {when} as the date of death, and {family['decedent']['died_on']} "
                              "was given."]}
    items.append({"key": "death", **death})
    basis = family.get("disposition")
    if basis in ("will", "court_order"):
        word = "will" if basis == "will" else "court order"
        orders = [d for d in docs_ if d.kind == "heirship"]
        stated = {(_key(n["name"]), str(succession._fraction(n["share"]))) for n in family.get("named_shares") or []
                  if _fraction_ok(n["share"])}
        found = []
        for d in orders:
            printed = {(_key(s["name"]), str(succession._fraction(s["share"]))) for s in d.reading.get("shares") or []
                       if _fraction_ok(s["share"])}
            if printed and all(any(_full(" ".join(p[0]), " ".join(s[0])) and p[1] == s[1] for p in printed) for s in stated):
                found.append((d, [f"The {word} gives the shares the family stated."]))
        items.append({"key": "basis", **_link(f"The {word} and the shares it names", word, found, orders,
                                              f"The {word}, showing each share.")})
    if basis != "court_order":
        days = (today - date.fromisoformat(when)).days if when else None
        ok = days is not None and days >= DAYS_AFTER_DEATH
        items.append({"key": "forty_days", "label": "40 days since the death", "basis": "Probate Code 13101(a)(3)",
                      "status": "proven" if ok else "missing" if days is None else "not proven", "files": [],
                      "facts": [f"{days} days have passed since the date of death on the certificate."] if ok else [],
                      "problems": [] if ok else
                      ["The date of death has to be read from the death certificate first." if days is None else
                       f"Only {days} days have passed since the death. The declaration needs {DAYS_AFTER_DEATH}."]})
    estate_ready = all(i["status"] == "proven" for i in items) and bool(result.get("computed"))

    heirs = []
    for heir in estate.get("heirs") or []:
        ids = [d for d in docs_ if d.kind == "id" and any(_full(n, heir["name"]) for n in d.seen.names)]
        good = []
        for d in ids:
            mine = _Doc(d.doc, claim, today, heir.get("country") or "")     # the issuer is checked against the heir's country
            problems = mine.faults + mine.seen.is_government_photo_id()
            if mine.seen.expired:
                problems.append("It has expired.")
            good.append((mine, problems))
        usable = [d for d, problems in good if not problems]
        if usable:
            identity = {"label": "Photo identification in the heir's own name", "status": "proven",
                        "files": [usable[0].doc["filename"]], "problems": [],
                        "facts": [f"Government photo identification in the name {heir['name']}, read twice."]}
        elif good:
            doc, problems = good[0]
            refused = doc.seen.is_government_photo_id() or any(c["blocks"] for c in doc.seen.checks)
            identity = {"label": "Photo identification in the heir's own name",
                        "status": "held" if doc.seen.held_reasons and not refused else "not proven",
                        "files": [doc.doc["filename"]], "facts": [], "problems": problems[:3]}
        else:
            waiting = [d for d in docs_ if d.kind == "id" and d.seen.status in ("reading", "not_read")]
            identity = {"label": "Photo identification in the heir's own name",
                        "status": "being read" if waiting else "missing", "files": [], "facts": [],
                        "problems": [] if waiting else [f"Government photo identification of {heir['name'] or 'this heir'}."]}
        links = _chain(heir, family, docs_)
        need_declaration = basis != "court_order"
        declared = bool(heir.get("declared"))
        declaration = {"label": "The heir's statement of the declaration's points", "needed": need_declaration,
                       "status": "proven" if declared or not need_declaration else "missing",
                       "at": (heir.get("declared") or {}).get("at"), "note": SIMULATED_DECLARATION}
        payee = heir.get("payee")
        account = {"label": "A bank account in the heir's own name", "status": "proven" if payee else "missing",
                   "currency": (payee or {}).get("currency")}
        missing = [x["problems"][0] if x["problems"] else x["label"] for x in [identity] + links if x["status"] != "proven"]
        if need_declaration and not declared:
            missing.append("The heir's statement of the declaration's points.")
        proven = not missing
        if not payee:
            missing.append("A bank account in the heir's own name.")
        heirs.append({"id": heir["id"], "name": heir["name"], "relation": heir["relation"], "share": heir["share"],
                      "country": heir.get("country"), "identity": identity, "links": links,
                      "declaration": declaration, "account": account, "proven": proven,
                      "payable": proven and bool(payee) and estate_ready, "paid": heir.get("paid"),
                      "missing": missing})
    return {"assessed": True, "sample_documents": sample,
            "estate": {"items": items, "ready": estate_ready},
            "heirs": heirs, "ready": estate_ready and bool(heirs) and all(h["payable"] or h["paid"] for h in heirs),
            "payable": [h["id"] for h in heirs if h["payable"] and not h["paid"]],
            "held": [h["id"] for h in heirs if not h["payable"] and not h["paid"]],
            "remaining_risk": REMAINING_RISK, "decided_by": checks.DECIDED_BY}


def _fraction_ok(text: str) -> bool:
    try:
        return succession._fraction(text) > 0
    except (ValueError, ZeroDivisionError):
        return False


def record_proven(store: cl.ClaimStore, claim_id: str, result: dict) -> dict:
    """Keeps which heirs the proof found proven, so the approval's terms cover it. Called under the lock by the
    approval, and whenever the estate is looked at: when a proven heir stops being proven (a document was
    removed or re-read), an approval that relied on it is withdrawn."""
    with store.lock:
        claim = store.load(claim_id)
        estate = claim["estate"]
        before = cl.estate_terms(claim)
        for heir in result["heirs"]:
            estate["details"].setdefault(heir["id"], {})["proven"] = bool(heir["proven"])
        _rebuild(claim)
        if before != cl.estate_terms(claim):
            if claim.get("approval") and claim["state"] != cl.PAYING:
                store.void_approval(claim, "the proof for an heir changed after the approval")
            store.save(claim)
        return claim


def shares(claim: dict) -> dict[str, Fraction]:
    return {h["id"]: Fraction(h["share"]) for h in claim["estate"].get("heirs") or []}


def country_name(code: str) -> str:
    return COUNTRIES.get(code or "", {}).get("name") or code or ""


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def clean_email(value: str) -> str:
    value = (value or "").strip()[:200]
    if value and not _EMAIL.fullmatch(value):
        raise cl.ClaimError(422, "Give an email address.")
    return value
