"""The claim, payout and payer routes. `register` adds them to the app built in server.py.

Privacy: a claim is created from `public_record`, so a private owner's full name and street never enter a claim
file, the packet, or the payer queue. The claimant's own typed details are theirs and are returned to them.
"""
import hmac
import json
import re
from typing import Callable, Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from . import airwallex as awx
from . import claims as cl
from . import cards, documents, handover, packet, payouts, proof, reading
from . import instructions as ins
from .countries import COUNTRIES
from .demo import is_demonstration
from .match import History, Place, compare_streets, find, score
from .names import Person, normalise

PAYER_KEY_HEADER = "X-Payer-Key"

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
RECORD_COLUMNS = ["source", "record_id", "owner_name", "owner_norm", "owner_street", "owner_city", "owner_region",
                  "owner_postcode", "owner_country", "amount", "currency", "holder_name", "holder_city",
                  "holder_region", "property_type"]


class ClaimantIn(BaseModel):
    """The claimant's own details, as they type them."""
    name: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=4, max_length=300)
    country: str = Field(min_length=2, max_length=2)
    email: str = Field(max_length=200)
    relationship: Literal["self", "heir"]

    @field_validator("name", "address", "email", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("country")
    @classmethod
    def _known_country(cls, v: str) -> str:
        if v.upper() not in COUNTRIES:
            raise ValueError("choose a country from the list")
        return v.upper()

    @field_validator("email")
    @classmethod
    def _looks_like_email(cls, v: str) -> str:
        if not _EMAIL.fullmatch(v):
            raise ValueError("give an email address")
        return v


class PayeeIn(BaseModel):
    """Where the money should land: the claimant's own local bank account. It is given before the payer decides,
    so the payer's approval covers this exact account."""
    currency: Literal["PHP", "MXN"]
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    account_number: str = Field(min_length=6, max_length=34)
    swift_code: str = Field(default="", max_length=11)
    street_address: str = Field(min_length=3, max_length=200)
    city: str = Field(min_length=1, max_length=80)
    postcode: str = Field(default="", max_length=20)
    state: str = Field(default="", max_length=20)

    @field_validator("*", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


class PlanIn(BaseModel):
    """`what_if` asks the sandbox to stage one change of circumstance, so the response to it can be seen."""
    what_if: Literal["short_deposit", "transfer_fails", "transfer_returned", "rate_lock_expires"] | None = None


class InstructionsIn(BaseModel):
    """The holder's standing instructions. Checked and cleaned by instructions.clean."""
    tolerance_percent: str | float = Field(default=ins.DEFAULTS["tolerance_percent"])
    small_claim_usd: str | float = Field(default=ins.DEFAULTS["small_claim_usd"])
    route_rule: str = Field(default=ins.DEFAULTS["route_rule"], max_length=40)
    deadline_days: int = Field(default=ins.DEFAULTS["deadline_days"])
    # The holder's own date for handing unclaimed property to the State, and how long an owner needs to send a
    # document. Kept beside the instructions (handover.py); left out, the date already on file stands.
    handover_date: str | None = Field(default=None, max_length=10)
    document_days: int | None = None


class ApproveIn(BaseModel):
    """How the holder funds the claim it approves: a bank deposit, or a pull under a mandate on Metal. Left out,
    a first approval is funded by a bank deposit and a later one keeps the claim's choice."""
    funding: Literal["bank", "metal"] | None = None


class ConfirmIn(BaseModel):
    plan_id: str = Field(min_length=8, max_length=60)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


def register(app: FastAPI, store, claim_store: cl.ClaimStore, runner: payouts.PayoutRunner, history_model,
             public_record: Callable[[dict], dict], safe_lines: Callable[..., list[str]],
             read_documents: bool = False, ids=None, payer_key: str = "") -> None:

    class ClaimIn(BaseModel):
        # Our own id for the row, exactly as the search returned it. It names one owner of one property, and it
        # is not the State's property number, which never reaches a browser.
        record_id: str = Field(min_length=1, max_length=80)
        source: str = Field(default="", max_length=40)
        owner_shown: str = Field(default="", max_length=200)   # no longer needed; accepted from older pages
        claimant: ClaimantIn
        history: history_model | None = None   # what the person told the search, so the match can be explained

    def guard(fn):
        try:
            return fn()
        except cl.ClaimError as err:
            raise HTTPException(err.status, err.message) from None

    def payer_only(key: str | None = Header(default=None, alias=PAYER_KEY_HEADER)) -> None:
        """The payer's routes take a shared key in a header. Claim routes do not: whoever holds a claim's own
        number may read and change that claim, and nobody can list the numbers without this key."""
        if not payer_key:
            raise HTTPException(401, "The holder's view is locked: no key for it is set on this server. Set "
                                     "KHUTLISA_PAYER_KEY and start it again.")
        if not key or not hmac.compare_digest(key.encode(), payer_key.encode()):
            raise HTTPException(401, "The holder's key is missing or wrong.")

    def rows_for(source: str, record_id: str) -> list[dict]:
        sql = f"select {', '.join(RECORD_COLUMNS)} from records where record_id = ?"
        params = [record_id]
        if source:
            sql += " and source = ?"
            params.append(source)
        # California's owner records, the demonstration records and, by number only, the holder's own lists
        with getattr(store, "looking_up", store.searching)() as cursors:
            return [dict(zip(RECORD_COLUMNS, r)) for cur in cursors
                    for r in cur.execute(sql + " order by amount desc limit 200", params).fetchall()]

    def private_record(claim: dict) -> dict | None:
        """The full register record behind a claim, for comparing only. It never leaves this module: the proof
        built with it says whether things matched and shows the owner in the claim's masked form."""
        held = claim.get("property") or {}
        try:
            rows = rows_for(held.get("source") or "", held.get("record_id") or "")
        except Exception:
            return None
        shown = claim["record"].get("record_id")
        return next((row for row in rows if public_record(row)["record_id"] == shown), None)

    def proof_of(claim: dict, payer: bool = False) -> dict:
        """`payer` words the result for the office that decides the claim instead of for the claimant."""
        if not read_documents:
            return {"assessed": False}
        return proof.build_proof(claim, claim["documents"], private_record(claim), payer=payer)

    def is_sample(claim: dict) -> bool:
        """True for a claim on a demonstration record: one Khutlisa added itself, not one of California's."""
        return is_demonstration(claim["record"].get("source"))

    # For the modules that add their own routes beside these (estates_api.py, rings_api.py).
    app.state.payer_only = payer_only
    app.state.private_record = private_record
    app.state.proof_of = proof_of
    app.state.claim_view = lambda claim: claim_view(claim)
    app.state.queue_row = lambda claim: queue_row(claim)
    claim_store.reading_on = read_documents
    reader = reading.ReadingRunner(claim_store, is_ready=lambda claim: proof_of(claim)["ready"])
    app.state.reading = reader
    app.state.proof_ready = lambda claim: bool(proof_of(claim).get("ready"))
    app.state.read_documents = read_documents
    app.state.record_ids = ids

    def with_proof(need: dict, result: dict) -> dict:
        """The checklist with the proof result laid over it, item by item."""
        if not result.get("assessed"):
            return need
        by_key = {r["key"]: r for r in result["requirements"]}
        items = [{**i, "proof": by_key[i["key"]]["status"], "supports": by_key[i["key"]]["supports"]}
                 for i in need["items"]]
        return {**need, "items": items}

    def payee_view(claim: dict) -> dict | None:
        """The bank account on file, with the account number cut to its last four digits."""
        payee = claim.get("payee")
        if not payee:
            return None
        bank = payee["beneficiary"]["beneficiary"]["bank_details"]
        address = payee["beneficiary"]["beneficiary"].get("address") or {}
        return {"currency": payee["currency"], "account_name": bank.get("account_name"),
                "account_number": payouts._mask_account(bank.get("account_number") or ""),
                "bank_country": bank.get("bank_country_code"), "swift_code": bank.get("swift_code"),
                "city": address.get("city"), "set_at": payee.get("set_at"), "checked_by": payee.get("checked_by")}

    def approval_view(claim: dict) -> dict | None:
        approval = claim.get("approval")
        if not approval:
            return None
        t = approval["terms"]
        rules = t.get("instructions")
        return {"at": approval["at"], "amount": t["amount"], "currency": t["currency"],
                "claimant_name": t["claimant_name"], "documents": len(t["documents"]),
                "payee_currency": t.get("payee_currency"), "terms_hash": approval["terms_hash"],
                "replaces_earlier_approval": approval.get("replaces_earlier_approval", False),
                # The standing instructions as they stood at this approval. A later change does not touch them.
                "instructions": rules and {"rules": rules, "in_words": ins.in_words(rules)},
                "deadline_at": approval.get("deadline_at"), "fee_rule": approval.get("fee_rule")}

    def line_view(claim: dict) -> dict:
        """Where this claim stands among the claims on the same property. No other claimant is named."""
        others = claim_store.same_property(claim)
        return {"others": len(others), "ahead": len(claim_store.ahead_of(claim)),
                "paid_elsewhere": any(o["state"] == cl.PAID for o in others),
                "held_elsewhere": any(o["state"] in cl.HOLDS_THE_PROPERTY for o in others)}

    # "estate" holds each heir's bank account and has its own view (estates_api.py); "origin" and "risk" are for
    # the holder's risk view (rings_api.py).
    HIDDEN = ("property", "payee", "approval", "past_approvals", "estate", "origin", "risk")

    # ---- the street the person gave: compared here, never in the search ----------------------------------
    #
    # The search is open to anyone and never looks at a street (match.py). The streets a person gave with their
    # history are kept with the claim, in their own typed words, and compared with the record's street on the
    # server only once the claim holds photo identification that has been read and ties the claimant to the
    # record. Until then the view says only that the comparison will be made. After it, the view says that the
    # street matches or does not match, and never the street on the record.

    ADDRESS_TEXT = {
        "not_given": "No street was given with the history, so no street is compared with the record.",
        "waiting": "The street they gave has not been compared with the record. It will be compared once photo "
                   "identification that carries the name on the record has been read.",
        "matches": "The street they gave matches the street on the record.",
        "does_not_match": "The street they gave does not match the street on the record.",
        "no_street_on_record": "The record carries no street, so the street they gave cannot be compared.",
    }

    def streets_given(history_in) -> list[dict]:
        """The places a person gave a street for, in their own words. Kept with the claim."""
        if history_in is None:
            return []
        return [{k: (getattr(p, k) or "").strip() for k in ("street", "city", "region", "postcode")}
                for p in history_in.places if (p.street or "").strip()]

    def identification_read(claim: dict, result: dict) -> bool:
        """Whether the street may be compared yet. For a person claiming their own money the proof file must
        have tied them to the record (proof.build_proof's `record_link`): government photo identification that
        was read, is current, is in the claimant's name and carries the name on the record, or the same with a
        civil or court record linking the two names. A stranger's own passport does not open the comparison,
        so a claim cannot be used to try streets against somebody else's record. For an heir or an
        organisation, whose identification is not in the owner's name, the whole proof must be ready."""
        if not result.get("assessed"):
            return False
        link = result.get("record_link")
        return link.get("status") == "matched" if link else bool(result.get("ready"))

    def address_check(claim: dict, result: dict) -> dict:
        """{"status", "text"} for the claim view. The status is one of the keys of ADDRESS_TEXT."""
        given = claim.get("address_given") or []
        status = "not_given" if not given else "waiting"
        if given and identification_read(claim, result):
            record = private_record(claim)
            if record is not None:
                status = compare_streets(given, record)
        return {"status": status, "text": ADDRESS_TEXT[status]}

    def match_view(claim: dict, result: dict, check: dict | None = None) -> dict | None:
        """The claim's match explanation with the street comparison added as a reason or a doubt, once it has
        been made. The stored explanation is the search's own and never mentions a street."""
        match = claim.get("match")
        check = check or address_check(claim, result)
        if not match or check["status"] not in ("matches", "does_not_match"):
            return match
        line = check["text"][0].lower() + check["text"][1:].rstrip(".")
        key = "reasons" if check["status"] == "matches" else "doubts"
        return {**match, key: list(match.get(key) or []) + [line]}

    # ---- the handover to the State: the holder's date, and what the agent does as it comes near ----------

    handover_path = claim_store.folder / "holder_handover.json"

    def handover_setting() -> dict:
        """The holder's handover date and the days an owner needs for a document. The next 1 June until set."""
        try:
            held = json.loads(handover_path.read_text())
            return {**handover.clean(held), "set_by": "the holder"}
        except (OSError, ValueError):
            return {**handover.clean({}), "set_by": "default: the next 1 June"}

    def handover_view() -> dict:
        setting = handover_setting()
        return {**setting, "date_words": handover.in_words(setting["handover_date"]),
                "days_left": handover.days_left(setting), "schedule": handover.SCHEDULE}

    def deadline_card(claim: dict, result: dict) -> dict | None:
        """The deadline choice for a claim the holder has not decided yet: pay, ask the owner, or release."""
        if claim["state"] not in cl.BEFORE_DECISION:
            return None
        if result.get("assessed"):
            ready = bool(result.get("ready"))
            missing = [re.sub(r"^(the claimant's|your)\s+", "", r["title"], flags=re.I)
                       for r in result.get("requirements") or [] if r.get("required") and r.get("status") != "satisfied"]
        else:
            need = cl.checklist(claim)
            ready = bool(need["complete"])
            missing = [re.sub(r"^(the claimant's|your)\s+", "", m, flags=re.I) for m in need.get("missing") or []]
        amount = cards._money(claim["record"].get("amount") or 0)
        return handover.card(handover_setting(), proof_ready=ready, missing=missing, amount=amount)

    def deadline_summary(rows: list[dict]) -> dict | None:
        """One card for the whole queue: with time in hand the agent asks for what is missing; near the handover
        it pays what is proven and releases the rest to the State process."""
        open_ = [r for r in rows if r.get("deadline")]
        if not open_:
            return None
        first = open_[0]["deadline"]
        by = {k: [r for r in open_ if r["deadline"]["choice"] == k] for k in ("pay", "ask", "release")}
        # What is proven: open claims whose proof is ready, and the claims already approved, on their way or paid.
        proven = by["pay"] + [r for r in rows if r["state"] in (cl.APPROVED, cl.PAYING, cl.PAID, cl.PAYMENT_HELD)]
        total = lambda found: cards._money(sum(float(r["amount"] or 0) for r in found))
        count = lambda found: f"{len(found)} {'claim' if len(found) == 1 else 'claims'}"
        near = first["days_left"] <= first["document_days"]
        if by["release"]:
            did = (f"Near the date: it pays what is proven ({count(proven)}) and releases the rest "
                   f"({count(by['release'])}) to the State process.")
            money = f"{total(proven)} to owners. {total(by['release'])} goes on the Remit Report."
            tone = "stop"
        elif by["ask"]:
            did = f"Time in hand: it asked the owner for the missing document on {count(by['ask'])}."
            money = f"{total(proven)} proven. {total(by['ask'])} waits for a document."
            tone = "ask"
        else:
            did = f"Every open claim is proven ({count(by['pay'])}): pay before the handover."
            money = f"{total(by['pay'])} goes to owners, not to the State."
            tone = "go"
        return {**first, "title": "The handover date, across your open claims", "did": did, "money": money,
                "tone": tone, "choice": "release" if by["release"] else "ask" if by["ask"] else "pay", "near": near,
                "allowed": f"An owner needs about {first['document_days']} days to send a document."}

    def refusal_view(claim: dict) -> dict | None:
        """The last transfer the bank refused or returned on this claim, as a decision card, for the holder."""
        path = claim_store.payout_path(claim["id"])
        if not path.exists():
            return None
        payout = json.loads(path.read_text())
        if not payout.get("attempts"):
            return None
        card = cards.refusal_card(payout["attempts"][-1], payout)
        now_to = (((payout.get("beneficiary") or {}).get("beneficiary") or {}).get("bank_details") or {}).get("account_number") or ""
        return {**card, "first_account": payout["attempts"][-1].get("account_last4"), "now_account": now_to[-4:] or None,
                "payout_state": payout.get("state"), "needs": (payout.get("hold") or {}).get("needs", [])}

    def claim_view(claim: dict) -> dict:
        """A claim as its claimant sees it. The register's own property number stays on the server."""
        result = proof_of(claim)
        need = with_proof(cl.checklist(claim), result)
        check = address_check(claim, result)
        return {**{k: v for k, v in claim.items() if k not in HIDDEN},
                "address_given": claim.get("address_given") or [],
                "address_check": check, "match": match_view(claim, result, check),
                "sample": is_sample(claim), "checklist": need, "proof": result,
                "documents": [{k: v for k, v in d.items() if k not in ("stored_as", "sha256")}
                              for d in claim["documents"]],
                "payee": payee_view(claim), "approval": approval_view(claim), "line": line_view(claim),
                "approvals_withdrawn": [{"at": a.get("voided_at"), "because": a.get("voided_because")}
                                        for a in claim.get("past_approvals") or []],
                "packet_url": f"/api/claims/{claim['id']}/packet.pdf",
                "deadline": deadline_card(claim, result),
                "is_estate": bool(claim.get("estate")),
                "payout_started": claim_store.payout_path(claim["id"]).exists()}

    def find_record(body: ClaimIn) -> dict:
        held = ids.find(body.record_id) if ids is not None else None
        if held is None:
            raise HTTPException(404, "There is no record with that number. Search again and choose it from the "
                                     "results.")
        row = next((r for r in rows_for(*held) if public_record(r)["record_id"] == body.record_id), None)
        if row is None:
            raise HTTPException(404, "There is no record with that number in the register.")
        if (row.get("currency") or "USD") != "USD":
            # Queensland's register is searched, and its records are in Australian dollars. The claim path here
            # is built on California's rules and on a holder paying US dollars, so it does not open one.
            raise HTTPException(422, "This record is in Queensland's register. It can be searched here, and a "
                                     "claim on it is made to the Public Trustee of Queensland.")
        return row

    def explain_match(record: dict, history_in) -> dict | None:
        """The matcher's strength, reasons and doubts for this record against what the person said, made safe."""
        if history_in is None:
            return None
        person = Person(given=history_in.given_names, family=history_in.family_names)
        if not any(len(k) >= 2 for k in person.family_keys()):
            return None
        history = History(person=person,
                          places=[Place(**p.model_dump()) for p in history_in.places if any(p.model_dump().values())],
                          employers=history_in.employers, current_country=history_in.current_country.strip())
        with store.searching() as cursors:   # the search's own answer, so the claim carries the strength they saw
            hit = next((m for m in find(cursors, history, top=500, floor=0.0)
                        if m.record.get("record_id") == record["record_id"]
                        and m.record.get("owner_name") == record["owner_name"]), None)
        hit = hit or score(record, history)
        said = set(normalise(" ".join(
            history_in.given_names + history_in.family_names + history_in.employers
            + [v for p in history_in.places for k, v in p.model_dump().items() if k != "street"])).split())
        org = public_record(record)["owner_is_organisation"]
        return {"score": hit.score, "strength": getattr(hit, "strength", None),
                "reasons": safe_lines(hit.reasons, record, said, org),
                "doubts": safe_lines(hit.doubts, record, said, org)}

    # ---- claims ------------------------------------------------------------------------------------------

    @app.get("/api/document-kinds")
    def document_kinds() -> list[dict]:
        return [{"kind": k, "label": label, "weight": documents.WEIGHT[k]} for k, label in documents.KINDS.items()]

    @app.post("/api/claims", status_code=201)
    def create_claim(body: ClaimIn, request: Request) -> dict:
        record = find_record(body)
        match = explain_match(record, body.history)
        with claim_store.lock:
            claim = claim_store.create(public_record(record), body.claimant.model_dump(), match,
                                       {"source": record.get("source") or "", "record_id": record.get("record_id") or ""})
            # The streets they gave, in their own words. They are compared later, in address_check.
            claim["address_given"] = streets_given(body.history)
            for hook in claim_store.creation_hooks:
                hook(claim, request)
            claim_store.save(claim)
        return claim_view(claim)

    @app.get("/api/claims/{claim_id}")
    def get_claim(claim_id: str) -> dict:
        return claim_view(guard(lambda: claim_store.load(claim_id)))

    @app.post("/api/claims/{claim_id}/documents", status_code=201)
    async def add_document(claim_id: str, kind: str = Form(...), file: UploadFile = File(...)) -> dict:
        guard(lambda: claim_store.load(claim_id))
        data = await file.read(documents.MAX_BYTES + 1)
        claim = guard(lambda: claim_store.add_document(claim_id, kind, file.filename or "", data))
        if read_documents:   # the reading runs in the background; the screen polls the claim for the result
            reader.start(claim_id, claim["documents"][-1]["id"])
        return claim_view(claim)

    @app.delete("/api/claims/{claim_id}/documents/{doc_id}")
    def remove_document(claim_id: str, doc_id: str) -> dict:
        """Takes a document out of the proof file. If the payer had already approved, the approval is withdrawn,
        because it covered the documents as they were."""
        return claim_view(guard(lambda: claim_store.remove_document(claim_id, doc_id)))

    @app.get("/api/claims/{claim_id}/packet.pdf")
    def packet_pdf(claim_id: str) -> Response:
        claim = guard(lambda: claim_store.packet_made(claim_id))
        result = proof_of(claim)
        # The State's property number is printed only once the proof is ready: the claimant needs it to file,
        # and until then it would let anyone who opened a claim look the owner up.
        number = (claim.get("property") or {}).get("record_id") if result.get("ready") else None
        pdf = packet.build(claim, cl.checklist(claim), proof=result, property_number=number)
        return Response(pdf, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="khutlisa-claim-{claim_id}.pdf"',
            "Cache-Control": "no-store"})

    @app.post("/api/claims/{claim_id}/filed")
    def mark_filed(claim_id: str) -> dict:
        """The claimant tells us they signed the packet and sent it themselves. Khutlisa files nothing."""
        return claim_view(guard(lambda: claim_store.move(
            claim_id, (cl.PACKET_READY,), cl.FILED,
            "The claimant reports that they signed the packet and sent it themselves.",
            "A claim can be marked as sent only after its packet is complete and has been downloaded.")))

    # ---- the bank account to be paid ---------------------------------------------------------------------

    def load_payout(claim_id: str) -> awx.Payout | None:
        path = claim_store.payout_path(claim_id)
        return awx.Payout.load(path) if path.exists() else None

    def payout_view(claim: dict) -> dict:
        path = claim_store.payout_path(claim["id"])
        payout = json.loads(path.read_text()) if path.exists() else None
        shown = payouts.view(claim, payout, running=runner.running(claim["id"]),
                             problem=runner.problems.get(claim["id"]), credentials_ready=runner.credentials_ready(),
                             simulator_ready=runner.simulator_ready())
        if payout is None and claim.get("batch"):
            # Paid together with other approved claims: the payment is one of that batch's (book_api.py).
            shown["in_batch"] = {**claim["batch"], "note":
                                 f"This claim is paid as payment {claim['batch']['n']} of a batch the holder "
                                 "approved, from one deposit shared with other approved claims. The amount and the "
                                 "bank account are the ones the holder's approval covers."}
        return shown

    def checked_beneficiary(claim: dict, body: PayeeIn) -> tuple[dict, str]:
        """The Airwallex beneficiary body for these bank details, after every check that can be made now.
        Returns (body, who checked it)."""
        if (claim["record"].get("currency") or "USD") != "USD":
            raise HTTPException(409, "Only records held in US dollars can be paid out today.")
        holder = f"{body.first_name} {body.last_name}"
        # The account must be the claimant's own. Every word of the account holder's name has to be part of the
        # claimant's name (an initial may stand for a word), and at least two words have to match in full.
        if proof.compare_names(claim["claimant"]["name"], holder) != "full":
            raise HTTPException(422, f"The bank account is in the name {holder}, and this claim is in the name "
                                     f"{claim['claimant']['name']}. A claim is paid only into an account in the "
                                     "claimant's own name.")
        try:
            beneficiary = awx.local_beneficiary(
                body.currency, body.first_name, body.last_name, body.account_number.replace(" ", ""),
                swift_code=body.swift_code.upper() or None, street_address=body.street_address, city=body.city,
                postcode=body.postcode or None, state=body.state or None)
        except ValueError as err:
            text = str(err)
            raise HTTPException(422, text[:1].upper() + text[1:] + ".") from None
        try:
            client, _ = runner.factory()
        except awx.CredentialsError:
            return beneficiary, "Khutlisa's own checks (the Airwallex keys are not set up on this server)"
        try:   # the live schema for this corridor, then Airwallex's own validation, before anything is stored
            schema = client.beneficiary_schema(awx.CORRIDORS[body.currency]["country"], body.currency)
            problems = awx.schema_problems(schema, beneficiary)
            if problems:
                raise HTTPException(422, "The bank details do not fit what Airwallex requires: "
                                    + "; ".join(problems) + ".")
            client.validate_beneficiary(beneficiary)
        except awx.AirwallexError as err:
            if err.status == 400:
                raise HTTPException(422, f"Airwallex did not accept the bank details: "
                                         f"{(err.message or err.code or 'no reason given')[:300]}") from None
            raise HTTPException(502, payouts.explain(err)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Airwallex could not be reached. Try again in a moment.") from None
        finally:
            client.close()
        return beneficiary, "Airwallex's validation for this country and currency"

    @app.put("/api/claims/{claim_id}/payee")
    def set_payee(claim_id: str, body: PayeeIn) -> dict:
        """The claimant's bank account. Given before the payer decides, so the approval covers this account. A
        change after approval withdraws the approval. After a failed or returned payment this is where the
        corrected details go."""
        claim = guard(lambda: claim_store.load(claim_id))
        if claim["state"] in (cl.PAYING, cl.PAID, cl.REJECTED):
            raise HTTPException(409, "The bank account cannot be changed while a payment is under way or after "
                                     "the claim is closed.")
        beneficiary, checked_by = checked_beneficiary(claim, body)
        with claim_store.lock:
            payout = load_payout(claim_id)
            if payout is not None and payout.currency_locked() and body.currency != payout.target_currency:
                raise HTTPException(409, f"The money for this claim is already held in {payout.target_currency}, "
                                         "so the corrected account must take that currency.")
            claim = guard(lambda: claim_store.set_payee(
                claim_id, {"currency": body.currency, "beneficiary": beneficiary, "checked_by": checked_by}))
            if payout is not None and payout.state != awx.PAID:
                payout.beneficiary, payout.target_currency = beneficiary, body.currency
                if payout.state == awx.PLANNED:      # the plan was for another account: it has to be made again
                    payout.plan = None
                if payout.hold and "bank_details" in payout.hold.get("needs", []):
                    payout.agreed("bank_details")
                payout.save()
        return claim_view(claim)

    # ---- payout ------------------------------------------------------------------------------------------

    def ready_to_pay(claim: dict, payout: awx.Payout | None) -> None:
        """Refuses unless a live approval covers the claim exactly as it stands now."""
        if not claim.get("approval"):
            raise HTTPException(409, "A payment can start only after the holder has approved the claim.")
        # A first approval covers the amount on the record. An approval given after the money had already moved
        # (it arrived short, or it came back from the bank) covers exactly what is held for the claim.
        again = claim["approval"].get("replaces_earlier_approval")
        funds = payout.funds if payout is not None and again else None
        holds, why = cl.approval_holds(claim, funds)
        if not holds:
            with claim_store.lock:
                fresh = claim_store.load(claim["id"])
                if claim_store.void_approval(fresh, why):
                    claim_store.save(fresh)
            raise HTTPException(409, f"The holder's approval no longer holds, because {why}. The holder has to "
                                     "approve the claim again.")
        guard(lambda: claim_store.check_property_is_free(claim))
        guard(lambda: claim_store.check_may_pay(claim))

    @app.post("/api/claims/{claim_id}/payout/plan")
    def plan_payout(claim_id: str, body: PlanIn | None = None) -> dict:
        """Writes the payout plan for an approved claim: the route, the fees, the locked rate and the amount to
        expect, and what will be done if things change. It takes a quote from Airwallex and moves no money.
        Asking again before confirming makes a new plan with a new quote."""
        body = body or PlanIn()
        claim = guard(lambda: claim_store.load(claim_id))
        path = claim_store.payout_path(claim_id)
        existing = load_payout(claim_id)
        if existing is not None and existing.state != awx.PLANNED:
            return payout_view(claim)      # the payment has started: there is one payout per claim, and this is it
        if claim.get("estate"):
            raise HTTPException(409, "This is an estate claim. It is paid as one settlement to every heir, from "
                                     "the estate view.")
        if claim.get("batch"):
            raise HTTPException(409, "The holder is paying this claim together with other approved claims, in "
                                     "one batch. It is not paid on its own as well.")
        if claim["state"] != cl.APPROVED:
            raise HTTPException(409, "A payment can start only after the holder has approved the claim.")
        ready_to_pay(claim, None)
        payee = claim["payee"]
        approval = claim["approval"]
        rules = approval["terms"].get("instructions")
        claim_usd = str(awx.money(claim["record"]["amount"], "USD"))
        # Under the holder's fee rule a small claim is topped up with Airwallex's expected fees, so what the
        # holder sends can be more than the claim. Without instructions it is the claim's own amount.
        sends = ins.fee_plan(claim_usd, rules)["holder_sends"]
        try:
            client, simulator = runner.factory()
        except awx.CredentialsError:
            raise HTTPException(503, payouts.NO_CREDENTIALS) from None
        try:
            with claim_store.lock:
                payout = awx.Payout.open(path, usd_amount=sends,
                                         target_currency=payee["currency"], state=awx.PLANNED,
                                         deposit_reference=f"KHUTLISA-{claim_id}", beneficiary=payee["beneficiary"])
                if payout.state != awx.PLANNED:
                    return payout_view(claim)
                payout.beneficiary, payout.target_currency = payee["beneficiary"], payee["currency"]
                payout.usd_amount, payout.claim_usd = sends, claim_usd
                payout.instructions, payout.deadline_at = rules, approval.get("deadline_at")
                payout.what_if = body.what_if if simulator is not None else None
                payouts.make_plan(payout, client, simulator_ready=simulator is not None, fresh=True)
                payout.save()
        except awx.AirwallexError as err:
            raise HTTPException(502, payouts.explain(err)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Airwallex could not be reached. Try again in a moment.") from None
        finally:
            client.close()
        return payout_view(claim)

    @app.post("/api/claims/{claim_id}/payout/confirm")
    def confirm_payout(claim_id: str, body: ConfirmIn) -> dict:
        """The claimant agrees to the plan they were shown. The first time this starts the payment. After a
        pause it lets the payment carry on with the recalculated amount. `plan_id` must be the plan now on
        file, so nobody agrees to figures that have since changed."""
        claim = guard(lambda: claim_store.load(claim_id))
        with claim_store.lock:
            payout = load_payout(claim_id)
            if payout is None:
                raise HTTPException(409, "There is no payout plan to agree to yet.")
            hold = payout.hold or {}
            plan = hold.get("plan") if hold else payout.plan      # during a stop, only the plan made for the stop
            waiting = payout.state == awx.PLANNED or "claimant" in hold.get("needs", [])
            if not waiting:
                return payout_view(claim)                      # nothing is waiting for the claimant
            if not plan or plan["id"] != body.plan_id:
                raise HTTPException(409, "The plan has changed since you saw it. Read the new plan and agree to "
                                         "that one.")
            if "bank_details" in hold.get("needs", []):
                raise HTTPException(409, "Correct the bank details first. The holder then approves the new "
                                         "destination, and after that you can agree to the new amount.")
            if "payer" in hold.get("needs", []):
                raise HTTPException(409, "The holder has to approve the new terms first.")
            ready_to_pay(claim, payout)
            ends = awx._parse_time(payout.deadline_at)
            if payout.state == awx.PLANNED and ends is not None and awx.time.time() > ends:
                fresh = claim_store.load(claim_id)
                if claim_store.void_approval(fresh, "the deadline in the holder's standing instructions passed "
                                                    "before the payment was started"):
                    claim_store.save(fresh)
                raise HTTPException(409, "The holder's deadline for this payment has passed, so it cannot be "
                                         "started. The holder has to approve the claim again.")
            if payout.state == awx.PLANNED and payout.quote_id and awx._quote_expired(payout, awx.time.time):
                raise HTTPException(409, "The rate in this plan is no longer locked. Ask for the plan again.")
            payout.confirmed = {"plan_id": plan["id"], "local_amount": plan["expected_local"]["amount"],
                                "currency": plan["expected_local"]["currency"], "at": cl.now()}
            payout.plan = plan
            if payout.state == awx.PLANNED:
                claim = guard(lambda: claim_store.move(
                    claim_id, (cl.APPROVED,), cl.PAYING,
                    f"The claimant agreed to the payout plan and the payment started on the Airwallex sandbox, to "
                    f"a bank account in {payouts.PLACES[payout.target_currency]}.",
                    "A payment can start only after the holder has approved the claim."))
                payout._move(awx.DEPOSIT_EXPECTED, f"plan {plan['id']} agreed by the claimant")
            else:
                payout.agreed("claimant")
                with claim_store.lock:
                    claim = claim_store.load(claim_id)
                    claim["history"].append({"state": claim["state"], "at": cl.now(), "note":
                                             "The claimant agreed to the recalculated amount, and the payment "
                                             "carried on."})
                    claim_store.save(claim)
        runner.start(claim_id)
        return payout_view(claim)

    @app.post("/api/claims/{claim_id}/payout/resume")
    def resume_payout(claim_id: str) -> dict:
        """Carries on with a payment that stopped waiting on Airwallex. It is the same payout with the same
        request ids, so nothing is made twice. A payment that waits for a person is left alone."""
        claim = guard(lambda: claim_store.load(claim_id))
        payout = load_payout(claim_id)
        if payout is not None and payout.state not in awx.STOPPED and payout.state != awx.PAID:
            runner.start(claim_id)
        return payout_view(claim)

    @app.get("/api/claims/{claim_id}/payout")
    def get_payout(claim_id: str) -> dict:
        return payout_view(guard(lambda: claim_store.load(claim_id)))

    # ---- the payer's view --------------------------------------------------------------------------------

    def proof_summary(result: dict) -> dict:
        """The proof as a payer sees it: the verdict, the reasons, and each requirement with its visible ties."""
        if not result.get("assessed"):
            return {"assessed": False}
        return {"assessed": True, "ready": result["ready"], "readiness": result["readiness"],
                # "held for a person to look at" is its own status here, apart from "not ready"
                "status": result["status"], "held": result["held"],
                "remaining_risk": result["remaining_risk"], "decided_by": result["decided_by"],
                "documents": [{k: d[k] for k in ("filename", "kind_label", "standing", "read", "checks",
                                                 "held", "held_reasons")} for d in result["documents"]],
                "reasons": result["reasons"], "summary": result["summary"], "samples": result["samples"],
                "record_link": result["record_link"],
                "requirements": [{"title": r["title"], "key": r["key"], "required": r["required"],
                                  "status": r["status"],
                                  "problems": [] if any(e["settles"] for e in r["supports"]) else
                                              [p for e in r["supports"] for p in e["problems"]],
                                  "facts": [f for e in r["supports"] if e["settles"] for f in e["facts"]],
                                  # the documents that settle it; if none does, the ones that were offered
                                  "files": [e["filename"] for e in r["supports"] if e["settles"]]
                                           or [e["filename"] for e in r["supports"]]}
                                 for r in result["requirements"]],
                "concerns": [{"filename": d["filename"], "concerns": d["concerns"]}
                             for d in result["documents"] if d["concerns"]]}

    def payer_hold(claim: dict) -> dict | None:
        """What changed in a payment that is on hold, for the office that has to approve the new terms."""
        payout = load_payout(claim["id"])
        if payout is None or not payout.hold:
            return None
        hold = payout.hold
        return {"kind": hold["kind"], "needs": hold.get("needs", []),
                "explanation": hold.get("explanation") or payouts.fixed_explanation(hold["kind"], hold.get("facts") or {},
                                                                                    hold.get("plan")),
                "funds": payout.funds, "waiting_for_bank_details": "bank_details" in hold.get("needs", []),
                "expected_local": (hold.get("plan") or {}).get("expected_local")}

    def can_decide(claim: dict) -> bool:
        if claim["state"] in cl.BEFORE_DECISION:
            return True
        hold = payer_hold(claim) if claim["state"] == cl.PAYMENT_HELD else None
        return bool(hold and "payer" in hold["needs"] and not hold["waiting_for_bank_details"])

    def queue_row(claim: dict) -> dict:
        need = cl.checklist(claim)
        result = proof_of(claim, payer=True)
        # The search's explanation with the street comparison added once photo identification has been read:
        # the holder sees the same result as the claimant, and never the street on the record.
        match = match_view(claim, result)
        return {
            "id": claim["id"], "state": claim["state"], "created_at": claim["created_at"],
            "sample": is_sample(claim), "payout_started": claim_store.payout_path(claim["id"]).exists(),
            "updated_at": claim.get("updated_at"),
            "amount": claim["record"].get("amount"), "currency": claim["record"].get("currency") or "USD",
            "owner": claim["record"].get("owner"),   # masked by public_record unless it is a clear organisation
            "owner_is_organisation": claim["record"].get("owner_is_organisation"),
            "holder_name": claim["record"].get("holder_name"), "property_type": claim["record"].get("property_type"),
            "record_id": claim["record"].get("record_id"),   # our own id for the row, not the State's number
            "claimant": {k: claim["claimant"].get(k) for k in ("name", "country", "relationship")},
            "claimant_country_name": COUNTRIES.get(claim["claimant"].get("country") or "", {}).get("name")
                                     or claim["claimant"].get("country"),
            "proof": {"required": need["required"], "attached": need["attached"], "complete": need["complete"],
                      "missing": [i["payer_title"] for i in need["items"] if i["required"] and i["status"] != "attached"],
                      "documents": len(claim["documents"])},
            "proof_file": proof_summary(result),
            "match": match, "reasons": (match or {}).get("reasons", []), "doubts": (match or {}).get("doubts", []),
            "rejection_reason": claim.get("rejection_reason"),
            "payee": payee_view(claim), "approval": approval_view(claim), "line": line_view(claim),
            "approvals_withdrawn": [{"at": a.get("voided_at"), "because": a.get("voided_because")}
                                    for a in claim.get("past_approvals") or []],
            "hold": payer_hold(claim),
            "deadline": deadline_card(claim, result), "refusal": refusal_view(claim),
            "fee_card": cards.fee_card((claim.get("approval") or {}).get("fee_rule")
                                       or ins.fee_plan(claim["record"].get("amount") or 0,
                                                       (claim_store.instructions() or {}).get("rules"))),
            # What the standing instructions would mean for this claim if it were approved now.
            "fee_rule": ins.fee_plan(claim["record"].get("amount") or 0,
                                     (claim_store.instructions() or {}).get("rules")),
            "can_decide": can_decide(claim),
            "is_estate": bool(claim.get("estate")), "risk": claim.get("risk"),
            # Paid together with other approved claims (book_api.py), and opened from a holder's notice (outreach).
            "batch": claim.get("batch"), "from_notice": bool(claim.get("notice")),
            "funding": claim.get("funding", "bank"),
            "can_batch": claim["state"] == cl.APPROVED and bool(claim.get("payee")) and not claim.get("estate")
                         and not claim.get("batch")
                         and claim.get("funding", "bank") != "metal" and not claim_store.payout_path(claim["id"]).exists(),
            "can_reject": claim["state"] in cl.BEFORE_DECISION,
            "last_event": claim["history"][-1] if claim["history"] else None,
        }

    def instructions_view() -> dict:
        held = claim_store.instructions()
        rules = (held or {}).get("rules")
        return {"set": bool(held), "rules": rules, "set_at": (held or {}).get("set_at"),
                "defaults": ins.clean({}), "in_words": ins.in_words(rules), "handover": handover_view(),
                "applies_to": "Approvals given from now on. An approval already given keeps the instructions it "
                              "was given with."}

    @app.get("/api/payer/instructions", dependencies=[Depends(payer_only)])
    def get_instructions() -> dict:
        """The holder's standing instructions: inside them the payment machine acts alone and reports; outside
        them it stops and asks. None set means every change is put to a person."""
        return instructions_view()

    @app.put("/api/payer/instructions", dependencies=[Depends(payer_only)])
    def put_instructions(body: InstructionsIn) -> dict:
        raw = body.model_dump()
        try:
            wanted = None
            if raw.get("handover_date") or raw.get("document_days"):
                wanted = handover.clean({**handover_setting(), **{k: raw[k] for k in ("handover_date", "document_days")
                                                               if raw.get(k) not in (None, "")}})
            claim_store.set_instructions({k: v for k, v in raw.items() if k not in ("handover_date", "document_days")})
        except ValueError as err:
            raise HTTPException(422, str(err) + ".") from None
        if wanted is not None:
            with claim_store.lock:
                claim_store.folder.mkdir(parents=True, exist_ok=True)
                handover_path.write_text(json.dumps(wanted, indent=2, sort_keys=True))
        return instructions_view()

    @app.get("/api/payer/queue", dependencies=[Depends(payer_only)])
    def payer_queue() -> dict:
        claims = claim_store.all()
        rows = [queue_row(c) for c in claims]
        return {"claims": rows, "results": cl.results(claims), "instructions": instructions_view(),
                "handover": handover_view(), "deadline_summary": deadline_summary(rows)}

    @app.get("/api/payer/results", dependencies=[Depends(payer_only)])
    def payer_results() -> dict:
        return cl.results(claim_store.all())

    @app.post("/api/payer/claims/{claim_id}/approve", dependencies=[Depends(payer_only)])
    def approve(claim_id: str, body: ApproveIn | None = None) -> dict:
        """Approves the claim on exact terms: the amount and currency, the claimant's name, the bank account
        and the documents as they stand. Any later change to one of them withdraws the approval. For a payment
        on hold, this approves the new terms (what arrived, or what came back, and the corrected account)."""
        def go():
            with claim_store.lock:     # the claim and its payout file change together, or not at all
                return decide()

        def decide():
            before = claim_store.load(claim_id)
            if before.get("estate"):
                if body is not None and body.funding == "metal":
                    raise cl.ClaimError(409, cl.ESTATE_NOT_ON_METAL)
                raise cl.ClaimError(409, "This is an estate claim. Approve it on the estate view, where each "
                                         "heir's share is shown.")
            again = before["state"] == cl.PAYMENT_HELD
            payout = load_payout(claim_id) if again else None
            if again:
                hold = (payout.hold or {}) if payout else {}
                if "payer" not in hold.get("needs", []):
                    raise cl.ClaimError(409, "Nothing on this claim is waiting for the holder.")
                if "bank_details" in hold.get("needs", []):
                    raise cl.ClaimError(409, "The claimant has not yet corrected the bank details. The new "
                                             "approval has to cover the account that will really be paid.")

            def proof_is_ready(claim: dict) -> None:
                result = proof_of(claim, payer=True)
                if result.get("assessed") and not result["ready"]:
                    raise HTTPException(409, {"message": "This claim cannot be approved yet, because its proof "
                                                         "is not ready.", "reasons": result["reasons"]})

            need = cl.checklist(before)
            result = proof_of(before, payer=True)
            funds = payout.funds if payout else None
            covered = cl.terms(before, funds)
            what = f"{covered['amount']} {covered['currency']} to the bank account on file"
            if again:
                note = f"The holder approved the new terms: {what}."
            elif result.get("assessed"):
                note = (f"The holder approved the claim for {what}. The proof was ready: {result['satisfied']} of "
                        f"{result['required']} required items were proven by documents that were read.")
            else:
                note = (f"The holder approved the claim for {what}. Proof on file: {need['attached']} of "
                        f"{need['required']} required documents.")
            claim = claim_store.approve(claim_id, note, funds=funds, check=proof_is_ready)
            if again and payout is not None:
                # The new approval binds the instructions as they stand now, and its deadline counts from now.
                payout.instructions = claim["approval"]["terms"].get("instructions")
                payout.deadline_at = claim["approval"].get("deadline_at")
                payout.agreed("payer")
            return claim
        wanted = body.funding if body else None
        on_approval = getattr(app.state, "on_approval", None)
        if wanted == "metal" and on_approval is None:
            raise HTTPException(503, "Metal is not set up on this server, so this claim cannot be funded there.")
        approved = guard(go)
        if on_approval is not None:    # for a claim funded on Metal, the holder signs the mandate with the approval
            on_approval(approved, wanted)
        row = queue_row(claim_store.load(claim_id))
        runner.start(claim_id) if row["state"] == cl.PAYING else None    # nothing to do unless everyone has agreed
        return row

    @app.post("/api/payer/claims/{claim_id}/reject", dependencies=[Depends(payer_only)])
    def reject(claim_id: str, body: ReasonIn) -> dict:
        return queue_row(guard(lambda: claim_store.move(
            claim_id, cl.BEFORE_DECISION, cl.REJECTED, f"The holder rejected the claim: {body.reason}",
            "This claim has already been decided.", rejection_reason=body.reason)))
