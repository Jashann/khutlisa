"""Finds the holders that report a very large share of the register and writes their keys to a small file.

    uv run python scripts/make_generic_holders.py [database]

Writes src/khutlisa/generic_holders.json, which match.py reads. A holder is written many ways in California's file
("WELLS FARGO BANK NA", "WELLS FARGO BANK NA (APECS 1009)"), so holders are first grouped under the key
`match.holder_key` gives them. A key is kept when the holders under it reported at least one owner record in a
thousand. Naming such a holder says little about who an owner is: for a very common name, a record from that
holder in a big-city postcode is there by chance (see `strength_of` in match.py).

The file holds organisation names and counts only: holders are the companies, banks and offices that reported the
money, and a holder with this many records is never a private person. Read the printed list after a new load.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa.match import GENERIC_HOLDERS_PATH, holder_key  # noqa: E402
from khutlisa.registers import DB_PATH  # noqa: E402

SHARE = 1000          # a key is kept when it reported at least one owner record in this many
WRITTEN_AS = 3        # how many of the ways each holder is written are kept as examples


def main(db: Path = DB_PATH, out: Path = GENERIC_HOLDERS_PATH) -> dict:
    con = duckdb.connect(str(db), read_only=True)
    try:
        total = con.execute("select count(*) from records").fetchone()[0]
        rows = con.execute("select holder_name, count(*) from records where holder_name is not null and "
                           "holder_name <> '' group by 1").fetchall()
    finally:
        con.close()
    at_least = -(-total // SHARE)
    counts: dict[str, int] = defaultdict(int)
    written: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for name, n in rows:
        key = holder_key(name)
        if key:
            counts[key] += n
            written[key].append((n, name))
    holders = [{"key": key, "owner_records": n,
                "written_as": [name for _, name in sorted(written[key], reverse=True)[:WRITTEN_AS]]}
               for key, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n >= at_least]
    made = {"made_by": "scripts/make_generic_holders.py", "made_on": date.today().isoformat(),
            "rule": f"Holders grouped by match.holder_key that reported at least one owner record in {SHARE:,}.",
            "owner_records": total, "at_least": at_least, "holder_names_in_the_register": len(rows),
            "owner_records_under_these_holders": sum(h["owner_records"] for h in holders), "holders": holders}
    out.write_text(json.dumps(made, indent=1) + "\n")
    print(f"{len(holders)} holder keys reported at least {at_least:,} of {total:,} owner records each, "
          f"{made['owner_records_under_these_holders']:,} between them "
          f"({100 * made['owner_records_under_these_holders'] / total:.1f}% of the register).")
    print(f"wrote {out}")
    return made


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:2]))
