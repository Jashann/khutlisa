"""Writes data/totals.json from the loaded registers, counting each property once.

Usage: uv run python scripts/make_totals.py [database] [output file]
"""
import json
import sys
from pathlib import Path

import duckdb

from khutlisa.registers import DB_PATH, describe_totals, totals

SOURCE = "California State Controller, unclaimed property records, file dated 2026-11-04"
URL = "https://www.sco.ca.gov/upd_download_property_records.html"


def main(db: Path = DB_PATH, out: Path | None = None) -> dict:
    out = out or Path(db).parent / "totals.json"
    con = duckdb.connect(str(db), read_only=True)
    try:
        made = {"source": SOURCE, "url": URL, **totals(con)}
    finally:
        con.close()
    out.write_text(json.dumps(made, indent=1))
    print(describe_totals(made))
    print(f"wrote {out}")
    return made


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:3]))
