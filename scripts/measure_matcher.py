"""Measures the matcher on real records, without showing any of them. It prints counts and percentages only.

Three parts, all seeded so that a second run prints the same figures.

1. Finding the right person. For a random sample of individual owners it rebuilds what that person might type
   today (their name in another order, respelled, with a typo, as a nickname, in the wrong boxes) together with
   the city and postcode on their own record, and checks whether a record with their name and city is among the
   first three results. A second sample of people with a DE or DE LA surname is searched with the surname typed
   joined, typed apart and typed without the particle.
2. Not finding the wrong person. For the same sample it searches for a DIFFERENT, invented person who shares the
   family name and the city, or the family name and the postcode, and counts what comes back as a strong match
   and as a possible match. The invented given name is taken from a fixed list and is never one on the record. A
   harder variant uses the commonest other given name that the register holds for that family name, so that real
   strangers with that full name exist, and two variants also name the holder on the sampled record, one with
   the city and one with the postcode.
3. Invented common names in big-city postcodes, with the number of strong and possible matches for each, with
   the name and postcode alone and then also naming each of three very large holders.

The search never uses a street. Part 1 checks that on every sampled person: the search is run again with the
street from their own record added, and the script counts the searches whose results differ in any way.

What it cannot show: part 1 reuses the record's own city and postcode, which a real person may not remember, and
nobody has labelled true matches by hand, so "found" means "a record with that name and city came back", and
part 2 cannot tell a stranger from a second record of the invented person's real namesake.

Usage: uv run python scripts/measure_matcher.py [people] [--db PATH] [--any-country] [--min-amount N]
"""
from __future__ import annotations

import argparse
import random
import time
from collections import Counter

import duckdb

from khutlisa.match import COLUMNS, COMMON_NAME_PLACES, History, Place, family_filter, find, given_kind, is_generic_holder
from khutlisa.names import NOISE, ORG_WORDS, PARTICLES, Person, is_organisation, nickname_forms, romanisations, tokens

SEED = 7
# Given names from several cultures for the invented "different person".
OTHER = ["ROBERTO", "HIROSHI", "MEI", "FATIMA", "OLGA", "KWAME", "INGRID", "PABLO", "YUKI", "ANIL", "THABO",
         "SIOBHAN", "DMITRI", "NGOZI", "LEILANI", "SVEN"]
# Invented people: a common full name and a real big-city postcode. Nobody in particular.
COMMON = [("MARIA", "GARCIA", "90011"), ("JOSE", "HERNANDEZ", "90011"), ("THANH", "NGUYEN", "95122"),
          ("JOHN", "SMITH", "92101"), ("WEI", "CHEN", "91754"), ("MARIA", "SANTOS", "94015"),
          ("JUAN", "LOPEZ", "90022")]
COMMON_HOLDERS = ["Wells Fargo Bank", "Bank of America", "Citibank"]
WITH_STREET = "same order, with the street on the record (the search does not use it)"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SWAPPED = "given and family in the wrong boxes"
PARTICLE_SQL = (r"regexp_matches(owner_norm, '^(DE LA|DELA|DE LOS|DELOS|DE) [A-Z]{4,} [A-Z]{3,}( [A-Z]+)?$') "
                r"or regexp_matches(owner_norm, '^(DELA|DELOS)[A-Z]{4,} [A-Z]{3,}( [A-Z]+)?$')")


def pct(part: int, whole: int) -> str:
    return f"{part} of {whole} ({100 * part / whole:.0f}%)" if whole else "0 of 0"


class Register:
    """The register, plus a way to run many searches for one family name against a small copy of its rows."""

    def __init__(self, path: str):
        self.con = duckdb.connect(path, read_only=True)
        self.catalog = self.con.execute("select current_database()").fetchone()[0]
        self.table = f'"{self.catalog}".main.records'
        self.searches = 0
        self.seconds = 0.0

    def narrow(self, histories: list[History]) -> None:
        """Copies the rows that pass the family-name filter of any of these searches into a temporary table named
        `records`, which the searches then read. The results are the same as on the full table, which is read
        once here instead of once per search."""
        parts, params = [], []
        for h in histories:
            f = family_filter(h)
            if f:
                parts.append(f"({f[0]})"); params += f[1]
        cols = ", ".join(COLUMNS + ["phon_first", "phon_last"])
        started = time.perf_counter()
        self.con.execute(f"create or replace temp table records as select {cols} from {self.table} where "
                         + (" or ".join(parts) or "false"), params)
        self.seconds += time.perf_counter() - started

    def widen(self) -> None:
        self.con.execute("drop table if exists temp.main.records")

    def find(self, history: History, top: int = 5000) -> list:
        self.searches += 1
        return find(self.con, history, top=top)


def sample_people(reg: Register, n: int, where: str, rng_seed: int) -> list[dict]:
    rows = reg.con.execute(
        f"""select * from (select owner_name, owner_norm, owner_street, owner_city, owner_region, owner_postcode,
            owner_country, holder_name from {reg.table} where {where})
            using sample reservoir({max(n * 40, 400)} rows) repeatable ({rng_seed})""").fetchall()
    people = []
    for name, norm, street, city, region, zc, country, holder in sorted(rows, key=lambda r: (r[1] or "", r[3] or "", r[2] or "")):
        toks = tokens(norm)
        if is_organisation(name) or not city or any(t in ORG_WORDS for t in toks):
            continue
        people.append({"toks": toks, "norm": norm, "street": street or "", "city": city, "region": region or "",
                       "zip": (zc or "")[:5], "country": country or "", "holder": holder or ""})
    random.Random(rng_seed).shuffle(people)
    return people


def own_place(p: dict) -> Place:
    return Place(city=p["city"], region=p["region"], postcode=p["zip"])


def found_in_top(hits: list, p: dict, top: int = 3) -> bool:
    """The same person can have several records; any record with their exact name and city counts."""
    return any(h.record["owner_norm"] == p["norm"] and (h.record["owner_city"] or "").upper() == p["city"].upper()
               for h in hits[:top])


def own_record(hits: list, p: dict):
    return next((h for h in hits if h.record["owner_norm"] == p["norm"]
                 and (h.record["owner_city"] or "").upper() == p["city"].upper()), None)


def typo_dropped(name: str, rng: random.Random) -> str:
    i = rng.randrange(1, len(name))
    return name[:i] + name[i + 1:]


def typo_changed(name: str, rng: random.Random) -> str:
    i = rng.randrange(1, len(name))
    return name[:i] + rng.choice([c for c in LETTERS if c != name[i]]) + name[i + 1:]


def positive_variants(p: dict, rng: random.Random) -> dict[str, History]:
    family, given = p["toks"][0], p["toks"][1:]
    place, now = [own_place(p)], p["country"]
    out = {
        "same order": History(Person(given, [family]), place, [], now),
        "given name first": History(Person(given[:1], [family], aliases=[" ".join(given[:1] + [family])]), place, [], now),
        "middle name dropped": History(Person(given[:1], [family]), place, [], now),
        SWAPPED: History(Person([family], given[:1]), place, [], now),
        "name only, no place": History(Person(given, [family]), [], [], ""),
    }
    alt = sorted(romanisations(family, 30) - {family})
    if alt:
        out["respelled family name"] = History(Person(given, [rng.choice(alt)]), place, [], now)
    first = given[0]
    if len(first) >= 4:
        out["one letter dropped from the given name"] = History(Person([typo_dropped(first, rng)] + given[1:], [family]), place, [], now)
        out["one letter changed in the given name"] = History(Person([typo_changed(first, rng)] + given[1:], [family]), place, [], now)
    nick = sorted(nickname_forms(first))
    if nick:
        out["nickname in place of the given name"] = History(Person([rng.choice(nick)] + given[1:], [family]), place, [], now)
    if p["street"]:
        out[WITH_STREET] = History(
            Person(given, [family]), [Place(city=p["city"], region=p["region"], postcode=p["zip"], street=p["street"])], [], now)
    if p["holder"]:
        out["same order, with the holder on the record"] = History(Person(given, [family]), place, [p["holder"]], now)
    return out


POSITIVE_ORDER = ["same order", "given name first", "respelled family name", "middle name dropped",
                  "one letter dropped from the given name", "one letter changed in the given name",
                  "nickname in place of the given name", SWAPPED, "name only, no place",
                  WITH_STREET, "same order, with the holder on the record"]


def shape(hits: list) -> list[tuple]:
    """Everything a search reply is made from, record by record, in order."""
    return [(h.record["record_id"], h.record["owner_norm"], h.score, h.strength, tuple(h.reasons), tuple(h.doubts))
            for h in hits]


def different_given(p: dict, rng: random.Random) -> str:
    return rng.choice([o for o in OTHER if not given_kind(o, p["toks"])])


def common_given(reg: Register, p: dict) -> str:
    """The commonest second word among the register's records that start with this family name, other than this
    person's own given names. Used only as a search word; never printed."""
    family = p["toks"][0]
    rows = reg.con.execute(
        "select split_part(owner_norm, ' ', 2) g, count(*) n from records where split_part(owner_norm, ' ', 1) = ? "
        "group by 1 order by n desc, g limit 40", [family]).fetchall()
    for g, _ in rows:
        if len(g) >= 3 and g.isalpha() and g not in NOISE and g not in ORG_WORDS and g not in PARTICLES \
                and not given_kind(g, p["toks"]) and not any(given_kind(t, [g]) for t in p["toks"][1:] if len(t) > 1):
            return g
    return ""


class Tally:
    """Counts for one kind of wrong-person search."""

    def __init__(self):
        self.n = self.any_strong = self.strong = self.any_possible = self.possible = self.high = 0

    def add(self, hits: list) -> None:
        strong = sum(1 for h in hits if h.strength == "strong")
        possible = len(hits) - strong
        self.n += 1
        self.strong += strong; self.any_strong += strong > 0
        self.possible += possible; self.any_possible += possible > 0
        self.high += sum(1 for h in hits if h.score >= 0.6)

    def line(self, label: str) -> str:
        n = max(self.n, 1)
        return (f"  {label}: searches {self.n}; any strong match in {pct(self.any_strong, self.n)}, "
                f"{self.strong / n:.2f} strong per search; any possible match in {pct(self.any_possible, self.n)}, "
                f"{self.possible / n:.1f} possible per search; {self.high / n:.1f} per search have 0.60 points or more")


def particle_forms(p: dict) -> tuple[str, list[str], list[str]] | None:
    """(how the record writes it, [particle words, main word], given names) for a DE / DE LA surname."""
    toks = p["toks"]
    for prefix in ("DELOS", "DELA"):
        if toks[0].startswith(prefix) and len(toks[0]) - len(prefix) >= 4:
            return "joined", [prefix[:2], prefix[2:], toks[0][len(prefix):]], toks[1:]
    run = []
    for t in toks:
        if t in {"DE", "LA", "LOS", "DELA", "DELOS"}:
            run.append(t)
        else:
            break
    if not run or len(toks) < len(run) + 2:
        return None
    parts = [x for t in run for x in ({"DELA": ["DE", "LA"], "DELOS": ["DE", "LOS"]}.get(t, [t]))]
    return ("apart" if len(run) == len(parts) else "half joined"), parts + [toks[len(run)]], toks[len(run) + 1:]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("people", nargs="?", type=int, default=150)
    ap.add_argument("--db", default="data/registers.duckdb")
    ap.add_argument("--any-country", action="store_true", help="sample owners in every country, not only abroad")
    ap.add_argument("--min-amount", type=float, default=100.0)
    args = ap.parse_args()
    rng = random.Random(SEED)
    reg = Register(args.db)
    started = time.perf_counter()
    base = f"amount >= {float(args.min_amount)}"
    abroad = base if args.any_country else base + " and owner_country not in ('US', '')"

    people = [p for p in sample_people(reg, args.people, abroad, SEED)
              if 2 <= len(p["toks"]) <= 4 and all(len(t) >= 2 for t in p["toks"][:2]) and p["toks"][0] not in PARTICLES
              ][:args.people]
    print(f"people tested: {len(people)} (seed {SEED})")

    found = Counter(); tried = Counter(); labelled = Counter()
    wrong = {k: Tally() for k in ["invented given name, same family name and city",
                                  "invented given name, same family name and postcode",
                                  "common given name for that family name, same city",
                                  "common given name for that family name, same postcode",
                                  "common given name, same city, and the holder on the sampled record",
                                  "common given name, same postcode, and the holder on the sampled record"]}
    no_common = 0
    street_tried = street_changed = 0
    big_holder = common_name = both = 0
    for p in people:
        family = p["toks"][0]
        variants = positive_variants(p, rng)
        other = different_given(p, rng)
        # The wrong-boxes search looks for a given name as a family name, which is far too many rows to copy, so
        # it reads the full table. Every other search for this person reads one small copy.
        reg.widen()
        direct = {SWAPPED: reg.find(variants[SWAPPED])}
        reg.narrow([h for k, h in variants.items() if k != SWAPPED] + [History(Person([other], [family]))])
        kept: dict[str, list] = {}
        for kind, h in variants.items():
            hits = direct.get(kind) or reg.find(h)
            kept[kind] = hits
            tried[kind] += 1
            if found_in_top(hits, p):
                found[kind] += 1
            mine = own_record(hits, p)
            if mine is not None and mine.strength == "strong":
                labelled[kind] += 1
        if WITH_STREET in kept:
            street_tried += 1
            street_changed += shape(kept[WITH_STREET]) != shape(kept["same order"])
        mine = own_record(kept.get("same order, with the holder on the record") or [], p)
        if mine is not None:
            large = is_generic_holder(p["holder"])
            common_one = int(mine.evidence.get("name_places") or 0) > COMMON_NAME_PLACES
            big_holder += large; common_name += common_one; both += large and common_one
        keys = list(wrong)
        wrong[keys[0]].add(reg.find(History(Person([other], [family]), [Place(city=p["city"], region=p["region"])])))
        if p["zip"]:
            wrong[keys[1]].add(reg.find(History(Person([other], [family]), [Place(postcode=p["zip"])])))
        common = common_given(reg, p)
        if not common:
            no_common += 1
            continue
        wrong[keys[2]].add(reg.find(History(Person([common], [family]), [Place(city=p["city"], region=p["region"])])))
        if p["zip"]:
            wrong[keys[3]].add(reg.find(History(Person([common], [family]), [Place(postcode=p["zip"])])))
        if p["holder"]:
            wrong[keys[4]].add(reg.find(History(Person([common], [family]), [Place(city=p["city"], region=p["region"])],
                                                [p["holder"]])))
            if p["zip"]:
                wrong[keys[5]].add(reg.find(History(Person([common], [family]), [Place(postcode=p["zip"])],
                                                    [p["holder"]])))
    reg.widen()

    print("1. the right person: a record with their name and city is in the first three results")
    for kind in POSITIVE_ORDER:
        if tried[kind]:
            print(f"  {kind}: {pct(found[kind], tried[kind])}; their record is labelled strong in {pct(labelled[kind], tried[kind])}")
    print(f"  adding the street from their own record changed the results of {street_changed} of {street_tried} searches")
    print(f"  with the holder named: the holder is one of the very large holders for {big_holder} people, the name is "
          f"very common (in more than {COMMON_NAME_PLACES} places) for {common_name}, and both hold for {both}")

    particle = []
    for p in sample_people(reg, max(args.people, 40), f"{base} and ({PARTICLE_SQL})", SEED + 1):
        forms = particle_forms(p)
        if forms and all(len(g) >= 2 for g in forms[2][:1]) and forms[2]:
            particle.append((p, forms))
        if len(particle) >= max(40, args.people // 2):
            break
    print(f"   people with a DE or DE LA surname: {len(particle)}")
    p_found = Counter(); p_tried = Counter()
    for p, (how, parts, given) in particle:
        typed = {"joined": "".join(parts), "apart": " ".join(parts), "without the particle": parts[-1]}
        searches = {k: History(Person(given, [v]), [own_place(p)], [], p["country"]) for k, v in typed.items() if k != how}
        reg.narrow(list(searches.values()))
        for kind, h in searches.items():
            p_tried[kind] += 1
            p_found[kind] += found_in_top(reg.find(h), p)
    reg.widen()
    for kind in ("joined", "apart", "without the particle"):
        print(f"  surname typed {kind}, where the record writes it another way: {pct(p_found[kind], p_tried[kind])}")

    print("2. the wrong person: a different, invented person is searched for; every result is someone else")
    for label, tally in wrong.items():
        print(tally.line(label))
    if no_common:
        print(f"  (no common other given name was found for {no_common} of the family names)")

    print("3. invented common names in a big-city postcode")
    for given, family, zc in COMMON:
        for label, holders in [("name and postcode", [])] + [(f"name, postcode and the holder {h}", [h]) for h in COMMON_HOLDERS]:
            hits = reg.find(History(Person([given], [family]), [Place(postcode=zc)], holders))
            strong = sum(1 for h in hits if h.strength == "strong")
            named = sum(1 for h in hits if h.evidence.get("holder") and h.evidence.get("postcode"))
            places = max((int(h.evidence.get("name_places") or 0) for h in hits), default=0)
            print(f"  {given} {family} {zc}, {label}: {strong} strong, {len(hits) - strong} possible"
                  f"{' or more' if len(hits) >= 5000 else ''}, {sum(1 for h in hits if h.score >= 0.6)} with 0.60 points or more"
                  f"; the name is found in {places} places"
                  + (f"; {named} records in that postcode are from a holder of that name" if holders else ""))
    print(f"searches run: {reg.searches}; elapsed {time.perf_counter() - started:.0f} seconds")


if __name__ == "__main__":
    main()
