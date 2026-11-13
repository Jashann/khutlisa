"""Queensland's public unclaimed-money register, as a second source for the search.

The Public Trustee of Queensland publishes the register on the State's open data portal under the Creative
Commons Attribution 4.0 licence. This module reads it through the portal's own API (the direct CSV link may
answer 202 and send nothing), loads it into a DuckDB file of its own in the shape the search expects, and checks
the load against the count and the total the portal itself reports.

It is kept apart from California's file on purpose: its money is in Australian dollars, and nothing here adds
Australian dollars to US dollars. The search opens both files and runs over them in one pass (server.Store).

    source code   AU-QLD
    currency      AUD
    fields        ClientId_ActNo, Owner, Amount, SenderName, DateRec, PCode

The same privacy rule applies as everywhere else: a person's name is masked before it leaves the server and only
a clear organisation is shown in full (server.public_record).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterator

import duckdb

from .registers import RECORDS_TABLE, _flush, add_search_column

SOURCE = "AU-QLD"
CURRENCY = "AUD"
COUNTRY = "AU"
DATASET = "unclaimed-monies"
RESOURCE = "872065ae-ddfd-4b5f-ad15-e1935dadd883"
API = "https://www.data.qld.gov.au/api/3/action/datastore_search_sql"
DATASET_URL = "https://www.data.qld.gov.au/dataset/unclaimed-monies"
LICENCE = "Creative Commons Attribution 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"
ATTRIBUTION = ("Unclaimed monies register: The Public Trustee of Queensland, published on the Queensland Government "
               "Open Data Portal and used under the Creative Commons Attribution 4.0 licence. The figures shown "
               "were computed by Khutlisa from that register.")
CLAIM_URL = "https://www.pt.qld.gov.au/unclaimed-money/"
PROPERTY_TYPE = "Unclaimed money"
DB_PATH = Path(__file__).resolve().parents[2] / "data" / "queensland.duckdb"
PAGE = 32000          # the portal returns at most 32,000 rows for one request
PAUSE = 0.25          # seconds between requests, to be a polite client
USER_AGENT = "khutlisa-register-loader/0.1"

FIELDS = ("_id", "ClientId_ActNo", "Owner", "Amount", "SenderName", "DateRec", "PCode")

Get = Callable[[str], dict]


class PortalError(RuntimeError):
    """The open data portal could not be read, or answered with something other than rows."""


def http_get(sql: str, timeout: float = 120.0, tries: int = 4) -> dict:
    """One SQL query against the portal's datastore. Returns the `result` object. Only the query is sent."""
    import httpx

    last: Exception | None = None
    for attempt in range(tries):
        try:
            response = httpx.get(API, params={"sql": sql}, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if response.status_code == 200:
                body = response.json()
                if body.get("success"):
                    return body["result"]
                last = PortalError(f"the portal refused the query: {str(body.get('error'))[:200]}")
            else:
                last = PortalError(f"the portal answered HTTP {response.status_code}")
        except (httpx.HTTPError, ValueError) as err:
            last = PortalError(f"the portal could not be reached ({type(err).__name__})")
        time.sleep(min(2 ** attempt, 8))
    raise last or PortalError("the portal could not be read")


def portal_figures(get: Get = http_get) -> dict:
    """What the portal itself reports for the register: the number of records and the sum of the amounts."""
    rows = get(f'SELECT COUNT(*) AS n, SUM("Amount") AS total, MAX("DateRec") AS latest FROM "{RESOURCE}"')["records"]
    row = rows[0]
    return {"records": int(row["n"]), "amount": round(float(row["total"] or 0), 2),
            "latest_received": str(row.get("latest") or "")[:10]}


def pages(get: Get = http_get, page: int = PAGE, pause: float = PAUSE,
          sleep: Callable[[float], None] = time.sleep) -> Iterator[list[dict]]:
    """Every row of the register, in pages, in the order of the portal's own row number. Each page asks for the
    rows after the last one seen, so a row is never read twice and none is skipped if the register grows."""
    last = 0
    columns = ", ".join(f'"{f}"' for f in FIELDS)
    while True:
        result = get(f'SELECT {columns} FROM "{RESOURCE}" WHERE "_id" > {int(last)} ORDER BY "_id" LIMIT {int(page)}')
        rows = result.get("records") or []
        if not rows:
            return
        yield rows
        last = max(int(r["_id"]) for r in rows)
        if len(rows) < page:
            return
        sleep(pause)


def postcode(value: Any) -> str:
    """The portal stores the postcode as a number, so 0800 arrives as 800. Australian postcodes have four digits."""
    if value in (None, ""):
        return ""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return str(value).strip()
    return f"{number:04d}" if 0 < number < 10000 else str(number)


def record_id(value: Any) -> str:
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value or "").strip()


def as_record(row: dict) -> tuple:
    """One portal row in the shape of the `records` table (registers.connect)."""
    try:
        amount = float(row.get("Amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return (SOURCE, record_id(row.get("ClientId_ActNo")), str(row.get("Owner") or "").strip(), "", "", "",
            postcode(row.get("PCode")), "AUS", COUNTRY, amount, CURRENCY, str(row.get("SenderName") or "").strip(),
            "", "", PROPERTY_TYPE, str(row.get("DateRec") or "")[:10] or None)


def connect(path: Path | str = DB_PATH) -> duckdb.DuckDBPyConnection:
    from .registers import connect as open_register

    return open_register(Path(path))


def load(con: duckdb.DuckDBPyConnection, source: Iterator[list[dict]], progress: Callable[[int], None] | None = None) -> int:
    """Replace the Queensland rows in `con` with the rows from `source` and build the search columns. Returns the
    number of rows loaded."""
    # The file holds this register only, so a load starts from an empty table (the search columns are added at
    # the end and would not line up with fresh rows).
    con.execute("drop table if exists records")
    con.execute(RECORDS_TABLE)
    total = 0
    for rows in source:
        total += _flush(con, [as_record(r) for r in rows])
        if progress:
            progress(total)
    add_search_column(con)
    return total


def loaded_figures(con: duckdb.DuckDBPyConnection) -> dict:
    n, amount, ids = con.execute("select count(*), coalesce(sum(amount), 0), count(distinct record_id) from records "
                                 "where source = ?", [SOURCE]).fetchone()
    return {"records": int(n), "amount": round(float(amount), 2), "distinct_ids": int(ids)}


def verify(loaded: dict, portal: dict) -> dict:
    """Compare what was loaded with what the portal reports. The amounts are compared to the cent."""
    same_count = loaded["records"] == portal["records"]
    same_amount = abs(loaded["amount"] - portal["amount"]) < 0.005
    return {"records_match": same_count, "amount_match": same_amount, "ok": same_count and same_amount,
            "loaded": loaded, "portal": portal}


def facts(path: Path | str = DB_PATH) -> dict | None:
    """The stored facts about the load (written beside the database by scripts/load_queensland.py), or None."""
    import json

    file = Path(path).with_suffix(".json")
    if not Path(path).exists() or not file.exists():
        return None
    try:
        return json.loads(file.read_text())
    except ValueError:
        return None
