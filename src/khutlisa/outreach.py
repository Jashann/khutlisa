"""The holder's outreach: its own list of balances, the notices prepared from it, and what the agent decides.

Files, under one folder (data/claims/outreach in a normal run):

  settings.json            the holder's details for the letter and its standing instructions for outreach
  mappings.json            column mappings the holder has confirmed, by the titles of the export they fit
  lists/<id>.json          one uploaded file: its titles, the proposal, the confirmed mapping, the balances
  lists/<id>.rows.json     the rows of that file as text, kept so the mapping can be corrected
  notices/<id>.json        the notices prepared from that list
  translations.json        translations of the notice made on this server (notices.Translations)

Everything the agent decides here is arithmetic on dates and amounts inside the holder's standing
instructions, shown as the same four-line decision cards the payment uses (cards.py). No language model is
involved in any decision. Nothing is sent: a notice is prepared, and its delivery is recorded only when the
holder marks it sent.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb

from . import dormancy, handover, holder_list, notices
from .cards import _money
from .demo import SOURCE as DEMO_SOURCE
from .names import normalise, phonetic

HOLDER_SOURCE = "HOLDER"      # the source of a record from a real holder's own list
RULE_DEFAULTS = {"notice_minimum_usd": "50.00", "reminder_after_days": 30, "reminders_most": 1, "hold_answered": True}
HOLDER_FIELDS = ("name", "street", "city", "region", "postcode", "country", "contact", "email", "phone")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_rules(raw: dict | None) -> dict:
    """The outreach instructions in stored form. Raises ValueError in words for the screen."""
    raw = {**RULE_DEFAULTS, **{k: v for k, v in (raw or {}).items() if v not in (None, "")}}
    try:
        minimum = Decimal(str(raw["notice_minimum_usd"]).strip())
    except Exception:
        raise ValueError("The smallest balance to notify must be a number") from None
    if not Decimal(0) <= minimum <= dormancy.NOTICE_MINIMUM_USD:
        raise ValueError("The smallest balance to notify must be between 0 and 50 US dollars. The law requires "
                         "a notice from 50 dollars up, so the line cannot be higher")
    try:
        after, most = int(raw["reminder_after_days"]), int(raw["reminders_most"])
    except (TypeError, ValueError):
        raise ValueError("The reminder settings must be whole numbers") from None
    if not 7 <= after <= 180:
        raise ValueError("A reminder can follow after 7 to 180 days")
    if not 0 <= most <= 3:
        raise ValueError("The number of reminders must be between 0 and 3")
    return {"notice_minimum_usd": f"{minimum:.2f}", "reminder_after_days": after, "reminders_most": most,
            "hold_answered": bool(raw["hold_answered"]) and str(raw["hold_answered"]).lower() not in ("false", "0", "no")}


def rules_in_words(rules: dict) -> list[str]:
    most = rules["reminders_most"]
    return [
        f"Notify every owner abroad who is owed {_money(rules['notice_minimum_usd'])} or more and has an address on "
        "file. The law requires it from 50 US dollars.",
        "Order: the soonest handover date first, and the largest amount first within a date.",
        (f"Reminders: {most} at most, {rules['reminder_after_days']} days after a notice with no answer."
         if most else "Reminders: none."),
        ("At the handover date: pay what is proven, hold a balance whose owner has answered while the proof is "
         "completed, and release the rest to the State." if rules["hold_answered"] else
         "At the handover date: pay what is proven and release everything else to the State."),
        "Never inside these instructions: sending anything. Notices are prepared here and sent by the holder.",
    ]


def clean_holder(raw: dict | None) -> dict:
    out = {k: " ".join(str((raw or {}).get(k) or "").split())[:160] for k in HOLDER_FIELDS}
    if not out["name"]:
        raise ValueError("Give the holder's name, as it should stand on the letter")
    if not (out["phone"] or out["email"]):
        raise ValueError("Give a telephone number or an email address owners can use. The notice must carry one")
    return out


class ListRecords:
    """The balances of every confirmed list as a `records` table in the shape of the register, in memory, so a
    claim opened from a notice is compared with its record exactly as any other claim is (claims_api). These
    records are looked up by their own number only; the open search never runs over them."""

    COLUMNS = ["source", "record_id", "owner_name", "owner_norm", "owner_street", "owner_city", "owner_region",
               "owner_postcode", "owner_country", "amount", "currency", "holder_name", "holder_city", "holder_region",
               "property_type", "phon_first", "phon_last"]

    def __init__(self) -> None:
        self._con: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()
        self._rows: dict[str, list[list]] = {}

    def set_list(self, list_id: str, rows: list[list]) -> None:
        with self._lock:
            self._rows[list_id] = rows
            if self._con is not None:
                self._con.close()
                self._con = None

    def _build(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:")
        con.execute(f"create table records ({', '.join(c + (' double' if c == 'amount' else ' varchar') for c in self.COLUMNS)})")
        rows = [r for rows in self._rows.values() for r in rows]
        if rows:
            con.executemany(f"insert into records values ({','.join('?' * len(self.COLUMNS))})", rows)
        return con

    def cursor(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is None:
                self._con = self._build()
            return self._con.cursor()

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None


def record_id(list_id: str, row: int) -> str:
    return f"HL-{list_id}-{row}"


def record_row(list_meta: dict, balance: dict, holder_name: str) -> list:
    """One balance in the register's shape. The source says whether it is a demonstration record."""
    norm = normalise(balance["name"])
    words = norm.split() or [""]
    kind = balance.get("property_words") or dormancy.PERIODS[balance["property_class"]]["label"]
    return [DEMO_SOURCE if list_meta.get("invented") else HOLDER_SOURCE, record_id(list_meta["id"], balance["row"]),
            balance["name"], norm, balance.get("street") or "", balance.get("city") or "", balance.get("region") or "",
            balance.get("postcode") or "", balance.get("country") or "", float(balance["amount"]), "USD",
            holder_name, "", "", kind, phonetic(words[0]), phonetic(words[-1])]


class OutreachStore:
    """Reads and writes the outreach files. One lock guards every change."""

    def __init__(self, folder: Path | str):
        self.folder = Path(folder)
        self.lock = threading.RLock()
        self.records = ListRecords()
        self._loaded = False

    # ---- files ---------------------------------------------------------------------------------------------------

    def _read(self, name: str, default):
        try:
            return json.loads((self.folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, name: str, value) -> None:
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    # ---- the holder's details and instructions --------------------------------------------------------------------------

    def settings(self) -> dict:
        held = self._read("settings.json", {})
        rules = held.get("rules")
        return {"holder": held.get("holder"), "rules": rules or clean_rules({}), "rules_set": bool(rules),
                "set_at": held.get("set_at"), "in_words": rules_in_words(rules or clean_rules({})),
                "defaults": clean_rules({})}

    def set_settings(self, holder: dict | None = None, rules: dict | None = None) -> dict:
        with self.lock:
            held = self._read("settings.json", {})
            if holder is not None:
                held["holder"] = clean_holder(holder)
            if rules is not None:
                held["rules"] = clean_rules(rules)
            held["set_at"] = now()
            self._write("settings.json", held)
        self.load_records()
        return self.settings()

    # ---- lists ----------------------------------------------------------------------------------------------------

    def lists(self) -> list[dict]:
        folder = self.folder / "lists"
        out = []
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            if not path.name.endswith(".rows.json"):
                try:
                    out.append(json.loads(path.read_text(encoding="utf-8")))
                except ValueError:
                    continue
        return sorted(out, key=lambda m: (m.get("opened") or 0, m.get("uploaded_at", "")))

    def list(self, list_id: str) -> dict | None:
        if not list_id or not list_id.isalnum():
            return None
        return self._read(f"lists/{list_id}.json", None)

    def current(self) -> dict | None:
        """The list the holder is working on: the one uploaded last."""
        every = self.lists()
        return every[-1] if every else None

    def rows(self, list_id: str) -> dict:
        return self._read(f"lists/{list_id}.rows.json", {"rows": [], "row_numbers": []})

    def add_upload(self, table, filename: str, proposal: dict) -> dict:
        with self.lock:
            meta = {"id": secrets.token_hex(6), "filename": filename[:120], "uploaded_at": now(),
                    "opened": time.time_ns(),       # a clock reading fine enough to tell two uploads apart
                    "kind": table.kind,
                    "invented": bool(table.invented), "header": table.header, "header_row": table.header_row,
                    "rows_read": len(table.rows), "file_notes": table.notes, "proposal": proposal,
                    "signature": holder_list.signature(table.header), "state": "uploaded", "mapping": None,
                    "defaults": proposal.get("defaults") or {}, "balances": [], "failed": [], "notes": []}
            self._write(f"lists/{meta['id']}.rows.json", {"rows": table.rows, "row_numbers": table.row_numbers})
            self._write(f"lists/{meta['id']}.json", meta)
            return meta

    def confirm(self, list_id: str, mapping: dict, defaults: dict | None, today: date) -> dict:
        """The holder confirms the mapping: every row is validated in code, the result is kept, and the mapping
        is remembered for the next export with the same column titles."""
        with self.lock:
            meta = self.list(list_id)
            if meta is None:
                raise KeyError(list_id)
            mapping = holder_list.clean_mapping(mapping, meta["header"])
            defaults = {k: v for k, v in (defaults or {}).items() if k in ("property_class", "country") and v}
            if defaults.get("property_class") and defaults["property_class"] not in dormancy.PERIODS:
                raise ValueError("Choose one of the kinds of property")
            held = self.rows(list_id)
            result = holder_list.validate(meta["header"], held["rows"], held["row_numbers"], mapping, defaults, today)
            changed = bool(meta.get("mapping")) and (meta["mapping"] != mapping or meta.get("defaults") != defaults)
            meta.update({"state": "confirmed", "mapping": mapping, "defaults": defaults, "confirmed_at": now(),
                         "balances": result["balances"], "failed": result["failed"], "notes": result["notes"],
                         "date_order": result["date_order"]})
            self._write(f"lists/{list_id}.json", meta)
            remembered = self._read("mappings.json", {})
            remembered[meta["signature"]] = {"mapping": mapping, "defaults": defaults, "confirmed_at": meta["confirmed_at"],
                                             "titles": meta["header"]}
            self._write("mappings.json", remembered)
            if changed and not any(n.get("sent") or n.get("claim_id") for n in self.notices(list_id)):
                self.save_notices(list_id, [])      # notices prepared from the old reading no longer stand
        self.load_records()
        return meta

    def remembered(self, header: list[str]) -> dict | None:
        return self._read("mappings.json", {}).get(holder_list.signature(header))

    def load_records(self) -> None:
        """Puts every confirmed list's balances into the records table claims are compared with."""
        holder = (self.settings()["holder"] or {}).get("name") or "The holder"
        for meta in self.lists():
            if meta.get("state") == "confirmed":
                self.records.set_list(meta["id"], [record_row(meta, b, holder) for b in meta["balances"]])
        self._loaded = True

    def cursor(self) -> duckdb.DuckDBPyConnection:
        if not self._loaded:
            self.load_records()
        return self.records.cursor()

    # ---- notices --------------------------------------------------------------------------------------------------

    def notices(self, list_id: str) -> list[dict]:
        return self._read(f"notices/{list_id}.json", [])

    def save_notices(self, list_id: str, items: list[dict]) -> None:
        with self.lock:
            self._write(f"notices/{list_id}.json", items)
            index = {code: ref for code, ref in self._read("codes.json", {}).items() if ref[0] != list_id}
            index.update({n["code"]: [list_id, n["id"]] for n in items})
            self._write("codes.json", index)

    def by_code(self, code: str) -> tuple[dict, dict] | None:
        """(the list, the notice) for a code on a letter, or None."""
        ref = self._read("codes.json", {}).get(notices.clean_code(code))
        if not ref:
            return None
        meta = self.list(ref[0])
        notice = next((n for n in self.notices(ref[0]) if n["id"] == ref[1]), None)
        return (meta, notice) if meta and notice else None

    def change_notice(self, list_id: str, notice_id: str, change) -> dict | None:
        with self.lock:
            items = self.notices(list_id)
            for n in items:
                if n["id"] == notice_id:
                    change(n)
                    self.save_notices(list_id, items)
                    return n
        return None

    def close(self) -> None:
        self.records.close()


# ---- what the agent decides ------------------------------------------------------------------------------------------

def _total(rows: list[dict]) -> Decimal:
    return sum((Decimal(r["amount"]) for r in rows), Decimal(0))


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else many or one + 's'}"


def timing_basis(place: dict) -> dict:
    """Why a notice may go out today, for one balance."""
    if place["status"] == "notice" and place["window"] == "open":
        return {"kind": "in_window",
                "text": f"Inside the window the law sets: 6 to 12 months before the Notice Report due before "
                        f"{handover.in_words(place['notice_report'])}."}
    if place["status"] == "notice":
        return {"kind": "window_closed",
                "text": f"The window closed on {handover.in_words(place['window_closes'])}. The Controller asks for "
                        "the notice as soon as possible, and for the report on time."}
    return {"kind": "late",
            "text": "The window for this balance has passed. The Controller asks for the notice as soon as "
                    "possible. Section 1520(c) also allows a further notice at any time before the transfer."}


def choose_owners(queue: list[dict], rules: dict, already: set[int]) -> dict:
    """Which owners abroad get a notice now, in order: the soonest handover first, the largest amount first
    within a date. `queue` is the dormancy picture's queue; `already` holds the rows that have a notice."""
    minimum = Decimal(rules["notice_minimum_usd"])
    chosen, under, not_yet, have = [], [], [], []
    for b in queue:
        if b["row"] in already:
            have.append(b)
        elif Decimal(b["amount"]) < minimum:
            under.append(b)
        elif b["place"]["status"] == "later":
            not_yet.append(b)
        else:
            chosen.append(b)
    return {"chosen": chosen, "under_minimum": under, "not_yet": not_yet, "already": have}


def notify_card(picture: dict, chosen: dict, rules: dict, prepared: list[dict] | None = None) -> dict:
    """The decision "which owners to notify first", with its numbers."""
    queue = picture["queue"]
    soon = picture["abroad_due_soon"]
    covered = _total(chosen["chosen"] if prepared is None else prepared) + _total(chosen["already"])
    waiting = _total(chosen["under_minimum"]) + _total(chosen["not_yet"])
    n = len(chosen["chosen"])
    happened = (f"{_count(len(queue), 'owner')} abroad are owed {_money(picture['abroad']['amount'])}."
                + (f" {_money(soon['amount'])} goes to the State in {soon['days']} days." if soon["balances"] else ""))
    if prepared is not None:
        did = f"Prepared {_count(len(prepared), 'notice')}: soonest handover first, then largest amount."
    elif n:
        did = f"{_count(n, 'notice')} to prepare: soonest handover first, then largest amount."
    else:
        did = "Every owner who can be notified today has a notice."
    why = ["The order is fixed: balances that reach their handover date first come first, and within one date the "
           "largest amount comes first, so the most dollars at risk soonest are dealt with first.",
           f"{_count(len(chosen['under_minimum']), 'balance')} abroad, {_money(_total(chosen['under_minimum']))}, "
           f"{'is' if len(chosen['under_minimum']) == 1 else 'are'} under {_money(rules['notice_minimum_usd'])}. "
           "The law does not require a notice below 50 US dollars (Code of Civil Procedure 1520(b)).",
           f"{_count(len(chosen['not_yet']), 'balance')} abroad, {_money(_total(chosen['not_yet']))}, "
           f"{'reaches its' if len(chosen['not_yet']) == 1 else 'reach their'} dormancy period later. Their notice "
           "window has not opened."]
    kinds: dict[str, int] = {}
    for b in chosen["chosen"]:
        kinds[timing_basis(b["place"])["kind"]] = kinds.get(timing_basis(b["place"])["kind"], 0) + 1
    if kinds.get("in_window"):
        why.append(f"{_count(kinds['in_window'], 'notice')} fall inside the window the law sets, 6 to 12 months "
                   "before the next Notice Report.")
    if kinds.get("late") or kinds.get("window_closed"):
        late = kinds.get("late", 0) + kinds.get("window_closed", 0)
        why.append(f"{_count(late, 'notice')} {'is' if late == 1 else 'are'} for balances whose window has passed. "
                   "The Controller's guide says to send such a notice as soon as possible.")
    return {"kind": "notify_first", "tone": "go", "title": "Who is notified first",
            "happened": happened,
            "allowed": f"Notify owners of {_money(rules['notice_minimum_usd'])} or more, soonest handover first.",
            "did": did,
            "money": f"{_money(covered)} is covered by a notice. {_money(waiting)} waits or is under the line.",
            "why": why, "counts": {"to_prepare": n, "under_minimum": len(chosen["under_minimum"]),
                                   "not_yet": len(chosen["not_yet"]), "already": len(chosen["already"])}}


def last_sent(notice: dict) -> str | None:
    sent = notice.get("sent") or []
    return sent[-1]["on"] if sent else None


def reminders_due(items: list[dict], rules: dict, today: date) -> list[dict]:
    """Notices that were marked sent, have no answer, and are due a reminder under the instructions."""
    due = []
    for n in items:
        if n.get("claim_id") or not n.get("sent") or n["state"] != "ready":
            continue
        reminders = [s for s in n["sent"] if s.get("reminder")]
        if len(reminders) >= rules["reminders_most"]:
            continue
        waited = (today - date.fromisoformat(last_sent(n))).days
        if waited >= rules["reminder_after_days"] and date.fromisoformat(n["handover"]) > today:
            due.append(n)
    return sorted(due, key=lambda n: (n["handover"], -Decimal(n["amount"])))


def reminder_card(items: list[dict], rules: dict, today: date) -> dict | None:
    """The decision "when to send a reminder". None until a notice has been marked sent."""
    sent = [n for n in items if n.get("sent")]
    if not sent:
        return None
    unanswered = [n for n in sent if not n.get("claim_id")]
    due = reminders_due(items, rules, today)
    days = rules["reminder_after_days"]
    if not rules["reminders_most"]:
        did, tone = "No reminders: the instructions allow none.", "ask"
    elif due:
        did, tone = f"{_count(len(due), 'reminder')} due now, soonest handover first.", "ask"
    else:
        waiting = [n for n in unanswered if len([s for s in n["sent"] if s.get("reminder")]) < rules["reminders_most"]]
        if waiting:
            first = min(date.fromisoformat(last_sent(n)) for n in waiting)
            when = date.fromordinal(first.toordinal() + days)
            did = f"No reminder is due yet. The first falls due on {handover.in_words(when.isoformat())}."
        else:
            did = "No reminder is due: every notice is answered or has had its reminders."
        tone = "go"
    return {"kind": "reminder", "tone": tone, "title": "Reminders",
            "happened": f"{_count(len(sent), 'notice')} marked sent. {_count(len(unanswered), 'has', 'have')} no answer yet.",
            "allowed": (f"{_count(rules['reminders_most'], 'reminder')} at most, {days} days after a notice with no answer."
                        if rules["reminders_most"] else "No reminders."),
            "did": did,
            "money": f"{_money(_total(unanswered))} is still unanswered.",
            "why": ["A reminder is the same notice with a line that says it is a reminder. Section 1520(c) allows "
                    "further notices at any time before the property is transferred.",
                    "A reminder is prepared here and sent by the holder, like the notice itself."],
            "due": [n["id"] for n in due]}


def at_the_deadline(balances: list[dict], items: list[dict], stage_of, rules: dict, setting: dict,
                    today: date) -> dict:
    """What happens at the handover date to each balance abroad that is due on it: pay, hold for proof, or
    release to the State. `balances` are the queue rows due with the next handover; `stage_of(notice)` gives
    the furthest stage the owner's claim has reached ("responded", "proven", "paid") or None."""
    by_row = {n["row"]: n for n in items}
    groups: dict[str, list[dict]] = {"paid": [], "pay": [], "hold": [], "release": []}
    for b in balances:
        notice = by_row.get(b["row"])
        stage = stage_of(notice) if notice and notice.get("claim_id") else None
        if stage == "paid":
            groups["paid"].append(b)
        elif stage == "proven":
            groups["pay"].append(b)
        elif stage == "responded" and rules["hold_answered"]:
            groups["hold"].append(b)
        else:
            groups["release"].append(b)
    left = handover.days_left(setting, today)
    when = handover.in_words(setting["handover_date"])
    final = left <= int(setting["document_days"])
    happened = (f"{left} days to the handover on {when}. {_count(len(balances), 'balance')} abroad, "
                f"{_money(_total(balances))}, {'is' if len(balances) == 1 else 'are'} due." if left >= 0 else
                f"The handover date, {when}, has passed. {_count(len(balances), 'balance')} abroad "
                f"{'was' if len(balances) == 1 else 'were'} due.")
    allowed = ("Pay what is proven. Hold what an owner has answered. Release the rest." if rules["hold_answered"]
               else "Pay what is proven. Release the rest.")
    lead = "At the date" if final else "As things stand"
    done = f"{len(groups['paid']):,} already paid, " if groups["paid"] else ""
    did = (f"{lead}: {done}pay {len(groups['pay']):,}, hold {len(groups['hold']):,} for proof, release "
           f"{len(groups['release']):,} to the State.")
    money = (f"{_money(_total(groups['pay']) + _total(groups['paid']))} to owners, {_money(_total(groups['hold']))} "
             f"held, {_money(_total(groups['release']))} on the Remit Report.")
    why = [
        "Pay: the owner answered the notice and the proof is ready. A holder that is satisfied of the owner's "
        "right before delivery does not deliver the property to the Controller (Code of Civil Procedure 1532(b)).",
        ("Hold: the owner answered and the proof is not complete. Contact in answer to the notice, on record with "
         "the holder, means the property is deemed active and its period starts again (1520(b)); the Controller's "
         "guide adds that this depends on the kind of property. Holding on that basis is our reading."
         if rules["hold_answered"] else
         "The instructions do not hold a balance for an owner who has answered without proof; it is released."),
        "Release: nobody answered. The balance goes on the Remit Report, and the owner can still claim it from "
        "the State, which pays by a cheque in the post.",
        f"The date is the holder's own handover date, {when}. An owner needs about {setting['document_days']} days "
        "to send a document; inside that many days the choice is final.",
    ]
    if groups["paid"]:
        why.append(f"{_count(len(groups['paid']), 'balance')}, {_money(_total(groups['paid']))}, "
                   f"{'has' if len(groups['paid']) == 1 else 'have'} already been paid to the owner.")
    return {"kind": "deadline_outreach", "tone": "stop" if final and groups["release"] else "ask" if groups["release"] else "go",
            "title": "At the handover date", "happened": happened, "allowed": allowed, "did": did, "money": money,
            "why": why, "final": final, "days_left": left, "date": setting["handover_date"], "date_words": when,
            "groups": {k: {"balances": len(v), "amount": f"{_total(v):.2f}"} for k, v in groups.items()},
            "rows": {k: [b["row"] for b in v] for k, v in groups.items()}}


STAGES = ("prepared", "sent", "opened", "responded", "proven", "paid")
STAGE_WORDS = {"prepared": "Prepared", "sent": "Marked sent", "opened": "Opened", "responded": "Answered",
               "proven": "Proven", "paid": "Paid"}


def funnel(items: list[dict], stage_of, setting: dict, today: date) -> dict:
    """How far the notices have got: prepared, marked sent, opened, answered, proven, paid. Each stage counts
    the notices that reached it, with their dollars."""
    ready = [n for n in items if n["state"] == "ready"]
    reached: dict[str, list[dict]] = {s: [] for s in STAGES}
    for n in ready:
        reached["prepared"].append(n)
        if n.get("sent"):
            reached["sent"].append(n)
        if n.get("opened_at"):
            reached["opened"].append(n)
        stage = stage_of(n) if n.get("claim_id") else None
        if stage:
            reached["responded"].append(n)
        if stage in ("proven", "paid"):
            reached["proven"].append(n)
        if stage == "paid":
            reached["paid"].append(n)
    return {"stages": [{"key": s, "words": STAGE_WORDS[s], "notices": len(reached[s]),
                        "amount": f"{_total(reached[s]):.2f}"} for s in STAGES],
            "held": len(items) - len(ready),
            "days_left": handover.days_left(setting, today), "handover_date": setting["handover_date"],
            "date_words": handover.in_words(setting["handover_date"])}
