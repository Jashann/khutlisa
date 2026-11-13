"""Writes the book of every holder: what each one reported for owners abroad in California's file.

    uv run python scripts/make_books.py [database] [output file]

Writes data/books.parquet: one line for each property held for an owner whose last known address is in another
country, with the holder as the file writes it, the owner's country, the amount and the property type. No
owner's name or street is in it. The "Book" screen plans from this file (khutlisa.book).
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import book  # noqa: E402
from khutlisa.registers import DB_PATH  # noqa: E402


def main(db: Path = DB_PATH, out: Path = book.BOOKS_PATH) -> int:
    if not Path(db).exists():
        print(f"{db} is not there, so {out} is left as it is.")
        return 0
    con = duckdb.connect(str(db), read_only=True)
    try:
        rows = book.build(con)
    finally:
        con.close()
    book.write(rows, out)
    made = book.Books(rows)
    top = made.top(5)
    print(f"{len(rows):,} properties worth ${sum(r[2] for r in rows):,.2f} for owners abroad, in the books of "
          f"{len(made._index):,} holders.")
    for h in top:
        print(f"  {h['name'][:50]:50} {h['properties']:>7,} ${h['amount']:>15,.2f}  {h['countries']} countries")
    print(f"wrote {out}")
    return len(rows)


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:3]))
