"""Loads Queensland's public unclaimed-money register into data/queensland.duckdb.

    uv run python scripts/load_queensland.py [database]

The register is read through the open data portal's API in pages of 32,000 rows (about 80 requests), loaded in
the shape the search expects, and checked against the record count and the total the portal itself reports. The
facts of the load (count, total in Australian dollars, the time it took, whether it matches the portal, and the
attribution the licence asks for) are written beside the database as queensland.json. If the portal cannot be
reached the script says so and changes nothing.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import queensland as qld  # noqa: E402


def main(db: Path = qld.DB_PATH) -> dict:
    started = time.time()
    try:
        portal = qld.portal_figures()
    except qld.PortalError as err:
        print(f"Queensland's open data portal could not be read: {err}. Nothing was changed.")
        return {}
    print(f"The portal reports {portal['records']:,} records worth {portal['amount']:,.2f} AUD.")
    fresh = Path(db).with_name(Path(db).name + ".loading")
    for leftover in (fresh, Path(str(fresh) + ".wal")):
        leftover.unlink(missing_ok=True)
    con = qld.connect(fresh)
    try:
        n = qld.load(con, qld.pages(), progress=lambda done: print(f"  {done:,} rows", flush=True))
        loaded = qld.loaded_figures(con)
    except qld.PortalError as err:
        con.close()
        fresh.unlink(missing_ok=True)
        print(f"The portal stopped answering part of the way through: {err}. Nothing was changed.")
        return {}
    con.close()
    check = qld.verify(loaded, portal)
    seconds = round(time.time() - started, 1)
    out = {"source": qld.SOURCE, "currency": qld.CURRENCY, "records": loaded["records"], "amount": loaded["amount"],
           "distinct_ids": loaded["distinct_ids"], "portal": portal, "matches_portal": check["ok"],
           "records_match": check["records_match"], "amount_match": check["amount_match"],
           "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seconds": seconds,
           "dataset": qld.DATASET_URL, "resource": qld.RESOURCE, "licence": qld.LICENCE,
           "licence_url": qld.LICENCE_URL, "attribution": qld.ATTRIBUTION}
    fresh.replace(db)
    Path(db).with_suffix(".json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"Loaded {n:,} rows worth {loaded['amount']:,.2f} AUD in {seconds} seconds.")
    print("This matches the portal's count and total." if check["ok"] else
          f"This does NOT match the portal: count {'matches' if check['records_match'] else 'differs'}, "
          f"total {'matches' if check['amount_match'] else 'differs'}.")
    print(f"wrote {db}")
    return out


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:2]))
