"""Reads a prepared set of well-known organisations out of California's file and writes what the file says.

    uv run python scripts/make_notable_organisations.py [--if-database]

Writes src/khutlisa/notable_organisations.json, which the "who is owed" screen and the opening show. The list of
names below was chosen by hand: organisations only, each one read by a person, picked for the amount and for being
widely known. Every figure in the output is read from data/registers.duckdb by this script: the largest property
in that exact owner name, who reported it, the city on the record, and how many properties carry the same exact
name. The first group pairs a well-known owner with a well-known holder, and there the line is the largest
property in that owner name that this holder reported.

Two rules stop the script, so no person and no firm, estate or trust named after a person can get in. An owner
name that the strict organisation rule (server.shown_as_organisation) would not show in full stops it. So does a
holder name that is not in HOLDERS_READ below, the list of holder names a person has read.

The output records the date of California's file, when the database file was last written and when this script
ran. `npm run build` runs this script first with --if-database, which leaves the output as it is when the
database is not on the machine.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa.countries import COUNTRIES  # noqa: E402
from khutlisa.names import normalise  # noqa: E402
from khutlisa.registers import DB_PATH  # noqa: E402
from khutlisa.server import shown_as_organisation  # noqa: E402

OUT = ROOT / "src" / "khutlisa" / "notable_organisations.json"

FILE_DATED = "2026-11-04"      # the date on California's bulk file that scripts/load_registers.py loaded

# One well-known organisation whose money was reported by another. Found by searching owner and holder names
# together (organisations only) and chosen by hand for how well known the two names are and for the amount.
# (owner name exactly as the file writes it, the name to show, the holder exactly as the file writes it without
# its branch number, the holder's name to show)
PAIRS = "One well-known name reported by another"
PAIR_PICKS = [
    ("STANFORD UNIVERSITY", "Stanford University",
     "PRESIDENT AND FELLOWS OF HARVARD COLLEGE", "President and Fellows of Harvard College"),
    ("WARNER BROS ENTERTAINMENT INC", "Warner Bros. Entertainment",
     "WALT DISNEY COMPANY THE", "The Walt Disney Company"),
    ("INTERNAL REVENUE SERVICES", "Internal Revenue Services", "ORACLE AMERICA INC", "Oracle America"),
    ("BANK OF AMERICA", "Bank of America", "JPMORGAN CHASE BANK N A", "JPMorgan Chase Bank"),
    ("TESLA MOTORS INC", "Tesla Motors", "TOYOTA MOTOR SALES USA INC", "Toyota Motor Sales USA"),
    ("APPLE INC", "Apple", "STAPLES INC", "Staples"),
    ("MCDONALDS CORPORATION", "McDonald's Corporation", "AT&T SERVICES INC", "AT&T Services"),
    ("PAYPAL INC", "PayPal", "MICROSOFT CORPORATION", "Microsoft Corporation"),
]

# (category, owner name exactly as the file writes it, the name to show)
PICKS = [
    ("Universities", "UNIVERSITY OF SOUTHERN CALIFORNIA", "University of Southern California"),
    ("Universities", "UNIVERSITY OF CALIFORNIA BERKELEY", "University of California, Berkeley"),
    ("Universities", "SAARLAND UNIVERSITY", "Saarland University"),
    ("Universities", "HOKKAIDO UNIVERSITY", "Hokkaido University"),
    ("Universities", "MAKERERE UNIVERSITY", "Makerere University"),
    ("Universities", "LUND UNIVERSITY", "Lund University"),
    ("Universities", "UNIVERSITY OF TOKYO", "University of Tokyo"),
    ("Cities and counties", "CITY OF DALLAS", "City of Dallas"),
    ("Cities and counties", "COUNTY OF RIVERSIDE", "County of Riverside"),
    ("Cities and counties", "COUNTY OF LOS ANGELES", "County of Los Angeles"),
    ("Cities and counties", "CITY OF SAN DIEGO", "City of San Diego"),
    ("Cities and counties", "CITY OF LOS ANGELES", "City of Los Angeles"),
    ("Cities and counties", "CITY OF NEW YORK", "City of New York"),
    ("Cities and counties", "CITY OF TORONTO", "City of Toronto"),
    ("Hospitals", "EL CAMINO HOSPITAL", "El Camino Hospital"),
    ("Hospitals", "GREATER BAKERSFIELD MEMORIAL HOSPITAL", "Greater Bakersfield Memorial Hospital"),
    ("Hospitals", "HOSPITAL ESQUIROL UNITE DAUMEZON", "Hospital Esquirol, Unite Daumezon"),
    ("Hospitals", "KAISER FOUNDATION HOSPITALS", "Kaiser Foundation Hospitals"),
    ("Hospitals", "CHILDRENS HOSPITAL LOS ANGELES", "Children's Hospital Los Angeles"),
    ("Hospitals", "ST JUDE CHILDRENS RESEARCH HOSPITAL", "St. Jude Children's Research Hospital"),
    ("Charities", "WORLD WILDLIFE FUND", "World Wildlife Fund"),
    ("Charities", "GOODWILL INDUSTRIES INTERNATIONAL INC", "Goodwill Industries International"),
    ("Charities", "ALAMEDA CO FOOD BANK", "Alameda County Food Bank"),
    ("Charities", "CHINESE RED CROSS FOUNDATION", "Chinese Red Cross Foundation"),
    ("Charities", "AMERICAN HEART ASSOCIATION INC", "American Heart Association"),
    ("Charities", "AMERICAN CANCER SOCIETY INC", "American Cancer Society"),
    ("Charities", "UNITED STATES FUND FOR UNICEF", "United States Fund for UNICEF"),
    ("Well-known companies", "UBER TECHNOLOGIES INC", "Uber Technologies"),
    ("Well-known companies", "TESLA INC", "Tesla"),
    ("Well-known companies", "GOOGLE LLC", "Google"),
    ("Well-known companies", "FACEBOOK INC", "Facebook"),
    ("Well-known companies", "SONY ELECTRONICS INC", "Sony Electronics"),
    ("Well-known companies", "SAMSUNG ELECTRONICS CO LTD", "Samsung Electronics"),
    ("Well-known companies", "NETFLIX INC", "Netflix"),
    ("Governments and consulates", "US DEPARTMENT OF TREASURY", "United States Department of the Treasury"),
    ("Governments and consulates", "CONSULATE GENERAL OF THE STATE OF KUWAIT", "Consulate General of the State of Kuwait"),
    ("Governments and consulates", "CONSULATE GEN OF THE STATE OF QATAR", "Consulate General of the State of Qatar"),
    ("Governments and consulates", "GOVERNMENT OF THE DISTRICT OF COLUMBIA", "Government of the District of Columbia"),
    ("Governments and consulates", "EMBASSY OF THE STATE OF ERITRE", "Embassy of the State of Eritrea"),
]
# Three for the opening screen: the first three pairs.
OPENING = [written for written, _, _, _ in PAIR_PICKS[:3]]

# Every holder name this script may publish, as the file writes it without its branch number. A person has read
# each one: all are companies, banks, universities, public bodies or funds, and none is a person, a practice, an
# estate or a trust named after a person. A holder that is not here stops the script until someone reads it.
HOLDERS_READ = {
    "AT&T SERVICES INC", "BANK OF AMERICA - CALIFORNIA NA", "BLUE SHEILD OF CALIFORNIA PROMISE HEALTH PLAN",
    "BMO BANK NA (FKA) BMO HARRIS BANK NA)", "CITIBANK N A", "COMERICA BANK", "DATASITE LLC", "ELEVANCE HEALTH INC",
    "FDIC 10542 SILICON VALLEY BRIDGE BANK NATIONAL", "JPMORGAN CHASE BANK N A", "JPMORGAN CHASE BANK NA",
    "KAISER FOUNDATION HEALTH PLAN OF SO CAL", "MICREL INC.", "MICROSOFT CORPORATION",
    "NATIONAL FINANCIAL SERVICES LLC", "NATIONAL UNION FIRE INSURANCE COMPANY",
    "NEW JERSEY STATE OFFICE MANAGEMENT & BUD", "OFOS DC GOVERNMENT UNCLAIMED PROPERTY",
    "OPEN TEXT HOLDINGS INC", "ORACLE AMERICA INC", "PELCO BY SCHNEIDER ELECTRIC", "PERFORMANT RECOVERY INC",
    "PRESIDENT AND FELLOWS OF HARVARD COLLEGE", "PRINCIPAL FINANCIAL GROUP", "PRUDENTIAL FINANCIAL INC",
    "SIEMENS USA HOLDINGS INC.", "STANFORD UNIVERSITY", "STAPLES INC",
    "THE BOARD OF TRUSTEES OF LELAND STANFORD", "TOYOTA MOTOR SALES USA INC", "UNIVERSITY OF SAN DIEGO",
    "UNIVERSITY OF SOUTHERN CALIFORNIA", "VERIZON COMMUNICATIONS INC.", "WALT DISNEY COMPANY THE",
    "WELLS FARGO & COMPANY", "WELLS FARGO BANK NA", "WESCOM CREDIT UNION", "WM CORPORATE SERVICES INC",
}


def tidy(text: str) -> str:
    """'JPMORGAN CHASE BANK N.A. (1703)' as the file writes it, without the holder's own branch number."""
    return re.sub(r"\s*\((?:APECS )?\d+\)\s*$", "", (text or "").strip())


def check_names(written: str, holder: str) -> None:
    """Stops the script at an owner the organisation rule would mask, or at a holder nobody has read."""
    if not shown_as_organisation(written):
        sys.exit(f"{written} would not be shown in full by the organisation rule, so it cannot be listed.")
    if holder not in HOLDERS_READ:
        sys.exit(f"The holder {holder!r} (for {written}) has not been read by a person. Read it, and add it to "
                 "HOLDERS_READ only if it is plainly an organisation.")


def stamp(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(db: Path | None = None, out: Path = OUT, if_database: bool = False) -> dict | None:
    db = Path(db or os.environ.get("KHUTLISA_DB") or DB_PATH)
    if if_database and not db.exists():
        print(f"{db} is not on this machine, so {out.name} is left as it is.")
        return None
    try:
        con = duckdb.connect(str(db), read_only=True)
    except duckdb.Error as problem:
        if not if_database:
            raise
        print(f"{db} could not be opened ({str(problem).splitlines()[0]}), so {out.name} is left as it is.")
        return None
    owner_records, = con.execute("select count(*) from records").fetchone()
    picks = [(PAIRS, written, shown, holder, holder_shown) for written, shown, holder, holder_shown in PAIR_PICKS]
    picks += [(category, written, shown, None, None) for category, written, shown in PICKS]
    out_rows = []
    for category, written, shown, pair_holder, holder_shown in picks:
        if not shown_as_organisation(written):
            sys.exit(f"{written} would not be shown in full by the organisation rule, so it cannot be listed.")
        norm = normalise(written)
        columns = ("select owner_name, amount, holder_name, owner_city, owner_region, owner_country, property_type, "
                   "source, record_id from records where owner_norm = ?")
        if pair_holder:
            # The largest property in this owner name that this holder reported.
            top = con.execute(columns + " and starts_with(holder_name, ?) order by amount desc, holder_name, record_id limit 1",
                              [norm, pair_holder]).fetchone()
        else:
            # Two properties can share the largest amount, so the order is settled by holder and property number.
            top = con.execute(columns + " order by amount desc, holder_name, record_id limit 1", [norm]).fetchone()
        if top is None:
            sys.exit(f"{written} is not an owner name in the file" + (f" with the holder {pair_holder}." if pair_holder else "."))
        check_names(top[0], tidy(top[2]))
        count, total = con.execute(
            "select count(*), coalesce(sum(a), 0) from (select max(amount) a from records where owner_norm = ? "
            "group by source, record_id)", [norm]).fetchone()
        country = top[5] or ""
        row = {
            "category": category, "name": shown, "owner": top[0], "amount": round(float(top[1]), 2),
            "holder": tidy(top[2]), "city": (top[3] or "").strip(" ,"), "region": top[4] or "",
            "country": country, "country_name": COUNTRIES.get(country, {}).get("name", ""),
            "abroad": bool(country) and country != "US",
            "property_type": top[6] or "", "properties_in_this_name": int(count),
            "total_in_this_name": round(float(total), 2), "opening": written in OPENING,
        }
        if pair_holder:
            owners, = con.execute("select count(*) from records where source = ? and record_id = ?",
                                  [top[7], top[8]]).fetchone()
            if owners != 1:
                sys.exit(f"The property listed for {written} has {owners} owners, so it is not this organisation's alone.")
            from_holder, = con.execute(
                "select count(*) from (select 1 from records where owner_norm = ? and starts_with(holder_name, ?) "
                "group by source, record_id)", [norm, pair_holder]).fetchone()
            row.update({"pair": True, "holder_shown": holder_shown, "properties_from_this_holder": int(from_holder),
                        "owners_on_record": int(owners)})
        out_rows.append(row)
        print(f"{category[:28]:28} {shown:44} ${top[1]:>14,.2f}  by {tidy(top[2])[:40]:40} {top[3]}, {top[4]} {country}"
              f"  ({count} properties, ${total:,.2f} in this exact name)")
    con.close()
    categories = list(dict.fromkeys(c for c, *_ in picks))
    made = {
        "source": f"California State Controller, unclaimed property records, file dated {FILE_DATED}",
        "register_file_dated": FILE_DATED,
        "database_modified": stamp(datetime.fromtimestamp(db.stat().st_mtime, timezone.utc)),
        "made_at": stamp(datetime.now(timezone.utc)),
        "rule": "Organisations only. Each line is the largest single property in that exact owner name; in the "
                "first group it is the largest that the named holder reported. The names were chosen by hand and "
                "read by a person, and the figures were read from the file.",
        "owner_records": int(owner_records),
        "categories": categories,
        "examples": out_rows,
        "total": round(sum(e["amount"] for e in out_rows), 2),
        "count": len(out_rows),
        "properties_in_these_names": sum(e["properties_in_this_name"] for e in out_rows),
        "total_in_these_names": round(sum(e["total_in_this_name"] for e in out_rows), 2),
    }
    out.write_text(json.dumps(made, indent=1) + "\n")
    print(f"\n{len(out_rows)} organisations, ${made['total']:,.2f} in the properties listed. Wrote {out}")
    return made


if __name__ == "__main__":
    main(if_database="--if-database" in sys.argv[1:])
