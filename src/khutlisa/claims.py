"""Claims: one JSON file per claim under data/claims/, explicit states, and a dated history of what happened.

A claim never holds a private register owner's full name or street. It keeps only the public form of the record
(`server.public_record`), so anything built from a claim (the packet, the payer queue) cannot leak them either.
The claimant's own details, which they typed in, are theirs and are stored as given.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import california, documents
from . import instructions as ins

FOUND = "FOUND"
PROOF_NEEDED = "PROOF_NEEDED"
PROOF_READY = "PROOF_READY"
PACKET_READY = "PACKET_READY"
FILED = "FILED"
APPROVED = "APPROVED"
PAYING = "PAYING"
PAID = "PAID"
REJECTED = "REJECTED"   # a payer said no; the reason is kept with the claim
# The payment stopped part of the way: the money arrived short, or the bank refused or returned the transfer. The
# approval that started it no longer holds, so the payer has to approve the new terms before anything is sent.
PAYMENT_HELD = "PAYMENT_HELD"
STATES = (FOUND, PROOF_NEEDED, PROOF_READY, PACKET_READY, FILED, APPROVED, PAYING, PAID)
ALL_STATES = STATES + (REJECTED, PAYMENT_HELD)
BEFORE_DECISION = (FOUND, PROOF_NEEDED, PROOF_READY, PACKET_READY, FILED)

# An estate is paid to several heirs from one deposit (estate_settlement.py). A Metal mandate mirrors one approval
# paid to one bank account, so an estate is never funded on Metal; this is the sentence that says so.
ESTATE_NOT_ON_METAL = ("An estate is not funded on Metal. A Metal mandate mirrors one approval paid to one bank "
                       "account, and an estate is paid to several heirs, each in their own currency, from one bank "
                       "deposit. Approve it on the estate view, where it is funded by that deposit.")
# A claim in one of these states has an approval or money in motion. No second claim on its property may be
# approved while it is in one of them, and once one is PAID the property is closed for good.
HOLDS_THE_PROPERTY = (APPROVED, PAYING, PAID, PAYMENT_HELD)
CLOSED_TO_DOCUMENTS = (PAYING, PAID, REJECTED)

_ID = re.compile(r"[0-9a-f]{16}")


class ClaimError(Exception):
    """A request that the claim's present state does not allow. `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seconds_between(first: str, second: str) -> float:
    return (datetime.fromisoformat(second) - datetime.fromisoformat(first)).total_seconds()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value) -> str:
    """One hash for any JSON value, the same whatever order its keys were written in."""
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())


def property_key(claim: dict) -> tuple[str, str]:
    """Which property in the register a claim is on. Several owners can share one property; it is paid once."""
    held = claim.get("property") or {}
    return (held.get("source") or claim["record"].get("source") or "",
            held.get("record_id") or claim["record"].get("record_id") or "")


def _order(claim: dict) -> tuple:
    """The order claims were opened in. `opened` is a clock reading fine enough to tell two apart."""
    return (claim.get("opened") or 0, claim.get("created_at", ""), claim["id"])


def terms(claim: dict, funds: dict | None = None, rules: dict | None = None) -> dict:
    """Exactly what a holder's approval covers: how much, in which currency, to whom, into which account, on
    which documents, and under which standing instructions. `funds` is given when the money has already moved
    (it arrived short, or it came back from the bank in another currency); before that the amount is the one on
    the record. `rules` are the holder's standing instructions as they stand at the approval, or None."""
    payee = claim.get("payee") or {}
    return {
        "instructions": rules,
        "amount": str((funds or {}).get("amount") or f"{float(claim['record'].get('amount') or 0):.2f}"),
        "currency": (funds or {}).get("currency") or claim["record"].get("currency") or "USD",
        "claimant_name": claim["claimant"]["name"],
        "payee_hash": payee.get("hash"),
        "payee_currency": payee.get("currency"),
        "documents": {d["id"]: d.get("sha256") for d in claim.get("documents", [])},
        # An estate claim (estates.py) is approved on the family, each heir's share and each heir's bank account.
        **({"estate": estate_terms(claim)} if claim.get("estate") else {}),
    }


def estate_terms(claim: dict) -> dict:
    """What an approval of an estate claim covers beyond the amount and the documents: the family as it was
    described, each heir's share as an exact fraction, each heir's bank account, and which heirs were proven."""
    estate = claim["estate"]
    heirs = sorted(estate.get("heirs") or [], key=lambda h: h["id"])
    return {"family": digest(estate.get("family")),
            "shares": {h["id"]: h.get("share") for h in heirs},
            "payees": {h["id"]: (h.get("payee") or {}).get("hash") for h in heirs},
            "proven": {h["id"]: bool(h.get("proven")) for h in heirs}}


def approval_holds(claim: dict, funds: dict | None = None) -> tuple[bool, str]:
    """(True, "") while the claim still matches the terms its approval was given on. Otherwise (False, what
    changed), in words for the claim's history."""
    approval = claim.get("approval")
    if not approval:
        return False, "there is no approval on file"
    now_terms, then = terms(claim, funds), approval["terms"]
    if now_terms["payee_hash"] != then["payee_hash"]:
        return False, "the bank account to be paid was changed"
    if (now_terms["amount"], now_terms["currency"]) != (then["amount"], then["currency"]):
        return False, (f"the amount is now {now_terms['amount']} {now_terms['currency']}, and "
                       f"{then['amount']} {then['currency']} was approved")
    if now_terms["claimant_name"] != then["claimant_name"]:
        return False, "the claimant's name was changed"
    if now_terms.get("estate") != then.get("estate"):
        was, has = then.get("estate") or {}, now_terms.get("estate") or {}
        if was.get("family") != has.get("family") or was.get("shares") != has.get("shares"):
            return False, "the family or the shares were changed after the approval"
        if was.get("payees") != has.get("payees"):
            return False, "an heir's bank account was changed after the approval"
        return False, "the proof for an heir changed after the approval"
    added = [k for k in now_terms["documents"] if k not in then["documents"]]
    removed = [k for k in then["documents"] if k not in now_terms["documents"]]
    changed = [k for k, v in now_terms["documents"].items() if k in then["documents"] and then["documents"][k] != v]
    if added:
        return False, "a document was added after the approval"
    if removed:
        return False, "a document the approval relied on was removed"
    if changed:
        return False, "a document was changed after the approval"
    return True, ""


def checklist(claim: dict) -> dict:
    """What California asks for in this claim's case, with each document marked "attached" or "still needed"."""
    record, claimant = claim["record"], claim["claimant"]
    case = california.requirements(
        relationship=claimant["relationship"],
        amount=float(record.get("amount") or 0),
        claimant_country=claimant.get("country") or "",
        owner_is_organisation=bool(record.get("owner_is_organisation")),
        property_type=record.get("property_type") or "",
    )
    held: dict[str, list[str]] = {}
    for doc in claim.get("documents", []):
        held.setdefault(doc["kind"], []).append(doc["filename"])
    items = []
    for need in case["documents"]:
        files = [name for kind in need["kinds"] for name in held.get(kind, [])]
        items.append({**need, "kind_labels": [documents.KINDS[k] for k in need["kinds"]],
                      "status": "attached" if files else "still needed", "files": files})
    required = [i for i in items if i["required"]]
    attached = [i for i in required if i["status"] == "attached"]
    return {
        "items": items,
        "required": len(required),
        "attached": len(attached),
        "complete": len(attached) == len(required),
        "missing": [i["title"] for i in required if i["status"] != "attached"],
        "notary": case["notary"],
        "signing": case["signing"],
        "payment": case["payment"],
        "mail_to": case["mail_to"],
        "sources": case["sources"],
    }


class ClaimStore:
    """Reads and writes claim files. One lock guards every change, which is plenty at this scale."""

    def __init__(self, folder: Path | str):
        self.folder = Path(folder)
        self.lock = threading.RLock()
        # Set by the app when document reading is on. Then an upload is stored as "reading", a background
        # reader fills it in, and the claim becomes PROOF_READY only when the proof built from the readings is.
        self.reading_on = False
        # Checks other modules add (rings.py, estates.py). Each takes the claim and raises ClaimError to refuse.
        # `approval_checks` run under the lock before an approval is recorded; `payment_checks` run before any
        # step that starts or carries on a payment; `creation_hooks` are called with (claim, request) when a
        # claim is opened through the API and may add to the claim before it is saved.
        self.approval_checks: list = []
        self.payment_checks: list = []
        self.creation_hooks: list = []

    # ---- files ---------------------------------------------------------------------------------------------

    @staticmethod
    def check_id(claim_id: str) -> str:
        if not _ID.fullmatch(claim_id or ""):
            raise ClaimError(404, "There is no claim with that number.")
        return claim_id

    def path(self, claim_id: str) -> Path:
        return self.folder / f"{self.check_id(claim_id)}.json"

    def files(self, claim_id: str) -> Path:
        """The folder that holds this claim's uploaded documents and its payout file."""
        return self.folder / self.check_id(claim_id)

    def payout_path(self, claim_id: str) -> Path:
        return self.files(claim_id) / "payout.json"

    def load(self, claim_id: str) -> dict:
        path = self.path(claim_id)
        if not path.is_file():
            raise ClaimError(404, "There is no claim with that number.")
        return json.loads(path.read_text())

    def save(self, claim: dict) -> None:
        """Write the whole claim, then swap it into place, so a crash never leaves half a file."""
        claim["updated_at"] = now()
        target = self.path(claim["id"])
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(claim, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

    # ---- the holder's standing instructions ------------------------------------------------------------------

    @property
    def instructions_path(self) -> Path:
        return self.folder / "holder_instructions.json"

    def instructions(self) -> dict | None:
        """{"rules", "set_at"} as the holder last set them, or None when none have been set."""
        try:
            held = json.loads(self.instructions_path.read_text())
        except (OSError, ValueError):
            return None
        return held if isinstance(held, dict) and held.get("rules") else None

    def set_instructions(self, raw: dict) -> dict:
        """Stores the holder's standing instructions. They apply to approvals given from now on; an approval
        already given keeps the copy it was given with. Raises ValueError, in words, for a value out of range."""
        rules = ins.clean(raw)
        with self.lock:
            earlier = self.instructions()
            held = {"rules": rules, "set_at": now(),
                    "earlier": ((earlier or {}).get("earlier") or [])
                               + ([{"rules": earlier["rules"], "set_at": earlier["set_at"]}] if earlier else [])}
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.instructions_path.with_name(self.instructions_path.name + ".tmp")
            with open(tmp, "w") as fh:
                json.dump(held, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.instructions_path)
            return held

    def all(self) -> list[dict]:
        if not self.folder.is_dir():
            return []
        out = []
        for path in sorted(self.folder.glob("*.json")):
            if _ID.fullmatch(path.stem):
                try:
                    out.append(json.loads(path.read_text()))
                except ValueError:
                    continue
        return sorted(out, key=lambda c: c.get("created_at", ""), reverse=True)

    # ---- changes -------------------------------------------------------------------------------------------

    @staticmethod
    def _event(claim: dict, state: str, note: str) -> None:
        claim["state"] = state
        claim["history"].append({"state": state, "at": now(), "note": note})

    def create(self, record: dict, claimant: dict, match: dict | None, property_ref: dict | None = None) -> dict:
        """`record` must already be the public form of the register record (no private name, no street).
        `property_ref` is {"source", "record_id"}: the register's own number for the property. It stays in the
        claim file for the server's use (one live claim per property) and is never sent to a browser."""
        with self.lock:
            claim = {"id": secrets.token_hex(8), "created_at": now(), "opened": time.time_ns(), "state": FOUND,
                     "record": record,
                     "property": property_ref or {"source": record.get("source") or "",
                                                  "record_id": record.get("record_id") or ""},
                     "claimant": claimant, "match": match, "documents": [], "history": [],
                     "payee": None, "approval": None, "past_approvals": [], "rejection_reason": None}
            self._event(claim, FOUND, "The record was chosen from the search and a claim was opened.")
            ahead = self.ahead_of(claim)
            if ahead:
                claim["history"].append({"state": FOUND, "at": now(), "note":
                                         f"{len(ahead)} earlier {'claim is' if len(ahead) == 1 else 'claims are'} "
                                         "open on the same property. This claim waits behind "
                                         f"{'it' if len(ahead) == 1 else 'them'}."})
            need = checklist(claim)
            self._event(claim, PROOF_NEEDED, f"{need['required']} documents are needed before the packet is complete.")
            self.save(claim)
            return claim

    def move(self, claim_id: str, allowed_from: tuple[str, ...], state: str, note: str, refusal: str,
             **changes) -> dict:
        with self.lock:
            claim = self.load(claim_id)
            if claim["state"] not in allowed_from:
                raise ClaimError(409, refusal)
            claim.update(changes)
            self._event(claim, state, note)
            self.save(claim)
            return claim

    def add_document(self, claim_id: str, kind: str, filename: str, data: bytes) -> dict:
        if kind not in documents.KINDS:
            raise ClaimError(422, "Choose what kind of document this is.")
        if not data:
            raise ClaimError(422, "The file is empty.")
        if len(data) > documents.MAX_BYTES:
            raise ClaimError(413, "The file is larger than 15 MB. Send a smaller photo or scan.")
        sniffed = documents.sniff(data)
        if sniffed is None:
            raise ClaimError(415, "Only photos (JPEG, PNG, WebP, HEIC, GIF, TIFF) and PDF files can be added.")
        content_type, ext = sniffed
        with self.lock:
            claim = self.load(claim_id)
            if claim["state"] in CLOSED_TO_DOCUMENTS:
                raise ClaimError(409, "This claim is closed to new documents.")
            doc_id = secrets.token_hex(6)
            folder = self.files(claim_id)
            folder.mkdir(parents=True, exist_ok=True)
            stored = folder / f"{doc_id}{ext}"
            stored.write_bytes(data)
            doc = {"id": doc_id, "kind": kind, "kind_label": documents.KINDS[kind],
                   "filename": documents.safe_label(filename), "stored_as": stored.name,
                   "content_type": content_type, "size": len(data), "sha256": sha256(data), "uploaded_at": now(),
                   "reading": {"status": "reading"} if self.reading_on else {"status": "not_read"}}
            claim["documents"].append(doc)
            note = f"A document was added: {doc['kind_label'].lower()}."
            claim["history"].append({"state": claim["state"], "at": now(), "note": note})
            self.void_approval(claim, "a document was added after the approval")
            if not self.reading_on and claim["state"] in (FOUND, PROOF_NEEDED) and checklist(claim)["complete"]:
                self._event(claim, PROOF_READY, "Every required document is attached.")
            self.save(claim)
            return claim

    def remove_document(self, claim_id: str, doc_id: str) -> dict:
        """Takes a document out of the proof file and deletes the stored file."""
        with self.lock:
            claim = self.load(claim_id)
            if claim["state"] in CLOSED_TO_DOCUMENTS:
                raise ClaimError(409, "This claim is closed, so its documents can no longer be changed.")
            doc = next((d for d in claim["documents"] if d["id"] == doc_id), None)
            if doc is None:
                raise ClaimError(404, "There is no such document on this claim.")
            claim["documents"] = [d for d in claim["documents"] if d["id"] != doc_id]
            stored = self.files(claim_id) / doc["stored_as"]
            if stored.is_file():
                stored.unlink()
            claim["history"].append({"state": claim["state"], "at": now(), "note":
                                     f"A document was removed: {doc['kind_label'].lower()} ({doc['filename']})."})
            self.void_approval(claim, "a document the approval relied on was removed")
            self.save(claim)
            return claim

    # ---- the payee, the approval and the property ------------------------------------------------------------

    def set_payee(self, claim_id: str, payee: dict) -> dict:
        """Stores the bank account the claimant wants to be paid into. `payee` is {"currency", "beneficiary"}
        (the body Airwallex takes) plus anything the caller wants kept, and gets its hash here. It is collected
        before the payer decides, so the payer approves the real destination."""
        with self.lock:
            claim = self.load(claim_id)
            if claim["state"] in (PAYING, PAID, REJECTED):
                raise ClaimError(409, "The bank account cannot be changed while a payment is under way or after "
                                      "the claim is closed.")
            payee = {**payee, "hash": digest({"currency": payee["currency"], "beneficiary": payee["beneficiary"]}),
                     "set_at": now()}
            changed = (claim.get("payee") or {}).get("hash") != payee["hash"]
            claim["payee"] = payee
            if changed:
                claim["history"].append({"state": claim["state"], "at": now(), "note":
                                         "The claimant gave the bank account to be paid into."})
                self.void_approval(claim, "the bank account to be paid was changed")
            self.save(claim)
            return claim

    def void_approval(self, claim: dict, reason: str) -> bool:
        """Withdraws the payer's approval because the claim no longer matches what was approved. The caller
        holds the lock and saves. Returns True when there was an approval to withdraw."""
        approval = claim.get("approval")
        if not approval:
            return False
        claim.setdefault("past_approvals", []).append({**approval, "voided_at": now(), "voided_because": reason})
        claim["approval"] = None
        back_to = PAYMENT_HELD if claim["state"] in (PAYING, PAID, PAYMENT_HELD) else approval.get("from_state", FILED)
        self._event(claim, back_to, f"The holder's approval no longer holds, because {reason}. The holder has to "
                                    "approve the claim again before any money moves.")
        return True

    def approve(self, claim_id: str, note: str, funds: dict | None = None, check=None) -> dict:
        """Records the payer's approval together with the exact terms it covers. `check(claim)` may raise to
        refuse; it runs under the lock, so nothing can change between the check and the approval."""
        with self.lock:
            claim = self.load(claim_id)
            again = claim["state"] == PAYMENT_HELD
            if not again and claim["state"] not in BEFORE_DECISION:
                raise ClaimError(409, "This claim has already been decided.")
            if check is not None:
                check(claim)
            for extra in self.approval_checks:
                extra(claim)
            if not claim.get("payee") and not claim.get("estate"):   # an estate has one account per heir
                raise ClaimError(409, "This claim cannot be approved yet, because the claimant has not given "
                                      "the bank account to be paid into. An approval covers one exact account.")
            self.check_property_is_free(claim)
            rules = (self.instructions() or {}).get("rules")
            covered = terms(claim, funds, rules)
            at = now()
            claim["approval"] = {"at": at, "terms": covered, "terms_hash": digest(covered),
                                 "from_state": claim["state"], "replaces_earlier_approval": again,
                                 # The deadline and the fee arithmetic follow from the instructions bound above.
                                 "deadline_at": ins.deadline_at(at, rules),
                                 "fee_rule": ins.fee_plan(claim["record"].get("amount") or 0, rules) if rules else None}
            self._event(claim, PAYING if again else APPROVED, note)
            self.save(claim)
            return claim

    def check_may_pay(self, claim: dict) -> None:
        """Refuses when a check added by another module says no money may move on this claim now."""
        for extra in self.payment_checks:
            extra(claim)

    def same_property(self, claim: dict) -> list[dict]:
        """Every other claim on the same property, oldest first."""
        key = property_key(claim)
        if not key[1]:
            return []
        others = [c for c in self.all() if c["id"] != claim["id"] and property_key(c) == key]
        return sorted(others, key=_order)

    def ahead_of(self, claim: dict) -> list[dict]:
        """Claims on the same property that were opened earlier and are still open. This claim waits for them."""
        return [c for c in self.same_property(claim) if c["state"] != REJECTED and _order(c) < _order(claim)]

    def check_property_is_free(self, claim: dict) -> None:
        """Refuses when another claim on the same property is paid, approved, in payment, or simply first in
        line. One property is paid once."""
        for other in self.same_property(claim):
            if other["state"] == PAID:
                raise ClaimError(409, "This property has already been paid out on another claim. It cannot be "
                                      "paid again.")
            if other["state"] in HOLDS_THE_PROPERTY:
                raise ClaimError(409, "Another claim on this property has been approved and is being paid. "
                                      "Only one claim on a property can be live.")
        if self.ahead_of(claim):
            raise ClaimError(409, "An earlier claim on this property is still open. Decide that claim first; "
                                  "this one waits behind it.")

    def set_reading(self, claim_id: str, doc_id: str, reading: dict, is_ready=None) -> dict:
        """Stores what was read from one document. `is_ready(claim)` says whether the proof is now ready; when it
        is, the claim moves on to PROOF_READY."""
        with self.lock:
            claim = self.load(claim_id)
            doc = next((d for d in claim["documents"] if d["id"] == doc_id), None)
            if doc is None:
                return claim
            doc["reading"] = reading
            doc["read_at"] = now()
            words = {"read": "was read", "unreadable": "could not be made out", "failed": "could not be read"}
            note = f"The {doc['kind_label'].lower()} ({doc['filename']}) {words.get(reading.get('status'), 'was read')}."
            claim["history"].append({"state": claim["state"], "at": now(), "note": note})
            if claim["state"] in (FOUND, PROOF_NEEDED) and is_ready is not None and is_ready(claim):
                self._event(claim, PROOF_READY, "Every required document has been read and ties to the claim.")
            self.save(claim)
            return claim

    def packet_made(self, claim_id: str) -> dict:
        """Called when the packet is downloaded. A complete proof file moves the claim to PACKET_READY."""
        with self.lock:
            claim = self.load(claim_id)
            if claim["state"] == PROOF_READY:
                self._event(claim, PACKET_READY, "The claim packet was prepared for the claimant to review and sign.")
                self.save(claim)
            return claim


# ---- the payer's view ----------------------------------------------------------------------------------------

# The five figures a fund or state office is shown, and the state a claim must have reached to count in each.
MILESTONES = (("found", FOUND), ("proven", PROOF_READY), ("filed", FILED), ("approved", APPROVED), ("paid", PAID))


def reached(claim: dict) -> dict[str, str]:
    """The first time this claim entered each state, by state name."""
    first: dict[str, str] = {}
    for event in claim.get("history", []):
        first.setdefault(event["state"], event["at"])
    return first


def results(claims: list[dict]) -> dict:
    """Counts and totals for each milestone, and the median time from each milestone to the next."""
    times = [reached(c) for c in claims]
    stages = []
    for name, state in MILESTONES:
        hit = [c for c, t in zip(claims, times) if state in t]
        if state == PAID:   # a payment the bank sent back is not a payment
            hit = [c for c in hit if c["state"] == PAID]
        stages.append({"stage": name, "count": len(hit),
                       "amount": round(sum(float(c["record"].get("amount") or 0) for c in hit), 2)})
    medians = []
    for (a_name, a_state), (b_name, b_state) in zip(MILESTONES, MILESTONES[1:]):
        gaps = [_seconds_between(t[a_state], t[b_state]) for t in times if a_state in t and b_state in t]
        medians.append({"from": a_name, "to": b_name, "claims": len(gaps),
                        "median_seconds": round(statistics.median(gaps), 1) if gaps else None})
    return {"claims": len(claims), "currency": "USD", "stages": stages, "medians": medians,
            "rejected": sum(1 for c in claims if c["state"] == REJECTED),
            "payment_held": sum(1 for c in claims if c["state"] == PAYMENT_HELD)}
