"""Holders: the organisations that reported each property to California, and the money they reported for owners
whose last known address is in another country.

A holder is the business that owed the money in the first place (a bank, an employer, an insurer, a broker, a
retailer). California's file names it on every property. `compute` adds the properties up by holder, using the
project's one definition of "abroad" (registers.build_away) and counting each property once. The figures are
written to holders_abroad.json by scripts/make_holders.py and served from that file.

Holder names are organisations, but a few carry a person's name (a practice, or a firm named after its owner).
Those are counted in every total and never listed by name (`listable`).
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb

from .names import normalise

FILE = Path(__file__).with_name("holders_abroad.json")
LISTED = 25

_BANK_FORM = re.compile(r"\b(N\.?\s?A\.?|F\.?S\.?B\.?|F\.?A\.?|NT\s?&\s?SA)(?=\W|$)", re.I)
_BRACKETS = re.compile(r"\([^)]*\)?")
_KEY = re.compile(r"[^A-Z0-9]+")


def key(name: str | None) -> str:
    """The name in capitals with punctuation and extra spaces taken out. Two spellings with one key are one line."""
    return _KEY.sub(" ", (name or "").upper()).strip()


# Companies that the file writes in several ways (branch names, old names, punctuation). A name belongs to a
# family when it is one of these word sequences or starts with one followed by another word. Each list was made by
# reading every spelling it catches in the file; scripts/make_holders.py prints them for that purpose.
FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Bank of America", ("BANK OF AMERICA",)),
    ("Charles Schwab", ("CHARLES SCHWAB",)),
    ("Union Bank", ("UNION BANK N A", "UNION BANK NA", "UNION BANK OF CALIFORNIA")),
    ("Wells Fargo", ("WELLS FARGO",)),
    ("Citibank", ("CITIBANK",)),
    ("Cisco Systems", ("CISCO SYSTEMS",)),
    ("Washington Mutual", ("WASHINGTON MUTUAL",)),
    ("JPMorgan Chase", ("JPMORGAN CHASE", "JP MORGAN CHASE")),
)

# Holder names the strict organisation rule would hide (it sees a given name or a legal form it does not know)
# and that were read by hand and are well-known organisations. Compared after `key`.
READ_BY_HAND = frozenset(key(n) for n in (
    "HERBALIFE INTERNATIONAL OF AMERICA INC", "TURNITIN LLC", "KIVA USER FUNDS LLC", "BANAMEX USA",
    "THE BANK OF NEW YORK MELLON TRUST COMPAN", "CTBC BANK CORP USA", "STANFORD FEDERAL CREDIT UNION",
    "CALIFORNIA BANK & TRUST", "CALIFORNIA BANK AND TRUST", "SHANGHAI COMMERCIAL BANK LTD.",
    "THE BOARD OF TRUSTEES OF LELAND STANFORD", "FIRST TECH FEDERAL CREDIT UNION", "EDISON INTERNATIONAL",
    "TECHNOLOGY CREDIT UNION", "BANC OF CALIFORNIA", "MERIWEST CREDIT UNION", "HEWLETT-PACKARD COMPANY",
    "GEP ATL LLC DBA ENTERTAINMENT PARTNERS", "U. S. BANK, N. A.", "PG&E CORPORATION - COMMON", "SEMPRA ENERGY",
    "GOLDEN 1 CREDIT UNION", "U.S. BANK, TRUST TECHNOLOGY & SUPPORT SERVICES", "PREMIER AMERICA CREDIT UNION",
    "TRIMBLE NAVIGATION LIMITED", "BLUPEAK CREDIT UNION", "CHEVRON FEDERAL CREDIT UNION", "EPSON AMERICA INC.",
    "GEP TALENT SERVICE LLC DBA ENTERTAINMEN", "D-LINK SYSTEMS INC", "GEPCB LLC DBA ENTERTAINMENT PARTNERS",
    "DFS GROUP LP", "FULLER THEOLOGICAL SEMINARY", "ABC-CLIO LLC", "AURORA NATIONAL LIFE",
    "ADDISON AVENUE FEDERAL CREDIT UNION", "CALIFORNIA INSTITUTE OF TECHNOLOGY", "CEDARS-SINAI MEDICAL CENTER",
    "SHARP HEALTHCARE", "SCHOOLSFIRST FEDERAL CREDIT UNION", "USC CREDIT UNION", "SCRIPPS HEALTH",
    "MICROFABRICA LAB PERFORMANCE",
))

def family(name: str | None) -> str | None:
    """The company a spelling belongs to, when it is one of the hand-read families."""
    k = key(name)
    for shown, starts in FAMILIES:
        if any(k == s or k.startswith(s + " ") for s in starts):
            return shown
    return None


def listable(name: str | None) -> bool:
    """True when a holder name may be shown: a hand-read family, a hand-read organisation, or a name that passes
    the strict organisation rule once a bank's legal form ("N.A.", "FSB") and anything in brackets is set aside."""
    from .server import shown_as_organisation   # here, because the server imports this module

    if not key(name):
        return False
    if family(name) or key(name) in READ_BY_HAND:
        return True
    plain = _BANK_FORM.sub(" ", _BRACKETS.sub(" ", name or ""))
    plain = re.sub(r"\b\d+\b|BRANCH:.*$", " ", plain)
    return shown_as_organisation(" ".join(plain.split()))


# What kind of organisation a holder is, where its name says so. The words are matched as whole words on the name
# after `key`. A name that none of them fits is "not classified from the name": nothing is guessed. The platform
# list was read by hand: well-known companies whose business is a marketplace, a platform or money transfer.
KINDS: tuple[tuple[str, str], ...] = (
    ("insurer", "Insurers and health plans"),
    ("payroll", "Payroll companies"),
    ("platform", "Marketplaces, platforms and money transfer companies"),
    ("broker", "Brokers and investment funds"),
    ("bank", "Banks and credit unions"),
    ("education_health", "Universities, colleges and hospitals"),
    ("utility", "Utilities and telephone companies"),
    ("unclassified", "Not classified from the name"),
)
KIND_LABELS = dict(KINDS)
_KIND_WORDS = {
    "insurer": r"\b(INSURANCE|ASSURANCE|INDEMNITY|CASUALTY|HEALTH PLAN|NATIONAL LIFE|LIFE INS)\b",
    "payroll": r"\b(PAYROLL|STAFFING|ENTERTAINMENT PARTNERS|EMPLOYER GROUP)\b",
    "broker": r"\b(SECURITIES|BROKERAGE|GROWTH FUND|EQUITY FUND|INCOME FUND|MUTUAL FUND|LPL FINANCIAL)\b",
    "bank": r"\b(BANK|BANC|BANCORP|BANKAMERICA|UNIONBANCAL|CREDIT UNION|SAVINGS LOAN|SAVINGS AND LOAN|SAVINGS "
            r"ASSOCIATION|FEDERAL SAVINGS|BANAMEX)\b",
    "education_health": r"\b(UNIVERSITY|COLLEGE|INSTITUTE OF TECHNOLOGY|SEMINARY|MEDICAL CENTER|HOSPITAL|HOSPITALS|"
                        r"HEALTHCARE|LELAND STANFO\w*)\b",
    "utility": r"\b(GAS|ELECTRIC|EDISON|TELEPHONE|WATER DISTRICT|WATER COMPANY|SEMPRA|WIRELESS)\b",
}
_KIND_RULES = {k: re.compile(v) for k, v in _KIND_WORDS.items()}
_KIND_FAMILIES = {"Bank of America": "bank", "Union Bank": "bank", "Wells Fargo": "bank", "Citibank": "bank",
                  "Washington Mutual": "bank", "JPMorgan Chase": "bank", "Charles Schwab": "broker"}
PLATFORMS_READ_BY_HAND = frozenset(key(n) for n in (
    "KIVA USER FUNDS LLC", "UPWORK GLOBAL INC", "MONEYGRAM PAYMENT SYSTEMS INC", "WESTERN UNION FINANCIAL SERVICES INC",
    "WESTERN UNION FINANCIAL SERVICES", "INTERNET ESCROW SERVICES INC", "BANCOMER TRANSFER SERVICES INC",
    "TEMPO FINANCIAL US CORPORATION",
))


def kind_of(name: str | None) -> str:
    """The kind of holder, from its name alone: one of the keys in KINDS."""
    shown = family(name)
    if shown in _KIND_FAMILIES:
        return _KIND_FAMILIES[shown]
    k = key(name)
    if k in PLATFORMS_READ_BY_HAND:
        return "platform"
    for kind, _ in KINDS:
        rule = _KIND_RULES.get(kind)
        if rule is not None and rule.search(k):
            return kind
    return "unclassified"


def why_holders_pay(rows: list[tuple[str, str, int, float]], may_name=None, examples: int = 3) -> dict:
    """From (holder as written, property type as written, properties, dollars) rows for owners abroad:

      kinds_of_money    the properties and dollars by kind of money (property_types.GROUPS)
      kinds_of_holder   the holders, properties and dollars by kind of holder, where the name says what kind it
                        is (`kind_of`), with the largest holders of each kind that may be named
      wages             the holders that reported at least one wages property: employers and payroll companies,
                        told by what they reported and not by their names

    Organisations only: a holder is named only when `may_name` says its name may be shown."""
    from . import property_types as pt

    may_name = may_name or (lambda name: False)
    by_type: dict[str, list] = {}
    groups: dict[str, dict] = {}
    for written, kind, n, amount in rows:
        slot = by_type.setdefault(kind, [kind, 0, 0.0])
        slot[1] += int(n)
        slot[2] += float(amount)
        if not key(written):
            continue
        shown = family(written)
        g = groups.setdefault(shown or key(written), {"family": shown, "written": {}, "properties": 0, "amount": 0.0,
                                                      "wages_properties": 0, "wages_amount": 0.0})
        g["properties"] += int(n)
        g["amount"] += float(amount)
        g["written"][written] = g["written"].get(written, 0) + int(n)
        if pt.group_of(kind)[0] == "wages":
            g["wages_properties"] += int(n)
            g["wages_amount"] += float(amount)

    def name_of(g: dict) -> str:
        return g["family"] or sorted(g["written"], key=lambda w: (-g["written"][w], w))[0]

    def nameable(g: dict) -> bool:
        return bool(g["family"]) or all(may_name(w) for w in g["written"])

    kinds: dict[str, dict] = {k: {"key": k, "label": label, "holders": 0, "properties": 0, "amount": 0.0, "top": []}
                              for k, label in KINDS}
    for g in groups.values():
        slot = kinds[kind_of(name_of(g))]
        slot["holders"] += 1
        slot["properties"] += g["properties"]
        slot["amount"] += g["amount"]
        slot["top"].append(g)
    kinds_out = []
    for slot in kinds.values():
        ranked = sorted(slot["top"], key=lambda g: (-g["amount"], -g["properties"]))
        named = [{"name": name_of(g), "properties": g["properties"], "amount": round(g["amount"], 2)}
                 for g in ranked if nameable(g)][:examples]
        kinds_out.append({**slot, "amount": round(slot["amount"], 2),
                          "top": named if slot["key"] != "unclassified" else []})
    kinds_out.sort(key=lambda k: (k["key"] == "unclassified", -k["amount"]))
    paying = [g for g in groups.values() if g["wages_properties"]]
    ranked = sorted(paying, key=lambda g: (-g["wages_amount"], -g["wages_properties"]))
    wages = {"holders": len(paying), "properties": sum(g["wages_properties"] for g in paying),
             "amount": round(sum(g["wages_amount"] for g in paying), 2),
             "top": [{"name": name_of(g), "properties": g["wages_properties"], "amount": round(g["wages_amount"], 2)}
                     for g in ranked if nameable(g)][:5]}
    return {"kinds_of_money": pt.breakdown(list(map(tuple, by_type.values()))), "kinds_of_holder": kinds_out,
            "wages": wages,
            "kinds_source": {"label": pt.SOURCE_LABEL, "url": pt.SOURCE_URL, "read_on": pt.READ_ON}}


def compute(con: duckdb.DuckDBPyConnection, listed: int = LISTED) -> dict:
    """The figures, read from the register through `con`. Each property counts once, under the holder that
    reported it, when at least one of its owners has a last known address in another country."""
    from .registers import build_away

    build_away(con)
    con.execute("create or replace temp table holders_props as select source, record_id, max(amount) amount "
                "from totals_away where kind = 'abroad' group by 1, 2")
    con.execute("drop table totals_away")
    con.execute("""create or replace temp table holders_named as
        select p.source, p.record_id, p.amount, min(r.holder_name) holder, min(r.property_type) kind
        from records r join holders_props p on r.source = p.source and r.record_id = p.record_id
        group by 1, 2, 3""")
    properties, amount = con.execute("select count(*), coalesce(sum(amount), 0) from holders_named").fetchone()
    spellings = con.execute("select coalesce(holder, ''), count(*), coalesce(sum(amount), 0) from holders_named "
                            "group by 1").fetchall()
    kinds = con.execute("select coalesce(kind, ''), count(*), coalesce(sum(amount), 0) from holders_named "
                        "group by 1 order by 3 desc, 1 limit 8").fetchall()
    by_holder_and_type = con.execute("select coalesce(holder, ''), coalesce(kind, ''), count(*), coalesce(sum(amount), 0) "
                                     "from holders_named group by 1, 2").fetchall()
    con.execute("drop table holders_named")
    con.execute("drop table holders_props")

    groups: dict[str, dict] = {}
    for written, n, amt in spellings:
        if not key(written):
            continue
        shown = family(written)
        group = groups.setdefault(shown or key(written), {"family": shown, "written": {}, "properties": 0, "amount": 0.0})
        group["properties"] += int(n)
        group["amount"] += float(amt)
        group["written"][written] = group["written"].get(written, 0) + int(n)

    def row(group: dict) -> dict:
        commonest = sorted(group["written"], key=lambda w: (-group["written"][w], w))
        return {"name": group["family"] or commonest[0], "properties": group["properties"],
                "amount": round(group["amount"], 2), "spellings": len(group["written"]),
                "as_written": commonest[:4]}

    def may_list(group: dict) -> bool:
        return bool(group["family"]) or all(listable(w) for w in group["written"])

    skipped: set[int] = set()

    def first(order) -> list[dict]:
        """The first `listed` holders in this order that may be named. Any that may not be are passed over."""
        out = []
        for group in sorted(groups.values(), key=order):
            if len(out) == listed:
                break
            if may_list(group):
                out.append(row(group))
            else:
                skipped.add(id(group))
        return out

    by_amount = first(lambda g: (-g["amount"], -g["properties"]))
    by_properties = first(lambda g: (-g["properties"], -g["amount"]))
    top = by_amount[:10]
    amount = round(float(amount), 2)
    return {
        "properties": int(properties), "amount": amount,
        "holders_with_an_owner_abroad": len(groups),
        # Holders that rank among those listed but whose name could be a person's: counted, never named.
        "passed_over_as_possibly_a_person": len(skipped),
        "by_amount": by_amount, "by_properties": by_properties,
        "share_of_top_ten": {
            "amount_percent": round(sum(h["amount"] for h in top) / amount * 100, 1) if amount else 0.0,
            "properties_percent": round(sum(h["properties"] for h in top) / properties * 100, 1) if properties else 0.0},
        "property_types": [{"type": k, "properties": int(n), "amount": round(float(a), 2)} for k, n, a in kinds],
        **why_holders_pay(by_holder_and_type, may_name=listable),
        "families": [{"name": shown, "starts_with": list(starts)} for shown, starts in FAMILIES],
    }


RULE = ("Each property is counted once, under the holder that reported it, when at least one of its owners has a "
        "last known address in another country (United States territories are not another country). Holder names "
        "are as California's file writes them. Spellings that differ only in punctuation are one line, and the "
        "spellings of the few companies listed under 'families' are added together. A holder name that could be a "
        "person's name is counted in the totals and never listed.")

STATUS = ("No holder uses Khutlisa yet. The holder's view in this build is the same application behind a shared "
          "key, the holder's deposit is staged on the Airwallex sandbox, and no real money moves.")

PROPOSED_PRICING = {
    "label": "Proposed, not agreed with any holder",
    "text": "A fee per claim paid, charged to the holder: 2 percent of the amount, at least 2 US dollars and at "
            "most 25. Nothing is taken from the claimant. Airwallex's own fees are separate and are shown in "
            "every plan.",
}

_SCO = "https://www.sco.ca.gov/"
LAW = [
    {"title": "A holder must try to reach the owner first",
     "text": "Six to twelve months before a property becomes reportable, the holder must send a notice to an owner "
             "of 50 US dollars or more whose address it has: by post, or by email if the owner agreed to that.",
     "source": "Code of Civil Procedure 1520(b); State Controller, due diligence guide",
     "url": _SCO + "Files-UPD/upd_duediligence.pdf", "mark": "verified"},
    {"title": "The clock is short",
     "text": "Wages count as unclaimed one year after they were payable. Most other property, such as bank "
             "accounts, uncashed cheques and shares, after three years.",
     "source": "Code of Civil Procedure 1513 and 1520(a); State Controller, dormancy table",
     "url": _SCO + "Files-UPD/outreach_rptg_hol_dormancy.pdf", "mark": "verified"},
    {"title": "Two reports, and the money moves only with the second",
     "text": "The Notice Report is due before 1 November and no money is sent with it. The Controller then writes "
             "to the owners and tells them to contact the holder. The Remit Report and the money follow between "
             "1 and 15 June.",
     "source": "Code of Civil Procedure 1530(d), 1531(b), 1532(a); State Controller, how to report",
     "url": _SCO + "upd_how_to_report.html", "mark": "verified"},
    {"title": "Before the handover, the holder pays the owner itself",
     "text": "If the owner establishes their right before the property is delivered, the holder shall not deliver "
             "it to the Controller. Properties reunited with their owners are taken off the Remit Report.",
     "source": "Code of Civil Procedure 1532(b); State Controller, general reporting information",
     "url": _SCO + "Files-UPD/outreach_rptg_hol_genrptinfo.pdf", "mark": "verified"},
    {"title": "After the handover, the holder may still pay and is repaid",
     "text": "A holder that has paid the money to the Controller may pay the person entitled to it, and the "
             "Controller reimburses the holder on proof of the payment (form HCR-1).",
     "source": "Code of Civil Procedure 1560(b); State Controller, holder reimbursement guide",
     "url": _SCO + "Files-UPD/QuickGuide_HolderReimburseRequest_2017.pdf", "mark": "verified"},
    {"title": "Being late costs 12 percent a year",
     "text": "Property reported, paid or delivered late carries interest of 12 percent a year from the date it was "
             "due.",
     "source": "Code of Civil Procedure 1577",
     "url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CCP&sectionNum=1577.",
     "mark": "verified"},
    {"title": "The State is the fallback, and it pays by cheque",
     "text": "Once the State holds the property, the owner claims it from the Controller, who posts a cheque. "
             "\"There is no option for direct deposit for unclaimed property payments.\"",
     "source": "State Controller, payment questions",
     "url": _SCO + "upd_faq_payment.html", "mark": "verified"},
    {"title": "A bank transfer to an owner abroad is not named and not ruled out",
     "text": "The Controller's pages give reissuing a cheque and reactivating an account as ways to reunite "
             "property with its owner. They say nothing for or against a bank transfer, at home or abroad. "
             "Treating a transfer to the owner's own account as such a way is our reading, not the Controller's.",
     "source": "State Controller, general reporting information (what it does not say)",
     "url": _SCO + "Files-UPD/outreach_rptg_hol_genrptinfo.pdf", "mark": "our reading"},
]

# Who the buyer is and why, in lines that each rest on a page of the State Controller or on the statute as the
# Controller prints it (docs/CALIFORNIA_CLAIMS.md, read on 12 and 13 Nov 2026). Nothing here is a holder's own
# cost, quote or saving: none is known to us, so none is given.
_LAW_PDF = _SCO + "files-upd/guide_upd_updlaw.pdf"
BUYER = {
    "who": "Any holder with a bank account can pay by transfer today: an employer or payroll company holding "
           "final wages, a marketplace or platform holding balances and credits, a bank, a broker, an insurer. "
           "The State cannot. It pays by a cheque in the post.",
    "why": [
        {"title": "It has to write to the owner anyway",
         "text": "Six to twelve months before a property becomes reportable, the holder must send its own notice "
                 "to every owner of 50 US dollars or more whose address it has. \"California's unclaimed property "
                 "law requires holders to write and send due diligence letters independently.\"",
         "source": "Code of Civil Procedure 1520(b); State Controller, reporting questions",
         "url": _SCO + "upd_reporting_portal_faq.html"},
        {"title": "It may charge at most two dollars for that notice",
         "text": "A bank may deduct a service charge for the notice only up to what sending it cost, \"and in no "
                 "case to exceed two dollars ($2)\". The same cap holds for securities.",
         "source": "Code of Civil Procedure 1513.5(a) and 1516(d), as printed by the State Controller",
         "url": _LAW_PDF},
        {"title": "It reports twice and keeps the records for seven years",
         "text": "A Notice Report before 1 November, a Remit Report with the money between 1 and 15 June, both "
                 "through the Controller's portal, and \"all records pertaining to property for a period of seven "
                 "(7) years\" after the report.",
         "source": "Code of Civil Procedure 1530(d) and 1532(a); California Code of Regulations, title 2, 1175",
         "url": _LAW_PDF},
        {"title": "If the owner answers in time, the money never goes to the State",
         "text": "Where the owner establishes the right before delivery, \"the holder shall not pay or deliver the "
                 "property to the Controller\". Properties reunited with owners come off the Remit Report.",
         "source": "Code of Civil Procedure 1532(b); State Controller, general reporting information",
         "url": _SCO + "Files-UPD/outreach_rptg_hol_genrptinfo.pdf"},
        {"title": "Being late costs 12 percent a year",
         "text": "Property reported, paid or delivered late carries \"interest at the rate of 12 percent per annum\" "
                 "from the date it was due.",
         "source": "Code of Civil Procedure 1577(a), as printed by the State Controller",
         "url": _LAW_PDF},
    ],
    "already_with_the_state": "The figures on this screen are from the State's own file, so most of that money has "
                              "already been handed over. It is the record of owners who were not reached in time. "
                              "The plan is for the list a holder still holds, before its next handover.",
    "not_stated": "What these duties cost any one holder is not published, and no figure for it is given here.",
}

IN_SHORT = {
    "pay": "California's law tells a holder to pay the owner itself if the owner proves the claim before the "
           "handover (Code of Civil Procedure 1532(b)), and lets it pay afterwards and be repaid by the State "
           "(1560(b)).",
    "schedule": "The property is due to the State between 1 and 15 June each year (1532(a)).",
    "cheque": "Once the State holds it, the only way it pays is a cheque in the post.",
    "sources": [
        {"label": "1532(b): general reporting information", "url": _SCO + "Files-UPD/outreach_rptg_hol_genrptinfo.pdf"},
        {"label": "1560(b): holder reimbursement guide", "url": _SCO + "Files-UPD/QuickGuide_HolderReimburseRequest_2017.pdf"},
        {"label": "1532(a): how to report", "url": _SCO + "upd_how_to_report.html"},
        {"label": "Payment by cheque", "url": _SCO + "upd_faq_payment.html"},
    ],
}

HOW = [
    "The holder sets its standing instructions once: how far the amount may move, who bears the fees on a small "
    "claim, how the route is chosen, and a deadline.",
    "An owner abroad finds the record and proves it is theirs. Khutlisa reads the documents and shows the holder "
    "what was read and what could not be checked. Khutlisa has not verified them with the issuing authority.",
    "The holder, not Khutlisa, approves. The approval covers one amount, one person, one bank account, the "
    "documents as they stand and the instructions as they stand.",
    "The money goes out through Airwallex into the owner's own bank account in local currency. Inside the "
    "instructions the agent acts alone and reports what it did. Outside them it stops and asks.",
    "If the holder does not pay, nothing is lost: the property goes to the State as the law requires, and the "
    "owner can still claim it there and be paid by cheque.",
]


def served() -> dict | None:
    """Everything the "For holders" screen shows, or None when the figures have not been made yet."""
    import json

    if not FILE.exists():
        return None
    from . import handover

    june = handover.clean({})
    short = {**IN_SHORT, "days_to_handover": handover.days_left(june), "handover_words": handover.in_words(june["handover_date"])}
    return {"figures": json.loads(FILE.read_text()), "rule": RULE, "in_short": short, "status": STATUS, "law": LAW,
            "buyer": BUYER,
            "how_it_would_work": HOW, "proposed_pricing": PROPOSED_PRICING,
            "law_notes": "docs/CALIFORNIA_CLAIMS.md gives every source, what was read and what was not verified."}
