"""The demonstration records and the demonstration people.

California's file holds real private individuals, so nothing from it can be claimed in a walk-through. The
invented people a walk-through follows have invented records, and those live here, in `demonstration.json`,
apart from the register. A search runs over California's owner records and over these records in one pass
(`match.find` takes both connections). A demonstration record carries the source "DEMO", is marked once on its
card, and is never counted as one of California's records.
"""
from __future__ import annotations

import json
import re
import threading
from functools import lru_cache
from pathlib import Path

import duckdb

from .names import normalise, phonetic

FILE = Path(__file__).with_name("demonstration.json")
SOURCE = "DEMO"
# "SAMPLE" is the older mark, used by registers made up entirely of invented records.
DEMONSTRATION_SOURCES = frozenset({SOURCE, "SAMPLE"})

# Record words a Spanish speaker says another way ("APT" is "apartamento", "AND" may be "y").
_SPOKEN_OTHERWISE = frozenset({"APT", "AND"})

_COLUMNS = ["source", "record_id", "owner_name", "owner_norm", "owner_street", "owner_city", "owner_region",
            "owner_postcode", "owner_country", "amount", "currency", "holder_name", "holder_city", "holder_region",
            "property_type", "phon_first", "phon_last"]


def is_demonstration(source: str | None) -> bool:
    """True for a record that Khutlisa added itself and that is no real property."""
    return (source or "") in DEMONSTRATION_SOURCES


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def records() -> list[dict]:
    return load()["records"]


def people() -> list[dict]:
    """The demonstration people, with everything the screens need to fill a form for them."""
    return load()["people"]


def spoken_requirements(person: dict) -> dict[str, list[str]]:
    """The words a recogniser must hear in a demonstration person's two sound files, worked out from her own
    records, so the sound, the prepared text and the records cannot drift apart.

    "words" is her first account: every part of her name, the city and the holder of her main record, and the
    years in the line about her. "answer" is her reply to the follow-up question: the street of that record with
    its numbers, the postcode, and the holder of every other record of hers at that address. Empty for a person
    whose account is typed.
    """
    if not person.get("audio"):
        return {}
    main = next(r for r in records() if r["record_id"] == person["main_record"])
    here = [r for r in records() if r is not main and (r["owner_street"], r["owner_postcode"]) ==
            (main["owner_street"], main["owner_postcode"])]
    first = normalise(f"{person['name']} {main['owner_city']} {main['holder_name']}").split()
    first += re.findall(r"\b(?:19|20)\d\d\b", person["about"])
    answer = [w for w in normalise(main["owner_street"]).split() if w not in _SPOKEN_OTHERWISE]
    answer.append(main["owner_postcode"])
    for r in here:
        answer += [w for w in normalise(r["holder_name"]).split() if w not in _SPOKEN_OTHERWISE]
    return {"words": list(dict.fromkeys(first)), "answer": list(dict.fromkeys(answer))}


def missing_words(heard: str, required: list[str]) -> list[str]:
    """The required words that are not in `heard` as whole words. Case, accents and punctuation do not count;
    a year or postcode heard in pieces ("20-15", "93 905") does."""
    said = set(normalise(heard).split())
    return [w for w in required if w not in said]


class DemoStore:
    """The demonstration records as a table of their own, in memory, in the shape the register has."""

    def __init__(self) -> None:
        self._con: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    def _build(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:")
        con.execute(f"create table records ({', '.join(c + (' double' if c == 'amount' else ' varchar') for c in _COLUMNS)})")
        for r in records():
            norm = normalise(r["owner_name"])
            words = norm.split()
            con.execute(f"insert into records values ({','.join('?' * len(_COLUMNS))})", [
                SOURCE, r["record_id"], r["owner_name"], norm, r["owner_street"], r["owner_city"], r["owner_region"],
                r["owner_postcode"], r["owner_country"], float(r["amount"]), "USD", r["holder_name"], "", "",
                r["property_type"], phonetic(words[0]), phonetic(words[-1])])
        return con

    def cursor(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is None:
                self._con = self._build()
            return self._con.cursor()

    def count(self) -> int:
        return len(records())

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None
