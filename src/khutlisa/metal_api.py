"""The Metal routes. `register` adds them to the app built in server.py and connects the funding on Metal to the
payout runner and to the holder's approval.

  GET  /api/metal                              whether Metal is set up here, the network, the scale, the addresses
  GET  /api/claims/{id}/metal                  the "Funded on Metal" panel for a claim, as its claimant sees it
  GET  /api/payer/claims/{id}/metal            the same for the holder, with what the holder can do
  POST /api/payer/claims/{id}/metal/mandate    the holder signs the mandate for the approval as it stands
  POST /api/payer/claims/{id}/metal/revoke     the holder revokes the mandate
  POST /api/payer/claims/{id}/metal/attempt    the agent is told to overstep the mandate, to see Metal refuse
  POST /api/payer/claims/{id}/metal/verify     Metal's own verification of the mandate, run afresh

The holder chooses Metal with its approval: POST /api/payer/claims/{id}/approve with {"funding": "metal"}.
Nothing here returns a key, a credential file or the RPC endpoint.
"""
from __future__ import annotations

import hmac
from decimal import Decimal
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import claims as cl
from . import metal as mt
from . import payouts

NOT_RUN = "not yet run on testnet"


class AttemptIn(BaseModel):
    case: Literal["over_cap", "wrong_payee", "second_pull"]


def connect(chain=None, env: dict | None = None, public_demo: bool = False) -> tuple[object | None, Decimal, str | None]:
    """(the chain, the scale, why Metal is not available). `chain` is given by the tests; otherwise the real
    command line is used when ~/.khutlisa_metal is set up, and Metal is simply off when it is not. In the public
    demonstration Metal is off (public_demo.METAL_OFF says why)."""
    try:
        scale = mt.scale_from(env)
        if chain is not None:
            return chain, scale, None
        if public_demo:
            from .public_demo import METAL_OFF
            return None, scale, METAL_OFF
        return mt.MetalCli(mt.MetalConfig.load(env)), scale, None
    except mt.MetalUnavailable as err:
        return None, mt.DEFAULT_SCALE, str(err)


def register(app: FastAPI, claim_store: cl.ClaimStore, runner: payouts.PayoutRunner, payer_key: str,
             chain=None, scale: Decimal | str | None = None, keys_folder=None,
             public_demo: bool = False) -> mt.MetalFunding | None:
    chain, env_scale, problem = connect(chain, public_demo=public_demo)
    scale = Decimal(str(scale)) if scale is not None else env_scale
    funding = None
    if chain is not None:
        funding = mt.MetalFunding(claim_store, chain, scale=scale, keys_folder=keys_folder)
        runner.funding = funding
    app.state.metal = funding

    def payer_only(key: str | None = Header(default=None, alias="X-Payer-Key")) -> None:
        if not payer_key:
            raise HTTPException(401, "The holder's view is locked: no key for it is set on this server. Set "
                                     "KHUTLISA_PAYER_KEY and start it again.")
        if not key or not hmac.compare_digest(key.encode(), payer_key.encode()):
            raise HTTPException(401, "The holder's key is missing or wrong.")

    def ready() -> mt.MetalFunding:
        if funding is None:
            raise HTTPException(503, problem or "Metal is not set up on this server.")
        return funding

    def guard(fn):
        try:
            return fn()
        except cl.ClaimError as err:
            raise HTTPException(err.status, err.message) from None
        except mt.MetalUnavailable as err:
            raise HTTPException(503, str(err)) from None
        except mt.MetalError as err:
            raise HTTPException(502, f"Metal did not complete the step: {str(err)[:400]}") from None

    def on_approval(claim: dict, wanted: str | None) -> None:
        """Called by the approval route once an approval is on file."""
        try:
            ready().on_approval(claim, wanted)
        except cl.ClaimError as err:
            raise HTTPException(err.status, "The claim is approved, but no mandate was signed on Metal: "
                                            + err.message) from None
        except mt.MetalError as err:
            raise HTTPException(502, "The claim is approved, but the mandate could not be signed on Metal: "
                                     f"{str(err)[:300]} Sign it again from the Metal panel.") from None

    if funding is not None:
        app.state.on_approval = on_approval

    def view(claim_id: str, payer: bool) -> dict:
        claim = guard(lambda: claim_store.load(claim_id))
        if funding is None:
            return {"available": False, "problem": problem, "funding": claim.get("funding", "bank"),
                    "label": NOT_RUN}
        return {"available": True, "problem": None, **funding.view(claim, payer=payer)}

    @app.get("/api/metal")
    def metal_status() -> dict:
        """Whether a claim can be funded on Metal on this server, and on what terms. No secret is in here."""
        if funding is None:
            return {"available": False, "problem": problem, "network": mt.NETWORK_NAME, "label": NOT_RUN}
        return {"available": True, "problem": None, "network": mt.NETWORK_NAME, "chain": mt.CHAIN,
                "token": mt.TOKEN_NAME, "token_address": mt.TOKEN, "explorer": mt.EXPLORER,
                "scale": {"usd_per_usdz": str(funding.scale), "words": mt.scale_words(funding.scale)},
                "accounts": {"holder_account": funding.holder_account, "settlement": funding.settlement},
                "enforced": {"by_chain": mt.BY_CHAIN, "by_code": mt.BY_CODE}}

    @app.get("/api/claims/{claim_id}/metal")
    def claim_metal(claim_id: str) -> dict:
        return view(claim_id, payer=False)

    @app.get("/api/payer/claims/{claim_id}/metal", dependencies=[Depends(payer_only)])
    def payer_metal(claim_id: str) -> dict:
        return view(claim_id, payer=True)

    @app.post("/api/payer/claims/{claim_id}/metal/mandate", dependencies=[Depends(payer_only)])
    def sign_mandate(claim_id: str) -> dict:
        """The holder signs and binds the mandate for the approval as it stands. Used when the signing that goes
        with an approval did not complete. A payment that was waiting for the mandate carries on."""
        guard(lambda: ready().sign_mandate(claim_id))
        claim = guard(lambda: claim_store.load(claim_id))
        if claim["state"] == cl.PAYING:
            runner.start(claim_id)
        return view(claim_id, payer=True)

    @app.post("/api/payer/claims/{claim_id}/metal/revoke", dependencies=[Depends(payer_only)])
    def revoke_mandate(claim_id: str) -> dict:
        """The holder revokes the mandate on its Metal account. Before any money has been pulled this sends the
        claim back to the holder: at once when the payment has not started, and otherwise as soon as Metal
        refuses the agent's pull."""
        guard(lambda: ready().revoke(claim_id))
        claim = guard(lambda: claim_store.load(claim_id))
        if claim["state"] == cl.PAYING:
            runner.start(claim_id)
        return view(claim_id, payer=True)

    @app.post("/api/payer/claims/{claim_id}/metal/attempt", dependencies=[Depends(payer_only)])
    def attempt(claim_id: str, body: AttemptIn) -> dict:
        """Tells the agent to try a pull outside the mandate, so that Metal's refusal can be seen. The attempt
        is real and signed; nothing moves when it is refused."""
        refusal = guard(lambda: ready().attempt(claim_id, body.case))
        return {"refusal": {**refusal, "explorer": mt.explorer_tx(refusal.get("transaction"))},
                **view(claim_id, payer=True)}

    @app.post("/api/payer/claims/{claim_id}/metal/verify", dependencies=[Depends(payer_only)])
    def verify(claim_id: str) -> dict:
        guard(lambda: ready().verify(claim_id))
        return view(claim_id, payer=True)

    return funding
