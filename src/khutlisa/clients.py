"""Who a request came from, for the per-client counts.

By default the caller is the address the connection came from, and nothing the caller writes in a header is
believed. A request that carries a forwarding header is also counted on one count shared by all such requests,
because the server program in front of this app can rewrite the client address from that header when the
connection comes from the same machine: sending a new address with every request then gains nothing.

A deployed copy sits behind one proxy of its own (Caddy, in deploy/). Every request then arrives from the proxy
with X-Forwarded-For set by it, so the rule above would put all visitors on one count. With
KHUTLISA_TRUSTED_PROXY=1 the last address in X-Forwarded-For is taken as the caller instead: it is the one the
proxy itself appended, whatever the visitor wrote before it. Set it only when the app can be reached through
that proxy alone.
"""
from __future__ import annotations

import os

FORWARDING_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
SHARED = "a forwarding header"


def trusted_proxy() -> bool:
    return os.environ.get("KHUTLISA_TRUSTED_PROXY", "") in ("1", "true", "yes")


def keys(request, trusted: bool | None = None) -> list[str]:
    """The counts one request is taken from, most general first."""
    host = request.client.host if request.client else "unknown"
    trusted = trusted_proxy() if trusted is None else trusted
    if trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        last = forwarded.split(",")[-1].strip()
        return [last or host]
    forwarded = any(h in request.headers for h in FORWARDING_HEADERS)
    return ([SHARED] if forwarded else []) + [host]


def address(request, trusted: bool | None = None) -> str:
    return keys(request, trusted)[-1]
