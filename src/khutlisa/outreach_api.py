"""The routes for the holder's own list, the notices and the owner's answer. `register` adds them to the app.

The holder's routes take the same shared key as the rest of the holder's view (X-Payer-Key). Two routes are
open, and are counted per client address: reading a notice by the code on the letter, and answering it. An
answer opens a claim on that exact record, through the same claim store the search uses, so everything after
it (documents, proof, bank account, the holder's approval, the payment) is the existing journey.

Privacy: the holder sees its own file. The open routes never return the owner's name or street: the notice on
screen is opened with a code alone, and the record a claim keeps is the public form (server.public_record).

Nothing here sends a letter or an email. A notice is prepared, and the holder marks it sent.
"""
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import claims as cl
from . import dormancy, handover, holder_file, holder_list, invented_holder, notices, outreach
from .cards import _money
from .claims_api import PAYER_KEY_HEADER, ClaimantIn
from .countries import COUNTRIES
from .ratelimit import HOUR, MINUTE, SlidingWindow

NOT_SENT = ("Nothing is sent from here. Khutlisa prepares each notice; you send it, by post or by email, and mark "
            "it sent. Delivery is recorded only then.")
DEMO_ONLY_UPLOAD = ("This is a public demonstration, so only the invented holder file can be loaded here. Use "
                    "the invented file, or run Khutlisa yourself to load your own list.")
PAGE = 50


class MappingIn(BaseModel):
    mapping: dict[str, str | None]
    defaults: dict[str, str | None] = Field(default_factory=dict)


class SettingsIn(BaseModel):
    holder: dict[str, str] | None = None
    rules: dict[str, str | int | float | bool] | None = None


class PrepareIn(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100000)
    reminders: bool = False


class SentIn(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=100000)
    all_unsent: bool = False
    channel: str = Field(default="post", pattern="^(post|email)$")
    on: str | None = Field(default=None, max_length=10)
    reminder: bool = False


def register(app: FastAPI, claim_store: cl.ClaimStore, history_model, *, payer_key: str = "", public_url: str = "",
             use_model: bool = True, demo_only: bool = False, clock=None, today=None,
             store: "outreach.OutreachStore | None" = None) -> "outreach.OutreachStore":
    """`demo_only` is the public demonstration: only the invented file can be loaded. `today` returns the date
    the calendar is counted from, and exists so a test can stand on a fixed day."""
    held = store or outreach.OutreachStore(claim_store.folder / "outreach")
    today = today or handover.today
    translations = notices.Translations(held.folder, use_model=use_model)
    window = SlidingWindow([(30, MINUTE), (200, HOUR)], **({"clock": clock} if clock else {}))     # per client address
    app.state.outreach = held

    def holder_only(key: str | None = Header(default=None, alias=PAYER_KEY_HEADER)) -> None:
        if not payer_key:
            raise HTTPException(401, "The holder's view is locked: no key for it is set on this server. Set "
                                     "KHUTLISA_PAYER_KEY and start it again.")
        if not key or not hmac.compare_digest(key.encode(), payer_key.encode()):
            raise HTTPException(401, "The holder's key is missing or wrong.")

    def counted(request: Request) -> None:
        who = request.client.host if request.client else "unknown"
        wait = window.take(who)
        if wait:
            raise HTTPException(429, f"Too many requests have come from this address. Try again in {wait} "
                                     f"{'second' if wait == 1 else 'seconds'}.", headers={"Retry-After": str(wait)})

    def setting() -> dict:
        """The holder's handover date, kept by the holder's view (claims_api): the next 1 June until set."""
        try:
            return handover.clean(json.loads((claim_store.folder / "holder_handover.json").read_text()))
        except (OSError, ValueError):
            return handover.clean({})

    def base_url(request: Request | None = None) -> str:
        return (public_url or (str(request.base_url) if request is not None else "http://localhost:8000")).rstrip("/")

    def holder_details(meta: dict | None = None) -> dict | None:
        details = held.settings()["holder"]
        if details is None and meta is not None and meta.get("invented"):
            details = outreach.clean_holder(invented_holder.HOLDER)     # the invented file names its own holder
        return details

    def need_list(list_id: str | None = None, confirmed: bool = True) -> dict:
        meta = held.list(list_id) if list_id else held.current()
        if meta is None:
            raise HTTPException(404, "No list has been uploaded yet.")
        if confirmed and meta["state"] != "confirmed":
            raise HTTPException(409, "Confirm which column is which first.")
        return meta

    def picture_of(meta: dict) -> dict:
        return dormancy.picture(meta["balances"], today(), date.fromisoformat(setting()["handover_date"]))

    def stage_of(notice: dict | None) -> str | None:
        """How far the claim opened from a notice has got: "responded", "proven" or "paid"."""
        if not notice or not notice.get("claim_id"):
            return None
        try:
            claim = claim_store.load(notice["claim_id"])
        except cl.ClaimError:
            return "responded"
        if claim["state"] == cl.PAID:
            return "paid"
        ready = getattr(app.state, "proof_ready", None)
        proven = claim["state"] in (cl.PROOF_READY, cl.PACKET_READY, cl.FILED, cl.APPROVED, cl.PAYING, cl.PAYMENT_HELD)
        if not proven and getattr(app.state, "read_documents", False) and ready is not None:
            try:
                proven = bool(ready(claim))
            except Exception:
                proven = False
        return "proven" if proven else "responded"

    # ---- views ---------------------------------------------------------------------------------------------------

    def queue_row(b: dict, notice: dict | None = None) -> dict:
        p = b["place"]
        return {"row": b["row"], "name": b["name"], "city": b["city"], "country": b["country"],
                "country_name": COUNTRIES.get(b["country"], {}).get("name", b["country"]),
                "amount": b["amount"], "kind": dormancy.PERIODS[b["property_class"]]["label"],
                "years": p["years"], "last_activity": b["last_activity"], "status": p["status"],
                "status_words": dormancy.STATUS_WORDS[p["status"]], "handover": p["handover"],
                "handover_words": handover.in_words(p["handover"]), "days_to_state": p["days_to_state"],
                "notice_required": p["notice_required"], "window": p["window"],
                "has_email": bool(b.get("email")), "has_phone": bool(b.get("phone")),
                "notice": notice and {"id": notice["id"], "state": notice["state"], "sent": bool(notice.get("sent"))}}

    def notice_row(n: dict) -> dict:
        stage = stage_of(n)
        at = ("paid" if stage == "paid" else "proven" if stage == "proven" else "responded" if stage else
              "opened" if n.get("opened_at") else "sent" if n.get("sent") else "prepared")
        return {"id": n["id"], "row": n["row"], "name": n["name"], "country": n["country"],
                "country_name": COUNTRIES.get(n["country"], {}).get("name", n["country"]), "amount": n["amount"],
                "handover": n["handover"], "handover_words": handover.in_words(n["handover"]),
                "days_to_state": (date.fromisoformat(n["handover"]) - today()).days,
                "language": n["language"], "state": n["state"], "problems": n["problems"], "warnings": n["warnings"],
                "delivery": n["delivery"], "timing": n["timing"], "stage": at if n["state"] == "ready" else "held",
                "stage_words": outreach.STAGE_WORDS.get(at, "Held") if n["state"] == "ready" else "Held back",
                "sent": n.get("sent") or [], "opened_at": n.get("opened_at"), "responded_at": n.get("responded_at"),
                "claim_id": n.get("claim_id"), "code": n["code"],
                "reminders_sent": len([s for s in n.get("sent") or [] if s.get("reminder")])}

    def list_view(meta: dict) -> dict:
        view = {k: meta.get(k) for k in ("id", "filename", "uploaded_at", "kind", "invented", "header", "header_row",
                                         "rows_read", "file_notes", "proposal", "state", "mapping", "defaults",
                                         "notes", "confirmed_at")}
        view["fields"] = [{"key": k, "label": holder_list.LABELS[k], "about": text} for k, text in holder_list.FIELDS.items()]
        view["kinds"] = [{"key": k, "label": p["label"], "years": p["years"]} for k, p in dormancy.PERIODS.items()]
        rows = held.rows(meta["id"])["rows"][:5]
        view["first_rows"] = rows                      # the holder's own file, shown back to the holder
        view["valid"], view["failed"] = len(meta["balances"]), len(meta["failed"])
        view["failures"] = holder_list.failure_summary(meta["failed"])
        return view

    def whole(request: Request | None = None) -> dict:
        """Everything the holder's list screen shows, in one answer."""
        meta = held.current()
        settings = held.settings()
        out = {"list": None, "picture": None, "queue": [], "notices": None, "settings": settings,
               "holder": holder_details(meta), "handover": {**setting(), "days_left": handover.days_left(setting(), today()),
                                                            "date_words": handover.in_words(setting()["handover_date"])},
               "sends_nothing": NOT_SENT, "demo_only": demo_only, "public_url": base_url(request),
               "invented_file": {"name": invented_holder.file_name(), "url": "/api/holder/list/invented.csv"},
               "law": LAW}
        if meta is None:
            return out
        out["list"] = list_view(meta)
        if meta["state"] != "confirmed":
            return out
        picture = picture_of(meta)
        items = held.notices(meta["id"])
        by_row = {n["row"]: n for n in items}
        queue = picture.pop("queue")
        out["picture"] = picture
        out["queue"] = [queue_row(b, by_row.get(b["row"])) for b in queue[:PAGE]]
        out["queue_total"] = len(queue)
        chosen = outreach.choose_owners(queue, settings["rules"], set(by_row))
        due_on = {b["row"]: b["place"]["handover"] for b in queue}
        stale = [n for n in items if not n.get("sent") and not n.get("claim_id")
                 and due_on.get(n["row"], n["handover"]) != n["handover"]]
        due_rows = [b for b in queue if b["place"]["status"] in ("late", "remit")]
        cards = [outreach.notify_card({**picture, "queue": queue}, chosen, settings["rules"])]
        reminder = outreach.reminder_card(items, settings["rules"], today())
        if reminder:
            cards.append(reminder)
        cards.append(outreach.at_the_deadline(due_rows, items, stage_of, settings["rules"], setting(), today()))
        languages: dict[str, int] = {}
        for n in items:
            name = n["language"]["name"] if n["language"]["translated"] else "English only"
            languages[name] = languages.get(name, 0) + 1
        out["notices"] = {
            "count": len(items), "ready": len([n for n in items if n["state"] == "ready"]),
            "held": len([n for n in items if n["state"] != "ready"]), "stale": len(stale),
            "to_prepare": len(chosen["chosen"]),
            "unsent": len([n for n in items if n["state"] == "ready" and not n.get("sent")]),
            "languages": sorted(({"language": k, "notices": v} for k, v in languages.items()), key=lambda x: -x["notices"]),
            "funnel": outreach.funnel(items, stage_of, setting(), today()),
            "cards": cards,
            "rows": [notice_row(n) for n in sorted(items, key=lambda n: (-(bool(n.get("claim_id")) * 3 + bool(n.get("opened_at")) * 2
                                                                         + bool(n.get("sent"))), n["rank"]))[:PAGE]],
            "elements": notices.ELEMENTS,
        }
        return out

    # ---- the list ------------------------------------------------------------------------------------------------

    @app.get("/api/holder/outreach", dependencies=[Depends(holder_only)])
    def outreach_view(request: Request) -> dict:
        return whole(request)

    def take(data: bytes, filename: str, request: Request) -> dict:
        try:
            table = holder_file.read(data, filename)
        except holder_file.FileProblem as err:
            raise HTTPException(422, str(err)) from None
        if demo_only and not table.invented:
            raise HTTPException(403, DEMO_ONLY_UPLOAD)
        proposal = holder_list.propose(table.header, table.rows, held.remembered(table.header), use_model=use_model)
        held.add_upload(table, filename, proposal)
        return whole(request)

    @app.post("/api/holder/list", dependencies=[Depends(holder_only)])
    async def upload_list(request: Request, file: UploadFile = File(...)) -> dict:
        """The holder's own file. Its bytes stay on this server; a language model, when one is asked, sees the
        column titles and at most 20 rows with names, addresses, contact details and references masked."""
        data = await file.read(holder_file.MAX_BYTES + 1)
        if demo_only and hashlib.sha256(data).hexdigest() not in invented_hashes():
            raise HTTPException(403, DEMO_ONLY_UPLOAD)
        return take(data, file.filename or "list", request)

    _hashes: set[str] = set()

    def invented_hashes() -> set[str]:
        if not _hashes:
            table = invented_holder.rows()
            _hashes.update(hashlib.sha256(d).hexdigest() for d in (invented_holder.as_csv(table), invented_holder.as_excel(table)))
        return _hashes

    @app.get("/api/holder/list/invented.csv")
    def invented_file() -> Response:
        """The invented holder file, for anyone to look at or upload. No real person is in it."""
        return Response(invented_holder.as_csv(invented_holder.rows()), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{invented_holder.file_name()}"'})

    @app.post("/api/holder/list/invented", dependencies=[Depends(holder_only)])
    def load_invented(request: Request) -> dict:
        """Loads the invented holder file as if it had been uploaded."""
        return take(invented_holder.as_csv(invented_holder.rows()), invented_holder.file_name(), request)

    @app.put("/api/holder/list/{list_id}/mapping", dependencies=[Depends(holder_only)])
    def confirm_mapping(list_id: str, body: MappingIn, request: Request) -> dict:
        need_list(list_id, confirmed=False)
        try:
            held.confirm(list_id, body.mapping, body.defaults, today())
        except ValueError as err:
            raise HTTPException(422, str(err) + ".") from None
        return whole(request)

    @app.get("/api/holder/list/{list_id}/failed", dependencies=[Depends(holder_only)])
    def failed_rows(list_id: str, offset: int = Query(0, ge=0)) -> dict:
        meta = need_list(list_id)
        return {"total": len(meta["failed"]), "rows": meta["failed"][offset:offset + 200]}

    @app.get("/api/holder/list/{list_id}/queue", dependencies=[Depends(holder_only)])
    def queue_page(list_id: str, offset: int = Query(0, ge=0), country: str = Query("", max_length=2),
                   status: str = Query("", max_length=10)) -> dict:
        meta = need_list(list_id)
        by_row = {n["row"]: n for n in held.notices(meta["id"])}
        rows = [b for b in picture_of(meta)["queue"] if (not country or b["country"] == country.upper())
                and (not status or b["place"]["status"] == status)]
        return {"total": len(rows), "rows": [queue_row(b, by_row.get(b["row"])) for b in rows[offset:offset + PAGE]]}

    @app.put("/api/holder/outreach/settings", dependencies=[Depends(holder_only)])
    def put_settings(body: SettingsIn, request: Request) -> dict:
        try:
            held.set_settings(body.holder, body.rules)
        except ValueError as err:
            raise HTTPException(422, str(err) + ".") from None
        return whole(request)

    # ---- notices -------------------------------------------------------------------------------------------------

    _settable: dict[str, bool] = {}

    def other_strings(language: dict) -> tuple[dict | None, str]:
        """The sentences in the owner's language, or (None, why not)."""
        code = language["code"]
        if code == "en":
            return None, language["reason"]
        strings = translations.get(code)
        if strings is None:
            return None, translations.notes.get(code) or "No checked translation is on hand for this language."
        if code not in _settable:
            _settable[code] = notices.can_set(" ".join(strings.values()))
        if not _settable[code]:
            return None, ("This server has no typeface for this language's script, so the letter is in English "
                          "only. Set KHUTLISA_WIDE_FONT to a font file that has it.")
        return strings, ""

    def make_notice(meta: dict, b: dict, rank: int, holder: dict, url: str, rules: dict) -> dict:
        language = notices.language_for(b["country"], b.get("region") or "")
        other, why_not = other_strings(language)
        code = notices.new_code()
        facts = notices.facts_for(b, holder, code, url)
        english = notices.render(notices.STRINGS, facts, b["property_class"])
        result = notices.check(b, holder, facts, english, notices.render(other, facts, b["property_class"]) if other else None,
                               Decimal(dormancy.NOTICE_MINIMUM_USD))
        return {"id": hashlib.sha256(code.encode()).hexdigest()[:12], "row": b["row"], "rank": rank, "code": code,
                "name": b["name"], "country": b["country"], "amount": b["amount"], "handover": b["place"]["handover"],
                "state": "ready" if result["ready"] else "held", "problems": result["problems"],
                "warnings": result["warnings"], "elements": {e["key"]: e["present"] for e in result["elements"]},
                "delivery": result["delivery"], "timing": outreach.timing_basis(b["place"]), "facts": facts,
                "language": {**language, "translated": other is not None,
                             "note": "" if other is not None or language["code"] == "en" else why_not},
                "prepared_at": outreach.now(), "sent": [], "opened_at": None, "opens": 0, "responded_at": None,
                "claim_id": None}

    @app.post("/api/holder/notices/prepare", dependencies=[Depends(holder_only)])
    def prepare(request: Request, body: PrepareIn | None = None) -> dict:
        """The agent prepares the notices: who first is decided in code, inside the holder's instructions, and
        every notice is checked for its required elements before it is called ready. Nothing is sent."""
        body = body or PrepareIn()
        meta = need_list()
        holder = holder_details(meta)
        if holder is None:
            raise HTTPException(409, "Give the holder's name and contact details first. The notice must carry them.")
        rules = held.settings()["rules"]
        picture = picture_of(meta)
        queue = picture["queue"]
        with held.lock:
            items = held.notices(meta["id"])
            place = {b["row"]: b["place"]["handover"] for b in queue}
            kept = [n for n in items if n.get("sent") or n.get("claim_id") or place.get(n["row"]) == n["handover"]]
            chosen = outreach.choose_owners(queue, rules, {n["row"] for n in kept})
            todo = chosen["chosen"][:body.limit] if body.limit else chosen["chosen"]
            made = [make_notice(meta, b, 0, holder, base_url(request), rules) for b in todo]
            # The agent's order, over the notices that stand and the new ones together.
            every = sorted(kept + made, key=lambda n: (n["handover"], -Decimal(n["amount"]), n["row"]))
            for i, n in enumerate(every, start=1):
                n["rank"] = i
            held.save_notices(meta["id"], every)
        out = whole(request)
        out["prepared"] = {"notices": len(made), "ready": len([n for n in made if n["state"] == "ready"]),
                           "held": len([n for n in made if n["state"] != "ready"]),
                           "amount": f"{sum((Decimal(n['amount']) for n in made), Decimal(0)):.2f}",
                           "card": outreach.notify_card({**picture}, chosen, rules, todo)}
        return out

    def find_notice(notice_id: str) -> tuple[dict, dict]:
        meta = need_list()
        notice = next((n for n in held.notices(meta["id"]) if n["id"] == notice_id), None)
        if notice is None:
            raise HTTPException(404, "There is no notice with that number.")
        return meta, notice

    def letter_of(meta: dict, notice: dict, reminder: bool = False) -> dict:
        balance = next(b for b in meta["balances"] if b["row"] == notice["row"])
        other, _ = other_strings(notice["language"]) if notice["language"]["translated"] else (None, "")
        kind = balance["property_class"]
        return {"balance": balance, "holder": holder_details(meta) or {}, "facts": notice["facts"],
                "english": notices.render(notices.STRINGS, notice["facts"], kind),
                "other": notices.render(other, notice["facts"], kind) if other else None,
                "language": notice["language"]["code"], "today": today().isoformat(), "reminder": reminder,
                "invented": bool(meta.get("invented"))}

    @app.get("/api/holder/notices", dependencies=[Depends(holder_only)])
    def notice_page(offset: int = Query(0, ge=0), stage: str = Query("", max_length=12),
                    q: str = Query("", max_length=80)) -> dict:
        """The notices in the agent's order. `q` keeps those whose owner's name contains every word of it."""
        from .names import normalise

        meta = need_list()
        words = normalise(q).split()
        items = [n for n in sorted(held.notices(meta["id"]), key=lambda n: n["rank"])
                 if all(w in normalise(n["name"]).split() or any(part.startswith(w) for part in normalise(n["name"]).split())
                        for w in words)]
        rows = [notice_row(n) for n in items]
        rows = [r for r in rows if not stage or r["stage"] == stage]
        return {"total": len(rows), "rows": rows[offset:offset + PAGE]}

    def pdf(letters: list[dict], name: str) -> Response:
        return Response(notices.letter_pdf(letters), media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})

    @app.get("/api/holder/notices/batch.pdf", dependencies=[Depends(holder_only)])
    def batch_pdf(limit: int = Query(200, ge=1, le=5000), which: str = Query("unsent", pattern="^(unsent|all|reminders)$")) -> Response:
        """Every letter in one PDF, each on a new page, in the order the agent chose. `which` is "unsent" (ready
        and not yet marked sent), "all" (every ready notice) or "reminders" (the reminders now due)."""
        meta = need_list()
        items = sorted(held.notices(meta["id"]), key=lambda n: n["rank"])
        if which == "reminders":
            due = {n["id"] for n in outreach.reminders_due(items, held.settings()["rules"], today())}
            picked = [n for n in items if n["id"] in due]
        else:
            picked = [n for n in items if n["state"] == "ready" and (which == "all" or not n.get("sent"))]
        if not picked:
            raise HTTPException(404, "There is no letter of that kind to print.")
        return pdf([letter_of(meta, n, reminder=which == "reminders") for n in picked[:limit]],
                   f"khutlisa-notices-{which}-{len(picked[:limit])}.pdf")

    @app.get("/api/holder/notices/{notice_id}", dependencies=[Depends(holder_only)])
    def notice_detail(notice_id: str) -> dict:
        """One notice as the holder reviews it: both languages, each required element, and how it can go out."""
        meta, notice = find_notice(notice_id)
        letter = letter_of(meta, notice)
        present = notice["elements"]
        views = {"english": notices.web_view(letter["english"], notice["facts"], letter["balance"])}
        if letter["other"]:
            views["other"] = notices.web_view(letter["other"], notice["facts"], letter["balance"])
        return {**notice_row(notice), "elements": [{**e, "present": present.get(e["key"], False)} for e in notices.ELEMENTS],
                "views": views, "link": f"{notice['facts']['LINK']}/{notice['code']}",
                "letter_url": f"/api/holder/notices/{notice_id}/letter.pdf", "sends_nothing": NOT_SENT}

    @app.get("/api/holder/notices/{notice_id}/letter.pdf", dependencies=[Depends(holder_only)])
    def letter_pdf(notice_id: str, reminder: bool = False) -> Response:
        meta, notice = find_notice(notice_id)
        if notice["state"] != "ready":
            raise HTTPException(409, "This notice is held back: " + " ".join(notice["problems"]))
        return pdf([letter_of(meta, notice, reminder)], f"khutlisa-notice-{notice_id}.pdf")

    @app.post("/api/holder/notices/sent", dependencies=[Depends(holder_only)])
    def mark_sent(body: SentIn, request: Request) -> dict:
        """The holder says it has sent these notices. This is the only way a delivery is recorded. A notice
        that is held back cannot be marked sent, and a reminder only after the notice itself."""
        meta = need_list()
        try:
            on = date.fromisoformat(body.on) if body.on else today()
        except ValueError:
            raise HTTPException(422, "The date must be written as 2026-11-13.") from None
        if on > today():
            raise HTTPException(422, "The date sent cannot be in the future.")
        with held.lock:
            items = held.notices(meta["id"])
            wanted = set(body.ids or [])
            due = {n["id"] for n in outreach.reminders_due(items, held.settings()["rules"], today())}
            marked = 0
            for n in items:
                if n["state"] != "ready":
                    continue
                if body.reminder:
                    chosen = n["id"] in due and (body.all_unsent or n["id"] in wanted)
                else:
                    chosen = not n.get("sent") and (body.all_unsent or n["id"] in wanted)
                if not chosen:
                    continue
                if body.channel == "email" and not any(d["channel"] == "email" for d in n["delivery"]):
                    continue
                n["sent"].append({"on": on.isoformat(), "channel": body.channel, "reminder": body.reminder,
                                  "marked_at": outreach.now(), "marked_by": "the holder"})
                marked += 1
            held.save_notices(meta["id"], items)
        out = whole(request)
        out["marked"] = marked
        return out

    # ---- the owner's side: open with the code on the letter ------------------------------------------------------------

    def notice_for(code: str) -> tuple[dict, dict]:
        found = held.by_code(code)
        if found is None or found[1]["state"] != "ready" or not found[1].get("sent"):
            # one answer for a wrong code and for a notice not yet sent, so a code cannot be probed
            raise HTTPException(404, notices.STRINGS["ui_not_found"])
        return found

    @app.get("/api/notices/{code}", dependencies=[Depends(counted)])
    def read_notice(code: str) -> dict:
        """The owner's notice, in the owner's language and in English. Opened with the code on the letter. The
        owner's name and street are not in the answer."""
        meta, notice = notice_for(code)
        if not notice.get("opened_at"):
            held.change_notice(meta["id"], notice["id"], lambda n: n.update({"opened_at": outreach.now(), "opens": 1}))
        else:
            held.change_notice(meta["id"], notice["id"], lambda n: n.update({"opens": int(n.get("opens") or 0) + 1}))
        letter = letter_of(meta, notice)
        views = {"english": notices.web_view(letter["english"], notice["facts"], letter["balance"])}
        if letter["other"]:
            views["other"] = notices.web_view(letter["other"], notice["facts"], letter["balance"])
        return {"code": notice["code"], "language": notice["language"], "views": views,
                "amount": notice["amount"], "currency": "USD", "holder": notice["facts"]["HOLDER"],
                "deadline": notice["facts"]["DEADLINE"], "deadline_words": handover.in_words(notice["facts"]["DEADLINE"]),
                "days_left": (date.fromisoformat(notice["facts"]["DEADLINE"]) - today()).days,
                "country": notice["country"], "claim_id": notice.get("claim_id"),
                "demonstration": bool(meta.get("invented"))}

    class AnswerIn(BaseModel):
        claimant: ClaimantIn
        history: history_model | None = None

    @app.post("/api/notices/{code}/answer", status_code=201, dependencies=[Depends(counted)])
    def answer_notice(code: str, body: AnswerIn, request: Request) -> dict:
        """The owner answers: a claim is opened on the exact record the notice is about, and the answer is
        recorded against the notice. From here on it is the same claim journey as any other."""
        meta, notice = notice_for(code)
        with held.lock, claim_store.lock:
            notice = next(n for n in held.notices(meta["id"]) if n["id"] == notice["id"])
            if notice.get("claim_id"):
                return {"claim_id": notice["claim_id"], "already": True}
            balance = next(b for b in meta["balances"] if b["row"] == notice["row"])
            record = dict(zip(outreach.ListRecords.COLUMNS,
                              outreach.record_row(meta, balance, notice["facts"]["HOLDER"])))
            public = app.state.public_record(record)
            match = {"score": 1.0, "strength": "strong",
                     "reasons": ["the holder sent a notice about this balance, and this claim was opened with the "
                                 "code on that notice"],
                     "doubts": ["the code shows that someone has the letter; it does not show who they are, which "
                                "is what the documents are for"]}
            claim = claim_store.create(public, body.claimant.model_dump(), match,
                                       {"source": record["source"], "record_id": record["record_id"]})
            claim["address_given"] = [{k: (getattr(p, k) or "").strip() for k in ("street", "city", "region", "postcode")}
                                      for p in (body.history.places if body.history else []) if (p.street or "").strip()]
            claim["notice"] = {"id": notice["id"], "answered_at": outreach.now()}
            # The same hooks as a claim opened from the search (rings.py keeps where it was opened from), so a
            # claim that came from a notice is checked across the queue like any other.
            for hook in claim_store.creation_hooks:
                hook(claim, request)
            claim["history"].append({"state": claim["state"], "at": outreach.now(), "note":
                                     f"The owner answered {notice['facts']['HOLDER']}'s notice with the code on the "
                                     "letter, and this claim was opened on that exact record."})
            claim_store.save(claim)
            held.change_notice(meta["id"], notice["id"],
                               lambda n: n.update({"claim_id": claim["id"], "responded_at": outreach.now()}))
        return {"claim_id": claim["id"], "already": False}

    return held


_SCO = "https://www.sco.ca.gov/"
LAW = [
    {"title": "Who must be told", "mark": "verified",
     "text": "Every owner of 50 US dollars or more whose address the holder has. Under 50 dollars no notice is required.",
     "source": "Code of Civil Procedure 1520(b); State Controller, holder due diligence (rev. 12/2022)",
     "url": _SCO + "Files-UPD/upd_duediligence.pdf"},
    {"title": "When", "mark": "verified",
     "text": "6 to 12 months before the Notice Report is due. The Notice Report is due before 1 November, so the "
             "window runs from 1 November to 30 April. After a missed window the notice still goes out, as soon as "
             "possible.",
     "source": "Code of Civil Procedure 1520(b); State Controller, holder due diligence",
     "url": _SCO + "Files-UPD/upd_duediligence.pdf"},
    {"title": "What it must say", "mark": "verified",
     "text": "The heading the law gives; the date the property goes to the State and that a claim is then needed; "
             "in bold, that there has been no activity, a reference of up to four digits, that the property is in "
             "danger, and that the law requires the transfer; a form to return, or a telephone number or electronic "
             "way to answer.",
     "source": "Code of Civil Procedure 1520(b); State Controller, sample due diligence letter",
     "url": _SCO + "Files-UPD/outreach_rptg_notice_duediligencesample.pdf"},
    {"title": "How it goes", "mark": "verified",
     "text": "By post to the address on record, or electronically if the owner agreed to that.",
     "source": "Code of Civil Procedure 1520(b); State Controller, holder due diligence",
     "url": _SCO + "Files-UPD/upd_duediligence.pdf"},
    {"title": "How long before property counts as unclaimed", "mark": "verified",
     "text": "Wages one year. Most other property three years. Money orders seven, traveler's cheques fifteen.",
     "source": "State Controller, dormancy periods (rev. 07/2023)",
     "url": _SCO + "Files-UPD/outreach_rptg_hol_dormancy.pdf"},
    {"title": "A notice in the owner's language, and an answer online", "mark": "our reading",
     "text": "The law gives the English heading and does not mention other languages. Khutlisa always includes the "
             "English notice and adds a translation. The law allows \"a telephone number or other electronic "
             "means\" for the owner to answer; treating a personal link with a code as such a means is our reading.",
     "source": "Code of Civil Procedure 1520(b), what it says and does not say",
     "url": "https://www.sco.ca.gov/files-upd/guide_upd_updlaw.pdf"},
]
