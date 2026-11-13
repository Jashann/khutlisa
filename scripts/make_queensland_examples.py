"""Reads a hand-picked list of well-known organisations out of Queensland's register and writes what it says.

    uv run python scripts/make_queensland_examples.py [database]

Writes src/khutlisa/queensland_examples.json, which the "who is owed" screen shows beside California's examples.
Each line is one record: an organisation that is owed money, the amount in Australian dollars, the organisation
that sent the money to the Public Trustee, and the date it was received. The pairs were chosen by a person and
every amount is read from data/queensland.duckdb. The script stops if an owner name would not pass the strict
organisation rule, so no person can be listed. Nothing here is converted into another currency.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import queensland as qld  # noqa: E402
from khutlisa.server import shown_as_organisation  # noqa: E402

OUT = ROOT / "src" / "khutlisa" / "queensland_examples.json"

# (owner as the register writes it, the sender as the register writes it, the name to show for each)
CHOSEN = [
    ("TELSTRA CORPORATION LIMITED", "ENERGEX LIMITED", "Telstra Corporation", "Energex"),
    ("SUNCORP INSURANCE", "UNCM QLD HEALTH", "Suncorp Insurance", "Queensland Health"),
    ("RACQ INSURANCE PTY LIMITED", "GIO INSURANCE", "RACQ Insurance", "GIO Insurance"),
    ("WOOLWORTHS LIMITED", "GIO INSURANCE", "Woolworths", "GIO Insurance"),
    ("MYER PTY LTD", "GIO INSURANCE", "Myer", "GIO Insurance"),
    ("NATIONAL AUSTRALIA BANK", "GIO INSURANCE", "National Australia Bank", "GIO Insurance"),
    ("BANK OF QUEENSLAND LIMITED", "QUEENSLAND GOVERNMENT", "Bank of Queensland", "Queensland Government"),
    ("UNIVERSITY OF QUEENSLAND", "ORIGIN ENERGY (ELECTRICITY)", "The University of Queensland", "Origin Energy"),
]


def main(db: Path = qld.DB_PATH) -> dict:
    if not Path(db).exists():
        print(f"{db} is not there, so {OUT.name} is left as it is.")
        return {}
    con = duckdb.connect(str(db), read_only=True)
    rows = []
    try:
        total, amount = con.execute("select count(*), sum(amount) from records").fetchone()
        for owner, sender, shown, sender_shown in CHOSEN:
            if not shown_as_organisation(owner):
                raise SystemExit(f"{owner!r} does not pass the organisation rule; it cannot be listed.")
            hit = con.execute("select amount, received, count(*) over () from records where owner_name = ? and "
                              "holder_name = ? order by amount desc limit 1", [owner, sender]).fetchone()
            if hit is None:
                print(f"  not in the register any more: {owner} / {sender}")
                continue
            rows.append({"owner": shown, "as_written": owner, "amount": round(float(hit[0]), 2), "currency": qld.CURRENCY,
                         "sent_by": sender_shown, "sent_by_as_written": sender, "received": hit[1],
                         "records_for_this_pair": int(hit[2])})
    finally:
        con.close()
    rows.sort(key=lambda r: -r["amount"])
    out = {"source": qld.SOURCE, "currency": qld.CURRENCY, "owner_records": int(total), "amount": round(float(amount), 2),
           "examples": rows, "attribution": qld.ATTRIBUTION, "licence": qld.LICENCE, "licence_url": qld.LICENCE_URL,
           "dataset": qld.DATASET_URL, "claim_url": qld.CLAIM_URL,
           "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "note": "Amounts are Australian dollars as the register gives them. They are not converted and not "
                   "added to California's figures."}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for r in rows:
        print(f"  {r['owner']} is owed {r['amount']:,.2f} AUD. Sent by {r['sent_by']} ({r['received']}).")
    print(f"wrote {OUT}")
    return out


if __name__ == "__main__":
    main(*(Path(a) for a in sys.argv[1:2]))
