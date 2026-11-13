"""Loads public unclaimed-money registers into one local DuckDB file.

Sources are only the bulk files and open APIs the operators themselves publish.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "registers.duckdb"

# California mixes ISO alpha-3, ISO alpha-2 and older FIPS codes in OWNER_COUNTRY_CODE.
# Only codes whose meaning is settled are mapped here; the rest keep their raw code.
COUNTRY_FIX = {
    "USA": "US", "US": "US", "JPN": "JP", "JA": "JP", "CHN": "CN", "TWN": "TW", "TW": "TW", "MEX": "MX", "MX": "MX",
    "CAN": "CA", "HKG": "HK", "HK": "HK", "GBR": "GB", "UK": "GB", "FRA": "FR", "PHL": "PH", "AUS": "AU",
    "DEU": "DE", "GM": "DE", "SGP": "SG", "SN": "SG", "ISR": "IL", "CHE": "CH", "ITA": "IT", "IT": "IT",
    "EI": "IE", "IRL": "IE", "BRA": "BR", "SAU": "SA", "VEN": "VE", "ARG": "AR", "IND": "IN", "IN": "IN",
    "UY": "UY", "URY": "UY", "KOR": "KR", "ESP": "ES", "GRC": "GR", "CHL": "CL", "IDN": "ID", "THA": "TH",
    "SWE": "SE", "VNM": "VN", "NLD": "NL", "ZAF": "ZA", "NZL": "NZ", "COL": "CO", "PER": "PE", "NGA": "NG",
    "KEN": "KE", "LSO": "LS", "MYS": "MY", "ARE": "AE", "TUR": "TR", "EGY": "EG", "PAK": "PK", "BGD": "BD",
    "RUS": "RU", "UKR": "UA", "POL": "PL", "PRT": "PT", "BEL": "BE", "AUT": "AT", "DNK": "DK", "NOR": "NO",
    "FIN": "FI", "GTM": "GT", "SLV": "SV", "HND": "HN", "NIC": "NI", "CRI": "CR", "PAN": "PA", "ECU": "EC",
    "DOM": "DO", "JAM": "JM", "LBN": "LB", "IRN": "IR", "IRQ": "IQ", "JOR": "JO", "KWT": "KW", "QAT": "QA",
}

# Two-letter codes, each decided by the owner cities seen under that raw code in the file of 4 Nov 2026 (the most
# common cities and how many owner records carry them; no names were looked at). A code is mapped only when its
# cities all point to one country. Almost every two-letter code in the file turns out to follow the older FIPS list.

# The FIPS and ISO lists disagree on these, and the cities settle it (the other reading is in brackets).
COUNTRY_FIX.update({
    "CH": "CN",   # Beijing, Shanghai, Guangdong, Zhejiang, Jiangsu (not Switzerland, which the file writes CHE or SZ)
    "SZ": "CH",   # Adliswil, Silvaplana, Zurich, Geneva (not Eswatini)
    "AS": "AU",   # Thomastown, Sydney, Lismore, Perth (not American Samoa, which the file writes ASM)
    "IS": "IL",   # Netanya, Ashkelon, Petach Tiqwa, Jerusalem (not Iceland)
    "RS": "RU",   # Moscow, Dubna (not Serbia)
    "CI": "CL",   # Copiapo, Santiago, Antofagasta, Concepcion (not Ivory Coast)
    "VI": "VG",   # Road Town and Tortola only: the British Virgin Islands (not the United States Virgin Islands)
    "BF": "BS",   # Nassau, Freeport (not Burkina Faso)
    "PM": "PA",   # Panama City, San Miguelito (not Saint Pierre and Miquelon)
    "BA": "BH",   # Manama, Sanad, Riffa (not Bosnia and Herzegovina)
    "MG": "MN",   # Ulaanbaatar in every record (not Madagascar)
    "NI": "NG",   # Lagos, Ikeja, Lekki (not Nicaragua)
    "TD": "TT",   # Port of Spain, Fyzabad, Diego Martin (not Chad)
    "MP": "MU",   # Le Morne, Coromandel, Beau Bassin (not the Northern Mariana Islands)
    "BH": "BZ",   # Corozal Town, Belize City (not Bahrain)
    "NU": "NI",   # Managua, Masaya (not Niue)
    "MO": "MA",   # Casablanca (not Macao)
    "MC": "MO",   # Taipa, Macau (not Monaco)
    "PA": "PY",   # Ciudad del Este, Hernandarias, Asuncion (not Panama)
    "SC": "KN",   # Nevis, Basseterre (not Seychelles)
    "BG": "BD",   # Dhaka (not Bulgaria)
    "MN": "MC",   # postcode 98000, "MC 98000" (not Mongolia)
    "GG": "GE",   # Tbilisi (not Guernsey)
    "BO": "BY",   # Minsk (not Bolivia)
    "TK": "TC",   # Providenciales (not Tokelau)
    "CN": "CN",   # Shanghai, Chengdu, Suzhou: here the ISO reading holds (not Comoros)
})
# FIPS codes that the ISO list does not use, with cities that confirm the FIPS meaning.
COUNTRY_FIX.update({
    "RP": "PH",   # Bacoor, Pasay, Imus, Paranaque, Cebu City
    "SF": "ZA",   # Johannesburg, Somerset West, Pretoria, Durban
    "SP": "ES",   # Madrid, Getxo, Santa Cruz de Tenerife, Teruel
    "KS": "KR",   # Seoul, Koyang, Cheongju, Incheon
    "SW": "SE",   # Sveg, Umea, Lund, Stockholm
    "CS": "CR",   # San Jose, Zapote, Curridabat, Escazu
    "KU": "KW",   # Kuwait City, Safat
    "DR": "DO",   # Bonao, Santo Domingo, Cotui, La Vega
    "CJ": "KY",   # George Town, Grand Cayman
    "PO": "PT",   # Lisboa, Aveiro, Coimbra, Porto
    "TU": "TR",   # Istanbul in every record
    "EZ": "CZ",   # Prague, Brno, Prostejov
    "LE": "LB",   # Beirut, Saida, Jounieh
    "DA": "DK",   # Silkeborg, Frederiksberg, Kobenhavn, Arhus
    "BU": "BG",   # Sofia, Shumen, Stara Zagora
    "BX": "BN",   # Bandar Seri Begawan, Kuala Belait
    "VM": "VN",   # Ho Chi Minh City, Danang
    "UC": "CW",   # Klein Sint Michiel, Toni Kunchi
    "LO": "SK",   # Bratislava, Lipany, Pezinok
    "EN": "EE",   # Keila, Tallinn
    "LG": "LV",   # Riga
    "HO": "HN",   # Tegucigalpa, San Pedro Sula
    "UP": "UA",   # Kiev
    "CE": "LK",   # Nugegoda, Wattala, Hokandara
    "CB": "KH",   # Phnom Penh
    "WE": "PS",   # Ramallah
    "LH": "LT",   # Vilnius, Kaunas
    "IV": "CI",   # Plateau, Abengourou
    "IC": "IS",   # Reykjavik
    "AJ": "AZ",   # Baku
    "WA": "NA",   # Walvis Bay
    "GK": "GG",   # Forest, postcode GY8
    "FP": "PF",   # Papeete, Tahiti
    "AA": "AW",   # Oranjestad
    "RB": "RS",   # Belgrade
    "TS": "TN",   # "1004 Tunisia"
})
# Codes that mean the same country in both lists (or exist only in the ISO list), with cities that agree.
COUNTRY_FIX.update({
    "CA": "CA",   # Medicine Hat, Sarnia, Toronto, Corunna, Wallaceburg
    "FR": "FR",   # Saint Germain les Arpajon, Ruffec, Suresnes, Paris
    "CO": "CO",   # Bogota, Medellin, Cali
    "MY": "MY",   # Selangor, Kuala Lumpur, Klang, Bayan Lepas
    "NZ": "NZ",   # Kerikeri, Auckland, Wellington, Timaru
    "BR": "BR",   # Sao Paulo, Aracaju, Vitoria, Araraquara
    "AE": "AE",   # Dubai, Abu Dhabi, Sharjah
    "VE": "VE",   # Caracas, Maturin, Merida, Cabimas
    "ID": "ID",   # Jakarta, Samarinda, Banjarmasin
    "SA": "SA",   # Riyadh, Khobar, Dhahran, Jeddah
    "AR": "AR",   # Buenos Aires, Jose Marmol, Comodoro Rivadavia
    "NL": "NL",   # Amsterdam, Weesp, Rotterdam, Den Haag
    "TH": "TH",   # Bangkok, Mahasarakham, Nonthaburi
    "PL": "PL",   # Krakow, Olsztyn, Siedlce, Warsaw
    "BE": "BE",   # Woluwe St. Pierre, Brussels, Diest, Wavre
    "NO": "NO",   # Hundvag, Bergen, Trondheim
    "EG": "EG",   # Alexandria, Cairo, Giza, Port Said
    "PE": "PE",   # Lima, Arequipa
    "GT": "GT",   # Guatemala, Quetzaltenango
    "HU": "HU",   # Urom, Solymar, Budapest, Szeged
    "KE": "KE",   # Nairobi, Mombasa
    "FI": "FI",   # Helsinki, Espoo, Tampere
    "PK": "PK",   # Karachi, Islamabad, Lahore
    "EC": "EC",   # Quito, Quevedo, Guayaquil
    "GR": "GR",   # Athens, Piraeus, Chios
    "CY": "CY",   # Limassol, Nicosia, Paralimni
    "LY": "LY",   # Tripoli
    "RO": "RO",   # Bucharest, Timisoara, Cluj-Napoca, Iasi
    "JO": "JO",   # Amman
    "MT": "MT",   # Siggiewi, Balzan, Madliena
    "SI": "SI",   # Idrija, Ljubljana, Postojna, Nova Gorica
    "JM": "JM",   # Kingston, Montego Bay
    "HR": "HR",   # Zagreb, Makarska
    "BB": "BB",   # Hastings, Bridgetown
    "KZ": "KZ",   # Almaty, Kulsary, Atyrau
    "AM": "AM",   # Yerevan
    "QA": "QA",   # Doha
    "IL": "IL",   # Bat Yam, Tel Aviv, Jerusalem
    "TR": "TR",   # Istanbul, Corum
    "UA": "UA",   # Kyiv
    "GH": "GH",   # Accra
    "JP": "JP",   # Tendo, Adachi
    "LU": "LU",   # Bereldange, postcode L-7221
    "CZ": "CZ",   # Dubi, Ceska Lipa
    "PH": "PH",   # Angeles, Quezon City
    "CM": "CM",   # Yaounde
    "AO": "AO",   # Luanda
    "MD": "MD",   # Edinet
    "SG": "SG",   # Singapore
    "DE": "DE",   # Giessen
    "RU": "RU",   # Bryanskaya
})
# Left uncertain on purpose (kept as '?XX' and shown only in the unplaced line of the totals):
#   AU  Austrian towns (Buers, Vienna, Graz) but also Eaglemont in Australia, so both readings occur
#   BD  Bermuda parishes (Hamilton, Warwick) but also Tangail in Bangladesh
#   ES  El Salvador (San Salvador, Antiguo Cuscatlan) but also A Coruna in Spain
#   ZA  Lusaka (Zambia) and Johannesburg (South Africa)
#   MU  Muscat and Sohar (Oman) and San Juan in Puerto Rico
#   NT  Curacao and Sint Maarten: the former Netherlands Antilles, which is no single country today
#   BL  only "Santa Cruz", a city name found in many countries
#   CD  only Whitby, Ontario, which fits neither reading
#   AC, HA, UG, LV, TI, MZ, NP, 68  one or two records with no city, a number or a city that cannot be placed

# United States territories. They are not "another country", so the totals keep them apart from the money held
# for owners abroad (see countries.US_TERRITORIES and totals() below). GQ and VQ are the FIPS codes for Guam and
# the United States Virgin Islands (Yigo 96542 and St. Thomas 00803 in the file).
COUNTRY_FIX.update({"PRI": "PR", "GUM": "GU", "VIR": "VI", "ASM": "AS", "MNP": "MP", "UMI": "UM", "GQ": "GU",
                    "VQ": "VI"})
# Two other spellings of the United States: their cities are Long Beach, Torrance, Riverside, Los Angeles.
COUNTRY_FIX.update({"U.S": "US", "UNI": "US"})


# Codes that the owner cities under them contradict (PRK with South Korean cities, a Californian postcode written
# as a country). The list and the cities that decided each one are in countries.RAW_DECIDED. Codes it could not
# place keep their raw code and are shown only in the unplaced line of the totals.
from .countries import RAW_DECIDED as _RAW_DECIDED  # noqa: E402

COUNTRY_FIX.update({raw: iso for raw, iso in _RAW_DECIDED.items() if iso})


def country_of(raw: str) -> str:
    """ISO alpha-2 where the raw code is settled in COUNTRY_FIX. Any other two-letter raw code could be ISO or the
    older FIPS standard, so it is kept apart as '?XX'; longer codes are kept as they are."""
    if not raw:
        return ""
    if raw in COUNTRY_FIX:
        return COUNTRY_FIX[raw]
    return f"?{raw}" if len(raw) == 2 else raw


CA_COLUMNS = [
    "PROPERTY_ID", "PROPERTY_TYPE", "CASH_REPORTED", "SHARES_REPORTED", "NAME_OF_SECURITIES_REPORTED",
    "NO_OF_OWNERS", "OWNER_NAME", "OWNER_STREET_1", "OWNER_STREET_2", "OWNER_STREET_3", "OWNER_CITY",
    "OWNER_STATE", "OWNER_ZIP", "OWNER_COUNTRY_CODE", "CURRENT_CASH_BALANCE", "NUMBER_OF_PENDING_CLAIMS",
    "NUMBER_OF_PAID_CLAIMS", "HOLDER_NAME", "HOLDER_STREET_1", "HOLDER_STREET_2", "HOLDER_STREET_3",
    "HOLDER_CITY", "HOLDER_STATE", "HOLDER_ZIP", "CUSIP",
]


RECORDS_TABLE = """
    create table if not exists records (
        source varchar, record_id varchar, owner_name varchar, owner_street varchar, owner_city varchar,
        owner_region varchar, owner_postcode varchar, owner_country_raw varchar, owner_country varchar,
        amount double, currency varchar, holder_name varchar, holder_city varchar, holder_region varchar,
        property_type varchar, received varchar
    )
"""


def connect(path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(RECORDS_TABLE)
    return con


def _money(text: str) -> float:
    try:
        return float(text or 0)
    except ValueError:
        return 0.0


def load_california(zip_path: Path, con: duckdb.DuckDBPyConnection, batch: int = 200_000) -> int:
    """Streams one California band (a zip of CSV parts) into the records table. Returns rows loaded."""
    total = 0
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            with z.open(member) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""))
                rows: list[tuple] = []
                for r in reader:
                    code = (r.get("OWNER_COUNTRY_CODE") or "").strip().upper()
                    street = " ".join(
                        p.strip() for p in (r.get("OWNER_STREET_1"), r.get("OWNER_STREET_2"), r.get("OWNER_STREET_3")) if p and p.strip()
                    )
                    rows.append((
                        "US-CA", r.get("PROPERTY_ID"), (r.get("OWNER_NAME") or "").strip(), street,
                        (r.get("OWNER_CITY") or "").strip(), (r.get("OWNER_STATE") or "").strip(),
                        (r.get("OWNER_ZIP") or "").strip(), code, country_of(code),
                        _money(r.get("CURRENT_CASH_BALANCE")), "USD", (r.get("HOLDER_NAME") or "").strip(),
                        (r.get("HOLDER_CITY") or "").strip(), (r.get("HOLDER_STATE") or "").strip(),
                        (r.get("PROPERTY_TYPE") or "").strip(), None,
                    ))
                    if len(rows) >= batch:
                        total += _flush(con, rows)
                        rows = []
                total += _flush(con, rows)
    return total


def _flush(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    cols = list(zip(*rows))
    names = ["source", "record_id", "owner_name", "owner_street", "owner_city", "owner_region", "owner_postcode",
             "owner_country_raw", "owner_country", "amount", "currency", "holder_name", "holder_city",
             "holder_region", "property_type", "received"]
    types = [pa.string()] * 9 + [pa.float64()] + [pa.string()] * 6
    batch_table = pa.table({n: pa.array(c, type=t) for n, c, t in zip(names, cols, types)})
    con.register("batch_table", batch_table)
    con.execute("insert into records select * from batch_table")
    con.unregister("batch_table")
    return len(rows)


NORM_SQL = r"""
    update records set owner_norm = trim(regexp_replace(regexp_replace(
        upper(strip_accents(replace(owner_name, chr(39), ''))), '[^A-Z0-9 ]+', ' ', 'g'), '\s+', ' ', 'g'))
    where owner_norm is null
"""


def _phon_sql(expr: str) -> str:
    """The SQL twin of names.phonetic. Keep the two in step."""
    from .names import _PHON_LETTERS, _PHON_STEPS

    e = f"regexp_replace({expr}, '[^A-Z]', '', 'g')"
    for a, b in _PHON_STEPS:
        e = f"replace({e}, '{a}', '{b}')"
    e = f"(substr({e}, 1, 1) || regexp_replace(substr({e}, 2), '[AEIOU]', '', 'g'))"
    for _ in range(2):
        for c in _PHON_LETTERS:
            e = f"replace({e}, '{c}{c}', '{c}')"
    return e


def add_search_column(con: duckdb.DuckDBPyConnection) -> None:
    """Upper-case ASCII owner names plus said-aloud keys for the first and last word, so a name is found however
    it was typed or respelled."""
    con.execute("alter table records add column if not exists owner_norm varchar")
    con.execute(NORM_SQL)
    con.execute("alter table records add column if not exists phon_first varchar")
    con.execute("alter table records add column if not exists phon_last varchar")
    first = "split_part(owner_norm, ' ', 1)"
    last = "split_part(owner_norm, ' ', -1)"
    con.execute(f"update records set phon_first = {_phon_sql(first)}, phon_last = {_phon_sql(last)} where phon_first is null")


TOTALS_RULE = (
    "Each property is counted once, however many owners it has. A property is counted as held for an owner abroad "
    "when at least one of its owners has a last known address in another country. United States territories are "
    "counted apart and are not part of that figure. A property with owners in two countries is listed under each "
    "of those countries and counted once in the headline, so the country lines add up to more than the headline."
)


def build_away(con: duckdb.DuckDBPyConnection, home: str = "US") -> list[tuple[str, str, str]]:
    """Leaves a temp table totals_away(source, record_id, kind, shown, amount) for the caller to use and drop:
    one row per property and line it is listed under. `kind` is 'abroad' (an owner whose last known address is in
    another country; `shown` is the ISO code, or 'other' for a code that cannot be placed), 'territory' (a United
    States territory; `shown` is its code) or 'blank' (no country code on an owner). Properties whose owners are
    all at home have no row. This is the one definition of "abroad" in the project.

    The records table has one row per owner and repeats the property's full balance on every owner row, so a
    property is one (source, record_id) and its amount is taken once. Country codes are read with
    countries.resolve first, so two spellings of one country make one line; then the cities in
    countries.CITY_DECIDED move the owner records that sit under the wrong country, where the register has the
    owner city. Returns the (stored code, kind, shown) list the codes were read into."""
    from .countries import CITY_DECIDED, US_TERRITORIES, resolve

    settled = frozenset(COUNTRY_FIX.values())

    def kind_of(iso: str | None) -> tuple[str, str]:
        if iso == home:
            return "home", iso
        if iso in US_TERRITORIES:
            return "territory", iso
        return "abroad", iso or "other"

    place = []
    by_iso: dict[str, list[str]] = {}
    for (code,) in con.execute("select distinct coalesce(owner_country, '') from records").fetchall():
        iso = resolve(code, settled)
        if code == "":
            place.append((code, "blank", ""))
            continue
        by_iso.setdefault(iso or "", []).append(code)
        if code == home or iso == home:
            continue
        place.append((code, *kind_of(iso)))
    con.execute("create or replace temp table totals_place (code varchar, kind varchar, shown varchar)")
    if place:
        con.executemany("insert into totals_place values (?, ?, ?)", place)
    con.execute("create or replace temp table totals_city (code varchar, city varchar, postcode varchar, "
                "kind varchar, shown varchar)")
    columns = {c[0] for c in con.execute("describe records").fetchall()}
    moved = [(code, city, postcode, *kind_of(iso)) for said, city, postcode, iso in CITY_DECIDED
             for code in by_iso.get(said, []) if said != home] if "owner_city" in columns else []
    if moved:
        con.executemany("insert into totals_city values (?, ?, ?, ?, ?)", moved)
    postcode = "coalesce(r.owner_postcode, '')" if "owner_postcode" in columns else "''"
    city_join = (f"left join totals_city c on c.code = p.code and starts_with(upper(trim(r.owner_city)), c.city) "
                 f"and starts_with({postcode}, c.postcode)") if moved else \
        "left join totals_city c on false"
    # One row per property, kind and line it is listed under. Only rows away from home are touched here.
    con.execute(f"""
        create or replace temp table totals_away as
        select r.source, r.record_id, coalesce(c.kind, p.kind) kind, coalesce(c.shown, p.shown) shown,
               max(r.amount) amount
        from records r join totals_place p on coalesce(r.owner_country, '') = p.code
        {city_join}
        where coalesce(c.kind, p.kind) <> 'home'
        group by 1, 2, 3, 4
    """)
    con.execute("drop table totals_city")
    con.execute("drop table totals_place")
    return place


def totals(con: duckdb.DuckDBPyConnection, home: str = "US") -> dict:
    """The figures for the opening screen, counting each property once. build_away says which properties are
    held for an owner abroad; this adds them up."""
    place = build_away(con, home)
    owner_rows, = con.execute("select count(*) from records").fetchone()
    all_n, all_amt = con.execute(
        "select count(*), coalesce(sum(a), 0) from (select max(amount) a from records group by source, record_id)"
    ).fetchone()

    def once(kind: str) -> tuple[int, float]:
        n, amt = con.execute(
            "select count(*), coalesce(sum(a), 0) from (select max(amount) a from totals_away where kind = ? "
            "group by source, record_id)", [kind]).fetchone()
        return int(n), round(amt, 2)

    def lines(kind: str) -> list[dict]:
        rows = con.execute(
            "select shown, count(*), coalesce(sum(amount), 0) from totals_away where kind = ? group by 1 "
            "order by 3 desc, 1", [kind]).fetchall()
        return [{"code": c, "properties": int(n), "amount": round(a, 2)} for c, n, a in rows]

    abroad_n, abroad_amt = once("abroad")
    listed = lines("abroad")
    other = next((r for r in listed if r["code"] == "other"), {"properties": 0, "amount": 0.0})
    multi_n, multi_amt = con.execute(
        "select count(*), coalesce(sum(a), 0) from (select max(amount) a from totals_away where kind = 'abroad' "
        "group by source, record_id having count(*) > 1)").fetchone()
    listed_amount = round(float(sum(r["amount"] for r in listed)), 2)
    territory_n, territory_amt = once("territory")
    blank_n, blank_amt = once("blank")
    out = {
        "owner_rows": int(owner_rows),
        "all_properties": int(all_n), "all_amount": round(all_amt, 2),
        "abroad_properties": abroad_n, "abroad_amount": abroad_amt,
        "by_country": [r for r in listed if r["code"] != "other"],
        "other": {"properties": other["properties"], "amount": other["amount"],
                  "codes": sum(1 for _, kind, shown in place if kind == "abroad" and shown == "other")},
        "multi_country_properties": int(multi_n), "multi_country_amount": round(multi_amt, 2),
        "listed_amount": listed_amount,
        "multi_country_extra_amount": round(listed_amount - abroad_amt, 2),
        "us_territories": {"properties": territory_n, "amount": territory_amt, "by_territory": lines("territory")},
        "no_country_properties": blank_n, "no_country_amount": blank_amt,
        "codes_resolved": True,     # by_country holds ISO codes whose meaning is settled, one line per country
        "rule": TOTALS_RULE,
    }
    con.execute("drop table totals_away")
    return out


def describe_totals(t: dict, listed: int = 15) -> str:
    """The totals in words, for the scripts to print."""
    def props(n: int) -> str:
        return f"{n:,} property" if n == 1 else f"{n:,} properties"

    text = [
        f"All: {props(t['all_properties'])} worth ${t['all_amount']:,.0f}, in {t['owner_rows']:,} owner records "
        "(one for each owner of a property; the search runs over these).",
        f"Held for owners abroad: {props(t['abroad_properties'])} worth ${t['abroad_amount']:,.0f}.",
        f"United States territories, counted apart: {props(t['us_territories']['properties'])} worth "
        f"${t['us_territories']['amount']:,.0f}.",
        f"No country code on an owner: {props(t['no_country_properties'])} worth ${t['no_country_amount']:,.0f}.",
        f"Listed under more than one country: {props(t['multi_country_properties'])} worth "
        f"${t['multi_country_amount']:,.0f}; the country lines add up to ${t['listed_amount']:,.0f}, which is "
        f"${t['multi_country_extra_amount']:,.0f} more than the headline.",
        f"Under country codes that cannot be placed ({t['other']['codes']} codes): "
        f"{props(t['other']['properties'])} worth ${t['other']['amount']:,.0f}.",
        t["rule"],
    ]
    for r in t["by_country"][:listed]:
        text.append(f"  {r['code']:4} {r['properties']:>8,} ${r['amount']:>14,.0f}")
    return "\n".join(text)
