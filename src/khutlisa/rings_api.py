"""The holder's risk view: claims linked across the queue, the groups they form, and holds.

`register` puts the detector (rings.py) beside the claim store: a creation hook that keeps a fingerprint of where
a claim was opened from, an approval check and a payment check that refuse while a claim is held, and two routes
behind the holder's key.
"""
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import claims as cl
from . import rings


class ReleaseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def _trim(cls, v):
        return v.strip() if isinstance(v, str) else v


def register(app: FastAPI, claim_store) -> None:
    detector = rings.Rings(claim_store)
    app.state.rings = detector
    claim_store.creation_hooks.append(detector.on_create)
    claim_store.approval_checks.append(detector.check_approval)
    claim_store.payment_checks.append(detector.check_payment)
    payer_only = app.state.payer_only

    @app.get("/api/payer/risk", dependencies=[Depends(payer_only)])
    def risk_view() -> dict:
        """The queue with each claim's risk state, the groups of linked claims with their points, and the
        counts. Looking at it brings every claim's risk state up to date."""
        return detector.view()

    @app.post("/api/payer/risk/claims/{claim_id}/release", dependencies=[Depends(payer_only)])
    def release(claim_id: str, body: ReleaseIn) -> dict:
        """A person's decision to lift the hold on one claim, with the reason. Returns the view again."""
        try:
            detector.release(claim_id, body.reason)
        except cl.ClaimError as err:
            raise HTTPException(err.status, err.message) from None
        return detector.view()
