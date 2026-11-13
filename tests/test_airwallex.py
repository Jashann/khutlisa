"""Airwallex module tests. No network: a small in-memory fake of the sandbox sits behind httpx.MockTransport."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from khutlisa import airwallex as awx
from khutlisa.airwallex import AirwallexClient, AirwallexError, Payout, SandboxSimulator, advance, run

RATES = {"PHP": 58.0, "MXN": 18.5}


class FakeAirwallex:
    """Just enough of the sandbox to run the flow. Counts calls and keeps every request body."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.bodies: dict[str, list[dict]] = {}
        self.logins = 0
        self.global_accounts: list[dict] = []
        self.deposits: list[dict] = []
        self.balance = {"USD": 0.0}
        self.quotes: dict[str, dict] = {}
        self.conversions: list[dict] = []
        self.beneficiaries: list[dict] = []
        self.transfers: dict[str, dict] = {}
        self.ledger: list[dict] = []
        self.rates = dict(RATES)
        self.rates_down = False                   # the indicative rate endpoint answers 503
        self.mid_rates: dict[str, float] = {}     # the mid rate of a quote, where it differs from the client rate
        self.incoming_fee_rate = 0.0              # set to 0.003 for what the live sandbox charges on a deposit
        self.payout_fee_usd = 0.0                 # set to 5.0 for what the live sandbox charges on a local payout
        self.deposit_reads_before_settled = 0     # the deposit shows as PENDING, with no fee, this many reads
        self.now = time.time()                    # the fake's clock, for quote validity
        self.fail_once: dict[str, int] = {}      # path -> HTTP status to return one time
        self.drop_response_once: set[str] = set()  # path -> do the work, then lose the connection
        self.sent_becomes: str = "SENT"           # set to "FAILED" to make the bank reject the payout

    def count(self, method: str, path: str) -> int:
        return self.calls.count((method, path))

    def _row(self, source_id: str, kind: str, amount: float, currency: str, description: str = "") -> None:
        self.ledger.append({"id": "ftx_" + uuid.uuid4().hex[:20], "source_id": source_id,
                            "source_type": "FEE" if kind == "FEE" else kind.split("_")[0], "transaction_type": kind,
                            "amount": round(amount, 2), "net": round(amount, 2), "fee": 0, "currency": currency,
                            "status": "SETTLED", "description": description,
                            "created_at": f"2026-11-12T00:00:{len(self.ledger):02d}.000+00:00"})

    def _settle_deposit(self, dep: dict) -> None:
        fee = round(dep["amount"] * self.incoming_fee_rate, 2)
        dep.update(status="SETTLED", fee={"amount": fee, "currency": "USD"})
        self._row(dep["id"], "DEPOSIT", dep["amount"], "USD", dep["reference"])
        if fee:
            self._row(dep["id"], "FEE", -fee, "USD", "Deposit to account 8487576435")
            self.balance["USD"] -= fee

    def bank_refuses(self, transfer_id: str, status: str = "FAILED") -> None:
        """What the live sandbox does when a transfer fails or is returned: the status goes to FAILED and then
        CANCELLED, and what the person was to receive is booked back in the transfer's currency. The payout fee
        is kept."""
        t = self.transfers[transfer_id]
        t.update(status=status, failure_type="INVALID_ACCOUNT_NAME_OR_NUMBER",
                 failure_reason="90101: Invalid account name/number")
        back = t["amount_beneficiary_receives"]
        self._row(t["id"], "PAYOUT_REVERSAL", back, t["transfer_currency"], "Refund for failed payment")
        self.balance[t["transfer_currency"]] = self.balance.get(t["transfer_currency"], 0) + back

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @staticmethod
    def _err(status: int, code: str, message: str, **details) -> httpx.Response:
        return httpx.Response(status, json={"code": code, "message": message, "source": "request_id",
                                            "details": details})

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path))
        if body is not None:
            self.bodies.setdefault(path, []).append(body)
        if path in self.fail_once:
            return httpx.Response(self.fail_once.pop(path), json={"code": "service_unavailable", "message": "down"})

        if path == "/api/v1/authentication/login":
            assert request.headers["x-client-id"] == "cid" and request.headers["x-api-key"] == "key"
            assert not request.content
            self.logins += 1
            return httpx.Response(201, json={"token": f"tok{self.logins}", "expires_at": "2099-01-01T00:00:00+0000"})
        if not request.headers.get("authorization", "").startswith("Bearer tok"):
            return httpx.Response(401, json={"code": "credentials_invalid", "message": "bad token"})

        response = self.route(method, path, body, dict(request.url.params))
        if path in self.drop_response_once:
            self.drop_response_once.discard(path)
            raise httpx.ReadTimeout("response lost", request=request)
        return response

    def route(self, method, path, body, params) -> httpx.Response:
        if (method, path) == ("GET", "/api/v1/global_accounts"):
            return httpx.Response(200, json={"items": self.global_accounts, "page_after": None})
        if path == "/api/v1/global_accounts/create":
            acct = {"id": str(uuid.uuid4()), "request_id": body["request_id"], "status": "ACTIVE",
                    "country_code": body["country_code"], "required_features": body["required_features"],
                    "supported_features": [{"currency": "USD", "transfer_method": "LOCAL", "type": "DEPOSIT",
                                            "routing_codes": [{"type": "ach", "value": "026073150"}]}]}
            self.global_accounts.append(acct)
            return httpx.Response(201, json=acct)
        if path == "/api/v1/simulation/deposit/create":
            dep = {"id": str(uuid.uuid4()), "amount": body["amount"], "currency": "USD", "status": "PENDING",
                   "reference": body["reference"], "global_account_id": body["global_account_id"],
                   "type": "BANK_TRANSFER", "reads": 0}
            self.deposits.append(dep)
            self.balance["USD"] += body["amount"]
            if not self.deposit_reads_before_settled:
                self._settle_deposit(dep)
            return httpx.Response(201, json={k: v for k, v in dep.items() if k not in ("fee", "reads")} | {"status": "PENDING"})
        if path == "/api/v1/deposits":
            for dep in self.deposits:
                if dep["status"] == "PENDING":
                    dep["reads"] += 1
                    if dep["reads"] > self.deposit_reads_before_settled:
                        self._settle_deposit(dep)
            return httpx.Response(200, json={"has_more": False, "items": self.deposits})
        if path == "/api/v1/balances/current":
            return httpx.Response(200, json=[{"account_type": "cash", "currency": c, "available_amount": a,
                                              "total_amount": a} for c, a in self.balance.items()])
        if path == "/api/v1/fx/rates/current":
            if self.rates_down:
                return httpx.Response(503, json={"code": "service_unavailable", "message": "down"})
            buy = params["buy_currency"]
            return httpx.Response(200, json={"buy_currency": buy, "sell_currency": params["sell_currency"],
                                             "currency_pair": f"USD{buy}", "rate": self.rates[buy],
                                             "created_at": "2026-11-13T01:50:53+0000"})
        if path == "/api/v1/fx/quotes/create":
            assert "x-api-version" not in {k.lower() for k in body}
            rate = self.rates[body["buy_currency"]]
            lasts = {"MIN_1": 60, "MIN_15": 900, "MIN_30": 1800, "HR_1": 3600, "HR_4": 14400}[body["validity"]]
            stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
            quote = {"quote_id": str(uuid.uuid4()), "client_rate": rate,
                     "mid_rate": self.mid_rates.get(body["buy_currency"], rate), "sell_currency": "USD",
                     "buy_currency": body["buy_currency"], "sell_amount": body["sell_amount"],
                     "buy_amount": round(body["sell_amount"] * rate, 2), "validity": body["validity"],
                     "valid_from_at": stamp(self.now), "valid_to_at": stamp(self.now + lasts), "ends": self.now + lasts}
            self.quotes[quote["quote_id"]] = quote
            return httpx.Response(201, json=quote)
        if (method, path) == ("GET", "/api/v1/fx/conversions"):
            hits = [c for c in self.conversions if c["request_id"] == params.get("request_id")]
            return httpx.Response(200, json={"has_more": False, "items": hits})
        if path == "/api/v1/fx/conversions/create":
            if any(c["request_id"] == body["request_id"] for c in self.conversions):
                return self._err(400, "duplicate_request", "The request ID has been used previously.")
            quote = self.quotes[body["quote_id"]]
            sell = float(body["sell_amount"])
            if self.balance["USD"] < sell:
                return self._err(400, "insufficient_funds", "not enough USD")
            conv = {"conversion_id": str(uuid.uuid4()), "request_id": body["request_id"], "status": "SETTLED",
                    "sell_currency": "USD", "buy_currency": body["buy_currency"], "sell_amount": sell,
                    "buy_amount": round(sell * quote["client_rate"], 2), "client_rate": quote["client_rate"]}
            self.conversions.append(conv)
            self.balance["USD"] -= sell
            self.balance[conv["buy_currency"]] = self.balance.get(conv["buy_currency"], 0) + conv["buy_amount"]
            self._row(conv["conversion_id"], "CONVERSION", -sell, "USD", "Sell USD")
            self._row(conv["conversion_id"], "CONVERSION", conv["buy_amount"], conv["buy_currency"], "Buy")
            return httpx.Response(201, json=conv)
        if path == "/api/v1/beneficiary_api_schemas/generate":
            fields = [("beneficiary.entity_type", "COMPANY|PERSONAL"), ("beneficiary.bank_details.account_name", None),
                      ("beneficiary.bank_details.account_number", r"^[0-9]{8,18}$"),
                      ("beneficiary.bank_details.bank_country_code", "PH|MX"),
                      ("beneficiary.address.country_code", None)]
            if body["account_currency"] == "PHP":
                fields.append(("beneficiary.bank_details.swift_code", r"^[A-Z0-9]{8}([A-Z0-9]{3})?$"))
            return httpx.Response(200, json={"condition": body, "fields": [
                {"key": p.split(".")[-1], "path": p, "required": True, "rule": {"type": "string", "pattern": pat}}
                for p, pat in fields]})
        if path == "/api/v1/beneficiaries/validate":
            assert body["transfer_methods"] == ["LOCAL"]
            return httpx.Response(200, json="OK")
        if path == "/api/v1/beneficiaries/create":
            ben = {"id": str(uuid.uuid4()), **body}
            self.beneficiaries.append(ben)
            return httpx.Response(201, json=ben)
        if (method, path) == ("GET", "/api/v1/transfers"):
            if "request_id" not in params:      # the plain list, newest first, as the sandbox gives it
                return httpx.Response(200, json={"items": list(self.transfers.values())[::-1], "page_after": None})
            hits = [t for t in self.transfers.values() if t["request_id"] == params.get("request_id")]
            return httpx.Response(200, json={"items": hits, "page_after": None})
        if path == "/api/v1/transfers/create":
            for t in self.transfers.values():
                if t["request_id"] == body["request_id"]:
                    return self._err(400, "duplicate_request_id", "request ID used before", id=t["id"],
                                     request_id=t["request_id"])
            assert "payment_currency" not in body
            cur, src = body["transfer_currency"], body["source_currency"]
            quote = self.quotes.get(body.get("quote_id") or "")
            if quote and self.now >= quote["ends"]:
                return self._err(400, "quote_expired", "The quote has expired.")
            rate = 1.0 if src == cur else quote["client_rate"] if quote else self.rates[cur]
            fee = round(self.payout_fee_usd * (1.0 if src == "USD" else self.mid_rates.get(cur, self.rates[cur])), 2)
            by = body.get("fee_paid_by", "PAYER")
            if "transfer_amount" in body:
                amount = float(body["transfer_amount"])
                source = round(amount / rate, 2)
            else:
                source = float(body["source_amount"])
                amount = round(source * rate, 2)
            receives = round((source - fee) * rate, 2) if by == "BENEFICIARY" else amount
            pays = source if by == "BENEFICIARY" else round(source + fee, 2)
            if round(self.balance.get(src, 0) - pays, 2) < 0:
                return self._err(400, "balance_insufficient", f"not enough {src}")
            self.balance[src] = round(self.balance[src] - pays, 2)
            t = {"id": str(uuid.uuid4()), "request_id": body["request_id"], "status": "PROCESSING",
                 "beneficiary_id": body["beneficiary_id"], "transfer_currency": cur, "transfer_amount": amount,
                 "source_currency": src, "source_amount": source, "transfer_method": body["transfer_method"],
                 "reference": body["reference"], "amount_beneficiary_receives": receives, "amount_payer_pays": pays,
                 "fee_amount": fee, "fee_currency": src, "fee_paid_by": by}
            self.transfers[t["id"]] = t
            self._row(t["id"], "PAYOUT", -source, src, f"Pay {receives} {cur}")
            if by != "BENEFICIARY" and fee:
                self._row(t["id"], "FEE", -fee, src, "Fee for payout")
            return httpx.Response(201, json=t)
        if path.startswith("/api/v1/simulation/transfers/"):
            t = self.transfers[path.split("/")[5]]
            nxt = body["next_status"]
            if nxt == "SENT" and self.sent_becomes != "SENT":
                self.bank_refuses(t["id"], self.sent_becomes)
            elif nxt == "FAILED" and t["status"] in ("SENT", "PAID"):
                self.bank_refuses(t["id"])
            elif nxt == "FAILED":   # seen live: a push to FAILED before SENT is answered with a 500
                return httpx.Response(500, json={"code": "internal_error", "message": "cannot fail yet"})
            elif (t["status"], nxt) in {("SCHEDULED", "PROCESSING"), ("PROCESSING", "SENT"), ("SENT", "PAID")}:
                t["status"] = nxt
            else:
                return self._err(400, "invalid_status_for_operation", f"cannot go {t['status']} -> {nxt}")
            return httpx.Response(200, json=t)
        if path.startswith("/api/v1/transfers/"):
            return httpx.Response(200, json=self.transfers[path.rsplit("/", 1)[1]])
        if path == "/api/v1/financial_transactions":
            hits = [r for r in self.ledger if r["source_id"] == params.get("source_id")]
            return httpx.Response(200, json={"has_more": False, "items": hits})
        return httpx.Response(404, json={"code": "not_found", "message": path})


@pytest.fixture
def fake():
    return FakeAirwallex()


def make_client(fake, **kw):
    return AirwallexClient("cid", "key", transport=fake.transport(), min_interval=0, sleep=lambda s: None, **kw)


def make_payout(tmp_path, currency="MXN", usd="250.00"):
    return Payout.open(tmp_path / f"payout_{currency}.json", usd_amount=usd, target_currency=currency,
                       deposit_reference=f"KHUT-{currency}-0001", beneficiary=awx.EXAMPLE_BENEFICIARIES[currency])


# ---- credentials and login ---------------------------------------------------------------------------------

def test_load_credentials_env_then_file(tmp_path):
    assert awx.load_credentials({"AWX_CLIENT_ID": "a", "AWX_API_KEY": "b"}, tmp_path / "none") == ("a", "b")
    f = tmp_path / "creds"
    f.write_text("# sandbox\nAWX_CLIENT_ID=from_file\nexport AWX_API_KEY='secret value'\n")
    assert awx.load_credentials({}, f) == ("from_file", "secret value")
    assert awx.load_credentials({"AWX_CLIENT_ID": "env"}, f) == ("env", "secret value")
    f.write_text("AWX_CLIENT_ID=only_id\n")
    with pytest.raises(awx.CredentialsError) as exc:
        awx.load_credentials({}, f)
    assert "AWX_API_KEY" in str(exc.value) and "only_id" not in str(exc.value)


def test_login_once_and_token_reused(fake):
    client = make_client(fake)
    client.balances()
    client.balances()
    client.list_global_accounts()
    assert fake.logins == 1
    assert "key" not in repr(client) and "cid" not in repr(client)


def test_token_refreshed_before_expiry(fake):
    now = [1_000_000.0]
    client = make_client(fake, clock=lambda: now[0])
    client._send = _login_with_short_expiry(client._send, now)  # type: ignore[method-assign]
    client.balances()
    now[0] += 20 * 60
    client.balances()
    assert fake.logins == 1  # 10 minutes left: still good
    now[0] += 9 * 60
    client.balances()
    assert fake.logins == 2  # 1 minute left: inside the refresh margin


def _login_with_short_expiry(send, now):
    def wrapped(method, path, **kw):
        data = send(method, path, **kw)
        if path.endswith("/authentication/login"):
            data = {"token": data["token"]}  # no expires_at: the client falls back to the 30 minute lifetime
        return data
    return wrapped


def test_rejected_token_triggers_one_relogin(fake):
    client = make_client(fake)
    client.balances()
    client._token = "stale"
    assert client.balances()[0]['currency'] == 'USD'
    assert fake.logins == 2


def test_error_carries_status_code_and_message(fake):
    client = make_client(fake)
    with pytest.raises(AirwallexError) as exc:
        client.create_conversion(awx.new_request_id(), "USD", "MXN", sell_amount=10, quote_id=_quote(client))
    err = exc.value
    assert (err.status, err.code, err.message) == (400, "insufficient_funds", "not enough USD")
    assert "400" in str(err) and "insufficient_funds" in str(err)


def _quote(client, currency="MXN", amount=10):
    return client.create_quote("USD", currency, sell_amount=amount)["quote_id"]


# ---- request_id on retry -----------------------------------------------------------------------------------

def test_request_id_reused_on_retry(fake):
    client = make_client(fake)
    fake.balance["USD"] = 100
    quote_id = _quote(client)
    fake.fail_once["/api/v1/fx/conversions/create"] = 503
    rid = awx.new_request_id()
    conv = client.create_conversion(rid, "USD", "MXN", sell_amount=10, quote_id=quote_id)
    sent = fake.bodies["/api/v1/fx/conversions/create"]
    assert len(sent) == 2 and sent[0] == sent[1] and sent[0]["request_id"] == rid
    assert conv["status"] == "SETTLED" and len(fake.conversions) == 1
    assert sent[0]["sell_amount"] == "10.00"  # major units, as a string


def test_write_without_request_id_is_not_blindly_repeated(fake):
    client = make_client(fake)
    acct = client.find_or_create_usd_global_account(awx.new_request_id())
    fake.fail_once["/api/v1/simulation/deposit/create"] = 500
    with pytest.raises(AirwallexError):
        SandboxSimulator(client).deposit(acct["id"], 50, "REF-1")
    assert fake.count("POST", "/api/v1/simulation/deposit/create") == 1


def test_same_request_id_never_makes_a_second_transfer(fake):
    client = make_client(fake)
    fake.balance["MXN"] = 1000
    rid = awx.new_request_id()
    first = client.create_transfer(rid, "ben-1", "MXN", transfer_amount=100)
    again = client.create_transfer(rid, "ben-1", "MXN", transfer_amount=100)
    assert again["id"] == first["id"] and len(fake.transfers) == 1


def test_global_account_found_not_recreated(fake):
    client = make_client(fake)
    a = client.find_or_create_usd_global_account(awx.new_request_id())
    b = client.find_or_create_usd_global_account(awx.new_request_id())
    assert a["id"] == b["id"] and fake.count("POST", "/api/v1/global_accounts/create") == 1
    assert fake.bodies["/api/v1/global_accounts/create"][0]["required_features"] == [
        {"currency": "USD", "transfer_method": "LOCAL"}]


# ---- beneficiary payloads ----------------------------------------------------------------------------------

def test_example_beneficiaries_have_the_documented_fields():
    ph = awx.EXAMPLE_BENEFICIARIES["PHP"]["beneficiary"]["bank_details"]
    assert set(ph) == {"account_currency", "account_name", "account_number", "swift_code", "bank_country_code"}
    mx = awx.EXAMPLE_BENEFICIARIES["MXN"]["beneficiary"]["bank_details"]
    assert set(mx) == {"account_currency", "account_name", "account_number", "bank_country_code"}
    assert awx.is_valid_clabe(mx["account_number"]) and not awx.is_valid_clabe("002010077777777772")
    with pytest.raises(ValueError):
        awx.local_beneficiary("MXN", "A", "B", "123", street_address="x", city="y")


def test_schema_problems_lists_missing_and_malformed(fake):
    client = make_client(fake)
    schema = client.beneficiary_schema("PH", "PHP")
    good = awx.EXAMPLE_BENEFICIARIES["PHP"]
    assert awx.schema_problems(schema, good) == []
    bad = json.loads(json.dumps(good))
    del bad["beneficiary"]["bank_details"]["swift_code"]
    bad["beneficiary"]["bank_details"]["account_number"] = "12AB"
    problems = awx.schema_problems(schema, bad)
    assert any("swift_code: required" in p for p in problems) and any("account_number" in p for p in problems)


# ---- the payout state machine ------------------------------------------------------------------------------

def test_happy_path_mxn_through_paid(fake, tmp_path):
    client = make_client(fake)
    sim = SandboxSimulator(client)
    payout = make_payout(tmp_path, "MXN")
    seen = [payout.state]
    while payout.state not in (awx.PAID, awx.FAILED):
        advance(payout, client, sim)
        seen.append(payout.state)
        assert Payout.load(payout.path).state == payout.state  # saved after every step
    assert seen == [awx.DEPOSIT_EXPECTED, awx.DEPOSIT_CONFIRMED, awx.CONVERTED, awx.BENEFICIARY_READY,
                    awx.TRANSFER_CREATED, awx.SENT, awx.PAID]
    assert payout.target_amount == "4625.00" and payout.conversion_id
    transfer = fake.transfers[payout.transfer_id]
    assert transfer["status"] == "PAID" and transfer["transfer_method"] == "LOCAL"
    assert (transfer["source_currency"], transfer["transfer_currency"], transfer["transfer_amount"]) == (
        "MXN", "MXN", 4625.0)
    assert fake.balance == {"USD": 0.0, "MXN": 0.0}
    assert payout.proof["transfer"]["status"] == "PAID"
    assert payout.proof["financial_transactions"][0]["source_id"] == payout.transfer_id
    statuses = [b["next_status"] for p, bs in fake.bodies.items() if "/simulation/transfers/" in p for b in bs]
    assert statuses == ["SENT", "PAID"]
    ids = {payout.global_account_request_id, payout.conversion_request_id, payout.transfer_request_id}
    assert len(ids) == 3  # one id per operation
    advance(payout, client, sim)  # a later look at a PAID payout pays nothing
    assert payout.state == awx.PAID and len(fake.transfers) == 1


def test_happy_path_php_pays_from_usd_with_quote(fake, tmp_path):
    """PHP cannot be held in the wallet, so there is no stand-alone conversion: the transfer converts."""
    client = make_client(fake)
    payout = run(make_payout(tmp_path, "PHP", usd="100"), client, SandboxSimulator(client))
    assert payout.state == awx.PAID and payout.conversion_id is None
    assert fake.count("POST", "/api/v1/fx/conversions/create") == 0
    body = fake.bodies["/api/v1/transfers/create"][0]
    assert body["source_currency"] == "USD" and body["source_amount"] == "100.00"
    assert body["transfer_currency"] == "PHP" and body["quote_id"] == payout.quote_id
    assert "transfer_amount" not in body and payout.target_amount == "5800.00"


def test_without_simulator_the_machine_waits(fake, tmp_path):
    client = make_client(fake)
    payout = run(make_payout(tmp_path), client)  # production mode: nobody fakes the deposit
    assert payout.state == awx.DEPOSIT_EXPECTED
    assert fake.count("POST", "/api/v1/simulation/deposit/create") == 0
    assert not any("/simulation/" in path for _, path in fake.calls)


def test_restart_between_transfer_created_and_sent_makes_no_second_transfer(fake, tmp_path):
    client = make_client(fake)
    payout = make_payout(tmp_path)
    while payout.state != awx.TRANSFER_CREATED:
        advance(payout, client, SandboxSimulator(client))
    path, first_transfer = payout.path, payout.transfer_id
    del payout, client  # the process dies here

    client2 = make_client(fake)
    revived = Payout.load(path)
    assert revived.state == awx.TRANSFER_CREATED and revived.transfer_id == first_transfer
    run(revived, client2, SandboxSimulator(client2))
    assert revived.state == awx.PAID and revived.transfer_id == first_transfer
    assert fake.count("POST", "/api/v1/transfers/create") == 1 and len(fake.transfers) == 1
    assert fake.count("POST", "/api/v1/fx/conversions/create") == 1
    assert fake.count("POST", "/api/v1/simulation/deposit/create") == 1


def test_crash_while_creating_the_transfer_adopts_the_existing_one(fake, tmp_path):
    """Airwallex accepted the transfer but the answer never reached us and the state was not saved."""
    client = make_client(fake, max_retries=0)
    sim = SandboxSimulator(client)
    payout = make_payout(tmp_path)
    while payout.state != awx.BENEFICIARY_READY:
        advance(payout, client, sim)
    fake.drop_response_once.add("/api/v1/transfers/create")
    with pytest.raises(httpx.ReadTimeout):
        advance(payout, client, sim)
    assert len(fake.transfers) == 1 and Payout.load(payout.path).state == awx.BENEFICIARY_READY

    client2 = make_client(fake)
    revived = run(Payout.load(payout.path), client2, SandboxSimulator(client2))
    assert revived.state == awx.PAID
    assert len(fake.transfers) == 1 and fake.count("POST", "/api/v1/transfers/create") == 1
    assert revived.transfer_id == next(iter(fake.transfers))


def test_lost_response_is_retried_with_the_same_request_id(fake, tmp_path):
    """Same loss of the answer, but the client retries by itself: Airwallex reports a duplicate and names the
    transfer it already made, and the client returns that one."""
    client = make_client(fake)
    sim = SandboxSimulator(client)
    payout = make_payout(tmp_path)
    while payout.state != awx.BENEFICIARY_READY:
        advance(payout, client, sim)
    fake.drop_response_once.add("/api/v1/transfers/create")
    advance(payout, client, sim)
    sent = fake.bodies["/api/v1/transfers/create"]
    assert len(sent) == 2 and sent[0]["request_id"] == sent[1]["request_id"] == payout.transfer_request_id
    assert payout.state == awx.TRANSFER_CREATED and list(fake.transfers) == [payout.transfer_id]


def test_crash_after_conversion_does_not_convert_twice(fake, tmp_path):
    client = make_client(fake, max_retries=0)
    sim = SandboxSimulator(client)
    payout = make_payout(tmp_path)
    advance(payout, client, sim)
    fake.drop_response_once.add("/api/v1/fx/conversions/create")
    with pytest.raises(httpx.ReadTimeout):
        advance(payout, client, sim)
    revived = run(Payout.load(payout.path), client, sim)
    assert revived.state == awx.PAID and len(fake.conversions) == 1
    assert fake.count("POST", "/api/v1/fx/conversions/create") == 1


def test_failed_transfer_stops_the_machine(fake, tmp_path):
    client = make_client(fake)
    sim = SandboxSimulator(client)
    fake.sent_becomes = "FAILED"
    payout = run(make_payout(tmp_path), client, sim)
    assert payout.state == awx.FAILED and payout.transfer_status == "FAILED"
    assert "INVALID_ACCOUNT_NAME_OR_NUMBER" in payout.failure and "90101" in payout.failure
    assert Payout.load(payout.path).state == awx.FAILED
    # It stops with a way forward on file: the failed transfer is set aside and three people have to act.
    assert payout.hold["kind"] == "transfer_failed" and payout.hold["needs"] == ["bank_details", "payer", "claimant"]
    assert payout.attempts[0]["status"] == "FAILED" and payout.transfer_id is None

    calls_before = len(fake.calls)
    run(payout, client, sim)
    advance(payout, client, sim)
    assert len(fake.calls) == calls_before  # recorded, and nothing is retried
    assert fake.count("POST", "/api/v1/transfers/create") == 1


def test_cancelled_transfer_is_recorded_as_failed(fake, tmp_path):
    client = make_client(fake)
    sim = SandboxSimulator(client)
    payout = make_payout(tmp_path)
    while payout.state != awx.SENT:
        advance(payout, client, sim)
    sent = payout.transfer_id
    fake.transfers[sent].update(status="CANCELLED", failure_reason="returned by bank")
    advance(payout, client, sim)
    # Airwallex has not booked the money back yet, so the payout waits where it is and promises nothing.
    assert payout.state == awx.SENT and payout.transfer_status == "CANCELLED" and payout.attempts == []
    fake.bank_refuses(sent, "CANCELLED")
    advance(payout, client, sim)
    assert payout.state == awx.FAILED and payout.attempts[0]["status"] == "CANCELLED"
    assert payout.attempts[0]["came_back"] == {"amount": "4625.00", "currency": "MXN"}
    assert not any(b["next_status"] == "PAID" for p, bs in fake.bodies.items() if "/simulation/transfers/" in p
                   for b in bs)
