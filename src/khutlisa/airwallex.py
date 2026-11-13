"""Airwallex sandbox money movement: a claimant receives US dollars and is paid at home in local currency.

Request shapes follow the public Airwallex API reference, and every call here has been run against the live
sandbox (docs/AIRWALLEX_FLOW.md says what was seen). Amounts are major units: 100 means one hundred dollars.

Three parts:
  AirwallexClient   one method per step of the flow, each returning the parsed JSON.
  SandboxSimulator  the sandbox-only calls (fake deposit, forced transfer status). Leave it out in production.
  Payout + advance  a state machine saved to a JSON file after every step, so a restart never pays twice.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

import httpx

from . import instructions as ins

SANDBOX_BASE_URL = "https://api.sandbox.airwallex.com"
CREDENTIALS_FILE = Path.home() / ".airwallex_sandbox"

# The API reference documents the first path. Our hackathon guide names the second. Tried in this order.
BENEFICIARY_SCHEMA_PATHS = ("/api/v1/beneficiary_api_schemas/generate", "/api/v1/beneficiaries/schema")

# Airwallex uses three spellings for "this request_id was already used", depending on the endpoint.
DUPLICATE_CODES = {"duplicate_request_id", "request_id_duplicate", "duplicate_request"}

TRANSFER_DEAD = {"FAILED", "CANCELLED"}
ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP"}
THREE_DECIMAL = {"BHD", "KWD", "OMR", "JOD", "TND"}

# Payout corridors we support first. `hold_in_wallet` comes from the Airwallex FX coverage table: MXN can be
# bought into the wallet with a conversion, PHP cannot (it is "convert + payout" only), so a PHP payout is funded
# straight from USD with a locked quote and Airwallex books the conversion inside the transfer. (Seen live: when a
# PHP transfer fails, Airwallex books the refund in PHP all the same, and a transfer can then be paid from it.)
CORRIDORS: dict[str, dict[str, Any]] = {
    "PHP": {"country": "PH", "hold_in_wallet": False},
    "MXN": {"country": "MX", "hold_in_wallet": True},
}


class AirwallexError(Exception):
    """An HTTP error from Airwallex, with the status and the `code` and `message` from the response body."""

    def __init__(self, status: int, code: str | None, message: str | None, source: str | None = None,
                 details: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.source = source
        self.details = details or {}
        text = f"Airwallex HTTP {status}: {code or 'no_code'}: {message or 'no message'}"
        if source:
            text += f" (source: {source})"
        super().__init__(text)

    @property
    def is_duplicate_request(self) -> bool:
        return self.code in DUPLICATE_CODES


class CredentialsError(RuntimeError):
    """Sandbox credentials are missing. The message names the keys, never their values."""


def load_credentials(env: dict[str, str] | None = None, path: str | os.PathLike | None = None) -> tuple[str, str]:
    """Return (client_id, api_key) from AWX_CLIENT_ID / AWX_API_KEY, or from ~/.airwallex_sandbox (KEY=VALUE lines).

    The environment wins over the file. Values are never printed or logged.
    """
    env = os.environ if env is None else env
    found = {k: env.get(k, "").strip() for k in ("AWX_CLIENT_ID", "AWX_API_KEY")}
    file = Path(path) if path else CREDENTIALS_FILE
    if not all(found.values()) and file.is_file():
        for line in file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            if key in found and not found[key]:
                found[key] = value.strip().strip("'\"")
    missing = [k for k, v in found.items() if not v]
    if missing:
        raise CredentialsError(f"missing {', '.join(missing)}: set them in the environment or in {file}")
    return found["AWX_CLIENT_ID"], found["AWX_API_KEY"]


def new_request_id() -> str:
    """A fresh UUID. Make one per operation, store it, and send the same one again only when retrying."""
    return str(uuid.uuid4())


def money(amount: Any, currency: str) -> Decimal:
    """Round to the number of decimals the currency supports (2 for USD, PHP and MXN)."""
    places = 0 if currency in ZERO_DECIMAL else 3 if currency in THREE_DECIMAL else 2
    return Decimal(str(amount)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _parse_time(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return None


class AirwallexClient:
    """Thin REST client. Every money-moving method takes an explicit request_id so a retry can reuse it."""

    TOKEN_TTL = 30 * 60   # documented lifetime; the `expires_at` field in the login response wins when present
    REFRESH_MARGIN = 120  # log in again this many seconds before the token runs out

    def __init__(self, client_id: str, api_key: str, base_url: str = SANDBOX_BASE_URL,
                 transport: httpx.BaseTransport | None = None, *, max_retries: int = 3, min_interval: float = 0.11,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self._client_id = client_id
        self._api_key = api_key
        self._http = httpx.Client(base_url=base_url.rstrip("/"), transport=transport, timeout=30.0)
        self._max_retries = max_retries
        self._min_interval = min_interval  # stays under the sandbox limit of 10 requests a second per endpoint
        self._clock = clock
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires = 0.0
        self._last_call = 0.0
        self.calls = 0     # requests sent, so a run can say how many calls it took

    def __repr__(self) -> str:  # never show credentials or the token
        return f"AirwallexClient(base_url={str(self._http.base_url)!r})"

    def close(self) -> None:
        self._http.close()

    # ---- step 1: login -------------------------------------------------------------------------------------

    def login(self, force: bool = False) -> dict:
        """POST /api/v1/authentication/login. Returns {"token", "expires_at"}; reuses the cached token until
        shortly before it expires."""
        if not force and self._token and self._clock() < self._token_expires - self.REFRESH_MARGIN:
            return {"token": self._token, "expires_at": self._token_expires, "cached": True}
        headers = {"x-client-id": self._client_id, "x-api-key": self._api_key}
        data = self._send("POST", "/api/v1/authentication/login", headers=headers)
        self._token = data["token"]
        self._token_expires = _parse_time(data.get("expires_at")) or (self._clock() + self.TOKEN_TTL)
        return data

    # ---- transport -----------------------------------------------------------------------------------------

    def _send(self, method: str, path: str, *, headers: dict | None = None, json_body: Any = None,
              params: dict | None = None, safe_to_repeat: bool = True) -> Any:
        """One logical call. 429 is always retried (the request was not processed). A 5xx or a network error is
        retried only when repeating is safe: a read, or a write that carries a request_id."""
        attempt = 0
        while True:
            wait = self._last_call + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_call = self._clock()
            self.calls += 1
            try:
                kwargs: dict[str, Any] = {"headers": headers, "params": params}
                if json_body is not None:
                    kwargs["json"] = json_body
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError:
                if safe_to_repeat and attempt < self._max_retries:
                    attempt += 1
                    self._sleep(min(2 ** (attempt - 1), 16))
                    continue
                raise
            retryable = response.status_code == 429 or (response.status_code >= 500 and safe_to_repeat)
            if retryable and attempt < self._max_retries:
                attempt += 1
                self._sleep(min(2 ** (attempt - 1), 16))
                continue
            if response.status_code >= 400:
                raise self._error(response)
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text

    @staticmethod
    def _error(response: httpx.Response) -> AirwallexError:
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return AirwallexError(response.status_code, None, (response.text or "")[:300] or None)
        details = body.get("details") if isinstance(body.get("details"), dict) else None
        return AirwallexError(response.status_code, body.get("code"), body.get("message"), body.get("source"), details)

    def _request(self, method: str, path: str, *, json_body: Any = None, params: dict | None = None) -> Any:
        safe = method == "GET" or (isinstance(json_body, dict) and bool(json_body.get("request_id")))
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        for second_try in (False, True):
            self.login()
            try:
                return self._send(method, path, headers={"Authorization": f"Bearer {self._token}"},
                                  json_body=json_body, params=params, safe_to_repeat=safe)
            except AirwallexError as err:
                if err.status == 401 and not second_try:  # token rejected early: log in once more and repeat
                    self._token = None
                    continue
                raise

    def _pages(self, path: str, params: dict | None = None, max_pages: int = 20) -> list[dict]:
        """Collect `items` across pages. Handles both paging styles: page_num/has_more and page/page_after."""
        params = dict(params or {})
        items: list[dict] = []
        for page_num in range(max_pages):
            data = self._request("GET", path, params=params) or {}
            if isinstance(data, list):      # some list endpoints (deposits) return a bare array, unpaged
                return items + data
            items.extend(data.get("items") or [])
            if data.get("page_after"):
                params["page"] = data["page_after"]
            elif data.get("has_more"):
                params["page_num"] = page_num + 1
            else:
                break
        return items

    # ---- step 2: USD global account ------------------------------------------------------------------------

    def list_global_accounts(self, **filters: Any) -> list[dict]:
        """GET /api/v1/global_accounts."""
        return self._pages("/api/v1/global_accounts", filters)

    def create_global_account(self, request_id: str, country_code: str = "US", currency: str = "USD",
                              transfer_method: str = "LOCAL", nick_name: str | None = None) -> dict:
        """POST /api/v1/global_accounts/create."""
        body: dict[str, Any] = {"request_id": request_id, "country_code": country_code,
                                "required_features": [{"currency": currency, "transfer_method": transfer_method}]}
        if nick_name:
            body["nick_name"] = nick_name
        return self._request("POST", "/api/v1/global_accounts/create", json_body=body)

    @staticmethod
    def _has_local_usd(account: dict) -> bool:
        feats = (account.get("supported_features") or []) + (account.get("required_features") or [])
        usd_local = any(f.get("currency") == "USD" and f.get("transfer_method") == "LOCAL" for f in feats)
        # Older list responses are flat: currency / payment_methods on the account itself.
        flat = account.get("currency") == "USD" and "LOCAL" in (account.get("payment_methods") or [])
        return account.get("country_code") == "US" and (usd_local or flat)

    def find_or_create_usd_global_account(self, request_id: str) -> dict:
        """Reuse an ACTIVE US account with local USD details, or create one. A repeated call with the same
        request_id finds the account made the first time."""
        accounts = self.list_global_accounts()
        usable = [a for a in accounts if self._has_local_usd(a) and a.get("status") in ("ACTIVE", "PROCESSING")]
        for account in usable:
            if account.get("status") == "ACTIVE":
                return account
        if usable:
            return usable[0]
        try:
            return self.create_global_account(request_id)
        except AirwallexError as err:
            if not err.is_duplicate_request:
                raise
            for account in self.list_global_accounts():
                if account.get("request_id") == request_id or account.get("id") == err.details.get("id"):
                    return account
            raise

    # ---- step 3: deposits and balances ---------------------------------------------------------------------

    def list_deposits(self, from_created_at: str | None = None, to_created_at: str | None = None) -> list[dict]:
        """GET /api/v1/deposits. Without dates Airwallex returns the last 30 days."""
        return self._pages("/api/v1/deposits", {"from_created_at": from_created_at, "to_created_at": to_created_at})

    def find_deposit(self, reference: str, global_account_id: str | None = None) -> dict | None:
        """The deposit carrying our reference string, if it has arrived."""
        for dep in self.list_deposits():
            if dep.get("reference") != reference:
                continue
            if global_account_id and dep.get("global_account_id") not in (None, global_account_id):
                continue
            return dep
        return None

    def balances(self) -> list[dict]:
        """GET /api/v1/balances/current."""
        return self._request("GET", "/api/v1/balances/current") or []

    def available_balance(self, currency: str) -> Decimal:
        for row in self.balances():
            if row.get("currency") == currency and row.get("account_type", "cash") == "cash":
                return Decimal(str(row.get("available_amount") or 0))
        return Decimal(0)

    def confirm_deposit(self, reference: str, global_account_id: str | None = None) -> dict:
        """Read the deposit back from GET /deposits and the USD balance. Returns {"deposit", "available"};
        `deposit` is None while it has not arrived."""
        deposit = self.find_deposit(reference, global_account_id)
        currency = (deposit or {}).get("currency") or "USD"
        return {"deposit": deposit, "available": str(self.available_balance(currency)), "currency": currency}

    # ---- step 4: quote and convert -------------------------------------------------------------------------

    def create_quote(self, sell_currency: str, buy_currency: str, *, sell_amount: Any = None,
                     buy_amount: Any = None, validity: str = "HR_1") -> dict:
        """POST /api/v1/fx/quotes/create. Give exactly one amount. Read the rate from `client_rate`."""
        if (sell_amount is None) == (buy_amount is None):
            raise ValueError("give exactly one of sell_amount or buy_amount")
        body: dict[str, Any] = {"sell_currency": sell_currency, "buy_currency": buy_currency, "validity": validity}
        if sell_amount is not None:
            body["sell_amount"] = float(money(sell_amount, sell_currency))
        else:
            body["buy_amount"] = float(money(buy_amount, buy_currency))
        return self._request("POST", "/api/v1/fx/quotes/create", json_body=body)

    def create_conversion(self, request_id: str, sell_currency: str, buy_currency: str, *, sell_amount: Any = None,
                          buy_amount: Any = None, quote_id: str | None = None) -> dict:
        """POST /api/v1/fx/conversions/create. With quote_id the conversion runs at the quote's client_rate."""
        if (sell_amount is None) == (buy_amount is None):
            raise ValueError("give exactly one of sell_amount or buy_amount")
        body: dict[str, Any] = {"request_id": request_id, "sell_currency": sell_currency, "buy_currency": buy_currency}
        if sell_amount is not None:
            body["sell_amount"] = str(money(sell_amount, sell_currency))
        else:
            body["buy_amount"] = str(money(buy_amount, buy_currency))
        if quote_id:
            body["quote_id"] = quote_id
        return self._request("POST", "/api/v1/fx/conversions/create", json_body=body)

    def find_conversion(self, request_id: str) -> dict | None:
        """GET /api/v1/fx/conversions?request_id=... The conversion already booked under this request_id."""
        for conv in self._pages("/api/v1/fx/conversions", {"request_id": request_id}, max_pages=1):
            if conv.get("request_id") == request_id:
                return conv
        return None

    # ---- step 5: beneficiary -------------------------------------------------------------------------------

    def beneficiary_schema(self, bank_country_code: str, account_currency: str, transfer_method: str = "LOCAL",
                           entity_type: str = "PERSONAL") -> dict:
        """The required fields for this corridor: {"condition": {...}, "fields": [{"path", "required", "rule"}]}."""
        body = {"bank_country_code": bank_country_code, "account_currency": account_currency,
                "transfer_method": transfer_method, "entity_type": entity_type, "type": "BANK_ACCOUNT"}
        last: AirwallexError | None = None
        for path in BENEFICIARY_SCHEMA_PATHS:
            try:
                return self._request("POST", path, json_body=body)
            except AirwallexError as err:
                if err.status != 404:
                    raise
                last = err
        raise last  # type: ignore[misc]

    def validate_beneficiary(self, payload: dict) -> Any:
        """POST /api/v1/beneficiaries/validate. Returns "OK"; a bad payload raises AirwallexError (HTTP 400)."""
        return self._request("POST", "/api/v1/beneficiaries/validate", json_body=payload)

    def create_beneficiary(self, payload: dict) -> dict:
        """POST /api/v1/beneficiaries/create. Bank details are checked here, not when paying. No request_id
        exists on this call; a second beneficiary with the same details moves no money."""
        return self._request("POST", "/api/v1/beneficiaries/create", json_body=payload)

    # ---- step 6: transfer ----------------------------------------------------------------------------------

    def create_transfer(self, request_id: str, beneficiary_id: str, transfer_currency: str, *,
                        transfer_amount: Any = None, source_amount: Any = None, source_currency: str | None = None,
                        quote_id: str | None = None, reason: str = "personal_remittance",
                        reference: str = "Khutlisa payout", transfer_method: str = "LOCAL",
                        fee_paid_by: str | None = None, swift_charge_option: str | None = None) -> dict:
        """POST /api/v1/transfers/create. Give exactly one of transfer_amount (what the person receives) or
        source_amount (what leaves the wallet). If this request_id already made a transfer, that transfer is
        returned and no second one is created.

        `fee_paid_by="BENEFICIARY"` makes Airwallex take its payout fee out of the amount sent, so exactly
        source_amount leaves the wallet and not a cent more. Without it the fee is charged on top."""
        if (transfer_amount is None) == (source_amount is None):
            raise ValueError("give exactly one of transfer_amount or source_amount")
        source_currency = source_currency or transfer_currency
        body: dict[str, Any] = {"request_id": request_id, "beneficiary_id": beneficiary_id,
                                "transfer_currency": transfer_currency, "source_currency": source_currency,
                                "transfer_method": transfer_method, "reason": reason, "reference": reference[:140]}
        if transfer_amount is not None:
            body["transfer_amount"] = str(money(transfer_amount, transfer_currency))
        else:
            body["source_amount"] = str(money(source_amount, source_currency))
        if quote_id:
            body["quote_id"] = quote_id
        if fee_paid_by:
            body["fee_paid_by"] = fee_paid_by
        if swift_charge_option and transfer_method == "SWIFT":
            body["swift_charge_option"] = swift_charge_option   # SHARED or PAYER; seen live: 15 and 25 US dollars
        try:
            return self._request("POST", "/api/v1/transfers/create", json_body=body)
        except AirwallexError as err:
            if not err.is_duplicate_request:
                raise
            existing_id = err.details.get("id")
            existing = self.get_transfer(existing_id) if existing_id else self.find_transfer(request_id)
            if existing is None:
                raise
            return existing

    def get_transfer(self, transfer_id: str) -> dict:
        """GET /api/v1/transfers/{id}."""
        return self._request("GET", f"/api/v1/transfers/{transfer_id}")

    def find_transfer(self, request_id: str) -> dict | None:
        """GET /api/v1/transfers?request_id=... The transfer already created under this request_id, if any."""
        for transfer in self._pages("/api/v1/transfers", {"request_id": request_id}, max_pages=1):
            if transfer.get("request_id") == request_id:
                return transfer
        return None

    def recent_transfers(self, page_size: int = 50) -> list[dict]:
        """GET /api/v1/transfers: the newest transfers of this account, one page."""
        return self._pages("/api/v1/transfers", {"page_size": page_size}, max_pages=1)

    def indicative_rate(self, sell_currency: str, buy_currency: str) -> dict:
        """GET /api/v1/fx/rates/current. The rate a client would get right now. Nothing is locked by asking."""
        return self._request("GET", "/api/v1/fx/rates/current",
                             params={"sell_currency": sell_currency, "buy_currency": buy_currency})

    # ---- step 8: proof of receipt --------------------------------------------------------------------------

    def financial_transactions(self, source_id: str | None = None, **filters: Any) -> list[dict]:
        """GET /api/v1/financial_transactions, optionally only the ledger rows for one source object."""
        return self._pages("/api/v1/financial_transactions", {"source_id": source_id, **filters})

    def ledger(self, source_id: str) -> list[dict]:
        """The rows Airwallex booked for one deposit, conversion or transfer, cut down to what we keep."""
        keep = ("id", "source_id", "source_type", "transaction_type", "amount", "net", "fee", "currency", "status",
                "description", "created_at", "settled_at", "client_rate", "currency_pair")
        return [{k: row.get(k) for k in keep if k in row} for row in self.financial_transactions(source_id=source_id)]

    def proof_of_receipt(self, transfer_id: str) -> dict:
        """The transfer as Airwallex reports it now, plus the ledger rows that moved the money."""
        transfer = self.get_transfer(transfer_id)
        keep = ("id", "request_id", "short_reference_id", "status", "transfer_amount", "transfer_currency",
                "source_amount", "source_currency", "amount_beneficiary_receives", "amount_payer_pays", "fee_amount",
                "fee_currency", "fee_paid_by", "transfer_method", "reference", "transfer_date", "dispatch_date",
                "created_at",
                "updated_at", "failure_reason", "failure_type")
        return {"transfer": {k: transfer[k] for k in keep if k in transfer},
                "financial_transactions": self.financial_transactions(source_id=transfer_id)}


class SandboxSimulator:
    """The sandbox-only calls, kept apart so production code can run with `simulator=None`.

    Both paths live under /api/v1/simulation and do not exist outside the sandbox.
    """

    def __init__(self, client: AirwallexClient):
        self._client = client

    #: The failure the sandbox is asked for when a "what if" case makes a transfer fail or come back.
    BANK_REFUSAL = "INVALID_ACCOUNT_NAME_OR_NUMBER"

    def deposit(self, global_account_id: str, amount: Any, reference: str, payer_name: str | None = None) -> dict:
        """Step 3. POST /api/v1/simulation/deposit/create. The money lands in the global account's own currency;
        the response may say PENDING while the balance is already there."""
        body: dict[str, Any] = {"global_account_id": global_account_id, "amount": float(money(amount, "USD")),
                                "reference": reference}
        if payer_name:
            body["payer_name"] = payer_name
        return self._client._request("POST", "/api/v1/simulation/deposit/create", json_body=body)

    def transition_transfer(self, transfer_id: str, next_status: str, failure_type: str | None = None) -> dict:
        """Step 7. POST /api/v1/simulation/transfers/{id}/transition. next_status is PROCESSING, SENT, PAID,
        FAILED or CANCELLED. FAILED needs a failure_type such as INVALID_ACCOUNT_NAME_OR_NUMBER."""
        body = {"next_status": next_status}
        if failure_type:
            body["failure_type"] = failure_type
        return self._client._request("POST", f"/api/v1/simulation/transfers/{transfer_id}/transition", json_body=body)


# ---- beneficiary payloads ----------------------------------------------------------------------------------

def clabe_check_digit(first17: str) -> int:
    """Check digit of a Mexican CLABE (weights 3, 7, 1 repeating)."""
    return (10 - sum((int(d) * w) % 10 for d, w in zip(first17, (3, 7, 1) * 6)) % 10) % 10


def is_valid_clabe(clabe: str) -> bool:
    return bool(re.fullmatch(r"\d{18}", clabe)) and clabe_check_digit(clabe[:17]) == int(clabe[17])


def local_beneficiary(currency: str, first_name: str, last_name: str, account_number: str, *,
                      swift_code: str | None = None, street_address: str, city: str, postcode: str | None = None,
                      state: str | None = None) -> dict:
    """The request body for /beneficiaries/validate and /beneficiaries/create for a person's local bank account.

    PHP (InstaPay / PESONet): account_number of 8 to 16 digits plus the bank's swift_code.
    MXN (SPEI): account_number is the 18-digit CLABE; no routing code.
    """
    country = CORRIDORS[currency]["country"]
    if currency == "MXN" and not is_valid_clabe(account_number):
        raise ValueError("a Mexican account number must be an 18-digit CLABE with a correct check digit")
    if currency == "PHP":
        if not re.fullmatch(r"\d{8,16}", account_number):
            raise ValueError("a Philippine account number must be 8 to 16 digits")
        if not swift_code:
            raise ValueError("a Philippine local payout needs the bank's swift_code")
    bank: dict[str, Any] = {"account_currency": currency, "bank_country_code": country,
                            "account_name": f"{first_name} {last_name}", "account_number": account_number}
    if swift_code:
        bank["swift_code"] = swift_code
    address = {"country_code": country, "street_address": street_address, "city": city}
    if postcode:
        address["postcode"] = postcode
    if state:
        address["state"] = state
    return {"beneficiary": {"type": "BANK_ACCOUNT", "entity_type": "PERSONAL", "first_name": first_name,
                            "last_name": last_name, "address": address, "bank_details": bank},
            "transfer_methods": ["LOCAL"]}


# Synthetic people for sandbox runs. The field set is from the Airwallex payout guides for each country. The
# values are ours: a real bank identifier (BPI's BIC, a CLABE with Banamex's bank code and a correct check
# digit) with made-up account numbers, which is what the sandbox validation asks for.
EXAMPLE_BENEFICIARIES: dict[str, dict] = {
    "PHP": local_beneficiary("PHP", "Maria", "Santos", "1234567890", swift_code="BOPIPHMM",
                             street_address="123 Ayala Avenue", city="Makati", postcode="1226"),
    "MXN": local_beneficiary("MXN", "Jose", "Hernandez", "002010077777777771",
                             street_address="Avenida Reforma 100", city="Ciudad de Mexico", postcode="06600",
                             state="MX-CMX"),
}


def schema_problems(schema: dict, payload: dict) -> list[str]:
    """Compare a payload with the corridor schema. Returns one line per required field that is missing or whose
    value does not match the schema's pattern. An empty list means the payload fits."""
    problems: list[str] = []
    for spec in schema.get("fields") or []:
        path = spec.get("path") or spec.get("key") or ""
        parts = path.split(".")
        value: Any = payload
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else None
        if value is None and parts[0] != "beneficiary":  # some schemas give paths relative to the beneficiary
            value = payload.get("beneficiary", {})
            for part in parts:
                value = value.get(part) if isinstance(value, dict) else None
        if path == "transfer_method" and value in (None, ""):   # the create body carries a list instead
            methods = payload.get("transfer_methods") or []
            value = methods[0] if methods else None
        if value in (None, ""):
            if spec.get("required"):
                problems.append(f"{path}: required")
            continue
        pattern = (spec.get("rule") or {}).get("pattern")
        if pattern and isinstance(value, str):
            try:
                if not re.fullmatch(pattern, value):
                    problems.append(f"{path}: does not match {pattern[:80]}")
            except re.error:
                pass
    return problems


# ---- payout state machine ----------------------------------------------------------------------------------

PLANNED = "PLANNED"                # a plan is on file and nothing has moved; waits for the claimant to confirm it
DEPOSIT_EXPECTED = "DEPOSIT_EXPECTED"
DEPOSIT_CONFIRMED = "DEPOSIT_CONFIRMED"
CONVERTED = "CONVERTED"
BENEFICIARY_READY = "BENEFICIARY_READY"
TRANSFER_CREATED = "TRANSFER_CREATED"
SENT = "SENT"
PAID = "PAID"
HELD = "HELD"                      # something changed before the money was sent; `hold` says what and who must agree
FAILED = "FAILED"                  # the bank refused or returned the transfer (`hold` gives the way forward), or
                                   # the deposit could not be used at all (no `hold`)
STATES = (PLANNED, DEPOSIT_EXPECTED, DEPOSIT_CONFIRMED, CONVERTED, BENEFICIARY_READY, TRANSFER_CREATED, SENT, PAID,
          HELD, FAILED)
STOPPED = (PLANNED, HELD, FAILED)  # states the machine leaves only when a person acts

# The three ways the money can travel. Which one is used is decided by `choose_route`.
PAY_WITH_QUOTE = "pay_with_quote"        # one transfer from US dollars; Airwallex converts inside it at the quote
CONVERT_THEN_PAY = "convert_then_pay"    # convert to the local currency first, then pay from that balance
PAY_FROM_BALANCE = "pay_from_balance"    # the claim's money is already in the local currency (a refund came back)

# Changes of circumstance the sandbox can be asked to stage, so the response to each can be seen.
WHAT_IFS = ("short_deposit", "transfer_fails", "transfer_returned", "rate_lock_expires")
SHORT_DEPOSIT_SHARE = Decimal("0.85")    # the staged short deposit is 85 percent of what was approved
RATE_TOLERANCE = Decimal("0.005")        # a re-quoted amount within half a percent of the confirmed one goes ahead
QUOTE_MARGIN = 5.0                       # seconds before a quote's end at which we stop relying on it
# What Airwallex has charged on every sandbox run so far. Used only to plan; the booked figures replace them.
EXPECTED_INCOMING_FEE_RATE = ins.EXPECTED_INCOMING_FEE_RATE
EXPECTED_PAYOUT_FEE_USD = ins.EXPECTED_PAYOUT_FEE_USD
SPOT_VALIDITY = {"convert_then_pay": "MIN_1", "pay_with_quote": "MIN_15"}   # the short quote tried beside the lock
RETURN_WATCH_SECONDS = 24 * 3600         # how long a PAID transfer is read again in case the bank returns it


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def choose_route(target_currency: str, funds_currency: str = "USD") -> tuple[str, str]:
    """(route, the reason in a sentence). The choice depends on where the claim's money is and on what
    Airwallex can do with the currency, so it changes when those change."""
    if funds_currency == target_currency:
        return PAY_FROM_BALANCE, (f"The money for this claim is already held in {target_currency}, because the "
                                  "earlier transfer came back in that currency. It is paid from that balance and "
                                  "nothing is converted a second time.")
    if not CORRIDORS.get(target_currency, {}).get("hold_in_wallet", True):
        return PAY_WITH_QUOTE, (f"Airwallex does not convert US dollars into a held balance of {target_currency}, "
                                "so the dollars are sent in one transfer and converted inside it, at a rate "
                                "locked beforehand with a quote.")
    return CONVERT_THEN_PAY, (f"Airwallex can hold {target_currency}, so the dollars are converted first at the "
                              "locked rate. The local amount is then fixed before any transfer is made, and the "
                              "transfer is paid from that balance.")


def estimate(route: str, funds: Any, target_currency: str, quote: dict | None, fees: dict | None = None) -> dict:
    """What the person should receive on this route from `funds` (US dollars, or the local currency for
    PAY_FROM_BALANCE), using a quote's rates and the payout fee Airwallex has charged so far (five US dollars, or
    its worth in the currency the transfer is paid from). `fees` may carry what Airwallex really charged on the
    last such payouts (`observed_payout_fees`); those figures are used in place of the expectation. Every figure
    is an expectation until Airwallex books it."""
    quote = quote or {}
    fees = fees or {}
    rate = _dec(quote.get("client_rate"))
    mid = _dec(quote.get("mid_rate") or quote.get("client_rate"))
    funds = _dec(funds)
    if route == PAY_WITH_QUOTE:
        seen = fees.get("USD")
        fee_usd = _dec(seen["amount"]) if seen else EXPECTED_PAYOUT_FEE_USD
        fee = {"amount": str(money(fee_usd, "USD")), "currency": "USD", "observed": bool(seen)}
        received = money(max(funds - fee_usd, 0) * rate, target_currency)
    else:
        local = funds if route == PAY_FROM_BALANCE else money(funds * rate, target_currency)
        seen = fees.get(target_currency)
        fee_local = money(seen["amount"], target_currency) if seen else money(EXPECTED_PAYOUT_FEE_USD * mid,
                                                                              target_currency)
        fee = {"amount": str(fee_local), "currency": target_currency, "observed": bool(seen)}
        received = max(local - fee_local, Decimal(0))
    return {"payout_fee": fee, "received": {"amount": str(money(received, target_currency)),
                                            "currency": target_currency}}


def observed_payout_fees(client: "AirwallexClient", target_currency: str) -> dict:
    """What Airwallex charged on this account's most recent local payouts in `target_currency`, by the currency
    the payout was funded from: {"USD": {...}} for a payout converted inside the transfer, {target: {...}} for one
    paid from a held balance. Empty where no such payout has been made yet."""
    seen: dict[str, dict] = {}
    try:
        transfers = client.recent_transfers()
    except (AirwallexError, httpx.HTTPError):
        return seen
    for t in transfers:
        if t.get("transfer_currency") != target_currency or t.get("transfer_method", "LOCAL") != "LOCAL":
            continue
        if t.get("fee_amount") is None or t.get("fee_paid_by") != "BENEFICIARY":
            continue
        source = t.get("fee_currency") or t.get("source_currency")
        if source and source not in seen:
            seen[source] = {"amount": str(money(t["fee_amount"], source)), "currency": source,
                            "at": t.get("created_at")}
    return seen


def compare_routes(target_currency: str, usd: Any, quote: dict, fees: dict | None = None) -> list[dict]:
    """Every way the dollars for this claim could reach the claimant, with what each would deliver at this
    quote and these fees. One of them is marked `chosen`: the one that delivers the most, and on a tie the one
    that fixes the local amount before any transfer is made."""
    can_hold = CORRIDORS.get(target_currency, {}).get("hold_in_wallet", True)
    out = []
    for route in (CONVERT_THEN_PAY, PAY_WITH_QUOTE):
        if route == CONVERT_THEN_PAY and not can_hold:
            out.append({"route": route, "available": False, "chosen": False, "payout_fee": None, "would_receive": None,
                        "why_not": f"Airwallex does not convert US dollars into a held balance of {target_currency} "
                                   "for this account."})
            continue
        got = estimate(route, usd, target_currency, quote, fees)
        fee = got["payout_fee"]
        out.append({"route": route, "available": True, "chosen": False, "why_not": None,
                    "payout_fee": {"amount": fee["amount"], "currency": fee["currency"],
                                   "basis": "what Airwallex charged on the last payout made this way" if fee["observed"]
                                   else "expected: no payout has been made this way yet"},
                    "would_receive": got["received"]})
    open_ = [r for r in out if r["available"]]
    best = max(open_, key=lambda r: (_dec(r["would_receive"]["amount"]), r["route"] == CONVERT_THEN_PAY))
    best["chosen"] = True
    return out


def claim_balance(ledger: list[dict], currency: str) -> Decimal:
    """What Airwallex's own rows for this claim add up to in one currency: the money the claim holds there."""
    return sum((_dec(r.get("amount")) for r in ledger if r.get("currency") == currency), Decimal(0))


@dataclass
class Payout:
    """One claimant's payout. Saved to `path` after every step.

    The request ids are made once and stored. Every retry and every restart sends the same ids again, and
    Airwallex refuses to act twice on one id. A replacement transfer after a failure gets a new id, made and
    saved at the moment the failed one is set aside in `attempts`.
    """
    path: str
    usd_amount: str                    # what the payer approved and is to send, in US dollars, as a decimal string
    target_currency: str               # "PHP" or "MXN"
    deposit_reference: str             # the reference string the incoming deposit carries
    beneficiary: dict                  # body for /beneficiaries/create, see local_beneficiary()
    payout_id: str = field(default_factory=new_request_id)
    state: str = DEPOSIT_EXPECTED
    global_account_request_id: str = field(default_factory=new_request_id)
    conversion_request_id: str = field(default_factory=new_request_id)
    transfer_request_id: str = field(default_factory=new_request_id)
    global_account_id: str | None = None
    deposit_id: str | None = None
    deposit_amount: str | None = None  # what actually arrived, in US dollars
    deposit_fee: str | None = None     # what Airwallex booked as its fee on the incoming deposit, in US dollars
    funds: dict | None = None          # {"amount", "currency"}: what this claim holds at Airwallex right now
    route: str | None = None
    plan: dict | None = None           # the written plan the claimant was shown (payouts.make_plan)
    confirmed: dict | None = None      # {"plan_id", "local_amount", "at"}: what the claimant last agreed to
    what_if: str | None = None         # one of WHAT_IFS, staged with the sandbox simulator
    what_if_done: bool = False
    quote_id: str | None = None
    quote_sell: str | None = None      # the US dollar amount the quote was made for
    quote_valid_to: str | None = None
    quote_validity: str = "HR_1"
    client_rate: float | None = None
    mid_rate: float | None = None
    conversion_id: str | None = None   # stays None unless the route converts into a held balance
    target_amount: str | None = None   # what the claimant receives, in target_currency
    beneficiary_id: str | None = None
    transfer_id: str | None = None
    transfer_status: str | None = None
    transfer_fee: dict | None = None   # {"amount", "currency", "paid_by"} as Airwallex set it on the transfer
    payer_pays: str | None = None      # what left the wallet for the transfer, fee included
    failure: str | None = None
    hold: dict | None = None           # why the payout is paused and who must agree before it goes on
    attempts: list = field(default_factory=list)    # transfers that failed or were returned, with their fate
    decisions: list = field(default_factory=list)   # dated notes of what was decided when something changed
    ledger: list = field(default_factory=list)      # Airwallex's own rows for this claim, re-read at each step
    paid_at: str | None = None
    watch_until: float | None = None   # a PAID transfer is read again until this time
    instructions: dict | None = None   # the holder's standing instructions, as bound into the approval
    deadline_at: str | None = None     # after this moment nothing more is sent without the holder
    claim_usd: str | None = None       # the claim's own amount; `usd_amount` is what the holder sends for it
    spot_checked: bool = False         # the lock has been compared with a short quote at the moment of use
    transfer_method: str = "LOCAL"     # "LOCAL" or "SWIFT"; a single claim is always paid by local rails
    swift_charge_option: str | None = None   # for SWIFT only: "PAYER", so the amount stated is the amount that arrives
    allocation: dict | None = None     # {"amount", "currency", "batch"}: this payout's share of a batch's money, when
                                       # it is funded by a batch (batch.py) and has no deposit of its own
    proof: dict | None = None
    history: list = field(default_factory=list)

    def save(self) -> None:
        """Write the whole record, then swap it into place, so a crash never leaves half a file."""
        target = Path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(asdict(self), fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Payout":
        data = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        payout = cls(**{k: v for k, v in data.items() if k in known})
        payout.path = str(path)
        if payout.state not in STATES:
            raise ValueError(f"unknown payout state {payout.state!r} in {path}")
        return payout

    @classmethod
    def open(cls, path: str | os.PathLike, **new_fields: Any) -> "Payout":
        """Load the payout stored at `path`, or create and save a new one from `new_fields`."""
        if Path(path).exists():
            return cls.load(path)
        payout = cls(path=str(path), **new_fields)
        payout.save()
        return payout

    def _move(self, state: str, note: str = "") -> None:
        self.state = state
        self.history.append({"state": state, "at": _now(), "note": note})
        self.save()

    def currency_locked(self) -> bool:
        """True once the claim's money is held in the payout currency, so the currency can no longer change."""
        return bool(self.funds and self.funds.get("currency") == self.target_currency) or bool(self.conversion_id)

    def note(self, kind: str, text: str, **facts: Any) -> None:
        """Keep a dated line of what was decided and why."""
        self.decisions.append({"at": _now(), "kind": kind, "text": text, **facts})

    def decide(self, kind: str, rule: str, text: str, **facts: Any) -> None:
        """Keep a dated line of something the machine decided by itself, inside the standing instructions, and
        which of them it rested on ("tolerance", "fees", "route", "deadline", or "safety" for the fixed rules)."""
        self.decisions.append({"at": _now(), "kind": kind, "text": text, "by": "agent", "rule": rule, **facts})

    def pause(self, state: str, kind: str, needs: list[str], resume: str, facts: dict, note: str) -> None:
        """Stop until everyone in `needs` has agreed. `resume` is the state the machine carries on from."""
        self.hold = {"kind": kind, "needs": list(needs), "resume": resume, "facts": facts, "at": _now()}
        self._move(state, note)

    def agreed(self, who: str) -> bool:
        """One of the people a pause waits for has agreed. Returns True when nobody is left and the payout has
        gone back to the state it carries on from."""
        if not self.hold:
            return False
        self.hold["needs"] = [n for n in self.hold.get("needs", []) if n != who]
        if self.hold["needs"]:
            self.save()
            return False
        done, self.hold = self.hold, None
        self.failure = None
        self.note("resumed", f"Everyone who had to agree after the {done['kind'].replace('_', ' ')} has agreed.",
                  after=done["kind"])
        self._move(done["resume"], f"carried on after {done['kind'].replace('_', ' ')}")
        return True


def refresh_ledger(payout: Payout, client: AirwallexClient) -> list[dict]:
    """Read again every row Airwallex has booked for this claim's deposit, conversion and transfers."""
    parts = [("deposit", payout.deposit_id), ("conversion", payout.conversion_id)]
    parts += [("earlier transfer", a.get("transfer_id")) for a in payout.attempts]
    parts += [("earlier conversion", a.get("conversion_id")) for a in payout.attempts if a.get("conversion_id")]
    parts.append(("transfer", payout.transfer_id))
    rows: list[dict] = []
    seen: set[str] = set()
    for part, source_id in parts:
        if not source_id:
            continue
        for row in client.ledger(source_id):
            key = row.get("id") or json.dumps(row, sort_keys=True)
            if key not in seen:
                seen.add(key)
                rows.append({**row, "source_id": row.get("source_id") or source_id, "part": part})
    rows.sort(key=lambda r: r.get("created_at") or "")
    payout.ledger = rows
    return rows


def _read_deposit(payout: Payout, client: AirwallexClient, deposit: dict) -> bool:
    """Take the deposit's amount and Airwallex's fee from what Airwallex booked. False while the deposit's own
    ledger row is not there yet (the fee is posted with it, a moment after the deposit first shows up)."""
    rows = refresh_ledger(payout, client)
    mine = [r for r in rows if r.get("source_id") == payout.deposit_id]
    arrived = money(deposit.get("amount") or 0, "USD")
    if mine:
        if not any(r.get("transaction_type") == "DEPOSIT" for r in mine):
            return False
        fee = -sum((_dec(r.get("amount")) for r in mine if r.get("transaction_type") == "FEE"), Decimal(0))
        held = claim_balance(rows, "USD")
    else:   # no ledger to read: fall back on the fee field of the deposit itself
        fee = _dec((deposit.get("fee") or {}).get("amount"))
        held = arrived - fee
    payout.deposit_amount = str(arrived)
    payout.deposit_fee = str(money(fee, "USD"))
    payout.funds = {"amount": str(money(held, "USD")), "currency": "USD"}
    return True


def _take_quote(payout: Payout, quote: dict, sell: Decimal, validity: str = "HR_1") -> None:
    payout.quote_validity = validity   # so the plan names the length of the lock that is really held
    payout.quote_id = quote["quote_id"]
    payout.client_rate = quote.get("client_rate")
    payout.mid_rate = quote.get("mid_rate")
    payout.quote_sell = str(sell)
    payout.quote_valid_to = quote.get("valid_to_at")


def _quote_expired(payout: Payout, clock: Callable[[], float]) -> bool:
    ends = _parse_time(payout.quote_valid_to)
    return ends is not None and clock() >= ends - QUOTE_MARGIN


def _figure(amount: Any, currency: str) -> str:
    return f"{_dec(amount):,.2f} {currency}"


def _past_deadline(payout: Payout, clock: Callable[[], float], resume: str) -> bool:
    """True, and the payout paused for the holder, when the deadline in the standing instructions has passed.
    Checked before each step that would commit or send money."""
    ends = _parse_time(payout.deadline_at)
    if ends is None or clock() <= ends:
        return False
    facts = {"deadline": payout.deadline_at, "funds": payout.funds,
             "days": (payout.instructions or {}).get("deadline_days")}
    payout.pause(HELD, "deadline_passed", ["payer"], resume, facts,
                 f"the deadline {payout.deadline_at} has passed; nothing more is sent without the holder")
    return True


def _take_transfer(payout: Payout, transfer: dict) -> None:
    currency = payout.target_currency
    payout.transfer_id, payout.transfer_status = transfer["id"], transfer.get("status")
    receives = transfer.get("amount_beneficiary_receives", transfer.get("transfer_amount"))
    if receives is not None:
        payout.target_amount = str(money(receives, currency))
    if transfer.get("fee_amount") is not None:
        payout.transfer_fee = {"amount": str(transfer["fee_amount"]),
                               "currency": transfer.get("fee_currency") or transfer.get("source_currency") or currency,
                               "paid_by": transfer.get("fee_paid_by")}
    if transfer.get("amount_payer_pays") is not None:
        payout.payer_pays = str(transfer["amount_payer_pays"])


def _keep_reason(payout: Payout, transfer: dict | None) -> None:
    """Keep the bank's reason from the answer that carries it. Seen live: the transfer reads FAILED with a
    failure_type and failure_reason for a moment, then CANCELLED with both fields empty."""
    transfer = transfer or {}
    reason = " ".join(str(x) for x in (transfer.get("failure_type"), transfer.get("failure_reason")) if x)
    if reason:
        payout.failure = reason
        payout.save()


def _transfer_dead(payout: Payout, client: AirwallexClient, transfer: dict, returned: bool) -> bool:
    """A transfer that ended FAILED or CANCELLED. Nothing is sent again by itself. Once Airwallex has booked the
    money back, the transfer is set aside in `attempts`, a fresh request id is made for a replacement, and the
    payout stops in FAILED until the bank details are corrected, the payer approves the new terms and the
    claimant agrees. Returns True when the transfer is dead (whether or not the refund is booked yet)."""
    payout.transfer_status = transfer.get("status")
    if payout.transfer_status not in TRANSFER_DEAD:
        return False
    reason = " ".join(str(x) for x in (transfer.get("failure_type"), transfer.get("failure_reason")) if x)
    if reason:   # Airwallex clears these a few seconds after the failure, so keep the first ones seen
        payout.failure = reason
    rows = refresh_ledger(payout, client)
    mine = [r for r in rows if r.get("source_id") == payout.transfer_id]
    back = [r for r in mine if r.get("transaction_type") == "PAYOUT_REVERSAL"]
    if mine and not back:
        payout.save()   # the refund is not booked yet; read again on the next step
        return True
    currency = (back[0].get("currency") if back else transfer.get("source_currency")) or payout.target_currency
    came_back = sum((_dec(r.get("amount")) for r in back), Decimal(0)) if back else _dec(transfer.get("source_amount"))
    fee = dict(payout.transfer_fee or {})
    payout.attempts.append({
        "transfer_id": payout.transfer_id, "request_id": payout.transfer_request_id,
        "beneficiary_id": payout.beneficiary_id, "conversion_id": payout.conversion_id,
        "status": payout.transfer_status, "reason": payout.failure or "no reason given by the bank",
        # the last four digits of the account the dead transfer was sent to, so a replacement can be told apart
        "account_last4": str((((payout.beneficiary or {}).get("beneficiary") or {}).get("bank_details") or {})
                             .get("account_number") or "")[-4:] or None,
        "fate": "returned by the bank after it was paid" if returned else "refused by the bank before it was paid",
        "was_to_receive": {"amount": payout.target_amount, "currency": payout.target_currency},
        "came_back": {"amount": str(money(came_back, currency)), "currency": currency},
        "fee_kept": fee or None, "at": _now()})
    facts = {"transfer_id": payout.transfer_id, "reason": payout.failure or "no reason given by the bank",
             "returned": returned, "came_back": {"amount": str(money(came_back, currency)), "currency": currency},
             "fee_kept": fee or None, "was_to_receive": {"amount": payout.target_amount,
                                                         "currency": payout.target_currency}}
    payout.funds = {"amount": str(money(came_back, currency)), "currency": currency}
    # A replacement is a new operation at Airwallex, so it gets new ids. The old ones stay with the attempt.
    payout.transfer_request_id, payout.conversion_request_id = new_request_id(), new_request_id()
    payout.transfer_id = payout.beneficiary_id = payout.conversion_id = None
    payout.quote_id = payout.quote_sell = payout.quote_valid_to = None
    payout.transfer_fee = payout.payer_pays = payout.proof = payout.target_amount = None
    payout.paid_at = payout.watch_until = None
    was_route = payout.route
    payout.route, why = choose_route(payout.target_currency, currency)
    resume = CONVERTED if payout.route == PAY_FROM_BALANCE else DEPOSIT_CONFIRMED
    if payout.route != was_route:
        payout.decide("route_changed", "route", why, came_back=facts["came_back"])
    facts["agreed_local"] = (payout.confirmed or {}).get("local_amount")
    payout.confirmed = None
    payout.pause(FAILED, "transfer_returned" if returned else "transfer_failed",
                 ["bank_details", "payer", "claimant"], resume, facts,
                 f"transfer {facts['transfer_id']} ended {payout.transfer_status}: {facts['reason']}")
    return True


def advance(payout: Payout, client: AirwallexClient, simulator: SandboxSimulator | None = None,
            clock: Callable[[], float] | None = None, funding: Any = None) -> Payout:
    """Do the next step for this payout and save it. Call again for the step after.

    If the outside world is not ready (deposit not in yet, bank has not confirmed) the state stays the same. A
    payout that is paused (`hold` with someone still to agree) or only planned does nothing here.
    With a `simulator` the sandbox is pushed along: the deposit is made and the transfer is moved to SENT and
    PAID, or made to fail when a "what if" case asks for it. Without one the function only reads and waits,
    which is the production behaviour.

    `funding` is how the holder's money reaches Airwallex when it is not a plain bank deposit. It has one method,
    `before_deposit(payout, client, clock)`, called while the deposit is expected: it returns True when the
    machine may go on to look for the deposit (for a claim funded on Metal: the pull has settled on chain and
    the deposit reference is now the transaction hash), and False when the machine must wait or has been
    stopped. With no `funding` the holder's money is the bank deposit, as before.
    """
    if payout.state == PLANNED or (payout.hold and payout.hold.get("needs")):
        return payout
    clock = clock or time.time
    gross = money(payout.usd_amount, "USD")
    currency = payout.target_currency
    staging = payout.what_if if (simulator is not None and not payout.what_if_done) else None

    if payout.state == DEPOSIT_EXPECTED:
        if not payout.global_account_id:
            payout.global_account_id = client.find_or_create_usd_global_account(payout.global_account_request_id)["id"]
            payout.save()
        if funding is not None and not payout.deposit_id and not funding.before_deposit(payout, client, clock):
            return payout
        deposit = client.find_deposit(payout.deposit_reference, payout.global_account_id)
        if deposit is None and simulator is not None:
            send = money(gross * SHORT_DEPOSIT_SHARE, "USD") if staging == "short_deposit" else gross
            simulator.deposit(payout.global_account_id, send, payout.deposit_reference)
            deposit = client.find_deposit(payout.deposit_reference, payout.global_account_id)
        if deposit is None:
            return payout
        payout.deposit_id = deposit.get("id")
        if deposit.get("status") in ("REJECTED", "REVERSED"):
            payout.failure = f"deposit {payout.deposit_id} was {deposit.get('status')}"
            payout._move(FAILED, payout.failure)
            return payout
        # The fee is booked when the deposit settles, a moment after it first appears. Reading it earlier is how
        # a fee of 0.00 was once shown for a deposit Airwallex charged 0.36 on. So wait for SETTLED and the row.
        if deposit.get("status") != "SETTLED" or not _read_deposit(payout, client, deposit):
            payout.save()
            return payout
        arrived = money(payout.deposit_amount, "USD")
        if arrived != gross:
            if payout.what_if == "short_deposit":
                payout.what_if_done = True
            facts = {"approved": str(gross), "arrived": str(arrived), "difference": str(abs(gross - arrived)),
                     "incoming_fee": payout.deposit_fee, "left": payout.funds["amount"], "currency": "USD"}
            inside, short = ins.within_tolerance(gross, arrived, payout.instructions)
            if arrived < gross and payout.instructions and inside:
                payout.decide("short_within_tolerance", "tolerance",
                              f"The holder sent {_figure(arrived, 'USD')}, which is {_figure(gross - arrived, 'USD')} "
                              f"({short} percent) less than the {_figure(gross, 'USD')} approved. That is inside the "
                              f"tolerance of {payout.instructions['tolerance_percent']} percent, so the payment carried "
                              "on without asking. The amount in the claimant's currency is checked against the same "
                              "tolerance when the rate is taken.", **facts, shortfall_percent=str(short))
                payout._move(DEPOSIT_CONFIRMED, f"deposit {payout.deposit_id} SETTLED, {short} percent short, "
                                                "inside the tolerance")
                return payout
            payout.pause(HELD, "short_deposit" if arrived < gross else "deposit_differs", ["payer", "claimant"],
                         DEPOSIT_CONFIRMED, facts,
                         f"deposit {payout.deposit_id} is {arrived} USD and {gross} USD was approved")
        else:
            payout._move(DEPOSIT_CONFIRMED, f"deposit {payout.deposit_id} SETTLED; incoming fee booked by Airwallex: "
                                            f"{payout.deposit_fee} USD")

    elif payout.state == DEPOSIT_CONFIRMED:
        if _past_deadline(payout, clock, DEPOSIT_CONFIRMED):
            return payout
        rules = payout.instructions
        deposit = client.find_deposit(payout.deposit_reference, payout.global_account_id)
        if deposit is not None:   # read the fee again: what Airwallex has booked now is what counts
            _read_deposit(payout, client, deposit)
        usd = money((payout.funds or {}).get("amount") or gross - _dec(payout.deposit_fee), "USD")
        if usd <= 0:
            payout.failure = "nothing is left of the deposit after Airwallex's fee"
            payout._move(FAILED, payout.failure)
            return payout
        payout.route = payout.route if payout.route in (PAY_WITH_QUOTE, CONVERT_THEN_PAY) else choose_route(currency)[0]
        done = client.find_conversion(payout.conversion_request_id) if payout.route == CONVERT_THEN_PAY else None
        if done is None:
            if staging == "rate_lock_expires" and payout.quote_id and not _quote_expired(payout, clock):
                payout.save()   # the staged case: hold the conversion back until the lock has really run out
                return payout
            expired = bool(payout.quote_id) and _quote_expired(payout, clock)
            fits = bool(payout.quote_id) and payout.quote_sell is not None and money(payout.quote_sell, "USD") == usd
            if not payout.quote_id or expired or not fits:
                before = {"rate": payout.client_rate, "valid_to": payout.quote_valid_to,
                          "local": (payout.confirmed or {}).get("local_amount")}
                quote = client.create_quote("USD", currency, sell_amount=usd, validity="HR_1")
                _take_quote(payout, quote, usd)
                payout.spot_checked = True      # this quote is fresh; there is no older lock to compare it with
                now_local = estimate(payout.route, usd, currency, quote)["received"]["amount"]
                if payout.confirmed and before["local"]:
                    if payout.what_if == "rate_lock_expires":
                        payout.what_if_done = True
                    was = _dec(before["local"])
                    drift = abs(_dec(now_local) - was) / was if was else Decimal(1)
                    inside, short = ins.within_tolerance(was, now_local, rules)
                    tolerance = rules["tolerance_percent"] if rules else str(RATE_TOLERANCE * 100)
                    facts = {"old_rate": before["rate"], "new_rate": payout.client_rate, "old_local": str(was),
                             "new_local": now_local, "currency": currency, "lock_ended": before["valid_to"],
                             "usd": str(usd), "tolerance_percent": tolerance, "shortfall_percent": str(short)}
                    # With standing instructions the one test is the tolerance, whatever made the new quote
                    # necessary. Without them a lock that ran out is always put to the claimant.
                    stop = (not inside) if rules else (expired or drift > RATE_TOLERANCE)
                    if stop:
                        payout.pause(HELD, "rate_lock_expired" if expired else "amount_changed", ["claimant"],
                                     DEPOSIT_CONFIRMED, facts,
                                     f"the rate lock {'ran out' if expired else 'no longer fits'}; new quote "
                                     f"{payout.quote_id} gives {now_local} {currency}, {was} {currency} was confirmed")
                        return payout
                    if rules:
                        why = ("The rate lock ran out before the money could be converted" if expired else
                               f"The amount to convert came to {_figure(usd, 'USD')}, which the lock was not made for")
                        how = (f"{abs(short)} percent more than" if short < 0 else
                               "the same as" if short == 0 else f"{short} percent less than")
                        payout.decide("requoted", "tolerance",
                                      f"{why}, so a new rate was locked for one hour: {payout.client_rate} in place "
                                      f"of {before['rate']}. It gives {_figure(now_local, currency)}, {how} the "
                                      f"{_figure(was, currency)} agreed. That is inside the tolerance of {tolerance} "
                                      "percent, so the payment carried on without asking.", **facts)
                    else:
                        payout.note("requoted", f"The amount to convert came to {usd} USD, so a new quote was taken. "
                                                f"It gives {now_local} {currency}, within {RATE_TOLERANCE * 100:f} "
                                                f"percent of the {was} {currency} that was confirmed, so the payout "
                                                "went ahead without asking again.", **facts)
                payout.save()
            elif rules and rules.get("route_rule") == "most_to_claimant" and not payout.spot_checked:
                # The lock taken with the plan is a floor. At the moment it is used, a short quote is taken beside
                # it, and whichever delivers more to the claimant is the one that is used.
                validity = SPOT_VALIDITY[payout.route]
                spot = client.create_quote("USD", currency, sell_amount=usd, validity=validity)
                locked = {"client_rate": payout.client_rate, "mid_rate": payout.mid_rate}
                with_lock = estimate(payout.route, usd, currency, locked)["received"]["amount"]
                with_spot = estimate(payout.route, usd, currency, spot)["received"]["amount"]
                facts = {"locked_rate": payout.client_rate, "spot_rate": spot.get("client_rate"),
                         "with_lock": with_lock, "with_spot": with_spot, "currency": currency, "usd": str(usd)}
                payout.spot_checked = True
                if _dec(with_spot) > _dec(with_lock):
                    _take_quote(payout, spot, usd, validity)
                    payout.decide("better_rate", "route",
                                  f"The rate locked with the plan was {facts['locked_rate']}, which gives "
                                  f"{_figure(with_lock, currency)}. A quote taken at the moment of use was "
                                  f"{facts['spot_rate']}, which gives {_figure(with_spot, currency)}. The better one "
                                  f"was used: {_figure(_dec(with_spot) - _dec(with_lock), currency)} more for the "
                                  "claimant.", **facts)
                else:
                    payout.decide("kept_lock", "route",
                                  f"A quote taken at the moment of use was {facts['spot_rate']}, which gives "
                                  f"{_figure(with_spot, currency)}. The rate locked with the plan, "
                                  f"{facts['locked_rate']}, gives {_figure(with_lock, currency)}, so the lock was "
                                  "kept.", **facts)
                payout.save()
            if payout.route == CONVERT_THEN_PAY:
                try:
                    done = client.create_conversion(payout.conversion_request_id, "USD", currency, sell_amount=usd,
                                                    quote_id=payout.quote_id)
                except AirwallexError as err:
                    if not err.is_duplicate_request:
                        raise
                    done = client.find_conversion(payout.conversion_request_id)
                    if done is None:
                        raise
        if done is not None:
            payout.conversion_id = done.get("conversion_id") or done.get("id")
            payout.client_rate = done.get("client_rate", payout.client_rate)
            bought = money(done["buy_amount"], currency)
            payout.target_amount = str(bought)
            payout.funds = {"amount": str(bought), "currency": currency}
            payout._move(CONVERTED, f"conversion {payout.conversion_id} {done.get('status')}")
        else:
            payout.target_amount = estimate(payout.route, usd, currency, {"client_rate": payout.client_rate,
                                                                          "mid_rate": payout.mid_rate})["received"]["amount"]
            payout._move(CONVERTED, f"rate locked by quote {payout.quote_id}; converts inside the transfer")

    elif payout.state == CONVERTED:
        country = (payout.beneficiary["beneficiary"]["bank_details"].get("bank_country_code")
                   or CORRIDORS.get(currency, {}).get("country"))
        entity = payout.beneficiary["beneficiary"].get("entity_type", "PERSONAL")
        problems = schema_problems(client.beneficiary_schema(country, currency, payout.transfer_method, entity),
                                   payout.beneficiary)
        if problems:
            raise ValueError("beneficiary does not fit the Airwallex schema: " + "; ".join(problems))
        client.validate_beneficiary(payout.beneficiary)
        payout.beneficiary_id = client.create_beneficiary(payout.beneficiary)["id"]
        payout._move(BENEFICIARY_READY, f"beneficiary {payout.beneficiary_id}")

    elif payout.state == BENEFICIARY_READY:
        # The lock: a replacement is never sent while an earlier transfer for this claim could still pay.
        seen_dead = None
        for attempt in payout.attempts:
            earlier = client.get_transfer(attempt["transfer_id"])
            seen_dead = earlier.get("status")
            if earlier.get("status") not in TRANSFER_DEAD:
                raise ValueError(f"an earlier transfer for this claim ({attempt['transfer_id']}) is "
                                 f"{earlier.get('status')} at Airwallex, so no replacement is sent")
        # Ask first: a crash after Airwallex accepted the transfer but before we saved leaves it findable here.
        transfer = client.find_transfer(payout.transfer_request_id)
        if transfer is None and _past_deadline(payout, clock, BENEFICIARY_READY):
            return payout
        if transfer is None and payout.attempts and not any(
                d.get("kind") == "replacement_cleared" and d.get("request_id") == payout.transfer_request_id
                for d in payout.decisions):
            dead = payout.attempts[-1]
            payout.decide("replacement_cleared", "safety",
                          f"Before sending the replacement, the earlier transfer {dead['transfer_id']} was read again "
                          f"at Airwallex. It is {seen_dead or dead['status']}, so it can no longer pay. One replacement is sent "
                          "under a new request id, for exactly what Airwallex's records say this claim holds.",
                          request_id=payout.transfer_request_id, earlier=dead["transfer_id"])
        if transfer is None:
            route = payout.route or (CONVERT_THEN_PAY if payout.conversion_id else PAY_WITH_QUOTE)
            source = "USD" if route == PAY_WITH_QUOTE else currency
            amount = money((payout.funds or {}).get("amount") or 0, source)
            rows = refresh_ledger(payout, client)
            if rows or payout.allocation:   # never send more than Airwallex's own rows say this claim holds
                held = claim_balance(rows, source)
                # A payout funded by a batch has no deposit of its own. What it may send is its share of the
                # batch's money, less everything Airwallex has booked for its own transfers so far.
                if payout.allocation and payout.allocation.get("currency") == source:
                    held += _dec(payout.allocation.get("amount"))
                amount = min(amount, money(held, source))
            if amount <= 0:
                payout.failure = f"this claim holds no {source} at Airwallex to send"
                payout._move(FAILED, payout.failure)
                return payout
            # The payout fee comes out of the claim's own money: exactly `amount` leaves the wallet, fee included.
            try:
                transfer = client.create_transfer(payout.transfer_request_id, payout.beneficiary_id, currency,
                                                  source_amount=amount, source_currency=source,
                                                  quote_id=payout.quote_id if route == PAY_WITH_QUOTE else None,
                                                  fee_paid_by="BENEFICIARY", reference=payout.deposit_reference,
                                                  transfer_method=payout.transfer_method,
                                                  swift_charge_option=payout.swift_charge_option)
            except AirwallexError as err:
                if err.code != "quote_expired" or route != PAY_WITH_QUOTE:
                    raise
                # The lock ran out in the moments before the transfer. Nothing was sent. Go back to the rate
                # step, which takes a new quote and puts the new amount to the claimant.
                payout.quote_valid_to = "1970-01-01T00:00:00+0000"
                payout._move(DEPOSIT_CONFIRMED, "Airwallex reports the quote as expired; no transfer was made")
                return payout
        _take_transfer(payout, transfer)
        payout._move(TRANSFER_CREATED, f"transfer {payout.transfer_id} {payout.transfer_status}")

    elif payout.state == TRANSFER_CREATED:
        transfer = client.get_transfer(payout.transfer_id)
        if _transfer_dead(payout, client, transfer, returned=False):
            return payout
        # Seen on the live sandbox: a transfer that converts on the way (USD to PHP) starts as SCHEDULED and moves
        # to PROCESSING by itself a few seconds later. Pushing it before then returns a 500, so wait for it.
        if transfer.get("status") == "PROCESSING" and simulator is not None:
            simulator.transition_transfer(payout.transfer_id, "SENT")
            transfer = client.get_transfer(payout.transfer_id)
            if _transfer_dead(payout, client, transfer, returned=False):
                return payout
        if transfer.get("status") in ("SENT", "PAID"):
            _take_transfer(payout, transfer)
            payout._move(SENT, f"transfer {payout.transfer_id} left Airwallex")
        else:
            payout.save()

    elif payout.state == SENT:
        transfer = client.get_transfer(payout.transfer_id)
        if _transfer_dead(payout, client, transfer, returned=False):
            return payout
        if transfer.get("status") != "PAID" and simulator is not None:
            if staging == "transfer_fails":   # the staged case: the receiving bank refuses the transfer
                payout.what_if_done = True
                payout.save()
                _keep_reason(payout, simulator.transition_transfer(payout.transfer_id, "FAILED",
                                                                   SandboxSimulator.BANK_REFUSAL))
            else:
                simulator.transition_transfer(payout.transfer_id, "PAID")
            transfer = client.get_transfer(payout.transfer_id)
            if _transfer_dead(payout, client, transfer, returned=False):
                return payout
        if transfer.get("status") == "PAID":
            _take_transfer(payout, transfer)
            payout.proof = client.proof_of_receipt(payout.transfer_id)
            refresh_ledger(payout, client)
            payout.paid_at = _now()
            payout.watch_until = clock() + RETURN_WATCH_SECONDS
            payout._move(PAID, f"transfer {payout.transfer_id} paid")
        else:
            payout.save()

    elif payout.state == PAID:
        # A PAID transfer can still be sent back by the receiving bank. Reading it again is how we find out.
        if staging == "transfer_returned":   # the staged case: the bank returns the money after it was paid
            payout.what_if_done = True
            payout.save()
            _keep_reason(payout, simulator.transition_transfer(payout.transfer_id, "FAILED",
                                                               SandboxSimulator.BANK_REFUSAL))
        transfer = client.get_transfer(payout.transfer_id)
        if not _transfer_dead(payout, client, transfer, returned=True):
            payout.proof = client.proof_of_receipt(payout.transfer_id)
            refresh_ledger(payout, client)
            payout.save()

    return payout  # HELD and FAILED: nothing to do until a person acts


def run(payout: Payout, client: AirwallexClient, simulator: SandboxSimulator | None = None) -> Payout:
    """Advance until the payout is PAID or stopped, or until a step makes no progress (waiting on the outside)."""
    while payout.state not in (PAID,) + STOPPED:
        before = payout.state
        advance(payout, client, simulator)
        if payout.state == before:
            break
    return payout
