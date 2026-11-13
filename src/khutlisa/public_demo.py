"""Public demonstration mode, and the health and readiness answers a deployed copy needs.

KHUTLISA_PUBLIC_DEMO=1 turns the mode on. A copy that anyone on the internet can open then keeps the real
search, the "who is owed" and holders screens, the demonstration journeys and the Airwallex sandbox payments,
and closes everything a stranger could misuse:

  claims            can be opened only on demonstration records, so nobody's real details reach a shared screen
  documents         only the sample documents that ship with the product are accepted; any other file is refused
  voice             only the demonstration sound files are transcribed; a visitor's own recording is refused
  the holder's list only the invented holder file can be loaded (outreach_api)
  payments          can be planned, approved, started or released from a hold only on demonstration claims:
                    a single payment, an estate's settlement, a batch of claims and a pull on Metal alike
  language model    a small number of calls a day; when it is used up, a plain sentence says so
  everything        counted per client address, with a limit per minute and per hour

The holder's view stays behind its key, and in this mode the key is given to the page (/api/mode), because
everything behind it is a demonstration.

Nothing here is a language model and nothing here decides a claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from . import clients, demo, llm, payouts, speech
from .ratelimit import HOUR, MINUTE, SlidingWindow

BUDGET_USED = ("Today's small budget of language model calls for this public demonstration is used up. It "
               "starts again at midnight UTC. Until then the search, the prepared examples and the forms still "
               "work; reading new words or documents does not.")
ONLY_DEMO_CLAIMS = ("This is a public demonstration. A claim can be opened only on a demonstration record, so "
                    "that nobody's real details are entered here. Follow Marisol or Amihan, or run Khutlisa "
                    "yourself.")
ONLY_SAMPLE_DOCUMENTS = ("This is a public demonstration, so only the sample documents offered on this screen "
                         "can be added. Do not upload a real document here.")
ONLY_SAMPLE_VOICE = ("This is a public demonstration, so only the spoken example is transcribed. Type your "
                     "history instead, and do not enter real personal details.")
ONLY_DEMO_PAYMENTS = "This is a public demonstration. Only demonstration claims can be approved or paid here."
METAL_OFF = ("Funding on Metal is switched off in this public demonstration. Every approval here is a click by "
             "any visitor, and on Metal it would be signed with the demonstration holder's own testnet key and "
             "spend its small faucet balance and paid testnet RPC credit, which a few visitors would use up for "
             "everyone. The Metal runs are recorded in docs/METAL_RUN_LOG.md; a copy run on a developer's machine "
             "with the Metal testnet setup funds claims on Metal.")
RECORDED_NOTE = ("The language model's answers for the demonstration journeys were recorded in advance and are "
                 "replayed here. A copy run with a model key, or on a developer's machine, calls the model live.")
DO_NOT_ENTER = "Public demonstration. Everything typed here can be seen by other visitors: do not enter real personal details."


def enabled(env=None) -> bool:
    return (os.environ if env is None else env).get("KHUTLISA_PUBLIC_DEMO", "") in ("1", "true", "yes")


class BudgetUsed(llm.ModelUnavailable):
    """The day's budget of model calls is used. The message is a sentence for the screen."""
    for_screen = True


class DailyBudget:
    """So many language model calls in one UTC day, for the whole server. Kept in memory."""

    def __init__(self, calls: int, clock=time.time):
        self.calls, self.clock = int(calls), clock
        self._day, self._used = -1, 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        day = int(self.clock() // 86400)
        if day != self._day:
            self._day, self._used = day, 0

    def take(self) -> None:
        with self._lock:
            self._roll()
            if self._used >= self.calls:
                raise BudgetUsed(BUDGET_USED)
            self._used += 1

    def left(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self.calls - self._used)


def fixed_wording(kind: str, facts: dict, plan: dict | None) -> dict:
    """The payment explanations of the public demonstration: always the fixed sentence, never a model's words."""
    return {"text": payouts.fixed_explanation(kind, facts, plan), "worded_by": "fixed sentence"}


def model_status() -> dict:
    """How this server reaches a language model, if at all. Never the key itself."""
    held = llm.recorded
    if held is not None and len(held) and not os.environ.get("ANTHROPIC_API_KEY") and not shutil.which("claude"):
        return {"available": True, "through": "answers recorded in advance for the demonstration inputs",
                "recorded_inputs": len(held), "note": RECORDED_NOTE}
    if os.environ.get("ANTHROPIC_API_KEY"):
        return {"available": True, "through": "the API, with a key from the environment"}
    if shutil.which("claude"):
        return {"available": True, "through": "the claude program on this machine"}
    return {"available": False, "through": None,
            "note": "No language model: ANTHROPIC_API_KEY is not set. Speech and documents are not read, the "
                    "column mapping is made in code, and the notices use the translations that ship with the "
                    "product."}


def _sample_bytes(web_dist: Path, folder: str, pattern: str) -> list[bytes]:
    out = []
    for base in (web_dist, web_dist.parent / "public"):
        place = base / folder
        if place.is_dir():
            out += [p.read_bytes() for p in sorted(place.glob(pattern))]
        if out:
            break
    return out


class Gate:
    """The checks of the public demonstration, as one ASGI layer in front of the app.

    It reads the body of the few requests it has to look into (a new claim, a document, a recording), decides,
    and hands the same body on. Everything else passes through after the per-client count."""

    _DOCUMENT = re.compile(r"^/api/claims/([0-9a-f]{16})/(?:estate/)?documents$")
    # Every route that approves, starts, carries on or releases a payment or a pull on Metal, with the claim it
    # acts on: a single payment, an estate's settlement, a Metal mandate, and a hold in the risk view.
    _MONEY = [re.compile(p) for p in (
        r"^/api/claims/([0-9a-f]{16})/payout/(?:plan|confirm|resume)$",
        r"^/api/payer/claims/([0-9a-f]{16})/approve$",
        r"^/api/payer/claims/([0-9a-f]{16})/metal/(?:mandate|attempt|revoke|verify)$",
        r"^/api/claims/([0-9a-f]{16})/estate/settlement/(?:plan|confirm|resume|heirs/[^/]+/agree)$",
        r"^/api/payer/estates/([0-9a-f]{16})/approve$",
        r"^/api/payer/risk/claims/([0-9a-f]{16})/release$",
    )]
    _BATCH = re.compile(r"^/api/payer/batches/([0-9a-z]{1,32})/(?:approve|resume|items/\d+/(?:account|approve|agree))$")
    MAX_BODY = 32 * 1024 * 1024

    def __init__(self, app, *, claim_store, record_ids, web_dist: Path, per_minute: int, per_hour: int,
                 clock=time.monotonic, batches=None):
        self.app, self.claim_store, self.record_ids = app, claim_store, record_ids
        self.batches = batches             # batch.BatchRunner: a batch of claims pays only demonstration claims
        self.window = SlidingWindow([(per_minute, MINUTE), (per_hour, HOUR)], clock)
        self.documents = _sample_bytes(Path(web_dist), "samples", "*.png")
        self.sounds = _sample_bytes(Path(web_dist), "demo", "*.m4a")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["path"] in ("/api/health", "/api/ready"):
            return await self.app(scope, receive, send)
        from starlette.requests import Request

        request = Request(scope)
        who = clients.address(request)
        wait = self.window.take(who)
        if wait:
            return await self._refuse(send, 429, f"Too many requests have come from this address. Try again in "
                                                 f"{wait} {'second' if wait == 1 else 'seconds'}.", {"retry-after": str(wait)})
        path, method = scope["path"], scope["method"]
        claim_id = None
        if method == "POST":
            match = next((m for m in (p.match(path) for p in self._MONEY) if m), None)
            if match:
                claim_id = match.group(1)
            batch = self._BATCH.match(path)
            if batch and not self._demonstration_batch(batch.group(1)):
                return await self._refuse(send, 403, ONLY_DEMO_PAYMENTS)
        if claim_id and not self._demonstration_claim(claim_id):
            return await self._refuse(send, 403, ONLY_DEMO_PAYMENTS)
        look = (method == "POST" and (path == "/api/claims" or self._DOCUMENT.match(path)
                                      or path == "/api/payer/batches/claims"
                                      or path in ("/api/intake/audio", "/api/intake/heard")))
        if not look:
            return await self.app(scope, receive, send)
        body = b""
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return
            body += message.get("body", b"")
            if len(body) > self.MAX_BODY:
                return await self._refuse(send, 413, "The file is too large.")
            if not message.get("more_body"):
                break
        refusal = self._refusal_for(path, body)
        if refusal:
            return await self._refuse(send, 403, refusal)
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return await self.app(scope, replay, send)

    def _demonstration_claim(self, claim_id: str) -> bool:
        try:
            claim = self.claim_store.load(claim_id)
        except Exception:
            return True                # no such claim: the route itself answers 404
        return demo.is_demonstration(claim["record"].get("source"))

    def _demonstration_batch(self, batch_id: str) -> bool:
        """A batch from the book pays demonstration owners only. A batch of claims from the queue is a
        demonstration only when every claim in it is."""
        if self.batches is None:
            return True
        try:
            batch = self.batches.load(batch_id)
        except Exception:
            return True                # no such batch: the route itself answers 404
        return all(self._demonstration_claim(i["claim_id"]) for i in batch.items if i.get("claim_id"))

    def _refusal_for(self, path: str, body: bytes) -> str | None:
        if path == "/api/payer/batches/claims":
            try:
                ids = json.loads(body or b"{}").get("claim_ids") or []
            except (ValueError, AttributeError):
                return None
            return None if all(self._demonstration_claim(str(i)) for i in ids) else ONLY_DEMO_PAYMENTS
        if path == "/api/claims":
            try:
                shown = json.loads(body or b"{}").get("record_id") or ""
            except (ValueError, AttributeError):
                return None            # not JSON: the route itself answers 422
            held = self.record_ids.find(str(shown)) if self.record_ids is not None else None
            return None if held is None or demo.is_demonstration(held[0]) else ONLY_DEMO_CLAIMS
        if path.startswith("/api/intake/"):
            return None if any(sound in body for sound in self.sounds) else ONLY_SAMPLE_VOICE
        return None if any(document in body for document in self.documents) else ONLY_SAMPLE_DOCUMENTS

    @staticmethod
    async def _refuse(send, status: int, text: str, headers: dict | None = None) -> None:
        body = json.dumps({"detail": text}).encode()
        head = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        head += [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
        await send({"type": "http.response.start", "status": status, "headers": head})
        await send({"type": "http.response.body", "body": body})


def register(app, *, store, claim_store, runner, web_dist: Path, payer_key: str, public_demo: bool,
             budget: DailyBudget | None) -> None:
    """Adds /api/health, /api/ready and /api/mode."""
    progress_path = Path(store.path).parent / "build_progress.json"
    web_dist = Path(web_dist)

    @app.get("/api/health")
    def health() -> dict:
        """The process is up. It says nothing about what is loaded; /api/ready does."""
        return {"status": "ok"}

    def readiness() -> dict:
        try:
            building = json.loads(progress_path.read_text())
        except (OSError, ValueError):
            building = None
        register_loaded = store.loaded()
        model = model_status()
        return {
            "ready": register_loaded and (web_dist / "index.html").exists(),
            "register": {"loaded": register_loaded, "building": None if register_loaded else building,
                         "note": None if register_loaded else
                                 "California's file is not loaded yet. Until it is, the search runs over the "
                                 "demonstration records only."},
            "web": (web_dist / "index.html").exists(),
            "model": {**model, "calls_left_today": budget.left() if budget else None},
            "speech": speech.engine(),
            "airwallex_keys": bool(runner.credentials_ready()),
            "holder_key_set": bool(payer_key),
            "public_demo": public_demo,
        }

    @app.get("/api/ready")
    def ready():
        """Whether the whole app can serve: California's file loaded and the pages built. While the file is
        still being fetched and built on a first start, this answers 503 with the progress."""
        from fastapi.responses import JSONResponse

        out = readiness()
        return JSONResponse(out, status_code=200 if out["ready"] else 503)

    @app.get("/api/mode")
    def mode() -> dict:
        """What kind of copy this is, for the pages. In the public demonstration the holder's key is given
        out here on purpose: everything behind it is a demonstration."""
        model = model_status()
        return {"public_demo": public_demo, "notice": DO_NOT_ENTER if public_demo else "",
                "holder_key": payer_key if public_demo and payer_key else None,
                "model": {"available": model["available"], "calls_left_today": budget.left() if budget else None,
                          "note": model.get("note")},
                "register_loaded": store.loaded()}


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
