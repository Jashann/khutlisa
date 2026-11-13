"""The routes for the whole book and for a batch.

  GET  /api/book/holders        the holders whose book can be opened, largest first, or those matching `q`
  GET  /api/book                the plan for one holder's book under the four inputs given (or the saved ones)
  POST /api/payer/batches       write a demonstration batch from a plan; moves no money
  GET  /api/payer/batches[/id]  the batches, or one of them as the "Batch" screen shows it
  POST /api/payer/batches/{id}/approve                 the holder approves the exact terms, which starts it
  POST /api/payer/batches/{id}/items/{n}/account       the demonstration owner gives another bank account
  POST /api/payer/batches/{id}/items/{n}/approve       the holder approves that account
  POST /api/payer/batches/{id}/items/{n}/agree         the demonstration owner agrees to the smaller amount
  POST /api/payer/batches/claims  write a batch of claims from the holder's own queue, each already approved

The plan routes read prepared files only (data/books.parquet and airwallex_corridors.json) and move nothing. The
batch routes need the holder's key, like every route that decides something for the holder.
"""
from __future__ import annotations

import hmac
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import airwallex as awx
from . import batch as bt
from . import book as bk
from . import claims as cl
from . import corridors as co
from . import handover as ho
from . import instructions as ins
from .payouts import NO_CREDENTIALS, explain

PAYER_KEY_HEADER = "X-Payer-Key"
NO_BOOKS = "The books have not been made yet. Run scripts/make_books.py (see the README)."
NO_CORRIDORS = ("Airwallex has not been asked about the corridors yet. Run scripts/discover_corridors.py (see the "
                "README).")


class BatchIn(BaseModel):
    holder: str = Field(min_length=1, max_length=200)
    small_claim_usd: str | None = Field(default=None, max_length=20)
    tolerance_percent: str | None = Field(default=None, max_length=20)
    handover_date: str | None = Field(default=None, max_length=20)
    document_days: int | None = None
    refuse: list[int] | None = Field(default=None, max_length=9)


class ClaimsBatchIn(BaseModel):
    claim_ids: list[str] = Field(min_length=2, max_length=50)


def register(app: FastAPI, claim_store: cl.ClaimStore, runner: bt.BatchRunner, factory, *, payer_key: str = "",
             books_path: Path | None = None, corridors_path: Path | None = None, counted=None) -> None:
    books_path = Path(books_path or bk.BOOKS_PATH)
    corridors_path = Path(corridors_path or co.FILE)

    def payer_only(key: str | None = Header(default=None, alias=PAYER_KEY_HEADER)) -> None:
        if not payer_key:
            raise HTTPException(401, "The holder's view is locked: no key for it is set on this server. Set "
                                     "KHUTLISA_PAYER_KEY and start it again.")
        if not key or not hmac.compare_digest(key.encode(), payer_key.encode()):
            raise HTTPException(401, "The holder's key is missing or wrong.")

    def saved_inputs() -> dict:
        """The holder's own limits and handover date as they are saved, or the defaults."""
        rules = (claim_store.instructions() or {}).get("rules") or ins.clean({})
        path = claim_store.folder / "holder_handover.json"
        setting: dict = {}
        if path.exists():
            import json
            try:
                setting = json.loads(path.read_text())
            except ValueError:
                setting = {}
        setting = ho.clean({k: setting.get(k) for k in ("handover_date", "document_days")})
        return {"tolerance_percent": rules["tolerance_percent"], "small_claim_usd": rules["small_claim_usd"],
                "handover_date": setting["handover_date"], "document_days": setting["document_days"]}

    def ready() -> tuple[bk.Books, dict]:
        books = bk.books(books_path)
        if books is None:
            raise HTTPException(503, NO_BOOKS)
        found = co.load(corridors_path)
        if found is None:
            raise HTTPException(503, NO_CORRIDORS)
        return books, found

    def planned(holder: str, raw: dict) -> tuple[dict, dict, dict]:
        books, found = ready()
        got = books.get(holder)
        if got is None:
            raise HTTPException(404, "There is no holder of that name whose book can be opened. Choose one from "
                                     "the list.")
        line, claims = got
        base = saved_inputs()
        try:
            wanted = bk.clean_inputs({**base, **{k: v for k, v in raw.items() if v not in (None, "")}})
        except ValueError as err:
            raise HTTPException(422, str(err) + ".") from None
        plan = bk.plan(line, claims, found, wanted)
        baseline = plan if wanted == bk.clean_inputs(base) else bk.plan(line, claims, found, base)
        return plan, baseline, found

    @app.get("/api/book/holders", dependencies=[Depends(counted)] if counted else [])
    def book_holders(q: str = Query(default="", max_length=80)) -> dict:
        """The holders whose book can be opened: organisations only, largest first. With `q`, those whose name
        contains it. A holder whose name could be a person's is counted in every total and never listed."""
        books = bk.books(books_path)
        if books is None:
            raise HTTPException(503, NO_BOOKS)
        found = co.load(corridors_path)
        return {"top": books.top(12), "matches": books.find(q) if q.strip() else [], "query": q.strip(),
                "corridors_ready": found is not None, "discovered_at": (found or {}).get("fetched_at")}

    @app.get("/api/book", dependencies=[Depends(counted)] if counted else [])
    def book_plan(holder: str = Query(..., min_length=1, max_length=200),
                  small_claim_usd: str | None = Query(default=None, max_length=20),
                  tolerance_percent: str | None = Query(default=None, max_length=20),
                  handover_date: str | None = Query(default=None, max_length=20),
                  document_days: int | None = Query(default=None)) -> dict:
        """The plan for one holder's book. Every figure is computed in code from the holder's lines in
        California's public file and from what the Airwallex sandbox answered. Nothing is locked or moved."""
        plan, baseline, _ = planned(holder, {"small_claim_usd": small_claim_usd, "tolerance_percent": tolerance_percent,
                                             "handover_date": handover_date, "document_days": document_days})
        out = bk.without_cents(plan)
        out["baseline"] = {"inputs": baseline["inputs"], "totals": baseline["totals"],
                           "work": len(baseline["order"]["work"])}
        out["changes"] = bk.changes(baseline, plan)
        out["slice"] = bt.choose_slice(plan)
        return out

    # ---- a batch -------------------------------------------------------------------------------------------

    def load(batch_id: str) -> bt.Batch:
        try:
            return runner.load(batch_id)
        except ValueError as err:
            raise HTTPException(404, str(err)) from None

    def shown(batch: bt.Batch) -> dict:
        return bt.view(batch, running=runner.running(batch.batch_id), problem=runner.problems.get(batch.batch_id))

    @app.post("/api/payer/batches", status_code=201, dependencies=[Depends(payer_only)])
    def make_batch(body: BatchIn) -> dict:
        """Write a demonstration batch from the plan: one invented owner in each of up to nine corridors the plan
        works, with example bank details checked against Airwallex's live schema for the country. No money moves
        until the holder approves."""
        plan, _, found = planned(body.holder, body.model_dump(exclude={"holder", "refuse"}))
        chosen = bt.choose_slice(plan)
        if len(chosen) < 2:
            raise HTTPException(409, "This plan works fewer than two corridors for which a demonstration owner "
                                     "exists, so there is no batch to run.")
        try:
            client, _ = factory()
        except awx.CredentialsError:
            raise HTTPException(503, NO_CREDENTIALS) from None
        rules = ins.clean({"tolerance_percent": plan["inputs"]["tolerance_percent"],
                           "small_claim_usd": plan["inputs"]["small_claim_usd"]})
        if body.refuse is None:      # by default: the largest payment and the smallest, so both outcomes can be seen
            order = sorted(range(len(chosen)), key=lambda i: float(chosen[i]["claim_usd"]))
            refuse = tuple(sorted({order[-1] + 1, order[0] + 1}))
        else:
            refuse = tuple(n for n in body.refuse if 1 <= n <= len(chosen))
        try:
            checked = []
            for row in chosen:      # the example bank details must fit the schema Airwallex gives for the corridor today
                payload = bt.example_beneficiary(row["country"], row["currency"], row["method"])
                schema = client.beneficiary_schema(row["country"], row["currency"], row["method"])
                problems = awx.schema_problems(schema, payload)
                if not problems:
                    client.validate_beneficiary(payload)
                checked.append({"country": row["country"], "fields": len(schema.get("fields") or []), "problems": problems})
            bad = [c for c in checked if c["problems"]]
            if bad:
                raise HTTPException(409, "The example bank details no longer fit Airwallex's schema for "
                                         + ", ".join(c["country"] for c in bad) + ".")
        except (awx.AirwallexError, httpx.HTTPError) as err:
            raise HTTPException(502, explain(err)) from None
        finally:
            client.close()
        batch = bt.new_batch(runner.folder, plan["holder"], chosen, plan, rules, refuse=refuse)
        for item, check in zip(batch.items, checked):
            item["schema_fields"] = check["fields"]
        batch.save()
        return shown(batch)

    # ---- a batch of claims from the holder's own queue ----

    def claim_problem(claim_id: str, n: int, approving: bool) -> str | None:
        """Why the claim behind payment `n` may not be paid now, or None. The same checks as a single payment:
        the approval still holds on its exact terms, nothing else claims the property, and nothing another
        module adds (rings.py) holds the claim. Before the batch is approved the approval checks run as well."""
        try:
            claim = claim_store.load(claim_id)
        except cl.ClaimError:
            return f"Payment {n}: its claim is no longer there."
        holds, why = cl.approval_holds(claim)
        if not holds:
            return f"Payment {n}: the holder's approval of its claim no longer holds, because {why}."
        try:
            claim_store.check_property_is_free(claim)
            if approving:
                for extra in claim_store.approval_checks:
                    extra(claim)
            claim_store.check_may_pay(claim)
        except cl.ClaimError as err:
            return f"Payment {n}: {err.message}"
        return None

    def queue_checks(batch: bt.Batch) -> str | None:
        for item in batch.items:
            if item.get("claim_id"):
                problem = claim_problem(item["claim_id"], item["n"], approving=False)
                if problem:
                    return problem + " Nothing was sent for this batch."
        return None

    def carry_to_claims(batch: bt.Batch) -> None:
        """What happened to each payment, carried over to its claim in the queue: paid, or the batch stopped
        before any money left the holder (the claim goes back to approved, so it can be paid another way)."""
        if not bt.claim_ids(batch):
            return
        with claim_store.lock:
            for item in batch.items:
                if not item.get("claim_id"):
                    continue
                try:
                    claim = claim_store.load(item["claim_id"])
                except cl.ClaimError:
                    continue
                mine = (claim.get("batch") or {}).get("id") == batch.batch_id
                payout = batch.payout(item["n"])
                if mine and batch.deposit_id and claim["state"] == cl.APPROVED:
                    # The claim stays approved until the holder's deposit for the batch has arrived, so a hold
                    # that appears before then still stops it (rings.py counts a paying claim as money gone).
                    claim_store._event(claim, cl.PAYING, f"The holder's deposit for batch {batch.batch_id} arrived; "
                                                         f"payment {item['n']} is on its way.")
                    claim_store.save(claim)
                if payout is not None and payout.state == awx.PAID and claim["state"] == cl.PAYING:
                    claim_store._event(claim, cl.PAID, f"Airwallex reports transfer {payout.transfer_id} as paid: "
                                                       f"{payout.target_amount} {payout.target_currency}, as payment "
                                                       f"{item['n']} of batch {batch.batch_id}.")
                    claim_store.save(claim)
                elif mine and batch.state == bt.STOPPED and not batch.deposit_id and claim["state"] == cl.APPROVED:
                    claim["batch"] = None
                    claim["history"].append({"state": claim["state"], "at": cl.now(), "note":
                                             f"Batch {batch.batch_id} stopped before any money left the holder: "
                                             f"{batch.problem} The claim is still approved and can be paid another way."})
                    claim_store.save(claim)

    runner.checks.append(queue_checks)
    runner.after.append(carry_to_claims)

    @app.post("/api/payer/batches/claims", status_code=201, dependencies=[Depends(payer_only)])
    def make_claims_batch(body: ClaimsBatchIn) -> dict:
        """Write a batch from claims in the holder's queue that the holder has approved, each to be paid to the
        bank account its approval covers. No money moves until the holder approves the batch."""
        ids = list(dict.fromkeys(body.claim_ids))
        if len(ids) < 2:
            raise HTTPException(422, "A batch pays at least two claims.")
        chosen, problems = [], []
        with claim_store.lock:
            for n, claim_id in enumerate(ids, 1):
                try:
                    claim = claim_store.load(claim_id)
                except cl.ClaimError as err:
                    raise HTTPException(err.status, err.message) from None
                if claim.get("estate"):
                    problems.append(f"Claim {claim_id} is an estate. It is paid as one settlement to every heir, "
                                    "from the estate view.")
                    continue
                if claim.get("batch"):
                    problems.append(f"Claim {claim_id} is already in batch {claim['batch']['id']}.")
                    continue
                if claim["state"] != cl.APPROVED or not claim.get("payee"):
                    problems.append(f"Claim {claim_id} is not approved and waiting to be paid.")
                    continue
                if claim.get("funding") == "metal":
                    problems.append(f"Claim {claim_id} is funded on Metal, under its own mandate.")
                    continue
                if claim_store.payout_path(claim_id).exists():
                    problems.append(f"Claim {claim_id} already has a payment of its own.")
                    continue
                problem = claim_problem(claim_id, n, approving=False)
                if problem:
                    problems.append(problem.replace(f"Payment {n}", f"Claim {claim_id}"))
                    continue
                chosen.append(claim)
            if problems:
                raise HTTPException(409, {"message": "These claims cannot be paid together yet.", "reasons": problems})
            rules = [(c["approval"]["terms"].get("instructions")) for c in chosen]
            if any(r != rules[0] for r in rules):
                raise HTTPException(409, "These claims were approved under different standing instructions. "
                                         "A batch keeps one set: approve the older ones again first.")
            batch = bt.new_claims_batch(runner.folder, chosen, rules[0])
        return shown(batch)

    @app.get("/api/payer/batches", dependencies=[Depends(payer_only)])
    def list_batches() -> dict:
        return {"batches": [{"batch_id": b.batch_id, "holder": b.holder, "state": b.state,
                             "state_words": bt.STATE_WORDS[b.state], "payments": len(b.items),
                             "created_at": b.created_at, "finished_at": b.finished_at} for b in runner.all()]}

    @app.get("/api/payer/batches/{batch_id}", dependencies=[Depends(payer_only)])
    def get_batch(batch_id: str) -> dict:
        return shown(load(batch_id))

    def act(batch_id: str, fn) -> dict:
        with runner.lock:
            batch = load(batch_id)
            try:
                fn(batch)
            except ValueError as err:
                raise HTTPException(409, str(err)) from None
        runner.start(batch_id)
        return shown(load(batch_id))

    @app.post("/api/payer/batches/{batch_id}/approve", dependencies=[Depends(payer_only)])
    def approve_batch(batch_id: str) -> dict:
        """The holder approves the batch on the exact terms shown. That starts it. For a batch of claims from the
        queue, every claim is checked again first, exactly as a single approval and a single payment would be,
        and each claim then shows that it is being paid in this batch."""
        if not factory_ready():
            raise HTTPException(503, NO_CREDENTIALS)

        def approve_from_queue(batch: bt.Batch) -> None:
            if batch.state != bt.PLANNED:
                raise ValueError("This batch has already been approved.")
            with claim_store.lock:
                problems = [p for p in (claim_problem(i["claim_id"], i["n"], approving=True)
                                        for i in batch.items if i.get("claim_id")) if p]
                if not problems:
                    for i in batch.items:
                        if i.get("claim_id") and claim_store.load(i["claim_id"])["state"] != cl.APPROVED:
                            problems.append(f"Payment {i['n']}: its claim is no longer waiting to be paid.")
                if problems:
                    raise ValueError(" ".join(problems))
                bt.approve(batch)
                for i in batch.items:
                    if i.get("claim_id"):
                        claim = claim_store.load(i["claim_id"])
                        claim["batch"] = {"id": batch.batch_id, "n": i["n"]}
                        claim["history"].append({"state": claim["state"], "at": cl.now(), "note":
                                                 f"The holder is paying this claim as payment {i['n']} of batch "
                                                 f"{batch.batch_id}, with {len(batch.items) - 1} other approved "
                                                 f"{'claim' if len(batch.items) == 2 else 'claims'}, from one deposit "
                                                 "on the Airwallex sandbox. The amount and the bank account are the "
                                                 "ones the approval covers."})
                        claim_store.save(claim)

        return act(batch_id, lambda batch: approve_from_queue(batch) if bt.claim_ids(batch) else bt.approve(batch))

    @app.post("/api/payer/batches/{batch_id}/resume", dependencies=[Depends(payer_only)])
    def resume_batch(batch_id: str) -> dict:
        load(batch_id)
        runner.start(batch_id)
        return shown(load(batch_id))

    @app.post("/api/payer/batches/{batch_id}/items/{n}/account", dependencies=[Depends(payer_only)])
    def corrected_account(batch_id: str, n: int) -> dict:
        """The demonstration owner gives her second example account after a refusal. For a claim from the queue
        the account is the one the claimant has since given on the claim."""
        def corrected(batch: bt.Batch):
            item = next((i for i in batch.items if i["n"] == n), None)
            if item and item.get("claim_id"):
                payee = claim_store.load(item["claim_id"]).get("payee") or {}
                if not payee.get("beneficiary") or bt.digest(payee["beneficiary"]) == bt.digest(item["beneficiary"]):
                    raise ValueError("The claimant has not given another bank account on the claim yet.")
                return bt.give_corrected_account(batch, n, payee["beneficiary"])
            return bt.give_corrected_account(batch, n)
        return act(batch_id, corrected)

    @app.post("/api/payer/batches/{batch_id}/items/{n}/approve", dependencies=[Depends(payer_only)])
    def approve_account(batch_id: str, n: int) -> dict:
        """The holder approves the corrected account of one payment."""
        return act(batch_id, lambda batch: bt.approve_item(batch, n))

    @app.post("/api/payer/batches/{batch_id}/items/{n}/agree", dependencies=[Depends(payer_only)])
    def owner_agrees(batch_id: str, n: int) -> dict:
        """The demonstration owner agrees to a replacement that is outside the tolerance."""
        return act(batch_id, lambda batch: bt.owner_agrees(batch, n))

    def factory_ready() -> bool:
        try:
            client, _ = factory()
        except awx.CredentialsError:
            return False
        client.close()
        return True
