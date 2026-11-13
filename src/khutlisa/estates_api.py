"""The estate routes: an owner who has died, the family, each heir's proof and the one settlement that pays them.

A claim made as an heir becomes an estate claim with `POST /api/claims/{id}/estate`. The claimant's routes take
the claim's own number, like every claim route. The holder's routes take the holder's key. Nothing here returns
the register's private record, a full bank account number, or a stored document.
"""
from __future__ import annotations

import json
import time
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from . import airwallex as awx
from . import claims as cl
from . import documents, estates, llm, payouts, proof, succession
from . import estate_settlement as es
from . import instructions as ins
from .countries import COUNTRIES
from .demo import is_demonstration

SAMPLE_FILE = Path(__file__).with_name("demonstration_estate.json")


class WordsIn(BaseModel):
    text: str = Field(min_length=2, max_length=6000)
    earlier: str = Field(default="", max_length=6000)
    question: str = Field(default="", max_length=400)


class FamilyIn(BaseModel):
    family: dict


class HeirIn(BaseModel):
    country: str | None = Field(default=None, max_length=2)
    email: str | None = Field(default=None, max_length=200)
    declared: bool | None = None


class HeirPayeeIn(BaseModel):
    """An heir's own local bank account. Which routing fields are needed depends on the currency."""
    currency: Literal["MXN", "PHP", "GBP", "JPY"]
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    account_number: str = Field(min_length=6, max_length=34)
    swift_code: str = Field(default="", max_length=11)
    sort_code: str = Field(default="", max_length=8)
    bank_code: str = Field(default="", max_length=4)
    branch_code: str = Field(default="", max_length=3)
    account_type: str = Field(default="", max_length=10)
    street_address: str = Field(min_length=3, max_length=200)
    city: str = Field(min_length=1, max_length=80)
    postcode: str = Field(default="", max_length=20)
    state: str = Field(default="", max_length=20)

    @field_validator("*", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


class PlanIn(BaseModel):
    fail_heir: str | None = Field(default=None, max_length=24)   # sandbox only: this heir's bank refuses the transfer


class ConfirmIn(BaseModel):
    plan_id: str = Field(min_length=8, max_length=60)


class ApproveIn(BaseModel):
    other_law_reason: str = Field(default="", max_length=500)
    # Asked for so the answer is plain: an estate is funded by a bank deposit, never on Metal.
    funding: Literal["bank", "metal"] | None = None

    @field_validator("other_law_reason", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


def register(app: FastAPI, claim_store: cl.ClaimStore, factory, intake_model: str = "sonnet") -> None:
    payer_only = app.state.payer_only
    private_record = app.state.private_record
    read_documents = bool(app.state.read_documents)

    def guard(fn):
        try:
            return fn()
        except cl.ClaimError as err:
            raise HTTPException(err.status, err.message) from None

    def estate_claim(claim_id: str) -> dict:
        claim = guard(lambda: claim_store.load(claim_id))
        if not claim.get("estate"):
            raise HTTPException(404, "This claim is not an estate claim.")
        return claim

    def proof_of(claim: dict) -> dict:
        return estates.build_proof(claim, private_record(claim))

    def is_ready(claim: dict) -> bool:
        return bool(claim.get("estate")) and bool(proof_of(claim)["payable"])

    reader = estates.EstateReadingRunner(claim_store, is_ready=None)
    app.state.estate_reading = reader

    # ---- what the settlement does to the claim when it comes to rest ----------------------------------------

    def settle(claim_id: str, settlement: es.Settlement) -> None:
        with claim_store.lock:
            try:
                claim = claim_store.load(claim_id)
            except cl.ClaimError:
                return
            estate = claim["estate"]
            for heir_id, info in settlement.paid_heirs().items():
                mine = estate["details"].setdefault(heir_id, {})
                if not mine.get("paid"):
                    mine["paid"] = info
                    name = next((h["name"] for h in estate["heirs"] if h["id"] == heir_id), "An heir")
                    claim["history"].append({"state": claim["state"], "at": cl.now(), "note":
                                             f"Airwallex reports {name} as paid: {info['amount']} {info['currency']} "
                                             f"(transfer {info['transfer_id']})."})
            estates._rebuild(claim)
            left = [h for h in estate["heirs"] if not h.get("paid")]
            rnd = settlement.round
            if claim["state"] == cl.PAYING and not left:
                claim_store._event(claim, cl.PAID, f"Every heir of this estate has been paid: {len(estate['heirs'])} "
                                                   "transfers, one settlement.")
            elif claim["state"] == cl.PAYING and rnd and es.idle(settlement):
                waiting = [(meta, leg) for meta, leg in settlement.legs(rnd) if leg is not None and leg.hold]
                for_holder = [m for m, leg in waiting if "payer" in leg.hold.get("needs", [])
                              or "bank_details" in leg.hold.get("needs", [])]
                held = [h for h in left if h["id"] not in settlement.live_heirs()]
                if rnd["state"] == es.HELD:
                    reason = "a different amount arrived from the one planned"
                elif for_holder:
                    reason = ("the bank refused the transfer to " + ", ".join(m["name"] for m in for_holder)
                              + ", so the terms that were approved can no longer be carried out for that heir")
                elif held and not waiting:
                    reason = ("the proven heirs were paid and the share of " + ", ".join(h["name"] for h in held)
                              + " is held until that heir is proven")
                else:
                    reason = ""
                if reason and not claim_store.void_approval(claim, reason):
                    claim_store._event(claim, cl.PAYMENT_HELD, "The settlement is on hold.")
            claim_store.save(claim)

    runner = es.EstateRunner(claim_store, factory, after=settle,
                             pause=float(getattr(app.state.payouts, "pause", 1.0)))
    app.state.estates = runner

    # ---- indicative amounts: what a share would become in the heir's currency today ---------------------------

    rates: dict[str, tuple[Decimal, float]] = {}

    def per_dollar(currency: str) -> Decimal | None:
        held = rates.get(currency)
        if held and time.time() - held[1] < 60:
            return held[0]
        try:
            client, _ = factory()
        except awx.CredentialsError:
            return None
        try:
            got = client.indicative_rate("USD", currency)
            rate = Decimal(str(got.get("rate") or 0))
            if rate <= 0:
                return None
            one = 1 / rate if str(got.get("currency_pair") or "").endswith("USD") else rate
            rates[currency] = (one, time.time())
            return one
        except Exception:        # an indicative figure is never worth failing the view for
            return held[0] if held else None
        finally:
            client.close()

    # ---- views ---------------------------------------------------------------------------------------------------

    def payee_view(payee: dict | None) -> dict | None:
        if not payee:
            return None
        bank = payee["beneficiary"]["beneficiary"]["bank_details"]
        return {"currency": payee["currency"], "account_name": bank.get("account_name"),
                "account_number": payouts._mask_account(bank.get("account_number") or ""),
                "bank_country": bank.get("bank_country_code"), "set_at": payee.get("set_at"),
                "checked_by": payee.get("checked_by")}

    def tree(claim: dict, owed: dict[str, int], by_proof: dict[str, dict]) -> list[dict]:
        """The family as rows for drawing: the owner at the top, then each relative with the person they hang
        from. An heir's row carries the fraction, the amount and the state of their proof."""
        estate = claim["estate"]
        family = estate["family"]
        heirs = {h["id"]: h for h in estate["heirs"]}
        nodes = [{"id": "owner", "parent": None, "kind": "owner", "name": family["decedent"]["name"], "alive": False,
                  "died_on": family["decedent"]["died_on"]}]

        def add(person: dict, parent: str, kind: str) -> None:
            heir = heirs.get(person["id"])
            row = {"id": person["id"], "parent": parent, "kind": kind, "name": person.get("name") or "",
                   "alive": person.get("alive"), "country": person.get("country") or ""}
            if heir:
                currency = (heir.get("payee") or {}).get("currency") or es.BY_COUNTRY.get(heir.get("country") or "")
                one = per_dollar(currency) if currency else None
                usd = Decimal(owed[heir["id"]]) / 100
                proven = by_proof.get(heir["id"], {})
                row.update({"heir": True, "relation": heir["relation"], "share": heir["share"],
                            "amount_usd": f"{usd:.2f}", "country": heir.get("country") or row["country"],
                            "currency": currency,
                            "indicative_local": one and {"amount": str(awx.money(usd * one, currency)),
                                                         "currency": currency},
                            "steps": heir.get("steps") or [], "proven": bool(proven.get("proven")),
                            "payable": bool(proven.get("payable")), "missing": len(proven.get("missing") or []),
                            "paid": heir.get("paid")})
            nodes.append(row)
            for child in person.get("children") or []:
                add(child, person["id"], "child")

        if family.get("spouse"):
            add(family["spouse"], "owner", "spouse")
        for person in family["children"]:
            add(person, "owner", "child")
        for person in family["parents"]:
            add(person, "owner", "parent")
        for person in family["siblings"]:
            add(person, "owner", "sibling")
        for row in family["named_shares"]:
            add(row, "owner", "named")
        return nodes

    def approval_view(claim: dict) -> dict | None:
        approval = claim.get("approval")
        if not approval:
            return None
        t = approval["terms"]
        rules = t.get("instructions")
        return {"at": approval["at"], "amount": t["amount"], "currency": t["currency"],
                "shares": (t.get("estate") or {}).get("shares"), "proven": (t.get("estate") or {}).get("proven"),
                "documents": len(t["documents"]), "terms_hash": approval["terms_hash"],
                "replaces_earlier_approval": approval.get("replaces_earlier_approval", False),
                "instructions": rules and {"rules": rules, "in_words": ins.in_words(rules)},
                "deadline_at": approval.get("deadline_at")}

    def estate_view(claim: dict, payer: bool = False) -> dict:
        estate = claim["estate"]
        result = proof_of(claim)
        by_proof = {h["id"]: h for h in result["heirs"]}
        owed = es.entitlements(claim["record"].get("amount") or 0, estate["heirs"]) if estate["heirs"] else {}
        succ = estate.get("succession") or {}
        settlement = runner.load(claim["id"])
        heirs = []
        for heir in estate["heirs"]:
            mine = by_proof[heir["id"]]
            heirs.append({**mine, "email": heir.get("email") or "", "payee": payee_view(heir.get("payee")),
                          "entitlement": es.dollars(owed[heir["id"]]),
                          "country_name": estates.country_name(heir.get("country") or ""),
                          "currency": (heir.get("payee") or {}).get("currency")
                                      or es.BY_COUNTRY.get(heir.get("country") or ""),
                          "can_be_paid_here": (heir.get("country") or "") in es.BY_COUNTRY})
        rules = (claim_store.instructions() or {}).get("rules")
        flags = succ.get("flags") or []
        return {
            "claim_id": claim["id"], "state": claim["state"], "sample": is_demonstration(claim["record"].get("source")),
            "record": claim["record"], "claimant": {"name": claim["claimant"]["name"]},
            "amount": f"{Decimal(str(claim['record'].get('amount') or 0)):.2f}", "currency": "USD",
            "family": estate["family"], "tree": tree(claim, owed, by_proof),
            "succession": {"computed": bool(succ.get("computed")), "basis": succ.get("basis"),
                           "steps": succ.get("steps") or [], "flags": flags, "refusal": succ.get("refusal"),
                           "needs_person": bool(succ.get("needs_person"))},
            "question": estates.next_question(estate["family"], estate.get("asked")),
            "intake": {"words": estate.get("words") or "", "language": estate.get("language") or "",
                       "english": estate.get("english") or ""},
            "heirs": heirs, "estate_proof": result["estate"], "proof_ready": result["ready"],
            "payable": result["payable"], "held": result["held"],
            "remaining_risk": result["remaining_risk"], "decided_by": result["decided_by"],
            "documents": [{**{k: v for k, v in d.items() if k not in ("stored_as", "sha256", "reading")},
                           "status": (d.get("reading") or {}).get("status"),
                           "summary": (d.get("reading") or {}).get("summary"),
                           "people": (d.get("reading") or {}).get("people") or [],
                           "agreement": ((d.get("reading") or {}).get("agreement") or {}).get("status")}
                          for d in claim["documents"]],
            "document_kinds": [{"kind": k, "label": documents.KINDS[k]} for k in estates.ESTATE_KINDS],
            "approval": approval_view(claim),
            "approvals_withdrawn": [{"at": a.get("voided_at"), "because": a.get("voided_because")}
                                    for a in claim.get("past_approvals") or []],
            "other_law": {"flag": next((f for f in flags if f["key"] == "other_law"), None),
                          "acknowledged": estate.get("other_law")},
            "fee_rule": {"small_claim_usd": rules and rules["small_claim_usd"], "words": es.FEE_RULE_WORDS},
            "rounding_rule": es.ROUNDING_RULE,
            "declaration": {"points": estates.DECLARATION, "note": estates.SIMULATED_DECLARATION},
            "corridors": [{"currency": c, "country": row["country"], "place": row["place"]}
                          for c, row in es.CORRIDORS.items()],
            "settlement": es.view(settlement, running=runner.running(claim["id"]),
                                  problem=runner.problems.get(claim["id"])),
            "history": claim["history"][-12:],
            "risk": {"held": bool((claim.get("risk") or {}).get("held"))} if payer else None,
        }

    # ---- the claimant's routes -----------------------------------------------------------------------------------

    @app.get("/api/estate/sample")
    def sample() -> dict:
        """The invented family used to show the journey: their words, their bank details and their documents."""
        return json.loads(SAMPLE_FILE.read_text(encoding="utf-8")) if SAMPLE_FILE.exists() else {}

    @app.post("/api/claims/{claim_id}/estate")
    def open_estate(claim_id: str) -> dict:
        return estate_view(guard(lambda: estates.open_estate(claim_store, claim_id)))

    @app.get("/api/claims/{claim_id}/estate")
    def get_estate(claim_id: str) -> dict:
        return estate_view(estate_claim(claim_id))

    @app.post("/api/claims/{claim_id}/estate/intake")
    def intake_words(claim_id: str, body: WordsIn) -> dict:
        """The claimant says, in their own language, who has died and who the family is. A model turns the words
        into the family structure; the shares are then worked out in code, and one follow-up question is asked
        for the first fact the rule still needs."""
        estate_claim(claim_id)
        try:
            said = estates.understand_family(body.text, body.earlier, body.question, model=intake_model)
        except llm.ModelUnavailable:
            raise HTTPException(503, "The language model is not available on this server, so the words could not "
                                     "be read. Fill in the family below instead.") from None
        except Exception:
            raise HTTPException(502, "The words could not be read this time. Try again, or fill in the family "
                                     "below.") from None
        claim = guard(lambda: estates.set_family(
            claim_store, claim_id, said["family"],
            {"words": said["full_transcript"], "language": said["language"], "english": said["english"],
             "asked": said["asked"]}))
        return estate_view(claim)

    @app.put("/api/claims/{claim_id}/estate/family")
    def put_family(claim_id: str, body: FamilyIn) -> dict:
        """The family as the claimant corrected it by hand."""
        return estate_view(guard(lambda: estates.set_family(claim_store, claim_id, body.family, {"asked": None})))

    @app.put("/api/claims/{claim_id}/estate/heirs/{heir_id}")
    def put_heir(claim_id: str, heir_id: str, body: HeirIn) -> dict:
        country = body.country.upper() if body.country else None
        if country is not None and country not in COUNTRIES:
            raise HTTPException(422, "Choose a country from the list.")
        email = guard(lambda: estates.clean_email(body.email)) if body.email is not None else None
        return estate_view(guard(lambda: estates.set_heir(claim_store, claim_id, heir_id, country=country,
                                                          email=email, declared=body.declared)))

    def checked_beneficiary(heir: dict, body: HeirPayeeIn) -> tuple[dict, str]:
        holder = f"{body.first_name} {body.last_name}"
        if proof.compare_names(heir["name"], holder) != "full":
            raise HTTPException(422, f"The bank account is in the name {holder}, and this heir is {heir['name']}. "
                                     "An heir is paid only into an account in their own name.")
        try:
            beneficiary = es.beneficiary(
                body.currency, body.first_name, body.last_name, body.account_number.replace(" ", ""),
                street_address=body.street_address, city=body.city, postcode=body.postcode, state=body.state,
                swift_code=body.swift_code.upper(), sort_code=body.sort_code, bank_code=body.bank_code,
                branch_code=body.branch_code, account_type=body.account_type)
        except ValueError as err:
            text = str(err)
            raise HTTPException(422, text[:1].upper() + text[1:] + ".") from None
        try:
            client, _ = factory()
        except awx.CredentialsError:
            return beneficiary, "Khutlisa's own checks (the Airwallex keys are not set up on this server)"
        try:
            schema = client.beneficiary_schema(es.CORRIDORS[body.currency]["country"], body.currency)
            problems = awx.schema_problems(schema, beneficiary)
            if problems:
                raise HTTPException(422, "The bank details do not fit what Airwallex requires: "
                                    + "; ".join(problems) + ".")
            client.validate_beneficiary(beneficiary)
        except awx.AirwallexError as err:
            if err.status == 400:
                raise HTTPException(422, "Airwallex did not accept the bank details: "
                                         f"{(err.message or err.code or 'no reason given')[:300]}") from None
            raise HTTPException(502, payouts.explain(err)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Airwallex could not be reached. Try again in a moment.") from None
        finally:
            client.close()
        return beneficiary, "Airwallex's validation for this country and currency"

    @app.put("/api/claims/{claim_id}/estate/heirs/{heir_id}/payee")
    def put_heir_payee(claim_id: str, heir_id: str, body: HeirPayeeIn) -> dict:
        """An heir's own bank account. After a refused transfer this is where the corrected account goes; the
        money that came back is already in that heir's currency, so the currency cannot change then."""
        claim = estate_claim(claim_id)
        heir = next((h for h in claim["estate"]["heirs"] if h["id"] == heir_id), None)
        if heir is None:
            raise HTTPException(404, "There is no such heir on this estate.")
        beneficiary, checked_by = checked_beneficiary(heir, body)
        with claim_store.lock:
            settlement = runner.load(claim_id)
            leg = meta = None
            if settlement and settlement.round and heir_id in settlement.round["legs"]:
                meta, leg = settlement.round["legs"][heir_id], settlement.leg(settlement.round, heir_id)
            waiting = leg is not None and leg.hold and "bank_details" in leg.hold.get("needs", [])
            if leg is not None and not waiting:
                raise HTTPException(409, "This heir's payment is already on its way or paid, so the account "
                                         "cannot be changed now.")
            if waiting and body.currency != leg.target_currency:
                raise HTTPException(409, f"The money for this heir is already held in {leg.target_currency}, so "
                                         "the corrected account must take that currency.")
            claim = guard(lambda: estates.set_heir(claim_store, claim_id, heir_id, payee={
                "currency": body.currency, "beneficiary": beneficiary, "checked_by": checked_by}))
            if waiting:
                leg.beneficiary = beneficiary
                meta["beneficiary"] = beneficiary
                settlement.save()
                leg.agreed("bank_details")
        return estate_view(claim)

    @app.post("/api/claims/{claim_id}/estate/documents", status_code=201)
    async def add_document(claim_id: str, kind: str = Form(...), file: UploadFile = File(...)) -> dict:
        """A document for the estate: the owner's death certificate, a birth or marriage certificate that shows
        a relationship, a will or court order, or an heir's photo identification. It is read twice, with the
        part each named person plays in it."""
        estate_claim(claim_id)
        if kind not in estates.ESTATE_KINDS:
            raise HTTPException(422, "Choose what kind of document this is.")
        data = await file.read(documents.MAX_BYTES + 1)
        claim = guard(lambda: claim_store.add_document(claim_id, kind, file.filename or "", data))
        if read_documents:
            reader.start(claim_id, claim["documents"][-1]["id"])
        return estate_view(claim)

    # ---- the settlement --------------------------------------------------------------------------------------------

    def ready_to_pay(claim: dict) -> None:
        if not claim.get("approval"):
            raise HTTPException(409, "The settlement can start only after the holder has approved the estate.")
        holds, why = cl.approval_holds(claim)
        result = proof_of(claim)
        approved = (claim["approval"]["terms"].get("estate") or {}).get("proven") or {}
        if holds and any(approved.get(h["id"]) and not h["proven"] and not h["paid"] for h in result["heirs"]):
            holds, why = False, "the proof for an heir changed after the approval"
        if not holds:
            with claim_store.lock:
                fresh = claim_store.load(claim["id"])
                if claim_store.void_approval(fresh, why):
                    claim_store.save(fresh)
            raise HTTPException(409, f"The holder's approval no longer holds, because {why}. The holder has to "
                                     "approve the estate again.")
        guard(lambda: claim_store.check_property_is_free(claim))
        guard(lambda: claim_store.check_may_pay(claim))

    @app.post("/api/claims/{claim_id}/estate/settlement/plan")
    def plan(claim_id: str, body: PlanIn | None = None) -> dict:
        """Writes the settlement plan for an approved estate: who is paid now, who is held, what the holder
        sends, and for each heir the route, the locked rate and the amount to expect. It takes quotes from
        Airwallex and moves no money."""
        body = body or PlanIn()
        claim = estate_claim(claim_id)
        if claim["state"] not in (cl.APPROVED, cl.PAYING):
            raise HTTPException(409, "The settlement can start only after the holder has approved the estate.")
        ready_to_pay(claim)
        try:
            client, simulator = factory()
        except awx.CredentialsError:
            raise HTTPException(503, payouts.NO_CREDENTIALS) from None
        try:
            with claim_store.lock:
                settlement = es.Settlement.open(runner.path(claim_id), claim_id)
                if runner.running(claim_id) or not es.idle(settlement):
                    return estate_view(claim)             # a round is under way: there is nothing to plan
                approval = claim["approval"]
                made = guard(lambda: es.make_plan(
                    claim, proof_of(claim), client, settlement, rules=approval["terms"].get("instructions"),
                    deadline_at=approval.get("deadline_at"), fail_heir=body.fail_heir,
                    simulator_ready=simulator is not None))
                settlement.rounds = [r for r in settlement.rounds if r["state"] != es.PLANNED]
                settlement.rounds.append({"n": made["round"], "state": es.PLANNED, "plan": made, "legs": {},
                                          "events": [], "problems": {}})
                if made.get("on_what_arrived"):     # the stopped round stays the current one; keep the plan beside it
                    settlement.rounds.pop()
                    settlement.round["replan"] = made
                settlement.save()
        except awx.AirwallexError as err:
            raise HTTPException(502, payouts.explain(err)) from None
        except httpx.HTTPError:
            raise HTTPException(502, "Airwallex could not be reached. Try again in a moment.") from None
        finally:
            client.close()
        return estate_view(claim)

    @app.post("/api/claims/{claim_id}/estate/settlement/confirm")
    def confirm(claim_id: str, body: ConfirmIn) -> dict:
        """The family agrees to the plan they were shown, by its id. The round then starts with the holder's one
        deposit. In this build whoever holds the claim's number answers for the family."""
        claim = estate_claim(claim_id)
        with claim_store.lock:
            settlement = runner.load(claim_id)
            rnd = settlement.round if settlement else None
            made = None
            if rnd and rnd["state"] == es.PLANNED:
                made = rnd["plan"]
            elif rnd and rnd["state"] == es.HELD:
                made = rnd.get("replan")
            if not made:
                raise HTTPException(409, "There is no settlement plan to agree to yet.")
            if made["id"] != body.plan_id:
                raise HTTPException(409, "The plan has changed since you saw it. Read the new plan and agree to "
                                         "that one.")
            ready_to_pay(claim)
            if any(awx._parse_time(leg["quote"].get("valid_to_at")) and
                   time.time() > awx._parse_time(leg["quote"]["valid_to_at"]) - awx.QUOTE_MARGIN for leg in made["legs"]):
                raise HTTPException(409, "A rate in this plan is no longer locked. Ask for the plan again.")
            approval = claim["approval"]
            try:
                client, simulator = factory()
            except awx.CredentialsError:
                raise HTTPException(503, payouts.NO_CREDENTIALS) from None
            client.close()
            es.start_round(settlement, claim, made, rules=approval["terms"].get("instructions"),
                           deadline_at=approval.get("deadline_at"), simulator_ready=simulator is not None)
            places = sorted({leg["place"] for leg in made["legs"]})
            note = (f"The family agreed to the settlement plan. {len(made['legs'])} heirs are being paid on the "
                    f"Airwallex sandbox, in {', '.join(places)}."
                    + (f" The share of {', '.join(h['name'] for h in made['held'])} is held." if made["held"] else ""))
            if claim["state"] == cl.APPROVED:
                claim = guard(lambda: claim_store.move(claim_id, (cl.APPROVED,), cl.PAYING, note,
                                                       "The settlement can start only after the holder has approved."))
            else:
                claim = claim_store.load(claim_id)
                claim["history"].append({"state": claim["state"], "at": cl.now(), "note": note})
                claim_store.save(claim)
        runner.start(claim_id)
        return estate_view(claim)

    @app.post("/api/claims/{claim_id}/estate/settlement/resume")
    def resume(claim_id: str) -> dict:
        """Carries on with a settlement that stopped waiting on Airwallex. The same request ids are used, so
        nothing is made twice."""
        claim = estate_claim(claim_id)
        with claim_store.lock:
            settlement = runner.load(claim_id)
            if settlement is not None and settlement.round and settlement.round.get("problems") \
                    and not runner.running(claim_id):
                settlement.round["problems"] = {}      # an heir's payout that gave up on errors is tried again
                settlement.save()
        if settlement is not None and not es.idle(settlement):
            runner.start(claim_id)
        return estate_view(claim)

    @app.post("/api/claims/{claim_id}/estate/settlement/heirs/{heir_id}/agree")
    def agree(claim_id: str, heir_id: str) -> dict:
        """The family agrees to a changed amount for one heir, where the change was beyond the tolerance."""
        claim = estate_claim(claim_id)
        with claim_store.lock:
            settlement = runner.load(claim_id)
            leg = settlement.leg(settlement.round, heir_id) if settlement and settlement.round else None
            needs = (leg.hold or {}).get("needs", []) if leg else []
            if "claimant" not in needs:
                raise HTTPException(409, "Nothing for this heir is waiting for the family.")
            if "bank_details" in needs or "payer" in needs:
                raise HTTPException(409, "The corrected bank account and the holder's approval come first.")
            guard(lambda: claim_store.check_may_pay(claim))
            leg.agreed("claimant")
        runner.start(claim_id)
        return estate_view(claim)

    # ---- the holder's routes ---------------------------------------------------------------------------------------

    def row(claim: dict) -> dict:
        estate = claim["estate"]
        result = proof_of(claim)
        return {"id": claim["id"], "state": claim["state"], "created_at": claim["created_at"],
                "sample": is_demonstration(claim["record"].get("source")), "owner": claim["record"].get("owner"),
                "holder_name": claim["record"].get("holder_name"), "amount": claim["record"].get("amount"),
                "heirs": [{"name": h["name"], "relation": h["relation"], "share": h["share"],
                           "country": h.get("country"), "proven": h["proven"], "paid": bool(h["paid"])}
                          for h in result["heirs"]],
                "computed": bool((estate.get("succession") or {}).get("computed")),
                "other_law": bool((estate.get("succession") or {}).get("needs_person")),
                "payable": len(result["payable"]), "held": len(result["held"]), "approved": bool(claim.get("approval"))}

    @app.get("/api/payer/estates", dependencies=[Depends(payer_only)])
    def payer_estates() -> dict:
        return {"estates": [row(c) for c in claim_store.all() if c.get("estate")]}

    @app.get("/api/payer/estates/{claim_id}", dependencies=[Depends(payer_only)])
    def payer_estate(claim_id: str) -> dict:
        return estate_view(estate_claim(claim_id), payer=True)

    @app.post("/api/payer/estates/{claim_id}/approve", dependencies=[Depends(payer_only)])
    def approve(claim_id: str, body: ApproveIn | None = None) -> dict:
        """Approves the estate on exact terms: the amount, the family as described, each heir's share as a
        fraction, each heir's bank account, which heirs are proven, and every document. A change to any of them
        withdraws the approval. Heirs who are proven and have given an account are paid; the others are held.
        After a refused transfer, this approves the corrected account for that heir."""
        body = body or ApproveIn()
        if body.funding == "metal":
            raise HTTPException(409, cl.ESTATE_NOT_ON_METAL)
        resumed = []
        with claim_store.lock:
            claim = estate_claim(claim_id)
            estate = claim["estate"]
            succ = estate.get("succession") or {}
            if not succ.get("computed"):
                why = (succ.get("refusal") or {}).get("reason") or "the shares have not been worked out"
                raise HTTPException(409, f"This estate cannot be approved yet: {why}")
            again = claim["state"] == cl.PAYMENT_HELD
            if not again and claim["state"] not in cl.BEFORE_DECISION:
                raise HTTPException(409, "This estate has already been decided.")
            result = proof_of(claim)
            claim = estates.record_proven(claim_store, claim_id, result)
            estate = claim["estate"]
            if not result["estate"]["ready"]:
                raise HTTPException(409, {"message": "This estate cannot be approved yet, because its proof is "
                                                     "not ready.",
                                          "reasons": [p for i in result["estate"]["items"] for p in i["problems"]]})
            settlement = runner.load(claim_id)
            waiting = []
            if settlement and settlement.round:
                for meta, leg in settlement.legs(settlement.round):
                    needs = (leg.hold or {}).get("needs", []) if leg else []
                    if "payer" in needs and "bank_details" in needs:
                        raise HTTPException(409, f"{meta['name']} has not yet corrected the bank account. The new "
                                                 "approval has to cover the account that will really be paid.")
                    if "payer" in needs:
                        waiting.append((meta, leg))
            stopped = bool(settlement and settlement.round and settlement.round["state"] == es.HELD)
            live = settlement.live_heirs() if settlement else set()
            payable = [h for h in result["heirs"] if h["payable"] and h["id"] not in live]
            if not payable and not waiting and not stopped:
                raise HTTPException(409, {"message": "No heir of this estate can be paid yet.",
                                          "reasons": [f"{h['name']}: {h['missing'][0]}" for h in result["heirs"]
                                                      if h["missing"] and not h["paid"]][:6]})
            flag = next((f for f in succ.get("flags") or [] if f["key"] == "other_law"), None)
            if flag:
                if len(body.other_law_reason) < 10 and not estate.get("other_law"):
                    raise HTTPException(409, "The owner did not live in California at death, so other law may "
                                             "apply. Khutlisa computed California's default and has not decided "
                                             "which law governs. To approve, write down why the California shares "
                                             "are being used.")
                if len(body.other_law_reason) >= 10:
                    estate["other_law"] = {"reason": body.other_law_reason, "at": cl.now()}
                    claim["history"].append({"state": claim["state"], "at": cl.now(), "note":
                                             "The holder recorded why California's shares are used although the "
                                             f"owner lived elsewhere: {body.other_law_reason}"})
                    claim_store.save(claim)
            held = [h for h in result["heirs"] if not h["payable"] and not h["paid"] and h["id"] not in live]
            shares = ", ".join(f"{h['name']} {h['share']}" for h in result["heirs"])
            if waiting:
                note = ("The holder approved the corrected bank account for "
                        + ", ".join(m["name"] for m, _ in waiting) + ".")
            else:
                note = (f"The holder approved the estate on these shares: {shares}. "
                        f"{len(payable)} {'heir is' if len(payable) == 1 else 'heirs are'} proven and can be paid"
                        + (f"; the share of {', '.join(h['name'] for h in held)} is held until proven." if held else "."))

            def still_the_same(now: dict) -> None:
                if cl.digest(cl.estate_terms(now)) != cl.digest(cl.estate_terms(claim)):
                    raise cl.ClaimError(409, "The estate changed while it was being approved. Look at it again.")

            claim = guard(lambda: claim_store.approve(claim_id, note, check=still_the_same))
            for meta, leg in waiting:
                leg.instructions = claim["approval"]["terms"].get("instructions")
                leg.deadline_at = claim["approval"].get("deadline_at")
                leg.agreed("payer")
                resumed.append(meta["heir"])
        if resumed:
            runner.start(claim_id)
        return estate_view(claim, payer=True)
