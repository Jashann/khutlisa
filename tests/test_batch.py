"""A batch: one deposit, one conversion for each currency that can be held, and every payment carried by the same
payout machine. A stand-in for Airwallex sits behind every test; no network and no model."""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from khutlisa import airwallex as awx
from khutlisa import batch as bt
from khutlisa import book as bk
from khutlisa import corridors as co
from khutlisa import instructions as ins
from khutlisa.server import create_app
from test_airwallex import FakeAirwallex, make_client
from test_book import CLAIMS, HOLDER, TODAY, WAGES
from test_claims import make_register
from test_corridors import Sandbox

RULES = ins.clean({})
RATES = {"GBP": 0.75, "EUR": 0.9, "CAD": 1.42, "INR": 88.0, "AUD": 1.47, "USD": 1.0}


class FiveCountries(FakeAirwallex):
    """The sandbox stand-in with more currencies, a schema for any country, and SWIFT accepted."""

    def __init__(self):
        super().__init__()
        self.rates.update(RATES)
        self.incoming_fee_rate, self.payout_fee_usd = 0.003, 5.0

    def route(self, method, path, body, params):
        if path == "/api/v1/beneficiary_api_schemas/generate":
            fields = ["beneficiary.entity_type", "beneficiary.bank_details.account_name", "beneficiary.address.country_code"]
            return httpx.Response(200, json={"condition": body, "fields": [{"path": p, "required": True, "rule": {}} for p in fields]})
        if path == "/api/v1/beneficiaries/validate":
            return httpx.Response(200, json="OK")
        return super().route(method, path, body, params)


def chosen(*rows):
    """Rows as batch.choose_slice gives them: (country, currency, method, claim, payout fee)."""
    return [{"country": c, "name": c, "currency": cur, "method": m, "claim_usd": claim, "scheme": None, "amount_is": "the median claim",
             "fee": {"usd": fee, "basis": "observed"}} for c, cur, m, claim, fee in rows]


SLICE = chosen(("MX", "MXN", "LOCAL", "2316.40", "5.00"), ("MX", "MXN", "LOCAL", "120.00", "5.00"), ("GB", "GBP", "LOCAL", "800.00", "5.00"),
               ("DE", "EUR", "LOCAL", "95.00", "5.00"), ("CA", "CAD", "LOCAL", "640.00", "5.00"), ("PH", "PHP", "LOCAL", "500.00", "5.00"),
               ("IN", "INR", "LOCAL", "300.00", "5.00"), ("TW", "USD", "SWIFT", "1000.00", "5.00"))
PLAN = {"inputs": {}, "funding": {"currencies": [
    {"currency": c, "mode": m, "mode_words": w} for c, m, w in (
        ("MXN", "batch", "Convert once for the batch."), ("GBP", "batch", "Convert once."), ("EUR", "batch", "Convert once."),
        ("CAD", "batch", "Convert once."), ("PHP", "each", "Inside each transfer."), ("INR", "each", "Inside each transfer."),
        ("USD", "none", "Nothing is converted."))]}}


@pytest.fixture
def fake():
    return FiveCountries()


def made(tmp_path, fake, refuse=(), rows=SLICE):
    client = make_client(fake)
    batch = bt.new_batch(tmp_path / "batches", HOLDER, rows, PLAN, RULES, refuse=refuse)
    return batch, client, awx.SandboxSimulator(client)


def transfers_of(fake, batch, n):
    return [t for t in fake.transfers.values() if t["reference"] == f"KHUTLISA-{batch.batch_id}-{n:02d}"]


def test_a_batch_is_written_from_the_plan_with_the_fee_rule_on_every_payment(tmp_path, fake):
    batch, _, _ = made(tmp_path, fake)
    assert batch.state == bt.PLANNED and len(batch.items) == 8 and not fake.calls       # writing it asks Airwallex nothing
    small = batch.items[1]                    # 120.00 is below the line: the holder adds the fees
    assert small["fees_borne_by"] == "holder" and small["holder_sends"] == "125.38" and small["net_usd"] == "125.00"
    big = batch.items[0]
    assert big["fees_borne_by"] == "claim" and big["holder_sends"] == "2316.40" and big["planned"]["incoming_fee_usd"] == "6.95"
    assert batch.plan["holder_funds_usd"] == f"{sum(Decimal(i['holder_sends']) for i in batch.items):.2f}"
    assert {c: f["mode"] for c, f in batch.funding.items()} == {"MXN": "batch", "GBP": "batch", "EUR": "batch", "CAD": "batch",
                                                                 "PHP": "each", "INR": "each", "USD": "none"}
    assert all(i["owner"]["demonstration"] and i["owner"]["name"] in ("Ximena Olvareda", "Rowan Ashcombe", "Jonas Feldbrunner",
               "Odile Marchetier", "Dalisay Marquendo", "Kavya Indurkar", "Meilin Zhaoqing") for i in batch.items)
    assert "invented" in batch.plan["statement"] and bt.Batch.load(batch.path).items == batch.items
    tiny = bt.new_batch(tmp_path / "b2", HOLDER, chosen(("MX", "MXN", "LOCAL", "3.00", "5.00")), PLAN, RULES)
    assert tiny.items == []                   # a claim smaller than its fees is not put in a batch


def test_one_deposit_one_conversion_for_each_held_currency_and_every_currency_adds_up_to_zero(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake)
    bt.approve(batch)
    bt.run(batch, client, sim)
    assert batch.state == bt.DONE and batch.finished_at
    assert fake.count("POST", "/api/v1/simulation/deposit/create") == 1 and len(fake.deposits) == 1
    gross = sum(Decimal(i["holder_sends"]) for i in batch.items)
    assert Decimal(str(fake.deposits[0]["amount"])) == gross and batch.deposit_amount == f"{gross:.2f}"
    assert sorted(c["buy_currency"] for c in fake.conversions) == ["CAD", "EUR", "GBP", "MXN"]       # once each, never PHP or INR
    assert len(fake.transfers) == 8 and all(len(transfers_of(fake, batch, i["n"])) == 1 for i in batch.items)
    by = {(t["transfer_currency"], t["source_currency"]) for t in fake.transfers.values()}
    assert ("MXN", "MXN") in by and ("PHP", "USD") in by and ("INR", "USD") in by and ("USD", "USD") in by
    swift = transfers_of(fake, batch, 8)[0]
    sent = fake.bodies["/api/v1/transfers/create"]
    assert swift["transfer_method"] == "SWIFT" and [b.get("swift_charge_option") for b in sent if b["transfer_method"] == "SWIFT"] == ["PAYER"]
    assert all("swift_charge_option" not in b for b in sent if b["transfer_method"] == "LOCAL")
    assert all(b["fee_paid_by"] == "BENEFICIARY" for b in fake.bodies["/api/v1/transfers/create"])
    # the two Mexican payments share one conversion in proportion to their dollars, to the centavo
    mxn = [i for i in batch.items if i["currency"] == "MXN"]
    assert sum(Decimal(i["allocation_local"]) for i in mxn) == Decimal(batch.conversions["MXN"]["buy"])
    assert sum(bk._cents(i["allocation_usd"]) for i in batch.items) == bk._cents(batch.pool)        # every dollar is given to a payment
    books = bt.reconcile(batch)
    assert books["balanced"] and books["all_paid"] and all(Decimal(s["left"]) == 0 for s in books["sums"])
    assert {s["currency"] for s in books["sums"]} == {"USD", "MXN", "GBP", "EUR", "CAD"}
    assert all(round(v, 2) == 0 for v in fake.balance.values())          # the stand-in's wallet started empty and ends empty
    costs = bt.costs(batch)
    assert costs["planned"]["transfers"] == 8 and costs["actual"]["transfers"] == 8
    assert costs["actual"]["incoming_usd"] == batch.deposit_fee and abs(Decimal(costs["difference_usd"])) < Decimal("0.10")
    assert any(d["kind"] == "converted_once" for d in batch.decisions)


def test_nothing_moves_without_the_holders_approval(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake)
    bt.run(batch, client, sim)
    assert batch.state == bt.PLANNED and not fake.calls
    with pytest.raises(ValueError):
        bt.approve(bt.approve(batch))            # approved once
    assert bt.approval_holds(batch) == (True, "")


@pytest.mark.parametrize("tamper", ["amount", "rules", "funding", "owner"])
def test_a_batch_that_is_no_longer_what_was_approved_moves_no_money(tmp_path, fake, tamper):
    batch, client, sim = made(tmp_path, fake)
    bt.approve(batch)
    if tamper == "amount":
        batch.items[0]["first_terms"]["holder_sends"] = "9999.00"
    elif tamper == "rules":
        batch.rules = {**batch.rules, "tolerance_percent": "5"}
    elif tamper == "funding":
        batch.funding["PHP"]["mode"] = "batch"
    else:
        batch.items[2]["first_terms"]["name"] = "Somebody Else"
    batch.save()
    bt.run(batch, client, sim)
    assert batch.state == bt.STOPPED and "no longer what the holder approved" in batch.problem
    assert not fake.deposits and not fake.conversions and not fake.transfers


def test_a_payment_whose_terms_changed_after_the_approval_is_not_sent(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake)
    bt.approve(batch)
    for _ in range(40):
        bt.advance(batch, client, sim)
        if batch.state == bt.PAYING:
            break
    batch.items[2]["beneficiary"]["beneficiary"]["bank_details"]["account_number"] = "99999999"      # after the approval
    batch.save()
    bt.run(batch, client, sim)
    assert batch.state == bt.PAYING and not bt.item_approved(batch.items[2])
    assert transfers_of(fake, batch, 3) == [] and len(fake.transfers) == 7       # the others are paid; this one waits
    assert bt.view(batch)["items"][2]["approved"] is False and not bt.reconcile(batch)["balanced"]


def test_a_restart_at_every_step_never_makes_a_second_deposit_conversion_or_transfer(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake)
    bt.approve(batch)
    path = batch.path
    for _ in range(300):                      # a fresh process for every step: the batch is read from its file each time
        batch = bt.Batch.load(path)
        if batch.state == bt.DONE:
            break
        bt.advance(batch, make_client(fake), awx.SandboxSimulator(make_client(fake)))
    assert batch.state == bt.DONE
    assert len(fake.deposits) == 1 and len(fake.conversions) == 4 and len(fake.transfers) == 8
    assert bt.reconcile(batch)["balanced"]


def test_a_conversion_whose_answer_was_lost_is_found_again_and_not_made_twice(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake)
    bt.approve(batch)
    fake.drop_response_once.add("/api/v1/fx/conversions/create")       # Airwallex converted, and the reply never arrived
    bt.run(batch, client, sim)
    assert batch.state == bt.DONE and len(fake.conversions) == 4
    assert fake.count("POST", "/api/v1/fx/conversions/create") == 5    # the repeat was refused as a duplicate and adopted
    assert bt.reconcile(batch)["balanced"]


def test_a_deposit_that_does_not_fit_the_approval_converts_and_sends_nothing(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake)
    bt.approve(batch)
    client.find_or_create_usd_global_account(batch.global_account_request_id)
    sim.deposit(fake.global_accounts[0]["id"], 100, batch.deposit_reference)       # far less than was approved
    bt.run(batch, client, sim)
    assert batch.state == bt.STOPPED and "100.00 USD arrived" in batch.problem and not fake.conversions and not fake.transfers


def test_a_refused_payment_is_replaced_once_to_the_corrected_account_and_the_tolerance_decides_what_is_asked(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake, refuse=(1, 2))
    bt.approve(batch)
    bt.run(batch, client, sim)
    assert batch.state == bt.PAYING and bt.view(batch)["waiting_for_people"] == [1, 2] and bt.view(batch)["paid"] == 6
    big, small = batch.payout(1), batch.payout(2)
    assert big.state == awx.FAILED and big.attempts[0]["account_last4"] == "7712"
    # 2,316.40: the second fee is 0.22 percent, inside 0.5: the owner is not asked about the amount. 120.00: 4 percent.
    assert big.hold["needs"] == ["bank_details", "payer"] and big.attempts[0]["outcome"]["claimant_asked"] is False
    assert small.hold["needs"] == ["bank_details", "payer", "claimant"] and small.attempts[0]["outcome"]["claimant_asked"] is True
    assert any(d["kind"] == "replacement_within_tolerance" for d in big.decisions)
    rows = bt.view(batch)["items"]
    assert rows[0]["state_words"].startswith("Refused by the bank: waiting for the owner's corrected account")
    assert "did not ask the owner to confirm the amount" in rows[0]["cards"][0]["did"] and "stopped and asked" in rows[1]["cards"][0]["did"]

    with pytest.raises(ValueError, match="has not given another bank account"):
        bt.approve_item(batch, 1)                      # the holder cannot approve an account nobody has given
    with pytest.raises(ValueError, match="come first"):
        bt.owner_agrees(batch, 2)
    with pytest.raises(ValueError, match="just refused"):
        bt.give_corrected_account(batch, 1, batch.items[0]["beneficiary"])
    bt.give_corrected_account(batch, 1)
    assert batch.items[0]["account_last4"] == "8232" and batch.items[0]["refused_last4"] == "7712"
    assert not bt.item_approved(batch.items[0])        # a different account is never inside what was approved
    bt.run(batch, client, sim)
    assert len(transfers_of(fake, batch, 1)) == 1      # nothing is sent to an account the holder has not approved
    bt.approve_item(batch, 1)
    bt.run(batch, client, sim)
    assert batch.payout(1).state == awx.PAID and len(transfers_of(fake, batch, 1)) == 2
    first, second = transfers_of(fake, batch, 1)
    sent_to = next(b for b in fake.beneficiaries if b["id"] == second["beneficiary_id"])
    assert sent_to["beneficiary"]["bank_details"]["account_number"].endswith("8232") and first["status"] == "FAILED"
    assert second["source_amount"] == first["amount_beneficiary_receives"]       # exactly what came back, not a centavo more

    bt.give_corrected_account(batch, 2)
    bt.approve_item(batch, 2)
    bt.run(batch, client, sim)
    assert batch.payout(2).state == awx.FAILED and batch.payout(2).hold["needs"] == ["claimant"]      # outside the tolerance
    assert bt.view(batch)["items"][1]["state_words"].startswith("Outside the tolerance")
    bt.owner_agrees(batch, 2)
    bt.run(batch, client, sim)
    assert batch.state == bt.DONE and len(fake.transfers) == 10
    books, costs = bt.reconcile(batch), bt.costs(batch)
    assert books["balanced"] and all(round(v, 2) == 0 for v in fake.balance.values())
    assert costs["actual"]["transfers"] == 10 and costs["planned"]["transfers"] == 8        # two refusals, two more fees
    assert Decimal(costs["difference_usd"]) == pytest.approx(Decimal("10"), abs=Decimal("0.3"))


def test_no_replacement_is_sent_while_the_first_transfer_could_still_pay(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake, refuse=(1,))
    bt.approve(batch)
    bt.run(batch, client, sim)
    bt.give_corrected_account(batch, 1)
    bt.approve_item(batch, 1)
    transfers_of(fake, batch, 1)[0]["status"] = "PROCESSING"      # Airwallex says the first one is alive after all
    with pytest.raises(ValueError, match="no replacement is sent"):
        bt.run(batch, client, sim)
    assert len(transfers_of(fake, batch, 1)) == 1


def test_a_payment_never_sends_more_than_its_share_of_the_batch(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake)
    bt.approve(batch)
    for _ in range(40):
        bt.advance(batch, client, sim)
        if batch.state == bt.PAYING:
            break
    payout = batch.payout(3)
    share = payout.allocation["amount"]
    payout.funds = {"amount": str(Decimal(share) * 3), "currency": "GBP"}      # a wrong figure in the file
    payout.save()
    bt.run(batch, client, sim)
    assert transfers_of(fake, batch, 3)[0]["source_amount"] == float(share)


def test_the_view_shows_states_in_words_and_no_whole_account_number(tmp_path, fake):
    batch, client, sim = made(tmp_path, fake, refuse=(1,))
    assert bt.view(batch)["state_words"].startswith("Planned") and bt.view(batch)["items"][0]["state_words"] == "Planned"
    bt.approve(batch)
    bt.run(batch, client, sim)
    shown = bt.view(batch)
    text = json.dumps(shown)
    for item in batch.items:
        number = item["beneficiary"]["beneficiary"]["bank_details"].get("account_number") or item["beneficiary"]["beneficiary"]["bank_details"]["iban"]
        assert number not in text and number[-4:] == item["account_last4"]
    assert shown["paid"] == 7 and shown["payments"] == 8 and shown["reconciliation"]["balanced"] is False
    assert shown["funding"][0]["currency"] == "MXN" and "request_id" not in json.dumps(shown["funding"])
    assert shown["approval"]["holds"] and shown["deposit"]["fee"] == batch.deposit_fee
    assert {l["part"] for l in shown["reconciliation"]["lines"]} >= {"deposit", "conversion to MXN", "payment 1"}


def test_the_slice_comes_from_the_plan_and_only_from_corridors_it_works_in_time():
    found = co.discover(Sandbox(), ["MX", "GB", "PH", "CN", "TW", "VE"], try_conversions=True)
    plan = bk.plan(HOLDER, CLAIMS, found, {"handover_date": "2027-06-01"}, today=TODAY)
    rows = bt.choose_slice(plan)
    assert [r["country"] for r in rows] == ["MX", "TW", "PH", "GB"]             # largest first; China has no demonstration owner
    assert rows[0]["amount_is"].startswith("the claim at the ninetieth percentile") and rows[0]["claim_usd"] == "40000.00"
    assert rows[1]["method"] == "SWIFT" and rows[1]["currency"] == "USD" and rows[2]["claim_usd"] == "500.00"
    near = bk.plan(HOLDER, CLAIMS, found, {"handover_date": "2026-12-17"}, today=TODAY)
    assert "TW" not in [r["country"] for r in bt.choose_slice(near)]            # too close for SWIFT: not in the slice


def test_the_example_bank_details_are_invented_people_with_two_accounts_each():
    assert set(bt.EXAMPLE_OWNERS) >= {"MX", "PH", "JP", "GB", "DE", "CA", "IN", "AU", "TW"}
    for country, owner in bt.EXAMPLE_OWNERS.items():
        currency = "USD" if country == "TW" else co.currency_of(country)
        first = bt.example_beneficiary(country, currency, "LOCAL")
        second = bt.example_beneficiary(country, currency, "LOCAL", corrected=True)
        assert bt.account_tail(first) != bt.account_tail(second) and first["beneficiary"]["first_name"] == owner["first"]
        assert first["beneficiary"]["bank_details"]["account_name"] == f"{owner['first']} {owner['last']}"
    assert awx.is_valid_clabe(bt.EXAMPLE_OWNERS["MX"]["bank"]["account_number"])
    assert awx.is_valid_clabe(bt.EXAMPLE_OWNERS["MX"]["corrected"]["account_number"])


# ---- the routes ------------------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, fake):
    books = tmp_path / "books.parquet"
    bk.write([(HOLDER["name"], c, cents / 100, t) for c, cents, t in CLAIMS], books)
    corridors = tmp_path / "corridors.json"
    co.save(co.discover(Sandbox(), ["MX", "GB", "PH", "CN", "TW", "VE"], try_conversions=True), corridors)

    def factory():
        client = make_client(fake)
        return client, awx.SandboxSimulator(client)

    app = create_app(db_path=make_register(tmp_path), totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no",
                     claims_dir=tmp_path / "claims", books_path=books, corridors_path=corridors, payer_key="k",
                     airwallex_factory=factory, payout_pause=0.01)
    with TestClient(app) as client:
        yield client, app


def test_a_batch_is_made_approved_and_run_through_the_holders_routes(api, fake):
    client, app = api
    key = {"X-Payer-Key": "k"}
    assert client.post("/api/payer/batches", json={"holder": HOLDER["name"]}).status_code == 401       # the holder's key
    made = client.post("/api/payer/batches", json={"holder": HOLDER["name"], "refuse": []}, headers=key)
    assert made.status_code == 201
    view = made.json()
    assert view["state_words"].startswith("Planned") and view["payments"] == 4 and not fake.deposits
    assert fake.count("POST", "/api/v1/beneficiaries/validate") == 4         # the example details were checked against the schema
    batch_id = view["batch_id"]
    assert client.get(f"/api/payer/batches/{batch_id}").status_code == 401
    assert client.get("/api/payer/batches", headers=key).json()["batches"][0]["batch_id"] == batch_id
    assert client.post(f"/api/payer/batches/{batch_id}/approve", headers=key).status_code == 200
    app.state.batches.join(batch_id)
    done = client.get(f"/api/payer/batches/{batch_id}", headers=key).json()
    assert done["state_words"] == "Every payment is paid" and done["paid"] == 4 and done["reconciliation"]["balanced"]
    assert done["api_calls"] > 20 and len(fake.deposits) == 1 and len(fake.transfers) == 4
    assert client.post(f"/api/payer/batches/{batch_id}/approve", headers=key).status_code == 409       # approved once
    assert client.get("/api/payer/batches/nosuchbatch", headers=key).status_code == 404
    assert client.post(f"/api/payer/batches/{batch_id}/items/1/account", headers=key).status_code == 409   # nothing was refused


def test_a_refusal_in_a_batch_is_put_right_through_the_routes(api, fake):
    client, app = api
    key = {"X-Payer-Key": "k"}
    view = client.post("/api/payer/batches", json={"holder": HOLDER["name"]}, headers=key).json()     # by default: largest and smallest refused
    batch_id = view["batch_id"]
    staged = [i["n"] for i in view["items"] if i["staged"]]
    assert len(staged) == 2
    client.post(f"/api/payer/batches/{batch_id}/approve", headers=key)
    app.state.batches.join(batch_id)
    now = client.get(f"/api/payer/batches/{batch_id}", headers=key).json()
    assert now["waiting_for_people"] == staged and now["paid"] == 2
    for n in staged:
        assert client.post(f"/api/payer/batches/{batch_id}/items/{n}/approve", headers=key).status_code == 409    # account first
        client.post(f"/api/payer/batches/{batch_id}/items/{n}/account", headers=key)
        client.post(f"/api/payer/batches/{batch_id}/items/{n}/approve", headers=key)
        app.state.batches.join(batch_id)
        item = next(i for i in client.get(f"/api/payer/batches/{batch_id}", headers=key).json()["items"] if i["n"] == n)
        if item["needs"] == ["claimant"]:
            client.post(f"/api/payer/batches/{batch_id}/items/{n}/agree", headers=key)
            app.state.batches.join(batch_id)
    done = client.get(f"/api/payer/batches/{batch_id}", headers=key).json()
    assert done["state_words"] == "Every payment is paid" and done["reconciliation"]["balanced"] and len(fake.transfers) == 6
    assert done["costs"]["actual"]["transfers"] == 6 and done["costs"]["planned"]["transfers"] == 4


def test_a_batch_cannot_be_made_without_the_sandbox_keys(tmp_path):
    books = tmp_path / "books.parquet"
    bk.write([(HOLDER["name"], c, cents / 100, t) for c, cents, t in CLAIMS], books)
    corridors = tmp_path / "corridors.json"
    co.save(co.discover(Sandbox(), ["MX", "GB", "PH", "CN", "TW", "VE"], try_conversions=True), corridors)
    app = create_app(db_path=make_register(tmp_path), totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no",
                     claims_dir=tmp_path / "claims", books_path=books, corridors_path=corridors, payer_key="k")
    with TestClient(app) as client:
        answer = client.post("/api/payer/batches", json={"holder": HOLDER["name"]}, headers={"X-Payer-Key": "k"})
        assert answer.status_code == 503 and "sandbox keys" in answer.json()["detail"]
