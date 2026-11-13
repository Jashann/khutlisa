"""Adds up, by holder, the properties California holds for owners abroad, and writes what the file says.

    uv run python scripts/make_holders.py [database]

Writes src/khutlisa/holders_abroad.json, which the "For holders" screen shows. A holder is the organisation that
reported a property. Every figure is read from data/registers.duckdb by khutlisa.holders.compute: each property
once, under its holder, when at least one owner has a last known address in another country. The script prints
the lists it wrote and every spelling the hand-read company families caught, so a person can read them: holder
names are organisations, and a name that could be a person's is counted and never listed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import holders  # noqa: E402
from khutlisa.registers import DB_PATH  # noqa: E402

SOURCE = "California State Controller, unclaimed property records, file dated 2026-11-04"
URL = "https://www.sco.ca.gov/upd_download_property_records.html"


def main(db: Path = DB_PATH) -> dict:
    if not Path(db).exists():
        print(f"{db} is not there, so {holders.FILE.name} is left as it is.")
        return {}
    con = duckdb.connect(str(db), read_only=True)
    try:
        made = holders.compute(con)
        caught = con.execute("select distinct holder_name from records where holder_name is not null").fetchall() \
            if "--spellings" in sys.argv else []
    finally:
        con.close()
    out = {"source": SOURCE, "url": URL, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "rule": holders.RULE, **made}
    holders.FILE.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{made['holders_with_an_owner_abroad']:,} holders reported at least one property for an owner abroad: "
          f"{made['properties']:,} properties worth ${made['amount']:,.2f}.")
    print(f"{made['passed_over_as_possibly_a_person']:,} holders that rank among those listed were passed over, "
          "because the name could be a person's or has not been read by hand (see holders.READ_BY_HAND).")
    print("By dollars:")
    for h in made["by_amount"]:
        print(f"  {h['name'][:60]:60} {h['properties']:>7,} ${h['amount']:>15,.2f}  ({h['spellings']} spellings)")
    print("By properties:")
    for h in made["by_properties"]:
        print(f"  {h['name'][:60]:60} {h['properties']:>7,} ${h['amount']:>15,.2f}")
    for shown, _ in holders.FAMILIES:        # for reading: what each family caught, across the whole file
        names = sorted({w for (w,) in caught if holders.family(w) == shown})
        if names:
            print(f"{shown}: {len(names)} spellings in the whole file, for example {names[:12]}")
    print(f"wrote {holders.FILE}")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(*(Path(a) for a in args[:1]))
