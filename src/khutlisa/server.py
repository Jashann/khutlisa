"""The web server: totals for the opening screen, the search, and the built front end.

Privacy rule: the registers hold real private individuals. Nothing this server sends may carry a private
individual's full name or street. Every record passes through `public_record` before it leaves, and every
reason or doubt passes through `_safe_lines`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import duckdb
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import batch as batches
from . import book_api, claims_api, clients, demo, estates_api, intake, llm, metal_api, money_api, outreach_api, public_demo, queensland, recorded, rings_api, speech
from .indicative import Indicative
from .claims import ClaimStore
from .countries import COUNTRIES, ORIGIN, resolve
from .match import STRENGTH_RULE, STRONG_NOTE, History, Place, find
from .names import ORG_WORDS, Person, is_organisation, normalise
from .payouts import PayoutRunner, sandbox_factory
from .ratelimit import HOUR, MINUTE, SlidingWindow
from .record_ids import RecordIds
from .registers import COUNTRY_FIX, DB_PATH

ROOT = Path(__file__).resolve().parents[2]
TOTALS_PATH = ROOT / "data" / "totals.json"
NOTABLE_PATH = Path(__file__).with_name("notable_organisations.json")
QUEENSLAND_EXAMPLES_PATH = Path(__file__).with_name("queensland_examples.json")
CLAIMIT_SEARCH = "https://claimit.ca.gov/app/claim-search"   # California's own search page; never queried from here
WEB_DIST = ROOT / "web" / "dist"

CONFIDENCE_LINE = 0.6      # still sent as `confidence_line` for older clients; it no longer decides anything
SEARCH_FLOOR = 0.40        # matches with fewer points are not returned at all, unless the rule calls them strong
MAX_MATCHES = 25
MAX_ORGANISATIONS = 20
MASK_DOT = "·"
MASK_DOTS = 3              # every masked word is its first letter and this many dots, whatever its length
# How many searches one client address may make. The opening makes one, the "who is owed" box makes a few as a
# name is typed, and a whole walk through the screens makes a few dozen over several minutes.
SEARCHES_PER_MINUTE = 30
SEARCHES_PER_HOUR = 300
TRUSTED_CODES = frozenset(COUNTRY_FIX.values())

# Organisation words that are also ordinary family or given names ("CHURCH ROBERT", "NGUYEN CO").
# On their own they are not enough to treat an owner as an organisation and show the name in full.
_NAME_LIKE = {"CO", "SA", "AG", "KK", "NV", "BV", "SPA", "LP", "BANK", "CHURCH", "CITY", "STATE", "COUNTY",
              "SCHOOL", "COLLEGE", "GROUP", "FUND", "DISTRICT", "PARTNERS"}
_TRAILING = {"BANK", "GROUP", "FUND", "DISTRICT", "PARTNERS", "COUNTY", "SCHOOL", "COLLEGE"}
_STRONG = ORG_WORDS - _NAME_LIKE


# Words that mean a person stands behind the name, whatever follows: a practice named after its owner, an
# estate, a family trust, an account held for someone. An owner carrying one is masked like a person.
PERSON_MARKERS = {"MD", "DDS", "DMD", "DO", "DC", "DPM", "DVM", "OD", "PHD", "PSYD", "ESQ", "CPA", "RN", "JD",
                  "ESTATE", "EST", "ESTATES", "TRUST", "TRUSTS", "TRUSTEE", "TRUSTEES", "TTEE", "TTEES", "FAMILY",
                  "IRA", "ROTH", "FBO", "UTMA", "UGMA", "CUST", "CUSTODIAN", "DECD", "DEC", "DECEASED", "HEIRS",
                  "HEIR", "DBA", "AKA", "SURVIVOR", "SURVIVORS", "GUARDIAN", "CONSERVATOR", "EXECUTOR", "EXECUTRIX",
                  "ADMINISTRATOR", "REVOCABLE", "LIVING", "TESTAMENTARY", "JR", "SR", "MR", "MRS", "MS", "DR",
                  "JTWROS", "JT", "TEN"}
# Suffixes that say only "this is a company" and nothing about what it does. A name made of nothing but ordinary
# words and one of these ("JOHN SMITH INC") is, as far as anyone can tell from the register, a person's name.
_BARE_SUFFIX = {"INC", "LLC", "LLP", "LP", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC", "PTY",
                "SA", "AG", "GMBH", "KK", "NV", "BV", "SPA", "SRL", "SDN", "BHD", "PC", "PA", "APC", "PLLC", "AND"}
# Words that describe a trade or an institution. One of these beside the suffix makes a clear organisation.
_TRADE = {"BANK", "UNIVERSITY", "COLLEGE", "CITY", "COUNTY", "STATE", "DEPT", "DEPARTMENT", "ASSOCIATION", "ASSN",
          "FOUNDATION", "CHURCH", "HOSPITAL", "SCHOOL", "DISTRICT", "GROUP", "PARTNERS", "SERVICES", "SERVICE",
          "FUND", "INSURANCE", "AUTHORITY", "TRUCKING", "HARDWARE", "BOOKSTORE", "MEDICAL", "DENTAL", "CLINIC",
          "CENTER", "CENTRE", "PAYROLL", "SUPPLY", "SUPPLIES", "SYSTEMS", "TECHNOLOGIES", "TECHNOLOGY", "SOFTWARE",
          "HOLDINGS", "ENTERPRISES", "INDUSTRIES", "INTERNATIONAL", "GLOBAL", "PROPERTIES", "REALTY", "INVESTMENTS",
          "CAPITAL", "FINANCIAL", "MORTGAGE", "CREDIT", "UNION", "ELECTRIC", "ENERGY", "POWER", "WATER", "GAS",
          "COMMUNICATIONS", "TELEPHONE", "WIRELESS", "MEDIA", "RESTAURANT", "CAFE", "FOODS", "FOOD", "MARKET",
          "MARKETS", "STORES", "STORE", "SHOP", "AUTO", "MOTORS", "AIRLINES", "TRANSPORT", "LOGISTICS", "FREIGHT",
          "CONSTRUCTION", "BUILDERS", "ENGINEERING", "DESIGN", "CONSULTING", "CONSULTANTS", "MANAGEMENT",
          "SOLUTIONS", "LABS", "LABORATORIES", "PHARMACY", "PHARMACEUTICALS", "HEALTH", "HEALTHCARE", "CARE",
          "MANUFACTURING", "PRODUCTS", "TRADING", "IMPORTS", "EXPORTS", "DISTRIBUTORS", "DISTRIBUTION",
          "PUBLISHING", "PRESS", "PRODUCTIONS", "STUDIOS", "RECORDS", "ENTERTAINMENT", "TRAVEL", "TOURS", "HOTEL",
          "HOTELS", "INN", "LODGE", "RANCH", "FARMS", "FARM", "NURSERY", "LANDSCAPING", "PLUMBING", "ROOFING",
          "PAINTING", "CLEANERS", "CLEANING", "LAUNDRY", "SALON", "SECURITY", "STAFFING", "AGENCY", "ACADEMY",
          "INSTITUTE", "SOCIETY", "CLUB", "LEAGUE", "COUNCIL", "COMMITTEE", "COMMISSION", "BOARD", "MINISTRY",
          "MINISTRIES", "TEMPLE", "MOSQUE", "SYNAGOGUE", "PARISH", "DIOCESE", "MISSION", "LIBRARY", "MUSEUM",
          "THEATRE", "THEATER", "NETWORK", "NETWORKS", "ONLINE", "DIGITAL", "DATA", "ELECTRONICS", "SEMICONDUCTOR",
          "AEROSPACE", "MARINE", "PETROLEUM", "OIL", "MINING", "STEEL", "PLASTICS", "CHEMICAL", "CHEMICALS",
          "TEXTILES", "APPAREL", "FASHION", "JEWELRY", "FURNITURE", "APPLIANCES", "EQUIPMENT", "MACHINERY", "TOOLS",
          "RENTALS", "LEASING", "FINANCE", "SECURITIES", "BROKERAGE", "ADVISORS", "ASSOCIATES", "VENTURES",
          "ESCROW", "TITLE", "UNIFIED", "MUNICIPAL", "FEDERAL", "NATIONAL", "AMERICAN", "PACIFIC", "CALIFORNIA",
          "UNITED", "GENERAL", "FIRST", "WESTERN", "EASTERN", "NORTHERN", "SOUTHERN", "CENTRAL", "GOLDEN"}


# Very common given names. One of these in an owner name with no word that names a trade means a person.
_GIVEN = set("""JAMES JOHN ROBERT MICHAEL WILLIAM DAVID RICHARD JOSEPH THOMAS CHARLES CHRISTOPHER DANIEL MATTHEW ANTHONY
MARK DONALD STEVEN PAUL ANDREW JOSHUA KENNETH KEVIN BRIAN GEORGE EDWARD RONALD TIMOTHY JASON JEFFREY RYAN JACOB GARY
NICHOLAS ERIC JONATHAN STEPHEN LARRY JUSTIN SCOTT BRANDON BENJAMIN SAMUEL GREGORY FRANK ALEXANDER RAYMOND PATRICK JACK
DENNIS JERRY TYLER AARON JOSE HENRY ADAM DOUGLAS NATHAN PETER ZACHARY KYLE WALTER HAROLD JEREMY ETHAN CARL KEITH ROGER
GERALD CHRISTIAN TERRY SEAN ARTHUR AUSTIN NOAH LAWRENCE JESSE JOE BRYAN BILLY JORDAN ALBERT DYLAN BRUCE WILLIE GABRIEL
ALAN JUAN LOGAN WAYNE RALPH ROY EUGENE RANDY VINCENT RUSSELL LOUIS PHILIP BOBBY JOHNNY BRADLEY MARY PATRICIA JENNIFER
LINDA ELIZABETH BARBARA SUSAN JESSICA SARAH KAREN NANCY LISA BETTY MARGARET SANDRA ASHLEY KIMBERLY EMILY DONNA
MICHELLE DOROTHY CAROL AMANDA MELISSA DEBORAH STEPHANIE REBECCA SHARON LAURA CYNTHIA KATHLEEN AMY SHIRLEY ANGELA HELEN
ANNA BRENDA PAMELA NICOLE EMMA SAMANTHA KATHERINE CHRISTINE DEBRA RACHEL CATHERINE CAROLYN JANET RUTH MARIA HEATHER
DIANE VIRGINIA JULIE JOYCE VICTORIA OLIVIA KELLY CHRISTINA LAUREN JOAN EVELYN JUDITH MEGAN CHERYL ANDREA HANNAH MARTHA
JACQUELINE FRANCES GLORIA ANN TERESA KATHRYN SARA JANICE JEAN ALICE MADISON DORIS ABIGAIL JULIA JUDY GRACE DENISE
AMBER MARILYN BEVERLY DANIELLE THERESA SOPHIA MARIE DIANA BRITTANY NATALIE ISABELLA CHARLOTTE ROSE ALEXIS KAYLA LUIS
CARLOS JESUS MIGUEL ANTONIO FRANCISCO PEDRO MANUEL JORGE RICARDO ROBERTO FERNANDO EDUARDO JAVIER RAFAEL SERGIO
ALEJANDRO ANGEL MARIO OSCAR HECTOR RAUL RAMON ENRIQUE ARTURO ALFREDO PABLO GUILLERMO ANDRES JULIO SALVADOR ARMANDO
GUADALUPE ROSA ANA CARMEN JUANA TERESA MARGARITA LETICIA ELENA SILVIA ADRIANA VERONICA GABRIELA ALICIA YOLANDA
LUZ ESPERANZA JOSEFINA IRMA BLANCA CLAUDIA LAURA NORMA MARTHA ROSARIO CONCEPCION DOLORES PILAR MERCEDES REYNALDO
ROMEO RODOLFO ROGELIO ERNESTO DANILO ROLANDO EDGARDO RENATO VIRGILIO WEI MING HONG JING LI YAN HUI XIN YING JUN
HIROSHI KENJI YUKI AKIRA TAKASHI NGUYEN THANH MINH ANH HUNG DUNG TUAN LAN MAI AHMED MOHAMMED MOHAMED ALI HASSAN
FATIMA AISHA OMAR IBRAHIM YUSUF RAJ RAVI SANJAY ANIL SUNIL VIJAY PRIYA ANITA SUNITA DEEPAK AMIT""".split())


def shown_as_organisation(name: str) -> bool:
    """True only for a clear organisation, whose name may be shown in full. Everything else is masked like a
    person, including a company, estate or trust that carries a person's name ("JOHN SMITH MD INC", "ESTATE OF
    ...", "... FAMILY TRUST") and a bare name with a company suffix ("JOHN SMITH INC").

    Stricter than `is_organisation`: a word that doubles as a personal name only counts when it is used the way
    an organisation uses it ("BANK OF ...", "... MEDICAL GROUP")."""
    if not name or not is_organisation(name):
        return False
    toks = normalise(name).split()
    if any(t in PERSON_MARKERS for t in toks) or any(len(t) == 1 and t.isalpha() for t in toks):
        return False          # a personal marker or a lone initial: a person stands behind this name
    if any(t in _TRADE and t not in _NAME_LIKE for t in toks):
        return True
    if any(t in _GIVEN for t in toks):
        return False          # a given name and no word for a trade ("JOHN SMITH GROUP")
    for i, t in enumerate(toks):
        if t in _NAME_LIKE and t not in {"CO", "SA"}:
            if i + 1 < len(toks) and toks[i + 1] == "OF":
                return True
            if t in _TRAILING and i == len(toks) - 1 and len(toks) >= 2 and all(len(x) > 1 for x in toks):
                return True
    # What is left has a company suffix and no word that says what the company is. With one ordinary word it is
    # a brand ("ACME INC"); with two or more it reads like a person's name, so it stays masked.
    plain = [t for t in toks if t not in _BARE_SUFFIX and t not in ORG_WORDS]
    return any(t in _STRONG for t in toks) and len(plain) <= 1


def mask_word(word: str) -> str:
    return word[:1] + MASK_DOT * MASK_DOTS if word else ""


def mask_name(name: str) -> str:
    """'SANTOS MARIA L' -> 'S··· M··· L···'. Each word keeps its first letter and nothing else: the dots are the
    same number for every word, so the mask does not show how long a name is or which word is only an initial."""
    return " ".join(mask_word(w) for w in (name or "").split())


def _safe_lines(lines: list[str], record: dict, said: set[str], organisation: bool) -> list[str]:
    """Removes anything from a reason or doubt that would reveal a private owner's name or street.

    `said` holds the words the person typed themselves, which may be repeated back to them.
    """
    street = (record.get("owner_street") or "").strip()
    private = set()
    if not organisation:
        private = {t for t in normalise(record.get("owner_name") or "").split() if len(t) > 1 and t not in said}
    out = []
    for line in lines:
        # The matcher never reads a street in a search and never quotes one. This is a second net.
        if street and street in line:
            line = line.replace(street, "the street on the record")
        if private:
            line = re.sub(r"[A-Z0-9]{2,}", lambda m: mask_word(m.group()) if m.group() in private else m.group(), line)
        out.append(line)
    return out


def public_record(record: dict, ids=None) -> dict:
    """The only fields of a register record that may leave the server. There is no street here on purpose, and
    `record_id` is an id of our own (record_ids.RecordIds), never the State's property number: that number opens
    the owner's full name and address on the State's own site."""
    name = record.get("owner_name") or ""
    organisation = shown_as_organisation(name)
    return {
        "record_id": ids.public(record) if ids is not None else None,
        "source": record.get("source"),
        "owner": name if organisation else mask_name(name),
        "owner_is_organisation": organisation,
        "amount": round(float(record.get("amount") or 0), 2),
        "currency": record.get("currency") or "USD",
        "holder_name": record.get("holder_name") or "",
        "property_type": record.get("property_type") or "",
        "owner_city": record.get("owner_city") or "",
        "owner_region": record.get("owner_region") or "",
        "owner_country": record.get("owner_country") or "",
    }


_Short = Field(default="", max_length=120)


class PlaceIn(BaseModel):
    city: str = _Short
    region: str = _Short
    postcode: str = _Short
    country: str = _Short
    street: str = _Short


class HistoryIn(BaseModel):
    """What a person tells us. The voice intake and the form both produce this shape."""
    given_names: list[str] = Field(default_factory=list, max_length=8)
    family_names: list[str] = Field(default_factory=list, max_length=8)
    places: list[PlaceIn] = Field(default_factory=list, max_length=20)
    employers: list[str] = Field(default_factory=list, max_length=20)
    current_country: str = _Short

    @field_validator("given_names", "family_names", "employers", mode="before")
    @classmethod
    def _as_list(cls, v):
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError("must be a list of text values")
        out = []
        for item in v:
            if not isinstance(item, str):
                raise ValueError("must be a list of text values")
            if len(item) > 120:
                raise ValueError("each entry must be 120 characters or fewer")
            if item.strip():
                out.append(item.strip())
        return out


class WordsIn(BaseModel):
    """Typed words in any language. `earlier` and `question` are sent when this answers a follow-up question."""
    text: str = Field(min_length=1, max_length=4000)
    earlier: str = Field(default="", max_length=intake.MAX_WORDS)
    question: str = Field(default="", max_length=400)


class Store:
    """One shared read-only connection. Each request takes its own cursor, which DuckDB allows across threads.

    `demonstration` is the separate table of demonstration records (demo.DemoStore), or None. `searching()` gives
    a cursor on every table there is, so one search runs over California's owner records and the demonstration
    records together. The server starts without the register database; `loaded()` says whether it is there."""

    def __init__(self, path: Path, demonstration: "demo.DemoStore | None" = None, queensland_path: Path | None = None):
        self.path = Path(path)
        self.demonstration = demonstration
        # Queensland's register is a file of its own (queensland.py). It is searched in the same pass and never
        # mixed into California's figures: its money is in Australian dollars.
        self.queensland_path = Path(queensland_path) if queensland_path else None
        self.lists = None          # the holder's own lists (outreach.OutreachStore), once the app has made it
        self._con: duckdb.DuckDBPyConnection | None = None
        self._qld: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    def queensland_loaded(self) -> bool:
        return bool(self.queensland_path and self.queensland_path.exists())

    def queensland_cursor(self) -> duckdb.DuckDBPyConnection | None:
        if not self.queensland_loaded():
            return None
        with self._lock:
            if self._qld is None:
                self._qld = duckdb.connect(str(self.queensland_path), read_only=True)
            return self._qld.cursor()

    def loaded(self) -> bool:
        return self.path.exists()

    @contextmanager
    def searching(self):
        """Cursors on every table a search runs over. Without the register database and without demonstration
        records there is nothing to search, and the answer is 503 as before."""
        cursors = []
        try:
            if self.loaded() or self.demonstration is None:
                cursors.append(self.cursor())
            if self.demonstration is not None:
                cursors.append(self.demonstration.cursor())
            other = self.queensland_cursor()
            if other is not None:
                cursors.append(other)
            yield cursors
        finally:
            for cur in cursors:
                cur.close()

    @contextmanager
    def looking_up(self):
        """Cursors for finding one record by its own number: every table a search runs over, and the holder's
        own lists, which no search reads. A claim opened from a notice is compared with its record this way."""
        with self.searching() as cursors:
            extra = [self.lists.cursor()] if self.lists is not None else []
            try:
                yield cursors + extra
            finally:
                for cur in extra:
                    cur.close()

    def cursor(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is None:
                if not self.path.exists():
                    raise HTTPException(503, "The register database has not been loaded yet. See the README.")
                self._con = duckdb.connect(str(self.path), read_only=True)
            return self._con.cursor()

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None
            if self._qld is not None:
                self._qld.close()
                self._qld = None
        if self.demonstration is not None:
            self.demonstration.close()


def build_totals(raw: dict) -> dict:
    """Adds names and map positions to the totals file. Every figure counts properties, each one once (the file's
    `rule` says how). Codes with no certain meaning are kept in one 'other' line, apart from the countries."""
    from .countries import US_TERRITORIES

    merged: dict[str, dict] = {}
    kept = raw.get("other") or {}
    other = {"code": "other", "name": "Country codes that cannot be placed",
             "properties": int(kept.get("properties") or 0), "amount": float(kept.get("amount") or 0),
             "codes": int(kept.get("codes") or 0)}
    settled = bool(raw.get("codes_resolved"))     # registers.totals has already read every code
    for row in raw.get("by_country", []):
        code = row.get("code", "")
        iso = code if settled and code in COUNTRIES else resolve(code, TRUSTED_CODES)
        if iso is None or iso == "US" or iso in US_TERRITORIES:
            other["properties"] += int(row.get("properties") or 0)
            other["amount"] += float(row.get("amount") or 0)
            other["codes"] += 1
            continue
        slot = merged.setdefault(iso, {**COUNTRIES[iso], "properties": 0, "amount": 0.0})
        slot["properties"] += int(row.get("properties") or 0)
        slot["amount"] += float(row.get("amount") or 0)
    countries = sorted(merged.values(), key=lambda c: -c["amount"])
    for c in countries:
        c["amount"] = round(c["amount"], 2)
    other["amount"] = round(other["amount"], 2)
    out = {k: v for k, v in raw.items() if k not in ("by_country", "other")}
    out.update({"origin": ORIGIN, "countries": countries, "other": other, "by_country": raw.get("by_country", [])})
    return out


def create_app(db_path: Path | str | None = None, totals_path: Path | str | None = None,
               web_dist: Path | str | None = None, claims_dir: Path | str | None = None,
               airwallex_factory=None, payout_pause: float = 1.0, read_documents: bool = False,
               payer_key: str | None = None, watch_seconds: float | None = None,
               watch_pause: float | None = None, demonstration: bool = False,
               search_per_minute: int | None = None, search_per_hour: int | None = None,
               clock=time.monotonic, queensland_path: Path | str | None = None,
               books_path: Path | str | None = None, corridors_path: Path | str | None = None,
               metal=None, metal_scale=None, metal_keys=None,
               public_demo_mode: bool | None = None, public_url: str | None = None,
               outreach_model: bool = True, outreach_today=None) -> FastAPI:
    """`claims_dir` defaults to a `claims` folder beside the register database (data/claims in a normal run).
    `airwallex_factory` returns (client, simulator) and exists so tests can run payouts without the network.
    `read_documents` switches on the document reading and the proof file. The served app (`app` below) has it
    on. With it off, uploads are stored unread, the checklist trusts the kind the claimant chose and a payer's
    approval is not held back, which is how the product behaved before the reading was built.
    `demonstration` adds the demonstration records (demo.py) to every search, in a table of their own beside
    California's owner records. The served app has it on unless KHUTLISA_DEMONSTRATION=0.
    `search_per_minute` and `search_per_hour` are how many searches one client address may make; they default
    to KHUTLISA_SEARCHES_PER_MINUTE and KHUTLISA_SEARCHES_PER_HOUR, and then to 30 and 300. 0 switches a limit
    off. `clock` gives the seconds they are counted in, so a test need not wait.
    `queensland_path` is Queensland's register (queensland.py); by default the file beside the register database,
    and it is searched only when it is there. `books_path` and `corridors_path` are the prepared files the "Book"
    screen plans from (book.py and corridors.py).
    `metal` is the chain a claim can be funded on (metal.FakeMetal in the tests). Left out, the real Metal
    command line is used when ~/.khutlisa_metal is set up, and funding on Metal is off when it is not.
    `metal_scale` is how many US dollars one *USDZ stands for, and `metal_keys` where mandate keys are written.
    `public_demo_mode` is the public demonstration (public_demo.py); it defaults to KHUTLISA_PUBLIC_DEMO.
    `public_url` is the address owners are sent to in a notice (KHUTLISA_PUBLIC_URL). `outreach_model` lets the
    holder's list ask a language model to propose its column mapping, and `outreach_today` fixes the day the
    holder's calendar is counted from, for tests."""
    db_path = Path(db_path or os.environ.get("KHUTLISA_DB") or DB_PATH)
    queensland_path = Path(queensland_path or os.environ.get("KHUTLISA_QUEENSLAND") or db_path.parent / "queensland.duckdb")

    def limit(given: int | None, name: str, default: int) -> int:
        return int(given if given is not None else os.environ.get(name) or default)

    limits = [(limit(search_per_minute, "KHUTLISA_SEARCHES_PER_MINUTE", SEARCHES_PER_MINUTE), MINUTE),
              (limit(search_per_hour, "KHUTLISA_SEARCHES_PER_HOUR", SEARCHES_PER_HOUR), HOUR)]
    # The person search and the organisation search are counted apart, each per client address, in memory.
    windows = {"search": SlidingWindow(limits, clock), "organisations": SlidingWindow(limits, clock),
               "book": SlidingWindow(limits, clock)}

    def counted(kind: str):
        """A dependency that counts one search for the caller, or answers 429 with the seconds to wait. The
        caller is the address the connection came from. Nothing the caller writes in a header is believed. The
        server program in front of this app (uvicorn) can itself rewrite the client address from
        X-Forwarded-For when the connection comes from the same machine, so a request that carries any
        forwarding header is also counted on one count shared by all such requests: sending a new address in
        the header with every request gains nothing. Behind a proxy, then, every caller shares one count."""
        def check(request: Request) -> None:
            keys = clients.keys(request)       # the caller, and how a proxy of our own is handled: clients.py
            for who in keys:
                wait = windows[kind].take(who)
                if wait:
                    break
            if wait:
                n, seconds = windows[kind].full_limit(who) or limits[0]
                raise HTTPException(
                    429, f"Too many searches have come from this address: the limit is {n} in "
                         f"{'a minute' if seconds == MINUTE else 'an hour'}. Try again in {wait} "
                         f"{'second' if wait == 1 else 'seconds'}.",
                    headers={"Retry-After": str(wait)})
        return check

    claim_store = ClaimStore(claims_dir or os.environ.get("KHUTLISA_CLAIMS") or db_path.parent / "claims")
    demo_mode = public_demo.enabled() if public_demo_mode is None else public_demo_mode
    # In the public demonstration the payment explanations are the fixed sentences: no model rewords them.
    runner = PayoutRunner(claim_store, airwallex_factory or sandbox_factory, pause=payout_pause,
                          watch_seconds=watch_seconds, watch_pause=watch_pause,
                          **({"word": public_demo.fixed_wording} if demo_mode else {}))
    # The payer's routes need this shared key in the X-Payer-Key header. With no key set they answer 401 always.
    payer_key = payer_key if payer_key is not None else os.environ.get("KHUTLISA_PAYER_KEY", "")
    ids = RecordIds(claim_store.folder / "record_ids.sqlite")

    def public(record: dict) -> dict:
        return public_record(record, ids)
    totals_path = Path(totals_path or os.environ.get("KHUTLISA_TOTALS") or TOTALS_PATH)
    web_dist = Path(web_dist or os.environ.get("KHUTLISA_WEB") or WEB_DIST)
    store = Store(db_path, demo.DemoStore() if demonstration else None, queensland_path)
    batch_runner = batches.BatchRunner(claim_store.folder / "batches", airwallex_factory or sandbox_factory,
                                       pause=payout_pause)

    @asynccontextmanager
    async def lifespan(started: FastAPI):
        runner.resume_all()   # payouts that were under way when the server last stopped carry on; none is remade
        if started.state.read_documents:
            started.state.reading.resume_all()   # so do document readings
        batch_runner.resume_all()   # and batches that were approved and not finished; none is made
        started.state.estates.resume_all()       # and estate settlements, each heir's payout with its own ids
        yield
        runner.stop()
        batch_runner.stop()
        started.state.estates.stop()
        store.close()

    app = FastAPI(title="Khutlisa", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
                  lifespan=lifespan)
    app.state.store = store
    app.state.claims = claim_store
    app.state.payouts = runner
    app.state.batches = batch_runner

    @app.get("/api/totals")
    def totals() -> dict:
        """The opening's totals, in properties. When the totals file has not been made, the totals file beside
        the database is used instead: beside the sample register that is its own file, marked `sample`."""
        for path in (totals_path, db_path.parent / "totals.json"):
            if path.exists():
                return build_totals(json.loads(path.read_text()))
        raise HTTPException(503, "The totals file has not been made yet. Run scripts/make_totals.py (see the README).")

    register_facts: dict = {}

    @app.get("/api/register")
    def register_info() -> dict:
        """How many owner records the search runs over (one for each owner of a property), and whether this is
        the sample register of invented records (every record's source is SAMPLE). `records` is the same number
        under its older name."""
        if not register_facts:
            total = sample = 0
            if store.loaded() or not demonstration:
                cur = store.cursor()
                try:
                    total, sample = cur.execute(
                        "select count(*), count(*) filter (where source = 'SAMPLE') from records").fetchone()
                finally:
                    cur.close()
            register_facts.update({"owner_records": int(total), "records": int(total),
                                   "sample": bool(total) and total == sample})
            if demonstration:    # the demonstration records are counted apart and never as California's
                register_facts.update({"loaded": store.loaded(), "demonstration_records": store.demonstration.count()})
            other = queensland_facts()
            if other is not None:    # only where Queensland's register is loaded on this server
                register_facts["queensland"] = other
        return register_facts

    def queensland_facts() -> dict | None:
        """Queensland's register as it is loaded on this server: its own count, its own currency, and the
        attribution its licence asks for. None when it is not loaded. Its figures are never added to
        California's."""
        cur = store.queensland_cursor()
        if cur is None:
            return None
        try:
            n, amount = cur.execute("select count(*), coalesce(sum(amount), 0) from records").fetchone()
        finally:
            cur.close()
        stored = queensland.facts(store.queensland_path) or {}
        return {"source": queensland.SOURCE, "name": "Queensland", "owner_records": int(n),
                "amount": round(float(amount), 2), "currency": queensland.CURRENCY,
                "matches_portal": stored.get("matches_portal"), "loaded_at": stored.get("loaded_at"),
                "attribution": queensland.ATTRIBUTION, "licence": queensland.LICENCE,
                "licence_url": queensland.LICENCE_URL, "dataset": queensland.DATASET_URL,
                "claim_url": queensland.CLAIM_URL}

    @app.get("/api/demonstration")
    def demonstration_people() -> dict:
        """The demonstration people: their prepared words, their details for "fill for me", and their sample
        documents. Everything here is invented. Empty when the demonstration records are switched off."""
        if not demonstration:
            return {"people": [], "records": 0}
        return {"people": demo.people(), "records": store.demonstration.count(),
                "speech_ready": speech.engine() is not None}

    @app.get("/api/countries")
    def countries() -> list[dict]:
        """Every country the form can offer for 'where do you live now'."""
        return sorted(({"code": c["code"], "name": c["name"]} for c in COUNTRIES.values()), key=lambda c: c["name"])

    @app.post("/api/search", dependencies=[Depends(counted("search"))])
    def search(body: HistoryIn) -> dict:
        """Anyone may call this, so it must not confirm anything about a private person's street. A street in
        the request is dropped before the search and the matcher does not read the record's street either: the
        reply is the same for the right street, a wrong one and none. A street is compared only inside a claim
        (claims_api.py), after photo identification has been read."""
        person = Person(given=body.given_names, family=body.family_names)
        if not any(len(k) >= 2 for k in person.family_keys()):
            raise HTTPException(422, "Give at least one family name of two letters or more.")
        history = History(
            person=person,
            places=[Place(**place) for place in ({**p.model_dump(), "street": ""} for p in body.places)
                    if any(place.values())],
            employers=body.employers,
            current_country=body.current_country.strip(),
        )
        said = set(normalise(" ".join(
            body.given_names + body.family_names + body.employers
            + [v for p in body.places for k, v in p.model_dump().items() if k != "street"])).split())
        started = time.perf_counter()
        with store.searching() as cursors:     # one pass: California's owner records and the demonstration records
            everything = find(cursors, history, top=5000, floor=SEARCH_FLOOR)
        # "Strong" is the rule in match.strength_of, never the points. The points only order the list.
        strong = [m for m in everything if m.strength == "strong"]
        found = everything[:500]
        # Every strong match is listed (up to the limit), then the possible ones with the most points.
        shown = strong[:MAX_MATCHES]
        shown += [m for m in found if m.strength != "strong"][:MAX_MATCHES - len(shown)]
        shown.sort(key=lambda m: -m.score)
        matches = []
        for m in shown:
            row = public(m.record)
            org = row["owner_is_organisation"]
            row.update({
                "score": m.score,
                "strength": m.strength,
                "above_line": m.strength == "strong",
                **({"note": STRONG_NOTE} if m.strength == "strong" else {}),
                "reasons": _safe_lines(m.reasons, m.record, said, org),
                "doubts": _safe_lines(m.doubts, m.record, said, org),
            })
            matches.append(row)
        return {
            "confidence_line": CONFIDENCE_LINE,
            "found": len(found),
            "found_is_capped": len(found) >= 500,
            "strength_rule": STRENGTH_RULE,
            "strong_note": STRONG_NOTE,       # the one line every strong match carries; also on each strong row
            "strong_count": len(strong),
            # Money is added up one currency at a time. `strong_amount` is the US dollars only, as before;
            # `strong_amounts` has every currency found, each on its own line. Nothing is converted.
            "strong_amount": by_currency(strong).get("USD", 0.0),
            "strong_amounts": [{"currency": c, "amount": a} for c, a in sorted(by_currency(strong).items())],
            "possible_count": len(found) - sum(1 for m in found if m.strength == "strong"),
            "confident_count": len(strong),          # the same two figures under their older names
            "confident_amount": by_currency(strong).get("USD", 0.0),
            "currency": "USD",
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "searched": searched(),
            "matches": matches,
        }

    def by_currency(matches: list) -> dict[str, float]:
        sums: dict[str, float] = {}
        for m in matches:
            currency = m.record.get("currency") or "USD"
            sums[currency] = sums.get(currency, 0.0) + float(m.record.get("amount") or 0)
        return {c: round(a, 2) for c, a in sums.items()}

    def searched() -> dict:
        """What a search ran over, for the one line above the results."""
        loaded = store.loaded() or not demonstration
        other = register_info().get("queensland") or {}
        out = {"register_loaded": loaded,
               "owner_records": register_info()["owner_records"] if loaded else 0,
               "demonstration_records": store.demonstration.count() if demonstration else 0}
        if other:
            out.update({"queensland_records": int(other.get("owner_records") or 0),
                        "queensland_attribution": other.get("attribution")})
        return out

    @app.get("/api/organisations/notable")
    def notable_organisations() -> dict:
        """A prepared set of organisations that appear as owners in California's file, chosen by hand for amount
        and for being widely known, with the amounts read from the file by scripts/make_notable_organisations.py.
        It is served from a small file, so it is there without the register database."""
        if not NOTABLE_PATH.exists():
            raise HTTPException(503, "The prepared examples have not been made yet. Run "
                                     "scripts/make_notable_organisations.py (see the README).")
        out = {**json.loads(NOTABLE_PATH.read_text()), "check_url": CLAIMIT_SEARCH}
        if QUEENSLAND_EXAMPLES_PATH.exists():     # organisations in Queensland's register, in Australian dollars
            out["queensland"] = json.loads(QUEENSLAND_EXAMPLES_PATH.read_text())
        return out

    @app.get("/api/organisations", dependencies=[Depends(counted("organisations"))])
    def organisations(q: str = Query(..., max_length=80)) -> dict:
        """Organisation-owned records whose name contains q, largest first. Individuals are never returned."""
        needle = normalise(q)
        if len(needle.replace(" ", "")) < 3:
            raise HTTPException(422, "Type at least three letters or digits.")
        cols = ["source", "record_id", "owner_name", "owner_city", "owner_region", "owner_country", "amount",
                "currency", "holder_name", "property_type"]
        if demonstration and not store.loaded():
            raise HTTPException(503, "California's file is not loaded on this server, so names cannot be searched "
                                     "here. The prepared examples below were read from the file earlier.")
        started = time.perf_counter()
        cur = store.cursor()
        try:
            rows = cur.execute(
                f"select {', '.join(cols)} from records where contains(owner_norm, ?) order by amount desc limit 2000",
                [needle]).fetchall()
        finally:
            cur.close()
        results = []
        for row in rows:
            record = dict(zip(cols, row))
            if shown_as_organisation(record["owner_name"] or ""):
                results.append(public(record))
                if len(results) >= MAX_ORGANISATIONS:
                    break
        # Queensland's register is asked in the same request and kept apart: its amounts are Australian dollars.
        other = []
        qld = store.queensland_cursor()
        if qld is not None:
            try:
                rows = qld.execute(
                    f"select {', '.join(cols)} from records where contains(owner_norm, ?) order by amount desc limit 2000",
                    [needle]).fetchall()
            finally:
                qld.close()
            for row in rows:
                record = dict(zip(cols, row))
                if shown_as_organisation(record["owner_name"] or ""):
                    other.append(public(record))
                    if len(other) >= MAX_ORGANISATIONS:
                        break
        facts = register_info()
        return {"query": needle, "results": results, "check_url": CLAIMIT_SEARCH,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "owner_records": facts["owner_records"],
                **({"queensland": {"results": other, "currency": queensland.CURRENCY,
                                   "owner_records": (facts.get("queensland") or {}).get("owner_records", 0),
                                   "attribution": queensland.ATTRIBUTION, "claim_url": queensland.CLAIM_URL}}
                   if qld is not None else {})}

    # ---- the intake: a life told aloud or typed, in any language -------------------------------------------

    intake_model = os.environ.get("KHUTLISA_INTAKE_MODEL", "sonnet")

    def understood(words: str, earlier: str, question: str, heard: dict | None = None) -> dict:
        started = time.perf_counter()
        try:
            out = intake.understand(words, earlier, question, model=intake_model)
        except llm.ModelUnavailable as err:
            if getattr(err, "for_screen", False):      # the public demonstration's daily budget is used up
                raise HTTPException(503, str(err)) from None
            raise HTTPException(503, "The language model that reads your words is not available on this machine. "
                                     "You can fill in the form yourself.") from None
        except Exception:
            raise HTTPException(502, "Your words could not be turned into a history this time. Try again, or "
                                     "fill in the form yourself.") from None
        out["seconds"] = {"understand": round(time.perf_counter() - started, 1)}
        if heard is not None:
            out["seconds"]["transcribe"] = heard["seconds"]
            out["heard_language"] = speech.language_name(heard.get("language") or "")
            out["language"] = out["language"] or out["heard_language"]
        return out

    @app.get("/api/intake/sample")
    def intake_sample() -> dict:
        """The prepared sentence behind "Hear an example". The person in it is made up."""
        return {"language": "Tagalog", "text": intake.SAMPLE_TAGALOG, "speech_ready": speech.engine() is not None}

    @app.post("/api/intake/text")
    def intake_text(body: WordsIn) -> dict:
        if not body.text.strip():
            raise HTTPException(422, "Type a few words about where you have lived and worked.")
        return understood(body.text, body.earlier, body.question)

    # In the public demonstration only the demonstration sound files are transcribed (public_demo.Gate), and the
    # same file always gives the same words, so each one is transcribed once and its words kept in memory: on a
    # small server a transcription takes most of a minute. Nothing a visitor recorded is ever kept.
    heard_before: dict[str, dict] = {}

    def hear(file: UploadFile) -> dict:
        """The sound turned into words on this machine: {text, language, seconds}. The sound is not kept."""
        data = file.file.read(speech.MAX_BYTES + 1)
        if len(data) > speech.MAX_BYTES:
            raise HTTPException(413, "The recording is too large. Record a shorter account, up to five minutes.")
        if len(data) < 200:
            raise HTTPException(422, "The recording is empty. Check that the microphone is allowed, then try again.")
        started = time.perf_counter()
        digest = hashlib.sha256(data).hexdigest() if demo_mode else None
        if digest in heard_before:
            return {**heard_before[digest], "seconds": round(time.perf_counter() - started, 1)}
        with tempfile.TemporaryDirectory(prefix="khutlisa-audio-") as tmp:   # the recording is not kept
            path = Path(tmp) / "recording"
            path.write_bytes(data)
            try:
                heard = speech.transcribe(path)
            except speech.SpeechUnavailable as err:
                raise HTTPException(503, str(err)) from None
            except Exception:
                raise HTTPException(502, "The recording could not be turned into words. Try again, or type "
                                         "your history instead.") from None
        if len((heard.get("text") or "").strip()) < 3:
            raise HTTPException(422, "No words could be heard in the recording. Speak a little closer to the "
                                     "microphone, or type your history instead.")
        heard["seconds"] = round(time.perf_counter() - started, 1)
        if digest:
            heard_before[digest] = dict(heard)
        return heard

    @app.post("/api/intake/audio")
    def intake_audio(file: UploadFile = File(...), earlier: str = Form(default="", max_length=intake.MAX_WORDS),
                     question: str = Form(default="", max_length=400)) -> dict:
        heard = hear(file)
        return understood(heard["text"], earlier, question, heard)

    @app.post("/api/intake/heard")
    def intake_heard(file: UploadFile = File(...)) -> dict:
        """Only the first half of /api/intake/audio: the words the recogniser heard, with no language model. The
        spoken example asks for this so it can show the heard words while its sound is still playing."""
        heard = hear(file)
        return {"transcript": heard["text"].strip(), "seconds": heard["seconds"],
                "heard_language": speech.language_name(heard.get("language") or "")}

    app.state.public_record = public
    claims_api.register(app, store, claim_store, runner, HistoryIn, public, _safe_lines,
                        read_documents=read_documents, ids=ids, payer_key=payer_key)

    # Funding on Metal: the holder's mandate, the agent's pull, and the panel that shows both (metal_api.py).
    metal_api.register(app, claim_store, runner, payer_key, chain=metal, scale=metal_scale, keys_folder=metal_keys,
                       public_demo=demo_mode)

    # Indicative amounts for the match cards and the plan summary on the claim screen. Nothing is locked.
    money_api.register(app, claim_store, Indicative(runner.factory),
                       proof_ready=(lambda claim: app.state.proof_ready(claim)) if read_documents else None)

    # The whole book of one holder, planned, and a batch run from the plan.
    book_api.register(app, claim_store, batch_runner, runner.factory, payer_key=payer_key,
                      books_path=Path(books_path) if books_path else (Path(os.environ["KHUTLISA_BOOKS"]) if os.environ.get("KHUTLISA_BOOKS") else None),
                      corridors_path=Path(corridors_path) if corridors_path else None, counted=counted("book"))

    # Estates (an owner who has died, paid to several heirs in one settlement) and the risk view (claims linked
    # across the queue). Each lives in its own module and adds its routes here.
    estates_api.register(app, claim_store, runner.factory, intake_model=intake_model)
    rings_api.register(app, claim_store)

    # The holder's own list, the notices prepared from it, and the owner's answer to a notice (outreach_api.py).
    store.lists = outreach_api.register(
        app, claim_store, HistoryIn, payer_key=payer_key, demo_only=demo_mode,
        public_url=public_url if public_url is not None else os.environ.get("KHUTLISA_PUBLIC_URL", ""),
        use_model=outreach_model, today=outreach_today, clock=clock)

    # Health, readiness and the public demonstration (public_demo.py).
    budget = None
    llm.gate = None
    llm.recorded = None
    if demo_mode:
        budget = public_demo.DailyBudget(int(os.environ.get("KHUTLISA_MODEL_CALLS_PER_DAY") or 150))
        llm.gate = budget.take
        # The model's answers to the demonstration's fixed inputs, recorded in advance (recorded.py).
        llm.recorded = recorded.RecordedAnswers.load()
        app.add_middleware(public_demo.Gate, claim_store=claim_store, record_ids=ids, web_dist=web_dist,
                           per_minute=int(os.environ.get("KHUTLISA_REQUESTS_PER_MINUTE") or 240),
                           per_hour=int(os.environ.get("KHUTLISA_REQUESTS_PER_HOUR") or 3000), clock=clock,
                           batches=batch_runner)
    app.state.model_budget = budget
    public_demo.register(app, store=store, claim_store=claim_store, runner=runner, web_dist=web_dist,
                         payer_key=payer_key, public_demo=demo_mode, budget=budget)

    @app.get("/api/{rest:path}", include_in_schema=False)
    def no_such_api(rest: str):
        raise HTTPException(404, "There is no such address in this API.")

    if (web_dist / "index.html").exists():
        if (web_dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{rest:path}", include_in_schema=False)
        def front_end(rest: str):
            target = (web_dist / rest).resolve()
            if rest and target.is_file() and web_dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(web_dist / "index.html")

    return app


app = create_app(read_documents=os.environ.get("KHUTLISA_READ_DOCUMENTS", "1") != "0",
                 demonstration=os.environ.get("KHUTLISA_DEMONSTRATION", "1") != "0")
