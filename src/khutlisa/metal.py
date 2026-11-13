"""Metal: the holder funds each approved claim under a mandate, and the chain enforces the approval's limits.

When the holder approves a claim it signs a Metal mandate whose terms are the approval's terms: one payee
(Khutlisa's settlement address), a per-payment cap and a total budget equal to what the holder is to send, one
payment, an expiry equal to the holder's deadline, and the claim number as the reference. Khutlisa's agent holds
the mandate key and nothing else of the holder's. It pulls the payment under the mandate. A pull above the cap,
to another address, a second time, after the expiry or after the holder revoked the mandate is refused by the
holder's Metal account itself, in the transaction that would have moved the money.

Four parts:
  MetalCli      shells out to the `metal-agent` command line (tools/metal). Signing happens only there.
  FakeMetal     the same calls over a small in-memory chain that enforces the same limits. Used by every test.
  MetalFunding  the product's logic: the mandate that mirrors an approval, the pull, the reading of the
                settlement from the chain, the hand-over to the payout machine, and what the screens show.
  terms         pure functions: the scale, and the mandate terms an approval asks for.

The scale. The testnet faucet tops an address up to 100 *USDZ, so a claim of 1,840.55 US dollars cannot be
funded one for one. On testnet 1 *USDZ therefore stands for `scale` US dollars of the claim (100 unless
KHUTLISA_METAL_SCALE says otherwise). Mandates count in whole *USDZ cents, so an amount is rounded up to the
next cent on chain. Every screen and document that shows an amount on Metal shows the scale beside it.

Keys never enter the repository and are never printed: they live under ~/.khutlisa_metal with mode 600. The RPC
endpoint is a credential too, and every line that leaves this module has it cut out.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import Any, Callable

from . import airwallex as awx
from . import claims as cl
from . import handover
from . import instructions as ins
from . import payouts

NETWORK = "testnet"
CHAIN = "eip155:63825"
NETWORK_NAME = "Metal testnet"
TOKEN = "0x000000000000000000000000000000000000B5d5"
TOKEN_NAME = "*USDZ"
EXPLORER = "https://testnet.metalntwx.com"
CLI_VERSION = "0.3.3"
HOME = Path.home() / ".khutlisa_metal"
REPO = Path(__file__).resolve().parents[2]
LOCAL_CLI = REPO / "tools" / "metal" / "node_modules" / ".bin" / "metal-agent"
DEFAULT_SCALE = Decimal(100)
USDZ_CENT = Decimal("0.01")

# Every reason Metal gives for refusing a payment under a mandate (docs.metalntwx.com/agents/metal-agent), in
# words for the screens.
REFUSALS = {
    "mandate_cap_exceeded": "the amount is above the mandate's per-payment cap",
    "mandate_payee_not_listed": "the address is not the one the mandate allows",
    "mandate_budget_spent": "the mandate's budget is spent, so nothing more can be pulled under it",
    "mandate_occurrences_used": "the mandate's one payment has been made",
    "mandate_expired": "the mandate has expired",
    "mandate_revoked": "the holder revoked the mandate",
    "mandate_not_bound": "the holder's account has no such mandate bound",
    "mandate_outside_recurrence": "the mandate has not started yet",
    "mandate_bad_signature": "the payment is not signed by the mandate's key",
    "mandate_outside_window": "the payment's validity window is not open",
    "mandate_nonce_used": "this payment was already made or refused",
    "transfer_would_fail": "the mandate allows it, but the token refuses the transfer (the holder's account is short)",
}
# Out-of-terms pulls the agent can be told to attempt, so the chain's refusal can be seen. Nothing moves.
ATTEMPTS = {
    "over_cap": "Pull one *USDZ cent more than the cap",
    "wrong_payee": "Pull to an address other than Khutlisa's settlement address",
    "second_pull": "Pull a second time after the claim was funded",
}

_REASON = re.compile(r"\b(mandate_[a-z_]+|transfer_would_fail)\b")
_RPC = re.compile(r"(rpc[-.\w]*\.metalntwx\.com/v1/)[A-Za-z0-9_.~-]+")
_HASH = re.compile(r"0x[0-9a-fA-F]{64}")


class MetalError(ValueError):
    """A Metal step failed. The message is safe for a screen: no key, no endpoint. (A ValueError, so the payout
    runner shows the message itself, as it does for its own refusals.)"""


class MetalUnavailable(MetalError):
    """Metal is not set up on this server. The message names what is missing, never a value."""


def redact(text: str) -> str:
    """Cuts the RPC endpoint's id out of anything that will be shown or logged."""
    return _RPC.sub(r"\1<endpoint id>", text or "")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def explorer_tx(tx: str | None) -> str | None:
    return f"{EXPLORER}/tx/{tx}" if tx else None


def explorer_address(address: str | None) -> str | None:
    return f"{EXPLORER}/address/{address}" if address else None


# ---- the scale and the terms ---------------------------------------------------------------------------------

def scale_from(env: dict | None = None) -> Decimal:
    raw = (os.environ if env is None else env).get("KHUTLISA_METAL_SCALE", "").strip()
    try:
        scale = Decimal(raw) if raw else DEFAULT_SCALE
    except ArithmeticError:
        raise MetalUnavailable("KHUTLISA_METAL_SCALE must be a number: how many US dollars one *USDZ stands for") from None
    if not Decimal(1) <= scale <= Decimal(100000):
        raise MetalUnavailable("KHUTLISA_METAL_SCALE must be between 1 and 100,000")
    return scale


def to_usdz(usd: Any, scale: Decimal) -> Decimal:
    """The amount on chain for a US dollar amount: divided by the scale and rounded up to the *USDZ cent, which
    is the smallest amount a mandate counts in."""
    return (Decimal(str(usd)) / scale).quantize(USDZ_CENT, ROUND_UP)


def to_usd(usdz: Any, scale: Decimal) -> Decimal:
    """What an amount on chain stands for in US dollars at this scale."""
    return (Decimal(str(usdz)) * scale).quantize(Decimal("0.01"))


def scale_words(scale: Decimal) -> str:
    if scale == 1:
        return "Scale: 1 *USDZ on Metal testnet stands for 1 US dollar of the claim. No real money moves."
    cent = (USDZ_CENT * scale).quantize(Decimal("0.01"))
    return (f"Scale: 1 *USDZ on Metal testnet stands for {scale:,f} US dollars of the claim, because the testnet "
            f"faucet gives an address at most 100 *USDZ. Mandates count in *USDZ cents, so one cent on chain "
            f"stands for {cent:,.2f} US dollars and amounts are rounded up to it. No real money moves.")


def _unix(stamp: str) -> int:
    when = datetime.fromisoformat(stamp)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return int(when.timestamp())


def _iso(unix: int | None) -> str | None:
    return None if unix is None else datetime.fromtimestamp(int(unix), timezone.utc).isoformat(timespec="seconds")


def _when(unix: int | None) -> str:
    """'27 Nov 2026, 06:52:55 UTC' for the screens."""
    if unix is None:
        return "no expiry"
    at = datetime.fromtimestamp(int(unix), timezone.utc)
    return f"{at.day} {at:%b %Y, %H:%M:%S} UTC"


def holder_sends(claim: dict) -> Decimal:
    """What the holder is to send for this claim under its approval: the claim, or under the fee rule the claim
    plus Airwallex's expected fees. This is the amount the payout machine expects to arrive."""
    approval = claim.get("approval") or {}
    rules = (approval.get("terms") or {}).get("instructions")
    amount = claim["record"].get("amount") or 0
    return Decimal(ins.fee_plan(awx.money(amount, "USD"), rules)["holder_sends"])


def wanted_terms(claim: dict, settlement: str, scale: Decimal, handover_date: str | None) -> dict:
    """The mandate an approval asks for. Every value is taken from the approval or follows from it by arithmetic.

    payee       Khutlisa's settlement address and no other
    cap, budget what the holder is to send, at the scale: one payment of exactly that, and nothing after it
    payments    one
    expiry      the deadline in the holder's standing instructions, or the holder's handover date to the State,
                whichever comes first
    reference   the claim number, with the start of the approval's terms hash
    """
    approval = claim.get("approval")
    if not approval:
        raise MetalError("A mandate mirrors an approval, and this claim has none.")
    usd = holder_sends(claim)
    amount = to_usdz(usd, scale)
    ends = []
    if approval.get("deadline_at"):
        ends.append((_unix(approval["deadline_at"]), "the deadline in the holder's standing instructions"))
    if handover_date:
        ends.append((_unix(handover_date + "T00:00:00+00:00"), "the holder's handover date to the State"))
    if not ends:
        raise MetalError("The approval carries no deadline and no handover date is set, so the mandate would "
                         "have no expiry.")
    expiry, why = min(ends)
    return {"payee": settlement, "cap_usdz": str(amount), "budget_usdz": str(amount), "max_occurrences": 1,
            "expiry": expiry, "expiry_from": why, "approved_usd": str(usd),
            "stands_for_usd": str(to_usd(amount, scale)), "scale": str(scale), "reference": claim["id"],
            "terms_hash": approval["terms_hash"],
            "description": f"Khutlisa claim {claim['id']} approval {approval['terms_hash'][:16]}"}


# ---- the command line ----------------------------------------------------------------------------------------

@dataclass
class MetalConfig:
    """Where the keys are and which addresses they stand for. Addresses are public; key files are not read here."""
    home: Path
    cli: list[str]
    rpc_url: str
    holder_key: Path
    holder_account: str
    settlement: str
    agent_key: Path | None
    agent_address: str | None
    scale: Decimal

    @classmethod
    def load(cls, env: dict | None = None, home: Path | str | None = None) -> "MetalConfig":
        """Reads ~/.khutlisa_metal (or KHUTLISA_METAL_HOME). `scripts/metal_setup.py` writes it. Raises
        MetalUnavailable naming what is missing."""
        env = os.environ if env is None else env
        home = Path(home or env.get("KHUTLISA_METAL_HOME") or HOME)
        try:
            held = json.loads((home / "config.json").read_text())
        except (OSError, ValueError):
            raise MetalUnavailable(f"Metal is not set up on this server: {home / 'config.json'} is missing. Run "
                                   "scripts/metal_setup.py (docs/METAL.md).") from None
        rpc = env.get("METAL_RPC_URL", "").strip()
        if not rpc:
            try:
                rpc = (home / "rpc_url").read_text().strip()
            except OSError:
                rpc = ""
        if not rpc:
            raise MetalUnavailable("Metal is not set up on this server: no RPC endpoint. Set METAL_RPC_URL or run "
                                   "scripts/metal_setup.py.")
        cli = env.get("KHUTLISA_METAL_CLI", "").strip()
        command = [cli] if cli else [str(LOCAL_CLI)] if LOCAL_CLI.exists() else ["metal-agent"]
        if not cli and not LOCAL_CLI.exists() and shutil.which("metal-agent") is None:
            raise MetalUnavailable("Metal is not set up on this server: the Metal command line is not installed. "
                                   "Run `npm ci` in tools/metal.")
        holder_key = home / "holder" / "owner-key.json"
        missing = [k for k in ("holder_account", "settlement") if not held.get(k)]
        if missing or not holder_key.is_file():
            raise MetalUnavailable("Metal is not set up on this server: the holder's account or Khutlisa's "
                                   "settlement address is missing. Run scripts/metal_setup.py.")
        agent_key = home / "agent" / "key.json"
        return cls(home=home, cli=command, rpc_url=rpc, holder_key=holder_key, holder_account=held["holder_account"],
                   settlement=held["settlement"], agent_key=agent_key if agent_key.is_file() else None,
                   agent_address=held.get("agent"), scale=scale_from(env))


def _fields(text: str) -> dict[str, list[str]]:
    """`name value` lines, as every metal-agent command prints them."""
    out: dict[str, list[str]] = {}
    for line in (text or "").splitlines():
        if not line.strip() or line.startswith((" ", "\t")):
            continue
        name, _, value = line.strip().partition(" ")
        out.setdefault(name, []).append(value.strip())
    return out


def _first(fields: dict, name: str) -> str | None:
    return (fields.get(name) or [None])[0]


def _usdz(text: str | None) -> str | None:
    """'0.05' from '0.05 *USDZ until expiry'."""
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", text or "")
    return m.group(1) if m else None


def _terms(fields: dict) -> dict:
    """The mandate's terms from what `credential create` and `mandate status` print."""
    payees = [p.split(" ")[0] for p in fields.get("payee", [])]
    unix = lambda name: int(_first(fields, name).split(" ")[0]) if _first(fields, name) else None
    spent = _first(fields, "spent")
    out = {"mandate_id": _first(fields, "mandate"), "description": _first(fields, "description"),
           "principal": _first(fields, "principal"), "token": _first(fields, "token"),
           "cap_usdz": _usdz(_first(fields, "per-payment-cap")), "budget_usdz": _usdz(_first(fields, "budget")),
           "starts": unix("starts"), "expiry": unix("expiry"),
           "max_occurrences": int(_first(fields, "max-occurrences")) if _first(fields, "max-occurrences") else None,
           "payees": payees}
    if "bound" in fields:
        out.update({"bound": _first(fields, "bound") == "yes", "revoked": _first(fields, "revoked") == "yes",
                    "spent_usdz": _usdz(spent), "account_type": _first(fields, "account-type"),
                    "payments": int(_first(fields, "payments")) if _first(fields, "payments") else None})
    return out


class MetalCli:
    """The real chain, through the `metal-agent` command line. Each method is one command.

    The command line keeps what it has sent under its home directory, so a pull repeated under the same payment
    id is the same payment and pays at most once. It is therefore always run with the same HOME."""

    def __init__(self, config: MetalConfig, run: Callable = subprocess.run):
        self.config = config
        self._run_process = run

    def __repr__(self) -> str:   # never show the endpoint
        return f"MetalCli(network={NETWORK!r}, holder_account={self.config.holder_account!r})"

    def _run(self, *args: str, timeout: float = 180.0) -> tuple[int, str, str]:
        (self.config.home / "home").mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "HOME": str(self.config.home / "home"), "METAL_RPC_URL": self.config.rpc_url}
        try:
            done = self._run_process([*self.config.cli, *args, "--network", NETWORK], capture_output=True,
                                     text=True, timeout=timeout, env=env)
        except FileNotFoundError:
            raise MetalUnavailable("The Metal command line is not installed. Run `npm install` in tools/metal.") from None
        except subprocess.TimeoutExpired:
            raise MetalError(f"Metal did not answer within {int(timeout)} seconds ({args[0]} {args[1] if len(args) > 1 else ''}). "
                             "Nothing is assumed about the outcome; the same step can be run again.") from None
        return done.returncode, done.stdout or "", done.stderr or ""

    def _ok(self, *args: str) -> dict[str, list[str]]:
        code, out, err = self._run(*args)
        if code != 0:
            raise MetalError(redact((err or out).strip())[:600] or f"metal-agent {args[0]} failed")
        return _fields(out)

    def version(self) -> str:
        done = self._run_process([*self.config.cli, "--version"], capture_output=True, text=True, timeout=30)
        return (done.stdout or "").strip()

    def create_credential(self, folder: Path | str, *, cap: Any, budget: Any, expires_in: int, description: str,
                          payee: str | None = None, max_occurrences: int | None = 1) -> dict:
        """`mandate credential create`: writes the credential and its mandate key into `folder`. Nothing is on
        chain yet. Returns the terms the command printed, with the credential's path."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        target = folder / "mandate.json"
        args = ["mandate", "credential", "create", "--principal", self.config.holder_account,
                "--payee", payee or self.config.settlement, "--cap", f"{Decimal(str(cap)):.2f}",
                "--budget", f"{Decimal(str(budget)):.2f}", "--expires-in", str(int(expires_in)),
                "--description", description, "--key", str(self.config.holder_key), "--out", str(target)]
        if max_occurrences:
            args += ["--max-occurrences", str(max_occurrences)]
        fields = self._ok(*args)
        for name in ("mandate.json", "mandate.key.json"):
            if (folder / name).exists():
                os.chmod(folder / name, 0o600)
        return {**_terms(fields), "credential": str(target)}

    def discard_credential(self, credential: str) -> None:
        """Removes a credential that was written and never bound."""
        folder = Path(credential).parent
        for name in ("mandate.json", "mandate.key.json"):
            (folder / name).unlink(missing_ok=True)

    def bind(self, credential: str) -> dict:
        fields = self._ok("mandate", "bind", "--credential", credential, "--key", str(self.config.holder_key))
        return {"mandate_id": _first(fields, "bound"), "transaction": _first(fields, "transaction")}

    def revoke(self, credential: str) -> dict:
        fields = self._ok("mandate", "revoke", "--credential", credential, "--key", str(self.config.holder_key))
        return {"mandate_id": _first(fields, "revoked"), "transaction": _first(fields, "transaction")}

    def status(self, credential: str) -> dict:
        return _terms(self._ok("mandate", "status", "--credential", credential))

    def pull(self, credential: str, to: str, amount: Any, payment_id: str, record_refusal: bool = False) -> dict:
        """`mandate pull`. Returns {"outcome": paid | refused | pending | held, ...}. A refusal is an answer, not
        an error. With `record_refusal` and an agent key that holds *USDZ for gas, a refused pull is sent anyway
        and the refusal is written to the chain in a transaction that moves nothing."""
        args = ["mandate", "pull", "--credential", credential, "--to", to, "--amount", f"{Decimal(str(amount)):.2f}",
                "--payment-id", payment_id]
        recording = record_refusal and self.config.agent_key is not None
        if recording:
            args += ["--key", str(self.config.agent_key), "--record-refusal"]
        code, out, err = self._run(*args)
        fields = _fields(out)
        said = _first(fields, "outcome") or ""
        text = redact((out + "\n" + err).strip())
        reason = _REASON.search(_first(fields, "reason") or "") or _REASON.search(err)
        outcome = ("paid" if said.startswith("paid") else "refused" if said.startswith("refused") else
                   "pending" if said.startswith("pending") else "held" if said.startswith("held") else
                   "refused" if code != 0 and reason else None)
        if outcome is None:
            raise MetalError(text[:600] or "metal-agent mandate pull gave no outcome")
        tx = _first(fields, "transaction")
        return {"outcome": outcome, "reason": reason.group(1) if reason and outcome != "paid" else None,
                "transaction": tx, "recorded": bool(tx) and outcome == "refused",
                "already_paid": "already paid" in out, "payer": _first(fields, "payer"),
                "payee": _first(fields, "payee") or to, "amount_usdz": _usdz(_first(fields, "amount")) or str(amount),
                "spent_usdz": _usdz(_first(fields, "spent")), "payment_id": payment_id, "said": text[:1200]}

    def settlement(self, tx: str) -> dict:
        """`status <tx>`: the settlement as the chain holds it."""
        fields = self._ok("status", tx)
        transfers = []
        for line in fields.get("transfer", []):
            m = re.match(r"([0-9.]+) \*USDZ from (0x[0-9a-fA-F]{40}) to (0x[0-9a-fA-F]{40})", line)
            if m:
                transfers.append({"amount_usdz": m.group(1), "from": m.group(2), "to": m.group(3)})
        return {"transaction": _first(fields, "transaction") or tx, "status": _first(fields, "status"),
                "block": _first(fields, "block"), "submitter": _first(fields, "submitter"),
                "gas": _first(fields, "gas"), "transfers": transfers}

    def verify(self, credential: str, tx: str | None = None) -> dict:
        """`mandate verify`: Metal's own check of the mandate and every payment and refusal under it, read from
        the chain alone. With `tx`, of that one transaction."""
        issuer = self.config.holder_key.with_name(self.config.holder_key.stem + ".issuer.public.json")
        args = ["mandate", "verify", "--credential", credential, "--issuer", str(issuer)]
        if tx:
            args += ["--tx", tx]
        code, out, err = self._run(*args)
        if "verified" not in out:
            raise MetalError(redact((err or out).strip())[:600] or "metal-agent mandate verify gave no result")
        return parse_verify(out, tx)

    def balance(self, address: str) -> str | None:
        """The address's *USDZ, read with eth_call. None when the endpoint does not answer."""
        import httpx
        data = "0x70a08231" + address.lower().removeprefix("0x").rjust(64, "0")
        try:
            reply = httpx.post(self.config.rpc_url, timeout=20.0, json={
                "jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": TOKEN, "data": data}, "latest"]})
            return str((Decimal(int(reply.json()["result"], 16)) / Decimal(10) ** 18).normalize())
        except Exception:
            return None


def parse_verify(out: str, tx: str | None = None) -> dict:
    steps, lines = [], []
    rows = out.splitlines()
    for i, line in enumerate(rows):
        m = re.match(r"step (\d) (pass|fail|skipped): (.*)", line)
        if m:
            detail = rows[i + 1].strip() if i + 1 < len(rows) and rows[i + 1].startswith(" ") else ""
            steps.append({"step": int(m.group(1)), "result": m.group(2), "title": m.group(3), "detail": detail})
        m = re.match(r"(payment|refusal(?: \((\w+)\))?) (0x[0-9a-fA-F]{64}) block (\d+): ([0-9.]+) \*USDZ to "
                     r"(0x[0-9a-fA-F]{40})", line)
        if m:
            lines.append({"kind": "payment" if m.group(1) == "payment" else "refusal", "reason": m.group(2),
                          "transaction": m.group(3), "block": m.group(4), "amount_usdz": m.group(5), "to": m.group(6)})
    return {"verified": bool(re.search(r"^verified yes$", out, re.M)), "steps": steps, "lines": lines,
            "transaction": tx, "at": now(),
            "command": "metal-agent mandate verify --credential <credential> --issuer <issuer public key>"
                       + (f" --tx {tx}" if tx else "") + " --network testnet"}


# ---- a fake chain for the tests ------------------------------------------------------------------------------

class FakeMetal:
    """An in-memory chain with the same calls as MetalCli. It enforces what a Metal account enforces: the payee,
    the cap, the budget, the number of payments, the expiry and a revocation, and it pays one payment id at most
    once. With `path` its state is kept in a file, so a test can stop one app and start another over it."""

    def __init__(self, holder_account: str = "0x" + "a1" * 20, settlement: str = "0x" + "5e" * 20,
                 agent_address: str = "0x" + "a9" * 20, balance: Any = "100", path: Path | str | None = None,
                 clock: Callable[[], float] = time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self.calls: list[tuple] = []
        self.fail: dict[str, Exception] = {}       # {"bind": MetalError(...)}: raised once by that call
        self.pending_pulls = 0                      # this many pulls answer "pending" before the outcome
        self.state = {"holder_account": holder_account, "settlement": settlement, "agent_address": agent_address,
                      "balances": {holder_account: str(balance)}, "mandates": {}, "transactions": {}, "counter": 0}
        if self.path and self.path.exists():
            self.state = json.loads(self.path.read_text())
        self.config = type("FakeConfig", (), {"holder_account": self.state["holder_account"],
                                              "settlement": self.state["settlement"],
                                              "agent_address": self.state["agent_address"],
                                              "agent_key": "fake"})()

    def _save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self.state, indent=1, sort_keys=True))

    def _called(self, name: str, *args: Any) -> None:
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.fail.pop(name)

    def _tx(self, body: dict) -> str:
        self.state["counter"] += 1
        tx = "0x" + hashlib.sha256(f"fake-metal-{self.state['counter']}".encode()).hexdigest()
        self.state["transactions"][tx] = {**body, "transaction": tx, "block": str(1000 + self.state["counter"])}
        return tx

    def count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def version(self) -> str:
        return "fake"

    def create_credential(self, folder: Path | str, *, cap: Any, budget: Any, expires_in: int, description: str,
                          payee: str | None = None, max_occurrences: int | None = 1) -> dict:
        self._called("create_credential", str(folder))
        self.state["counter"] += 1
        mandate_id = "0x" + hashlib.sha256(f"mandate-{self.state['counter']}".encode()).hexdigest()
        credential = f"{folder}/mandate.json"
        starts = int(self.clock()) // 86400 * 86400
        self.state["mandates"][credential] = {
            "mandate_id": mandate_id, "description": description, "principal": self.state["holder_account"],
            "token": TOKEN, "cap_usdz": f"{Decimal(str(cap)):.2f}", "budget_usdz": f"{Decimal(str(budget)):.2f}",
            "starts": starts, "expiry": int(self.clock()) + int(expires_in), "max_occurrences": max_occurrences,
            "payees": [payee or self.state["settlement"]], "bound": False, "revoked": False, "spent_usdz": "0",
            "payments": 0, "paid": {}, "log": []}
        self._save()
        return {**self._public(self.state["mandates"][credential]), "credential": credential}

    @staticmethod
    def _public(m: dict) -> dict:
        return {k: v for k, v in m.items() if k not in ("paid", "log")}

    def discard_credential(self, credential: str) -> None:
        self.state["mandates"].pop(credential, None)
        self._save()

    def bind(self, credential: str) -> dict:
        self._called("bind", credential)
        m = self.state["mandates"][credential]
        m["bound"] = True
        tx = self._tx({"status": "success", "transfers": [], "what": "bind"})
        self._save()
        return {"mandate_id": m["mandate_id"], "transaction": tx}

    def revoke(self, credential: str) -> dict:
        self._called("revoke", credential)
        m = self.state["mandates"][credential]
        m["revoked"] = True
        tx = self._tx({"status": "success", "transfers": [], "what": "revoke"})
        self._save()
        return {"mandate_id": m["mandate_id"], "transaction": tx}

    def status(self, credential: str) -> dict:
        self._called("status", credential)
        return {**self._public(self.state["mandates"][credential]), "account_type": "MetalAccount"}

    def _refusal(self, m: dict, to: str, amount: Decimal) -> str | None:
        """The reason the account refuses this payment, or None when it pays."""
        now_ = self.clock()
        balance = Decimal(self.state["balances"].get(m["principal"], "0"))
        if not m["bound"]:
            return "mandate_not_bound"
        if m["revoked"]:
            return "mandate_revoked"
        if now_ >= m["expiry"]:
            return "mandate_expired"
        if now_ < m["starts"]:
            return "mandate_outside_recurrence"
        if to.lower() not in [p.lower() for p in m["payees"]]:
            return "mandate_payee_not_listed"
        if amount > Decimal(m["cap_usdz"]):
            return "mandate_cap_exceeded"
        if Decimal(m["spent_usdz"]) + amount > Decimal(m["budget_usdz"]):
            return "mandate_budget_spent"
        if m["max_occurrences"] and m["payments"] >= m["max_occurrences"]:
            return "mandate_occurrences_used"
        if amount > balance:
            return "transfer_would_fail"
        return None

    def pull(self, credential: str, to: str, amount: Any, payment_id: str, record_refusal: bool = False) -> dict:
        self._called("pull", credential, to, str(amount), payment_id)
        m = self.state["mandates"][credential]
        amount = Decimal(str(amount)).quantize(USDZ_CENT)
        base = {"payer": m["principal"], "payee": to, "amount_usdz": str(amount), "payment_id": payment_id,
                "already_paid": False, "recorded": False, "reason": None, "transaction": None,
                "spent_usdz": m["spent_usdz"], "said": ""}
        if payment_id in m["paid"]:      # the same payment again: reported, and nothing is sent
            return {**base, "outcome": "paid", "transaction": m["paid"][payment_id], "already_paid": True,
                    "said": "already paid, nothing sent"}
        if self.pending_pulls > 0:
            self.pending_pulls -= 1
            return {**base, "outcome": "pending", "said": "outcome pending"}
        reason = self._refusal(m, to, amount)
        if reason:
            tx = None
            if record_refusal:
                tx = self._tx({"status": "success", "transfers": [], "what": f"refusal {reason}"})
                m["log"].append({"kind": "refusal", "reason": reason, "transaction": tx, "amount_usdz": str(amount),
                                 "to": to, "block": self.state["transactions"][tx]["block"]})
            self._save()
            return {**base, "outcome": "refused", "reason": reason, "transaction": tx, "recorded": bool(tx),
                    "said": f"outcome refused\nreason {reason} ({REFUSALS[reason]})"}
        balances = self.state["balances"]
        balances[m["principal"]] = str(Decimal(balances.get(m["principal"], "0")) - amount)
        balances[to] = str(Decimal(balances.get(to, "0")) + amount)
        m["spent_usdz"] = str(Decimal(m["spent_usdz"]) + amount)
        m["payments"] += 1
        tx = self._tx({"status": "success", "what": "pull", "submitter": "0x" + "fa" * 20,
                       "transfers": [{"amount_usdz": str(amount.normalize()), "from": m["principal"], "to": to}]})
        m["paid"][payment_id] = tx
        m["log"].append({"kind": "payment", "reason": None, "transaction": tx, "amount_usdz": str(amount), "to": to,
                         "block": self.state["transactions"][tx]["block"]})
        self._save()
        return {**base, "outcome": "paid", "transaction": tx, "spent_usdz": m["spent_usdz"], "said": "outcome paid"}

    def settlement(self, tx: str) -> dict:
        self._called("settlement", tx)
        held = self.state["transactions"].get(tx)
        if held is None:
            raise MetalError(f"the chain holds no transaction {tx}")
        return {"transaction": tx, "status": held["status"], "block": held["block"],
                "submitter": held.get("submitter"), "gas": "1", "transfers": held["transfers"]}

    def verify(self, credential: str, tx: str | None = None) -> dict:
        self._called("verify", credential, tx)
        m = self.state["mandates"][credential]
        lines = [l for l in m["log"] if tx is None or l["transaction"] == tx]
        ok = m["bound"] and (tx is None or bool(lines))
        steps = [{"step": n, "result": "pass" if ok else "fail", "title": title, "detail": ""} for n, title in (
            (1, "The mandate is bound on the principal's account"),
            (2, "The credential in hand states the bound limits, payees and mandate key"),
            (3, "The credential's signatures"),
            (4, "Each payment and refusal is inside the mandate at its block"))]
        return {"verified": ok, "steps": steps, "lines": lines, "transaction": tx, "at": now(), "command": "fake"}

    def balance(self, address: str) -> str | None:
        return self.state["balances"].get(address, "0")


# ---- the product's logic -------------------------------------------------------------------------------------

BY_CHAIN = [
    "Who can be paid: only Khutlisa's settlement address. A pull to any other address is refused.",
    "How much: no pull above the approved amount (at the scale), and no more than that in total.",
    "How often: one payment. A second pull under the same mandate is refused.",
    "Until when: after the holder's deadline the mandate has expired and a pull is refused.",
    "The holder's say: once the holder revokes the mandate, a pull is refused.",
]
BY_CODE = [
    "That the mandate's terms are the approval's terms: Khutlisa builds the mandate from the approval, shows the "
    "two side by side and refuses to pull under a mandate signed for other terms.",
    "The tolerance: if the owner would receive less than the holder's tolerance allows, the agent does not pull "
    "at all and asks.",
    "The bridge to Airwallex: the sandbox cannot receive *USDZ, so the settled pull is credited as a simulated "
    "deposit whose reference is the Metal transaction hash. One hash funds one claim once.",
    "Everything after the money has arrived: the conversion, the bank transfer, a replacement after a refused "
    "transfer, and the ledger check.",
]

# Words the payment screen and the claim's history need for the stops this module makes.
payouts.DECISION_TITLES.update({
    "funded_on_metal": "Pulled the holder's funds under the Metal mandate",
    "metal_no_pull": "Did not pull: the amount fell outside your tolerance",
    "metal_requoted": "Locked a new rate before pulling, inside your tolerance",
})
payouts.RULE_NAMES.update({"mandate": "Your mandate on Metal, enforced by the chain"})
payouts.VOID_REASONS.update({
    "mandate_revoked": "the holder revoked the Metal mandate before any money was pulled",
    "metal_refused": "Metal refused the pull under the mandate, so the terms that were approved cannot be carried out",
    "metal_settlement_differs": "the settlement on Metal is not the one the approval covers",
})


def _explain_refusal(facts: dict, plan: dict | None) -> str:
    reason = facts.get("reason") or "no reason given"
    words = REFUSALS.get(reason, "Metal gave this reason")
    if reason == "mandate_revoked":
        return ("The holder revoked the Metal mandate before any money was pulled. Metal refused the agent's pull "
                f"({reason}), nothing moved, and the claim is back with the holder. A new approval signs a new "
                "mandate.")
    return (f"Metal refused the agent's pull of {facts.get('amount_usdz')} *USDZ under the holder's mandate: "
            f"{reason} ({words}). Nothing moved, and the claim is back with the holder.")


payouts.EXPLAINERS.update({
    "mandate_revoked": _explain_refusal, "metal_refused": _explain_refusal,
    "metal_settlement_differs": lambda facts, plan: (
        "The pull settled on Metal, but the chain's record of it is not the payment the approval covers "
        f"({facts.get('why')}). Nothing has been credited at Airwallex. A person needs to look at this."),
})


class MetalFunding:
    """The holder's mandates and the agent's pulls, per claim. One file per claim holds what happened
    (`<claims>/<claim id>/metal.json`), and one file for all claims holds which transaction funded which claim
    (`<claims>/metal_funded.json`), so a hash can never fund two claims or one claim twice.

    `before_deposit` is the funding interface the payout machine calls (airwallex.advance): it returns True once
    the claim's money has settled on Metal and the payout's deposit reference is the transaction hash."""

    def __init__(self, store: cl.ClaimStore, chain, *, scale: Decimal = DEFAULT_SCALE,
                 clock: Callable[[], float] = time.time, keys_folder: Path | str | None = None):
        self.store = store
        self.chain = chain
        self.scale = Decimal(str(scale))
        self.clock = clock
        # Where credentials and mandate keys are written. Never inside the repository or the claims folder.
        self.keys_folder = Path(keys_folder) if keys_folder else HOME / "mandates"
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    # ---- files ---------------------------------------------------------------------------------------------

    @property
    def settlement(self) -> str:
        return self.chain.config.settlement

    @property
    def holder_account(self) -> str:
        return self.chain.config.holder_account

    def _lock(self, claim_id: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(claim_id, threading.RLock())

    def record_path(self, claim_id: str) -> Path:
        return self.store.files(claim_id) / "metal.json"

    def load(self, claim_id: str) -> dict:
        try:
            return json.loads(self.record_path(claim_id).read_text())
        except (OSError, ValueError):
            return {"claim_id": claim_id, "mandates": [], "pull": None, "refusals": [], "events": []}

    def _write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def save(self, record: dict) -> None:
        self._write(self.record_path(record["claim_id"]), record)

    def _event(self, record: dict, text: str, **facts: Any) -> None:
        record["events"].append({"at": now(), "text": text, **facts})

    @property
    def funded_path(self) -> Path:
        return self.store.folder / "metal_funded.json"

    def funded(self) -> dict:
        try:
            return json.loads(self.funded_path.read_text())
        except (OSError, ValueError):
            return {}

    def claim_hash(self, tx: str, claim_id: str) -> None:
        """Writes down that this transaction funds this claim. Raises if it already funds another."""
        with self.store.lock:
            held = self.funded()
            owner = held.get(tx.lower())
            if owner and owner != claim_id:
                raise MetalError(f"Metal transaction {tx} already funded another claim. One transaction funds one "
                                 "claim once.")
            if not owner:
                held[tx.lower()] = claim_id
                self._write(self.funded_path, held)

    def handover_date(self) -> str | None:
        try:
            held = json.loads((self.store.folder / "holder_handover.json").read_text())
        except (OSError, ValueError):
            held = {}
        try:
            return handover.clean(held)["handover_date"]
        except ValueError:
            return None

    @staticmethod
    def live_mandate(record: dict) -> dict | None:
        """The newest mandate that is bound and not revoked."""
        for m in reversed(record["mandates"]):
            if m.get("status") == "bound":
                return m
        return None

    # ---- the holder's side ---------------------------------------------------------------------------------

    def on_approval(self, claim: dict, funding: str | None) -> dict | None:
        """Called once the holder has approved. `funding` is the holder's choice for a first approval ("metal"
        or "bank"); None keeps the claim's choice, as when new terms are approved for a payment on hold. For a
        claim funded on Metal whose money has not been pulled yet, the holder signs the mandate now."""
        claim_id = claim["id"]
        if claim.get("estate") and funding == "metal":
            raise cl.ClaimError(409, cl.ESTATE_NOT_ON_METAL)
        with self._lock(claim_id):
            record = self.load(claim_id)
            pulled = bool((record.get("pull") or {}).get("transaction"))
            with self.store.lock:
                fresh = self.store.load(claim_id)
                if funding in ("metal", "bank") and fresh.get("funding", "bank") != funding:
                    if pulled:
                        raise cl.ClaimError(409, "This claim has already been funded on Metal. The way it is "
                                                 "funded cannot change now.")
                    fresh["funding"] = funding
                    self.store.save(fresh)
                claim = fresh
            live = self.live_mandate(record)
            if claim.get("funding") != "metal" and live is not None and not pulled:
                self._revoke(record, live, "the holder chose a bank deposit for this claim")
            if claim.get("funding") != "metal" or pulled:
                return None
            return self.sign_mandate(claim_id)

    def sign_mandate(self, claim_id: str) -> dict:
        """The holder signs and binds a mandate for the claim's approval as it stands. A mandate signed for an
        earlier approval is revoked first, so one claim never has two live mandates."""
        with self._lock(claim_id):
            claim = self.store.load(claim_id)
            if claim.get("estate"):
                raise cl.ClaimError(409, cl.ESTATE_NOT_ON_METAL)
            if claim.get("funding") != "metal":
                raise cl.ClaimError(409, "This claim is funded by a bank deposit, not on Metal.")
            if not claim.get("approval"):
                raise cl.ClaimError(409, "A mandate mirrors an approval. Approve the claim first.")
            record = self.load(claim_id)
            if (record.get("pull") or {}).get("transaction"):
                raise cl.ClaimError(409, "This claim has already been funded on Metal.")
            live = self.live_mandate(record)
            if live and live["terms_hash"] == claim["approval"]["terms_hash"]:
                return record
            wanted = wanted_terms(claim, self.settlement, self.scale, self.handover_date())
            expires_in = wanted["expiry"] - int(self.clock())
            if expires_in <= 0:
                raise cl.ClaimError(409, "The holder's deadline for this claim has passed, so no mandate can be "
                                         "signed for it. Approve the claim again.")
            balance = self.chain.balance(self.holder_account)
            if balance is not None and Decimal(balance) < Decimal(wanted["cap_usdz"]):
                raise cl.ClaimError(409, f"The holder's Metal account holds {Decimal(balance):,.2f} *USDZ, and this "
                                         f"claim needs {Decimal(wanted['cap_usdz']):,.2f} *USDZ at the scale in use. "
                                         "Fund the account first.")
            if live:
                self._revoke(record, live, "a new approval replaced the one this mandate was signed for")
            seq = len(record["mandates"]) + 1
            folder = self.keys_folder / f"{claim_id}-{seq}"
            issued = None
            for attempt in range(6):
                # The command takes a duration, not a moment. If the second ticks over on the way, the credential
                # is thrown away (nothing is on chain yet) and written again just after the next tick.
                if attempt:
                    time.sleep(1.02 - (time.time() % 1))
                issued = self.chain.create_credential(
                    folder, cap=wanted["cap_usdz"], budget=wanted["budget_usdz"],
                    expires_in=wanted["expiry"] - int(self.clock()), description=wanted["description"],
                    payee=wanted["payee"], max_occurrences=wanted["max_occurrences"])
                if issued["expiry"] == wanted["expiry"]:
                    break
                self.chain.discard_credential(issued["credential"])
            else:
                raise MetalError("The mandate's expiry could not be set to the approval's deadline to the second, "
                                 "so no mandate was signed. Try again.")
            mandate = {"seq": seq, "mandate_id": issued["mandate_id"], "credential": issued["credential"],
                       "terms_hash": wanted["terms_hash"], "approval_at": claim["approval"]["at"], "wanted": wanted,
                       "issued": {k: issued.get(k) for k in ("principal", "token", "cap_usdz", "budget_usdz", "starts",
                                                             "expiry", "max_occurrences", "payees", "description")},
                       "status": "issued", "issued_at": now()}
            record["mandates"].append(mandate)
            self.save(record)
            bound = self.chain.bind(issued["credential"])
            mandate.update({"status": "bound", "bind_transaction": bound["transaction"], "bound_at": now()})
            self._event(record, f"The holder signed mandate {seq} and bound it on its Metal account.",
                        transaction=bound["transaction"])
            self.save(record)
            self.read_chain(record, mandate)
            self.save(record)
            with self.store.lock:
                fresh = self.store.load(claim_id)
                fresh["history"].append({"state": fresh["state"], "at": cl.now(), "note":
                                         f"The holder signed a Metal mandate for this approval: one payment of up to "
                                         f"{Decimal(wanted['cap_usdz']):,.2f} *USDZ to Khutlisa's settlement address, "
                                         f"until {_when(wanted['expiry'])}. {scale_words(self.scale)}"})
                self.store.save(fresh)
            return record

    def read_chain(self, record: dict, mandate: dict) -> dict | None:
        """What the holder's account holds for this mandate right now, read from the chain."""
        try:
            status = self.chain.status(mandate["credential"])
        except MetalError as err:
            mandate["chain_problem"] = str(err)[:300]
            return None
        mandate.pop("chain_problem", None)
        mandate["chain"] = {**{k: status.get(k) for k in ("cap_usdz", "budget_usdz", "starts", "expiry", "payees",
                                                           "max_occurrences", "bound", "revoked", "spent_usdz",
                                                           "payments", "description", "principal")},
                            "read_at": now()}
        return mandate["chain"]

    def _revoke(self, record: dict, mandate: dict, why: str) -> None:
        done = self.chain.revoke(mandate["credential"])
        mandate.update({"status": "revoked", "revoke_transaction": done["transaction"], "revoked_at": now(),
                        "revoked_because": why})
        self._event(record, f"The holder revoked mandate {mandate['seq']}: {why}.", transaction=done["transaction"])
        self.save(record)
        self.read_chain(record, mandate)
        self.save(record)

    def revoke(self, claim_id: str) -> dict:
        """The holder revokes the claim's mandate. If no money has been pulled and the payment has not started,
        the approval is withdrawn here and the claim goes back to the holder. If the payment has started, the
        agent's next pull is refused by Metal and the payout machine sends the claim back."""
        with self._lock(claim_id):
            record = self.load(claim_id)
            live = self.live_mandate(record)
            if live is None:
                raise cl.ClaimError(409, "This claim has no live mandate to revoke.")
            pulled = bool((record.get("pull") or {}).get("transaction"))
            self._revoke(record, live, "the holder revoked it")
            if not pulled:
                with self.store.lock:
                    claim = self.store.load(claim_id)
                    if claim["state"] == cl.APPROVED and self.store.void_approval(
                            claim, payouts.VOID_REASONS["mandate_revoked"]):
                        self.store.save(claim)
            return record

    # ---- the agent's side: the funding interface -----------------------------------------------------------

    def before_deposit(self, payout: awx.Payout, client: awx.AirwallexClient,
                       clock: Callable[[], float] | None = None) -> bool:
        """For a claim funded on Metal: pull under the mandate, read the settlement from the chain and make its
        transaction hash the payout's deposit reference. Returns True when the payout machine may go on to the
        Airwallex deposit; False when it must wait or has been stopped. A claim funded by a bank deposit passes
        straight through."""
        claim_id = Path(payout.path).parent.name
        try:
            claim = self.store.load(claim_id)
        except cl.ClaimError:
            return True
        if claim.get("funding") != "metal":
            return True
        clock = clock or self.clock
        with self._lock(claim_id):
            record = self.load(claim_id)
            pull = record.get("pull") or {}
            if payout.deposit_id or (pull.get("transaction") and payout.deposit_reference == pull["transaction"]):
                return True
            if pull.get("transaction") and pull.get("checked"):     # stopped between the pull and the reference
                return self._hand_over(payout, record)
            approval = claim.get("approval")
            mandate = self.live_mandate(record)
            if not approval or mandate is None or mandate["terms_hash"] != approval["terms_hash"]:
                gone = next((m for m in reversed(record["mandates"]) if approval and m.get("status") == "revoked"
                             and m["terms_hash"] == approval["terms_hash"]), None)
                if gone is None:
                    raise ValueError("The holder has not signed a Metal mandate for this approval yet, so nothing "
                                     "can be pulled. The holder signs it from the holder's view.")
                mandate = gone      # signed for this approval and revoked since: the chain will say so
            # The checks other modules add before any money moves (rings.py holds a claim linked to others) run
            # here too, right before the pull: a claim held since its payment was confirmed is not funded.
            try:
                self.store.check_may_pay(claim)
            except cl.ClaimError as err:
                self._event(record, f"No pull was made: {err.message}")
                self.save(record)
                raise ValueError(f"Nothing was pulled on Metal. {err.message}") from None
            amount = to_usdz(payout.usd_amount, self.scale)
            if not self._still_inside_tolerance(payout, client, clock, record):
                return False
            if payout.what_if == "short_deposit":   # a pull is exact or it is nothing; this case cannot be staged
                payout.what_if = None
            try:
                result = self.chain.pull(mandate["credential"], self.settlement, amount, payment_id=claim_id,
                                         record_refusal=True)
            except MetalUnavailable:
                raise
            except MetalError as err:
                # No outcome is known. The same pull is asked for again under the same payment id, which pays at
                # most once, so nothing is assumed here.
                self._event(record, f"The pull gave no outcome ({str(err)[:200]}). It is asked for again.")
                self.save(record)
                return False
            if result["outcome"] == "pending":
                self._event(record, "The pull was sent and has no outcome yet. The same pull is asked for again; it "
                                    "pays at most once.")
                self.save(record)
                return False
            if result["outcome"] != "paid":
                return self._refused(payout, record, mandate, result, amount)
            record["pull"] = {"transaction": result["transaction"], "outcome": "paid", "payment_id": claim_id,
                              "mandate_seq": mandate["seq"], "mandate_id": mandate["mandate_id"],
                              "amount_usdz": str(amount), "stands_for_usd": str(to_usd(amount, self.scale)),
                              "approved_usd": str(awx.money(payout.usd_amount, "USD")), "at": now(),
                              "repeat_reported": result.get("already_paid", False)}
            self.save(record)
            if not self._check_settlement(payout, record, mandate, amount):
                return False
            return self._hand_over(payout, record)

    def _still_inside_tolerance(self, payout: awx.Payout, client: awx.AirwallexClient, clock, record: dict) -> bool:
        """Before any money leaves the holder: if the rate locked with the plan has run out, lock a new one and
        compare what the owner would receive with what they agreed to. Outside the holder's tolerance (or, with
        no instructions, whenever the lock ran out) the agent does not pull at all and asks the owner."""
        agreed = (payout.confirmed or {}).get("local_amount")
        if not payout.quote_id or not agreed or not awx._quote_expired(payout, clock):
            return True
        rules, currency = payout.instructions, payout.target_currency
        usd = awx.money(payout.quote_sell, "USD")
        before = {"rate": payout.client_rate, "valid_to": payout.quote_valid_to}
        quote = client.create_quote("USD", currency, sell_amount=usd, validity="HR_1")
        awx._take_quote(payout, quote, usd)
        payout.spot_checked = True
        route = payout.route if payout.route in (awx.PAY_WITH_QUOTE, awx.CONVERT_THEN_PAY) else awx.choose_route(currency)[0]
        now_local = awx.estimate(route, usd, currency, quote)["received"]["amount"]
        inside, short = ins.within_tolerance(agreed, now_local, rules)
        tolerance = rules["tolerance_percent"] if rules else "0"
        facts = {"old_rate": before["rate"], "new_rate": payout.client_rate, "old_local": str(Decimal(agreed)),
                 "new_local": now_local, "currency": currency, "lock_ended": before["valid_to"], "usd": str(usd),
                 "tolerance_percent": tolerance, "shortfall_percent": str(short), "before_pull": True}
        if rules and inside:
            payout.decide("metal_requoted", "tolerance",
                          f"The rate locked with the plan ran out before the holder's funds were pulled. A new rate "
                          f"was locked: {payout.client_rate} in place of {before['rate']}. It gives "
                          f"{Decimal(now_local):,.2f} {currency} against the {Decimal(agreed):,.2f} {currency} agreed, "
                          f"which is inside the tolerance of {tolerance} percent, so the pull went ahead.", **facts)
            payout.save()
            return True
        payout.decide("metal_no_pull", "tolerance",
                      f"The rate locked with the plan ran out before the holder's funds were pulled. At the new rate "
                      f"of {payout.client_rate} the owner would receive {Decimal(now_local):,.2f} {currency}, "
                      f"{short} percent less than the {Decimal(agreed):,.2f} {currency} agreed. That is outside "
                      f"{'the tolerance of ' + tolerance + ' percent' if rules else 'what may be decided without standing instructions'}"
                      ", so nothing was pulled from the holder's Metal account and the owner is asked.", **facts)
        self._event(record, f"The agent did not pull: the owner would receive {short} percent less than agreed, "
                            "outside the tolerance. The mandate is untouched.")
        self.save(record)
        payout.pause(awx.HELD, "rate_lock_expired", ["claimant"], awx.DEPOSIT_EXPECTED, facts,
                     f"the rate lock ran out before the pull; {now_local} {currency} now, {agreed} {currency} was "
                     "agreed; nothing was pulled on Metal")
        return False

    def _refused(self, payout: awx.Payout, record: dict, mandate: dict, result: dict, amount: Decimal) -> bool:
        """Metal refused the agent's pull. Nothing moved. The claim goes back to the holder with the reason."""
        reason = result.get("reason") or result["outcome"]
        refusal = {"at": now(), "case": "the agent's pull for this claim", "staged": False, "reason": reason,
                   "words": REFUSALS.get(reason, "Metal gave this reason"), "transaction": result.get("transaction"),
                   "recorded_on_chain": bool(result.get("recorded")), "amount_usdz": str(amount),
                   "payee": self.settlement, "mandate_seq": mandate["seq"]}
        record["refusals"].append(refusal)
        if reason == "mandate_revoked" and mandate.get("status") == "bound":
            mandate.update({"status": "revoked", "revoked_at": now(), "revoked_because": "found revoked on chain"})
        self._event(record, f"Metal refused the pull: {reason}.", transaction=result.get("transaction"))
        self.read_chain(record, mandate)
        self.save(record)
        kind = "mandate_revoked" if reason == "mandate_revoked" else "metal_refused"
        facts = {"reason": reason, "amount_usdz": str(amount), "transaction": result.get("transaction"),
                 "mandate_id": mandate["mandate_id"], "funds": None}
        payout.pause(awx.HELD, kind, ["payer"], awx.DEPOSIT_EXPECTED, facts,
                     f"Metal refused the pull under mandate {mandate['mandate_id'][:12]}: {reason}; nothing moved")
        return False

    def _check_settlement(self, payout: awx.Payout, record: dict, mandate: dict, amount: Decimal) -> bool:
        """Reads the settlement from the chain and Metal's own verification of it. The pull counts only if the
        chain shows one transfer of exactly the amount from the holder's account to the settlement address."""
        pull = record["pull"]
        seen = self.chain.settlement(pull["transaction"])
        mine = [t for t in seen.get("transfers", [])
                if t["from"].lower() == self.holder_account.lower() and t["to"].lower() == self.settlement.lower()]
        why = None
        if seen.get("status") != "success":
            why = f"the transaction's status is {seen.get('status')}"
        elif len(mine) != 1 or Decimal(mine[0]["amount_usdz"]) != amount:
            why = (f"the chain shows {[t['amount_usdz'] for t in mine] or 'no transfer'} from the holder's account to "
                   f"the settlement address, and {amount} *USDZ was pulled")
        pull["settlement"] = seen
        if why is None:
            try:
                pull["verification"] = self.chain.verify(mandate["credential"], pull["transaction"])
            except MetalError as err:
                pull["verification"] = {"verified": False, "problem": str(err)[:300], "steps": [], "lines": [],
                                        "at": now()}
            if not pull["verification"].get("verified"):
                why = "Metal's own verification of the payment against the mandate did not pass"
        if why is None:
            try:
                self.claim_hash(pull["transaction"], record["claim_id"])
            except MetalError as err:
                why = str(err)
        if why:
            pull["problem"] = why
            self._event(record, f"The pull was not accepted as funding: {why}.")
            self.save(record)
            payout.pause(awx.HELD, "metal_settlement_differs", ["payer"], awx.DEPOSIT_EXPECTED,
                         {"why": why, "transaction": pull["transaction"], "funds": None},
                         f"the settlement of {pull['transaction']} is not the approved payment: {why}")
            return False
        pull["checked"] = True
        mandate["status"] = "spent"
        self._event(record, f"The pull settled on Metal: {amount} *USDZ from the holder's account to Khutlisa's "
                            "settlement address, read from the chain and verified against the mandate.",
                    transaction=pull["transaction"])
        self.read_chain(record, mandate)
        self.save(record)
        return True

    def _hand_over(self, payout: awx.Payout, record: dict) -> bool:
        """Makes the Metal transaction hash the deposit reference. The payout machine then looks the hash up in
        Airwallex's deposits before it credits anything, so the same hash is never credited twice."""
        pull = record["pull"]
        self.claim_hash(pull["transaction"], record["claim_id"])
        if payout.deposit_reference != pull["transaction"]:
            payout.deposit_reference = pull["transaction"]
            payout.decide("funded_on_metal", "mandate",
                          f"Pulled {Decimal(pull['amount_usdz']):,.2f} *USDZ from the holder's Metal account under "
                          f"its mandate, which stands for {Decimal(pull['approved_usd']):,.2f} US dollars of this "
                          f"claim. The settlement was read from the chain and passed Metal's own verification. "
                          f"Transaction {pull['transaction']}. The Airwallex sandbox cannot receive *USDZ, so the "
                          "same amount is credited as a simulated deposit whose reference is that transaction "
                          "hash.", transaction=pull["transaction"], amount_usdz=pull["amount_usdz"],
                          scale=str(self.scale))
            payout.save()
        return True

    def attempt(self, claim_id: str, case: str) -> dict:
        """Tells the agent to overstep the mandate in one named way, so the chain's refusal can be seen. The
        attempt is real: it is signed with the mandate key and sent. Nothing moves when Metal refuses it."""
        if case not in ATTEMPTS:
            raise cl.ClaimError(422, "Choose one of the attempts on offer.")
        with self._lock(claim_id):
            self.store.load(claim_id)
            record = self.load(claim_id)
            pull = record.get("pull") or {}
            mandate = self.live_mandate(record) or next(
                (m for m in reversed(record["mandates"]) if m.get("status") in ("spent", "revoked")), None)
            if mandate is None:
                raise cl.ClaimError(409, "This claim has no mandate on Metal yet.")
            cap = Decimal(mandate["wanted"]["cap_usdz"])
            n = sum(1 for r in record["refusals"] if r.get("staged")) + 1
            if case == "over_cap":
                to, amount = self.settlement, cap + USDZ_CENT
            elif case == "wrong_payee":
                to, amount = self.chain.config.agent_address, cap
                if not to or to.lower() == self.settlement.lower():
                    raise cl.ClaimError(409, "No second address is set up to try a pull to.")
            else:
                if not pull.get("checked"):
                    raise cl.ClaimError(409, "A second pull can be tried only after the claim has been funded.")
                to, amount = self.settlement, cap
            result = self.chain.pull(mandate["credential"], to, amount, payment_id=f"{claim_id}-{case}-{n}",
                                     record_refusal=True)
            if result["outcome"] == "paid":      # must not happen; say so loudly if the chain ever allows it
                self._event(record, f"A staged attempt ({case}) was paid by Metal. This should be impossible.",
                            transaction=result.get("transaction"))
                self.save(record)
                raise MetalError(f"Metal paid a pull that should have been refused ({case}). Transaction "
                                 f"{result.get('transaction')}.")
            reason = result.get("reason") or result["outcome"]
            refusal = {"at": now(), "case": ATTEMPTS[case], "case_key": case, "staged": True, "reason": reason,
                       "words": REFUSALS.get(reason, "Metal gave this reason"),
                       "transaction": result.get("transaction"), "recorded_on_chain": bool(result.get("recorded")),
                       "amount_usdz": str(amount), "payee": to, "mandate_seq": mandate["seq"]}
            record["refusals"].append(refusal)
            self._event(record, f"Staged attempt, {ATTEMPTS[case].lower()}: Metal refused it ({reason}).",
                        transaction=result.get("transaction"))
            self.read_chain(record, mandate)
            self.save(record)
            return refusal

    def verify(self, claim_id: str) -> dict:
        """Runs Metal's own verification of the claim's mandate and everything under it, afresh."""
        with self._lock(claim_id):
            record = self.load(claim_id)
            if not record["mandates"]:
                raise cl.ClaimError(409, "This claim has no mandate on Metal yet.")
            mandate = record["mandates"][-1]
            mandate["verification"] = self.chain.verify(mandate["credential"])
            self.read_chain(record, mandate)
            self.save(record)
            return record

    # ---- what the screens show -----------------------------------------------------------------------------

    def compare(self, claim: dict, mandate: dict) -> list[dict]:
        """The approval's terms beside the mandate's, term by term. The mandate's side is what the chain holds
        when it has been read, otherwise what the credential states."""
        wanted = mandate["wanted"]
        on_chain = mandate.get("chain") or mandate.get("issued") or {}
        source = "read from the chain" if mandate.get("chain") else "as the credential states"
        scale = Decimal(wanted["scale"])
        usd = Decimal(wanted["approved_usd"])
        cap, budget = Decimal(on_chain.get("cap_usdz") or 0), Decimal(on_chain.get("budget_usdz") or 0)
        payees = [p.lower() for p in on_chain.get("payees") or []]
        rows = [
            {"term": "Who may be paid", "approval": "Khutlisa's settlement address, and no other",
             "mandate": ", ".join(on_chain.get("payees") or []) or "any address",
             "same": payees == [wanted["payee"].lower()]},
            {"term": "Most per payment", "approval": f"{usd:,.2f} USD, what the holder is to send for this claim",
             "mandate": f"{cap:,.2f} *USDZ, which stands for {to_usd(cap, scale):,.2f} USD",
             "same": cap == Decimal(wanted["cap_usdz"])},
            {"term": "Most in total", "approval": f"{usd:,.2f} USD, once",
             "mandate": f"{budget:,.2f} *USDZ, which stands for {to_usd(budget, scale):,.2f} USD",
             "same": budget == Decimal(wanted["budget_usdz"])},
            {"term": "Number of payments", "approval": "One. A second payment is never inside the limits",
             "mandate": str(on_chain.get("max_occurrences") or "unlimited"),
             "same": on_chain.get("max_occurrences") == 1},
            {"term": "Until", "approval": f"{_when(wanted['expiry'])}: {wanted['expiry_from']}",
             "mandate": _when(on_chain.get("expiry")), "same": on_chain.get("expiry") == wanted["expiry"]},
            {"term": "Reference", "approval": f"Claim {claim['id']}, approval terms {wanted['terms_hash'][:16]}",
             "mandate": on_chain.get("description") or "", "same": on_chain.get("description") == wanted["description"]},
        ]
        for row in rows:
            row["source"] = source
        return rows

    def view(self, claim: dict, payer: bool = False) -> dict:
        """Everything the "Funded on Metal" panel shows. Nothing here is a key, a credential or an endpoint."""
        record = self.load(claim["id"])
        funding = claim.get("funding", "bank")
        approval = claim.get("approval")
        live = self.live_mandate(record)
        newest = record["mandates"][-1] if record["mandates"] else None
        shown = live or newest
        pull = record.get("pull")

        def mandate_view(m: dict) -> dict:
            chain = m.get("chain") or {}
            current = bool(approval) and m["terms_hash"] == approval["terms_hash"]
            return {"seq": m["seq"], "mandate_id": m["mandate_id"], "status": m["status"],
                    "signed_at": m.get("bound_at"), "bind_transaction": m.get("bind_transaction"),
                    "bind_explorer": explorer_tx(m.get("bind_transaction")),
                    "revoke_transaction": m.get("revoke_transaction"),
                    "revoke_explorer": explorer_tx(m.get("revoke_transaction")),
                    "revoked_because": m.get("revoked_because"), "for_current_approval": current,
                    "terms": self.compare(claim, m), "all_same": all(r["same"] for r in self.compare(claim, m)),
                    "chain": chain and {"bound": chain.get("bound"), "revoked": chain.get("revoked"),
                                        "spent_usdz": chain.get("spent_usdz"), "budget_usdz": chain.get("budget_usdz"),
                                        "payments": chain.get("payments"), "read_at": chain.get("read_at")},
                    "chain_problem": m.get("chain_problem"), "verification": m.get("verification")}

        can = None
        if payer:
            unpulled = not (pull or {}).get("transaction")
            can = {"sign": funding == "metal" and bool(approval) and unpulled
                           and not (live and live["terms_hash"] == approval["terms_hash"]),
                   "revoke": live is not None,
                   "attempts": [{"key": k, "label": label} for k, label in ATTEMPTS.items()
                                if shown is not None and (k != "second_pull" or (pull or {}).get("checked"))],
                   "verify": shown is not None}
        return {
            "funding": funding, "network": NETWORK_NAME, "chain": CHAIN, "token": TOKEN_NAME, "token_address": TOKEN,
            "explorer": EXPLORER, "scale": {"usd_per_usdz": str(self.scale), "words": scale_words(self.scale)},
            "accounts": {"holder_account": self.holder_account, "holder_explorer": explorer_address(self.holder_account),
                         "settlement": self.settlement, "settlement_explorer": explorer_address(self.settlement)},
            "mandate": shown and mandate_view(shown),
            "earlier_mandates": [mandate_view(m) for m in record["mandates"] if m is not shown],
            "pull": pull and {**{k: pull.get(k) for k in ("transaction", "outcome", "amount_usdz", "stands_for_usd",
                                                          "approved_usd", "at", "payment_id", "problem", "checked")},
                              "explorer": explorer_tx(pull.get("transaction")),
                              "settlement": pull.get("settlement"), "verification": pull.get("verification")},
            "refusals": [{**r, "explorer": explorer_tx(r.get("transaction"))} for r in record["refusals"]],
            "events": record["events"][-30:],
            "enforced": {"by_chain": BY_CHAIN, "by_code": BY_CODE},
            "can": can,
        }
