"""Asks the live Airwallex sandbox which corridors exist, and keeps the answers.

    uv run python scripts/discover_corridors.py [--refresh] [--rates] [--conversions] [--countries MX,JP,...]

For every country that an owner in data/books.parquet lives in, it asks Airwallex for the beneficiary schema by
local rails in the country's own currency, by SWIFT in that currency and by SWIFT in US dollars; and for every
currency it takes the indicative rate, a real quote at six sizes from 10 to 1,000,000 US dollars, a real quote at
three lock lengths, and a quote back into US dollars. With --conversions it also converts one US dollar of
sandbox money into each wallet currency, which is the only way to learn which currencies can be held. It reads
the fees Airwallex charged on the transfers this account has made.

The answers go to src/khutlisa/airwallex_corridors.json, each with the time it was fetched. What the file already
holds is not asked again (--refresh asks everything again, --rates asks only the rates and quotes again), so the discovery runs once and is reused. The client
paces its calls under the sandbox's limit of ten requests a second for one endpoint. Needs the sandbox keys; the
keys are never printed.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import airwallex as awx  # noqa: E402
from khutlisa import book, corridors  # noqa: E402


def main(argv: list[str]) -> int:
    refresh, conversions = "--refresh" in argv, "--conversions" in argv
    rates_again = "--rates" in argv          # ask every rate and quote again, and keep the schemas
    chosen = next((argv[i + 1] for i, a in enumerate(argv) if a == "--countries" and i + 1 < len(argv)), None)
    if chosen:
        countries = [c.strip().upper() for c in chosen.split(",") if c.strip()]
    else:
        books = book.books()
        if books is None:
            print("data/books.parquet has not been made yet. Run scripts/make_books.py first.")
            return 1
        seen: dict[str, int] = {}
        for claims in books._claims.values():
            for country, cents, _ in claims:
                seen[country] = seen.get(country, 0) + cents
        countries = [c for c in sorted(seen, key=lambda c: -seen[c]) if c != book.UNPLACED]
    try:
        client = awx.AirwallexClient(*awx.load_credentials())
    except awx.CredentialsError as err:
        print(f"The Airwallex sandbox keys are not set up: {err}")
        return 1
    started = time.time()
    known = None if refresh else corridors.load()
    if known and rates_again:
        known = {**known, "currencies": {}}
    try:
        found = corridors.discover(client, countries, known=known,
                                   try_conversions=conversions, progress=lambda line: print("  " + line, flush=True))
    finally:
        client.close()
    corridors.save(found)
    rows = found["corridors"].values()
    print(f"{len(found['corridors'])} countries: {sum(1 for r in rows if r['local'].get('available'))} with a local "
          f"schema, {sum(1 for r in rows if r['swift'].get('available') or r['swift_usd'].get('available'))} with a "
          f"SWIFT schema, {sum(1 for r in rows if not (r['local'].get('available') or r['swift'].get('available') or r['swift_usd'].get('available')))} with neither.")
    print(f"{sum(1 for c in found['currencies'].values() if c.get('quotable'))} currencies quoted; "
          f"{sum(1 for c in found['conversions'].values() if c.get('held'))} converted into a held balance, "
          f"{sum(1 for c in found['conversions'].values() if not c.get('held'))} refused.")
    print(f"took {time.time() - started:.0f} seconds; wrote {corridors.FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
